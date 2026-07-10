#!/usr/bin/env bash
###############################################################################
# benchmark_suite.sh
#
# サーバー仮想化技術とコンテナ技術の性能比較・最適化研究用
# ベンチマーク自動実行スクリプト
#
# 処理の流れ:
#   1. 依存ツールの確認
#   2. 保存先ディレクトリの作成 (~/benchmark/yyyy-mm-dd-hh-mm[-LABEL])
#   3. システム情報 (CPU/メモリ使用率・稼働プロセス・仮想化/コンテナ状態等) の収集
#   4. 各種ベンチマークの実行
#        - CPU     : sysbench cpu
#        - メモリ  : sysbench memory
#        - ストレージI/O : fio
#        - ネットワーク  : iperf3
#   5. GitHub用ディレクトリ (~/Laboratory-Data-File/日時/) へコピー
#   6. git fetch → git pull → git add/commit → git push
#
# 使い方:
#   ./benchmark_suite.sh [LABEL]
#     LABEL は任意。 "vm" や "docker" のように環境を区別するタグを付けると
#     後で仮想化環境とコンテナ環境の結果を比較しやすくなります。
#     例: ./benchmark_suite.sh kvm-vm
#         ./benchmark_suite.sh docker-container
###############################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/benchmark.conf"

###############################################################################
# 設定 (環境に合わせて書き換えてください)
###############################################################################

if [ ! -f "${CONFIG_FILE}" ]; then
    echo "Configuration file not found: ${CONFIG_FILE}"
    echo "Create it from the checked-in benchmark.conf template or restore it from version control."
    exit 1
fi

# shellcheck source=/dev/null
source "${CONFIG_FILE}"

if [ -z "${SYSBENCH_THREADS:-}" ]; then
    SYSBENCH_THREADS=$(nproc)
fi

###############################################################################
# タイムスタンプ・パス生成
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
# 共通関数
###############################################################################

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"
}

check_dependencies() {
    log "Checking required dependencies..."
    local missing=0
    for cmd in sysbench fio iperf3 git nc; do
        if ! command -v "$cmd" &> /dev/null; then
            log "Error: '${cmd}' is not installed."
            missing=1
        fi
    done
    if [ "${missing}" -eq 1 ]; then
        log "You can install them together with:"
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
# システム情報収集
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
        echo "===== OS information ====="
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

    # CPU/メモリ使用率のスナップショット (top をバッチモードで1回取得)
    top -b -n 1 > "${info_dir}/top_snapshot.txt" 2>&1

    # 稼働中プロセス一覧 (CPU順・メモリ順)
    ps aux --sort=-%cpu > "${info_dir}/process_list_by_cpu.txt"
    ps aux --sort=-%mem > "${info_dir}/process_list_by_mem.txt"

    # 稼働中の systemd サービス
    systemctl list-units --type=service --state=running \
        > "${info_dir}/running_services.txt" 2>&1 || true

    # 仮想化 / コンテナ状態の検出 (比較研究のキモになる部分)
    {
        echo "===== systemd-detect-virt ====="
        systemd-detect-virt 2>&1 || true
        echo
        echo "===== hypervisor flag in /proc/cpuinfo ====="
        grep -o 'hypervisor' /proc/cpuinfo | head -1 || echo "Not detected"
        echo
        echo "===== docker ps -a (if available) ====="
        if command -v docker &> /dev/null; then
            docker ps -a 2>&1 || true
        else
            echo "docker is not installed"
        fi
        echo
        echo "===== virsh list --all (if available) ====="
        if command -v virsh &> /dev/null; then
            virsh list --all 2>&1 || true
        else
            echo "virsh is not installed"
        fi
    } > "${info_dir}/virtualization_info.txt"

    # 稼働時間・ロードアベレージ
    uptime > "${info_dir}/uptime.txt"

    # cgroup情報 (コンテナのリソース制限確認用)
    if [ -d /sys/fs/cgroup ]; then
        find /sys/fs/cgroup -maxdepth 1 > "${info_dir}/cgroup_list.txt" 2>&1 || true
    fi

    log "System information collection complete: ${info_dir}"
}

write_metadata() {
    cat > "${RUN_DIR}/metadata.txt" <<EOF
実行日時       : ${RUN_NAME}
ホスト名       : $(hostname)
実行ユーザー   : $(whoami)
ラベル         : ${LABEL:-なし}
CPUコア数      : ${SYSBENCH_THREADS}
EOF
}

###############################################################################
# ベンチマーク: CPU (sysbench)
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
# ベンチマーク: メモリ (sysbench)
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
# ベンチマーク: ストレージ I/O (fio)
###############################################################################

