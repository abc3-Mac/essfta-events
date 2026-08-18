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
E_ID=$(sqlite3 "$(dirname "$0")/../data/events.db" "SELECT id FROM events WHERE region='East' AND status='scheduled' AND end_date >= date('now') LIMIT 1")
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

# 14a. excel export + edit-in-place round trip with undo
PY="$(dirname "$0")/../.venv/bin/python"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/excel" -H "$C")
ck "$code" 200 "excel tools page renders"
curl -s "$BASE/export.xlsx?year=2026" -H "$C" -o /tmp/essfta-export-test.xlsx
$PY - <<'PYEOF'
from openpyxl import load_workbook
wb = load_workbook("/tmp/essfta-export-test.xlsx")
ws = wb.active
assert "EVENT ID" in str(ws.cell(row=2, column=10).value), "no id column"
ws.cell(row=3, column=5, value="SmokeCity")  # first data row, CITY column
wb.save("/tmp/essfta-export-test.xlsx")
print(int(ws.cell(row=3, column=10).value))
PYEOF
EDIT_ID=$($PY - <<'PYEOF'
from openpyxl import load_workbook
ws = load_workbook("/tmp/essfta-export-test.xlsx").active
print(int(ws.cell(row=3, column=10).value))
PYEOF
)
[ -n "$EDIT_ID" ] && ck ok ok "export has EVENT ID column" || ck no ok "export has EVENT ID column"
PREVIEW=$(curl -s -X POST "$BASE/import" -H "$C" -F "csrf=$CSRF" -F "file=@/tmp/essfta-export-test.xlsx")
echo "$PREVIEW" | grep -q "will be updated" && ck ok ok "xlsx edit shows update preview" || ck no ok "xlsx edit shows update preview"
TOKEN=$(echo "$PREVIEW" | grep -o 'name="pending" value="[^"]*"' | sed 's/.*value="//;s/"//')
curl -s -o /dev/null -X POST "$BASE/import/apply" -H "$C" -d "csrf=$CSRF&pending=$TOKEN"
CITY=$(sqlite3 "$DB" "SELECT city FROM events WHERE id=$EDIT_ID")
ck "$CITY" "SmokeCity" "xlsx edit applied to the event"
BX=$(sqlite3 "$DB" "SELECT id FROM batches WHERE action='xlsx-import' ORDER BY created_at DESC, rowid DESC LIMIT 1")
curl -s -o /dev/null -X POST "$BASE/bulk/undo" -H "$C" -d "csrf=$CSRF&batch_id=$BX"
CITY2=$(sqlite3 "$DB" "SELECT city FROM events WHERE id=$EDIT_ID")
[ "$CITY2" != "SmokeCity" ] && ck ok ok "xlsx edit undo restored the city" || ck no ok "xlsx edit undo restored the city"

# 14b. ticked-events actions: region isolation, shift + undo
MW_ID2=$(sqlite3 "$DB" "SELECT id FROM events WHERE region='Mid West' AND status='scheduled' LIMIT 1")
curl -s -o /dev/null -X POST "$BASE/bulk/selected" -H "$C" -d "csrf=$CSRF&action=hide&ids=$E_ID&ids=$MW_ID2"
MWH2=$(sqlite3 "$DB" "SELECT hidden FROM events WHERE id=$MW_ID2")
ck "$MWH2" 0 "ticked action skips another region's event"
EH3=$(sqlite3 "$DB" "SELECT hidden FROM events WHERE id=$E_ID")
ck "$EH3" 1 "ticked hide applied to own event"
BT=$(sqlite3 "$DB" "SELECT id FROM batches ORDER BY created_at DESC, rowid DESC LIMIT 1")
curl -s -o /dev/null -X POST "$BASE/bulk/undo" -H "$C" -d "csrf=$CSRF&batch_id=$BT"
EH4=$(sqlite3 "$DB" "SELECT hidden FROM events WHERE id=$E_ID")
ck "$EH4" 0 "ticked hide undone"
OLDSTART=$(sqlite3 "$DB" "SELECT start_date FROM events WHERE id=$E_ID")
curl -s -o /dev/null -X POST "$BASE/bulk/selected" -H "$C" -d "csrf=$CSRF&action=shift&days=7&ids=$E_ID"
NEWSTART=$(sqlite3 "$DB" "SELECT start_date FROM events WHERE id=$E_ID")
WANT=$(sqlite3 "$DB" "SELECT date('$OLDSTART', '+7 days')")
ck "$NEWSTART" "$WANT" "shift moved the start date +7"
BS=$(sqlite3 "$DB" "SELECT id FROM batches ORDER BY created_at DESC, rowid DESC LIMIT 1")
curl -s -o /dev/null -X POST "$BASE/bulk/undo" -H "$C" -d "csrf=$CSRF&batch_id=$BS"
BACKSTART=$(sqlite3 "$DB" "SELECT start_date FROM events WHERE id=$E_ID")
ck "$BACKSTART" "$OLDSTART" "shift undo restored the date"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/bulk/selected" -H "$C" -d "csrf=$CSRF&action=remove&ids=$E_ID")
ck "$code" 403 "governor blocked from ticked remove"

