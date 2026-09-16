#!/usr/bin/env bash
# Optional accelerator for the trading-desk app.
#
# It is NOT required. The trading-desk-heal cron does exactly the same work and
# runs within 900s of install, so the app comes up either way. Run this by hand
# (or let setup.onInstall fire it) only to skip that wait.
#
# Every step is idempotent: an existing file is left exactly as it is.
#
# Env note: the gateway runs lifecycle scripts with a MINIMAL env allowlist
# (HOME/USER/PATH/... only) -- KIROCREW_HOME is NOT passed through. So the home
# is honored from the env when a human runs this from a shell, and probed from
# $HOME otherwise.
set -euo pipefail

DESK_ROOT="${DESK_ROOT:-$HOME/trading-desk}"
APP_NAME="trading-desk"

resolve_home() {
  if [ -n "${KIROCREW_HOME:-}" ]; then
    printf '%s\n' "${KIROCREW_HOME}"
  elif [ -d "${HOME:-}/.kirocrew" ]; then
    printf '%s\n' "${HOME}/.kirocrew"
  else
    printf '%s\n' "${HOME:-}/.kiro/crew"
  fi
}

CREW_HOME="$(resolve_home)"
STATE_DIR="${CREW_HOME}/workspace/${APP_NAME}"
STATE_FILE="${STATE_DIR}/state.json"
APP_DIR="${CREW_HOME}/apps/${APP_NAME}"
DATA_DIR="${APP_DIR}/data"
CONFIG_FILE="${DATA_DIR}/config.json"

echo "trading-desk: gateway home ${CREW_HOME}"

# (1) State dir the UI polls.
mkdir -p "${STATE_DIR}"
if [ -f "${STATE_FILE}" ]; then
  echo "trading-desk: state.json already present, left untouched"
else
  echo '{}' > "${STATE_FILE}"
  echo "trading-desk: created ${STATE_FILE}"
fi

# (2) data/config.json -- how the UI learns deskRoot, appRoot and statePath.
#     appRoot is how the UI locates fixtures/*.json (ARCHITECTURE.md §1, cycle3);
#     data/ is gitignored: it is per-machine install state, never repo content.
mkdir -p "${DATA_DIR}"
if [ -f "${CONFIG_FILE}" ]; then
  echo "trading-desk: data/config.json already present, left untouched"
else
  printf '{\n  "deskRoot": "%s",\n  "appRoot": "%s",\n  "statePath": "%s"\n}\n' \
    "${DESK_ROOT}" "${APP_DIR}" "${STATE_FILE}" > "${CONFIG_FILE}"
  echo "trading-desk: created ${CONFIG_FILE}"
fi

# (3) Run-events directory on the desk root. The backend derives /run from
#     artifact mtimes when runs/<date>/events.jsonl is absent, so an empty
#     directory here is the correct steady state until crews land the writer.
if [ -d "${DESK_ROOT}" ]; then
  mkdir -p "${DESK_ROOT}/runs"
  echo "trading-desk: ensured ${DESK_ROOT}/runs"
else
  echo "trading-desk: WARNING desk root ${DESK_ROOT} not found -- skipped runs/." >&2
  echo "trading-desk: the app installs fine; fix deskRoot in ${CONFIG_FILE}." >&2
fi

echo "trading-desk: setup complete"
