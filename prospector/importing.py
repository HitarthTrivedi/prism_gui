"""
Prism Prospector — CSV import, the way Apollo's importer reads a file
──────────────────────────────────────────────────────────────────────
Apollo's "Import a CSV" is a mapping step, not a guess: "map your CSV column
headers to the corresponding Apollo field… When possible, Apollo automatically
detects and maps fields for you." sheet.py only ever guessed — by alias, with
no way to correct it — and its aliases did not know Apollo's own export: a
file straight out of Apollo ("First Name", "Last Name", "Person Linkedin Url")
lost every name and every profile link on the way in.

This module is the mapping step's model, for the Import wizard
(addons/leads/import_wizard.py):

  · tabs(path)                        the sheets a file holds, with row counts
  · read_table(path, sheet)           one tab: (name, header, rows) — or, with
                                      ALL_SHEETS, every tab as one table
  · guess_mapping(header, kind)       a field for every column, best guess
  · contacts_from_rows(…)             rows → Leads    (kind "contacts")
  · accounts_from_rows(…)             rows → companies (kind "accounts")

Fields, as Apollo's importer offers them. Every column is mapped to one: a
field, CUSTOM ("keep as a custom field" — the value is kept on the record
under the column's own header, sheet.py's rule that nothing the owner typed
is lost) or SKIP ("do not import").

Stdlib-only and Qt-free; the readers are sheet.py's.
"""
from __future__ import annotations

import re

from . import sheet as _sheet
from .models import Lead

CUSTOM = "custom"
SKIP = "skip"

# (key, label) — what the mapping step's drop-down offers, in its order, named
# the way Apollo's importer names them ("contact first name", "account name").
CONTACT_FIELDS = (
    ("first_name", "Contact first name"), ("last_name", "Contact last name"),
    ("name", "Contact full name"), ("title", "Contact title"),
    ("company", "Account name"), ("website", "Account website"),
    ("email", "Contact email"), ("phone", "Contact phone"),
    ("linkedin", "Contact LinkedIn URL"),
    ("city", "Contact city"), ("state", "Contact state"),
    ("country", "Contact country"), ("location", "Contact location"),
    ("industry", "Account industry"), ("seniority", "Contact seniority"),
    ("department", "Contact department"), ("headcount", "Account # employees"),
    ("since", "In role since"), ("stage", "Contact stage"),
)
ACCOUNT_FIELDS = (
    ("name", "Account name"), ("website", "Account website"),
    ("city", "Account city"), ("state", "Account state"),
    ("country", "Account country"), ("location", "Account location"),
    ("industry", "Account industry"), ("headcount", "Account # employees"),
    ("phone", "Account phone"), ("linkedin", "Account LinkedIn URL"),
    ("stage", "Account stage"),
)
FIELDS = {"contacts": CONTACT_FIELDS, "accounts": ACCOUNT_FIELDS}
EXTRA_CHOICES = ((CUSTOM, "Keep as a custom field"), (SKIP, "Do not import"))

