#!/bin/bash
# Functional smoke test against a running instance.
# Usage: ./seed/smoke_test.sh http://localhost:8791 <east_pw> <admin_user> <admin_pw>
set -u
BASE=$1; EAST_PW=$2; ADMIN=$3; ADMIN_PW=$4
pass=0; fail=0
ck() { if [ "$1" = "$2" ]; then pass=$((pass+1)); echo "PASS: $3"; else fail=$((fail+1)); echo "FAIL: $3 (got $1, want $2)"; fi }

tok() { # login, print session cookie value
  curl -s -i -X POST "$BASE/login" -d "username=$1&password=$2" \
    | grep -i '^set-cookie: essfta_events_session=' | sed 's/.*session=\([^;]*\);.*/\1/'
}

# 1. bad password rejected
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/login" -d "username=east&password=wrong")
ck "$code" 401 "bad password rejected"

# 2. governor login works
T=$(tok east "$EAST_PW")
[ -n "$T" ] && ck ok ok "east login sets session" || ck no ok "east login sets session"
C="Cookie: essfta_events_session=$T"

# 3. dashboard shows own region
curl -s "$BASE/dashboard" -H "$C" | grep -q "East region events" && ck ok ok "east dashboard scoped" || ck no ok "east dashboard scoped"

# 4. east cannot edit a Mid West event
MW=$(curl -s "$BASE/?region=Mid+West&past=1&year=2026" | grep -o 'events/[0-9]*' | head -1)
MW_ID=$(sqlite3 "$(dirname "$0")/../data/events.db" "SELECT id FROM events WHERE region='Mid West' LIMIT 1")
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/events/$MW_ID/edit" -H "$C")
ck "$code" 404 "east blocked from Mid West event"

# 5. east CAN open own event
E_ID=$(sqlite3 "$(dirname "$0")/../data/events.db" "SELECT id FROM events WHERE region='East' LIMIT 1")
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/events/$E_ID/edit" -H "$C")
ck "$code" 200 "east can edit East event"

# 6. governor blocked from user management
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/users" -H "$C")
ck "$code" 403 "governor blocked from /users"

# 7. create event as east — needs csrf from session; pull the form and post
CSRF=$(curl -s "$BASE/events/new" -H "$C" | grep -o 'name="csrf" value="[^"]*"' | head -1 | sed 's/.*value="//;s/"//')
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/events/new" -H "$C" \
  -d "csrf=$CSRF&title=SMOKE TEST EVENT&club=Smoke Test Club&start_date=2027-06-01&end_date=2027-06-02&event_type=Field Trial&region=Mid West&city=Testville&state=NY&status=scheduled")
ck "$code" 303 "east creates event"
REG=$(sqlite3 "$(dirname "$0")/../data/events.db" "SELECT region FROM events WHERE title='SMOKE TEST EVENT'")
ck "$REG" "East" "region forced to governor's own despite form tampering"

# 8. admin login + /users + add/deactivate governor
TA=$(tok "$ADMIN" "$ADMIN_PW"); CA="Cookie: essfta_events_session=$TA"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/users" -H "$CA")
ck "$code" 200 "admin reaches /users"
CSRFA=$(curl -s "$BASE/users" -H "$CA" | grep -o 'name="csrf" value="[^"]*"' | head -1 | sed 's/.*value="//;s/"//')
curl -s -X POST "$BASE/users/new" -H "$CA" -d "csrf=$CSRFA&username=smoketest&display_name=Smoke Test&region=West" | grep -q "Password for" && ck ok ok "admin adds governor (pw shown once)" || ck no ok "admin adds governor"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/users/smoketest/active" -H "$CA" -d "csrf=$CSRFA&active=0")
ck "$code" 303 "admin deactivates governor"
ACT=$(sqlite3 "$(dirname "$0")/../data/events.db" "SELECT active FROM users WHERE username='smoketest'")
ck "$ACT" 0 "deactivated in DB"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/login" -d "username=smoketest&password=whatever")
ck "$code" 401 "deactivated user cannot log in"

# 9. audit log: governors blocked, admin sees it, sign-ins were recorded
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/audit" -H "$C")
ck "$code" 403 "governor blocked from /audit"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/audit" -H "$CA")
ck "$code" 200 "admin reaches /audit"
DB="$(dirname "$0")/../data/events.db"
NOK=$(sqlite3 "$DB" "SELECT COUNT(*) FROM login_events WHERE username='east' AND event='login_ok'")
[ "$NOK" -ge 1 ] && ck ok ok "login_ok recorded for east" || ck no ok "login_ok recorded for east"
NFAIL=$(sqlite3 "$DB" "SELECT COUNT(*) FROM login_events WHERE username='east' AND event='login_failed'")
[ "$NFAIL" -ge 1 ] && ck ok ok "login_failed recorded for east" || ck no ok "login_failed recorded for east"

