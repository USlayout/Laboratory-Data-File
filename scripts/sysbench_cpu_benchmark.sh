#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"
parse_benchmark_args "$@"
start_benchmark sysbench-cpu sysbench
for ((RUN_NUMBER=1; RUN_NUMBER<=BENCHMARK_RUNS; RUN_NUMBER++)); do
OUT_DIR="${RUN_DIR}/sysbench/run$(printf '%02d' "${RUN_NUMBER}")"
mkdir -p "${OUT_DIR}/cpu"
echo "Running sysbench CPU..."

"${CPU_PREFIX[@]}" sysbench cpu \
    --cpu-max-prime="${SYSBENCH_CPU_MAX_PRIME}" \
    --threads="${SYSBENCH_THREADS}" \
    --time="${SYSBENCH_CPU_TIME}" \
    run \
    > "${OUT_DIR}/cpu/sysbench_cpu_result.txt" 2>&1



done
finish_benchmark
