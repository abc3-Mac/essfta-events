# Verification report — essfta-events.collver.biz

**Verified:** 13 Aug 2026, ~20:35–20:50 UTC
**Target:** https://essfta-events.collver.biz (FastAPI + SQLite, Portainer git stack)
**Ground truth:** `archive/events-all.json` — 220 events captured from the essft.com
Tribe Events REST API on 13 Aug 2026.
**Method:** read-only. HTTPS GETs plus two form logins. No event, user, or setting was
created, edited, cancelled, or deleted.

Working artefacts (scratchpad, not committed): parsed live HTML, expected-record
derivation, matcher, field differ, freshness capture.

---

## 1. Coverage — 186/186, full check (not a sample)

**Expected set.** 220 archive events, 34 carrying the `Holidays` category, leaving
**186** to be seeded. No archive event carries a duplicate `(stripped title, start_date)`
key, so the migrator's dedupe guard could not have silently dropped one.

**Observed set.** `/?year=2026&past=1` and `/?year=2027&past=1` were fetched and the
event tables parsed (month band → year; `fmt_dates` cell → start/end; `<span class="title">`
→ club). **186 rows**, 176 in 2026 and 10 in 2027 — matching the archive's own year split.

**Matching.** Every archive event was paired 1:1 against a live row on
`(start_date, end_date, normalised club name)`. Result:

| | count |
|---|---|
| Archive events expected live | 186 |
| Matched **exactly** on start + end + name | **186** |
| Archive events with no live counterpart | **0** |
| Live rows with no archive counterpart | **0** |

**No archive event is missing from the live site, and the live site invents nothing.**

Seven `(start_date, club)` pairs legitimately occur twice — a club running a Springer
trial and a Cocker trial on the same weekend, etc. All seven were checked group-by-group;
in every case the two live rows carry the two distinct archive payloads (differing end
date, type, region, cost, judges). Nothing collapsed or duplicated:

| Date | Club | Archive pair | Live pair |
|---|---|---|---|
| 2026-01-22 | Houston ESS Club | Cocker Trial (ends 01-23) + Field Trial / Rocky Mountain (ends 01-25) | both present, correct |
| 2026-02-21 | Southern California Sporting Spaniel Club | Field Trial / West + Cocker Trial | both present, correct |
| 2026-03-14 | Stillwater Valley ESSC | Field Trial / Mid East + Cocker Trial (different judge pairs) | both present, correct |
| 2026-03-28 | Ohio Valley ESS Club | two Field Trials / Mid East, $155 and $160.00 | both present, correct |
| 2026-05-09 | Minnesota Hunting Spaniel Association | Hunt Test $80 (ends 05-10) + Cocker Trial $25 | both present, correct |
| 2026-08-29 | Central Connecticut Spaniel Club | Field Trial / East + Cocker Trial | both present, correct |
| 2026-09-05 | Maine Spaniel Field Trial Club | Field Trial ends 09-07 (no cost) + Field Trial ends 09-05 $175 | both present, correct |

**Region slices.** Each `&region=` slice was fetched for both years and counted, and
every returned row was confirmed to actually carry that region label in its meta line:

| Region | Archive | Live | |
|---|---|---|---|
| East | 12 | 12 | OK |
| Mid East | 10 | 10 | OK |
| Mid West | 21 | 21 | OK |
| Rocky Mountain | 18 | 18 | OK |
| West | 33 | 33 | OK |
| (no region) | 92 | 92 | OK |

Region mapping matches the stated rule in all 186 cases: `Field Trials - X` → region X,
everything else → NULL. The two multi-category archive events resolve as specified —
Heart of Texas (`Field Trials - Rocky Mountain` + `Water Test`) → Rocky Mountain, and
Tamarin (`Cocker Trial` + `Field Trials - West`) → West.

---

## 2. Field comparison — every event, every field (superset of the requested spot-check)

Rather than sample, all 186 matched pairs were diffed field by field against the archive
JSON (cost, judges 1–4, entries-close, city, state, region, event type, cancelled status,
entry-info link presence, start and end date).

| Field | Mismatches |
|---|---|
| start_date / end_date | 0 |
| cost | 0 |
| judges (1–4, order preserved) | 0 |
| entries close | 0 |
| city | 0 |
| state | 0 |
| region | 0 |
| event type | 0 |
| cancelled status | 0 |
| entry-info link present | 0 |

Judges are drawn from `custom_fields` labelled `Judge 1`…`Judge 4`; the live meta line
renders them in order, comma-joined. Verbatim down to the source's own inconsistencies
(e.g. `Elaine O' Keefe` on the Springer trial and `Elaine O'Keefe` on the Cocker trial the
same weekend — both preserved exactly as the old site had them).

### Requested 25-event spot check (4 per region + 5 non-region)

