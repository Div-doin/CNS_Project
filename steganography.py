"""Lossless PNG text steganography using one least significant bit per RGB channel.

The format is intentionally small and documented for a CNS mini project.
It conceals UTF-8 text; it does not encrypt or authenticate the text.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import math
import struct
import time
import warnings
import zlib

from PIL import Image, UnidentifiedImageError


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


def load_png(data: bytes) -> Image.Image:
    """Decode an actual, static PNG and normalise colour while keeping alpha."""
    if not data or len(data) > MAX_FILE_BYTES:
        raise SteganographyError("Choose a PNG no larger than 12 MiB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format != "PNG":
                    raise SteganographyError("Only PNG images are supported. Convert your image to PNG first.")
                if source.width * source.height > MAX_PIXELS:
                    raise SteganographyError("Choose an image with at most 8 million pixels.")
                if getattr(source, "n_frames", 1) != 1:
                    raise SteganographyError("Animated PNGs are not supported. Choose a still image.")
                mode = "RGBA" if "A" in source.getbands() or "transparency" in source.info else "RGB"
                return source.convert(mode)
    except SteganographyError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise SteganographyError("This PNG cannot be read. Choose a valid, undamaged image.") from exc


def capacity(image: Image.Image) -> int:
    """Maximum UTF-8 payload bytes after the 14-byte header."""
    return max(0, (image.width * image.height * 3) // 8 - HEADER.size)


def inspect_image(data: bytes) -> dict:
    image = load_png(data)
    return {"width": image.width, "height": image.height, "mode": image.mode,
            "capacity_bytes": capacity(image), "header_bytes": HEADER.size,
            "file_bytes": len(data)}


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
    image = load_png(data)
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
    image = load_png(data)
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
