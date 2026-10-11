#!/usr/bin/env bash
# Install the approved owned-page SEO schedule through the parent lake-first
# runner. This script never creates a nested virtual environment.
#
# Usage:
#   SOLO_EMPIRE_DATA_LAKE_URI=/absolute/path/to/lake bash setup_seo_cron.sh plan
#   SOLO_EMPIRE_DATA_LAKE_URI=/absolute/path/to/lake bash setup_seo_cron.sh install
#   bash setup_seo_cron.sh remove
#   bash setup_seo_cron.sh status

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
RUNNER="${ROOT_DIR}/infra/scripts/data_lake/run_seo_capture.py"
PYTHON_WRAPPER="${ROOT_DIR}/infra/scripts/setup/run-python3.sh"
LOCK_PATH="${ROOT_DIR}/data/seo-feeds.lock"
LOG_FILE="${ROOT_DIR}/data/logs/seo-feeds-cron.log"
CRON_TAG="# book-seo-data-feeds"

shell_quote() {
    printf '%q' "$1"
}

require_control_plane() {
    if [ ! -f "${RUNNER}" ]; then
        echo "Cannot find SEO capture runner: ${RUNNER}" >&2
        return 1
    fi
    if [ ! -f "${PYTHON_WRAPPER}" ]; then
        echo "Cannot find Solo Empire Python wrapper: ${PYTHON_WRAPPER}" >&2
        return 1
    fi
}

require_python_runtime() {
    require_control_plane
    if ! "${PYTHON_WRAPPER}" -c "import duckdb, pyarrow, httpx, bs4" >/dev/null 2>&1; then
        echo "Refusing SEO cron install: parent Python runtime is missing data-lake/httpx/bs4 dependencies" >&2
        return 1
    fi
}

require_lake_for_install() {
    local lake_uri="${SOLO_EMPIRE_DATA_LAKE_URI:-}"
    if [ -z "${lake_uri}" ]; then
        echo "Refusing SEO cron install: set SOLO_EMPIRE_DATA_LAKE_URI to a writable shared lake" >&2
        return 1
    fi
    case "${lake_uri}" in
        *://*) return 0 ;;
    esac
    if [ ! -d "${lake_uri}" ] || [ ! -w "${lake_uri}" ]; then
        echo "Refusing SEO cron install: lake path is missing or not writable: ${lake_uri}" >&2
        return 1
    fi
}

cron_entry() {
    local lake_uri="$1"
    require_control_plane
    printf '%s cd %s && %s %s --lake-uri %s --lock-path %s --log-dir %s --attempts 2 --timeout-seconds 180 --json >> %s 2>&1 %s\n' \
        "30 8 * * *" \
        "$(shell_quote "${ROOT_DIR}")" \
        "$(shell_quote "${PYTHON_WRAPPER}")" \
        "$(shell_quote "${RUNNER}")" \
        "$(shell_quote "${lake_uri}")" \
        "$(shell_quote "${LOCK_PATH}")" \
        "$(shell_quote "${ROOT_DIR}/data/logs/seo-capture")" \
        "$(shell_quote "${LOG_FILE}")" \
        "${CRON_TAG}"
}

remove_cron_silent() {
    local current_file
    current_file="$(mktemp)"
    trap 'rm -f "${current_file}"' RETURN
    crontab -l 2>/dev/null >"${current_file}" || true
    sed -i "\|${CRON_TAG}|d" "${current_file}"
    if [ -s "${current_file}" ]; then
        crontab "${current_file}"
    else
        crontab -r 2>/dev/null || true
    fi
    rm -f "${current_file}"
    trap - RETURN
}

install_cron() {
    require_python_runtime
    require_lake_for_install
    mkdir -p "${ROOT_DIR}/data/logs/seo-capture" "${ROOT_DIR}/data/logs"
    remove_cron_silent
    entry="$(cron_entry "${SOLO_EMPIRE_DATA_LAKE_URI}")"
    {
        crontab -l 2>/dev/null || true
        # Command substitution strips trailing newlines; add the crontab
        # terminator explicitly so Vixie cron accepts the generated file.
        printf '%s\n' "${entry}"
    } | crontab -
    echo "SEO cron installed for the bounded owned-page public check"
    echo "Lake: ${SOLO_EMPIRE_DATA_LAKE_URI}"
    echo "Log: ${LOG_FILE}"
}

show_plan() {
    echo "SEO scheduler plan (not installed)"
    echo "Schedule: daily 08:30"
    echo "Query: python developer thailand"
    echo "Domains: bookchaowalit.com,chaowalit.com"
    echo "Lake: ${SOLO_EMPIRE_DATA_LAKE_URI:-SET_SOLO_EMPIRE_DATA_LAKE_URI}"
    echo "Command:"
    cron_entry "${SOLO_EMPIRE_DATA_LAKE_URI:-SET_SOLO_EMPIRE_DATA_LAKE_URI}"
}

remove_cron() {
    remove_cron_silent
    echo "SEO cron removed"
}

show_status() {
    if crontab -l 2>/dev/null | grep -qF "${CRON_TAG}"; then
        crontab -l | grep -F "${CRON_TAG}"
        echo "Status: ACTIVE"
    else
        echo "Status: NOT INSTALLED"
    fi
}

case "${1:-plan}" in
    plan) show_plan ;;
    install) install_cron ;;
    remove) remove_cron ;;
    status) show_status ;;
    *)
        echo "Usage: $0 {plan|install|remove|status}"
        exit 1
        ;;
esac
