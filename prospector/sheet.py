"""
Prism Prospector — reading the client's own list
─────────────────────────────────────────────────
The on-ramp. The buyer already has a sheet he trusts (Sales Nav + Apollo,
exported to Excel). We do not ask him to rebuild it — we ingest it, then
verify, enrich and qualify on top. So this module has to be forgiving about
the mess a real hand-kept sheet carries.

Three quirks learned from a real export (`LinkedIn Data.xlsx`), handled here:

  · **Headers carry trailing spaces** ("Company ", "Name ") — matched loosely.
  · **Company / Industry are filled on the first row of each block only**, the
    rest left blank as a visual grouping. We forward-fill them down, so every
    contact keeps its company instead of most rows losing it.
  · **One cell can hold two e-mails** ("corp@x.com   personal@gmail.com"). The
    first becomes the primary; the rest are kept in `extra`, never dropped.

xlsx is parsed with the standard library only (it is a zip of XML) so ingest
never depends on pandas/openpyxl being installed on a customer's machine.
"""
from __future__ import annotations

import csv
import os
import re
import zipfile
from xml.etree import ElementTree as ET

from .models import Lead

_M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS = {"m": _M}
_RNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

# How we recognise the columns we care about, whatever the client called them.
_ALIASES = {
    "name": ("name", "full name", "contact", "person"),
    "title": ("designation", "title", "job title", "role", "position"),
    "company": ("company", "organisation", "organization", "account", "firm"),
    "email": ("e-mail", "email", "mail", "email address"),
    "phone": ("phone no.", "phone", "phone number", "mobile", "contact no", "number"),
    "industry": ("industry", "sector", "vertical", "segment"),
    "location": ("location", "city", "region", "country", "geo", "area"),
    "since": ("in role since", "role since", "since", "start date", "tenure"),
    "linkedin": ("linkedin", "linkedin url", "profile url", "linkedin profile", "profile"),
}
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def _col_to_idx(ref) -> int:
    m = re.match(r"([A-Z]+)\d+", ref or "A1")
    letters = m.group(1) if m else "A"
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


# ── low-level readers: (sheet_name, header, rows) tuples ─────────────────────

def _read_xlsx(path: str):
    z = zipfile.ZipFile(path)
    names = z.namelist()

    shared = []
    if "xl/sharedStrings.xml" in names:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall("m:si", _NS):
            shared.append("".join(t.text or "" for t in si.findall(".//m:t", _NS)))

    wb = ET.fromstring(z.read("xl/workbook.xml"))
    sheets = wb.findall(".//m:sheet", _NS)
    rid_to_target = {}
    if "xl/_rels/workbook.xml.rels" in names:
        for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")):
            rid_to_target[r.get("Id")] = r.get("Target")

    for s in sheets:
        target = rid_to_target.get(s.get("{%s}id" % _RNS))
        p = "xl/" + target.lstrip("/") if target else None
        if not p or p not in names:
            cand = [n for n in names if "worksheets" in n and n.endswith(".xml")]
            p = cand[0] if cand else None
        if not p:
            continue
        rows = []
        for row in ET.fromstring(z.read(p)).findall(".//m:sheetData/m:row", _NS):
            cells, maxc = {}, -1
            for c in row.findall("m:c", _NS):
                ci = _col_to_idx(c.get("r"))
                maxc = max(maxc, ci)
                t, v = c.get("t"), c.find("m:v", _NS)
                if t == "s":
                    val = shared[int(v.text)] if (v is not None and v.text) else None
                elif t == "inlineStr":
                    isel = c.find("m:is", _NS)
                    val = "".join(tt.text or "" for tt in isel.findall(".//m:t", _NS)) if isel is not None else None
                else:
                    val = v.text if v is not None else None
                cells[ci] = val
            rows.append([cells.get(i) for i in range(maxc + 1)])
        if rows:
            yield s.get("name"), rows[0], rows[1:]


def _read_csv(path: str):
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if rows:
        yield os.path.splitext(os.path.basename(path))[0], rows[0], rows[1:]


# ── mapping a sheet's rows to Leads ──────────────────────────────────────────

def _column_map(header) -> dict:
    """field -> column index, by loose alias match."""
    out = {}
    for i, h in enumerate(header or []):
        hn = _norm(h)
        for field, aliases in _ALIASES.items():
            if field in out:
                continue
            if any(hn == a or hn.startswith(a) for a in aliases):
                out[field] = i
    return out


def _split_emails(cell: str):
    found = _EMAIL_RE.findall(str(cell or ""))
    return found[0] if found else "", found[1:]


def leads_from_sheet(name, header, rows) -> list[Lead]:
    cm = _column_map(header)
    carry_company = carry_industry = ""
    out = []
    for r in rows:
        def cell(field):
            i = cm.get(field)
            return (str(r[i]).strip() if i is not None and i < len(r) and r[i] is not None else "")

        # Forward-fill the block columns.
        company = cell("company") or carry_company
        industry = cell("industry") or carry_industry or name
        carry_company, carry_industry = company, (cell("industry") or carry_industry)

        person = cell("name")
        if not person:
            continue                     # a spacer / blank row, skip it

        email, extra_emails = _split_emails(cell("email"))
        lead = Lead(
            name=person, title=cell("title"), company=company,
            email=email, phone=cell("phone"), industry=industry or name,
        )
        if extra_emails:
            lead.extra["other_emails"] = extra_emails
        # Kept for the leads-sheet export (Location / In role since / LinkedIn);
        # unmapped, they were being dropped, which is why the exported sheet
        # looked thinner than the client's own.
        for key in ("location", "since", "linkedin"):
            v = cell(key)
            if v:
                lead.extra[key] = v
        out.append(lead)
    return out


def load(path: str, sheet: str | None = None) -> list[Lead]:
    """Every lead in the workbook, or just one sheet if `sheet` is given
    (case-insensitive match)."""
    reader = _read_xlsx if path.lower().endswith((".xlsx", ".xlsm")) else _read_csv
    want = _norm(sheet) if sheet else None
    out = []
    for sname, header, rows in reader(path):
        # "Steel" should match a sheet called "Steel Manufacturing" — a loose
        # contains match, so the caller need not know the exact tab name.
        if want and want not in _norm(sname):
            continue
        out.extend(leads_from_sheet(sname, header, rows))
    return out


def sheet_names(path: str) -> list[str]:
    if not path.lower().endswith((".xlsx", ".xlsm")):
        return [os.path.splitext(os.path.basename(path))[0]]
    return [name for name, _h, _r in _read_xlsx(path)]
