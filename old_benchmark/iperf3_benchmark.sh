#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

LABEL="${1:-}"

require_command iperf3
require_command nc
require_command git

# iperf3専用の実験ディレクトリを作成
init_experiment "iperf3${LABEL:+-${LABEL}}"

OUT_DIR="${RUN_DIR}/iperf3"
mkdir -p "${OUT_DIR}"

collect_system_info
write_metadata


# =============================================================================
# サーバー接続確認
# =============================================================================

log "Checking iperf3 server ${IPERF_SERVER_IP}:5201..."

if ! nc -z -w 3 "${IPERF_SERVER_IP}" 5201 2>/dev/null; then

    log "ERROR: Cannot connect to iperf3 server."
    log "${IPERF_SERVER_IP}:5201"

    echo "iperf3 server unreachable: ${IPERF_SERVER_IP}:5201" \
        > "${OUT_DIR}/FAILED.txt"

    exit 1
fi


# =============================================================================
# TCP
# =============================================================================

log "Running iperf3 TCP..."

iperf3 \
    -c "${IPERF_SERVER_IP}" \
    -t "${IPERF_DURATION}" \
    -J \
    > "${OUT_DIR}/iperf3_tcp.json"

log "TCP complete"


# =============================================================================
# UDP
# =============================================================================

log "Running iperf3 UDP..."

iperf3 \
    -c "${IPERF_SERVER_IP}" \
    -u \
    -b 1G \
    -t "${IPERF_DURATION}" \
    -J \
    > "${OUT_DIR}/iperf3_udp.json"

log "UDP complete"


# =============================================================================
# GitHub
# =============================================================================

upload_to_github


log "=================================================="
log " iperf3 benchmark complete"
log "=================================================="

log "Result:"
log "  ${RUN_DIR}"