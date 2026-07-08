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

###############################################################################
# 設定 (環境に合わせて書き換えてください)
###############################################################################

# ローカルの生データ保存先ルート
BASE_DIR="${HOME}/benchmark"

# GitHubリポジトリのローカルパス (事前に git clone 済みであること)
GITHUB_REPO_DIR="${HOME}/Laboratory-Data-File"

# iperf3サーバーのIPアドレス (別ホスト/別VM/別コンテナで `iperf3 -s` を起動しておく)
IPERF_SERVER_IP="192.168.1.100"
IPERF_DURATION=30            # 秒

# sysbench 設定
SYSBENCH_THREADS=$(nproc)
SYSBENCH_CPU_MAX_PRIME=20000
SYSBENCH_CPU_TIME=60         # 秒
SYSBENCH_MEMORY_TOTAL_SIZE="10G"

# fio 設定
FIO_SIZE="1G"
FIO_RUNTIME=30                # 秒

# git 設定
GIT_REMOTE="origin"
GIT_BRANCH="main"

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
    log "依存ツールを確認しています..."
    local missing=0
    for cmd in sysbench fio iperf3 git nc; do
        if ! command -v "$cmd" &> /dev/null; then
            log "エラー: '${cmd}' がインストールされていません。"
            missing=1
        fi
    done
    if [ "${missing}" -eq 1 ]; then
        log "以下でまとめてインストールできます:"
        log "  sudo apt update && sudo apt install -y sysbench fio iperf3 git netcat-openbsd"
        exit 1
    fi
    log "依存ツールの確認完了"
}

setup_directories() {
    log "保存先ディレクトリを作成しています: ${RUN_DIR}"
    mkdir -p "${RUN_DIR}"
}

###############################################################################
# システム情報収集
###############################################################################

collect_system_info() {
    log "システム情報を収集しています..."
    local info_dir="${RUN_DIR}/system_info"
    mkdir -p "${info_dir}"

    {
        echo "===== hostname / uname ====="
        hostname
        uname -a
        echo
        echo "===== OS情報 ====="
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
        echo "===== /proc/cpuinfo 中の hypervisor flag ====="
        grep -o 'hypervisor' /proc/cpuinfo | head -1 || echo "検出されず"
        echo
        echo "===== docker ps -a (存在する場合) ====="
        if command -v docker &> /dev/null; then
            docker ps -a 2>&1 || true
        else
            echo "dockerは未インストール"
        fi
        echo
        echo "===== virsh list --all (存在する場合) ====="
        if command -v virsh &> /dev/null; then
            virsh list --all 2>&1 || true
        else
            echo "virshは未インストール"
        fi
    } > "${info_dir}/virtualization_info.txt"

    # 稼働時間・ロードアベレージ
    uptime > "${info_dir}/uptime.txt"

    # cgroup情報 (コンテナのリソース制限確認用)
    if [ -d /sys/fs/cgroup ]; then
        find /sys/fs/cgroup -maxdepth 1 > "${info_dir}/cgroup_list.txt" 2>&1 || true
    fi

    log "システム情報収集完了: ${info_dir}"
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
    log "CPUベンチマークを実行しています (sysbench cpu)..."
    local out_dir="${RUN_DIR}/cpu"
    mkdir -p "${out_dir}"

    sysbench cpu \
        --cpu-max-prime="${SYSBENCH_CPU_MAX_PRIME}" \
        --threads="${SYSBENCH_THREADS}" \
        --time="${SYSBENCH_CPU_TIME}" \
        run > "${out_dir}/sysbench_cpu_result.txt" 2>&1

    log "CPUベンチマーク完了"
}

###############################################################################
# ベンチマーク: メモリ (sysbench)
###############################################################################

run_memory_benchmark() {
    log "メモリベンチマークを実行しています (sysbench memory)..."
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

    log "メモリベンチマーク完了"
}

###############################################################################
# ベンチマーク: ストレージ I/O (fio)
###############################################################################

