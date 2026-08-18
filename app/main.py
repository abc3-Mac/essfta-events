"""ESSFTA Field Events calendar — governor-maintained events, embeddable public views."""
import calendar as calmod
import os
from datetime import date, datetime, timedelta

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import auth, db, xlsx_io

app = FastAPI(title="ESSFTA Field Events")
HERE = os.path.dirname(__file__)
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))

FRAME_ANCESTORS = os.environ.get(
    "FRAME_ANCESTORS",
    "'self' https://englishspringerspaniels.org https://*.englishspringerspaniels.org https://*.collver.biz",
)

db.init()


# ---------- helpers ----------

def fmt_dates(start: str, end: str) -> str:
    """'Sep 11' or 'Sep 12–13' or 'Sep 30 – Oct 1'."""
    s, e = date.fromisoformat(start[:10]), date.fromisoformat(end[:10])
    if s == e:
        return s.strftime("%b %-d")
    if s.month == e.month:
        return f"{s.strftime('%b %-d')}–{e.day}"
    return f"{s.strftime('%b %-d')} – {e.strftime('%b %-d')}"


def fmt_days(start: str, end: str) -> str:
    """'Friday' / 'Saturday & Sunday' / 'Thu–Sun' — derived, never typed."""
    s, e = date.fromisoformat(start[:10]), date.fromisoformat(end[:10])
    n = (e - s).days
    if n == 0:
        return s.strftime("%A")
    if n == 1:
        return f"{s.strftime('%A')} & {e.strftime('%A')}"
    return f"{s.strftime('%a')}–{e.strftime('%a')}"


templates.env.globals.update(
    fmt_dates=fmt_dates,
    fmt_days=fmt_days,
    REGIONS=db.REGIONS,
    EVENT_TYPES=db.EVENT_TYPES,
    REGION_COLORS=db.REGION_COLORS,
)


@app.middleware("http")
async def frame_ancestors_header(request: Request, call_next):
    # every route inherits the embed policy (Opus verify pass caught /login & co. missing it)
    resp = await call_next(request)
    resp.headers["Content-Security-Policy"] = f"frame-ancestors {FRAME_ANCESTORS}"
    return resp


def public_headers(resp: Response):
    return resp


def current_user(request: Request):
    sess = auth.read_session(request.cookies.get(auth.COOKIE, ""))
    if not sess:
        return None, None
    user = db.get_user(sess["u"])
    return user, sess


def parse_filters(request: Request):
    qp = request.query_params
    return {
        "region": qp.get("region") or None,
        "event_type": qp.get("type") or None,
        "state": qp.get("state") or None,
        "club": qp.get("club") or None,
        "include_canceled": qp.get("hide_canceled") != "1",
    }


def month_bounds(ym: str):
    y, m = int(ym[:4]), int(ym[5:7])
    last = calmod.monthrange(y, m)[1]
    return f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{last:02d}"


# ---------- public views ----------

@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def list_view(request: Request):
    f = parse_filters(request)
    qp = request.query_params
    year = qp.get("year") or str(date.today().year)
    events = db.list_events(
        region=f["region"], event_type=f["event_type"], state=f["state"], club=f["club"],
        date_from=f"{year}-01-01" if qp.get("past") == "1" else max(f"{year}-01-01", date.today().isoformat()),
        date_to=f"{year}-12-31", include_canceled=f["include_canceled"],
    )
    months = {}
    for ev in events:
        key = ev["start_date"][:7]
        months.setdefault(key, []).append(ev)
    resp = templates.TemplateResponse(request, "list.html", {
        "months": months, "filters": f, "year": year, "show_past": qp.get("past") == "1",
        "states": db.distinct_states(), "view": "list",
        "embed": qp.get("embed") == "1",
        "month_name": lambda k: date.fromisoformat(k + "-01").strftime("%B %Y"),
    })
    return public_headers(resp)


