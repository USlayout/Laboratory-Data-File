#!/usr/bin/env bash
###############################################################################
# benchmark_suite.sh
#
# Automated benchmarking script for research comparing server virtualization
# and container technology performance.
#
# Workflow:
#   1. Check dependencies
#   2. Create output directory (~/benchmark/yyyy-mm-dd-hh-mm[-LABEL])
#   3. Collect system info (CPU/memory usage, running processes,
#      virtualization/container status, etc.)
#   4. Run benchmarks
#        - CPU     : sysbench cpu
#        - Memory  : sysbench memory
#        - Storage : fio
#        - Network : iperf3
#   5. Copy results into the GitHub data repo (~/Laboratory-Data-File/<run>/)
#   6. git fetch -> git pull -> git add/commit -> git push
#
# Usage:
#   ./benchmark_suite.sh [LABEL]
#     LABEL is optional. Tagging the run with something like "vm" or
#     "docker" makes it easy to compare virtualization vs container
#     results later.
#     e.g. ./benchmark_suite.sh kvm-vm
#          ./benchmark_suite.sh docker-container
#
# Configuration:
#   All tunable settings live in benchmark.conf (same directory as this
#   script by default). Edit that file instead of this script.
###############################################################################

set -euo pipefail

###############################################################################
# Load configuration
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${BENCHMARK_CONF:-${SCRIPT_DIR}/benchmark.conf}"

if [ ! -f "${CONFIG_FILE}" ]; then
    echo "[ERROR] Config file not found: ${CONFIG_FILE}"
    echo "        Copy benchmark.conf next to this script, or set BENCHMARK_CONF."
    exit 1
fi

# shellcheck source=benchmark.conf
source "${CONFIG_FILE}"

###############################################################################
# Timestamp / path setup
###############################################################################

LABEL="${1:-}"
TIMESTAMP=$(date +"%Y-%m-%d-%H-%M")
if [ -n "${LABEL}" ]; then
    RUN_NAME="${TIMESTAMP}-${LABEL}"
else
    RUN_NAME="${TIMESTAMP}"
fi

RUN_DIR="${BASE_DIR}/${RUN_NAME}"
GITHUB_RUN_DIR="${GITHUB_REPO_DIR}/${RUN_NAME}"
GIT_COMMIT_MESSAGE="Benchmark data ${RUN_NAME}"

###############################################################################
# Common functions
###############################################################################

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"
}

check_dependencies() {
    log "Checking dependencies..."
    local missing=0
    for cmd in sysbench fio iperf3 git nc; do
        if ! command -v "$cmd" &> /dev/null; then
            log "ERROR: '${cmd}' is not installed."
            missing=1
        fi
    done
    if [ "${missing}" -eq 1 ]; then
        log "Install everything at once with:"
        log "  sudo apt update && sudo apt install -y sysbench fio iperf3 git netcat-openbsd"
        exit 1
    fi
    log "Dependency check complete"
}

setup_directories() {
    log "Creating output directory: ${RUN_DIR}"
    mkdir -p "${RUN_DIR}"
}

###############################################################################
# System info collection
###############################################################################

collect_system_info() {
    log "Collecting system information..."
    local info_dir="${RUN_DIR}/system_info"
    mkdir -p "${info_dir}"

    {
        echo "===== hostname / uname ====="
        hostname
        uname -a
        echo
        echo "===== OS release info ====="
        cat /etc/os-release
    } > "${info_dir}/os_info.txt" 2>&1

    lscpu > "${info_dir}/cpu_info.txt" 2>&1

    {
        echo "===== free -h ====="
        free -h
        echo
        echo "===== /proc/meminfo ====="
        cat /proc/meminfo
    } > "${info_dir}/memory_info.txt" 2>&1

    {
        echo "===== df -h ====="
        df -h
        echo
        echo "===== lsblk ====="
        lsblk
    } > "${info_dir}/disk_info.txt" 2>&1

    ip a > "${info_dir}/network_info.txt" 2>&1 || true

    # CPU/memory usage snapshot (single batch-mode top run)
    top -b -n 1 > "${info_dir}/top_snapshot.txt" 2>&1

    # Running processes (by CPU / by memory)
    ps aux --sort=-%cpu > "${info_dir}/process_list_by_cpu.txt"
    ps aux --sort=-%mem > "${info_dir}/process_list_by_mem.txt"

    # Running systemd services
    systemctl list-units --type=service --state=running \
        > "${info_dir}/running_services.txt" 2>&1 || true

    # Virtualization / container detection (core to this comparison study)
    {
        echo "===== systemd-detect-virt ====="
        systemd-detect-virt 2>&1 || true
        echo
        echo "===== hypervisor flag in /proc/cpuinfo ====="
        grep -o 'hypervisor' /proc/cpuinfo | head -1 || echo "not detected"
        echo
        echo "===== docker ps -a (if installed) ====="
        if command -v docker &> /dev/null; then
            docker ps -a 2>&1 || true
        else
            echo "docker not installed"
        fi
        echo
        echo "===== virsh list --all (if installed) ====="
        if command -v virsh &> /dev/null; then
            virsh list --all 2>&1 || true
        else
            echo "virsh not installed"
        fi
    } > "${info_dir}/virtualization_info.txt"

    # Uptime / load average
    uptime > "${info_dir}/uptime.txt"

    # cgroup info (useful for checking container resource limits)
    if [ -d /sys/fs/cgroup ]; then
        find /sys/fs/cgroup -maxdepth 1 > "${info_dir}/cgroup_list.txt" 2>&1 || true
    fi

    log "System info collection complete: ${info_dir}"
}

