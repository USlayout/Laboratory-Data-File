#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"
BENCHMARK_RUNS="${IPERF_RUNS}"
parse_benchmark_args "$@"
for value in "${IPERF_INTERVAL_SECONDS}" "${IPERF_RETRIES}" "${IPERF_RETRY_INTERVAL_SECONDS}"; do
    if [[ ! "${value}" =~ ^(0|[1-9][0-9]*)$ ]]; then
        echo 'ERROR: iperf3 intervals and retries must be nonnegative integers' >&2
        exit 1
    fi
done
start_benchmark iperf3 iperf3

# 接続確認も測定自体で行う。失敗した試行は別名で保存する。
run_iperf() {
    local protocol="$1"
    shift
    local attempt=1
    local result="${OUT_DIR}/iperf3_${protocol}"
    while true; do
        log "iperf3 ${protocol}: run ${RUN_NUMBER}/${BENCHMARK_RUNS}, attempt ${attempt}"
        if "${CPU_PREFIX[@]}" iperf3 -c "${IPERF_SERVER_IP}" \
            -t "${IPERF_DURATION}" -J "$@" \
            > "${result}.attempt${attempt}.json" 2> "${result}.attempt${attempt}.stderr"; then
            mv "${result}.attempt${attempt}.json" "${result}.json"
            return 0
        fi
        if (( attempt > IPERF_RETRIES )); then
            log "ERROR: ${protocol} failed after ${attempt} attempts"
            echo "${protocol} failed after ${attempt} attempts" > "${OUT_DIR}/FAILED.txt"
            return 1
        fi
        log "Retrying in ${IPERF_RETRY_INTERVAL_SECONDS} seconds..."
        sleep "${IPERF_RETRY_INTERVAL_SECONDS}"
        attempt=$((attempt + 1))
    done
}

for ((RUN_NUMBER=1; RUN_NUMBER<=BENCHMARK_RUNS; RUN_NUMBER++)); do
    OUT_DIR="${RUN_DIR}/iperf3/run$(printf '%02d' "${RUN_NUMBER}")"
    mkdir -p "${OUT_DIR}"
    run_iperf tcp
    sleep "${IPERF_INTERVAL_SECONDS}"
    run_iperf udp -u -b 1G
    if (( RUN_NUMBER < BENCHMARK_RUNS )); then
        sleep "${IPERF_INTERVAL_SECONDS}"
    fi
done
finish_benchmark
