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

OUT_DIR="${RUN_DIR}/fio/run$(printf '%02d' "${RUN_NUMBER}")"

mkdir -p "${OUT_DIR}"


echo "Sequential WRITE..."

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


echo "Sequential READ..."

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


echo "Random WRITE..."

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


echo "Random READ..."

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


# fioテストファイル削除
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


echo "fio run ${RUN_NUMBER} complete"