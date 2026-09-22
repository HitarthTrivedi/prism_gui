import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QTextDocument, QPdfWriter, QPageSize, QPageLayout
from PySide6.QtCore import QMarginsF, QSizeF

app = QApplication.instance() or QApplication(sys.argv)

writer = QPdfWriter("test_res.pdf")
writer.setResolution(96)
layout = QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(15, 15, 15, 15), QPageLayout.Millimeter)
writer.setPageLayout(layout)

doc = QTextDocument()
paint_rect = layout.paintRectPixels(96)
doc.setPageSize(QSizeF(paint_rect.width(), paint_rect.height()))
doc.setHtml("""
<html>
<body style="font-family: Arial; font-size: 14pt; color: #111;">
    <h1 style="font-size: 24pt; color: #2563eb;">Heading 1 (24pt)</h1>
    <h2 style="font-size: 18pt; color: #333;">Heading 2 (18pt)</h2>
    <p style="font-size: 12pt; line-height: 1.6;">This is 12pt body text. It should be large, clear, and perfectly readable on any screen or printout.</p>
</body>
</html>
""")

doc.print_(writer)
print("Generated test_res.pdf, paint rect:", paint_rect.width(), paint_rect.height())