Sampled at random from unambiguous events, seed fixed for reproducibility.

| # | Region | Club (live) | Archive dates | Live dates | Cost A/L | Judges | Result |
|---|---|---|---|---|---|---|---|
| 1 | East | New Jersey Spaniel Field Trial Club | 2026-10-01 | 2026-10-01 (`Oct 1`) | — / — | — | PASS |
| 2 | East | New Jersey Spaniel Field Trial Club | 2026-10-17 | 2026-10-17 (`Oct 17`) | — / — | — | PASS |
| 3 | East | Central Connecticut Spaniel Club | 2026-04-18 → 04-19 | 2026-04-18 → 04-19 (`Apr 18–19`) | $140.00 / $140.00 | Phil Lincoln, Bill McCaffrey | PASS |
| 4 | East | Central Maine Spaniel Club Trial | 2026-06-11 → 06-12 | 2026-06-11 → 06-12 (`Jun 11–12`) | $175.00 / $175.00 | Mike Pollack, Todd Stelzer | PASS |
| 5 | Mid East | Euclid Sporting Spaniel Club | 2026-03-21 → 03-22 | 2026-03-21 → 03-22 (`Mar 21–22`) | $150.00 / $150.00 | Chuck Nelson, Mike Pollack | PASS |
| 6 | Mid East | Cincinnati English Springer Spaniel Field… | 2026-02-28 → 03-01 | 2026-02-28 → 03-01 (`Feb 28 – Mar 1`) | $160.00 / $160.00 | Francis Terry Sworsky, Gary Fluckiger | PASS |
| 7 | Mid East | Hall of Fame II | 2026-02-06 | 2026-02-06 (`Feb 6`) | $165.00 / $165.00 | John Dunn, Dan Tuttle | PASS |
| 8 | Mid East | Mid-Penn | 2026-03-07 → 03-08 | 2026-03-07 → 03-08 (`Mar 7–8`) | — / — | — | PASS |
| 9 | Mid West | Central Wisconsin Sporting Spaniel Club | 2026-10-22 → 10-23 | 2026-10-22 → 10-23 (`Oct 22–23`) | — / — | — | PASS |
| 10 | Mid West | Sportsmen's Spaniel Club of Calumet | 2026-10-17 → 10-18 | 2026-10-17 → 10-18 (`Oct 17–18`) | — / — | — | PASS |
| 11 | Mid West | Minnesota English Springer Spaniel Club | 2026-04-11 | 2026-04-11 (`Apr 11`) | $160.00 / $160.00 | Josh Riddle, Tom Nabity | PASS |
| 12 | Mid West | Minnesota Heartland English Springer Spa… | 2026-03-28 → 03-29 | 2026-03-28 → 03-29 (`Mar 28–29`) | $155.00 / $155.00 | Robert Clayton, Pete Anderson | PASS |
| 13 | Rocky Mountain | PRESSC | 2026-10-17 → 10-18 | 2026-10-17 → 10-18 (`Oct 17–18`) | — / — | — | PASS |
| 14 | Rocky Mountain | North Dakota Sporting Spaniel Club | 2026-05-09 → 05-10 | 2026-05-09 → 05-10 (`May 9–10`) | $155.00 / $155.00 | Tom Nabity, Alex Cacchio | PASS |
| 15 | Rocky Mountain | Missouri Hunting Spaniel Club | 2026-02-21 → 02-22 | 2026-02-21 → 02-22 (`Feb 21–22`) | $170.00 / $170.00 | Ryan Lamberg, Mark Haglin | PASS |
| 16 | Rocky Mountain | Platte River English Springer Spaniel Cl… | 2026-02-13 → 02-15 | 2026-02-13 → 02-15 (`Feb 13–15`) | $170.00 / $170.00 | Bill McCaffrey, Katie Gorecki, Chris Jensen | PASS |
| 17 | West | Rogue Valley Sporting Spaniel Club | 2026-01-30 → 01-31 | 2026-01-30 → 01-31 (`Jan 30–31`) | $165.00 / $165.00 | Ray Jack, Bob Bullard | PASS |
| 18 | West | Arrowhead ESS Club | 2027-02-13 → 02-15 | 2027-02-13 → 02-15 (`Feb 13–15`) | — / — | — | PASS |
| 19 | West | Inland Empire ESS Club | 2027-03-13 → 03-14 | 2027-03-13 → 03-14 (`Mar 13–14`) | — / — | — | PASS |
| 20 | West | Western Washington ESS Club | 2026-04-11 → 04-12 | 2026-04-11 → 04-12 (`Apr 11–12`) | $165.00 / $165.00 | Bob Davis, Terry Sworsky | PASS |
| 21 | — | Puget Sound English Springer Spaniel Ass… | 2026-09-07 | 2026-09-07 (`Sep 7`) | $85.00 / $85.00 | Kathy Stermolle, Jon Beernink | PASS |
| 22 | — | NOC Delegates Meeting | 2026-01-11 | 2026-01-11 (`Jan 11`) | — / — | — | PASS |
| 23 | — | Central Maine Spaniel Club | 2026-08-08 → 08-09 | 2026-08-08 → 08-09 (`Aug 8–9`) | $85.00 / $85.00 | Joe DeMarkis, Charlie Roberts | PASS |
| 24 | — | Platte River English Springer Spaniel Cl… | 2026-02-15 → 02-17 | 2026-02-15 → 02-17 (`Feb 15–17`) | $170.00 / $170.00 | Chris Jensen, Bill McCaffrey | PASS |
| 25 | — | Houston ESSC Spaniel | 2026-02-14 → 02-15 | 2026-02-14 → 02-15 (`Feb 14–15`) | $80.00 / $80.00 | Amy Rogers, Kevin Gaddie | PASS |

