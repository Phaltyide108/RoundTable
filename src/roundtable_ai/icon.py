"""The Sabha icon as PNG, ICO and ICNS, drawn in plain Python (no image libraries).

The same picture as ui/icon.svg: a lotus of eight petals (people around a table, each with
an orange flame at its tip) around a ring, on a rounded paper-coloured square. Used for the
app-menu entry on Linux, the Start menu shortcut on Windows and the .app bundle on macOS.
"""

from __future__ import annotations

import math
import struct
import zlib

PAPER = (0xF8, 0xF6, 0xF0)
INK = (0x1D, 0x21, 0x52)
FLAME = (0xEA, 0x82, 0x1E)


def _drop(u: float, v: float, base: float, radius: float, apex: float) -> bool:
    """Inside a drop pointing outwards: a round end at `base` and a point at `apex` (distances from the centre)."""
    if (u - base) ** 2 + v * v <= radius * radius:
        return True
    if base <= u <= apex:
        return abs(v) <= radius * ((apex - u) / (apex - base)) ** 0.85
    return False


def _mark(x: float, y: float) -> tuple[int, int, int] | None:
    """Colour of the lotus (100 x 100 units, centred on 50, 50) at (x, y), or None for background."""
    dx, dy = x - 50, 50 - y
    r = math.hypot(dx, dy)
    if r > 49:
        return None
    angle = math.degrees(math.atan2(dx, dy)) % 45     # 0 on a petal's axis
    off = angle if angle <= 22.5 else angle - 45
    u, v = r * math.cos(math.radians(off)), r * math.sin(math.radians(off))
    if _drop(u, v, 40.4, 4.4, 47.6):
        return FLAME
    if abs(r - 12.3) <= 1.55:
        return INK
    if r < 16.4 or _drop(u, v, 40.4, 6.2, 50) or (u - 23) ** 2 + v * v <= 36:
        return None
    if r < 31.5 and r * math.sin(math.radians(22.5 - abs(off))) < 1.1:
        return None                                    # the gap between two petals
    return INK if _drop(u, v, 23.6, 12.3, 41.4) else None


def _color_at(x: float, y: float) -> tuple[int, int, int] | None:
    """Colour of the 32x32 picture at (x, y), or None outside it."""
    r = 7.0
    cx = min(max(x, r), 32 - r)
    cy = min(max(y, r), 32 - r)
    if (x - cx) ** 2 + (y - cy) ** 2 > r * r or not (0 <= x <= 32 and 0 <= y <= 32):
        return None
    m = _mark(50 + (x - 16) * 100 / 26, 50 + (y - 16) * 100 / 26)     # the lotus fills 26 of the 32 units
    return m or PAPER


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
