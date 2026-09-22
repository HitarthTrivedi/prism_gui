import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QTextDocument, QPdfWriter, QPageSize, QPageLayout
from PySide6.QtCore import QMarginsF
import pypdf

app = QApplication.instance() or QApplication(sys.argv)

with open("generate_qa_pdf.py", "r", encoding="utf-8") as f:
    code = f.read()

# Extract html_content from generate_qa_pdf.py
start = code.find('html_content = f"""') + len('html_content = f"""')
end = code.find('"""\n\ndoc.setHtml(html_content)')
html = code[start:end]

# Test 1: setTextWidth instead of setPageSize
writer = QPdfWriter("test_multi.pdf")
writer.setResolution(96)
layout = QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(15, 15, 15, 15), QPageLayout.Millimeter)
writer.setPageLayout(layout)

doc = QTextDocument()
paint_rect = layout.paintRectPixels(96)
doc.setTextWidth(paint_rect.width())
doc.setHtml(html)
doc.print_(writer)

reader = pypdf.PdfReader("test_multi.pdf")
print("With setTextWidth, Total Pages:", len(reader.pages))
for i, page in enumerate(reader.pages):
    print(f"Page {i+1} text length:", len(page.extract_text()))