run_storage_benchmark() {
    log "ストレージI/Oベンチマークを実行しています (fio)..."
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

    log "ストレージI/Oベンチマーク完了"
}

###############################################################################
# ベンチマーク: ネットワーク (iperf3)
###############################################################################

run_network_benchmark() {
    log "ネットワークベンチマークを実行しています (iperf3)..."
    local out_dir="${RUN_DIR}/network"
    mkdir -p "${out_dir}"

    if ! nc -z -w 3 "${IPERF_SERVER_IP}" 5201 2>/dev/null; then
        log "警告: iperf3サーバー(${IPERF_SERVER_IP}:5201)に接続できません。ネットワークベンチマークをスキップします。"
        echo "iperf3サーバー(${IPERF_SERVER_IP}:5201)に接続できなかったためスキップしました。" \
            > "${out_dir}/SKIPPED.txt"
        return 0
    fi

    # TCPスループット
    iperf3 -c "${IPERF_SERVER_IP}" -t "${IPERF_DURATION}" -J \
        > "${out_dir}/iperf3_tcp.json"

    # UDPスループット・ジッタ・パケットロス (帯域上限1Gbpsで送出)
    iperf3 -c "${IPERF_SERVER_IP}" -u -b 1G -t "${IPERF_DURATION}" -J \
        > "${out_dir}/iperf3_udp.json"

    log "ネットワークベンチマーク完了"
}

###############################################################################
# GitHubへのアップロード
###############################################################################

upload_to_github() {
    log "GitHubリポジトリへのアップロードを開始します..."

    if [ ! -d "${GITHUB_REPO_DIR}/.git" ]; then
        log "エラー: ${GITHUB_REPO_DIR} はgitリポジトリではありません。"
        log "事前に 'git clone <repo-url> ${GITHUB_REPO_DIR}' を実行してください。"
        exit 1
    fi

    mkdir -p "${GITHUB_RUN_DIR}"
    cp -r "${RUN_DIR}/." "${GITHUB_RUN_DIR}/"

    pushd "${GITHUB_REPO_DIR}" > /dev/null

    log "git fetch を実行しています..."
    git fetch "${GIT_REMOTE}"

    # 追跡対象ファイル(benchmark.sh 等)にローカル未コミットの変更が残っていると
    # pull が "would be overwritten by merge" で失敗するため、
    # 今回コピーしたデータ以外に汚れがある場合は自動で退避してから pull する。
    log "git pull を実行しています..."
    if ! git pull "${GIT_REMOTE}" "${GIT_BRANCH}"; then
        log "警告: pullに失敗しました。ローカルの未コミット変更を一時退避(stash)して再試行します。"
        git stash push --include-untracked -m "auto-stash before pull ${RUN_NAME}"
        git pull "${GIT_REMOTE}" "${GIT_BRANCH}"
        log "退避した変更を復元します (今回のベンチマークデータを含む)..."
        git stash pop
    fi

    log "git add / commit を実行しています..."
    git add "${RUN_NAME}"
    if git diff --cached --quiet; then
        log "コミットする変更がありません"
    else
        git commit -m "${GIT_COMMIT_MESSAGE}"
        log "git push を実行しています..."
        git push "${GIT_REMOTE}" "${GIT_BRANCH}"
    fi

    popd > /dev/null

    log "GitHubへのアップロード完了: ${GITHUB_RUN_DIR}"
}

###############################################################################
# メイン処理
###############################################################################

main() {
    log "===== ベンチマーク自動化スクリプト開始 (${RUN_NAME}) ====="

    check_dependencies
    setup_directories
    collect_system_info
    write_metadata

    run_cpu_benchmark
    run_memory_benchmark
    run_storage_benchmark
    run_network_benchmark

    upload_to_github

    log "===== ベンチマーク自動化スクリプト完了 ====="
    log "ローカル保存先 : ${RUN_DIR}"
    log "GitHub保存先   : ${GITHUB_RUN_DIR}"
}

main "$@"