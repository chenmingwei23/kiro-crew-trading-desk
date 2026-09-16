#!/usr/bin/env bash
# Cleanup for the trading-desk app.
#
# Removes ONLY state this app created:
#   <gateway home>/workspace/trading-desk/   (state.json)
#   <app dir>/data/                          (config.json)
#
# It NEVER touches the desk data root ($DESK_ROOT). That is the
# user's own git repo holding every research artifact, position and config file;
# the app only ever reads it. Nothing here is recoverable by re-running the
# script, but nothing here is worth keeping either -- the heal cron and
# install.sh both recreate state.json and data/config.json from scratch.
#
# Env note: the gateway runs this with cwd = the installed app directory and a
# MINIMAL env allowlist (no KIROCREW_HOME), so the gateway home is derived from
# cwd -- <home>/apps/trading-desk -> <home>. A human running it from elsewhere
# gets the env/probe fallback instead.
set -euo pipefail

APP_NAME="trading-desk"
DESK_ROOT="${DESK_ROOT:-$HOME/trading-desk}"

# `set -u` is on (the gateway prepends `set -euo pipefail`), and BASH_SOURCE is
# unset when the body is sourced or piped rather than executed as a file.
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || pwd)"

resolve_home() {
  # cwd is the installed app dir when the gateway invokes this.
  local cwd_home
  cwd_home="$(pwd)"
  if [ "$(basename "${cwd_home}")" = "${APP_NAME}" ] \
     && [ "$(basename "$(dirname "${cwd_home}")")" = "apps" ]; then
    printf '%s\n' "$(dirname "$(dirname "${cwd_home}")")"
    return
  fi
  # Same shape, reached via the script's own location (hand-run from the app dir).
  local app_dir
  app_dir="$(dirname "${here}")"
  if [ "$(basename "${app_dir}")" = "${APP_NAME}" ] \
     && [ "$(basename "$(dirname "${app_dir}")")" = "apps" ]; then
    printf '%s\n' "$(dirname "$(dirname "${app_dir}")")"
    return
  fi
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
DATA_DIR="${CREW_HOME}/apps/${APP_NAME}/data"

echo "trading-desk: gateway home ${CREW_HOME}"

# Refuse to act on a path that is not the app's own state, whatever the
# resolution produced. A bad home must yield "nothing to do", never a delete
# somewhere else.
remove_owned() {
  local target="$1" label="$2"
  case "${target}" in
    */workspace/"${APP_NAME}"|*/apps/"${APP_NAME}"/data) : ;;
    *)
      echo "trading-desk: refusing to remove unexpected path ${target}" >&2
      return 0
      ;;
  esac
  if [ "${target}" = "${DESK_ROOT}" ] || [ "${target#"${DESK_ROOT}/"}" != "${target}" ]; then
    echo "trading-desk: refusing to remove ${target} -- inside the desk data root" >&2
    return 0
  fi
  if [ -d "${target}" ]; then
    rm -rf "${target}"
    echo "trading-desk: removed ${label} ${target}"
  else
    echo "trading-desk: ${label} already absent"
  fi
}

remove_owned "${STATE_DIR}" "state dir"
remove_owned "${DATA_DIR}" "data dir"

echo "trading-desk: desk data at ${DESK_ROOT} left untouched (never owned by this app)"
echo "trading-desk: cleanup complete"