write_metadata() {
    {
        echo "Run name        : ${RUN_NAME}"
        echo "Hostname        : $(hostname)"
        echo "User            : $(whoami)"
        echo "Label           : ${LABEL:-none}"
        echo "CPU threads     : ${SYSBENCH_THREADS}"
        echo "iperf3 targets  :"
        if [ "${#IPERF_TARGETS[@]}" -eq 0 ]; then
            echo "  (none configured)"
        else
            for t in "${IPERF_TARGETS[@]}"; do
                echo "  - ${t}"
            done
        fi
    } > "${RUN_DIR}/metadata.txt"
}

###############################################################################
# Benchmark: CPU (sysbench)
###############################################################################

run_cpu_benchmark() {
    log "Running CPU benchmark (sysbench cpu)..."
    local out_dir="${RUN_DIR}/cpu"
    mkdir -p "${out_dir}"

    sysbench cpu \
        --cpu-max-prime="${SYSBENCH_CPU_MAX_PRIME}" \
        --threads="${SYSBENCH_THREADS}" \
        --time="${SYSBENCH_CPU_TIME}" \
        run > "${out_dir}/sysbench_cpu_result.txt" 2>&1

    log "CPU benchmark complete"
}

###############################################################################
# Benchmark: Memory (sysbench)
###############################################################################

run_memory_benchmark() {
    log "Running memory benchmark (sysbench memory)..."
    local out_dir="${RUN_DIR}/memory"
    mkdir -p "${out_dir}"

    sysbench memory \
        --memory-block-size=1K \
        --memory-total-size="${SYSBENCH_MEMORY_TOTAL_SIZE}" \
        --memory-oper=write \
        --threads="${SYSBENCH_THREADS}" \
        run > "${out_dir}/sysbench_memory_write.txt" 2>&1

    sysbench memory \
        --memory-block-size=1K \
        --memory-total-size="${SYSBENCH_MEMORY_TOTAL_SIZE}" \
        --memory-oper=read \
        --threads="${SYSBENCH_THREADS}" \
        run > "${out_dir}/sysbench_memory_read.txt" 2>&1

    log "Memory benchmark complete"
}

###############################################################################
# Benchmark: Storage I/O (fio)
###############################################################################

run_storage_benchmark() {
    log "Running storage I/O benchmark (fio)..."
    local out_dir="${RUN_DIR}/storage"
    mkdir -p "${out_dir}"

    # Sequential write/read (throughput)
    fio --name=seq_write --directory="${out_dir}" --rw=write --bs=1M \
        --size="${FIO_SIZE}" --numjobs=1 --runtime="${FIO_RUNTIME}" \
        --time_based --group_reporting --output-format=json \
        --output="${out_dir}/fio_seq_write.json"

    fio --name=seq_read --directory="${out_dir}" --rw=read --bs=1M \
        --size="${FIO_SIZE}" --numjobs=1 --runtime="${FIO_RUNTIME}" \
        --time_based --group_reporting --output-format=json \
        --output="${out_dir}/fio_seq_read.json"

    # Random I/O (IOPS / latency)
    fio --name=rand_write --directory="${out_dir}" --rw=randwrite --bs=4k \
        --size="${FIO_SIZE}" --numjobs=4 --iodepth=32 --runtime="${FIO_RUNTIME}" \
        --time_based --group_reporting --output-format=json \
        --output="${out_dir}/fio_rand_write.json"

    fio --name=rand_read --directory="${out_dir}" --rw=randread --bs=4k \
        --size="${FIO_SIZE}" --numjobs=4 --iodepth=32 --runtime="${FIO_RUNTIME}" \
        --time_based --group_reporting --output-format=json \
        --output="${out_dir}/fio_rand_read.json"

    # Remove fio's raw test files, keep only the result JSON
    find "${out_dir}" -maxdepth 1 -type f \
        \( -name "seq_write.*" -o -name "seq_read.*" -o -name "rand_write.*" -o -name "rand_read.*" \) \
        ! -name "*.json" -delete 2>/dev/null || true

    log "Storage I/O benchmark complete"
}

###############################################################################
# Benchmark: Network (iperf3)
###############################################################################

