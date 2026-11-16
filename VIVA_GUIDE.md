# Explanation and demonstration guide

## A one minute introduction

My project hides a UTF-8 text message inside a PNG image using least significant
bit steganography. It changes only the last bit of each red, green and blue
sample. The resulting image looks very similar to the cover. The decoder reads
the same channel bits and recovers the text. A format header stores the message
length and a CRC32 checksum so the app can validate its own message format and
detect accidental payload corruption. It runs locally in Python with Pillow and
a browser interface. It demonstrates steganography from Module 1 of CNS.

## A five minute demonstration

1. Open the app and select **Try a sample**. Mention the 720 by 480 pixel size.
2. Type your own short message. Point out that the counter measures UTF-8 bytes.
3. Click **Hide message and create PNG**. Explain the 14-byte header and three
   carrier bits per pixel. Point out the number of actual changed RGB values.
4. Expand the original/output comparison. Show that an RGB value such as 52 can
   become 53 to store a 1. Explain the bitwise operation `(value & 254) | bit`.
5. Download the PNG. Select it on **Extract a message**, then recover the text.
6. Try an ordinary PNG and the supplied damaged message. Explain the different
   errors: no matching format versus a recognised packet with a failed checksum.
7. Finish with limitations and one future improvement, such as encrypting the
   payload before embedding it.

## Questions to practise

**What is steganography?** It conceals information inside a carrier such as an
image. Here the carrier is its pixel samples. Encryption instead transforms the
message using a key. Both can be combined, but this version only hides text.

**Why change the least significant bit?** Changing that bit changes an 8-bit
sample by at most 1. Changing higher bits would cause larger colour differences.

**Does each embedded bit change a sample?** No. If its last bit already equals
the message bit, the value stays unchanged. For the supplied 77-byte example,
728 bits are stored and 357 sample values change.

**Why PNG?** Its lossless encoding preserves the pixel values used by the decoder.
JPEG uses lossy compression, which can alter the embedded bits. Renaming a JPEG
to `.png` does not convert it and the app checks the actual image format.

**How much text fits?** There are three carrier bits per pixel. Divide total
carrier bits by eight, discard any fractional byte, then reserve 14 bytes for the
header. A 720 by 480 image holds 129,586 message bytes.

**Why store length?** The decoder must know how many bytes belong to the message.
Length-based framing allows newlines, null characters and delimiter-like text.

**Why UTF-8?** It represents Unicode text. One emoji may require four bytes, so
capacity must use encoded byte length instead of the number of characters.

**What is the header?** `CNS1` magic, version, reserved flags, a four-byte payload
length and a four-byte CRC32. Integers use big-endian network byte order.

**How does extraction work?** Read LSBs in the same row-major RGB order. Rebuild
bytes, validate the header and length, read the payload, check CRC32, and decode
UTF-8. The original cover image is not required.

**Does CRC32 make the message secure?** No. It detects many accidental changes.
An intentional attacker can alter the payload and recompute the checksum.

**What happens to transparency?** RGBA alpha samples remain unchanged and are
excluded from embedding and image quality calculations.

**What do MSE and PSNR mean?** MSE is average squared difference across all
normalised RGB samples. Here changed samples differ by exactly 1, so MSE equals
the count of changed samples divided by the total RGB samples. PSNR compares
255 squared with MSE on a logarithmic scale. Larger PSNR means smaller pixel
error; it does not prove resistance to hidden-message detection.

**Can image editing go undetected?** Yes. Edits outside the packet bits need not
affect the payload. The checksum verifies recovered text, not the entire image.

**What is the time complexity?** Reading and saving the image scales with its
pixel count. Embedding/extraction scales with the number of packet bits. Overall
time is O(P + B), and memory is O(P + B), where P is pixel count and B is packet
bytes. Compression costs depend on the image and PNG encoder.

**Which part did Python implement?** All image validation, capacity checks,
bitwise embedding, framing, extraction and measurements. HTML/CSS/JavaScript
provide the browser screens and send images to the Python process on loopback.

**What are the limitations?** Sequential LSB embedding is easy to recover when
the method is known. The message has no encryption or authentication. Changes
to carrier pixels can damage it. File size and pixel limits bound resource use.

**What would you improve?** Authenticated encryption before embedding, a properly
managed key, keyed placement, and testing against statistical steganalysis.
These are future work and are not implemented in the current version.

## Before submission

- Add your name, USN, institution, department and guide to the report and slides.
- Read `steganography.py` and be able to explain `encode`, `decode` and the header.
- Practise using your own PNG and message rather than only the bundled sample.
- Keep an unmodified encoded PNG for the live demo and a spare local copy.
- Run the tests on the evaluation computer before the demonstration.
