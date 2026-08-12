"""
rigol_screen.py

Captures the Rigol DS1054Z screen display and saves it as a PNG.
Can be imported by other scripts or run standalone.

Usage (imported):
    from rigol_screen import save_screen
    path = save_screen(scope, "my_screen.png")

Usage (standalone):
    python3 rigol_screen.py --ip 169.254.123.183 --out screen.png

Also converts any previously saved .bin screen file:
    python3 rigol_screen.py --bin 20260811_rigol_screen.bin

Requirements:
    pip install ds1054z python-vxi11 pillow
"""

import io
import argparse
from pathlib import Path
from PIL import Image, ImageFile

# Allow PIL to open truncated PNG/image files.
# The DS1054Z sends a valid but truncated PNG stream —
# PIL rejects these by default without this flag.
ImageFile.LOAD_TRUNCATED_IMAGES = True


# ─────────────────────────────────────────────
# CORE: Save scope screen to PNG
# ─────────────────────────────────────────────

def save_screen(scope, path: str) -> str | None:
    """
    Captures the DS1054Z display bitmap via LAN and saves as PNG.

    The scope sends a truncated PNG stream via display_data.
    PIL's LOAD_TRUNCATED_IMAGES flag allows it to decode
    the partial stream correctly.

    Parameters
    ----------
    scope : ds1054z.DS1054Z
        Connected scope instance.
    path : str
        Destination file path (should end in .png).

    Returns
    -------
    str | None
        The path the file was saved to, or None on failure.
    """
    print(f"  Capturing scope screen...", end="", flush=True)

    try:
        raw_bytes = scope.display_data

        img = Image.open(io.BytesIO(raw_bytes))
        img.save(path)

        print(f" saved → {path}  "
              f"({img.size[0]}×{img.size[1]} px, {len(raw_bytes):,} bytes)")
        return path

    except Exception as e:
        # Never let screen capture abort a waveform capture run
        fallback = str(path).replace(".png", ".bin")
        print(f"\n  ⚠️  Screen capture failed: {e}")
        try:
            Path(fallback).write_bytes(raw_bytes)
            print(f"  ⚠️  Raw bytes saved → {fallback} "
                  f"({len(raw_bytes):,} bytes)")
        except Exception as e2:
            print(f"  ❌ Could not save fallback: {e2}")
            return None
        return fallback


# ─────────────────────────────────────────────
# CORE: Convert a saved .bin file to PNG
# ─────────────────────────────────────────────

def convert_bin_to_png(bin_path: str | Path) -> str | None:
    """
    Converts a previously saved raw .bin screen capture to PNG.

    Parameters
    ----------
    bin_path : path to the .bin file

    Returns
    -------
    str | None
        Path to the saved PNG, or None on failure.
    """
    bin_path = Path(bin_path)
    png_path = bin_path.with_suffix(".png")

    print(f"Converting {bin_path.name} → {png_path.name}...")

    try:
        raw_bytes = bin_path.read_bytes()
        img       = Image.open(io.BytesIO(raw_bytes))
        img.save(png_path)
        print(f"✅ Saved → {png_path}  "
              f"({img.size[0]}×{img.size[1]} px)")
        return str(png_path)

    except Exception as e:
        print(f"❌ Conversion failed: {e}")
        return None


# ─────────────────────────────────────────────
# STANDALONE ENTRY POINT
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Capture or convert a Rigol DS1054Z screen image."
    )
    parser.add_argument(
        "--ip",
        type=str,
        default=None,
        help="Scope IP address for live capture (e.g. 169.254.123.183)"
    )
    parser.add_argument(
        "--out",
        type=str,
        default="rigol_screen.png",
        help="Output PNG filename (default: rigol_screen.png)"
    )
    parser.add_argument(
        "--bin",
        type=str,
        default=None,
        help="Convert a previously saved .bin file to PNG"
    )
    args = parser.parse_args()

    # ── Convert existing .bin ─────────────────
    if args.bin:
        result = convert_bin_to_png(args.bin)
        if result:
            print(f"✅ Done: {result}")
        return

    # ── Live capture ──────────────────────────
    if args.ip is None:
        # Fall back to shared config IP
        try:
            from rigol_common import SCOPE_IP
            print(f"No --ip given — using SCOPE_IP from rigol_common.py: {SCOPE_IP}")
            args.ip = SCOPE_IP
        except ImportError:
            # rigol_common not available — try .bin conversion instead
            bins = sorted(
                Path(".").glob("*_rigol_screen.bin"),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )
            if bins:
                print(f"No --ip given. Converting most recent .bin: {bins[0]}")
                convert_bin_to_png(bins[0])
            else:
                print("No --ip or --bin provided and no .bin files found.")
                print("Set SCOPE_IP in rigol_common.py or use --ip 169.254.x.x")
            return

    try:
        from ds1054z import DS1054Z
        print(f"Connecting to DS1054Z at {args.ip}...")
        scope  = DS1054Z(args.ip)
        print(f"✅ Connected: {scope.idn}")
        result = save_screen(scope, args.out)
        if result:
            print(f"✅ Done: {result}")
    except ImportError:
        print("❌ ds1054z not installed: pip install ds1054z python-vxi11")
    except Exception as e:
        print(f"❌ Failed: {e}")


if __name__ == "__main__":
    main()