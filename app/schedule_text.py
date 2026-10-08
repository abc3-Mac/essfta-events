"""Read an interclub schedule as the governors actually circulate it — a Word
document (or pasted text) with one trial per line:

    TENTATIVE (revised 7/14/26)
    2027 ESSFTA Midwest Interclub Field Trial Schedule
    SPRING:
    3/13-14     Sportsmen's Spaniel Club of Calumet
    3/28        Easter Sunday
    9/17        Tilden Valley Eng. Springer Spaniel Club (Fri Open)
    10/31-11/1  Engl. Springer Spaniel Field Trial Club of Illinois

A plain parser does the work — same answer every time. The year and region come
from the title line, holidays are recognised and set aside, a "(Fri Open)"-style
parenthesis becomes a note, and club spellings are matched to the clubs already
on the calendar. Lines it cannot read are returned for the optional local-AI
fallback (see read_with_llm) or reported back to the governor; nothing here
writes to the database.
"""
import difflib
import io
import json
import os
import re
import urllib.request
import zipfile
from datetime import date
from xml.etree import ElementTree

REGION_WORDS = [  # longest first; "Midwest"/"Western" are how the documents spell them
    ("Rocky Mountain", r"rocky\s*m(ou)?n?ta?i?n?s?"),
    ("Mid East", r"mid[\s-]*east(ern)?"),
    ("Mid West", r"mid[\s-]*west(ern)?"),
    ("East", r"east(ern)?"),
    ("West", r"west(ern)?"),
]

HOLIDAYS = re.compile(
    r"\b(easter|christmas|thanksgiving|new year|memorial day|labor day|mother'?s day|"
    r"father'?s day|independence day|july 4|fourth of july|good friday|holiday)\b", re.I)

DATE_LINE = re.compile(
    r"^\s*(?P<m1>\d{1,2})/(?P<d1>\d{1,2})(?:/(?P<y1>\d{2,4}))?"
    r"(?:\s*[-–—]\s*(?:(?P<m2>\d{1,2})/)?(?P<d2>\d{1,2})(?:/\d{2,4})?)?"
    r"\s+(?P<rest>\S.*?)\s*$")

DAYS_ONLY = re.compile(r"^(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*"
                       r"(\s*[-–&/]\s*(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*)?$", re.I)
STATUS_WORDS = re.compile(r"\b(tentative|draft|revised|final|approved|updated)\b", re.I)


