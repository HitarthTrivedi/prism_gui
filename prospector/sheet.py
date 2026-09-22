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
    "website": ("website", "company website", "url", "domain", "site"),
}
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def _part(target) -> str:
    """The zip entry a workbook relationship points at.

    The two writers spell the target differently: Excel writes it relative to
    the workbook ("worksheets/sheet1.xml"), openpyxl — which writes Prism's own
    exports — writes the absolute part name ("/xl/worksheets/sheet1.xml").
    Prefixing "xl/" blindly turned the second kind into "xl/xl/…", a part that
    is not in the zip, so every tab fell through to the fallback below and a
    three-industry export read back as tab one, three times over.
    """
    t = str(target or "").lstrip("/")
    return t if not t or t.startswith("xl/") else "xl/" + t


def _worksheet_parts(names) -> list:
    """Every worksheet part, in sheet1, sheet2 … sheet10 order — shortest name
    first, so sheet2 sorts before sheet10 the way a reader expects."""
    parts = [n for n in names
             if n.startswith("xl/worksheets/") and n.endswith(".xml")
             and "/_rels/" not in n]
    return sorted(parts, key=lambda n: (len(n), n))


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

    for pos, s in enumerate(sheets):
        p = _part(rid_to_target.get(s.get("{%s}id" % _RNS)))
        if not p or p not in names:
            # A rels entry we could not resolve: fall back to the worksheet
            # parts in their own order and take THIS tab's. Taking the first
            # one for every tab is how a lost relationship used to become
            # silent data loss — the same rows, repeated, and the rest gone.
            cand = _worksheet_parts(names)
            p = cand[pos] if pos < len(cand) else None
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
        email, extra_emails = _split_emails(cell("email"))
        linkedin = cell("linkedin")
        # Apollo's own rule for a row worth keeping: name, email or LinkedIn
        # — any ONE identifies a person worth reaching. Company alone does
        # not (that is what a company-only sheet's own search path is for,
        # see has_contact_signal) — a spacer/blank row and a pure company-
        # research row look identical here, and both get skipped the same
        # way they always did.
        if not (person or email or linkedin):
            continue
        lead = Lead(
            name=person, title=cell("title"), company=company,
            email=email, phone=cell("phone"), industry=industry or name,
        )
        if extra_emails:
            lead.extra["other_emails"] = extra_emails
        # Kept for the leads-sheet export (Location / In role since / LinkedIn
        # / Website); unmapped, they were being dropped, which is why the
        # exported sheet looked thinner than the client's own.
        for key, v in (("location", cell("location")), ("since", cell("since")),
                      ("linkedin", linkedin), ("website", cell("website"))):
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


def has_name_column(path: str, sheet: str | None = None) -> bool:
    """Whether any sheet's header has a column load() would read as a
    person's NAME (see _ALIASES) — the header check alone, no row work.

    load() returning nothing is ambiguous: an empty sheet and a sheet
    of real data with no name/contact column both come back as `[]`,
    and look identical to a customer as "the sheet had nobody in it".
    They are not the same problem — a company-research export (Company
    Name, Industry, City, Website …) has real rows, every one of them
    skipped for lacking a name column, not for lacking people worth
    importing. False here is the caller's cue to say which one happened.
    """
    reader = _read_xlsx if path.lower().endswith((".xlsx", ".xlsm")) else _read_csv
    want = _norm(sheet) if sheet else None
    for sname, header, _rows in reader(path):
        if want and want not in _norm(sname):
            continue
        if "name" in _column_map(header):
            return True
    return False


def has_contact_signal(path: str, sheet: str | None = None) -> bool:
    """Whether any sheet's header has a column that could identify or reach
    a PERSON — name, email or LinkedIn (see _ALIASES) — the header check
    alone, no row work. This is leads_from_sheet's own row-keeping rule
    (name or email or LinkedIn) read off the header instead of the rows,
    so it answers the same question load() answers by actually reading the
    sheet, cheaply, before doing that work.

    Broader than has_name_column on purpose, matching the same widened row
    rule: a sheet with Company + Email columns and no separate Name column
    at all is a real, if thin, contacts sheet — Apollo's own "Import
    contacts" accepts exactly this shape — not a company-research export.
    Company or Website alone is NOT enough here even though load_companies
    can still read the companies out of such a sheet; that is what a
    company-only sheet's own search path (addons.leads.workbench) is for."""
    reader = _read_xlsx if path.lower().endswith((".xlsx", ".xlsm")) else _read_csv
    want = _norm(sheet) if sheet else None
    for sname, header, _rows in reader(path):
        if want and want not in _norm(sname):
            continue
        cm = _column_map(header)
        if "name" in cm or "email" in cm or "linkedin" in cm:
            return True
    return False


def load_companies(path: str, sheet: str | None = None) -> list[str]:
    """Every distinct company named in the workbook — the read a sheet with
    no contact signal (has_contact_signal() is False) falls back to.

    Reuses leads_from_sheet's own forward-fill: a block-formatted export
    (LinkedIn Data.xlsx's shape, see the module docstring) leaves Company
    blank on every row but the block's first, and the same carry-down that
    keeps a contact's company also keeps a company-only row's. De-duplicated
    case-insensitively, first spelling wins, in the order the sheet has
    them — the same rule _values() uses for a filter's own chip list, since
    that is almost always where this goes next (addons.leads.workbench,
    the "current company" filter)."""
    reader = _read_xlsx if path.lower().endswith((".xlsx", ".xlsm")) else _read_csv
    want = _norm(sheet) if sheet else None
    out, seen = [], set()
    for sname, header, rows in reader(path):
        if want and want not in _norm(sname):
            continue
        cm = _column_map(header)
        ci = cm.get("company")
        if ci is None:
            continue
        carry = ""
        for r in rows:
            cell = (str(r[ci]).strip() if ci < len(r) and r[ci] is not None else "")
            company = cell or carry
            carry = company
            if not company:
                continue
            key = company.casefold()
            if key not in seen:
                seen.add(key)
                out.append(company)
    return out


def sheet_names(path: str) -> list[str]:
    if not path.lower().endswith((".xlsx", ".xlsm")):
        return [os.path.splitext(os.path.basename(path))[0]]
    return [name for name, _h, _r in _read_xlsx(path)]
