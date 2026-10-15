"""The Roundtable icon as PNG, ICO and ICNS, drawn in plain Python (no image libraries).

The same picture as ui/icon.svg: a table seen from above with four seats around it.
Used for the app-menu entry on Linux, the Start menu shortcut on Windows and the
.app bundle on macOS.
"""

from __future__ import annotations

import struct
import zlib

BG = (0x3E, 0x6A, 0x5B)
TABLE = (0x55, 0x7F, 0x70)
RIM = (0xE9, 0xDF, 0xC9)
SEAT = (0xF5, 0xF3, 0xEE)
SEATS = ((16, 5.6), (16, 26.4), (4.8, 16), (27.2, 16))


def _color_at(x: float, y: float) -> tuple[int, int, int] | None:
    """Colour of the 32x32 picture at (x, y), or None outside it."""
    r = 8.0
    cx = min(max(x, r), 32 - r)
    cy = min(max(y, r), 32 - r)
    if (x - cx) ** 2 + (y - cy) ** 2 > r * r or not (0 <= x <= 32 and 0 <= y <= 32):
        return None
    for sx, sy in SEATS:
        if (x - sx) ** 2 + (y - sy) ** 2 <= 2.1 ** 2:
            return SEAT
    e = ((x - 16) / 8) ** 2 + ((y - 16) / 5.5) ** 2
    if e <= 1:
        # the rim: about 0.8 units on each side of the ellipse outline
        inner = ((x - 16) / 7.2) ** 2 + ((y - 16) / 4.7) ** 2
        return TABLE if inner <= 1 else RIM
    outer = ((x - 16) / 8.8) ** 2 + ((y - 16) / 6.3) ** 2
    if outer <= 1:
        return RIM
    return BG


def rgba(size: int) -> bytes:
    """size x size RGBA pixels, anti-aliased with 3x3 samples per pixel."""
    rows = bytearray()
    step = 32.0 / size
    offs = (1 / 6, 0.5, 5 / 6)
    for py in range(size):
        rows.append(0)                       # PNG filter type: none
        for px in range(size):
            r = g = b = a = 0
            for oy in offs:
                for ox in offs:
                    c = _color_at((px + ox) * step, (py + oy) * step)
                    if c is not None:
                        r += c[0]
                        g += c[1]
                        b += c[2]
                        a += 1
            if a:
                rows += bytes((r // a, g // a, b // a, round(255 * a / 9)))
            else:
                rows += b"\0\0\0\0"
    return bytes(rows)


def png(size: int = 256) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    head = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head) + chunk(b"IDAT", zlib.compress(rgba(size), 9)) + chunk(b"IEND", b"")


def ico(data: bytes | None = None) -> bytes:
    """A Windows .ico holding one 256x256 PNG (supported since Windows Vista)."""
    data = data or png(256)
    return struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(data), 22) + data


def icns(data: bytes | None = None) -> bytes:
    """A macOS .icns holding one 256x256 PNG ('ic08')."""
    data = data or png(256)
    entry = b"ic08" + struct.pack(">I", len(data) + 8) + data
    return b"icns" + struct.pack(">I", len(entry) + 8) + entry
