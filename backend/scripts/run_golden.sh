#!/bin/bash
# Golden run (ship-readiness plan E5), against the TEST tenant only. Three modes:
#
#   (default) full   ~3h15m  static, preflight, api, ui, unit, integrity, live
#   --smoke          ~1h40m  static, preflight, api (money suites 9/10/11), ui (money journey),
#                            pure unit, integrity, live
#   --quick          minutes static + pure unit suites (no journey writes, no servers needed)
#
# Phases:
#   static     ruff (backend) + tsc --noEmit, npm run test:audit, vitest (frontend)
#   preflight  servers up, live `logismart` counts BEFORE
#   api        golden journeys, ONE pytest session in a fixed order (the session fixture resets
#              logismart-test once; later suites read state written by earlier ones)
#   ui         Playwright click-through (frontend :3000, dedicated fake-env API :8100) in the shared
#              Chrome on CDP :9224, or a self-launched headless Chrome when :9224 is down / UI_HEADLESS=1
#   unit       money / property / tenant-filter / lifecycle / seed-core suites (pure only in
#              --quick and --smoke)
#   integrity  B11/C6 integrity audit of logismart-test (read-only)
#   live       live `logismart` counts AFTER == BEFORE
# Fail fast: the first failing phase stops the run (later phases are reported as NOT RUN), the
# per-suite pass/fail table and the live-count check are always printed. Exit 0 only when every
# phase of the chosen mode is green.
#
# Usage (from naviera/backend):
#   bash scripts/run_golden.sh [--quick|--smoke] > ../llm_resources/.agents/golden_runs/run_<N>.log 2>&1
# Env: GOLDEN_TENANT_SLUG (only logismart-test is allowed), GOLDEN_LIVE_SLUG (default logismart),
#      GOLDEN_SKIP_UI=1 to skip the ui phase (reported as SKIPPED, the run is then not "green"),
#      GOLDEN_ARTIFACT_DIR (default ../llm_resources/.agents/golden_runs/artifacts/<timestamp>).
set -uo pipefail

MODE="full"
case "${1:-}" in
  "") ;;
  --quick) MODE="quick" ;;
  --smoke) MODE="smoke" ;;
  *) echo "usage: $0 [--quick|--smoke]"; exit 2 ;;
esac

cd "$(dirname "$0")/.."
export PYTHON_KEYRING_BACKEND="${PYTHON_KEYRING_BACKEND:-keyring.backends.null.Keyring}"
export GOLDEN_TENANT_SLUG="${GOLDEN_TENANT_SLUG:-logismart-test}"
# Every in-process suite prices Delhivery on the deterministic fake for the test tenant and binds
# no slug live, overriding backend/.env (env vars beat .env in pydantic Settings). The UI phase
# starts its own dedicated uvicorn on UI_API_PORT (default 8100) with these same env vars, so
# the shared :8000 server can keep logismart-test live.
export DELHIVERY_FAKE_TENANT_SLUGS="logismart-test"
export DELHIVERY_LIVE_TENANT_SLUGS=""
UI_API_PORT="${UI_API_PORT:-8100}"
UI_UVICORN_PID=""

stop_ui_uvicorn() {
  if [ -n "$UI_UVICORN_PID" ] && kill -0 "$UI_UVICORN_PID" 2> /dev/null; then
    kill "$UI_UVICORN_PID" 2> /dev/null || true
    wait "$UI_UVICORN_PID" 2> /dev/null || true
  fi
  UI_UVICORN_PID=""
}
trap stop_ui_uvicorn EXIT INT TERM
LIVE_SLUG="${GOLDEN_LIVE_SLUG:-logismart}"
POETRY="${POETRY:-$(command -v poetry || echo "$HOME/.local/bin/poetry")}"
FRONTEND_DIR="../frontend"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARTIFACTS="${GOLDEN_ARTIFACT_DIR:-../llm_resources/.agents/golden_runs/artifacts/$STAMP}"
mkdir -p "$ARTIFACTS"

# Node may only be installed through nvm (not on the non-interactive PATH).
if ! command -v npx > /dev/null 2>&1; then
  NVM_BIN="$(ls -d "$HOME"/.nvm/versions/node/*/bin 2> /dev/null | sort -V | tail -1)"
  [ -n "$NVM_BIN" ] && export PATH="$NVM_BIN:$PATH"
