# Image based secret message hiding and retrieval using LSB steganography

A Cryptography and Network Security mini project for Module 1. A local Python
application accepts many raster image formats, hides UTF-8 text in their decoded
pixels, and saves a new lossless PNG without changing the original file.
It includes a browser interface, a command-line interface, source
code, tests, sample images, a report, execution screenshots and a presentation.

## Start on Windows

1. Extract the complete project ZIP into a folder.
2. Double-click **Start_Project.bat**.
3. Keep the console window open. Your browser opens at
   **http://127.0.0.1:8765**.
4. Click **Try a sample**, enter your message, then click **Hide message and create PNG**.
5. Click **Download PNG** to save the actual output.
6. Click **Test extraction**, or select that saved PNG on the extraction tab.

The launcher uses Python's Windows launcher and creates a local `.venv` if
available. Its first setup needs internet to install Pillow and the HEIC/HEIF decoder.
Run the launcher again after updating an older copy to install the new decoder.
When the Windows
Python launcher is absent, it also checks for an existing Codex bundled Python
that already contains Pillow. It does not install Python itself or change system settings.

If port 8765 is already in use, stop the existing copy or use the manual command
`python app.py --port 8766`.

## Manual setup on Windows macOS or Linux

Requirements: Python 3.10 or newer, Pillow, pillow-heif, and a modern browser.

```text
python -m venv .venv
```

Activate the environment:

```text
Windows:       .venv\Scripts\activate
macOS/Linux:   source .venv/bin/activate
```

```text
python -m pip install -r requirements.txt
python app.py
```

On some systems use `python3` instead of `python`. Once dependencies are installed,
normal operation needs no internet. Press Ctrl+C in the app's console to stop.
The server binds only to the computer's loopback address. It is a classroom
local application, not an internet hosting service.

## Optional command line

```text
python cli.py inspect samples/sample_cover.png
python cli.py hide samples/sample_cover.png my_encoded.png --message "Hello CNS"
python cli.py hide photo.jpg photo_encoded.png --message "A message in my photo"
python cli.py extract my_encoded.png
python cli.py extract my_encoded.png --output recovered.txt
```

For longer text use `--message-file my_message.txt` instead of `--message`.
CLI output files must be new files: existing files are never overwritten.
The `hide` output filename must end in `.png`, regardless of the source format.

## Supported images

Input detection uses the actual file contents, not the filename extension.
Common supported inputs include PNG, JPEG/JPG/JFIF, WebP, GIF, BMP, TIFF,
AVIF, HEIC/HEIF, ICO, JPEG 2000, PPM/PGM/PBM, TGA, PCX and QOI.
Other raster inputs work when their installed Pillow decoder can read them,
including flattened PSD images. Support depends on installed codecs; this does
not mean every image format in existence. SVG, PDF, EPS and camera RAW files
requiring a separate renderer or decoder are outside this version's scope.

- HEIC/HEIF uses `pillow-heif`, included in `requirements.txt`.
- Animated GIF/APNG and multipage TIFF/HEIF inputs use only the first frame or
  page. The interface explicitly identifies this. Output is a single still PNG.
- Phone-photo EXIF orientation is applied before embedding.
- The server provides a small PNG preview so TIFF and HEIC also display in a
  browser that cannot display the source format directly.
- **Encoded output always stays PNG.** JPEG, GIF palette conversion and lossy
  WebP/AVIF/HEIC re-encoding can alter bits and destroy the message.
- Extraction accepts readable raster inputs. It succeeds only if their RGB
  values retain the embedded packet. The original encoded PNG is recommended.
  Lossless BMP, TIFF or WebP conversions can also retain the payload.

The DOCX report, PPT and numbered execution screenshots document the initial
PNG-only version. This README and `CHANGELOG.md` describe the broader input
support added on 16 November 2026. The LSB packet format and PNG output remain
compatible with the original sample images.

## What to demonstrate

