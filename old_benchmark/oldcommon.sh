#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/benchmark.conf"

# =============================================================================
# 設定読み込み
# =============================================================================

if [ ! -f "${CONFIG_FILE}" ]; then
    echo "Configuration file not found: ${CONFIG_FILE}"
    exit 1
fi

# shellcheck source=/dev/null
source "${CONFIG_FILE}"

if [ -z "${SYSBENCH_THREADS:-}" ]; then
    SYSBENCH_THREADS=$(nproc)
fi


# =============================================================================
# ログ
# =============================================================================

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"
}


# =============================================================================
# 実行ディレクトリ作成
#
# init_run "sysbench" "kvm"
# =============================================================================

init_run() {

    BENCHMARK_TYPE="$1"
    LABEL="${2:-}"

    TIMESTAMP=$(date +"%Y-%m-%d-%H-%M-%S")

    if [ -n "${LABEL}" ]; then
        RUN_NAME="${TIMESTAMP}-${LABEL}"
    else
        RUN_NAME="${TIMESTAMP}"
    fi

    RUN_DIR="${BASE_DIR}/${BENCHMARK_TYPE}/${RUN_NAME}"

    # GitHub側も種類ごとに分離
    GITHUB_RUN_DIR="${GITHUB_REPO_DIR}/${BENCHMARK_TYPE}/${RUN_NAME}"

    GIT_COMMIT_MESSAGE="${BENCHMARK_TYPE} benchmark data ${RUN_NAME}"

    mkdir -p "${RUN_DIR}"

    log "Output directory: ${RUN_DIR}"
}


# =============================================================================
# コマンド存在確認
# =============================================================================

require_command() {

    local cmd="$1"

    if ! command -v "${cmd}" &> /dev/null; then
        log "ERROR: '${cmd}' is not installed."
        exit 1
    fi
}


# =============================================================================
# システム情報
# =============================================================================

collect_system_info() {

    log "Collecting system information..."

    local info_dir="${RUN_DIR}/system_info"

    mkdir -p "${info_dir}"

    {
        echo "===== hostname ====="
        hostname

        echo
        echo "===== uname ====="
        uname -a

        echo
        echo "===== OS ====="
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


    top -b -n 1 \
        > "${info_dir}/top_snapshot.txt" 2>&1


    ps aux --sort=-%cpu \
        > "${info_dir}/process_list_by_cpu.txt"

    ps aux --sort=-%mem \
        > "${info_dir}/process_list_by_mem.txt"


    systemctl list-units \
        --type=service \
        --state=running \
        > "${info_dir}/running_services.txt" 2>&1 || true


    # =========================================================================
    # 仮想化 / コンテナ情報
    # =========================================================================

    {
        echo "===== systemd-detect-virt ====="

        systemd-detect-virt 2>&1 || true


        echo
        echo "===== hypervisor flag ====="

        grep -o 'hypervisor' /proc/cpuinfo \
            | head -1 \
            || echo "Not detected"


        echo
        echo "===== docker ps -a ====="

        if command -v docker &> /dev/null; then
            docker ps -a 2>&1 || true
        else
            echo "docker is not installed"
        fi


        echo
        echo "===== virsh list --all ====="

        if command -v virsh &> /dev/null; then
            virsh list --all 2>&1 || true
        else
            echo "virsh is not installed"
        fi

    } > "${info_dir}/virtualization_info.txt"


    uptime > "${info_dir}/uptime.txt"


    if [ -d /sys/fs/cgroup ]; then

        find /sys/fs/cgroup \
            -maxdepth 1 \
            > "${info_dir}/cgroup_list.txt" 2>&1 || true

    fi


    log "System information collection complete"
}


# =============================================================================
# メタデータ
# =============================================================================

write_metadata() {

    cat > "${RUN_DIR}/metadata.txt" <<EOF
ベンチマーク   : ${BENCHMARK_TYPE}
実行日時       : ${TIMESTAMP}
ホスト名       : $(hostname)
実行ユーザー   : $(whoami)
ラベル         : ${LABEL:-なし}
CPUコア数      : ${SYSBENCH_THREADS}
EOF

}


# =============================================================================
# GitHubアップロード
# =============================================================================

upload_to_github() {

    log "Starting GitHub upload..."

    require_command git


    if [ ! -d "${GITHUB_REPO_DIR}/.git" ]; then

        log "ERROR: ${GITHUB_REPO_DIR} is not a Git repository."
        log "Run git clone first."

        exit 1
    fi


    mkdir -p "${GITHUB_RUN_DIR}"

    cp -r \
        "${RUN_DIR}/." \
        "${GITHUB_RUN_DIR}/"


    pushd "${GITHUB_REPO_DIR}" > /dev/null


    log "git fetch"

    git fetch "${GIT_REMOTE}"


    log "git pull"

    if ! git pull "${GIT_REMOTE}" "${GIT_BRANCH}"; then

        log "Pull failed. Stashing local changes."

        git stash push \
            --include-untracked \
            -m "auto-stash before pull ${RUN_NAME}"

        git pull "${GIT_REMOTE}" "${GIT_BRANCH}"

        log "Restoring stash"

        git stash pop

    fi


    log "git add"

    git add "${BENCHMARK_TYPE}/${RUN_NAME}"


    if git diff --cached --quiet; then

        log "No changes to commit"

    else

        git commit \
            -m "${GIT_COMMIT_MESSAGE}"

        log "git push"

        git push \
            "${GIT_REMOTE}" \
            "${GIT_BRANCH}"

    fi


    popd > /dev/null


    log "GitHub upload complete"
}