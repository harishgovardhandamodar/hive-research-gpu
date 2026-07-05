#!/usr/bin/env python3
"""Build script for Hive Research Chrome Extension.

Creates a distributable ZIP file in dist/ and prints the SHA256 hash.
Usage:
    python3 build.py              # create extension zip
    python3 build.py --install    # create + print install instructions
"""

import argparse
import hashlib
import pathlib
import shutil
import zipfile


def build_extension(output_dir: str = "dist") -> str:
    src = pathlib.Path(__file__).resolve().parent
    dst = pathlib.Path(output_dir) / "hive-research-extension.zip"
    dst.parent.mkdir(parents=True, exist_ok=True)

    # Collect files
    files = []
    for f in src.rglob("*"):
        if not f.is_file():
            continue
        name = f.name
        # Skip dotfiles, readme, build script itself
        if name.startswith(".") or name in ("README.md", "build.py", "gen_icons.py"):
            continue
        files.append(f)

    # Create zip
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(files):
            arcname = str(f.relative_to(src.parent))
            zf.write(f, arcname=arcname)

    # SHA256
    sha = hashlib.sha256(dst.read_bytes()).hexdigest()
    size_kb = dst.stat().st_size / 1024

    print(f"Extension package: {dst}")
    print(f"Size: {size_kb:.1f} KB")
    print(f"SHA256: {sha}")

    return str(dst)


def print_instructions():
    print()
    print("To install:")
    print("  1. Open Chrome → chrome://extensions")
    print("  2. Enable Developer mode")
    print("  3. Drag and drop the .zip file onto the page")
    print()
    print("Or for development:")
    print("  1. Click 'Load unpacked'")
    print("  2. Select the chrome-extension/ directory")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build Hive Research Chrome Extension")
    parser.add_argument("--install", action="store_true", help="Show install instructions")
    args = parser.parse_args()

    build_extension()
    if args.install:
        print_instructions()
