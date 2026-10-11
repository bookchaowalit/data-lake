#!/usr/bin/env bash
# Install the approved public market product schedules through the parent
# lake-first runner. This script never creates a nested virtual environment.
#
# Usage:
#   SOLO_EMPIRE_DATA_LAKE_URI=/absolute/path/to/lake bash setup_market_cron.sh plan
#   SOLO_EMPIRE_DATA_LAKE_URI=/absolute/path/to/lake bash setup_market_cron.sh install
#   bash setup_market_cron.sh remove
#   bash setup_market_cron.sh status

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
RUNNER="${ROOT_DIR}/infra/scripts/data_lake/run_market_capture.py"
PYTHON_WRAPPER="${ROOT_DIR}/infra/scripts/setup/run-python3.sh"
LOCK_PATH="${ROOT_DIR}/data/market-feeds.lock"
LOG_FILE="${ROOT_DIR}/data/logs/market-feeds-cron.log"

CRON_TAGS=(
    "# book-crypto-data-feeds"
    "# book-stock-data-feeds"
    "# book-fx-data-feeds"
    "# book-defi-data-feeds"
)

shell_quote() {
    printf '%q' "$1"
}

require_control_plane() {
    if [ ! -f "${RUNNER}" ]; then
        echo "Cannot find market capture runner: ${RUNNER}" >&2
        return 1
    fi
    if [ ! -f "${PYTHON_WRAPPER}" ]; then
        echo "Cannot find Solo Empire Python wrapper: ${PYTHON_WRAPPER}" >&2
        return 1
    fi
}

require_python_runtime() {
    require_control_plane
    if ! "${PYTHON_WRAPPER}" -c "import duckdb, pyarrow, httpx" >/dev/null 2>&1; then
        echo "Refusing market cron install: parent Python runtime is missing data-lake/httpx dependencies" >&2
        return 1
    fi
}

require_lake_for_install() {
    local lake_uri="${SOLO_EMPIRE_DATA_LAKE_URI:-}"
    if [ -z "${lake_uri}" ]; then
        echo "Refusing market cron install: set SOLO_EMPIRE_DATA_LAKE_URI to a writable shared lake" >&2
        return 1
    fi
    case "${lake_uri}" in
        *://*) return 0 ;;
    esac
    if [ ! -d "${lake_uri}" ] || [ ! -w "${lake_uri}" ]; then
        echo "Refusing market cron install: lake path is missing or not writable: ${lake_uri}" >&2
        return 1
    fi
}

cron_entry() {
    local schedule="$1"
    local product="$2"
    local tag="$3"
    local lake_uri="$4"
    require_control_plane
    printf '%s cd %s && %s %s --product %s --lake-uri %s --lock-path %s --log-dir %s --attempts 2 --timeout-seconds 180 --json >> %s 2>&1 %s\n' \
        "${schedule}" \
        "$(shell_quote "${ROOT_DIR}")" \
        "$(shell_quote "${PYTHON_WRAPPER}")" \
        "$(shell_quote "${RUNNER}")" \
        "$(shell_quote "${product}")" \
        "$(shell_quote "${lake_uri}")" \
        "$(shell_quote "${LOCK_PATH}")" \
        "$(shell_quote "${ROOT_DIR}/data/logs/market-capture")" \
        "$(shell_quote "${LOG_FILE}")" \
        "${tag}"
}

all_entries() {
    local lake_uri="${SOLO_EMPIRE_DATA_LAKE_URI:-SET_SOLO_EMPIRE_DATA_LAKE_URI}"
    cron_entry "0 */4 * * *" crypto "# book-crypto-data-feeds" "${lake_uri}"
    cron_entry "0 8 * * *" stocks "# book-stock-data-feeds" "${lake_uri}"
    cron_entry "0 */6 * * *" fx "# book-fx-data-feeds" "${lake_uri}"
    cron_entry "0 7 * * *" defi "# book-defi-data-feeds" "${lake_uri}"
}

remove_cron_silent() {
    local current_file
    current_file="$(mktemp)"
    trap 'rm -f "${current_file}"' RETURN
    crontab -l 2>/dev/null >"${current_file}" || true
    for tag in "${CRON_TAGS[@]}"; do
        sed -i "\\|${tag}|d" "${current_file}"
    done
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
    mkdir -p "${ROOT_DIR}/data/logs/market-capture" "${ROOT_DIR}/data/logs"
    remove_cron_silent
    entries="$(all_entries)"
    {
        crontab -l 2>/dev/null || true
        # Command substitution strips trailing newlines; add the crontab
        # terminator explicitly so Vixie cron accepts the generated file.
        printf '%s\n' "${entries}"
    } | crontab -
    echo "Market cron installed for crypto, stocks, fx, and defi"
    echo "Lake: ${SOLO_EMPIRE_DATA_LAKE_URI}"
    echo "Log: ${LOG_FILE}"
}

show_plan() {
    echo "Market scheduler plan (not installed)"
    echo "Schedules: crypto=every 4h, fx=every 6h, stocks=08:00 daily, defi=07:00 daily"
    echo "Lake: ${SOLO_EMPIRE_DATA_LAKE_URI:-SET_SOLO_EMPIRE_DATA_LAKE_URI}"
    echo "Commands:"
    all_entries
}

remove_cron() {
    remove_cron_silent
    echo "Market cron removed"
}

show_status() {
    local active=0
    local current
    current="$(crontab -l 2>/dev/null || true)"
    for tag in "${CRON_TAGS[@]}"; do
        if printf '%s\n' "${current}" | grep -Fq "${tag}"; then
            printf '%s\n' "${current}" | grep -F "${tag}"
            active=$((active + 1))
        else
            echo "Missing: ${tag}"
        fi
    done
    if [ "${active}" -eq "${#CRON_TAGS[@]}" ]; then
        echo "Status: ACTIVE"
    elif [ "${active}" -gt 0 ]; then
        echo "Status: PARTIAL (${active}/${#CRON_TAGS[@]})"
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