# Header spellings per field. EXACT matches first (a header that IS the
# alias), then prefixes ("Email Address 2" → email) — and among equal
# matches the leftmost column wins, so Apollo's "Email" beats its later
# "Email Status", and its "Company" beats "Company Name for Emails".
_CONTACT_ALIASES = {
    "first_name": ("first name", "firstname", "first", "given name"),
    "last_name": ("last name", "lastname", "surname", "family name", "last"),
    "name": ("name", "full name", "contact name", "person", "contact",
             "person name", "lead name"),
    "title": ("title", "job title", "designation", "role", "position",
              "headline"),
    "company": ("company", "company name", "organisation", "organization",
                "account", "account name", "firm", "employer",
                "company name for emails"),
    "website": ("website", "company website", "url", "domain", "site",
                "company domain", "account website", "web"),
    "email": ("email", "e-mail", "email address", "work email", "mail",
              "contact email", "business email"),
    "phone": ("phone", "phone number", "mobile", "mobile phone", "work phone",
              "work direct phone", "corporate phone", "direct phone",
              "contact no", "phone no.", "phone no", "number", "telephone"),
    "linkedin": ("linkedin", "linkedin url", "person linkedin url",
                 "linkedin profile", "profile url", "profile",
                 "linkedin profile url"),
    "city": ("city", "town"),
    "state": ("state", "province", "region/state"),
    "country": ("country", "nation"),
    "location": ("location", "region", "geo", "area", "address"),
    "industry": ("industry", "sector", "vertical", "industry category"),
    "seniority": ("seniority", "level", "management level"),
    "department": ("department", "departments", "function", "sub departments"),
    "headcount": ("# employees", "employees", "employee count", "company size",
                  "headcount", "approx employee size", "no. of employees",
                  "number of employees", "size"),
    "since": ("in role since", "role since", "since", "start date", "tenure"),
    "stage": ("stage", "contact stage", "lead stage", "prospect stage"),
}
_ACCOUNT_ALIASES = {
    "name": ("account name", "company name", "company", "name", "organisation",
             "organization", "account", "firm", "business name"),
    "website": ("account website", "website", "company website", "domain",
                "url", "site", "company domain", "web"),
    "city": ("city", "town"),
    "state": ("state", "province"),
    "country": ("country", "nation"),
    "location": ("location", "region", "geo", "area", "address", "hq",
                 "headquarters"),
    "industry": ("industry", "sector", "vertical", "industry category"),
    "headcount": ("# employees", "employees", "employee count", "company size",
                  "headcount", "approx employee size", "no. of employees",
                  "number of employees", "size"),
    "phone": ("phone", "phone number", "company phone", "telephone",
              "contact no", "number"),
    "linkedin": ("company linkedin url", "linkedin", "linkedin url",
                 "company linkedin"),
    "stage": ("account stage", "stage", "company stage"),
}
_ALIASES = {"contacts": _CONTACT_ALIASES, "accounts": _ACCOUNT_ALIASES}
# Fields a file commonly spreads over several columns, any one of them filled:
# Apollo's export has "Work Direct Phone", "Mobile Phone" and "Corporate
# Phone", and the number is usually in only one. Mapped from every matching
# column; the row reads the first one that holds a value (_cells).
_MULTI = frozenset({"phone"})
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _norm(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _reader(path: str):
    return (_sheet._read_xlsx if str(path).lower().endswith((".xlsx", ".xlsm"))
            else _sheet._read_csv)


# read_table's `sheet` for every tab at once, and what the table is called.
ALL_SHEETS = "*"
ALL_SHEETS_NAME = "All sheets"
# The column an all-tabs table adds: which tab each row came from.
SHEET_COLUMN = "Sheet"


def tabs(path: str) -> list:
    """[(sheet name, data rows)] for every tab with a header — what the wizard
    offers when a workbook holds more than one."""
    return [(name, len(rows)) for name, _header, rows in _reader(path)(path)]


def read_table(path: str, sheet: str = ""):
    """(sheet name, header, rows) for one tab — the named one (exact, any
    case), else the first. With ALL_SHEETS, every tab as ONE table
    (_all_tabs). Raises ValueError for a file with no rows at all; OSError /
    zipfile errors pass through for the caller to word."""
    tables = [(name, [str(h or "").strip() for h in header], rows)
              for name, header, rows in _reader(path)(path)]
    if not tables:
        raise ValueError("This file has no rows to import.")
    if sheet == ALL_SHEETS:
        return _all_tabs(tables) if len(tables) > 1 else tables[0]
    for name, cells, rows in tables:
        if sheet and _norm(name) == _norm(sheet):
            return name, cells, rows
    return tables[0]


def _all_tabs(tables) -> tuple:
    """Every tab as one table: the columns of all of them in the order met
    (one header in two tabs, any case, is ONE column; a blank header stays its
    own column), each row under its own tab's columns and blank where its tab
    has none — and a last column, SHEET_COLUMN, naming the tab each row came
    from, which the mapping step keeps as a custom field."""
    header, at = [], {}
    for t, (_name, cells, _rows) in enumerate(tables):
        for c, h in enumerate(cells):
            key = _norm(h) or f"\x00{t}:{c}"
            if key not in at:
                at[key] = len(header)
                header.append(h)
    sheet_at = len(header)
    header.append(SHEET_COLUMN)
    out = []
    for t, (name, cells, rows) in enumerate(tables):
        place = [at[_norm(h) or f"\x00{t}:{c}"] for c, h in enumerate(cells)]
        for row in rows:
            merged = [""] * len(header)
            for c, value in enumerate(row):
                if c < len(place) and value not in (None, ""):
                    merged[place[c]] = value
            merged[sheet_at] = name
            out.append(merged)
    return ALL_SHEETS_NAME, header, out


def guess_mapping(header, kind: str) -> list:
    """A field key (or CUSTOM) for every column, in column order — Apollo's
    "automatically detect and map". Each field is used once: exact header
    matches first, then prefix matches, leftmost column first; everything
    left over is CUSTOM (a blank header is SKIP — there is no name to keep it
    under)."""
    aliases = _ALIASES[kind]
    cols = [_norm(h) for h in header or ()]
    out = [SKIP if not c else CUSTOM for c in cols]
    taken = set()
    for exact in (True, False):
        for i, c in enumerate(cols):
            if not c or out[i] != CUSTOM:
                continue
            for field, names in aliases.items():
                if field in taken and field not in _MULTI:
                    continue
                if (c in names) if exact else any(
                        c.startswith(a) and len(a) > 3 for a in names):
                    out[i] = field
                    taken.add(field)
                    break
    return out


# What a researched sheet writes where it found nothing. In a mapped field this
# means "blank", never a value: "Not Found" in a Website column is not a website
# (it once made 132 of 215 companies look like duplicates of each other), and
# "Not Found" in City is not a place to search. A CUSTOM column keeps what the
# owner typed, verbatim.
_PLACEHOLDERS = frozenset({
    "not found", "not available", "not applicable", "not provided", "not disclosed",
    "not listed", "not known", "no website", "no data", "n/a", "n.a.", "n.a", "nil",
    "none", "null", "nan", "unknown", "tbd", "-", "--", "—", "?"})


def is_placeholder(value) -> bool:
    """True for a cell that says there is nothing here ("Not Found", "N/A", "-")."""
    return _norm(value) in _PLACEHOLDERS


def _cells(row, header, mapping):
    """{field: value} and {header: value} (the CUSTOM columns) for one row.
    A field mapped twice keeps its first non-empty value; a placeholder
    ("Not Found", "N/A") in a field is a blank one."""
    fields, custom = {}, {}
    for i, target in enumerate(mapping):
        raw = row[i] if i < len(row) else None
        value = " ".join(str(raw).split()) if raw is not None else ""
        if not value or target == SKIP:
            continue
        if target == CUSTOM:
            key = str(header[i]).strip() if i < len(header) else f"Column {i + 1}"
            custom.setdefault(key, value)
        elif not is_placeholder(value):
            fields.setdefault(target, value)
    return fields, custom


def _place(fields) -> str:
    parts = [fields.get(k, "") for k in ("city", "state", "country")]
    joined = ", ".join(p for p in parts if p)
    return fields.get("location", "") or joined


def contacts_from_rows(header, rows, mapping, sheet_name: str = "") -> tuple:
    """(leads, skipped) — every row that identifies a PERSON as a Lead.

    Apollo's importer needs "at least one of Company Name, Company Website,
    Contact LinkedIn URL, Contact Email", and then refuses a file where "most
    rows need a valid full name". Prism keeps the row-level half of that: a
    row with a name, an e-mail or a LinkedIn link is a person; a row with
    only a company is not (that is an ACCOUNTS import), and is counted as
    skipped. Company and industry carry down a block of rows the way sheet.py
    has always read a block-formatted export."""
    leads, skipped = [], 0
    carry_company = carry_industry = ""
    for row in rows or ():
        f, custom = _cells(row, header, mapping)
        company = f.get("company") or carry_company
        industry = f.get("industry") or carry_industry
        carry_company, carry_industry = company, industry
        name = f.get("name") or " ".join(
            p for p in (f.get("first_name", ""), f.get("last_name", "")) if p)
        found = _EMAIL.findall(f.get("email", ""))
        email = found[0] if found else ""
        linkedin = f.get("linkedin", "")
        if not (name or email or linkedin):
            if any(f.values()) or custom:
                skipped += 1
            continue
        lead = Lead(name=name, title=f.get("title", ""), company=company,
                    email=email, phone=f.get("phone", ""),
                    industry=industry or sheet_name)
        if found[1:]:
            lead.extra["other_emails"] = found[1:]
        if email:
            lead.extra["email_source"] = "sheet"     # the owner's own file had it
        # "stage" rides on the lead only as far as the import: the saved
        # contact keeps it as its own field (addons/leads/contacts.py).
        for key, value in (("linkedin", linkedin), ("website", f.get("website", "")),
                           ("location", _place(f)), ("since", f.get("since", "")),
                           ("seniority", f.get("seniority", "")),
                           ("department", f.get("department", "")),
                           ("headcount", f.get("headcount", "")),
                           ("stage", f.get("stage", ""))):
            if value:
                lead.extra[key] = value
        if custom:
            lead.extra["custom"] = custom
        leads.append(lead)
    return leads, skipped


def accounts_from_rows(header, rows, mapping) -> tuple:
    """(companies, skipped) — every row that names a company (a name or a
    website) as {"name", "website", "location", "industry", "headcount",
    "phone", "linkedin", "stage", "custom"}. Rows naming none are skipped and counted;
    blank spacer rows are neither."""
    companies, skipped = [], 0
    for row in rows or ():
        f, custom = _cells(row, header, mapping)
        name, website = f.get("name", ""), f.get("website", "")
        if not (name or website):
            if any(f.values()) or custom:
                skipped += 1
            continue
        company = {"name": name, "website": website, "location": _place(f),
                   "industry": f.get("industry", ""),
                   "headcount": f.get("headcount", ""),
                   "phone": f.get("phone", ""), "linkedin": f.get("linkedin", ""),
                   "stage": f.get("stage", "")}
        if custom:
            company["custom"] = custom
        companies.append(company)
    return companies, skipped


def looks_like(header) -> str:
    """"contacts" when the header has a column that identifies a PERSON (a
    name, first/last name, e-mail or LinkedIn link), else "accounts" — the
    Import menu's pre-selection when the owner has not said which."""
    mapping = guess_mapping(header, "contacts")
    person = {"name", "first_name", "last_name", "email", "linkedin"}
    return "contacts" if person & set(mapping) else "accounts"