# ---------- getting text out of the file ----------

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_text(data: bytes) -> str:
    """Paragraphs of a .docx as lines, tabs kept — stdlib only (no python-docx)."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ElementTree.fromstring(z.read("word/document.xml"))
    lines = []
    for p in root.iter(W + "p"):
        parts = []
        for el in p.iter():
            if el.tag == W + "t":
                parts.append(el.text or "")
            elif el.tag == W + "tab":
                parts.append("\t")
            elif el.tag in (W + "br", W + "cr"):
                parts.append("\n")
        lines.append("".join(parts))
    return "\n".join(lines)


def file_text(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".docx") or data[:2] == b"PK":
        return docx_text(data)
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


# ---------- club-name matching ----------

_ABBREV = [
    (r"\beng\.?\b|\bengl\.?\b", "english"),
    (r"\bess\b", "english springer spaniel"),
    (r"\bspr\.?\b", "springer"),
    (r"\bassn\.?\b|\bassoc\.?\b", "association"),
    (r"\bft\b", "field trial"),
    (r"\bst\.?\b", "saint"),
    (r"\bmn\b", "minnesota"),
    (r"\bwi\b", "wisconsin"),
    (r"&", " and "),
]
_FILLER = re.compile(r"\b(the|club|inc|spring|fall|trial|field trial)\b")


def club_key(name: str) -> str:
    s = (name or "").lower().replace("’", "'")
    for pat, rep in _ABBREV:
        s = re.sub(pat, rep, s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = _FILLER.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def match_club(name: str, known: list[str]):
    """(canonical club, how) — 'exact', 'spelling' (same club, different
    abbreviations), 'close' (fuzzy, shown to the governor) or None (new club)."""
    if not known:
        return name, None
    for k in known:
        if k.lower() == name.lower():
            return k, "exact"
    key = club_key(name)
    keyed = {}
    for k in known:
        keyed.setdefault(club_key(k), k)
    if key in keyed:
        return keyed[key], "spelling"
    # typo-level only: same word count, very close spelling. "Minnesota ESSC" must
    # never become "Minnesota Heartland ESSC".
    best = difflib.get_close_matches(key, list(keyed), n=1, cutoff=0.9)
    if best and len(best[0].split()) == len(key.split()):
        return keyed[best[0]], "close"
    return name, None


# ---------- the parser ----------

def detect_region(text: str):
    for region, pat in REGION_WORDS:
        if re.search(rf"\b{pat}\b", text, re.I):
            return region
    return None


def _iso(y, m, d):
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        return None


def parse_schedule(text: str, default_year: int | None = None):
    """Returns a dict:
       rows       — [{club, start_date, end_date, note, line}] in document order
       year, region, status_note  — from the heading lines
       holidays   — lines recognised as holidays (ignored)
       unread     — lines that look like they hold a date but didn't parse
       errors     — human-readable problems
    """
    lines = [ln.replace(" ", " ").rstrip() for ln in text.splitlines()]
    year, region, status_note = None, None, None
    rows, holidays, unread, errors = [], [], [], []

    # heading = everything before the first dated line
    heading = []
    for ln in lines:
        if DATE_LINE.match(ln):
            break
        if ln.strip():
            heading.append(ln.strip())
    for h in heading:
        if year is None:
            m = re.search(r"\b(20\d\d)\b", h)
            if m and not STATUS_WORDS.search(h):
                year = int(m.group(1))
        if region is None and not STATUS_WORDS.search(h):
            region = detect_region(h)
        if status_note is None and STATUS_WORDS.search(h) and len(h) < 80:
            status_note = h.strip().rstrip(":")
    if year is None:
        for h in heading:  # last resort: a year anywhere in the heading
            m = re.search(r"\b(20\d\d)\b", h)
            if m:
                year = int(m.group(1))
                break
    year = year or default_year
    if year is None:
        errors.append("Couldn't find the year in the document's title — add it (e.g. \"2027 … Schedule\") and upload again.")
        return {"rows": [], "year": None, "region": region, "status_note": status_note,
                "holidays": [], "unread": [], "errors": errors}

    prev_month = 0
    for n, ln in enumerate(lines, 1):
        if not ln.strip() or ln.strip() in heading:
            continue
        m = DATE_LINE.match(ln)
        if not m:
            if re.match(r"^\s*\d", ln):
                unread.append(ln.strip())
            continue  # section headings (SPRING:, FALL:) and prose
        rest = re.sub(r"\s+", " ", m.group("rest")).strip()
        if HOLIDAYS.search(rest) and "club" not in rest.lower():
            holidays.append(ln.strip())
            continue
        note = ""
        pm = re.search(r"\(([^)]*)\)\s*$", rest)
        if pm:
            note = pm.group(1).strip()
            rest = rest[:pm.start()].strip()
            if DAYS_ONLY.match(note):
                note = ""  # "(Fri-Sat)": days are derived from the dates anyway
        m1, d1 = int(m.group("m1")), int(m.group("d1"))
        y1 = m.group("y1")
        y = (int(y1) + 2000 if len(y1) == 2 else int(y1)) if y1 else year
        m2 = int(m.group("m2")) if m.group("m2") else m1
        d2 = int(m.group("d2")) if m.group("d2") else d1
        y2 = y + 1 if m2 < m1 else y  # a Dec 31 – Jan 1 trial
        start, end = _iso(y, m1, d1), _iso(y2, m2, d2)
        if not start or not end or end < start:
            unread.append(ln.strip())
            continue
        if m1 < prev_month and not y1:
            errors.append(f"Line {n} ({rest}): dates go back from month {prev_month} to {m1} — "
                          f"check the order; read as {start}.")
        prev_month = m1
        rows.append({"club": rest, "start_date": start, "end_date": end, "note": note,
                     "line": ln.strip(), "by_ai": False})
    return {"rows": rows, "year": year, "region": region, "status_note": status_note,
            "holidays": holidays, "unread": unread, "errors": errors}


# ---------- optional local-AI fallback for lines the parser couldn't read ----------

def llm_configured() -> bool:
    return bool(os.environ.get("SCHEDULE_LLM_URL"))


def read_with_llm(lines: list[str], year: int, timeout: float = 60.0):
    """Ask the local OpenAI-compatible server (llama.cpp on the NAS) to read the
    lines the parser couldn't. Every answer is re-validated here; nothing the model
    says is trusted beyond a date pair and a club name, and the governor sees each
    of these rows flagged 'read by AI — check' before anything is saved.
    Returns (rows, still_unread)."""
    if not lines or not llm_configured():
        return [], lines
    url = os.environ["SCHEDULE_LLM_URL"].rstrip("/") + "/chat/completions"
    prompt = (
        f"These lines come from a {year} dog field-trial schedule. For each line that names a "
        f"trial, give the first and last day (YYYY-MM-DD, year {year} unless the line says otherwise) "
        "and the club name exactly as written. Skip holidays and lines that aren't trials. "
        'Answer with JSON only: {"rows":[{"line":"…","start":"YYYY-MM-DD","end":"YYYY-MM-DD","club":"…"}]}\n\n'
        + "\n".join(lines))
    body = json.dumps({
        "model": os.environ.get("SCHEDULE_LLM_MODEL", "qwen3.5-4b"),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    if os.environ.get("SCHEDULE_LLM_KEY"):
        req.add_header("Authorization", "Bearer " + os.environ["SCHEDULE_LLM_KEY"])
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = json.load(resp)["choices"][0]["message"]["content"]
        content = re.sub(r"^```(json)?|```$", "", content.strip()).strip()
        answer = json.loads(content).get("rows", [])
    except Exception:
        return [], lines
    rows, used = [], set()
    for a in answer:
        line = str(a.get("line", "")).strip()
        club = str(a.get("club", "")).strip()
        try:
            s, e = date.fromisoformat(a["start"]), date.fromisoformat(a.get("end") or a["start"])
        except (KeyError, TypeError, ValueError):
            continue
        # validation: a club name, sane dates, near the schedule's year, and a line we actually sent
        if not club or line not in lines or e < s or (e - s).days > 4 or abs(s.year - year) > 1:
            continue
        rows.append({"club": club, "start_date": s.isoformat(), "end_date": e.isoformat(),
                     "note": "", "line": line, "by_ai": True})
        used.add(line)
    return rows, [ln for ln in lines if ln not in used]
