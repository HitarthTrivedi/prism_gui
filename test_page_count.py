import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QTextDocument, QPdfWriter, QPageSize, QPageLayout
from PySide6.QtCore import QMarginsF
import pypdf

app = QApplication.instance() or QApplication(sys.argv)
writer = QPdfWriter('test_pages.pdf')
writer.setResolution(96)
layout = QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(15, 15, 15, 15), QPageLayout.Millimeter)
writer.setPageLayout(layout)

doc = QTextDocument()
html = '<h1>Header</h1>' + '<p style="font-size: 14pt;">Long paragraph testing pagination line.</p>' * 100
doc.setHtml(html)
doc.print_(writer)

reader = pypdf.PdfReader('test_pages.pdf')
print('Without setPageSize, Pages:', len(reader.pages))

# Now test with doc.setPageSize(paintRectPixels)
writer2 = QPdfWriter('test_pages2.pdf')
writer2.setResolution(96)
writer2.setPageLayout(layout)
doc2 = QTextDocument()
doc2.setPageSize(layout.paintRectPixels(96).size())
doc2.setHtml(html)
doc2.print_(writer2)

reader2 = pypdf.PdfReader('test_pages2.pdf')
print('With setPageSize, Pages:', len(reader2.pages))
