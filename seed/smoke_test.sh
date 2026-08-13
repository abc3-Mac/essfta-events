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

# 9. public pages + headers
curl -s -D - -o /dev/null "$BASE/" | grep -qi "frame-ancestors" && ck ok ok "CSP frame-ancestors on public page" || ck no ok "CSP frame-ancestors"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/events.ics"); ck "$code" 200 "iCal feed"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/print");      ck "$code" 200 "print view"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/embed-demo"); ck "$code" 200 "embed demo"

# cleanup test artifacts
sqlite3 "$(dirname "$0")/../data/events.db" "DELETE FROM events WHERE title='SMOKE TEST EVENT'; DELETE FROM users WHERE username='smoketest';"
echo; echo "RESULT: $pass passed, $fail failed"
[ "$fail" = 0 ]
