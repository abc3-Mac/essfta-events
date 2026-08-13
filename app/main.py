"""ESSFTA Field Events calendar — governor-maintained events, embeddable public views."""
import calendar as calmod
import os
from datetime import date, datetime, timedelta

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import auth, db

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
    if auth.rate_limited(ip):
        return templates.TemplateResponse(
            request, "login.html", {"error": "Too many attempts — wait ten minutes."}, status_code=429)
    auth.record_attempt(ip)
    user = db.get_user(username.strip().lower())
    if not user or not auth.check_password(password, user["pw_hash"]):
        return templates.TemplateResponse(
            request, "login.html", {"error": "Wrong username or password."}, status_code=401)
    resp = RedirectResponse("/dashboard", status_code=303)
    resp.set_cookie(auth.COOKIE, auth.make_session(user["username"]),
                    httponly=True, samesite="lax", secure=True, max_age=auth.SESSION_TTL)
    return resp


@app.post("/logout")
def logout():
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


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    region = user["region"] if user["role"] == "governor" else (request.query_params.get("region") or None)
    events = db.list_events(region=region)
    today = date.today().isoformat()
    upcoming = [e for e in events if e["end_date"][:10] >= today]
    past = [e for e in events if e["end_date"][:10] < today][::-1]
    return templates.TemplateResponse(request, "dashboard.html", {
        "user": user, "csrf": sess["csrf"], "upcoming": upcoming, "past": past,
        "region_filter": region,
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


@app.get("/users", response_class=HTMLResponse)
def users_page(request: Request):
    user, sess, redir = require_admin(request)
    if redir:
        return redir
    return templates.TemplateResponse(request, "users.html", {
        "user": user, "csrf": sess["csrf"], "users": db.list_users(),
        "new_password": None, "pw_for": None,
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
    return templates.TemplateResponse(request, "users.html", {
        "user": user, "csrf": sess["csrf"], "users": db.list_users(),
        "new_password": pw, "pw_for": username,
    })


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
    return templates.TemplateResponse(request, "users.html", {
        "user": user, "csrf": sess["csrf"], "users": db.list_users(),
        "new_password": pw, "pw_for": username,
    })


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
