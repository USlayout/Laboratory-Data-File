#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"


LABEL="${1:-}"

init_run "sysbench" "${LABEL}"

require_command sysbench


log "===== sysbench benchmark started ====="


collect_system_info
write_metadata


# =============================================================================
# CPU
# =============================================================================

log "Running CPU benchmark..."

mkdir -p "${RUN_DIR}/cpu"


sysbench cpu \
    --cpu-max-prime="${SYSBENCH_CPU_MAX_PRIME}" \
    --threads="${SYSBENCH_THREADS}" \
    --time="${SYSBENCH_CPU_TIME}" \
    run \
    > "${RUN_DIR}/cpu/sysbench_cpu_result.txt" 2>&1


log "CPU benchmark complete"


# =============================================================================
# Memory WRITE
# =============================================================================

mkdir -p "${RUN_DIR}/memory"


log "Running memory WRITE benchmark..."


sysbench memory \
    --memory-block-size=1K \
    --memory-total-size="${SYSBENCH_MEMORY_TOTAL_SIZE}" \
    --memory-oper=write \
    --threads="${SYSBENCH_THREADS}" \
    run \
    > "${RUN_DIR}/memory/sysbench_memory_write.txt" 2>&1


# =============================================================================
# Memory READ
# =============================================================================

log "Running memory READ benchmark..."


sysbench memory \
    --memory-block-size=1K \
    --memory-total-size="${SYSBENCH_MEMORY_TOTAL_SIZE}" \
    --memory-oper=read \
    --threads="${SYSBENCH_THREADS}" \
    run \
    > "${RUN_DIR}/memory/sysbench_memory_read.txt" 2>&1


log "Memory benchmark complete"


# =============================================================================
# GitHub
# =============================================================================

upload_to_github


log "===== sysbench benchmark complete ====="
log "Result: ${RUN_DIR}"