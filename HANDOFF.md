# HANDOFF — ESSFTA Field Events

Read this first in any new session. Built 13 Aug 2026 (session: essft.com shutdown replacement).

## What this is
Governor-maintained events calendar replacing essft.com/events. FastAPI + SQLite +
Jinja, one container. Public list/calendar views (region color-coded) for iframe
embed into englishspringerspaniels.org; authenticated dashboard for the five Field
Governors + two admins (Albert, Patty). See README.md for routes and the embed snippet.

## State at handoff
- **Local:** fully working, 33/33 smoke tests pass (`seed/smoke_test.sh`).
- **18 Aug 2026 round:** login audit log (`login_events`, `/audit`, last-seen on
  `/users`), Hide-vs-Remove split (`events.hidden` flag), `/bulk` date-range
  hide/unhide (+ admin remove/restore) with preview + batch undo, `/rollforward`
  season cloning. Bulk ops share `batches` + `event_history.batch_id`. Pre-deploy
  live-DB backups in `backups/` (gitignored) via the Portainer archive API.
- **Data:** 186 events seeded from `archive/` (the 13 Aug 2026 essft.com API capture;
  34 "Holidays" filler excluded). Non-region events (Hunt Tests, Cockers, Nationals,
  seminars) have region=NULL → gray, admin-managed.
- **Deploy:** Portainer git stack `essfta-events` → NAS build, NPM → https://essfta-events.collver.biz
  (same pattern as essfta-breeder-showcase; see that project's memory for API recipes).
- **Phase 3 (WordPress page on englishspringerspaniels.org) NOT done** — awaiting
  Albert's approval. Draft page + menu wording ("Field Trial Events" vs "Field Events")
  to be mocked. WP REST creds: `~/.essfta.env`.

## Key decisions
- Club names derive from event titles, NOT the old site's "organizer" (that's a
  contact person — Albert caught person names showing where clubs belonged).
- Governors' region is forced server-side from their account; form tampering tested.
- "Remove a governor" = deactivate (login blocked, events + audit trail kept).
- Never hard-delete events: status = scheduled/canceled/postponed/archived.
- Days-of-week always derived from dates, never typed.
- Portability requirement (Albert): must be movable to the ESSFTA site's own server
  later — hence single container + single SQLite file + no external services.
  Migration = copy repo + /data volume.

## Gotchas
- Session cookie is `secure=True` — login only works over https (or via curl with
  a hand-carried Cookie header, as smoke_test.sh does).
- `archive/` and `data/` are gitignored — the DB on the server is the live truth;
  local copies are seeds/tests. Live DB was pushed once at deploy via the Docker
  archive API (tar upload), then diverges.
- The NAS has NO SSH — Portainer API (`~/.config/portainer.env`) + NPM API
  (`~/.config/npm.env`) + Owlfiles SMB only.
- Watchtower: image is built locally by Portainer from git (`essfta-events:1.0.0`),
  not registry-pulled, so Watchtower auto-update doesn't apply. Redeploy after code
  push: `POST /api/stacks/{id}/git/redeploy?endpointId=3`.
- `EVENTS_SECRET_KEY` lives in the Portainer stack env + `~/.config/essfta-events.env`.

## Account model
users(username, role governor|admin, region, active). Admins manage governors at
`/users` — create (password shown once), reset password, deactivate/reactivate.
Admins are only creatable by seed script or DB edit, by design.
