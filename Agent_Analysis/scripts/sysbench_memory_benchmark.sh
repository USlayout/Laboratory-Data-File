#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"
parse_benchmark_args "$@"
start_benchmark sysbench-memory sysbench
for ((RUN_NUMBER=1; RUN_NUMBER<=BENCHMARK_RUNS; RUN_NUMBER++)); do
OUT_DIR="${RUN_DIR}/sysbench/run$(printf '%02d' "${RUN_NUMBER}")"
mkdir -p "${OUT_DIR}/memory"
echo "Running sysbench memory WRITE..."

"${CPU_PREFIX[@]}" sysbench memory \
    --memory-block-size=1K \
    --memory-total-size="${SYSBENCH_MEMORY_TOTAL_SIZE}" \
    --memory-oper=write \
    --threads="${SYSBENCH_THREADS}" \
    run \
    > "${OUT_DIR}/memory/sysbench_memory_write.txt" 2>&1


echo "Running sysbench memory READ..."

"${CPU_PREFIX[@]}" sysbench memory \
    --memory-block-size=1K \
    --memory-total-size="${SYSBENCH_MEMORY_TOTAL_SIZE}" \
    --memory-oper=read \
    --threads="${SYSBENCH_THREADS}" \
    run \
    > "${OUT_DIR}/memory/sysbench_memory_read.txt" 2>&1


done
finish_benchmark
