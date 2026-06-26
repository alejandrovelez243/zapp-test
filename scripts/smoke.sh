#!/usr/bin/env bash
# scripts/smoke.sh — Compose smoke check for the Zapp platform.
#
# Proves: one-command boot (platform-scaffold-004), pgvector/pgvector:pg16 image
# (platform-scaffold-005), and auto-migration creating the vector extension
# (platform-scaffold-006).
#
# Usage (from repo root or any directory — script resolves the project root):
#   ./scripts/smoke.sh
#
# CI-usable: exits non-zero on any failure.
# Idempotent: the EXIT trap always tears down containers + volumes, even on failure.

set -euo pipefail

# ---------------------------------------------------------------------------
# Config — derived from docker-compose.yml (do not duplicate values manually)
# ---------------------------------------------------------------------------
POSTGRES_USER="zapp"
POSTGRES_DB="zapp"
HEALTH_URL="http://localhost:8000/health"
MAX_WAIT_SECONDS=120   # generous budget: image build can take a while on first run
POLL_INTERVAL=3

# ---------------------------------------------------------------------------
# Resolve the repo root (parent of this script's directory)
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "[smoke] repo root: ${REPO_ROOT}"
cd "${REPO_ROOT}"

# ---------------------------------------------------------------------------
# Teardown trap — always fires on EXIT (success or failure)
# ---------------------------------------------------------------------------
teardown() {
  local exit_code=$?
  echo ""
  echo "[smoke] --- teardown (exit code: ${exit_code}) ---"
  docker compose down -v --remove-orphans || true
  echo "[smoke] teardown complete."
  exit "${exit_code}"
}
trap teardown EXIT

# ---------------------------------------------------------------------------
# 0. Ensure nothing from a previous run is still up
# ---------------------------------------------------------------------------
echo "[smoke] pre-clean: ensuring no leftover zapp containers..."
docker compose down -v --remove-orphans 2>/dev/null || true

# ---------------------------------------------------------------------------
# 1. Boot db + backend (frontend dev server excluded — slower and not under test)
# ---------------------------------------------------------------------------
echo "[smoke] starting db + backend..."
docker compose up -d --build db backend

# ---------------------------------------------------------------------------
# 2. Poll /health until HTTP 200 / {"status":"ok"} or timeout
# ---------------------------------------------------------------------------
echo "[smoke] polling ${HEALTH_URL} (up to ${MAX_WAIT_SECONDS}s)..."
elapsed=0
health_body=""
until health_body="$(curl -fsS --max-time 5 "${HEALTH_URL}" 2>/dev/null)"; do
  if (( elapsed >= MAX_WAIT_SECONDS )); then
    echo ""
    echo "[smoke] ERROR: /health did not return 200 within ${MAX_WAIT_SECONDS}s."
    echo "[smoke] --- last 40 lines of backend logs ---"
    docker compose logs backend | tail -40
    echo "[smoke] ---"
    exit 1
  fi
  printf "."
  sleep "${POLL_INTERVAL}"
  (( elapsed += POLL_INTERVAL )) || true
done
echo ""
echo "[smoke] /health response: ${health_body}"

# Verify the body contains "ok"
if ! echo "${health_body}" | grep -q '"ok"'; then
  echo "[smoke] ERROR: /health responded but body does not contain \"ok\": ${health_body}"
  echo "[smoke] --- last 40 lines of backend logs ---"
  docker compose logs backend | tail -40
  exit 1
fi
echo "[smoke] /health OK (HTTP 200, body contains \"ok\")."

# ---------------------------------------------------------------------------
# 3. Assert the vector extension was created by the baseline migration
# ---------------------------------------------------------------------------
echo "[smoke] checking pg_extension for vector..."
vector_result="$(docker compose exec -T db \
  psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -t -A \
  -c "SELECT extname FROM pg_extension WHERE extname='vector';" 2>&1)"
echo "[smoke] pg_extension query result: '${vector_result}'"

if [[ "${vector_result}" != "vector" ]]; then
  echo "[smoke] ERROR: 'vector' extension not found in pg_extension. Migration may not have run."
  echo "[smoke] --- last 40 lines of backend logs ---"
  docker compose logs backend | tail -40
  exit 1
fi
echo "[smoke] vector extension confirmed present."

# ---------------------------------------------------------------------------
# Done — teardown fires via EXIT trap
# ---------------------------------------------------------------------------
echo ""
echo "[smoke] ALL CHECKS PASSED."
echo "  /health => ${health_body}"
echo "  pg_extension(vector) => present"
echo ""
echo "[smoke] exiting cleanly — teardown will fire now."
