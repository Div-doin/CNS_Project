"""Image text steganography using one least significant bit per RGB channel.

The format is intentionally small and documented for a CNS mini project.
Pillow-compatible raster inputs are normalised to RGB/RGBA. Output is lossless
PNG so the embedded bits survive. Text is concealed, not encrypted.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import math
import struct
import time
import warnings
import zlib

from PIL import Image, ImageOps, UnidentifiedImageError

try:
    from pillow_heif import register_heif_opener
except ImportError:
    HEIF_AVAILABLE = False
else:
    register_heif_opener(thumbnails=False)
    HEIF_AVAILABLE = True


MAGIC = b"CNS1"
VERSION = 1
# Network byte order: magic, version, flags, payload byte length, CRC32.
HEADER = struct.Struct(">4sBBII")
MAX_PIXELS = 8_000_000
MAX_FILE_BYTES = 12 * 1024 * 1024


class SteganographyError(ValueError):
    """An expected validation error suitable for display to the user."""


@dataclass
class EncodingResult:
    png: bytes
    metrics: dict


def load_image(data: bytes) -> Image.Image:
    """Decode the first raster frame, orient it, and normalise colour.

    Identify files by their bytes, not their suffix or browser MIME type.
    Document/vector formats requiring external renderers are excluded.
    """
    if not data or len(data) > MAX_FILE_BYTES:
        raise SteganographyError("Choose an image no larger than 12 MiB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                source_format = source.format or "Unknown"
                if source_format in {"EPS", "PDF", "WMF", "MPEG"}:
                    raise SteganographyError("Choose a raster image such as JPG, PNG, WebP, GIF, BMP, TIFF, AVIF or HEIC.")
                if source.width * source.height > MAX_PIXELS:
                    raise SteganographyError("Choose an image with at most 8 million pixels.")
                frames = getattr(source, "n_frames", 1)
                source.seek(0)
                oriented = ImageOps.exif_transpose(source)
                mode = "RGBA" if "A" in oriented.getbands() or "transparency" in oriented.info else "RGB"
                image = oriented.convert(mode)
                image.info["source_format"] = source_format
                image.info["source_frames"] = frames
                return image
    except SteganographyError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, EOFError,
            NotImplementedError, ImportError, struct.error,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise SteganographyError(
            "This image cannot be read. It may be damaged or need an unavailable decoder. "
            "Try JPG, PNG, WebP, GIF, BMP, TIFF, AVIF or HEIC. For HEIC/HEIF, install the updated requirements."
        ) from exc


def load_png(data: bytes) -> Image.Image:
    """Compatibility entry point for the original PNG-only engine callers."""
    return load_image(data)


def capacity(image: Image.Image) -> int:
    """Maximum UTF-8 payload bytes after the 14-byte header."""
    return max(0, (image.width * image.height * 3) // 8 - HEADER.size)


def inspect_image(data: bytes, *, include_preview: bool = False) -> dict:
    image = load_image(data)
    info = {"width": image.width, "height": image.height, "mode": image.mode,
            "capacity_bytes": capacity(image), "header_bytes": HEADER.size,
            "file_bytes": len(data), "source_format": image.info["source_format"],
            "source_frames": image.info["source_frames"],
            "first_frame_only": image.info["source_frames"] > 1,
            "output_format": "PNG"}
    if include_preview:
        # Browsers cannot directly display every input format (for example TIFF
        # and HEIC). A small PNG preview also matches normalised orientation.
        preview = image.copy()
        preview.thumbnail((960, 640))
        buffer = BytesIO()
        preview.save(buffer, format="PNG")
        info["preview_png"] = buffer.getvalue()
    return info


def _channel_index(bit_index: int, channels: int) -> int:
    # Skip every alpha byte. Alpha does not carry message bits.
    return (bit_index // 3) * channels + bit_index % 3


def _read_bytes(raw: bytes, channels: int, count: int, start_bit: int = 0) -> bytes:
    result = bytearray(count)
    for byte_index in range(count):
        value = 0
        for offset in range(8):
            index = _channel_index(start_bit + byte_index * 8 + offset, channels)
            value = (value << 1) | (raw[index] & 1)
        result[byte_index] = value
    return bytes(result)


def encode(data: bytes, message: str) -> EncodingResult:
    started = time.perf_counter()
    if not isinstance(message, str) or not message:
        raise SteganographyError("Enter a message before hiding it.")
    try:
        payload = message.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise SteganographyError("The message contains an invalid text character.") from exc
    image = load_image(data)
    available = capacity(image)
    if len(payload) > available:
        raise SteganographyError(
            f"Your message needs {len(payload):,} bytes, but this image holds {available:,}. "
            "Use a larger image or shorten the message."
        )
    checksum = zlib.crc32(payload)
    packet = HEADER.pack(MAGIC, VERSION, 0, len(payload), checksum) + payload
    original = image.tobytes()
    modified = bytearray(original)
    channels = len(image.getbands())
    changed = 0
    samples = []
    for byte_index, value in enumerate(packet):
        for offset in range(8):
            bit_index = byte_index * 8 + offset
            index = _channel_index(bit_index, channels)
            bit = (value >> (7 - offset)) & 1
            before = modified[index]
            after = (before & 0xFE) | bit
            modified[index] = after
            changed += before != after
            if bit_index < 8:
                samples.append({"channel": "RGB"[bit_index % 3],
                                "pixel": bit_index // 3 + 1,
                                "before": before, "after": after, "bit": bit})
    encoded = Image.frombytes(image.mode, image.size, bytes(modified))
    output = BytesIO()
    # Write fresh PNG pixels only. Do not copy source text or private metadata.
    encoded.save(output, format="PNG")
    total_channels = image.width * image.height * 3
    mse = changed / total_channels  # Each changed colour value differs by exactly 1.
    psnr = round(10 * math.log10(255 ** 2 / mse), 2) if mse else None
    png = output.getvalue()
    if len(png) > MAX_FILE_BYTES:
        raise SteganographyError("The encoded PNG would exceed 12 MiB. Choose a smaller cover image.")
    return EncodingResult(png, {
        "width": image.width, "height": image.height, "mode": image.mode,
        "source_format": image.info["source_format"], "output_format": "PNG",
        "source_frames": image.info["source_frames"],
        "first_frame_only": image.info["source_frames"] > 1,
        "message_bytes": len(payload), "message_characters": len(message),
        "capacity_bytes": available, "header_bytes": HEADER.size,
        "embedded_bits": len(packet) * 8, "changed_channels": changed,
        "total_rgb_channels": total_channels,
        "changed_percent": round(100 * changed / total_channels, 6),
        "mse": mse, "psnr_db": psnr,
        "encode_ms": round((time.perf_counter() - started) * 1000, 2),
        "output_bytes": len(png), "checksum": f"{checksum:08X}",
        "samples": samples,
    })


def decode(data: bytes) -> dict:
    started = time.perf_counter()
    image = load_image(data)
    if image.width * image.height * 3 < HEADER.size * 8:
        raise SteganographyError("No supported hidden message was found.")
    raw = image.tobytes()
    channels = len(image.getbands())
    magic, version, flags, length, expected_crc = HEADER.unpack(
        _read_bytes(raw, channels, HEADER.size)
    )
    if magic != MAGIC:
        raise SteganographyError("No supported hidden message was found.")
    if version != VERSION or flags != 0:
        raise SteganographyError("This hidden message uses an unsupported format version.")
    if length == 0 or length > capacity(image):
        raise SteganographyError("The hidden message header is damaged or has an invalid length.")
    payload = _read_bytes(raw, channels, length, HEADER.size * 8)
    if zlib.crc32(payload) != expected_crc:
        raise SteganographyError("The message checksum does not match. The image may have been edited or damaged.")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SteganographyError("The hidden message is not valid UTF-8 text.") from exc
    return {"message": text, "message_bytes": length, "message_characters": len(text),
            "checksum": f"{expected_crc:08X}", "checksum_valid": True,
            "decode_ms": round((time.perf_counter() - started) * 1000, 2)}