**25/25 PASS.**

### Cancelled events

Both `CANCELLED!!` archive titles imported correctly — prefix stripped, `status=canceled`,
`CANCELED` badge and strike-through rendered on the list and print views, and both
excluded from the iCal feed:

- 2026-06-05 Spaniel Field Trial Judges Seminar hosted by Iowa Sporting Spaniel Club
- 2026-06-07 Iowa Sporting Spaniel Club SPRINGER and COCKER Water Test

No other event carries a cancelled status (patty's dashboard: 184 scheduled, 2 canceled).

### Club-name derivation — the stated risk is clean

The headline concern (the old site's `organizer` being a contact **person**, not a club)
holds up. Cross-checking all 79 distinct archive organizer names against all 133 distinct
live club names: **zero** clubs equal a contact-person name, and **zero** clubs are empty.
Fourteen person names do appear on public pages — every one of them as a **judge**, which
is intended and matches the archive exactly. Verified again on the calendar chips: 18
unique labels in September 2026, all club names, no person names.

---

## 3. Freshness diff — essft.com is still up, and the archive is current

`https://essft.com/wp-json/tribe/events/v1/events?per_page=50&start_date=2026-08-13&end_date=2027-12-31`
fetched, 2 pages, 2 s between requests. **86 events** returned.

- **Events on essft.com but not in the archive: 0.**
- **Events in the archive's window but gone from essft.com: 0.**
- **Events genuinely modified since the capture: 0.** Maximum `modified` timestamp is
  identical on both sides (`2026-08-13 13:14:32`).

18 events showed a byte difference in `description`, all of them the same non-substantive
artefact: WordPress's PDF-embed plugin assigns a per-request container index, so
`wppdfemb-frame-container-27` on one request is `-1` on the next (the index also appears
inside a base64 `data-` blob and in `data-pdf-index`). Diffed opcode by opcode on four
samples — only the index digits move. Dates, links, entry deadlines, judges, categories,
venues, costs and titles are byte-identical across all 86.

**The archive was not stale at seed time and has not gone stale since.**

---

## 4. Auth boundaries — all six pass

| # | Check | Expected | Observed | |
|---|---|---|---|---|
| f | unauthenticated `GET /dashboard` | redirect to `/login` | `303`, `Location: /login` | PASS |
| — | login as `east` | session issued | `303 → /dashboard`, `essfta_events_session` set `HttpOnly`, `Secure`, `SameSite=Lax`, 12 h expiry | PASS |
| a | `east` `GET /dashboard` | East events only | `200`; heading "East region events"; **12 rows, 100% region East**; the 12 club names are exactly the 12 East archive events | PASS |
| c | `east` `GET /users` | 403 | `403 "Admins only"` | PASS |
| b | `east` `GET /events/123/edit` (Mid West) | 404 | `404 "Not found or not yours to edit"` | PASS |
| d | `patty` `GET /users` | 200 | `200` | PASS |
| d | `patty` `GET /dashboard` | all regions | `200`; heading "All events"; **186 rows** — West 33, Mid West 21, Rocky Mountain 18, East 12, Mid East 10, no-region 92; club multiset identical to the archive | PASS |
| e | `POST /login` with a wrong password | 401 | `401`, "Wrong username or password." | PASS |

Event id 123 was identified as Mid West from patty's dashboard, then confirmed by loading
`/events/123/edit` as patty — the region select renders `Mid West` as selected.

Three extra adversarial probes, all correct:

- `east` → `/events/130/edit` (an event in her own East region): **200**. Positive control —
  the 404 above is a region check, not a blanket denial.
- `east` → `/events/124/edit` (a NULL-region, admin-managed event): **404**. Governors
  cannot reach the un-regioned Hunt Test / Cocker / National / seminar pool.
- `east` → `/events/99999/edit` (nonexistent): **404**, same body as the cross-region case —
  no id-enumeration oracle.

Login rate limiting (10 attempts / 10 min / IP) is present in code; deliberately not
exercised, to avoid locking out the account.

---

## 5. Public surface

### `/events.ics`

`200`, `Content-Type: text/calendar; charset=utf-8`. Structurally valid iCalendar:
CRLF line endings, `BEGIN:VCALENDAR` … `END:VCALENDAR`, `VERSION:2.0` and `PRODID` present,
**184 `BEGIN:VEVENT` / 184 `END:VEVENT`**, correctly nested, 184 unique UIDs, 184
`DTSTART;VALUE=DATE`, no malformed property lines.

**184 = 186 − the 2 cancelled events.** Exactly as specified. Both cancelled events
confirmed absent by name.

### `/calendar?month=2026-09`

`200`. 40 chip instances (multi-day events repeat per day), **18 unique labels**. The 18
labels are exactly the 18 clubs the list view shows as overlapping September 2026 — no
event missing from the grid, none added. All 18 are **club names**; zero person names.

### `/print`

`200` at `/print`, `/print?year=2026` and `/print?year=2027`. Renders as a real document
(month bands, header row, strike-through for cancelled). Row counts are right:
**176 event rows / 12 month bands for 2026**, **10 / 4 for 2027** — 186 total, matching
the archive.

### Content-Security-Policy `frame-ancestors`

| Route | Status | CSP |
|---|---|---|
| `/` | 200 | present |
| `/?year=2026&past=1` | 200 | present |
| `/calendar?month=2026-09` | 200 | present |
| `/print`, `/print?year=2026` | 200 | present |
| `/embed-demo` | 200 | **MISSING** |
| `/events.ics` | 200 | **MISSING** |
| `/login` | 200 | **MISSING** |
| `/healthz` | 200 | **MISSING** |

Header value where present:
`frame-ancestors 'self' https://englishspringerspaniels.org https://*.englishspringerspaniels.org https://*.collver.biz`

Cause: `app/main.py` wraps only `list_view`, `calendar_view` and `print_view` in
`public_headers()`. `embed_demo`, `ical`, `login_form` and `healthz` return their responses
directly. See defect 1.

---

## Verdict

**Data migration: CLEAN.** All 186 non-Holidays archive events are live, matched 1:1 with
zero missing, zero extra, and zero field mismatches across dates, cost, judges, entry
deadlines, city, state, region, type and cancelled status. Region mapping, cancelled-title
handling, and club-name derivation all behave as specified. Auth boundaries pass all six
required checks plus three extra probes. The iCal, calendar, and print surfaces are correct.
essft.com is still reachable and has not changed since the capture.

Two defects found, neither a data-integrity problem. Most serious first:

1. **`/login` is missing the `Content-Security-Policy: frame-ancestors` header** (and so are
   `/embed-demo`, `/events.ics`, `/healthz`). Only `/`, `/calendar` and `/print` call
   `public_headers()`. The login page carrying no frame-ancestors restriction means any
   site can iframe the governor login form — the usual clickjacking setup, and the only
   one of the four that takes a credential. Low practical risk (session cookie is
   `SameSite=Lax`, and the app has no other frame-busting need), but it is a stated
   requirement of the deploy that "every public page carries the header," and `/login` is
   a public page. Fix is one line each — wrap those responses in `public_headers()`, or
   move the header into middleware so new routes inherit it.

2. **Eight club names retain leftover event-type text from the title-derivation regex**
   (cosmetic only; no data lost, and no person names involved). The regex strips a trailing
   event-type phrase, but misses these shapes:

   - `Iowa Sporting Spaniel Club SPRINGER and` — from "…SPRINGER and COCKER Water Test";
     the strip leaves a dangling "and". This is the most visible one, since it is also one
     of the two CANCELED rows.
   - `Central Wisconsin Sporting Spaniel Club COCKER Fall Field Trail` — source typo
     "Trail" for "Trial", so nothing matched.
   - `Northern Colorado SS Club Spring Field Trial March 2026- SPRINGER`
   - `Platte River English Springer Spaniel Club COCKER Double Open & Water Test`
   - `Central Maine Spaniel Club Trial`
   - `Cocker Spaniel Hunting Enthusiasts Cocker`
   - `Maryland Sporting Dog Association Spaniel Hunting Test`
   - `Sportsman's Spaniel Club of Calumet Hunt Test` / `Sportsmen's Spaniel Club of Calumet Field Trial`

   Related and also cosmetic: `Patriot Sporting Spaniel Club's` keeps a trailing possessive,
   and eight clubs come through as bare abbreviations because that is all the source title
   gave (`ESSCEN`, `MHSC`, `Mid-Penn`, `NCSSC`, `NMESSC`, `PRESSC`, `RMSSC`, `SSCCK`). These
   are best fixed by hand in the dashboard rather than by widening the regex.
