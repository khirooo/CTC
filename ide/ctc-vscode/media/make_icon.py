#!/usr/bin/env python3
"""Render the CTC extension icon (icon.png) deterministically — no external deps.

A centered orange rounded square (brand #f2660f) with a white chevron on a
transparent background. Run: python3 media/make_icon.py
"""
import struct
import zlib

N = 256           # canvas
SS = 3            # supersampling factor for anti-aliasing
M = 8             # margin around the rounded square
R = 52            # corner radius
ORANGE = (242, 102, 15)
WHITE = (255, 255, 255)
STROKE = 26.0     # chevron stroke width
# chevron points (centered on the canvas: x-mid and y-mid both = 128)
CHEV = [(96, 76), (160, 128), (96, 180)]


def in_round_rect(x, y):
    x0, y0, x1, y1 = M, M, N - M, N - M
    if x < x0 or x > x1 or y < y0 or y > y1:
        return False
    # corner circles
    cx = min(max(x, x0 + R), x1 - R)
    cy = min(max(y, y0 + R), y1 - R)
    return (x - cx) ** 2 + (y - cy) ** 2 <= R * R


def _dist_seg(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    qx, qy = ax + t * dx, ay + t * dy
    return ((px - qx) ** 2 + (py - qy) ** 2) ** 0.5


def on_chevron(x, y):
    half = STROKE / 2.0
    for (ax, ay), (bx, by) in zip(CHEV, CHEV[1:]):
        if _dist_seg(x, y, ax, ay, bx, by) <= half:
            return True
    return False


def sample(x, y):
    # returns (r,g,b,a) for one subsample point
    if on_chevron(x, y):
        return (*WHITE, 255)
    if in_round_rect(x, y):
        return (*ORANGE, 255)
    return (0, 0, 0, 0)


def build_rgba():
    rows = []
    for py in range(N):
        row = bytearray()
        for px in range(N):
            r = g = b = a = 0
            for sy in range(SS):
                for sx in range(SS):
                    xx = px + (sx + 0.5) / SS
                    yy = py + (sy + 0.5) / SS
                    sr, sg, sb, sa = sample(xx, yy)
                    r += sr; g += sg; b += sb; a += sa
            n = SS * SS
            row += bytes((r // n, g // n, b // n, a // n))
        rows.append(bytes(row))
    return rows


def write_png(path, rows):
    def chunk(typ, data):
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", N, N, 8, 6, 0, 0, 0)  # RGBA
    raw = b"".join(b"\x00" + r for r in rows)            # filter 0 per row
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    open(path, "wb").write(png)


if __name__ == "__main__":
    import os
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
    write_png(out, build_rgba())
    print("wrote", out)
