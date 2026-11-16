"""Run from the project directory: python -m unittest discover -s tests -v."""

import base64
from io import BytesIO
import json
import random
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zlib

from PIL import Image

from app import Handler, ThreadingHTTPServer, make_demo, process_action
from steganography import (HEADER, HEIF_AVAILABLE, MAX_FILE_BYTES, SteganographyError,
                          capacity, decode, encode, inspect_image, load_image, load_png)


def png(image):
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def patch_bytes(data, start, values):
    """Independent packet editing for negative tests, including alpha skipping."""
    image = load_png(data)
    raw = bytearray(image.tobytes())
    channels = len(image.getbands())
    for n, value in enumerate(values):
        for offset in range(8):
            bit = (start + n) * 8 + offset
            index = (bit // 3) * channels + bit % 3
            raw[index] = (raw[index] & 254) | ((value >> (7 - offset)) & 1)
    return png(Image.frombytes(image.mode, image.size, bytes(raw)))


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.cover = png(Image.new("RGB", (64, 48), (120, 151, 202)))

    def test_ascii_round_trip(self):
        message = "Meet me at the library at 4 PM.\nCNS mini project."
        self.assertEqual(decode(encode(self.cover, message).png)["message"], message)

    def test_unicode_whitespace_and_markup_preserved(self):
        for message in ["नमस्ते 🔐 café", "\n\t  ", "A\x00B", "<script>alert(1)</script>", "e\u0301", "中文 العربية"]:
            with self.subTest(message=message):
                result = encode(self.cover, message)
                self.assertEqual(decode(result.png)["message"], message)
                self.assertEqual(result.metrics["message_bytes"], len(message.encode()))

    def test_rgba_alpha_unchanged(self):
        image = Image.new("RGBA", (64, 48))
        image.putdata([(x % 256, (x * 3) % 256, 100, (x * 7) % 256) for x in range(64 * 48)])
        result = encode(png(image), "Transparent image 🔐")
        output = load_png(result.png)
        self.assertEqual(output.mode, "RGBA")
        self.assertEqual(output.getchannel("A").tobytes(), image.getchannel("A").tobytes())
        self.assertEqual(decode(result.png)["message"], "Transparent image 🔐")

    def test_grayscale_palette_and_grayscale_alpha(self):
        for mode, colour in [("L", 110), ("P", 0), ("LA", (128, 81))]:
            with self.subTest(mode=mode):
                image = Image.new(mode, (64, 48), colour)
                if mode == "P":
                    image.putpalette([i for i in range(256) for _ in range(3)])
                    image.info["transparency"] = 0
                result = encode(png(image), "Palette and grayscale")
                self.assertEqual(decode(result.png)["message"], "Palette and grayscale")
                if mode in {"P", "LA"}:
                    self.assertEqual(load_png(result.png).mode, "RGBA")

    def test_exact_capacity_and_oversize(self):
        available = inspect_image(self.cover)["capacity_bytes"]
        self.assertEqual(available, 64 * 48 * 3 // 8 - 14)
        text = "x" * available
        self.assertEqual(decode(encode(self.cover, text).png)["message"], text)
        with self.assertRaisesRegex(SteganographyError, "holds"):
            encode(self.cover, text + "x")

    def test_utf8_capacity_counts_bytes(self):
        cover = png(Image.new("RGB", (8, 8), (100, 100, 100)))
        self.assertEqual(inspect_image(cover)["capacity_bytes"], 10)
        self.assertEqual(decode(encode(cover, "🔐🔐").png)["message_bytes"], 8)
        with self.assertRaises(SteganographyError):
            encode(cover, "🔐🔐🔐")

    def test_empty_message_and_wrong_type(self):
        for message in ["", None, 123, [], {}]:
            with self.subTest(message=message):
                with self.assertRaises(SteganographyError):
                    encode(self.cover, message)

    def test_unencoded_and_tiny_images(self):
        for data in [self.cover, png(Image.new("RGB", (1, 1))), png(Image.new("RGB", (6, 6)))]:
            with self.subTest(size=len(data)):
                with self.assertRaisesRegex(SteganographyError, "No supported"):
                    decode(data)
        with self.assertRaises(SteganographyError):
            encode(png(Image.new("RGB", (1, 1))), "a")

    def test_invalid_file_rejected(self):
        for data in [b"", b"not an image", self.cover[:24], b'<svg xmlns="http://www.w3.org/2000/svg"/>']:
            with self.subTest(data_size=len(data)):
                with self.assertRaises(SteganographyError):
                    load_image(data)

    def test_animated_png_uses_first_frame(self):
        output = BytesIO()
        image = Image.new("RGB", (30, 30), "red")
        image.save(output, "PNG", save_all=True,
                   append_images=[Image.new("RGB", (30, 30), "blue")], duration=100, loop=0)
        info = inspect_image(output.getvalue())
        self.assertTrue(info["first_frame_only"])
        self.assertEqual(info["source_frames"], 2)
        result = encode(output.getvalue(), "First frame")
        self.assertEqual(decode(result.png)["message"], "First frame")
        with Image.open(BytesIO(result.png)) as saved:
            self.assertEqual(saved.format, "PNG")
            self.assertEqual(saved.n_frames, 1)

    def test_raster_input_formats_round_trip(self):
        formats = ["PNG", "JPEG", "BMP", "GIF", "TIFF", "WEBP", "PPM", "TGA",
                   "PCX", "ICO", "QOI", "JPEG2000", "AVIF"]
        image = Image.new("RGB", (64, 48), (37, 103, 182))
        for image_format in formats:
            with self.subTest(image_format=image_format):
                data = BytesIO()
                image.save(data, image_format)
                info = inspect_image(data.getvalue())
                self.assertEqual(info["source_format"], image_format)
                result = encode(data.getvalue(), f"Format {image_format}: नमस्ते 🔐")
                self.assertEqual(result.metrics["source_format"], image_format)
                self.assertEqual(result.metrics["output_format"], "PNG")
                self.assertEqual(decode(result.png)["message"], f"Format {image_format}: नमस्ते 🔐")
                with Image.open(BytesIO(result.png)) as saved:
                    self.assertEqual(saved.format, "PNG")

    @unittest.skipUnless(HEIF_AVAILABLE, "Install requirements.txt for HEIC/HEIF support")
    def test_heic_input_round_trip(self):
        data = BytesIO()
        Image.new("RGB", (64, 48), (60, 120, 190)).save(data, "HEIF")
        info = inspect_image(data.getvalue())
        self.assertEqual(info["source_format"], "HEIF")
        self.assertEqual(decode(encode(data.getvalue(), "HEIC photo 🔐").png)["message"], "HEIC photo 🔐")

    def test_animated_gif_and_multipage_tiff_use_first_frame(self):
        for image_format in ["GIF", "TIFF"]:
            with self.subTest(image_format=image_format):
                data = BytesIO()
                first = Image.new("RGB", (64, 48), "red")
                first.save(data, image_format, save_all=True,
                           append_images=[Image.new("RGB", (64, 48), "blue")])
                info = inspect_image(data.getvalue())
                self.assertEqual(info["source_frames"], 2)
                self.assertTrue(info["first_frame_only"])
                normalised = load_image(data.getvalue())
                self.assertEqual(normalised.getpixel((0, 0))[:3], (255, 0, 0))
                result = encode(data.getvalue(), "Animated first frame")
                self.assertTrue(result.metrics["first_frame_only"])
                self.assertEqual(decode(result.png)["message"], "Animated first frame")

    def test_exif_orientation_applied_before_embedding(self):
        source = Image.new("RGB", (64, 48), (51, 102, 153))
        exif = Image.Exif()
        exif[274] = 6  # Rotate 90 degrees clockwise for upright display.
        data = BytesIO()
        source.save(data, "JPEG", exif=exif)
        info = inspect_image(data.getvalue())
        self.assertEqual((info["width"], info["height"]), (48, 64))
        result = encode(data.getvalue(), "Upright photo")
        with Image.open(BytesIO(result.png)) as saved:
            self.assertEqual(saved.size, (48, 64))
            self.assertNotIn(274, saved.getexif())
        self.assertEqual(decode(result.png)["message"], "Upright photo")

    def test_lossless_carrier_conversion_still_extracts(self):
        packet = encode(self.cover, "Preserved RGB samples 🔐").png
        for image_format, options in [("BMP", {}), ("TIFF", {"compression": "tiff_lzw"}),
                                      ("WEBP", {"lossless": True})]:
            with self.subTest(image_format=image_format):
                output = BytesIO()
                load_image(packet).save(output, image_format, **options)
                self.assertEqual(decode(output.getvalue())["message"], "Preserved RGB samples 🔐")

    def test_normalised_preview_is_png_and_bounded(self):
        data = BytesIO()
        Image.new("RGB", (1500, 1000), (37, 103, 182)).save(data, "TIFF")
        info = inspect_image(data.getvalue(), include_preview=True)
        self.assertEqual(info["source_format"], "TIFF")
        with Image.open(BytesIO(info["preview_png"])) as preview:
            self.assertEqual(preview.format, "PNG")
            self.assertLessEqual(preview.width, 960)
            self.assertLessEqual(preview.height, 640)
        self.assertNotIn("preview_png", inspect_image(self.cover))

    def test_lossy_resave_cannot_be_claimed_to_preserve_message(self):
        result = encode(self.cover, "Do not resave this as JPEG")
        lossy = BytesIO()
        load_image(result.png).save(lossy, "JPEG", quality=40)
        with self.assertRaises(SteganographyError):
            decode(lossy.getvalue())

    def test_input_size_and_pixel_limits(self):
        with patch("steganography.MAX_PIXELS", 10):
            with self.assertRaisesRegex(SteganographyError, "million pixels"):
                load_png(self.cover)
        with patch("steganography.MAX_FILE_BYTES", 5):
            with self.assertRaises(SteganographyError):
                load_image(self.cover)

    def test_encoded_output_size_limit(self):
        with patch("steganography.MAX_FILE_BYTES", len(self.cover)):
            with self.assertRaisesRegex(SteganographyError, "encoded PNG would exceed"):
                encode(self.cover, "Message that changes the compressed image")

    def test_cli_round_trip_and_overwrite_protection(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=root / "tests") as folder:
            folder = Path(folder)
            cover = folder / "cover.png"
            output = folder / "encoded.png"
            text_file = folder / "message.txt"
            recovered = folder / "recovered.txt"
            cover.write_bytes(self.cover)
            text_file.write_text("CLI नमस्ते 🔐\nExact recovery", encoding="utf-8")
            base = [sys.executable, str(root / "cli.py")]
            def run(*args):
                return subprocess.run(base + [str(a) for a in args], capture_output=True, timeout=15)
            self.assertEqual(run("inspect", cover).returncode, 0)
            result = run("hide", cover, output, "--message-file", text_file)
            self.assertEqual(result.returncode, 0, result.stderr)
            saved_output = output.read_bytes()
            self.assertNotEqual(run("hide", cover, output, "--message", "overwrite").returncode, 0)
            self.assertEqual(output.read_bytes(), saved_output)
            self.assertEqual(run("extract", output, "--output", recovered).returncode, 0)
            self.assertEqual(recovered.read_bytes(), text_file.read_bytes())

    def test_cli_jpeg_input_and_non_png_output_guard(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=root / "tests") as folder:
            folder = Path(folder)
            cover, output = folder / "photo.jpg", folder / "photo_encoded.png"
            Image.new("RGB", (64, 48), (50, 100, 150)).save(cover, "JPEG")
            command = [sys.executable, str(root / "cli.py"), "hide", str(cover), str(output), "--message", "JPG input"]
            result = subprocess.run(command, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(decode(output.read_bytes())["message"], "JPG input")
            command[4] = str(folder / "bad_output.jpg")
            result = subprocess.run(command, capture_output=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b".png output filename", result.stderr)
            self.assertFalse((folder / "bad_output.jpg").exists())

    def test_crc_detects_damaged_payload(self):
        result = encode(self.cover, "Hello")
        damaged = patch_bytes(result.png, HEADER.size, b"J")
        with self.assertRaisesRegex(SteganographyError, "checksum"):
            decode(damaged)

    def test_invalid_header_version_flags_length_magic(self):
        data = encode(self.cover, "Hello").png
        for offset, replacement, expected in [
            (0, b"XXXX", "No supported"), (4, b"\x02", "unsupported"),
            (5, b"\x01", "unsupported"), (6, struct.pack(">I", 0), "invalid length"),
            (6, struct.pack(">I", 0xFFFFFFFF), "invalid length")]:
            with self.subTest(offset=offset, replacement=replacement):
                with self.assertRaisesRegex(SteganographyError, expected):
                    decode(patch_bytes(data, offset, replacement))

    def test_invalid_utf8_even_with_matching_crc(self):
        data = encode(self.cover, "A").png
        data = patch_bytes(data, HEADER.size, b"\xff")
        data = patch_bytes(data, 10, struct.pack(">I", zlib.crc32(b"\xff")))
        with self.assertRaisesRegex(SteganographyError, "UTF-8"):
            decode(data)

    def test_colour_delta_and_metrics_independently(self):
        original = load_png(self.cover)
        source_copy = bytes(self.cover)
        result = encode(self.cover, "Measurement test")
        output = load_png(result.png)
        differences = [abs(a - b) for a, b in zip(original.tobytes(), output.tobytes())]
        self.assertLessEqual(max(differences), 1)
        self.assertEqual(result.metrics["changed_channels"], sum(differences))
        self.assertEqual(result.metrics["embedded_bits"], (14 + len("Measurement test")) * 8)
        self.assertAlmostEqual(result.metrics["mse"], sum(d * d for d in differences) / len(differences))
        self.assertEqual(self.cover, source_copy)
        self.assertEqual(output.size, original.size)

    def test_random_images_and_messages(self):
        random_source = random.Random(703)
        for trial in range(8):
            width, height = random_source.randint(12, 60), random_source.randint(12, 60)
            image = Image.frombytes("RGB", (width, height), random_source.randbytes(width * height * 3))
            text = "".join(random_source.choice("Ab09 नमस्तेé") for _ in range(20))
            self.assertEqual(decode(encode(png(image), text).png)["message"], text)


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.image = base64.b64encode(make_demo()).decode()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join(timeout=3)

    def request(self, route, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        request_headers = {"Content-Type": "application/json", **(headers or {})}
        request = Request(self.url + route, data=data, headers=request_headers)
        try:
            with urlopen(request, timeout=10) as response:
                return response.status, response.headers, response.read()
        except HTTPError as error:
            return error.code, error.headers, error.read()

    def test_http_end_to_end(self):
        status, _, result = self.request("/api/hide", {"image": self.image, "message": "HTTP round trip 🔐"})
        self.assertEqual(status, 200)
        result = json.loads(result)
        status, _, extracted = self.request("/api/extract", {"image": result["image"]})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(extracted)["message"], "HTTP round trip 🔐")

    def test_http_jpeg_inspection_preview_and_encoding(self):
        data = BytesIO()
        Image.new("RGB", (64, 48), (60, 130, 190)).save(data, "JPEG")
        image = base64.b64encode(data.getvalue()).decode()
        status, _, body = self.request("/api/inspect", {"image": image})
        self.assertEqual(status, 200)
        info = json.loads(body)
        self.assertEqual(info["source_format"], "JPEG")
        with Image.open(BytesIO(base64.b64decode(info["preview"]))) as preview:
            self.assertEqual(preview.format, "PNG")
        status, _, body = self.request("/api/hide", {"image": image, "message": "Photo to PNG"})
        self.assertEqual(status, 200)
        result = json.loads(body)
        self.assertEqual(result["metrics"]["source_format"], "JPEG")
        status, _, body = self.request("/api/extract", {"image": result["image"]})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["message"], "Photo to PNG")

    def test_frontend_and_demo_routes(self):
        for route in ["/", "/style.css", "/app.js", "/api/demo"]:
            with self.subTest(route=route):
                status, headers, result = self.request(route)
                self.assertEqual(status, 200)
                self.assertTrue(result)
                self.assertEqual(headers["Cache-Control"], "no-store")
        status, _, _ = self.request("/../../app.py")
        self.assertEqual(status, 404)

    def test_error_and_invalid_base64(self):
        for body in [{}, {"image": "!!!!"}, {"image": self.image, "message": ""}, [], {"image": 42}]:
            with self.subTest(body_type=type(body).__name__):
                status, _, result = self.request("/api/hide", body)
                self.assertEqual(status, 400)
                self.assertIn("error", json.loads(result))

    def test_cross_origin_requests_rejected(self):
        for headers in [{"Origin": "https://example.com"}, {"Sec-Fetch-Site": "cross-site"}, {"Host": "example.com"}]:
            with self.subTest(headers=headers):
                status, _, _ = self.request("/api/inspect", {"image": self.image}, headers)
                self.assertEqual(status, 403)

    def test_wrong_content_type_and_malformed_json(self):
        status, _, _ = self.request("/api/inspect", {}, {"Content-Type": "text/plain"})
        self.assertEqual(status, 415)
        request = Request(self.url + "/api/inspect", data=b"{broken", headers={"Content-Type": "application/json"})
        with self.assertRaises(HTTPError) as raised:
            urlopen(request, timeout=5)
        self.assertEqual(raised.exception.code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
