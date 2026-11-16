"""Optional command-line interface for the same tested steganography engine."""

import argparse
import json
from pathlib import Path
import sys

from steganography import SteganographyError, decode, encode, inspect_image


def main():
    parser = argparse.ArgumentParser(description="Hide and recover UTF-8 text in PNG pixels")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="Show PNG capacity")
    inspect.add_argument("image", type=Path)
    hide = commands.add_parser("hide", help="Save an encoded PNG to a new file")
    hide.add_argument("image", type=Path)
    hide.add_argument("output", type=Path)
    message = hide.add_mutually_exclusive_group(required=True)
    message.add_argument("--message")
    message.add_argument("--message-file", type=Path)
    extract = commands.add_parser("extract", help="Recover text from an encoded PNG")
    extract.add_argument("image", type=Path)
    extract.add_argument("--output", type=Path, help="Write UTF-8 text to a new file")
    args = parser.parse_args()
    try:
        data = args.image.read_bytes()
        if args.command == "inspect":
            print(json.dumps(inspect_image(data), indent=2))
        elif args.command == "hide":
            if args.message is not None:
                text = args.message
            else:
                # Preserve CRLF/LF exactly for a file-to-file round trip.
                with args.message_file.open("r", encoding="utf-8", newline="") as file:
                    text = file.read()
            result = encode(data, text)
            with args.output.open("xb") as file:
                file.write(result.png)
            print(f"Encoded PNG saved to {args.output}")
            print(json.dumps(result.metrics, indent=2))
        else:
            result = decode(data)
            if args.output:
                with args.output.open("x", encoding="utf-8", newline="") as file:
                    file.write(result["message"])
                print(f"Recovered text saved to {args.output}")
            else:
                if hasattr(sys.stdout, "reconfigure"):
                    sys.stdout.reconfigure(encoding="utf-8")
                print(result["message"])
    except (SteganographyError, OSError, UnicodeError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