1. Load `samples/sample_cover.jpg` (or the original PNG) and hide your own message.
2. Explain the UTF-8 byte counter and available capacity.
3. Show the output, quality measurements and pixel-change table.
4. Download the PNG, then load it again on the extraction tab.
5. Recover the exact text and show its matching CRC32 checksum.
6. Try `samples/sample_cover.png` directly in extraction: no supported message.
7. Try `samples/damaged_message.png`: checksum mismatch.
8. Try `samples/tiny_cover.png` with an oversized message: capacity validation.

Use `VIVA_GUIDE.md` to understand the algorithm and practise the explanation.
Add your name, USN, institution and guide to the report and PPT before submission.

## Source map

| File | Purpose |
|---|---|
| `steganography.py` | Image loading, normalisation, previews, capacity, LSB embedding, extraction and measurements |
| `app.py` | Local HTTP server and API routes |
| `cli.py` | Optional command-line operations |
| `web/index.html` | Browser interface structure |
| `web/style.css` | Responsive visual layout |
| `web/app.js` | Previews, UTF-8 counter, API calls and downloads |
| `tests/test_project.py` | Engine and HTTP integration tests |
| `samples/` | Reproducible cover, encoded output and negative examples |
| `screenshots/` | Actual browser execution screenshots |
| `Project_Report.docx` | Editable academic report |
| `Project_Presentation.pptx` | Editable presentation with speaker notes |

## Packet format

The application writes one least significant bit into each R, G and B channel,
in row-major pixel order. It skips alpha. Each byte is stored most significant
bit first. The 14-byte header is followed immediately by the UTF-8 message.

| Header field | Size | Meaning |
|---|---:|---|
| Magic | 4 bytes | ASCII `CNS1` |
| Version | 1 byte | `1` |
| Flags | 1 byte | `0`, reserved for future use |
| Length | 4 bytes | Unsigned UTF-8 payload length in network byte order |
| CRC32 | 4 bytes | Unsigned CRC32 of the payload in network byte order |

Capacity in bytes is `max(0, floor(width * height * 3 / 8) - 14)`.
A 720 by 480 image holds 129,586 message bytes. Multibyte Unicode characters
consume more than one byte, so character count and byte count can differ.

## Limits and interpretation

- Readable raster inputs are accepted and only the first frame or page is used.
  Maximum uploaded size is 12 MiB and maximum first-frame image area is 8 million
  pixels. PNG outputs larger than 12 MiB are rejected too.
- The engine normalises source images to 8-bit RGB or RGBA. It preserves
  transparency in RGBA and skips its alpha channel. It creates a fresh PNG
  without copying source metadata. Quality measurements compare these normalised
  colour samples with the output, rather than metadata or compressed file bytes.
- LSB embedding conceals text. It provides no encryption, password protection,
  sender authentication, or resistance to steganalysis.
- CRC32 detects many accidental changes. It is not a cryptographic authenticity
  check and an intentional editor can recompute it. Changes outside the stored
  packet may leave the hidden text unaffected.
- Editing, resizing, screenshotting or JPEG conversion can damage the message.
  Copy the actual output PNG without modifying its pixel values.
- High PSNR describes small pixel error. It does not establish secure concealment.
- The app processes images in memory and does not save uploads on the server.
  Browser previews and downloaded files remain available on your computer.

## Run the tests

```text
python -m unittest discover -s tests -v
```

All 32 test methods passed for this update. The suite covers Unicode, exact capacity, transparent and palette images,
multiple input formats including HEIC, first-frame handling, EXIF orientation,
browser previews, lossless carrier conversion, unsupported input, packet damage,
invalid lengths, independent pixel measurements, CLI and HTTP round trips, and
local-origin restrictions. Local HTTP
tests need permission to make loopback connections on the computer.

## References

- Pillow image formats: https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html
- HEIC/HEIF plugin: https://pillow-heif.readthedocs.io/en/stable/pillow-plugin.html
- Python binary packing: https://docs.python.org/3/library/struct.html
- Python CRC32: https://docs.python.org/3/library/zlib.html#zlib.crc32
- PNG specification: https://www.w3.org/TR/png-3/
- Prescribed CNS syllabus BCS703, Module 1, supplied with the assignment.
