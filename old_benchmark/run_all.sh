#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

LABEL="${1:-}"

require_command sysbench
require_command fio
require_command git

init_experiment "${LABEL}"

log "=================================================="
log " Benchmark experiment started"
log " Label : ${LABEL:-none}"
log " Runs  : ${BENCHMARK_RUNS}"
log "=================================================="

collect_system_info
write_metadata


# =============================================================================
# sysbench × 10
# =============================================================================

log "=================================================="
log " sysbench x ${BENCHMARK_RUNS}"
log "=================================================="

for ((i=1; i<=BENCHMARK_RUNS; i++)); do

    log "sysbench run ${i}/${BENCHMARK_RUNS}"

    "${SCRIPT_DIR}/sysbench_benchmark.sh" \
        "${RUN_DIR}" \
        "${i}"

done


# =============================================================================
# fio × 10
# =============================================================================

log "=================================================="
log " fio x ${BENCHMARK_RUNS}"
log "=================================================="

for ((i=1; i<=BENCHMARK_RUNS; i++)); do

    log "fio run ${i}/${BENCHMARK_RUNS}"

    "${SCRIPT_DIR}/fio_benchmark.sh" \
        "${RUN_DIR}" \
        "${i}"

done


# =============================================================================
# GitHub
# =============================================================================

log "=================================================="
log " sysbench / fio completed"
log " Uploading results to GitHub"
log "=================================================="

upload_to_github


log "=================================================="
log " Benchmark experiment complete"
log "=================================================="

log "Local:"
log "  ${RUN_DIR}"

log "GitHub:"
log "  ${GITHUB_RUN_DIR}"