@app.get("/calendar", response_class=HTMLResponse)
def calendar_view(request: Request):
    f = parse_filters(request)
    ym = request.query_params.get("month") or date.today().strftime("%Y-%m")
    first, last = month_bounds(ym)
    events = db.list_events(
        region=f["region"], event_type=f["event_type"], state=f["state"], club=f["club"],
        date_from=first, date_to=last, include_canceled=f["include_canceled"],
    )
    y, m = int(ym[:4]), int(ym[5:7])
    weeks = calmod.Calendar(firstweekday=6).monthdatescalendar(y, m)  # weeks start Sunday
    by_day = {}
    for ev in events:
        s = date.fromisoformat(ev["start_date"][:10])
        e = date.fromisoformat(ev["end_date"][:10])
        d = s
        while d <= e:
            by_day.setdefault(d.isoformat(), []).append(ev)
            d += timedelta(days=1)
    prev_m = (date(y, m, 1) - timedelta(days=1)).strftime("%Y-%m")
    next_m = (date(y, m, calmod.monthrange(y, m)[1]) + timedelta(days=1)).strftime("%Y-%m")
    resp = templates.TemplateResponse(request, "calendar.html", {
        "weeks": weeks, "by_day": by_day, "ym": ym, "month_label": date(y, m, 1).strftime("%B %Y"),
        "prev_m": prev_m, "next_m": next_m, "this_month": m,
        "filters": f, "states": db.distinct_states(), "view": "calendar",
        "embed": request.query_params.get("embed") == "1", "today": date.today().isoformat(),
    })
    return public_headers(resp)


@app.get("/print", response_class=HTMLResponse)
def print_view(request: Request):
    year = request.query_params.get("year") or str(date.today().year)
    events = db.list_events(date_from=f"{year}-01-01", date_to=f"{year}-12-31")
    months = {}
    for ev in events:
        months.setdefault(ev["start_date"][:7], []).append(ev)
    resp = templates.TemplateResponse(request, "print.html", {
        "months": months, "year": year,
        "month_name": lambda k: date.fromisoformat(k + "-01").strftime("%B").upper(),
    })
    return public_headers(resp)


# Which region column a no-region event (Hunt Test, Cocker Trial…) lands in on the grid,
# inferred from its state. Nationals and unmappable events render as full-width bands.
STATE_REGION = {
    **{s: "East" for s in ["ME", "NH", "VT", "MA", "RI", "CT", "NY", "NJ", "DE"]},
    **{s: "Mid East" for s in ["MI", "OH", "PA", "MD", "VA", "WV", "NC", "SC", "GA", "TN", "FL", "AL", "ON", "QC"]},
    **{s: "Mid West" for s in ["WI", "IL", "MN", "IA", "IN", "KY", "MB"]},
    **{s: "Rocky Mountain" for s in ["ND", "SD", "NE", "KS", "MO", "OK", "TX", "CO", "WY", "MT", "NM", "SK", "AB"]},
    **{s: "West" for s in ["WA", "OR", "CA", "ID", "UT", "NV", "AZ", "AK", "HI", "BC"]},
}
GRID_COLUMNS = ["West", "Rocky Mountain", "Mid West", "Mid East", "East"]  # west→east like the sketch


@app.get("/grid", response_class=HTMLResponse)
def grid_view(request: Request):
    f = parse_filters(request)
    qp = request.query_params
    year = qp.get("year") or str(date.today().year)
    events = db.list_events(
        event_type=f["event_type"], state=f["state"], club=f["club"],
        date_from=f"{year}-01-01" if qp.get("past") == "1" else max(f"{year}-01-01", date.today().isoformat()),
        date_to=f"{year}-12-31", include_canceled=f["include_canceled"],
    )
    rows = {}   # (start, end) -> {column: [events]} ; "BAND" holds full-width rows
    for ev in events:
        col = ev["region"] or STATE_REGION.get(ev["state"] or "")
        if ev["event_type"] == "National" or not col:
            col = "BAND"
        key = (ev["start_date"][:10], ev["end_date"][:10])
        rows.setdefault(key, {}).setdefault(col, []).append(ev)
    ordered = [(k, rows[k]) for k in sorted(rows)]
    resp = templates.TemplateResponse(request, "grid.html", {
        "rows": ordered, "columns": GRID_COLUMNS, "year": year,
        "show_past": qp.get("past") == "1", "filters": f, "states": db.distinct_states(),
        "view": "grid", "embed": qp.get("embed") == "1",
    })
    return public_headers(resp)