fi

FULL_API_SUITES=(
  scripts/tests/golden_journeys/test_suite_1_2_auth_settings_rates.py
  scripts/tests/golden_journeys/test_suite_3_4_b2c_booking_and_pur.py
  scripts/tests/golden_journeys/test_suite_5_6_ops_ndr_and_reverse_qc.py
  scripts/tests/golden_journeys/test_suite_7_8_b2b_finance_support_and_audit.py
  scripts/tests/golden_journeys/test_suite_9_repricing.py
  scripts/tests/golden_journeys/test_suite_10_crosscut.py
  scripts/tests/golden_journeys/test_suite_11_lifecycle.py
  scripts/tests/golden_journeys/test_suite_13_notes_lite.py
)
SMOKE_API_SUITES=(  # the money suites: independent of the state files of suites 1-8
  scripts/tests/golden_journeys/test_suite_9_repricing.py
  scripts/tests/golden_journeys/test_suite_10_crosscut.py
  scripts/tests/golden_journeys/test_suite_11_lifecycle.py
)
FULL_UI_SUITES=(scripts/tests/ui_golden)
SMOKE_UI_SUITES=(scripts/tests/ui_golden/test_ui_helpers.py scripts/tests/ui_golden/test_ui_money.py)
PURE_UNIT_SUITES=(  # no app, no DB connection (conftest skips the DB for pure modules): seconds
  scripts/tests/test_money.py
  scripts/tests/test_response_audit.py
  scripts/tests/test_idempotency_default.py
  scripts/tests/test_pricing_engine.py
  scripts/tests/test_pricing_quotes_unit.py
  scripts/tests/test_delhivery_binding_unit.py
  scripts/tests/test_prime_pricing_unit.py
  scripts/tests/test_booking_pricing_unit.py
  scripts/tests/test_label_generator.py
  scripts/tests/test_gst_documents_unit.py
  scripts/tests/test_signup_consent.py
  scripts/tests/test_support_and_dashboard_ist.py
  scripts/tests/test_repricing_unit.py
  scripts/tests/test_repricing_redesign_unit.py
  scripts/tests/test_repricing_api_schemas.py
  scripts/tests/test_repository_tenant_filter.py
  scripts/tests/test_shipment_lifecycle.py
  scripts/tests/test_tenant_data_core.py
  scripts/tests/test_b2c_money_cod_settle_unit.py
  scripts/tests/test_b2c_money_support_claims.py
  scripts/tests/test_wallet_ledger_scope.py
  scripts/tests/test_wallet_remittance_guards_unit.py
  scripts/tests/test_weight_disputes_unit.py
  scripts/tests/test_staff_finance_views_unit.py
  scripts/tests/test_delhivery_b2b_unit.py
  scripts/tests/test_delhivery_http_contract_unit.py
  scripts/tests/test_prime_lanes_api.py
  scripts/tests/test_public_tracking_unit.py
  scripts/tests/test_pickup_read_ops_fields.py
  scripts/tests/test_ndr_stage_rules.py
  scripts/tests/test_exceptions_consignee_unit.py
  scripts/tests/test_platform_guards_unit.py
  scripts/tests/test_settings_history_rules_unit.py
  scripts/tests/test_team_admin_edits_unit.py
  scripts/tests/test_wp10_batch3_unit.py
  scripts/tests/test_temporal_hooks_worker.py  # in-memory SQLite, not the shared database
  scripts/tests/test_supabase_lockdown_migrations.py
)
FULL_UNIT_SUITES=(  # every pure suite plus the DB-backed ones (savepoint session on logismart-test)
  "${PURE_UNIT_SUITES[@]}"
  scripts/tests/test_money_w2a.py
  scripts/tests/test_money_w2b.py
  scripts/tests/test_money_guards.py
  scripts/tests/test_money_properties.py
  scripts/tests/test_exhaustive_api_and_forms_e2e.py
  scripts/tests/test_appointments.py
  scripts/tests/test_production_readiness_guards.py
  scripts/tests/test_security_w1.py
  scripts/tests/test_user_onboarding_self_service.py
  scripts/tests/test_b2b_onboarding_flow.py
  scripts/tests/test_dashboard_summary.py
  scripts/tests/test_exceptions_flow.py
  scripts/tests/test_manifest_flow.py
  scripts/tests/test_pretest_enhancements_g1_g6.py
  scripts/tests/test_reverse_bookings.py
  scripts/tests/test_settings_history.py
  scripts/tests/test_shipment_hardening.py
  scripts/tests/test_wallet_and_otp_e2e.py
)
PYTEST_FLAGS=(-p no:cacheprovider -p no:randomly -o console_output_style=classic -rfEs --tb=short)

