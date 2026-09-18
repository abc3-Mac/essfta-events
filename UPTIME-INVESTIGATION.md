# Uptime investigation — brief for a local session

Written from a Claude Code cloud session that had the repo but no network path to
the NAS. Read this, then do the work from the laptop, which does have the path.

## Why this exists

The question on the table: **what is the actual measured uptime of
`https://essfta-events.collver.biz`?**

It came up while pricing a website build for an outside client. The decision was
whether to self-host that client's site on this NAS or put it on a commercial
host. That decision is already made — commercial host, for reasons of
accountability rather than cost. What remains is the genuinely useful part:
nobody currently knows what this stack's real availability is.

The honest answer today is that the number does not exist. Nothing is measuring it.

## Why the server logs cannot answer it

This was checked before concluding it. Do not spend time re-deriving it:

- Container logs reset on every Portainer git redeploy, and redeploys are routine
  here (see `HANDOFF.md`).
- `restart: unless-stopped` in `docker-compose.yml` masks crashes. The container
  comes back and the gap reads as silence, not as a recorded failure.
- Logs record what the app did *while running*. They cannot record the window in
  which the container, Docker, DSM, the ISP, or mains power was the thing that
  was down. Those are precisely the outages that matter.
- NPM access logs show requests served. On a low-traffic site, "no requests for
  three hours" is indistinguishable from "down for three hours."

Server logs measure activity, not availability. Uptime needs an external observer
polling from outside the network.

## What the laptop can do that the cloud session could not

The laptop has Tailscale and the credential files. The cloud container had
neither, and its egress proxy blocked `collver.biz` outright.

Relevant facts from `HANDOFF.md`:

- The NAS has **no SSH**. Access is Portainer API, NPM API, and Owlfiles SMB only.
- Portainer credentials: `~/.config/portainer.env`
- NPM credentials: `~/.config/npm.env`
- Portainer endpoint id: `3`
- Stack and container name: `essfta-events`
- Redeploy: `POST /api/stacks/{id}/git/redeploy?endpointId=3`

## Step 1 — collect what history does exist

Against the Portainer API:

    GET /api/endpoints/3/docker/containers/essfta-events/json

Pull these fields and report them:

- `.State.StartedAt` — how long the current container has actually been running
- `.State.Status` and `.State.Running`
- `.RestartCount` — restarts since the container was created
- `.State.ExitCode` and `.State.Error` if non-empty
- `.Created` — distinguishes "restarted" from "redeployed"

A `RestartCount` above zero, or a `StartedAt` that does not line up with a known
redeploy, is a real signal worth chasing. This is not uptime, but it is evidence,
and it is the only historical evidence available.

Also worth a look: DSM's own notification log for unexpected reboots, power
events, and DSM updates that restarted the box. Those are the outages most likely
to have gone unnoticed.

## Step 2 — start actually measuring

This is the part that produces a number, and it takes about ten minutes.

Put an external monitor on `https://essfta-events.collver.biz`. UptimeRobot's free
tier gives 50 monitors at 5-minute checks; Better Stack's gives 10 at 30 seconds.
Either is sufficient. It must be external — a monitor running on the NAS cannot
observe the NAS being unreachable.

Configure alerting to email or push. Then leave it alone. After 30 days there is a
usable figure; after 90 there is one solid enough to quote in a contract.

Useful extras if the monitor supports them:

- Keyword check on a string the page always renders, so a 200 from a broken app
  still registers as down.
- A second monitor on `/events.ics`, since the iCal feed is what external
  subscribers consume and it can break independently of the HTML views.

## Step 3 — decide what the number means

Once there is 30 days of data:

- Around 99% is roughly 7 hours down per month. Fine for a volunteer club
  calendar, not fine for anything a business depends on.
- Around 99.9% is roughly 45 minutes per month. Respectable for self-hosted.
- Commercial static hosts publish 99.99%+ and stand behind it contractually.

The ESSFTA calendar can tolerate a few hours down. That tolerance is the reason
self-hosting is fine *here* and was the wrong answer for a paying client's
credibility site. Same infrastructure, different consequences.

## Context that does not need re-litigating

- The client website decision is settled: commercial host, domain registered in
  the client's own name on their own account.
- The proposal for that client lives in a Claude doc, not in this repo.
- Nothing in this file requires changing application code.
