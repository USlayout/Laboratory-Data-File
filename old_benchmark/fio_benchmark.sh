#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"


LABEL="${1:-}"

init_run "fio" "${LABEL}"

require_command fio


log "===== fio benchmark started ====="


collect_system_info
write_metadata


OUT_DIR="${RUN_DIR}/storage"

mkdir -p "${OUT_DIR}"


# =============================================================================
# Sequential WRITE
# =============================================================================

log "Sequential WRITE..."


fio \
    --name=seq_write \
    --directory="${OUT_DIR}" \
    --rw=write \
    --bs=1M \
    --size="${FIO_SIZE}" \
    --numjobs=1 \
    --runtime="${FIO_RUNTIME}" \
    --time_based \
    --group_reporting \
    --output-format=json \
    --output="${OUT_DIR}/fio_seq_write.json"


# =============================================================================
# Sequential READ
# =============================================================================

log "Sequential READ..."


fio \
    --name=seq_read \
    --directory="${OUT_DIR}" \
    --rw=read \
    --bs=1M \
    --size="${FIO_SIZE}" \
    --numjobs=1 \
    --runtime="${FIO_RUNTIME}" \
    --time_based \
    --group_reporting \
    --output-format=json \
    --output="${OUT_DIR}/fio_seq_read.json"


# =============================================================================
# Random WRITE
# =============================================================================

log "Random WRITE..."


fio \
    --name=rand_write \
    --directory="${OUT_DIR}" \
    --rw=randwrite \
    --bs=4k \
    --size="${FIO_SIZE}" \
    --numjobs=4 \
    --iodepth=32 \
    --runtime="${FIO_RUNTIME}" \
    --time_based \
    --group_reporting \
    --output-format=json \
    --output="${OUT_DIR}/fio_rand_write.json"


# =============================================================================
# Random READ
# =============================================================================

log "Random READ..."


fio \
    --name=rand_read \
    --directory="${OUT_DIR}" \
    --rw=randread \
    --bs=4k \
    --size="${FIO_SIZE}" \
    --numjobs=4 \
    --iodepth=32 \
    --runtime="${FIO_RUNTIME}" \
    --time_based \
    --group_reporting \
    --output-format=json \
    --output="${OUT_DIR}/fio_rand_read.json"


# =============================================================================
# テストファイル削除
# =============================================================================

find "${OUT_DIR}" \
    -maxdepth 1 \
    -type f \
    \( \
        -name "seq_write.*" \
        -o -name "seq_read.*" \
        -o -name "rand_write.*" \
        -o -name "rand_read.*" \
    \) \
    ! -name "*.json" \
    -delete 2>/dev/null || true


log "fio benchmark complete"


upload_to_github


log "===== fio benchmark complete ====="
log "Result: ${RUN_DIR}"