case "$MODE" in
  full)  PHASES=(static preflight api ui unit integrity live)
         API_SUITES=("${FULL_API_SUITES[@]}"); UI_SUITES=("${FULL_UI_SUITES[@]}")
         UNIT_SUITES=("${FULL_UNIT_SUITES[@]}") ;;
  smoke) PHASES=(static preflight api ui unit integrity live)
         API_SUITES=("${SMOKE_API_SUITES[@]}"); UI_SUITES=("${SMOKE_UI_SUITES[@]}")
         UNIT_SUITES=("${PURE_UNIT_SUITES[@]}") ;;
  quick) PHASES=(static unit)
         API_SUITES=(); UI_SUITES=(); UNIT_SUITES=("${PURE_UNIT_SUITES[@]}") ;;
esac

declare -A PHASE_STATUS=()
FAILED_PHASE=""

banner() { printf '\n==================== %s ====================\n' "$*"; }

has_phase() { local p; for p in "${PHASES[@]}"; do [ "$p" = "$1" ] && return 0; done; return 1; }

run_phase() {  # run_phase <name> <command...>: records PASS/FAIL, skips once a phase failed
  local name="$1"; shift
  has_phase "$name" || return 0
  if [ -n "$FAILED_PHASE" ]; then PHASE_STATUS[$name]="NOT RUN"; return; fi
  banner "phase $name ($(date -u +%H:%M:%SZ))"
  if "$@"; then PHASE_STATUS[$name]="PASS"; else PHASE_STATUS[$name]="FAIL"; FAILED_PHASE="$name"; fi
}

check_url() {  # check_url <label> <url>
  if curl -s -o /dev/null --max-time 60 "$2"; then echo "  $1 up ($2)"; else echo "  $1 DOWN ($2)"; return 1; fi
}

step() {  # step <label> <command...>: one static check, prints a one-line verdict
  local label="$1"; shift
  if "$@" > "$ARTIFACTS/static_${label}.log" 2>&1; then
    echo "  $label PASS"
  else
    echo "  $label FAIL (log: $ARTIFACTS/static_${label}.log)"; tail -20 "$ARTIFACTS/static_${label}.log"; return 1
  fi
}

static_checks() {
  local rc=0
  step ruff "$POETRY" run ruff check . || rc=1
  step tsc bash -c "cd '$FRONTEND_DIR' && npx tsc --noEmit" || rc=1
  step eslint bash -c "cd '$FRONTEND_DIR' && npx eslint --max-warnings=0 ." || rc=1
  step test_audit bash -c "cd '$FRONTEND_DIR' && npm run test:audit" || rc=1
  step vitest bash -c "cd '$FRONTEND_DIR' && npx vitest run" || rc=1
  return $rc
}

preflight() {
  [ "$GOLDEN_TENANT_SLUG" = "logismart-test" ] || { echo "refusing GOLDEN_TENANT_SLUG=$GOLDEN_TENANT_SLUG"; return 1; }
  check_url "API" "http://127.0.0.1:8000/docs" || return 1
  if [ "${GOLDEN_SKIP_UI:-0}" != "1" ]; then
    check_url "frontend" "http://127.0.0.1:3000/" || return 1
    check_url "chrome CDP" "http://127.0.0.1:9224/json/version" ||
      echo "  (no Chrome on :9224: the UI phase launches its own headless Chrome)"
  fi
  echo "  (logismart-test is reset + re-seeded by the golden session fixture; a missing auth"
  echo "   identity fails that reset: run the seed with --execute + GOLDEN_TEST_PASSWORD once)"
  "$POETRY" run python -m scripts.golden_checks live-counts --tenant "$LIVE_SLUG" --out "$ARTIFACTS/live_before.json"
}

run_pytest() {  # run_pytest <junit name> <paths...>
  local junit="$ARTIFACTS/$1.xml"; shift
  "$POETRY" run pytest "${PYTEST_FLAGS[@]}" --junitxml="$junit" "$@"
}