@app.get("/event/{event_id}", response_class=HTMLResponse)
def event_detail(request: Request, event_id: int):
    ev = db.get_event(event_id)
    if not ev or ev["status"] == "archived":
        return PlainTextResponse("Event not found", status_code=404)
    if ev.get("hidden"):
        viewer, _ = current_user(request)
        if not viewer:  # hidden events stay reachable for signed-in governors/admins
            return PlainTextResponse("Event not found", status_code=404)
    resp = templates.TemplateResponse(request, "event_detail.html", {
        "ev": ev, "embed": request.query_params.get("embed") == "1", "view": None,
    })
    return public_headers(resp)


@app.get("/embed-demo", response_class=HTMLResponse)
def embed_demo(request: Request):
    """Mock WordPress page proving the iframe embed — what Field Trial Events will look like."""
    return templates.TemplateResponse(request, "embed_demo.html", {})


@app.get("/events.ics")
def ical():
    events = db.list_events(include_canceled=False)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ESSFTA//Field Events//EN",
             "X-WR-CALNAME:ESSFTA Field Events"]
    for ev in events:
        end = (date.fromisoformat(ev["end_date"][:10]) + timedelta(days=1)).strftime("%Y%m%d")
        summary = ev["title"].replace(",", r"\,")
        loc = ", ".join(x for x in (ev["city"], ev["state"]) if x).replace(",", r"\,")
        lines += [
            "BEGIN:VEVENT",
            f"UID:essfta-event-{ev['id']}@essfta-events.collver.biz",
            f"DTSTART;VALUE=DATE:{ev['start_date'][:10].replace('-', '')}",
            f"DTEND;VALUE=DATE:{end}",
            f"SUMMARY:{summary}",
            f"LOCATION:{loc}",
            f"CATEGORIES:{ev['region'] or 'Other'}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return PlainTextResponse("\r\n".join(lines), media_type="text/calendar")


# ---------- auth ----------

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    ip = request.client.host if request.client else "?"
    ua = request.headers.get("user-agent", "")
    attempted = username.strip().lower()
    if auth.rate_limited(ip):
        db.log_login(attempted, "rate_limited", ip, ua)
        return templates.TemplateResponse(
            request, "login.html", {"error": "Too many attempts — wait ten minutes."}, status_code=429)
    auth.record_attempt(ip)
    user = db.get_user(attempted)
    if not user or not auth.check_password(password, user["pw_hash"]):
        db.log_login(attempted, "login_failed", ip, ua)
        return templates.TemplateResponse(
            request, "login.html", {"error": "Wrong username or password."}, status_code=401)
    db.log_login(user["username"], "login_ok", ip, ua)
    resp = RedirectResponse("/dashboard", status_code=303)
    resp.set_cookie(auth.COOKIE, auth.make_session(user["username"]),
                    httponly=True, samesite="lax", secure=True, max_age=auth.SESSION_TTL)
    return resp


@app.post("/logout")
def logout(request: Request):
    user, _ = current_user(request)
    if user:
        ip = request.client.host if request.client else "?"
        db.log_login(user["username"], "logout", ip, request.headers.get("user-agent", ""))
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(auth.COOKIE)
    return resp


# ---------- governor / admin ----------

def require_user(request: Request):
    user, sess = current_user(request)
    if not user:
        return None, None, RedirectResponse("/login", status_code=303)
    return user, sess, None


def can_edit(user, ev) -> bool:
    if user["role"] == "admin":
        return True
    return ev["region"] == user["region"] and user["region"] is not None


@app.get("/help", response_class=HTMLResponse)
def help_page(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    return templates.TemplateResponse(request, "help.html", {"user": user})


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    region = user["region"] if user["role"] == "governor" else (request.query_params.get("region") or None)
    events = db.list_events(region=region, include_hidden=True)
    today = date.today().isoformat()
    upcoming = [e for e in events if e["end_date"][:10] >= today]
    past = [e for e in events if e["end_date"][:10] < today][::-1]
    hidden = [e for e in events if e["hidden"]]
    archived = db.list_events(region=region, status="archived", include_hidden=True)  # governors: own region; admins: filterable
    return templates.TemplateResponse(request, "dashboard.html", {
        "user": user, "csrf": sess["csrf"], "upcoming": upcoming, "past": past,
        "hidden": hidden, "archived": archived[::-1], "region_filter": region,
    })


def event_from_form(form, user):
    region = form.get("region") or None
    if user["role"] == "governor":
        region = user["region"]  # governors can only file under their own region
    start = form.get("start_date", "")
    end = form.get("end_date", "") or start
    if end < start:
        start, end = end, start
    return {
        "title": form.get("title", "").strip(),
        "club": form.get("club", "").strip(),
        "region": region,
        "event_type": form.get("event_type", "Field Trial"),
        "start_date": start, "end_date": end,
        "city": form.get("city", "").strip(),
        "state": form.get("state", "").strip().upper()[:2],
        "venue": form.get("venue", "").strip(),
        "stakes_open": 1 if form.get("stakes_open") else 0,
        "stakes_amateur": 1 if form.get("stakes_amateur") else 0,
        "stakes_puppy": 1 if form.get("stakes_puppy") else 0,
        "stakes_cocker": 1 if form.get("stakes_cocker") else 0,
        "water_test": 1 if form.get("water_test") else 0,
        "cost": form.get("cost", "").strip(),
        "entries_close": form.get("entries_close", "").strip(),
        "judge1": form.get("judge1", "").strip(), "judge2": form.get("judge2", "").strip(),
        "judge3": form.get("judge3", "").strip(), "judge4": form.get("judge4", "").strip(),
        "apprentice_judges": form.get("apprentice_judges", "").strip(),
        "link_url": form.get("link_url", "").strip(),
        "notes": form.get("notes", "").strip(),
        "status": form.get("status", "scheduled"),
    }


@app.get("/events/new", response_class=HTMLResponse)
def new_event_form(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    blank = {f: "" for f in db.EVENT_FIELDS}
    blank.update(status="scheduled", event_type="Field Trial", region=user["region"] or "")
    return templates.TemplateResponse(request, "event_form.html", {
        "user": user, "csrf": sess["csrf"], "ev": blank, "is_new": True,
    })


@app.post("/events/new")
async def create_event(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    form = await request.form()
    if form.get("csrf") != sess["csrf"]:
        return PlainTextResponse("Bad CSRF token", status_code=403)
    data = event_from_form(form, user)
    if not data["title"] or not data["start_date"]:
        return PlainTextResponse("Title and start date are required", status_code=400)
    db.create_event(data, user["username"])
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/events/{event_id}/edit", response_class=HTMLResponse)
def edit_event_form(request: Request, event_id: int):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    ev = db.get_event(event_id)
    if not ev or not can_edit(user, ev):
        return PlainTextResponse("Not found or not yours to edit", status_code=404)
    return templates.TemplateResponse(request, "event_form.html", {
        "user": user, "csrf": sess["csrf"], "ev": ev, "is_new": False,
    })


@app.post("/events/{event_id}/edit")
async def save_event(request: Request, event_id: int):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    ev = db.get_event(event_id)
    if not ev or not can_edit(user, ev):
        return PlainTextResponse("Not found or not yours to edit", status_code=404)
    form = await request.form()
    if form.get("csrf") != sess["csrf"]:
        return PlainTextResponse("Bad CSRF token", status_code=403)
    db.update_event(event_id, event_from_form(form, user), user["username"])
    return RedirectResponse("/dashboard", status_code=303)


# ---------- spreadsheet template download + bulk upload ----------

@app.get("/template.xlsx")
def template_download(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    if user["role"] == "governor":
        region = user["region"]  # the file announces whose schedule it is
    else:
        region = request.query_params.get("region") or None
        if region not in db.REGIONS:
            region = None
    fname = f"ESSFTA-{(region or 'field-trial').replace(' ', '-')}-schedule.xlsx"
    return Response(
        xlsx_io.build_template(region),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.post("/import")
async def import_xlsx(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    form = await request.form()
    if form.get("csrf") != sess["csrf"]:
        return PlainTextResponse("Bad CSRF token", status_code=403)
    upload = form.get("file")
    if upload is None or not getattr(upload, "filename", ""):
        return PlainTextResponse("No file uploaded", status_code=400)
    try:
        rows, declared, errors = xlsx_io.parse_upload(await upload.read())
    except Exception:
        return templates.TemplateResponse(request, "import_result.html", {
            "user": user, "created": [], "skipped": [],
            "errors": ["That file could not be read as an Excel (.xlsx) spreadsheet."],
        })
    if user["role"] == "governor":
        region = user["region"]  # always their own, whatever the file says
        if declared and declared != region:
            errors.insert(0, f"Heads up: the spreadsheet is marked {declared}, but you are the {region} "
                             f"governor, so these events were added to {region}. If that's the wrong file, "
                             f"hide these events and ask the {declared} governor to upload it.")
    else:
        picked = form.get("region") or None
        region = declared or (picked if picked in db.REGIONS else None)
        if declared and picked and picked in db.REGIONS and declared != picked:
            errors.insert(0, f"The spreadsheet is marked {declared}, which overrode your {picked} selection.")
    created, skipped = [], []
    for row in rows:
        row["region"] = region
        con = db.connect()
        dup = con.execute("SELECT id FROM events WHERE club=? AND start_date=? AND status != 'archived'",
                          (row["club"], row["start_date"])).fetchone()
        con.close()
        if dup:
            skipped.append(f"{row['club']} — {row['start_date']} already on the calendar")
            continue
        eid = db.create_event(row, user["username"] + ":xlsx")
        created.append({**row, "id": eid})
    return templates.TemplateResponse(request, "import_result.html", {
        "user": user, "created": created, "skipped": skipped, "errors": errors,
    })


# ---------- admin: manage governor accounts ----------

def require_admin(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return None, None, redir
    if user["role"] != "admin":
        return None, None, PlainTextResponse("Admins only", status_code=403)
    return user, sess, None


def generate_password():
    import secrets
    return "-".join(secrets.token_hex(2) for _ in range(3))


def render_users(request, user, sess, new_password=None, pw_for=None):
    return templates.TemplateResponse(request, "users.html", {
        "user": user, "csrf": sess["csrf"], "users": db.list_users(),
        "last_seen": db.last_seen_map(),
        "new_password": new_password, "pw_for": pw_for,
    })


@app.get("/users", response_class=HTMLResponse)
def users_page(request: Request):
    user, sess, redir = require_admin(request)
    if redir:
        return redir
    return render_users(request, user, sess)


@app.get("/audit", response_class=HTMLResponse)
def audit_page(request: Request):
    """Admin-only: who signed in (or tried to), and who changed what. IPs are personal
    data — this page must never be linked from a public view or embedded."""
    user, sess, redir = require_admin(request)
    if redir:
        return redir
    qp = request.query_params
    f_user = qp.get("user") or None
    f_from = qp.get("from") or None
    f_to = qp.get("to") or None
    return templates.TemplateResponse(request, "audit.html", {
        "user": user, "csrf": sess["csrf"],
        "logins": db.list_login_events(username=f_user, date_from=f_from, date_to=f_to),
        "changes": db.recent_event_changes(150),
        "usernames": [u["username"] for u in db.list_users()],
        "f_user": f_user, "f_from": f_from, "f_to": f_to,
    })


@app.post("/users/new")
def add_governor(request: Request, username: str = Form(...), display_name: str = Form(...),
                 region: str = Form(...), csrf: str = Form(...)):
    user, sess, redir = require_admin(request)
    if redir:
        return redir
    if csrf != sess["csrf"] or region not in db.REGIONS:
        return PlainTextResponse("Bad request", status_code=403)
    username = username.strip().lower()
    if not username.isalnum() or db.get_user(username, include_inactive=True):
        return PlainTextResponse("Username taken or invalid (letters/numbers only)", status_code=400)
    pw = generate_password()
    db.create_user(username, display_name.strip(), "governor", region, auth.hash_password(pw))
    return render_users(request, user, sess, new_password=pw, pw_for=username)


@app.post("/users/{username}/resetpw")
def reset_password(request: Request, username: str, csrf: str = Form(...)):
    user, sess, redir = require_admin(request)
    if redir:
        return redir
    target = db.get_user(username, include_inactive=True)
    if csrf != sess["csrf"] or not target:
        return PlainTextResponse("Bad request", status_code=403)
    pw = generate_password()
    db.set_password(username, auth.hash_password(pw))
    return render_users(request, user, sess, new_password=pw, pw_for=username)


@app.post("/users/{username}/active")
def toggle_active(request: Request, username: str, active: str = Form(...), csrf: str = Form(...)):
    user, sess, redir = require_admin(request)
    if redir:
        return redir
    target = db.get_user(username, include_inactive=True)
    if csrf != sess["csrf"] or not target:
        return PlainTextResponse("Bad request", status_code=403)
    if target["username"] == user["username"]:
        return PlainTextResponse("You can't deactivate your own account", status_code=400)
    db.set_user_active(username, active == "1")
    return RedirectResponse("/users", status_code=303)


@app.post("/events/{event_id}/status")
async def change_status(request: Request, event_id: int, status: str = Form(...), csrf: str = Form(...)):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    ev = db.get_event(event_id)
    if not ev or not can_edit(user, ev):
        return PlainTextResponse("Not found or not yours to edit", status_code=404)
    if csrf != sess["csrf"] or status not in ("scheduled", "canceled", "postponed", "archived"):
        return PlainTextResponse("Bad request", status_code=403)
    db.set_status(event_id, status, user["username"])
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/events/{event_id}/hidden")
async def change_hidden(request: Request, event_id: int, hidden: str = Form(...), csrf: str = Form(...)):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    ev = db.get_event(event_id)
    if not ev or not can_edit(user, ev):
        return PlainTextResponse("Not found or not yours to edit", status_code=404)
    if csrf != sess["csrf"] or hidden not in ("0", "1"):
        return PlainTextResponse("Bad request", status_code=403)
    db.set_hidden(event_id, hidden == "1", user["username"])
    return RedirectResponse("/dashboard", status_code=303)


# ---------- bulk operations (hide / unhide by date range, batch undo) ----------

BULK_ACTIONS = {
    # action -> (label, select kwargs for bulk_select, apply function, admin_only)
    "hide": ("Hide from all public views",
             {"statuses": ("scheduled", "canceled", "postponed"), "hidden": 0},
             lambda eid, u, b: db.set_hidden(eid, True, u, batch_id=b), False),
    "unhide": ("Put back on the public views",
               {"statuses": ("scheduled", "canceled", "postponed"), "hidden": 1},
               lambda eid, u, b: db.set_hidden(eid, False, u, batch_id=b), False),
    "remove": ("Remove (move to the removed list)",
               {"statuses": ("scheduled", "canceled", "postponed")},
               lambda eid, u, b: db.set_status(eid, "archived", u, batch_id=b), True),
    "restore": ("Restore removed events to the calendar",
                {"statuses": ("archived",)},
                lambda eid, u, b: db.set_status(eid, "scheduled", u, batch_id=b), True),
}


def bulk_region_scope(user, submitted):
    """Governors act on their own region only, whatever the form claims — security boundary."""
    if user["role"] == "governor":
        return user["region"]
    r = submitted or "ALL"
    return r if (r in db.REGIONS or r in ("ALL", "NONE")) else "ALL"


def region_label(scope):
    return {"ALL": "all regions", "NONE": "no-region (National / other)"}.get(scope, scope + " region")


def _iso(s):
    try:
        return date.fromisoformat((s or "").strip()).isoformat()
    except ValueError:
        return None


def new_batch_id():
    import secrets
    return date.today().strftime("%y%m%d") + "-" + secrets.token_hex(3)


def render_bulk(request, user, sess, **extra):
    batches = db.list_batches(created_by=None if user["role"] == "admin" else user["username"])
    ctx = {"user": user, "csrf": sess["csrf"], "stage": "form",
           "today": date.today().isoformat(), "batches": batches,
           "message": None, "error": None}
    ctx.update(extra)
    return templates.TemplateResponse(request, "bulk.html", ctx)


@app.get("/bulk", response_class=HTMLResponse)
def bulk_form(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    return render_bulk(request, user, sess)


async def bulk_params(request, user, sess):
    """Shared validation for preview and apply. Returns (params, error_response)."""
    form = await request.form()
    if form.get("csrf") != sess["csrf"]:
        return None, PlainTextResponse("Bad CSRF token", status_code=403)
    action = form.get("action", "")
    if action not in BULK_ACTIONS:
        return None, PlainTextResponse("Bad request", status_code=400)
    if BULK_ACTIONS[action][3] and user["role"] != "admin":
        return None, PlainTextResponse("Admins only", status_code=403)
    date_from, date_to = _iso(form.get("date_from")), _iso(form.get("date_to"))
    if not date_from or not date_to or date_to < date_from:
        return None, render_bulk(request, user, sess, error="Please give a valid date range (from ≤ to).")
    scope = bulk_region_scope(user, form.get("region"))
    return {"action": action, "date_from": date_from, "date_to": date_to, "scope": scope}, None


@app.post("/bulk/preview")
async def bulk_preview(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    p, err = await bulk_params(request, user, sess)
    if err:
        return err
    label, sel, _, _ = BULK_ACTIONS[p["action"]]
    events = db.bulk_select(p["date_from"], p["date_to"], p["scope"], **sel)
    return render_bulk(request, user, sess, stage="preview", events=events,
                       action=p["action"], action_label=label,
                       date_from=p["date_from"], date_to=p["date_to"],
                       scope=p["scope"], scope_label=region_label(p["scope"]))


@app.post("/bulk/apply")
async def bulk_apply(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    p, err = await bulk_params(request, user, sess)
    if err:
        return err
    label, sel, apply_fn, _ = BULK_ACTIONS[p["action"]]
    # re-select server-side: what gets changed is exactly what the preview showed,
    # never a list of ids the browser could have tampered with
    events = db.bulk_select(p["date_from"], p["date_to"], p["scope"], **sel)
    if not events:
        return render_bulk(request, user, sess, error="Nothing matched — no events were changed.")
    batch = new_batch_id()
    for ev in events:
        apply_fn(ev["id"], user["username"], batch)
    desc = f"{p['action']}: {region_label(p['scope'])}, {p['date_from']} → {p['date_to']}"
    db.create_batch(batch, user["username"], p["action"], desc, len(events))
    return render_bulk(request, user, sess, stage="result", events=events,
                       action_label=label, batch_id=batch,
                       message=f"Done — {len(events)} event{'s' if len(events) != 1 else ''} changed "
                               f"(batch {batch}). You can undo this below.")


@app.post("/bulk/undo")
async def bulk_undo(request: Request, batch_id: str = Form(...), csrf: str = Form(...)):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    if csrf != sess["csrf"]:
        return PlainTextResponse("Bad CSRF token", status_code=403)
    batch = db.get_batch(batch_id)
    if not batch:
        return PlainTextResponse("No such batch", status_code=404)
    if user["role"] != "admin" and batch["created_by"] != user["username"]:
        return PlainTextResponse("Not your batch to undo", status_code=403)
    if batch["undone_at"]:
        return render_bulk(request, user, sess, error=f"Batch {batch_id} was already undone.")
    import json as _json
    count = 0
    for h in db.batch_history(batch_id):
        snap = _json.loads(h["snapshot_json"]) or {}
        if h["action"] == "create":
            # a roll-forward created this event: archive it (nothing is ever hard-deleted)
            db.set_status(h["event_id"], "archived", user["username"], batch_id=batch_id + "-undo")
        elif h["action"].startswith("hidden:"):
            db.set_hidden(h["event_id"], snap.get("hidden", 0), user["username"], batch_id=batch_id + "-undo")
        else:
            db.set_status(h["event_id"], snap.get("status", "scheduled"), user["username"],
                          batch_id=batch_id + "-undo")
        count += 1
    db.mark_batch_undone(batch_id)
    return render_bulk(request, user, sess,
                       message=f"Batch {batch_id} undone — {count} event{'s' if count != 1 else ''} put back.")


# ---------- roll a season forward (Ted's idea) ----------

ROLL_CARRY = ["club", "region", "event_type", "city", "state", "venue",
              "stakes_open", "stakes_amateur", "stakes_puppy", "stakes_cocker", "water_test"]
# judges, fees, closing dates, links and notes change every year — deliberately NOT carried


def shift_to_year(d: date, target_year: int) -> date:
    """Same time of year, same day of the week: nearest matching weekday to the
    anniversary date. For a one-year roll this is the familiar 52/53-week shift."""
    try:
        anchor = d.replace(year=target_year)
    except ValueError:  # Feb 29
        anchor = d.replace(year=target_year, day=28)
    delta = (d.weekday() - anchor.weekday()) % 7
    cand = anchor + timedelta(days=delta)
    return cand - timedelta(days=7) if delta > 3 else cand


def build_roll_plan(scope, source_year: int, target_year: int):
    """Plan rows: (source event, new_start, new_end, disposition, dup_of)."""
    events = db.bulk_select(f"{source_year}-01-01", f"{source_year}-12-31", scope,
                            ("scheduled", "canceled", "postponed"))
    plan = []
    for ev in events:
        s = date.fromisoformat(ev["start_date"][:10])
        e = date.fromisoformat(ev["end_date"][:10])
        ns = shift_to_year(s, target_year)
        ne = ns + (e - s)
        if ev["status"] == "canceled":
            plan.append({"ev": ev, "new_start": ns.isoformat(), "new_end": ne.isoformat(),
                         "disposition": "canceled", "dup_of": None})
            continue
        dup = db.find_near_duplicate(ev["club"], ns.isoformat())
        plan.append({"ev": ev, "new_start": ns.isoformat(), "new_end": ne.isoformat(),
                     "disposition": "dup" if dup else "create", "dup_of": dup})
    return plan


def render_roll(request, user, sess, **extra):
    years = db.distinct_event_years()
    this_year = date.today().year
    ctx = {"user": user, "csrf": sess["csrf"], "stage": "form", "years": years,
           "source_year": this_year, "target_year": this_year + 1,
           "message": None, "error": None}
    ctx.update(extra)
    return templates.TemplateResponse(request, "rollforward.html", ctx)


@app.get("/rollforward", response_class=HTMLResponse)
def rollforward_form(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    return render_roll(request, user, sess)


async def roll_params(request, user, sess):
    form = await request.form()
    if form.get("csrf") != sess["csrf"]:
        return None, None, PlainTextResponse("Bad CSRF token", status_code=403)
    try:
        sy, ty = int(form.get("source_year", "")), int(form.get("target_year", ""))
    except ValueError:
        return None, None, PlainTextResponse("Bad year", status_code=400)
    if not (2000 <= sy <= 2100 and 2000 <= ty <= 2100) or sy == ty:
        return None, None, render_roll(request, user, sess,
                                       error="Pick a source year and a different target year.")
    scope = bulk_region_scope(user, form.get("region"))
    if scope == "ALL":  # one region at a time keeps a mistake one region wide
        scope = "NONE" if user["role"] == "admin" and form.get("region") == "NONE" else None
    if scope is None:
        return None, None, render_roll(request, user, sess, error="Pick a region to roll forward.")
    return form, {"sy": sy, "ty": ty, "scope": scope}, None


@app.post("/rollforward/preview")
async def rollforward_preview(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    form, p, err = await roll_params(request, user, sess)
    if err:
        return err
    plan = build_roll_plan(p["scope"], p["sy"], p["ty"])
    return render_roll(request, user, sess, stage="preview", plan=plan,
                       source_year=p["sy"], target_year=p["ty"],
                       scope=p["scope"], scope_label=region_label(p["scope"]),
                       creatable=sum(1 for r in plan if r["disposition"] == "create"))


@app.post("/rollforward/apply")
async def rollforward_apply(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    form, p, err = await roll_params(request, user, sess)
    if err:
        return err
    include = set(form.getlist("include"))
    # the plan is recomputed server-side; the checkboxes can only NARROW it,
    # never reach events outside the caller's region scope
    plan = [r for r in build_roll_plan(p["scope"], p["sy"], p["ty"])
            if r["disposition"] == "create" and str(r["ev"]["id"]) in include]
    if not plan:
        return render_roll(request, user, sess, error="Nothing selected — no events were created.")
    batch = new_batch_id()
    created = []
    for r in plan:
        ev = r["ev"]
        data = {f: ev[f] for f in ROLL_CARRY}
        data["title"] = (ev["title"] or "").replace(str(p["sy"]), str(p["ty"]))
        data["start_date"], data["end_date"] = r["new_start"], r["new_end"]
        data["status"] = "scheduled"
        data["source"] = "rollforward"
        eid = db.create_event(data, user["username"], batch_id=batch)
        created.append({**data, "id": eid})
    db.create_batch(batch, user["username"], "rollforward",
                    f"rollforward: {region_label(p['scope'])}, {p['sy']} → {p['ty']}", len(created))
    return render_roll(request, user, sess, stage="result", created=created,
                       source_year=p["sy"], target_year=p["ty"], batch_id=batch,
                       message=f"Created {len(created)} event{'s' if len(created) != 1 else ''} "
                               f"for {p['ty']} (batch {batch}).")