# 10. hide flag: off public views, still visible signed-in, unhide works
curl -s -o /dev/null -X POST "$BASE/events/$E_ID/hidden" -H "$C" -d "csrf=$CSRF&hidden=1"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/event/$E_ID")
ck "$code" 404 "hidden event 404s for the public"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/event/$E_ID" -H "$C")
ck "$code" 200 "hidden event visible signed-in"
curl -s -o /dev/null -X POST "$BASE/events/$E_ID/hidden" -H "$C" -d "csrf=$CSRF&hidden=0"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/event/$E_ID")
ck "$code" 200 "unhidden event public again"

# 11. bulk: governor region isolation despite form tampering, then batch undo
curl -s -o /dev/null -X POST "$BASE/bulk/apply" -H "$C" \
  -d "csrf=$CSRF&action=hide&date_from=2026-01-01&date_to=2026-12-31&region=Mid West"
MWH=$(sqlite3 "$DB" "SELECT COUNT(*) FROM events WHERE region='Mid West' AND hidden=1")
ck "$MWH" 0 "bulk hide never touches another region despite tampering"
EH=$(sqlite3 "$DB" "SELECT COUNT(*) FROM events WHERE region='East' AND hidden=1")
[ "$EH" -ge 1 ] && ck ok ok "bulk hide hid East events" || ck no ok "bulk hide hid East events"
BATCH=$(sqlite3 "$DB" "SELECT id FROM batches ORDER BY created_at DESC, rowid DESC LIMIT 1")
curl -s -o /dev/null -X POST "$BASE/bulk/undo" -H "$C" -d "csrf=$CSRF&batch_id=$BATCH"
EH2=$(sqlite3 "$DB" "SELECT COUNT(*) FROM events WHERE hidden=1")
ck "$EH2" 0 "bulk undo restored everything"

# 12. governor blocked from admin-only bulk remove
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/bulk/apply" -H "$C" \
  -d "csrf=$CSRF&action=remove&date_from=2026-01-01&date_to=2026-12-31")
ck "$code" 403 "governor blocked from bulk remove"

# 13. roll-forward: region forced despite tampering, undo archives the batch
SRC=$(sqlite3 "$DB" "SELECT id FROM events WHERE region='East' AND start_date LIKE '2026%' AND status='scheduled' LIMIT 1")
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/rollforward/preview" -H "$C" \
  -d "csrf=$CSRF&source_year=2026&target_year=2028&region=Mid West")
ck "$code" 200 "rollforward preview renders"
curl -s -o /dev/null -X POST "$BASE/rollforward/apply" -H "$C" \
  -d "csrf=$CSRF&source_year=2026&target_year=2028&region=Mid West&include=$SRC"
NRF=$(sqlite3 "$DB" "SELECT COUNT(*) FROM events WHERE source='rollforward'")
ck "$NRF" 1 "rollforward created exactly the ticked event"
RFREG=$(sqlite3 "$DB" "SELECT region FROM events WHERE source='rollforward'")
ck "$RFREG" "East" "rollforward stayed in the governor's own region despite tampering"
RFJ=$(sqlite3 "$DB" "SELECT judge1 || cost || link_url FROM events WHERE source='rollforward'")
ck "x$RFJ" "x" "judges/fees/links not carried forward"
BATCH2=$(sqlite3 "$DB" "SELECT id FROM batches WHERE action='rollforward' ORDER BY created_at DESC, rowid DESC LIMIT 1")
curl -s -o /dev/null -X POST "$BASE/bulk/undo" -H "$C" -d "csrf=$CSRF&batch_id=$BATCH2"
RFA=$(sqlite3 "$DB" "SELECT status FROM events WHERE source='rollforward'")
ck "$RFA" "archived" "rollforward undo archived the created event"

# 14. public pages + headers
curl -s -D - -o /dev/null "$BASE/" | grep -qi "frame-ancestors" && ck ok ok "CSP frame-ancestors on public page" || ck no ok "CSP frame-ancestors"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/events.ics"); ck "$code" 200 "iCal feed"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/print");      ck "$code" 200 "print view"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/embed-demo"); ck "$code" 200 "embed demo"

# cleanup test artifacts (rollforward events + batches too, so reruns start clean)
sqlite3 "$(dirname "$0")/../data/events.db" "DELETE FROM events WHERE title='SMOKE TEST EVENT'; DELETE FROM users WHERE username='smoketest'; DELETE FROM events WHERE source='rollforward'; DELETE FROM batches; DELETE FROM event_history WHERE batch_id IS NOT NULL;"
echo; echo "RESULT: $pass passed, $fail failed"
[ "$fail" = 0 ]
