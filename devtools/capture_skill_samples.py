"""Render the skill test samples in real Chrome and save them as Prism captures them.

Prism never reads markdown. automation._capture takes Selenium's element
text of the chat page, so a table arrives as cells joined by spaces, a list
loses its bullets and numbers, and a heading is a bare line. The skill
checkers are tested against that shape, and this script produces it the same
way: each tests/skill_samples/source/*.md is rendered to HTML the way a chat
renders markdown, loaded in headless Chrome, and its Selenium element text is
written to tests/skill_samples/captured/*.txt.

    python devtools/capture_skill_samples.py

Needs Chrome and a matching chromedriver (Selenium's cache is used when
present). Development only; nothing under devtools/ ships.
"""
from __future__ import annotations

import glob
import html
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "tests", "skill_samples", "source")
CAPTURED = os.path.join(ROOT, "tests", "skill_samples", "captured")


def _inline(s: str) -> str:
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", s)


def to_html(md: str) -> str:
    """The markdown a chat model writes, rendered the way chat UIs render
    it: headings, lists, tables, bold, and a single newline kept as a line
    break."""
    out, lines, i = [], md.splitlines(), 0
    block = re.compile(r"^(#{1,6}\s|\s*[-*]\s|\s*\d+[.)]\s|\s*\|)")
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            n = len(m.group(1))
            out.append(f"<h{n}>{_inline(m.group(2))}</h{n}>")
            i += 1
            continue
        if line.strip().startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(set(c) <= set("-: ") for c in cells):
                    rows.append(cells)
                i += 1
            body = "".join(
                "<tr>" + "".join(f"<{'th' if r == 0 else 'td'}>{_inline(c)}"
                                 f"</{'th' if r == 0 else 'td'}>" for c in cells)
                + "</tr>" for r, cells in enumerate(rows))
            out.append(f"<table>{body}</table>")
            continue
        for pat, tag in ((r"^\s*[-*]\s+", "ul"), (r"^\s*\d+[.)]\s+", "ol")):
            if re.match(pat, line):
                items = []
                while i < len(lines) and re.match(pat, lines[i]):
                    items.append(re.sub(pat, "", lines[i]))
                    i += 1
                out.append(f"<{tag}>" + "".join(f"<li>{_inline(x)}</li>" for x in items)
                           + f"</{tag}>")
                break
        else:
            para = []
            while i < len(lines) and lines[i].strip() and not block.match(lines[i]):
                para.append(_inline(lines[i]))
                i += 1
            out.append("<p>" + "<br>".join(para) + "</p>")
    return "\n".join(out)


def _chrome_major() -> str:
    for exe in ("google-chrome", "google-chrome-stable", "chromium"):
        try:
            v = subprocess.run([exe, "--version"], capture_output=True, text=True).stdout
            m = re.search(r"(\d+)\.", v)
            if m:
                return m.group(1)
        except OSError:
            continue
    return ""


def _driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    opts = webdriver.ChromeOptions()
    for arg in ("--headless=new", "--no-first-run", "--disable-gpu",
                f"--user-data-dir={tempfile.mkdtemp(prefix='skill-capture-')}"):
        opts.add_argument(arg)
    major = _chrome_major()
    cached = sorted(glob.glob(os.path.expanduser(
        f"~/.cache/selenium/chromedriver/*/{major}.*/chromedriver")))
    if cached:
        return webdriver.Chrome(options=opts, service=Service(cached[-1]))
    return webdriver.Chrome(options=opts)


def main() -> int:
    from selenium.webdriver.common.by import By
    os.makedirs(CAPTURED, exist_ok=True)
    sources = sorted(glob.glob(os.path.join(SOURCE, "*.md")))
    driver = _driver()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            for path in sources:
                name = os.path.splitext(os.path.basename(path))[0]
                page = os.path.join(tmp, name + ".html")
                with open(path, encoding="utf-8") as f:
                    body = to_html(f.read())
                with open(page, "w", encoding="utf-8") as f:
                    f.write('<!doctype html><meta charset="utf-8">'
                            f'<div id="reply" class="markdown prose">{body}</div>')
                driver.get("file://" + page)
                text = driver.find_element(By.ID, "reply").text
                with open(os.path.join(CAPTURED, name + ".txt"), "w",
                          encoding="utf-8") as f:
                    f.write(text.rstrip() + "\n")
                print(f"captured {name}: {len(text)} chars")
    finally:
        driver.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