run_ui() {  # UI journeys must run against a dedicated fake-env uvicorn AND none may skip
  local ui_api_url="http://127.0.0.1:$UI_API_PORT"
  local ui_log="$ARTIFACTS/ui_uvicorn.log"
  echo "  starting UI fake-env uvicorn on $ui_api_url (log: $ui_log)"
  DELHIVERY_FAKE_TENANT_SLUGS="logismart-test" DELHIVERY_LIVE_TENANT_SLUGS="" \
    "$POETRY" run uvicorn app.main:app --host 127.0.0.1 --port "$UI_API_PORT" --no-access-log \
    > "$ui_log" 2>&1 &
  UI_UVICORN_PID=$!

  local ready=0
  for _ in $(seq 1 60); do
    if ! kill -0 "$UI_UVICORN_PID" 2> /dev/null; then
      echo "  UI uvicorn exited early (log: $ui_log)"; tail -20 "$ui_log"; stop_ui_uvicorn; return 1
    fi
    if curl -s -o /dev/null --max-time 2 "$ui_api_url/docs"; then
      ready=1; break
    fi
    sleep 0.5
  done
  if [ "$ready" -ne 1 ]; then
    echo "  UI uvicorn did not become ready on $ui_api_url (log: $ui_log)"; tail -20 "$ui_log"
    stop_ui_uvicorn; return 1
  fi
  echo "  UI fake-env API up ($ui_api_url)"

  local rc=0
  UI_API_URL="$ui_api_url" run_pytest ui "${UI_SUITES[@]}" -m ui &&
    "$POETRY" run python -m scripts.golden_checks junit-summary --fail-on-skip "$ARTIFACTS/ui.xml" > /dev/null ||
    { "$POETRY" run python -m scripts.golden_checks junit-summary --fail-on-skip "$ARTIFACTS/ui.xml"; rc=1; }
  stop_ui_uvicorn
  return $rc
}

live_after() {
  "$POETRY" run python -m scripts.golden_checks live-counts --tenant "$LIVE_SLUG" --out "$ARTIFACTS/live_after.json" &&
    "$POETRY" run python -m scripts.golden_checks compare-counts "$ARTIFACTS/live_before.json" "$ARTIFACTS/live_after.json"
}

banner "golden run mode=$MODE (artifacts: $ARTIFACTS)"
run_phase static static_checks
run_phase preflight preflight
run_phase api run_pytest api "${API_SUITES[@]}"
if has_phase ui && [ "${GOLDEN_SKIP_UI:-0}" = "1" ] && [ -z "$FAILED_PHASE" ]; then
  PHASE_STATUS[ui]="SKIPPED"
else
  run_phase ui run_ui
fi
run_phase unit run_pytest unit "${UNIT_SUITES[@]}"
run_phase integrity "$POETRY" run python -m scripts.golden_checks integrity --tenant "$GOLDEN_TENANT_SLUG"

# The live-count check always runs when a BEFORE snapshot exists, even after a failed phase.
if has_phase live; then
  banner "phase live ($(date -u +%H:%M:%SZ))"
  if [ -f "$ARTIFACTS/live_before.json" ] && live_after; then PHASE_STATUS[live]="PASS"; else PHASE_STATUS[live]="FAIL"; fi
fi

banner "SUMMARY mode=$MODE (artifacts: $ARTIFACTS)"
JUNIT_FILES=()
for name in api ui unit; do [ -f "$ARTIFACTS/$name.xml" ] && JUNIT_FILES+=("$ARTIFACTS/$name.xml"); done
[ ${#JUNIT_FILES[@]} -gt 0 ] && "$POETRY" run python -m scripts.golden_checks junit-summary "${JUNIT_FILES[@]}"
echo
EXIT=0
for phase in "${PHASES[@]}"; do
  status="${PHASE_STATUS[$phase]:-NOT RUN}"
  printf '  %-10s %s\n' "$phase" "$status"
  [ "$status" = "PASS" ] || EXIT=1
done
echo "GOLDEN RUN ($MODE): $([ $EXIT -eq 0 ] && echo GREEN || echo "RED (first failing phase: ${FAILED_PHASE:-live})")"
exit $EXIT
