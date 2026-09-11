"""
Prism Sales Automation — places: where a person is, read the way a recruiter reads it
──────────────────────────────────────────────────────────────────────────────────
A profile's location is loose text — "Pune, Maharashtra, India", "Greater
Mumbai Area", "Bombay", "Fort Wayne, IN", "Remote". A location FILTER is a place
— "India", "Europe", "Gujarat" — and "Location: anywhere, except India" is only
real when every one of those strings is read back to the countries it points at.
This module is that reader: a small offline gazetteer and one alias index.

    resolve(text)              the Place a filter value names (any case, accents folded)
    countries_in(location)     ISO2 codes a profile location points to; empty = unknown
    matches(location, place)   True / False, or None when the location can't be read
    aliases_of(place)          every lower-case name of the place and what is inside it,
                               so an excluded place never reaches a search query
    suggest(text)              labels for the chip box as the user types
    regions_outside(ex, inc)   search-location phrases covering the world minus exclusions

How a location string is read (the order matters, and the tests pin it):
  · a COUNTRY named in the string wins — "Hyderabad, Sindh, Pakistan" is PK and
    "London, Ontario, Canada" is CA, whatever the city names also mean. When
    countries sit in different comma segments the last one wins ("Lebanon,
    Pennsylvania, United States" is US), the way profiles are written: small
    place first, country last;
  · with no country, the biggest unit in the last segment decides ("Paris,
    Texas" is US) and the other names narrow it where they agree ("Atlanta,
    Georgia" is US, "Georgia" alone is {GE, US}, "Punjab" alone is {IN, PK});
  · a few names are SECONDARY — they count only when something else in the
    string agrees: bare "Hyderabad" is India, "Hyderabad, Sindh" is Pakistan;
  · a two-letter US state code ("Fort Wayne, IN") counts only as its own comma
    segment in a string naming no other country. A bare "IN" is never India;
  · "Remote", "Worldwide", "" read as nothing — unknown, never "everywhere".

Region choices (documented because they decide exclusions): Turkey is in Europe
AND the Middle East (not Asia); Egypt is in Africa (North Africa) AND the Middle
East; Russia is in Europe (Eastern Europe) only; Georgia, Armenia and Azerbaijan
are in Asia, not Europe; Mexico is in North America AND Latin America.

Stdlib-only and Qt-free: plain Python literals, built once at import.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

KINDS = ("region", "country", "state", "city")
_RANK = {kind: i for i, kind in enumerate(KINDS)}


@dataclass(frozen=True)
class Place:
    key: str            # "country:IN", "state:IN:gujarat", "city:IN:vadodara", "region:europe"
    label: str          # what a chip shows; unique across the gazetteer
    kind: str           # "region" | "country" | "state" | "city"
    countries: frozenset  # ISO2 codes


# ── folding: one spelling for every way a place is typed ─────────────────────

# Letters NFKD does not split into base + accent.
_LETTERS = str.maketrans({"ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "ł": "l",
                          "Ł": "l", "đ": "d", "Đ": "d", "þ": "th", "ı": "i"})
_DROP = re.compile(r"[.'’`]")          # "U.S." → "us", "Côte d'Ivoire" → "cote divoire"
_NON_WORD = re.compile(r"[^a-z0-9,;|]+")     # keep the segment separators
_SEGMENT = re.compile(r"[,;|]")


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.translate(_LETTERS))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.casefold().replace("&", " and ")
    return _NON_WORD.sub(" ", _DROP.sub("", text))


def _key(text) -> str:
    """A whole value as one phrase: folded, separators gone, spaces collapsed."""
    if not isinstance(text, str):
        return ""
    return " ".join(_SEGMENT.sub(" ", _fold(text)).split())


def _texts(values) -> list:
    if isinstance(values, str):
        return [values]
    try:
        return [v for v in values if isinstance(v, str) and v.strip()]
    except TypeError:
        return []


# ── the gazetteer (filled from the data below by _build) ──────────────────────

_PLACES: list = []          # every Place, regions → countries → states → cities
_BY_KEY: dict = {}
_LABELS: dict = {}          # _key(label) → Place
_ALIASES: dict = {}         # place key → lower-case names, label first
_FOLDED: dict = {}          # place key → folded names (suggest)
_PARENT: dict = {}          # state/city key → the state or country key it sits in
_DIRECT: dict = {}          # country key → states + stateless cities; state key → cities
_INDEX: dict = {}           # folded phrase → _Entry
_MAX_WORDS = 1
_WORLD: list = []           # country Places, most commercially important first
_REGION_ORDER: list = []


class _Entry:
    """Everything one phrase can mean, pre-summarised for the reader."""
    __slots__ = ("places", "full", "primary", "rank", "only_countries", "keys", "best")

    def __init__(self, pairs):
        self.places = tuple(p for p, _ in pairs)
        self.full = frozenset().union(*(p.countries for p in self.places))
        primary = frozenset().union(*(p.countries for p, main in pairs if main))
        self.primary = primary or self.full
        self.rank = min(_RANK[p.kind] for p in self.places)
        self.only_countries = all(p.kind == "country" for p in self.places)
        keys = set()
        for p in self.places:
            keys.add(p.key)
            parent = _PARENT.get(p.key)
            if parent:
                keys.add(parent)
        self.keys = frozenset(keys)
        # resolve() picks the biggest, main, first-defined meaning
        order = {p.key: i for i, p in enumerate(self.places)}
        mains = {p.key for p, main in pairs if main}
        self.best = min(self.places, key=lambda p: (_RANK[p.kind], p.key not in mains,
                                                    order[p.key]))


_US_CODES = frozenset(
    "al ak az ar ca co ct de dc fl ga hi id il in ia ks ky la me md ma mi mn ms mo "
    "mt ne nv nh nj nm ny nc nd oh ok or pa ri sc sd tn tx ut vt va wa wv wi wy".split())

# Most commercially important first — the order searches rotate through.
_WORLD_FIRST = ("US GB DE AE SG AU CA FR NL SA JP IT ES SE CH MY ZA BR MX ID IN IE BE "
                "PL DK NO FI AT QA IL KR CN HK TW TH VN PH NZ TR EG NG KE KW OM BH PT "
                "CZ RO GR HU LU AR CL CO PE BD LK PK NP MA").split()


# ── reading a location string ─────────────────────────────────────────────────

@lru_cache(maxsize=16384)
def _read(folded: str) -> tuple:
    """(countries, place keys named) for one folded location string."""
    hits = []                       # (segment index, _Entry)
    code = False
    for si, segment in enumerate(_SEGMENT.split(folded)):
        words = segment.split()
        n = len(words)
        found = False
        i = 0
        while i < n:
            for size in range(min(_MAX_WORDS, n - i), 0, -1):
                entry = _INDEX.get(" ".join(words[i:i + size]) if size > 1 else words[i])
                if entry is not None:
                    hits.append((si, entry))
                    i += size
                    found = True
                    break
            else:
                i += 1
        if not found and si > 0 and n == 1 and words[0] in _US_CODES:
            code = True
    countries = _decide(hits)
    if code and (not countries or "US" in countries):
        countries = frozenset({"US"})
    keys = frozenset().union(*(e.keys for _, e in hits)) if hits else frozenset()
    return countries, keys


def _decide(hits) -> frozenset:
    if not hits:
        return frozenset()
    named = [(si, e) for si, e in hits if e.only_countries]
    if named:                       # a country named in the string always wins …
        last = max(si for si, _ in named)
        base = frozenset().union(*(e.full for si, e in named if si == last))
        # … unless a later segment names somewhere outside it: "Lebanon,
        # Pennsylvania" is small place first, bigger place last — a US town
        if not any(si > last and not e.full & base for si, e in hits):
            return base
    last = max(si for si, _ in hits)
    top = [e for si, e in hits if si == last]
    rank = min(e.rank for e in top)
    top = [e for e in top if e.rank == rank]
    result = frozenset().union(*(e.full for e in top))
    # the other names narrow it — biggest units and later segments first — but
    # a name that disagrees ("London" in "London, Ontario") is outvoted, not obeyed
    rest = sorted(((si, e) for si, e in hits if not any(e is t for t in top)),
                  key=lambda h: (-h[0], h[1].rank))
    for _, e in rest:
        narrowed = result & e.full
        if narrowed:
            result = narrowed
    primary = frozenset().union(*(e.primary for _, e in hits))
    return (result & primary) or result


def countries_in(location_text) -> frozenset:
    """ISO2 codes a profile location string points to; empty = unknown."""
    if not isinstance(location_text, str) or not location_text.strip():
        return frozenset()
    return _read(_fold(location_text))[0]


def resolve(text):
    """The Place a name or alias means (any case, accents folded), or None.
    "Georgia" is the country; "Georgia, United States" is the state."""
    key = _key(text)
    if not key:
        return None
    place = _LABELS.get(key)
    if place is not None:
        return place
    entry = _INDEX.get(key)
    if entry is not None:
        return entry.best
    parts = [" ".join(p.split()) for p in _SEGMENT.split(_fold(text))]
    parts = [p for p in parts if p]
    if len(parts) >= 2:             # "Hyderabad, Pakistan": a name narrowed by where it is
        head = _INDEX.get(parts[0])
        if head is not None:
            countries, keys = _read(", ".join(parts[1:]))
            fits = [p for p in head.places
                    if _PARENT.get(p.key) in keys or p.countries & countries]
            if fits:
                return min(fits, key=lambda p: (_RANK[p.kind], head.places.index(p)))
    return None


def matches(location_text, place_text):
    """Does a profile location lie in a filter place? None = location unreadable.
    Region / country: the location's countries meet the place's. State: the state
    or one of its cities is named and no other country is. City: that city or
    its metro is named and no other country is. A place the gazetteer doesn't
    know is matched as a whole phrase."""
    folded = _fold(location_text) if isinstance(location_text, str) else ""
    if not _SEGMENT.sub(" ", folded).strip():
        return None
    place = resolve(place_text)
    if place is None:
        phrase = _key(place_text)
        if not phrase:
            return False
        return f" {phrase} " in f" {' '.join(_SEGMENT.sub(' ', folded).split())} "
    countries, keys = _read(folded)
    if not countries:
        return None
    if not countries & place.countries:
        return False
    if place.kind in ("region", "country"):
        return True
    return place.key in keys


def _inside(place) -> list:
    """The place and everything in it."""
    out = [place]
    if place.kind == "region":
        out += [r for r in _REGION_ORDER
                if r is not place and r.countries and r.countries <= place.countries]
        for country in _WORLD:
            if country.countries <= place.countries:
                out += _inside(country)
        return out
    for key in _DIRECT.get(place.key, ()):
        out += _inside(_BY_KEY[key])
    return out


def aliases_of(place_text) -> list:
    """Lower-case names of the place and of everything inside it — India gives
    "india", "bharat", "mumbai", "bombay", "gujarat", "vadodara", …; [] when the
    place is unknown. Used to keep an excluded place out of search queries."""
    place = resolve(place_text)
    if place is None:
        return []
    out, seen = [], set()
    for p in _inside(place):
        for name in _ALIASES[p.key]:
            if name not in seen:
                seen.add(name)
                out.append(name)
    return out


def suggest(text, limit: int = 8) -> list:
    """Labels for what is being typed: prefix matches before substring matches,
    and within each, regions and countries, then states, then cities."""
    q = _key(text)
    if not q or limit <= 0:
        return []
    scored = []
    for order, place in enumerate(_PLACES):
        best = None
        for name in _FOLDED[place.key]:
            if name == q:
                score = 0
            elif name.startswith(q):
                score = 1
            elif f" {q}" in f" {name}":     # a later word starts with it
                score = 2
            else:
                continue
            best = score if best is None else min(best, score)
        if best is not None:
            group = 0 if place.kind in ("region", "country") else _RANK[place.kind] - 1
            scored.append((best == 2, group, best, place.label.casefold(), order, place.label))
    scored.sort()
    return [row[-1] for row in scored[:limit]]


def _overlaps(p, x) -> bool:
    if not p.countries & x.countries:
        return False
    if x.kind in ("region", "country") or p.kind in ("region", "country"):
        return True
    return p.key == x.key or _PARENT.get(p.key) == x.key or _PARENT.get(x.key) == p.key


def _open(item, excluded, excluded_text) -> list:
    """The phrases an include (or a world country) contributes once exclusions
    are taken out: itself when clear, nothing when an exclusion covers it, or
    its parts when an exclusion sits inside it (India minus Gujarat → the
    other states)."""
    if isinstance(item, str):
        phrase = _key(item)
        if not phrase or phrase in excluded_text or any(
                f" {_key(name)} " in f" {phrase} "
                for x in excluded for name in _ALIASES[x.key]):
            return []
        return [item]
    if _key(item.label) in excluded_text:
        return []
    blockers = [x for x in excluded if _overlaps(item, x)]
    if not blockers:
        return [item]
    if item.kind == "region":
        kids = [c for c in _WORLD if c.countries <= item.countries]
    elif item.kind == "city" or any(_RANK[x.kind] <= _RANK[item.kind] for x in blockers):
        return []
    else:
        kids = [_BY_KEY[k] for k in _DIRECT.get(item.key, ())]
    out = []
    for kid in kids:
        out += _open(kid, excluded, excluded_text)
    return out


def regions_outside(excluded, included=()) -> list:
    """Search-location phrases covering the world (or the includes) minus the
    exclusions, most commercially important first. Never a phrase whose place
    meets an exclusion — an excluded region removes all its countries."""
    ex, ex_text = [], set()
    for value in _texts(excluded):
        place = resolve(value)
        if place is not None:
            ex.append(place)
        elif _key(value):
            ex_text.add(_key(value))
    roots = [resolve(v) or v for v in _texts(included)] or list(_WORLD)
    out, seen = [], set()
    for root in roots:
        for item in _open(root, ex, ex_text):
            label = item if isinstance(item, str) else item.label
            if label.casefold() not in seen:
                seen.add(label.casefold())
                out.append(label)
    return out


# ══ data ══════════════════════════════════════════════════════════════════════
# Names are written lower-case; the label is always a name too. "&" folds to
# "and", dots and apostrophes drop, accents fold — so each is written once.

# slug, label, aliases, members (ISO2 codes, or @slug of a region listed above it)
_REGIONS = (
    ("central_america", "Central America", "", "BZ CR SV GT HN NI PA"),
    ("caribbean", "Caribbean", "the caribbean|caribbean islands|west indies",
     "AG BS BB CU DM DO GD HT JM KN LC VC TT PR AW CW KY"),
    ("south_america", "South America", "", "AR BO BR CL CO EC GY PY PE SR UY VE"),
    ("latin_america", "Latin America", "latam|latin america and the caribbean",
     "MX @central_america @caribbean @south_america"),
    ("north_america", "North America", "noram", "US CA MX PR BM GL"),
    ("americas", "Americas", "the americas", "@north_america @latin_america"),
    ("european_union", "European Union", "eu|e.u.",
     "AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE"),
    ("western_europe", "Western Europe", "",
     "GB IE FR BE NL LU DE AT CH LI MC ES PT IT AD SM VA MT"),
    ("eastern_europe", "Eastern Europe", "central and eastern europe|cee",
     "PL CZ SK HU RO BG UA BY MD RU EE LV LT SI HR RS BA ME MK AL XK"),
    ("nordics", "Nordics", "nordic countries|nordic region|scandinavia", "DK FI IS NO SE"),
    ("dach", "DACH", "dach region", "DE AT CH"),
    ("benelux", "Benelux", "", "BE NL LU"),
    ("europe", "Europe", "continental europe",
     "@european_union @western_europe @eastern_europe @nordics GB IS NO CH LI MC AD SM VA GR CY TR"),
    ("gcc", "GCC", "gulf countries|gulf region|gulf cooperation council|arabian gulf",
     "AE SA QA KW BH OM"),
    ("middle_east", "Middle East", "mideast|west asia|middle east region",
     "@gcc IL JO LB SY IQ IR YE PS TR EG"),
    ("north_africa", "North Africa", "northern africa|maghreb", "DZ EG LY MA TN SD"),
    ("mena", "MENA", "middle east and north africa", "@middle_east @north_africa"),
    ("sub_saharan_africa", "Sub-Saharan Africa", "subsaharan africa",
     "AO BJ BW BF BI CV CM CF TD KM CG CD CI DJ GQ ER SZ ET GA GM GH GN GW KE LS LR MG "
     "MW ML MR MU MZ NA NE NG RW ST SN SC SL SO ZA SS TZ TG UG ZM ZW"),
    ("africa", "Africa", "african continent", "@north_africa @sub_saharan_africa"),
    ("east_asia", "East Asia", "far east", "CN JP KR KP TW HK MO MN"),
    ("southeast_asia", "Southeast Asia", "south east asia|asean",
     "BN KH ID LA MY MM PH SG TH TL VN"),
    ("south_asia", "South Asia", "indian subcontinent|saarc", "IN PK BD LK NP BT MV AF"),
    ("central_asia", "Central Asia", "", "KZ UZ TM KG TJ"),
    ("oceania", "Oceania", "pacific islands|australasia",
     "AU NZ PG FJ SB VU WS TO KI TV NR FM MH PW"),
    ("anz", "ANZ", "australia and new zealand|australia new zealand", "AU NZ"),
    ("apac", "Asia Pacific", "apac|asia pac|asiapac",
     "@east_asia @southeast_asia @south_asia @oceania"),
    ("asia", "Asia", "",
     "@east_asia @southeast_asia @south_asia @central_asia @gcc IL JO LB SY IQ IR YE PS GE AM AZ"),
    ("emea", "EMEA", "europe middle east and africa", "@europe @middle_east @africa"),
)

# ISO2|Label|aliases…
_COUNTRIES = """
AF|Afghanistan
AL|Albania
DZ|Algeria
AD|Andorra
AO|Angola
AG|Antigua and Barbuda|antigua
AR|Argentina
AM|Armenia
AU|Australia
AT|Austria|osterreich
AZ|Azerbaijan
BS|Bahamas|the bahamas
BH|Bahrain
BD|Bangladesh
BB|Barbados
BY|Belarus
BE|Belgium|belgie|belgique
BZ|Belize
BJ|Benin
BT|Bhutan
BO|Bolivia
BA|Bosnia and Herzegovina|bosnia
BW|Botswana
BR|Brazil|brasil
BN|Brunei|brunei darussalam
BG|Bulgaria
BF|Burkina Faso
BI|Burundi
CV|Cape Verde|cabo verde
KH|Cambodia
CM|Cameroon
CA|Canada
CF|Central African Republic
TD|Chad
CL|Chile
CN|China|mainland china|peoples republic of china|prc
CO|Colombia
KM|Comoros
CG|Republic of the Congo|congo-brazzaville|congo
CD|Democratic Republic of the Congo|dr congo|drc|congo-kinshasa|congo
CR|Costa Rica
CI|Ivory Coast|cote d'ivoire
HR|Croatia|hrvatska
CU|Cuba
CY|Cyprus
CZ|Czech Republic|czechia
DK|Denmark|danmark
DJ|Djibouti
DM|Dominica
DO|Dominican Republic
EC|Ecuador
EG|Egypt
SV|El Salvador
GQ|Equatorial Guinea
ER|Eritrea
EE|Estonia
SZ|Eswatini|swaziland
ET|Ethiopia
FJ|Fiji
FI|Finland|suomi
FR|France
GA|Gabon
GM|Gambia|the gambia
GE|Georgia
DE|Germany|deutschland
GH|Ghana
GR|Greece|hellas
GD|Grenada
GT|Guatemala
GN|Guinea
GW|Guinea-Bissau
GY|Guyana
HT|Haiti
HN|Honduras
HU|Hungary|magyarorszag
IS|Iceland
IN|India|bharat|hindustan|republic of india
ID|Indonesia
IR|Iran
IQ|Iraq
IE|Ireland|republic of ireland|eire
IL|Israel
IT|Italy|italia
JM|Jamaica
JP|Japan|nippon
JO|Jordan
KZ|Kazakhstan
KE|Kenya
KI|Kiribati
KP|North Korea
KR|South Korea|korea|republic of korea
XK|Kosovo
KW|Kuwait
KG|Kyrgyzstan
LA|Laos|lao pdr
LV|Latvia
LB|Lebanon
LS|Lesotho
LR|Liberia
LY|Libya
LI|Liechtenstein
LT|Lithuania
LU|Luxembourg
MG|Madagascar
MW|Malawi
MY|Malaysia
MV|Maldives
ML|Mali
MT|Malta
MH|Marshall Islands
MR|Mauritania
MU|Mauritius
MX|Mexico
FM|Micronesia
MD|Moldova
MC|Monaco
MN|Mongolia
ME|Montenegro
MA|Morocco
MZ|Mozambique
MM|Myanmar|burma
NA|Namibia
NR|Nauru
NP|Nepal
NL|Netherlands|the netherlands|holland|nederland
NZ|New Zealand|aotearoa
NI|Nicaragua
NE|Niger
NG|Nigeria
MK|North Macedonia|macedonia
NO|Norway|norge
OM|Oman
PK|Pakistan
PW|Palau
PS|Palestine|palestinian territories|state of palestine
PA|Panama
PG|Papua New Guinea
PY|Paraguay
PE|Peru
PH|Philippines|the philippines
PL|Poland|polska
PT|Portugal
QA|Qatar
RO|Romania
RU|Russia|russian federation
RW|Rwanda
KN|Saint Kitts and Nevis|st kitts and nevis
LC|Saint Lucia|st lucia
VC|Saint Vincent and the Grenadines|st vincent and the grenadines
WS|Samoa
SM|San Marino
ST|Sao Tome and Principe
SA|Saudi Arabia|ksa|kingdom of saudi arabia|saudi
SN|Senegal
RS|Serbia
SC|Seychelles
SL|Sierra Leone
SG|Singapore
SK|Slovakia
SI|Slovenia
SB|Solomon Islands
SO|Somalia
ZA|South Africa|rsa
SS|South Sudan
ES|Spain|espana
LK|Sri Lanka|ceylon
SD|Sudan
SR|Suriname
SE|Sweden|sverige
CH|Switzerland|schweiz|suisse|svizzera
SY|Syria
TW|Taiwan
TJ|Tajikistan
TZ|Tanzania
TH|Thailand
TL|Timor-Leste|east timor
TG|Togo
TO|Tonga
TT|Trinidad and Tobago|trinidad
TN|Tunisia
TR|Turkey|turkiye
TM|Turkmenistan
TV|Tuvalu
UG|Uganda
UA|Ukraine
AE|United Arab Emirates|uae|u.a.e.|emirates
GB|United Kingdom|uk|u.k.|great britain|britain
US|United States|us|u.s.|usa|u.s.a.|united states of america|america|new england
UY|Uruguay
UZ|Uzbekistan
VU|Vanuatu
VA|Vatican City|holy see
VE|Venezuela
VN|Vietnam|viet nam
YE|Yemen
ZM|Zambia
ZW|Zimbabwe
HK|Hong Kong|hong kong sar
MO|Macau|macao
PR|Puerto Rico
BM|Bermuda
GL|Greenland
AW|Aruba
CW|Curacao
KY|Cayman Islands
"""

# States / provinces per country: one per line, "Label|aliases…".
_STATES: dict = {}
# Cities per country: one state per line, "State: City|aliases…; City|aliases…".
# "-" as the state = a city filed straight under the country. A "~" before a city
# makes it SECONDARY — it counts only when something else in the string agrees.
_CITIES: dict = {}

# India in depth: every state and union territory, the big and the industrial
# cities, the old names people still write, and LinkedIn's metro forms.
_STATES["IN"] = """
Maharashtra|maharastra
Gujarat|gujrat
Karnataka
Tamil Nadu|tamilnadu
Telangana
Andhra Pradesh
Kerala
Delhi|nct of delhi|national capital territory of delhi
Haryana
Uttar Pradesh
West Bengal
Rajasthan
Madhya Pradesh
Punjab
Bihar
Jharkhand
Odisha|orissa
Chhattisgarh|chattisgarh
Assam
Uttarakhand|uttaranchal
Himachal Pradesh
Goa
Jammu and Kashmir|j and k|kashmir
Ladakh
Chandigarh
Puducherry|pondicherry
Dadra and Nagar Haveli and Daman and Diu|dadra and nagar haveli|daman and diu
Andaman and Nicobar Islands|andaman and nicobar
Lakshadweep
Arunachal Pradesh
Manipur
Meghalaya
Mizoram
Nagaland
Sikkim
Tripura
"""
_CITIES["IN"] = """
Maharashtra: Mumbai|bombay|greater mumbai|greater mumbai area|mumbai metropolitan region|mumbai area|mmr; Pune|poona|pune area|greater pune area|pune/pimpri-chinchwad area; Navi Mumbai|new bombay; Thane; Nagpur; Nashik|nasik; Aurangabad|chhatrapati sambhajinagar|sambhajinagar; Pimpri-Chinchwad|pimpri|chinchwad; Solapur|sholapur; Kolhapur; Amravati; Kalyan-Dombivli|kalyan|dombivli; Vasai-Virar|vasai|virar; Bhiwandi; Panvel; Satara; Sangli; Jalgaon; Ahmednagar|ahilyanagar; Latur; Nanded
Gujarat: Ahmedabad|amdavad|ahmedabad area|greater ahmedabad area; Vadodara|baroda; Surat; Rajkot; Gandhinagar|gift city; Bhavnagar; Jamnagar; Anand; Bharuch; Ankleshwar; Vapi; Morbi; Mehsana; Junagadh; Gandhidham; Nadiad; Valsad; Halol; Sanand
Karnataka: Bengaluru|bangalore|greater bengaluru area|bengaluru area|greater bangalore area|bangalore urban|bengaluru urban; Mysuru|mysore; Mangaluru|mangalore; Hubballi|hubli|hubli-dharwad|hubballi-dharwad; Belagavi|belgaum; Kalaburagi|gulbarga; Davanagere; Ballari|bellary; Tumakuru|tumkur; Shivamogga|shimoga; Udupi
Tamil Nadu: Chennai|madras|greater chennai area|chennai area; Coimbatore|kovai; Madurai; Tiruchirappalli|trichy|tiruchi; Salem; Tiruppur|tirupur; Erode; Vellore; Tirunelveli; Hosur; Thoothukudi|tuticorin; Sriperumbudur
Telangana: Hyderabad|greater hyderabad area|hyderabad area; Secunderabad; Warangal; Karimnagar; Nizamabad
Andhra Pradesh: Visakhapatnam|vizag|vishakhapatnam; Vijayawada; Guntur; Nellore; Tirupati; Kakinada; Amaravati; Kurnool; Rajahmundry|rajamahendravaram; Anantapur
Kerala: Thiruvananthapuram|trivandrum; Kochi|cochin|ernakulam; Kozhikode|calicut; Thrissur|trichur; Kollam|quilon; Kannur|cannanore; Palakkad|palghat
West Bengal: Kolkata|calcutta|greater kolkata area|kolkata area; Howrah; Durgapur; Asansol; Siliguri; Kharagpur; Haldia
Delhi: New Delhi|delhi|delhi ncr|ncr|national capital region|greater delhi area|new delhi area|delhi area
Haryana: Gurugram|gurgaon; Faridabad; Panipat; Sonipat|sonepat; Ambala; Karnal; Hisar; Rohtak; Manesar; Bahadurgarh
Uttar Pradesh: Noida; Greater Noida; Ghaziabad; Lucknow; Kanpur|cawnpore; Agra; Varanasi|benares|banaras; Prayagraj|allahabad; Meerut; Aligarh; Bareilly; Moradabad; Gorakhpur; Mathura; Jhansi
Rajasthan: Jaipur; Jodhpur; Udaipur; Kota; Bikaner; Ajmer; Bhilwara; Alwar; Neemrana; Bhiwadi
Madhya Pradesh: Indore; Bhopal; Jabalpur; Gwalior; Ujjain; Dewas; Pithampur; Satna; Ratlam
Punjab: Ludhiana; Amritsar; Jalandhar|jullundur; Mohali|sas nagar; Patiala; Bathinda|bhatinda
Bihar: Patna; Gaya; Bhagalpur; Muzaffarpur
Jharkhand: Ranchi; Jamshedpur|tatanagar; Dhanbad; Bokaro|bokaro steel city
Odisha: Bhubaneswar|bhubaneshwar; Cuttack; Rourkela; Sambalpur
Chhattisgarh: Raipur; Bhilai; Korba
Assam: Guwahati|gauhati; Dibrugarh; Silchar
Uttarakhand: Dehradun|dehra dun; Haridwar|hardwar; Rudrapur; Haldwani; Roorkee
Himachal Pradesh: Shimla|simla; Baddi; Solan; Dharamshala|dharamsala
Goa: Panaji|panjim; Margao|madgaon; Mapusa
Jammu and Kashmir: Srinagar; Jammu
Dadra and Nagar Haveli and Daman and Diu: Silvassa; Daman
Meghalaya: Shillong
Manipur: Imphal
Tripura: Agartala
Mizoram: Aizawl
Nagaland: Kohima; Dimapur
Arunachal Pradesh: Itanagar
Sikkim: Gangtok
Ladakh: Leh
"""

# The neighbours whose city and state names also exist in India, so they never
# read as India.
_STATES["PK"] = """
Sindh|sind
Punjab
Islamabad Capital Territory|ict
Khyber Pakhtunkhwa|kpk|khyber-pakhtunkhwa
Balochistan|baluchistan
Gilgit-Baltistan
Azad Kashmir|azad jammu and kashmir|ajk|kashmir
"""
_CITIES["PK"] = """
Sindh: ~Hyderabad; Karachi; Sukkur
Punjab: Lahore; Faisalabad; Rawalpindi; Multan; Gujranwala; Sialkot
Islamabad Capital Territory: Islamabad
Khyber Pakhtunkhwa: Peshawar
Balochistan: Quetta
"""
_CITIES["BD"] = """
-: Dhaka|dacca; Chittagong|chattogram; Khulna; Sylhet; Rajshahi; Gazipur; Narayanganj
"""
_CITIES["LK"] = """
-: Colombo; Kandy; Galle; Jaffna; Negombo; Sri Jayawardenepura Kotte|kotte
"""
_CITIES["NP"] = """
-: Kathmandu; Pokhara; Biratnagar; Birgunj; Bhaktapur
"""

# United States: every state + DC, and the metros LinkedIn writes.
_STATES["US"] = """
California
New York
Texas
Florida
Illinois
Washington|washington state
Massachusetts
Pennsylvania
Georgia
New Jersey
North Carolina
Virginia
Michigan
Ohio
Arizona
Colorado
Minnesota
Tennessee
Oregon
Maryland
District of Columbia|washington dc|washington d.c.
Indiana
Missouri
Wisconsin
Utah
Nevada
Connecticut
Louisiana
Kentucky
Oklahoma
South Carolina
Alabama
Iowa
Kansas
Arkansas
Mississippi
Nebraska
New Mexico
Idaho
West Virginia
Hawaii
New Hampshire
Maine
Rhode Island
Montana
Delaware
South Dakota
North Dakota
Alaska
Vermont
Wyoming
"""
_CITIES["US"] = """
California: San Francisco|san francisco bay area|bay area|sf bay area|silicon valley; Los Angeles|los angeles metropolitan area|greater los angeles area|greater los angeles; San Jose; San Diego|greater san diego area; Sacramento; Oakland; Palo Alto; Mountain View; Irvine; Santa Clara; Sunnyvale
New York: New York City|nyc|new york|new york city metropolitan area|greater new york city area|manhattan|brooklyn; Buffalo; Rochester; Albany
Texas: Dallas|dallas-fort worth metroplex|dallas-fort worth|dfw; Fort Worth; Houston|greater houston|houston metropolitan area; Austin|austin texas metropolitan area; San Antonio; Plano; El Paso
Illinois: Chicago|greater chicago area|chicagoland
Washington: Seattle|greater seattle area|seattle metropolitan area; Redmond; Bellevue; Spokane
District of Columbia: Washington DC-Baltimore Area|washington metropolitan area|dc metro area|greater washington dc area
Massachusetts: Boston|greater boston|greater boston area
Georgia: Atlanta|atlanta metropolitan area|greater atlanta area|metro atlanta
Florida: Miami|miami-fort lauderdale area|south florida; Orlando; Tampa|tampa bay area; Jacksonville
Pennsylvania: Philadelphia|greater philadelphia|philly; Pittsburgh|greater pittsburgh region
Arizona: Phoenix|greater phoenix area; Scottsdale; Tucson
Colorado: Denver|denver metropolitan area; Boulder
Michigan: Detroit|detroit metropolitan area|metro detroit; Ann Arbor; Grand Rapids
Minnesota: Minneapolis|minneapolis-st. paul|twin cities
Ohio: Columbus; Cleveland; Cincinnati
North Carolina: Charlotte; Raleigh|raleigh-durham|research triangle
Tennessee: Nashville; Memphis
Oregon: Portland
Nevada: Las Vegas
Utah: Salt Lake City
Missouri: St. Louis|saint louis; Kansas City
Indiana: Indianapolis|indy; Fort Wayne
Wisconsin: Milwaukee
Maryland: Baltimore
New Jersey: Newark; Jersey City
Louisiana: New Orleans
Kentucky: Louisville
Connecticut: Hartford; Stamford
"""

_STATES["GB"] = """
England
Scotland
Wales
Northern Ireland
"""
_CITIES["GB"] = """
England: London|greater london|greater london area|london area|city of london; Manchester|greater manchester; Birmingham; Leeds; Liverpool; Bristol; Sheffield; Newcastle upon Tyne|newcastle; Nottingham; Leicester; Cambridge; Oxford; Reading; Milton Keynes; Southampton; Coventry
Scotland: Edinburgh; Glasgow; Aberdeen; Dundee
Wales: Cardiff; Swansea
Northern Ireland: Belfast
"""

_STATES["CA"] = """
Ontario
Quebec
British Columbia
Alberta
Manitoba
Saskatchewan
Nova Scotia
New Brunswick
Newfoundland and Labrador|newfoundland
Prince Edward Island
Northwest Territories
Yukon
Nunavut
"""
_CITIES["CA"] = """
Ontario: Toronto|greater toronto area|greater toronto|gta; Ottawa; Mississauga; Brampton; Hamilton; Waterloo; Kitchener
Quebec: Montreal|greater montreal; Quebec City
British Columbia: Vancouver|greater vancouver|metro vancouver
Alberta: Calgary; Edmonton
Manitoba: Winnipeg
Saskatchewan: Saskatoon; Regina
"""

_STATES["AU"] = """
New South Wales|nsw
Victoria
Queensland|qld
Western Australia
South Australia
Tasmania
Australian Capital Territory
Northern Territory
"""
_CITIES["AU"] = """
New South Wales: Sydney|greater sydney
Victoria: Melbourne|greater melbourne
Queensland: Brisbane; Gold Coast
Western Australia: Perth
South Australia: Adelaide
Australian Capital Territory: Canberra
Tasmania: Hobart
Northern Territory: Darwin
"""

_STATES["DE"] = """
Bavaria|bayern
Berlin
Hamburg
Bremen
Hesse|hessen
North Rhine-Westphalia|nordrhein-westfalen|nrw
Baden-Wurttemberg|baden-wuerttemberg
Lower Saxony|niedersachsen
Saxony|sachsen
Saxony-Anhalt|sachsen-anhalt
Brandenburg
Rhineland-Palatinate|rheinland-pfalz
Saarland
Schleswig-Holstein
Mecklenburg-Vorpommern
Thuringia|thuringen|thueringen
"""
_CITIES["DE"] = """
Bavaria: Munich|munchen|muenchen|greater munich metropolitan area; Nuremberg|nurnberg|nuernberg; Augsburg
North Rhine-Westphalia: Cologne|koln|koeln; Dusseldorf|duesseldorf; Dortmund; Essen; Bonn
Hesse: Frankfurt|frankfurt am main|frankfurt rhine-main metropolitan area; Wiesbaden; Darmstadt
Baden-Wurttemberg: Stuttgart|stuttgart region; Karlsruhe; Mannheim; Heidelberg
Lower Saxony: Hanover|hannover
Saxony: Dresden; Leipzig
"""

_STATES["FR"] = """
Ile-de-France
Auvergne-Rhone-Alpes
Provence-Alpes-Cote d'Azur|paca
Occitanie
Nouvelle-Aquitaine
Hauts-de-France
Grand Est
Brittany|bretagne
Normandy|normandie
Pays de la Loire
Centre-Val de Loire
Bourgogne-Franche-Comte
Corsica|corse
"""
_CITIES["FR"] = """
Ile-de-France: Paris|greater paris metropolitan region|paris area
Auvergne-Rhone-Alpes: Lyon; Grenoble
Provence-Alpes-Cote d'Azur: Marseille; Nice
Occitanie: Toulouse; Montpellier
Nouvelle-Aquitaine: Bordeaux
Hauts-de-France: Lille
Grand Est: Strasbourg
Pays de la Loire: Nantes
Brittany: Rennes
"""

_STATES["NL"] = """
North Holland|noord-holland
South Holland|zuid-holland
Utrecht
North Brabant|noord-brabant
Gelderland
Overijssel
Limburg
Groningen
Friesland|fryslan
Drenthe
Flevoland
Zeeland
"""
_CITIES["NL"] = """
North Holland: Amsterdam|amsterdam area; Haarlem
South Holland: Rotterdam; The Hague|den haag; Leiden; Delft
North Brabant: Eindhoven; Tilburg; Breda
"""

_STATES["AE"] = """
Dubai|emirate of dubai
Abu Dhabi|emirate of abu dhabi
Sharjah
Ajman
Ras Al Khaimah|ras al-khaimah
Fujairah
Umm Al Quwain|umm al-quwain
"""
_CITIES["AE"] = """
Abu Dhabi: Al Ain
Dubai: Jebel Ali
"""

_STATES["SA"] = """
Riyadh Region|riyadh province
Makkah Region|makkah province|mecca region
Eastern Province|eastern region|ash sharqiyah
Madinah Region|madinah province|medina region
Al-Qassim|qassim
Asir
Tabuk
"""
_CITIES["SA"] = """
Riyadh Region: Riyadh
Makkah Region: Jeddah|jiddah|jedda; Mecca|makkah; Taif
Eastern Province: Dammam; Al Khobar|khobar; Dhahran; Jubail|al jubail; Al Ahsa|hofuf
Madinah Region: Medina|madinah; Yanbu
Al-Qassim: Buraidah
"""
_CITIES["QA"] = """
-: Doha; Al Rayyan|ar rayyan; Lusail; Al Wakrah; Ras Laffan; Mesaieed
"""

_STATES["CN"] = """
Beijing|peking
Shanghai
Tianjin
Chongqing
Guangdong
Zhejiang
Jiangsu
Shandong
Sichuan
Hubei
Fujian
Henan
Hunan
Anhui
Liaoning
Shaanxi
Hebei
"""
_CITIES["CN"] = """
Guangdong: Shenzhen; Guangzhou|canton; Dongguan; Foshan
Zhejiang: Hangzhou; Ningbo
Jiangsu: Suzhou; Nanjing|nanking; Wuxi
Sichuan: Chengdu
Hubei: Wuhan
Fujian: Xiamen
Shandong: Qingdao; Jinan
Shaanxi: Xi'an|xian
Liaoning: Dalian; Shenyang
"""

_STATES["JP"] = """
Tokyo|tokyo metropolis|greater tokyo area
Osaka
Kanagawa
Aichi
Hokkaido
Fukuoka
Kyoto
Hyogo
Saitama
Chiba
Hiroshima
Miyagi
Shizuoka
"""
_CITIES["JP"] = """
Kanagawa: Yokohama; Kawasaki
Aichi: Nagoya
Hokkaido: Sapporo
Hyogo: Kobe
Miyagi: Sendai
"""

# The business capitals of everywhere else, so a city-only profile still reads.
_CITIES["SG"] = "-: Jurong"
_CITIES["IL"] = "-: Tel Aviv|tel aviv-yafo; Jerusalem; Haifa"
_CITIES["TR"] = "-: Istanbul; Ankara; Izmir"
_CITIES["EG"] = "-: Cairo; Alexandria; Giza"
_CITIES["NG"] = "-: Lagos; Abuja"
_CITIES["KE"] = "-: Nairobi; Mombasa"
_CITIES["ZA"] = "-: Johannesburg; Cape Town; Durban; Pretoria"
_CITIES["BR"] = "-: Sao Paulo; Rio de Janeiro; Belo Horizonte; Brasilia"
_CITIES["MX"] = "-: Mexico City|ciudad de mexico|cdmx; Monterrey; Guadalajara"
_CITIES["AR"] = "-: Buenos Aires"
_CITIES["CO"] = "-: Bogota; Medellin"
_CITIES["PE"] = "-: Lima"
_CITIES["CL"] = "-: Santiago"
_CITIES["ES"] = "-: Madrid; Barcelona; Valencia; Seville|sevilla"
_CITIES["IT"] = "-: Milan|milano; Rome|roma; Turin|torino"
_CITIES["CH"] = "-: Zurich; Geneva|geneve; Basel; Lausanne"
_CITIES["SE"] = "-: Stockholm; Gothenburg|goteborg; Malmo"
_CITIES["DK"] = "-: Copenhagen|kobenhavn"
_CITIES["NO"] = "-: Oslo"
_CITIES["FI"] = "-: Helsinki"
_CITIES["AT"] = "-: Vienna|wien"
_CITIES["BE"] = "-: Brussels|bruxelles|brussel; Antwerp|antwerpen"
_CITIES["IE"] = "-: Dublin; Cork"
_CITIES["PT"] = "-: Lisbon|lisboa; Porto"
_CITIES["PL"] = "-: Warsaw|warszawa; Krakow; Wroclaw"
_CITIES["CZ"] = "-: Prague|praha"
_CITIES["RU"] = "-: Moscow; Saint Petersburg|st petersburg"
_CITIES["MY"] = "-: Kuala Lumpur; Penang; Johor Bahru"
_CITIES["ID"] = "-: Jakarta; Surabaya; Bandung"
_CITIES["TH"] = "-: Bangkok"
_CITIES["PH"] = "-: Manila|metro manila; Cebu"
_CITIES["VN"] = "-: Ho Chi Minh City|saigon; Hanoi"
_CITIES["KR"] = "-: Seoul"
_CITIES["TW"] = "-: Taipei"
_CITIES["NZ"] = "-: Auckland; Wellington"
_CITIES["OM"] = "-: Muscat"
_CITIES["BH"] = "-: Manama"
_CITIES["KW"] = "-: Kuwait City"
_CITIES["JO"] = "-: Amman"
_CITIES["LB"] = "-: Beirut"
_CITIES["MA"] = "-: Casablanca; Rabat"
_CITIES["GE"] = "-: Tbilisi; Batumi"

# ── build the index ────────────────────────────────────────────────────────────


def _slug(name: str) -> str:
    return _key(name).replace(" ", "_")


def _build() -> None:
    global _MAX_WORDS
    pending: dict = {}

    def add(key, name, kind, countries, aliases, main=True, context=""):
        while key in _BY_KEY:
            key += "_"
        label = name if _key(name) not in _LABELS else f"{name}, {context}"
        place = Place(key, label, kind, frozenset(countries))
        _PLACES.append(place)
        _BY_KEY[key] = place
        _LABELS[_key(label)] = place
        names = []
        for raw in [name] + list(aliases):
            raw = " ".join(raw.split()).lower()
            if raw and raw not in names:
                names.append(raw)
        _ALIASES[key] = names
        _FOLDED[key] = sorted({_key(n) for n in names} | {_key(label)})
        for n in names:
            pending.setdefault(_key(n), []).append((place, main))
        return place

    regions = {}
    for slug, label, aliases, members in _REGIONS:
        codes = set()
        for m in members.split():
            codes |= regions[m[1:]] if m.startswith("@") else {m}
        regions[slug] = codes
        _REGION_ORDER.append(add(f"region:{slug}", label, "region", codes,
                                 aliases.split("|") if aliases else ()))

    countries = {}
    for line in _COUNTRIES.strip().splitlines():
        iso, name, *aliases = line.split("|")
        countries[iso] = add(f"country:{iso}", name, "country", {iso}, aliases)
    first = [countries[c] for c in _WORLD_FIRST]
    rest = sorted((p for c, p in countries.items() if c not in _WORLD_FIRST),
                  key=lambda p: p.label)
    _WORLD.extend(first + rest)

    states = {}
    for iso, block in _STATES.items():
        country = countries[iso]
        for line in block.strip().splitlines():
            name, *aliases = line.strip().split("|")
            place = add(f"state:{iso}:{_slug(name)}", name, "state", {iso}, aliases,
                        context=country.label)
            states[(iso, _key(name))] = place
            _PARENT[place.key] = country.key
            _DIRECT.setdefault(country.key, []).append(place.key)

    for iso, block in _CITIES.items():
        country = countries[iso]
        for line in block.strip().splitlines():
            state_name, _, cities = line.partition(":")
            state = None if state_name.strip() == "-" else states[(iso, _key(state_name))]
            parent = state or country
            for item in cities.split(";"):
                if not item.strip():
                    continue
                name, *aliases = item.strip().split("|")
                main = not name.startswith("~")
                name = name.lstrip("~")
                place = add(f"city:{iso}:{_slug(name)}", name, "city", {iso}, aliases,
                            main=main, context=country.label)
                _PARENT[place.key] = parent.key
                _DIRECT.setdefault(parent.key, []).append(place.key)

    for phrase, pairs in pending.items():
        if phrase:
            _INDEX[phrase] = _Entry(pairs)
            _MAX_WORDS = max(_MAX_WORDS, len(phrase.split()))


_build()
