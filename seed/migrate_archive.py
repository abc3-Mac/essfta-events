#!/usr/bin/env python3
"""Seed data/events.db from the essft.com archive + create the seven user accounts.

Usage:
  python3 seed/migrate_archive.py            # events only
  python3 seed/migrate_archive.py --users    # also create accounts, print passwords ONCE
"""
import html
import json
import os
import re
import secrets
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import auth, db  # noqa: E402

ARCHIVE = os.path.join(os.path.dirname(__file__), "..", "archive", "events-all.json")

STATE_RE = re.compile(r"\b(A[LKZR]|C[AOT]|DE|FL|GA|HI|I[DLNA]|K[SY]|LA|M[EDAINSOT]|N[EVHJMYCD]|O[HKR]|PA|RI|S[CD]|T[NX]|UT|V[TA]|W[AVIY]|ON|QC|BC|AB|SK|MB|NS|NB)\b")

TYPE_MAP = [
    ("NATIONAL FIELD TRIALS", "National"),
    ("Hunt Tests", "Hunt Test"),
    ("Cocker Trial", "Cocker Trial"),
    ("Fun Trials", "Fun Trial"),
    ("Water Test", "Water Test"),
    ("Judging Seminar", "Judging Seminar"),
    ("Gunning Seminars", "Gunning Seminar"),
    ("Training Seminar", "Training Seminar"),
    ("Canadian FT", "Canadian Trial"),
]


def region_and_type(ev):
    cats = [c.get("name", "") for c in ev.get("categories", [])]
    region = None
    for r in sorted(db.REGIONS, key=len, reverse=True):
        if any(re.search(rf"\b{re.escape(r)}\b", c) for c in cats):
            region = r
            break
    etype = "Field Trial" if region else None
    for cat_name, t in TYPE_MAP:
        if cat_name in cats:
            etype = t
            break
    return region, etype or "Field Trial"


def strip_html(s):
    return html.unescape(re.sub(r"<[^>]+>", " ", s or "")).strip()


def extract_entries_close(desc_html):
    text = strip_html(desc_html)
    m = re.search(r"Entries?\s+Close[sd]?:?\s*([^.<]{4,80}?)(?:\s+on\s|\.|$)", text, re.I)
    return m.group(1).strip() if m else ""


def extract_link(desc_html, website):
    if website:
        return website
    m = re.search(r'href="(https?://[^"]+)"', desc_html or "")
    return m.group(1) if m else ""


def venue_city_state(ev):
    v = ev.get("venue") or {}
    if isinstance(v, list):
        v = v[0] if v else {}
    name = (v.get("venue") or "").strip()
    city = (v.get("city") or "").strip()
    state = (v.get("stateprovince") or v.get("state") or "").strip().upper()[:2]
    if not state:
        m = STATE_RE.search(name)
        if m:
            state = m.group(0)
    return name, city, state


def club_from(ev):
    # The old site's "organizer" is a contact PERSON, not the club — derive club from the title.
    t = strip_html(ev.get("title", ""))
    t = re.sub(
        r"\s+(Spring|Fall|Winter|Summer)?\s*((?:AKC\s+)?(?:Springer|Cocker)(?:\s+Spaniel)?)?\s*"
        r"(Field Trial|Hunt Test|Water Test|Fun Trial|Judges? Seminar|Seminar|Trial)s?\s*$",
        "", t, flags=re.I).strip()
    return t.rstrip("–- ,").strip()


def contact_from(ev):
    orgs = ev.get("organizer") or []
    if orgs and orgs[0].get("organizer"):
        return strip_html(orgs[0]["organizer"])
    return ""


def seed_events():
    evs = json.load(open(ARCHIVE))
    db.init()
    added = skipped = 0
    for ev in evs:
        cats = [c.get("name", "") for c in ev.get("categories", [])]
        if "Holidays" in cats:  # calendar filler on the old site
            skipped += 1
            continue
        region, etype = region_and_type(ev)
        venue, city, state = venue_city_state(ev)
        judges = {}
        for cf in (ev.get("custom_fields") or {}).values():
            label, val = cf.get("label", ""), strip_html(cf.get("value", ""))
            m = re.match(r"Judge\s*(\d)", label, re.I)
            if m and val:
                judges[f"judge{m.group(1)}"] = val
            elif "apprentice" in label.lower() and val:
                judges["apprentice_judges"] = val
        title = strip_html(ev.get("title", ""))
        canceled = bool(re.match(r"\s*CANCEL?LED", title, re.I))
        title = re.sub(r"^\s*CANCEL?LED!*\s*", "", title, flags=re.I)
        data = {
            "title": title,
            "club": club_from({**ev, "title": title}),
            "region": region,
            "event_type": etype,
            "start_date": ev["start_date"][:10],
            "end_date": ev["end_date"][:10],
            "city": city, "state": state, "venue": venue,
            "cost": (ev.get("cost") or "").strip(),
            "entries_close": extract_entries_close(ev.get("description")),
            "link_url": extract_link(ev.get("description"), (ev.get("website") or "").strip()),
            "notes": (f"Contact: {contact_from(ev)}" if contact_from(ev) else ""),
            "status": "canceled" if canceled else "scheduled",
            "source": "essft-import",
            **judges,
        }
        con = db.connect()
        dup = con.execute(
            "SELECT id FROM events WHERE title=? AND start_date=?",
            (data["title"], data["start_date"])).fetchone()
        con.close()
        if dup:
            skipped += 1
            continue
        eid = db.create_event(data, "essft-import")
        con = db.connect()
        con.execute("UPDATE events SET source_url=? WHERE id=?", (ev.get("url", ""), eid))
        con.commit()
        con.close()
        added += 1
    print(f"events: {added} added, {skipped} skipped (holidays/dupes)")


ACCOUNTS = [
    # username, display name, role, region
    ("east", "Field Governor — East", "governor", "East"),
    ("mideast", "Field Governor — Mid East", "governor", "Mid East"),
    ("midwest", "Field Governor — Mid West", "governor", "Mid West"),
    ("rockymountain", "Field Governor — Rocky Mountain", "governor", "Rocky Mountain"),
    ("west", "Field Governor — West", "governor", "West"),
    ("albert", "Albert Collver", "admin", None),
    ("patty", "Patty Mortara", "admin", None),
]


def seed_users():
    print("\n=== ACCOUNTS (passwords shown ONCE — copy them now) ===")
    for username, display, role, region in ACCOUNTS:
        if db.get_user(username):
            print(f"{username}: already exists, unchanged")
            continue
        pw = "-".join(secrets.token_hex(2) for _ in range(3))  # e.g. 3f9a-c210-77be
        db.create_user(username, display, role, region, auth.hash_password(pw))
        print(f"{username:15s} {pw}   ({display})")


if __name__ == "__main__":
    seed_events()
    if "--users" in sys.argv:
        seed_users()
