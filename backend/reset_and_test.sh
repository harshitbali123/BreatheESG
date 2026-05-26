#!/bin/bash
# ============================================================
# BreatheESG — full reset + verification script
# Run from the project root (where manage.py lives)
# Usage:
#   bash reset_and_test.sh          full reset + seed + verify
#   bash reset_and_test.sh --flush-only   just wipe, no reseed
# ============================================================
set -e
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}  ✓ $1${NC}"; }
fail() { echo -e "${RED}  ✗ $1${NC}"; }
info() { echo -e "${YELLOW}  → $1${NC}"; }

echo ""
echo "════════════════════════════════════════════"
echo "  BreatheESG — Reset & Verify"
echo "════════════════════════════════════════════"

# ── Step 1: Wipe all data ─────────────────────────────────
echo ""
info "Step 1: Wiping all seeded data..."

python3 manage.py shell << 'PYEOF'
from apps.audit.models import AuditLog
from apps.normalization.models import NormalizedActivity, EmissionFactor
from apps.ingestion.models import IngestionRun, RawRow
from apps.tenants.models import Tenant, User, PlantLookup

# Delete in FK-safe order
print(f"  Deleting AuditLog:          {AuditLog.objects.all().delete()[0]} rows")
print(f"  Deleting NormalizedActivity:{NormalizedActivity.objects.all().delete()[0]} rows")
print(f"  Deleting RawRow:            {RawRow.objects.all().delete()[0]} rows")
print(f"  Deleting IngestionRun:      {IngestionRun.objects.all().delete()[0]} rows")
print(f"  Deleting PlantLookup:       {PlantLookup.objects.all().delete()[0]} rows")
print(f"  Deleting EmissionFactor:    {EmissionFactor.objects.all().delete()[0]} rows")
print(f"  Deleting Users (all):       {User.objects.all().delete()[0]} rows")
print(f"  Deleting Tenants:           {Tenant.objects.all().delete()[0]} rows")
print("  All data wiped.")
PYEOF

if [ "$1" = "--flush-only" ]; then
  echo ""
  ok "Flush complete. Database is empty."
  exit 0
fi

# ── Step 2: Re-seed ───────────────────────────────────────
echo ""
info "Step 2: Running seed_dev..."
python3 manage.py seed_dev

# ── Step 3: Verify counts ─────────────────────────────────
echo ""
info "Step 3: Verifying database state..."

python3 manage.py shell << 'PYEOF'
from apps.audit.models import AuditLog
from apps.normalization.models import NormalizedActivity, EmissionFactor
from apps.ingestion.models import IngestionRun, RawRow
from apps.tenants.models import Tenant, User, PlantLookup

checks = [
    ("Tenants",           Tenant.objects.count(),              1),
    ("Users",             User.objects.count(),                2),
    ("EmissionFactors",   EmissionFactor.objects.count(),      9),
    ("PlantLookups",      PlantLookup.objects.count(),         4),
    ("IngestionRuns",     IngestionRun.objects.count(),        3),
    ("RawRows",           RawRow.objects.count(),             15),
    ("NormalizedActivity",NormalizedActivity.objects.count(), 15),
    ("AuditLogs",         AuditLog.objects.count(),           ">=15"),
]

all_ok = True
for name, got, expected in checks:
    if expected == ">=15":
        ok_flag = got >= 15
    else:
        ok_flag = got == expected
    status = "✓" if ok_flag else "✗"
    exp_str = str(expected)
    print(f"  {status} {name:<22} got={got:<4} expected={exp_str}")
    if not ok_flag:
        all_ok = False

print("")
if all_ok:
    print("  All checks passed.")
else:
    print("  Some checks failed — re-run seed_dev manually.")

# Scope breakdown
s1 = NormalizedActivity.objects.filter(scope='1').count()
s2 = NormalizedActivity.objects.filter(scope='2').count()
s3 = NormalizedActivity.objects.filter(scope='3').count()
print(f"\n  Scope breakdown: S1={s1}  S2={s2}  S3={s3}")

# Flagged rows
flagged = NormalizedActivity.objects.filter(is_flagged_suspicious=True).count()
print(f"  Flagged rows: {flagged}")

# Review status mix
from django.db.models import Count
statuses = NormalizedActivity.objects.values('review_status').annotate(n=Count('id'))
for s in statuses:
    print(f"  review_status={s['review_status']:<10}: {s['n']}")
PYEOF

# ── Step 4: Quick API smoke test (requires server running) ─
echo ""
info "Step 4: API smoke test (requires runserver on :8000)..."

BASE="http://localhost:8000"

# Login
RESPONSE=$(curl -s -X POST "$BASE/api/auth/login/" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"breathe123"}' 2>/dev/null)

TOKEN=$(echo $RESPONSE | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('access',''))" 2>/dev/null)

if [ -z "$TOKEN" ]; then
  echo -e "${YELLOW}  ⚠ Django server not running — skipping API checks${NC}"
  echo -e "${YELLOW}    Start with: python manage.py runserver${NC}"
else
  # Test each endpoint
  check_endpoint() {
    local desc="$1" url="$2" expected="$3"
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
      -H "Authorization: Bearer $TOKEN" "$BASE$url")
    if [ "$STATUS" = "$expected" ]; then
      echo -e "${GREEN}  ✓ $desc → HTTP $STATUS${NC}"
    else
      echo -e "${RED}  ✗ $desc → HTTP $STATUS (expected $expected)${NC}"
    fi
  }

  check_endpoint_unauth() {
    local desc="$1" url="$2" expected="$3"
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE$url")
    if [ "$STATUS" = "$expected" ]; then
      echo -e "${GREEN}  ✓ $desc → HTTP $STATUS${NC}"
    else
      echo -e "${RED}  ✗ $desc → HTTP $STATUS (expected $expected)${NC}"
    fi
  }

  check_endpoint "GET /api/ingestion/runs/"          "/api/ingestion/runs/"            "200"
  check_endpoint "GET /api/review/activities/"       "/api/review/activities/"         "200"
  check_endpoint "GET /api/review/activities/?scope=1" "/api/review/activities/?scope=1" "200"
  check_endpoint "GET /api/review/summary/"          "/api/review/summary/"            "200"
  check_endpoint "GET /api/audit/logs/"              "/api/audit/logs/"                "200"
  check_endpoint_unauth "Unauthenticated → 401"      "/api/review/activities/"         "401"
fi

echo ""
echo "════════════════════════════════════════════"
echo "  Done. Credentials: admin / breathe123"
echo "════════════════════════════════════════════"
echo ""
