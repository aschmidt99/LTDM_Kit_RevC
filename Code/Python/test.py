"""
probe_screen_bytes.py
Inspects the raw .bin screen capture to identify the format.
"""
from pathlib import Path
import struct

# ── Find the most recent .bin file ───────────
bins = sorted(Path(".").glob("*_rigol_screen.bin"),
              key=lambda f: f.stat().st_mtime, reverse=True)
if not bins:
    print("No .bin files found.")
    exit()

path = bins[0]
raw  = path.read_bytes()

print(f"File     : {path.name}")
print(f"Size     : {len(raw):,} bytes")
print(f"First 32 bytes (hex) : {raw[:32].hex(' ')}")
print(f"First 32 bytes (raw) : {raw[:32]!r}")
print()

# Check for known magic bytes
checks = {
    "BMP"  : (b'BM',          0),
    "PNG"  : (b'\x89PNG\r\n', 0),
    "JPEG" : (b'\xff\xd8\xff', 0),
    "TIFF" : (b'II*\x00',     0),
    "BMP (offset 1)" : (b'BM', 1),
    "BMP (offset 2)" : (b'BM', 2),
    "BMP (offset 11)": (b'BM', 11),
}

for name, (magic, offset) in checks.items():
    found = raw[offset:offset+len(magic)] == magic
    print(f"  {name:20s}: {'✅ MATCH' if found else '❌'}")

# Scan first 64 bytes for BM anywhere
bm_pos = raw.find(b'BM')
print(f"\n  'BM' found at byte offset: {bm_pos}")

png_pos = raw.find(b'\x89PNG')
print(f"  PNG magic at byte offset : {png_pos}")

# If BMP, parse the header
if bm_pos != -1:
    bmp = raw[bm_pos:]
    if len(bmp) >= 54:
        file_size, _, _, offset = struct.unpack_from("<IHHI", bmp, 2)
        width, height, planes, bpp = struct.unpack_from("<iiHH", bmp, 18)
        print(f"\n  BMP header:")
        print(f"    File size  : {file_size:,} bytes")
        print(f"    Data offset: {offset}")
        print(f"    Width      : {width} px")
        print(f"    Height     : {height} px")
        print(f"    Bit depth  : {bpp} bpp")

# Raw pixel math check
print(f"\n  Raw pixel checks:")
for bpp in [8, 16, 24, 32]:
    px = len(raw) * 8 // bpp
    print(f"    {bpp} bpp → {px:,} pixels "
          f"({'800×480=384000 ✅' if px == 384000 else f'≠ 384000'})")