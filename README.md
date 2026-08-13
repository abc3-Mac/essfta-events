# ESSFTA Field Events

Replacement for the events calendar on essft.com (shut down 2026). Five ESSFTA
Field Governors maintain their own region's events through a simple form; the
public sees a month calendar and a list view, color-coded by field region, and
the whole thing embeds by iframe into the ESSFTA main WordPress site.

**Live test:** https://essfta-events.collver.biz
**Embed demo:** https://essfta-events.collver.biz/embed-demo

## Views

- `/` — list view, month-band schedule table (Date | Days | Club | City | State | Stakes),
  filters for region / type / state / club / year
- `/calendar` — month grid, events as region-colored chips
- `/print` — printable year schedule (opens the print dialog)
- `/events.ics` — iCal feed
- `/embed-demo` — mock WordPress page demonstrating the iframe embed
- `?embed=1` on list/calendar — chromeless version for the iframe

## Accounts

- Five **governor** accounts (east, mideast, midwest, rockymountain, west) —
  each can add/edit/cancel events only in their own region.
- Two **admin** accounts (albert, patty) — edit anything, and manage governor
  accounts at `/users` (add a governor, reset a password, deactivate/reactivate).
  Passwords are generated server-side and shown exactly once.

## Region colors (canonical ESSFTA legend)

East `#2f5fa5` · Mid East `#8f1d22` · Mid West `#1f9d5b` ·
Rocky Mountain `#b84390` · West `#a3921e` · no region (Hunt Tests, Nationals, seminars) gray

## Run locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python seed/migrate_archive.py          # seed events from archive/ (optional)
.venv/bin/uvicorn app.main:app --port 8791 --reload
```

## Deploy

Single container, FastAPI + SQLite, no external services — **portable to any
Docker host** (including the ESSFTA site's own server later): copy this repo +
the `/data` volume (one SQLite file), `docker compose up -d`, done. Without
Docker it runs anywhere with Python 3.10+ via the three commands above.

Current home: Portainer git-repository stack `essfta-events` on the collver.biz
NAS, proxied by Nginx Proxy Manager with Let's Encrypt. Set `EVENTS_SECRET_KEY`
(any long random string) in the stack env.

## WordPress embed snippet

```html
<iframe id="essfta-events" src="https://essfta-events.collver.biz/?embed=1"
        title="ESSFTA Field Events" style="width:100%;border:0;min-height:600px"></iframe>
<script>
window.addEventListener("message", function (e) {
  if (e.data && e.data.essftaEventsHeight) {
    document.getElementById("essfta-events").style.height = (e.data.essftaEventsHeight + 20) + "px";
  }
});
</script>
```

The app sends `Content-Security-Policy: frame-ancestors` allowing
englishspringerspaniels.org and *.collver.biz, and posts its content height to
the parent page so the iframe never double-scrolls.

## Data lineage

`archive/` (not in git) holds the full essft.com capture (13 Aug 2026, REST API,
220 events 2026–2027 + venues/organizers/categories). `seed/migrate_archive.py`
seeds the database from it: region + event type from categories, judges from
custom fields, entries-close parsed from descriptions, club derived from the
title (the old site's "organizer" was a contact person, not the club),
"CANCELLED!!" titles imported as status=canceled, the 34 "Holidays" filler
entries excluded. Every event keeps `source='essft-import'` + `source_url`.
