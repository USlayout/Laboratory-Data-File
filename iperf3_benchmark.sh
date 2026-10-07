#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"


LABEL="${1:-}"

init_run "iperf3" "${LABEL}"

require_command iperf3
require_command nc


log "===== iperf3 benchmark started ====="


collect_system_info
write_metadata


OUT_DIR="${RUN_DIR}/network"

mkdir -p "${OUT_DIR}"


# =============================================================================
# 接続確認
# =============================================================================

log "Checking iperf3 server..."

if ! nc -z -w 3 "${IPERF_SERVER_IP}" 5201 2>/dev/null; then

    log "WARNING:"
    log "Cannot connect to ${IPERF_SERVER_IP}:5201"

    echo \
        "Skipped because iperf3 server ${IPERF_SERVER_IP}:5201 could not be reached." \
        > "${OUT_DIR}/SKIPPED.txt"

    upload_to_github

    exit 0
fi


# =============================================================================
# TCP
# =============================================================================

log "Running TCP benchmark..."


iperf3 \
    -c "${IPERF_SERVER_IP}" \
    -t "${IPERF_DURATION}" \
    -J \
    > "${OUT_DIR}/iperf3_tcp.json"


# =============================================================================
# UDP
# =============================================================================

log "Running UDP benchmark..."


iperf3 \
    -c "${IPERF_SERVER_IP}" \
    -u \
    -b 1G \
    -t "${IPERF_DURATION}" \
    -J \
    > "${OUT_DIR}/iperf3_udp.json"


log "iperf3 benchmark complete"


upload_to_github


log "===== iperf3 benchmark complete ====="
log "Result: ${RUN_DIR}"