run_storage_benchmark() {
    log "Running storage I/O benchmark (fio)..."
    local out_dir="${RUN_DIR}/storage"
    mkdir -p "${out_dir}"

    # シーケンシャル書き込み・読み込み (スループット計測)
    fio --name=seq_write --directory="${out_dir}" --rw=write --bs=1M \
        --size="${FIO_SIZE}" --numjobs=1 --runtime="${FIO_RUNTIME}" \
        --time_based --group_reporting --output-format=json \
        --output="${out_dir}/fio_seq_write.json"

    fio --name=seq_read --directory="${out_dir}" --rw=read --bs=1M \
        --size="${FIO_SIZE}" --numjobs=1 --runtime="${FIO_RUNTIME}" \
        --time_based --group_reporting --output-format=json \
        --output="${out_dir}/fio_seq_read.json"

    # ランダムI/O (IOPS・レイテンシ計測)
    fio --name=rand_write --directory="${out_dir}" --rw=randwrite --bs=4k \
        --size="${FIO_SIZE}" --numjobs=4 --iodepth=32 --runtime="${FIO_RUNTIME}" \
        --time_based --group_reporting --output-format=json \
        --output="${out_dir}/fio_rand_write.json"

    fio --name=rand_read --directory="${out_dir}" --rw=randread --bs=4k \
        --size="${FIO_SIZE}" --numjobs=4 --iodepth=32 --runtime="${FIO_RUNTIME}" \
        --time_based --group_reporting --output-format=json \
        --output="${out_dir}/fio_rand_read.json"

    # fioが作成したテストファイル本体は不要なので削除 (結果jsonのみ残す)
    find "${out_dir}" -maxdepth 1 -type f \
        \( -name "seq_write.*" -o -name "seq_read.*" -o -name "rand_write.*" -o -name "rand_read.*" \) \
        ! -name "*.json" -delete 2>/dev/null || true

    log "Storage I/O benchmark complete"
}

###############################################################################
# ベンチマーク: ネットワーク (iperf3)
###############################################################################

run_network_benchmark() {
    log "Running network benchmark (iperf3)..."
    local out_dir="${RUN_DIR}/network"
    mkdir -p "${out_dir}"

    if ! nc -z -w 3 "${IPERF_SERVER_IP}" 5201 2>/dev/null; then
        log "Warning: cannot connect to the iperf3 server (${IPERF_SERVER_IP}:5201). Skipping network benchmark."
        echo "Skipped because the iperf3 server (${IPERF_SERVER_IP}:5201) could not be reached." \
            > "${out_dir}/SKIPPED.txt"
        return 0
    fi

    # TCPスループット
    iperf3 -c "${IPERF_SERVER_IP}" -t "${IPERF_DURATION}" -J \
        > "${out_dir}/iperf3_tcp.json"

    # UDPスループット・ジッタ・パケットロス (帯域上限1Gbpsで送出)
    iperf3 -c "${IPERF_SERVER_IP}" -u -b 1G -t "${IPERF_DURATION}" -J \
        > "${out_dir}/iperf3_udp.json"

    log "Network benchmark complete"
}

###############################################################################
# GitHubへのアップロード
###############################################################################

upload_to_github() {
    log "Starting upload to the GitHub repository..."

    if [ ! -d "${GITHUB_REPO_DIR}/.git" ]; then
        log "Error: ${GITHUB_REPO_DIR} is not a git repository."
        log "Run 'git clone <repo-url> ${GITHUB_REPO_DIR}' first."
        exit 1
    fi

    mkdir -p "${GITHUB_RUN_DIR}"
    cp -r "${RUN_DIR}/." "${GITHUB_RUN_DIR}/"

    pushd "${GITHUB_REPO_DIR}" > /dev/null

    log "Running git fetch..."
    git fetch "${GIT_REMOTE}"

    # 追跡対象ファイル(benchmark.sh 等)にローカル未コミットの変更が残っていると
    # pull が "would be overwritten by merge" で失敗するため、
    # 今回コピーしたデータ以外に汚れがある場合は自動で退避してから pull する。
    log "Running git pull..."
    if ! git pull "${GIT_REMOTE}" "${GIT_BRANCH}"; then
        log "Warning: pull failed. Temporarily stashing local uncommitted changes and retrying."
        git stash push --include-untracked -m "auto-stash before pull ${RUN_NAME}"
        git pull "${GIT_REMOTE}" "${GIT_BRANCH}"
        log "Restoring stashed changes, including this benchmark data..."
        git stash pop
    fi

    log "Running git add / commit..."
    git add "${RUN_NAME}"
    if git diff --cached --quiet; then
        log "No changes to commit"
    else
        git commit -m "${GIT_COMMIT_MESSAGE}"
        log "Running git push..."
        git push "${GIT_REMOTE}" "${GIT_BRANCH}"
    fi

    popd > /dev/null

    log "Upload to GitHub complete: ${GITHUB_RUN_DIR}"
}

###############################################################################
# メイン処理
###############################################################################

main() {
    log "===== Benchmark automation started (${RUN_NAME}) ====="

    check_dependencies
    setup_directories
    collect_system_info
    write_metadata

    run_cpu_benchmark
    run_memory_benchmark
    run_storage_benchmark
    run_network_benchmark

    upload_to_github

    log "===== Benchmark automation complete ====="
    log "Local output directory : ${RUN_DIR}"
    log "GitHub output directory: ${GITHUB_RUN_DIR}"
}

main "$@"