run_network_benchmark() {
    log "Running network benchmark (iperf3)..."
    local base_out_dir="${RUN_DIR}/network"
    mkdir -p "${base_out_dir}"

    if [ "${#IPERF_TARGETS[@]}" -eq 0 ]; then
        log "WARNING: IPERF_TARGETS is empty, skipping network benchmark."
        echo "Skipped: IPERF_TARGETS was not configured." > "${base_out_dir}/SKIPPED.txt"
        return 0
    fi

    local target label ip out_dir
    for target in "${IPERF_TARGETS[@]}"; do
        label="${target%%:*}"
        ip="${target#*:}"
        out_dir="${base_out_dir}/${label}"
        mkdir -p "${out_dir}"

        log "  -> target: ${label} (${ip})"

        if ! nc -z -w 3 "${ip}" 5201 2>/dev/null; then
            log "  WARNING: cannot reach iperf3 server (${ip}:5201). Skipping '${label}'."
            echo "Skipped: could not reach iperf3 server (${ip}:5201)." \
                > "${out_dir}/SKIPPED.txt"
            continue
        fi

        # TCP throughput (forward direction: this host -> ${label})
        if ! iperf3 -c "${ip}" -t "${IPERF_DURATION}" -J \
            > "${out_dir}/iperf3_tcp.json" 2> "${out_dir}/iperf3_tcp.stderr"; then
            log "  WARNING: iperf3 TCP forward test failed for '${label}'."
            echo "iperf3 TCP forward test failed for ${ip}:5201." \
                > "${out_dir}/ERROR.txt"
        fi

        # TCP throughput (reverse direction: ${label} -> this host)
        if ! iperf3 -c "${ip}" -R -t "${IPERF_DURATION}" -J \
            > "${out_dir}/iperf3_tcp_reverse.json" 2>> "${out_dir}/iperf3_tcp.stderr"; then
            log "  WARNING: iperf3 TCP reverse test failed for '${label}'."
            echo "iperf3 TCP reverse test failed for ${ip}:5201." \
                > "${out_dir}/ERROR.txt"
        fi

        # UDP throughput, jitter, packet loss (capped at 1Gbps)
        if ! iperf3 -c "${ip}" -u -b 1G -t "${IPERF_DURATION}" -J \
            > "${out_dir}/iperf3_udp.json" 2>> "${out_dir}/iperf3_tcp.stderr"; then
            log "  WARNING: iperf3 UDP test failed for '${label}'."
            echo "iperf3 UDP test failed for ${ip}:5201." \
                > "${out_dir}/ERROR.txt"
        fi

        log "  -> '${label}' complete"
    done

    log "Network benchmark complete"
}

###############################################################################
# Upload to GitHub
###############################################################################

upload_to_github() {
    log "Uploading results to GitHub repository..."

    if [ ! -d "${GITHUB_REPO_DIR}/.git" ]; then
        log "ERROR: ${GITHUB_REPO_DIR} is not a git repository."
        log "Run 'git clone <repo-url> ${GITHUB_REPO_DIR}' first."
        exit 1
    fi

    mkdir -p "${GITHUB_RUN_DIR}"
    cp -r "${RUN_DIR}/." "${GITHUB_RUN_DIR}/"

    pushd "${GITHUB_REPO_DIR}" > /dev/null

    log "Running git fetch..."
    git fetch "${GIT_REMOTE}"

    # If a tracked file (e.g. a script committed into the repo) has
    # uncommitted local changes, `git pull` fails with "would be
    # overwritten by merge". Auto-stash (including this run's untracked
    # data) and retry so the script doesn't get stuck.
    log "Running git pull..."
    if ! git pull "${GIT_REMOTE}" "${GIT_BRANCH}"; then
        log "WARNING: git pull failed. Stashing local changes and retrying..."
        git stash push --include-untracked -m "auto-stash before pull ${RUN_NAME}"
        git pull "${GIT_REMOTE}" "${GIT_BRANCH}"
        log "Restoring stashed changes (including this run's data)..."
        git stash pop
    fi

    log "Running git add / commit..."
    git add "${RUN_NAME}"
    if git diff --cached --quiet; then
        log "Nothing to commit"
    else
        git commit -m "${GIT_COMMIT_MESSAGE}"
        log "Running git push..."
        git push "${GIT_REMOTE}" "${GIT_BRANCH}"
    fi

    popd > /dev/null

    log "GitHub upload complete: ${GITHUB_RUN_DIR}"
}

###############################################################################
# Main
###############################################################################

main() {
    log "===== Benchmark suite started (${RUN_NAME}) ====="

    check_dependencies
    setup_directories
    collect_system_info
    write_metadata

    run_cpu_benchmark
    run_memory_benchmark
    run_storage_benchmark
    run_network_benchmark

    upload_to_github

    log "===== Benchmark suite finished ====="
    log "Local output  : ${RUN_DIR}"
    log "GitHub output : ${GITHUB_RUN_DIR}"
}

main "$@"
