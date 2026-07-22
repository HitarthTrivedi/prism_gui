#!/usr/bin/env python3
"""Render the Prism mark into the three icon formats desktop OSes demand.

  packaging/icons/prism.png    Linux (.desktop / AppImage)
  packaging/icons/prism.ico    Windows (.exe resource, taskbar, explorer)
  packaging/icons/prism.icns   macOS (.app bundle, Dock, Finder)

Everything is written by hand from PNGs rendered with Qt, which the app already
depends on — so building icons needs no Pillow, no iconutil, no ImageMagick,
and works identically on all three CI runners. Both .ico and .icns are simple
containers that accept PNG payloads directly (ICO since Vista, ICNS since
10.7), so "by hand" here means a header and an offset table, not a rasteriser.

The logo is taller than it is wide; icons are square. Rather than distort it,
each size is drawn centred on a transparent square canvas.
"""
from __future__ import annotations
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GUI = os.path.dirname(HERE)
sys.path.insert(0, GUI)

from PySide6.QtCore import QBuffer, QByteArray, QRectF, Qt   # noqa: E402
from PySide6.QtGui import QImage, QPainter                    # noqa: E402
from PySide6.QtSvg import QSvgRenderer                        # noqa: E402
from PySide6.QtWidgets import QApplication                    # noqa: E402

SVG = os.path.join(GUI, "assets", "prism-logo.svg")
OUT = os.path.join(HERE, "icons")

# Windows wants the small sizes for the taskbar/explorer list views; macOS
# wants the big ones for the Dock and Finder's icon view.
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
# (icns OSType, pixel size). The @2x types carry the retina variants.
ICNS_TYPES = (
    (b"icp4", 16), (b"icp5", 32), (b"ic11", 32), (b"ic12", 64),
    (b"ic07", 128), (b"ic13", 256), (b"ic08", 256), (b"ic14", 512),
    (b"ic09", 512), (b"ic10", 1024),
)
# The mark occupies this share of the canvas; the margin keeps it off the edge
# the way every platform's own icons sit inside their grid.
INSET = 0.86


def render_png(size: int) -> bytes:
    """The logo, centred on a transparent size×size canvas, as PNG bytes."""
    renderer = QSvgRenderer(SVG)
    box = renderer.defaultSize()
    scale = (size * INSET) / max(box.width(), box.height())
    w, h = box.width() * scale, box.height() * scale

    image = QImage(size, size, QImage.Format_RGBA8888)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    renderer.render(painter, QRectF((size - w) / 2, (size - h) / 2, w, h))
    painter.end()

    # The QByteArray must outlive the QBuffer that writes into it — passing a
    # temporary here frees it under Qt and segfaults.
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QBuffer.WriteOnly)
    image.save(buf, "PNG")
    buf.close()
    return bytes(data)


def write_ico(path: str, sizes=ICO_SIZES):
    """ICONDIR + one ICONDIRENTRY per image, PNG payloads appended."""
    images = [(s, render_png(s)) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))       # reserved, type=icon, count
    offset = len(header) + 16 * len(images)
    entries, payloads = b"", b""
    for size, png in images:
        # 256 is stored as 0 — the field is a single byte.
        entries += struct.pack(
            "<BBBBHHII", size if size < 256 else 0, size if size < 256 else 0,
            0, 0, 1, 32, len(png), offset)
        payloads += png
        offset += len(png)
    with open(path, "wb") as f:
        f.write(header + entries + payloads)


def write_icns(path: str, types=ICNS_TYPES):
    """'icns' + total length, then a TYPE/length/PNG chunk per size."""
    chunks = b""
    for ostype, size in types:
        png = render_png(size)
        chunks += ostype + struct.pack(">I", len(png) + 8) + png
    with open(path, "wb") as f:
        f.write(b"icns" + struct.pack(">I", len(chunks) + 8) + chunks)


def main():
    app = QApplication.instance() or QApplication(sys.argv)   # noqa: F841
    os.makedirs(OUT, exist_ok=True)

    png_path = os.path.join(OUT, "prism.png")
    with open(png_path, "wb") as f:
        f.write(render_png(512))
    write_ico(os.path.join(OUT, "prism.ico"))
    write_icns(os.path.join(OUT, "prism.icns"))

    for name in ("prism.png", "prism.ico", "prism.icns"):
        p = os.path.join(OUT, name)
        print(f"  {name:12} {os.path.getsize(p):>8,} bytes")
    print(f"written to {OUT}")


if __name__ == "__main__":
    main()