# 14c. single copy-to-next-year
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/events/$E_ID/copyforward" -H "$C" -d "csrf=$CSRF")
ck "$code" 303 "copyforward creates and redirects to edit"
CFN=$(sqlite3 "$DB" "SELECT COUNT(*) FROM events WHERE source='rollforward' AND created_by='east'")
[ "$CFN" -ge 1 ] && ck ok ok "copyforward event created" || ck no ok "copyforward event created"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/events/$MW_ID2/copyforward" -H "$C" -d "csrf=$CSRF")
ck "$code" 404 "copyforward blocked on another region's event"

# 14. help page: signed-in only, role-aware
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/help")
ck "$code" 303 "help redirects anonymous to login"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/help" -H "$C")
ck "$code" 200 "governor sees help"
curl -s "$BASE/help" -H "$CA" | grep -q "Administrator tools" && ck ok ok "admin help shows admin tools" || ck no ok "admin help shows admin tools"

# 14d. public past-events toggle: default ALLOWS the public past option; admins can turn it off
P_ID=$(sqlite3 "$DB" "SELECT id FROM events WHERE end_date < date('now') AND status='scheduled' AND hidden=0 LIMIT 1")
curl -s "$BASE/?past=1&year=2026" | grep -q "event/$P_ID\"" && ck ok ok "default: anon past=1 shows past events" || ck no ok "default: anon past=1 shows past events"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/event/$P_ID")
ck "$code" 200 "default: past event detail public"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/settings" -H "$C" -d "csrf=$CSRF&public_past=0")
ck "$code" 403 "governor blocked from /settings"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/settings" -H "$CA" -d "csrf=$CSRFA&public_past=0")
ck "$code" 303 "admin turns public past events off"
curl -s "$BASE/?past=1&year=2026" | grep -q "event/$P_ID\"" && ck no ok "toggled off: anon past=1 hides past events" || ck ok ok "toggled off: anon past=1 hides past events"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/event/$P_ID")
ck "$code" 404 "toggled off: past event detail 404s for the public"
curl -s "$BASE/?past=1&year=2026" -H "$C" | grep -q "event/$P_ID\"" && ck ok ok "toggled off: signed-in still sees past" || ck no ok "toggled off: signed-in still sees past"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/calendar?month=2026-01")
ck "$code" 303 "toggled off: anon calendar bounced off a past month"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/calendar?month=2026-01" -H "$C")
ck "$code" 200 "toggled off: signed-in calendar reaches past months"
OLDICS=$(curl -s "$BASE/events.ics" | grep -o 'DTSTART;VALUE=DATE:[0-9]*' | sort | head -1 | sed 's/.*://')
TODAYC=$(date +%Y%m%d)
[ -z "$OLDICS" ] || [ "$OLDICS" -ge "$TODAYC" ] && ck ok ok "toggled off: iCal carries no past events" || ck no ok "toggled off: iCal carries no past events (oldest $OLDICS)"
PRINTJAN=$(curl -s "$BASE/print?year=2026" | grep -c "JANUARY")
ck "$PRINTJAN" 0 "toggled off: public printable starts at today"
curl -s -o /dev/null -X POST "$BASE/settings" -H "$CA" -d "csrf=$CSRFA&public_past=1"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/event/$P_ID")
ck "$code" 200 "toggled back on: past detail public again"

# 15. public pages + headers
curl -s -D - -o /dev/null "$BASE/" | grep -qi "frame-ancestors" && ck ok ok "CSP frame-ancestors on public page" || ck no ok "CSP frame-ancestors"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/events.ics"); ck "$code" 200 "iCal feed"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/print");      ck "$code" 200 "print view"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/embed-demo"); ck "$code" 200 "embed demo"

# cleanup test artifacts (rollforward events + batches too, so reruns start clean)
sqlite3 "$(dirname "$0")/../data/events.db" "DELETE FROM events WHERE title='SMOKE TEST EVENT'; DELETE FROM users WHERE username='smoketest'; DELETE FROM events WHERE source='rollforward'; DELETE FROM batches; DELETE FROM event_history WHERE batch_id IS NOT NULL; DELETE FROM settings;"
echo; echo "RESULT: $pass passed, $fail failed"
[ "$fail" = 0 ]
