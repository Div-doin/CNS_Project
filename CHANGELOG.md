# Project changes

## 16 November 2026

- Cover selection and the CLI now accept raster formats readable by installed
  Pillow decoders, including JPEG, WebP, GIF, BMP, TIFF, AVIF, ICO, JPEG 2000,
  PPM, TGA, PCX and QOI, in addition to PNG.
- Added HEIC/HEIF through the pillow-heif dependency.
- Animated images and multipage files use the first frame/page, with an explicit
  indication in the interface. EXIF orientation is applied before embedding.
- Added normalised PNG previews for formats browsers cannot display directly.
- Outputs always use PNG, and the CLI rejects misleading output extensions.
- Extraction can read other raster formats when they retain the embedded pixels.
- Preserved compatibility with the original CNS1 packet and supplied PNG samples.
- Expanded tests cover formats, orientation, transparency, previews, frame
  selection, and exact message recovery after supported lossless conversions.

The existing DOCX report, PPT and numbered screenshots describe the original
PNG-only input release. Current input behaviour is documented in README.md and
VIVA_GUIDE.md. The embedding algorithm and output format are unchanged.
