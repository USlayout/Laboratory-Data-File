#!/usr/bin/env bash

set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 RUN_DIR RUN_NUMBER"
    exit 1
fi

RUN_DIR="$1"
RUN_NUMBER="$2"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=/dev/null
source "${SCRIPT_DIR}/benchmark.conf"

if [ -z "${SYSBENCH_THREADS:-}" ]; then
    SYSBENCH_THREADS=$(nproc)
fi

OUT_DIR="${RUN_DIR}/sysbench/run$(printf '%02d' "${RUN_NUMBER}")"

mkdir -p "${OUT_DIR}/cpu"
mkdir -p "${OUT_DIR}/memory"

echo "Running sysbench CPU..."

sysbench cpu \
    --cpu-max-prime="${SYSBENCH_CPU_MAX_PRIME}" \
    --threads="${SYSBENCH_THREADS}" \
    --time="${SYSBENCH_CPU_TIME}" \
    run \
    > "${OUT_DIR}/cpu/sysbench_cpu_result.txt" 2>&1


echo "Running sysbench memory WRITE..."

sysbench memory \
    --memory-block-size=1K \
    --memory-total-size="${SYSBENCH_MEMORY_TOTAL_SIZE}" \
    --memory-oper=write \
    --threads="${SYSBENCH_THREADS}" \
    run \
    > "${OUT_DIR}/memory/sysbench_memory_write.txt" 2>&1


echo "Running sysbench memory READ..."

sysbench memory \
    --memory-block-size=1K \
    --memory-total-size="${SYSBENCH_MEMORY_TOTAL_SIZE}" \
    --memory-oper=read \
    --threads="${SYSBENCH_THREADS}" \
    run \
    > "${OUT_DIR}/memory/sysbench_memory_read.txt" 2>&1

echo "sysbench run ${RUN_NUMBER} complete"