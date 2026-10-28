# 仮想化環境性能比較 ベンチマーク実行マニュアル

この文書は `benchmark_reviewed.zip` に含まれるスクリプトに対応します。ホストOS・VM・Docker・VM上Dockerなどの実験環境で、sysbench（CPU/メモリ）、fio（ストレージ）、iperf3（ネットワーク）を測定します。

> **注意**：この配布版は構文チェック済みですが、実機でのベンチマーク完走は未確認です。fioの読み込み用ファイルの事前準備、Gitの自動stash処理、中央値の自動集計には改善余地があります。本測定前に試運転してください。

## 1. ファイル一覧

| ファイル | 役割 |
|---|---|
| `benchmark.conf` | 実験回数、CPU番号、測定時間、保存先などを設定 |
| `common.sh` | 共通設定、環境情報収集、GitHubアップロード |
| `run_all.sh` | sysbenchとfioを指定回数ずつ実行 |
| `sysbench_benchmark.sh` | CPU、メモリREAD/WRITEを1セット測定 |
| `fio_benchmark.sh` | 順次READ/WRITE、ランダムREAD/WRITEを1セット測定 |
| `iperf3_benchmark.sh` | TCPとUDPを1セット測定しGitHubに保存 |
| `graph_summary.py` | `*_summary_avg_median.txt` を読み込み、`Graph/` にグラフを出力 |

## 2. Ubuntuへの導入

```bash
sudo apt update
sudo apt install -y sysbench fio iperf3 git netcat-openbsd util-linux
```

`util-linux` は `taskset`、`netcat-openbsd` は `nc` を提供します。`lscpu`、`ip`、`top` などの環境情報収集コマンドも使用します。必要に応じて `iproute2`、`procps` を導入してください。

ZIPを展開し、スクリプトを同じディレクトリに置きます。

```bash
unzip benchmark_reviewed.zip
cd benchmark_reviewed
chmod +x run_all.sh sysbench_benchmark.sh fio_benchmark.sh iperf3_benchmark.sh
bash -n common.sh run_all.sh sysbench_benchmark.sh fio_benchmark.sh iperf3_benchmark.sh
```

## 3. CPU番号の確認と固定

```bash
lscpu -e=CPU,CORE,SOCKET,NODE,ONLINE
nproc
# 現在のシェルが使用可能なCPU
 taskset -pc $$
```

`CPU` はLinuxが認識する**論理CPU番号**、`CORE` は物理コアの識別子です。Pコア/Eコアを持つハイブリッドCPUでは、番号だけでPコアとは判断できません。CPU型番・トポロジー・各コアの最大周波数等を確認してください。同一物理コアのSMT兄弟スレッドを別々のPコアと数えないように注意します。

設定例（番号は例示であり、実機のPコアを保証しません）：

```bash
SYSBENCH_THREADS=4
BENCHMARK_CPU_CORES="0,2,4,6"
```

`SYSBENCH_THREADS` はsysbenchのワーカースレッド数、`BENCHMARK_CPU_CORES` は `taskset -c` で許可する論理CPU番号です。連続範囲 `0-3` も指定できます。空文字 `""` なら固定しません。設定CPUがコンテナのcpusetやVMで使用不可の場合は失敗します。

VM内部のCPU番号はホストの物理CPU番号と一致するとは限りません。VMのvCPUピニングと、ゲスト内のアフィニティ設定を分けて記録してください。Dockerはコンテナ自体のCPU制限も別途統一します。

## 4. benchmark.conf の設定

```bash
BASE_DIR="${HOME}/benchmark"
GITHUB_REPO_DIR="${HOME}/Laboratory-Data-File"
BENCHMARK_RUNS=10
SYSBENCH_THREADS=4
BENCHMARK_CPU_CORES="0,2,4,6"
SYSBENCH_CPU_MAX_PRIME=20000
SYSBENCH_CPU_TIME=60
SYSBENCH_MEMORY_TOTAL_SIZE="10G"
FIO_SIZE="1G"
FIO_RUNTIME=30
IPERF_SERVER_IP="192.168.50.65"
IPERF_DURATION=30
GIT_REMOTE="origin"
GIT_BRANCH="main"
```

- `SYSBENCH_CPU_TIME=60`：CPUテストの実行時間（秒）。
- `SYSBENCH_MEMORY_TOTAL_SIZE=10G`：メモリ転送の総量。**割り当てRAM容量ではありません**。
- `FIO_SIZE=1G`：fioのテストファイルサイズ。各ジョブで使用する容量に注意してください。
- `FIO_RUNTIME=30`：fio各テストの実行時間（秒）。
- `IPERF_SERVER_IP`：iperf3サーバーのIP。環境に合わせて変更します。

実験対象ディスクと同じファイルシステム上に `BASE_DIR` を置いてください。ルートディスクを測りたいのか、専用データディスクを測りたいのか明示し、空き容量を確保してください。

## 5. sysbench・fioを各10回実行

```bash
./run_all.sh host-pcore4
```

ラベル `host-pcore4` は任意です。`run_all.sh` はシステム情報を取得した後、sysbenchのCPU/メモリ測定を10セット、fioの4種類のI/O測定を10セット行い、最後にGitHubへアップロードします。**iperf3はこのコマンドでは実行されません。**

途中で失敗すると `set -e` により停止します。結果はローカルに残りますが、最後のGitHubアップロードまで到達しない場合があります。

## 6. iperf3を手動で1回ずつ実行

**サーバー側（別PC等）：**

```bash
iperf3 -s
```

**クライアント側（測定対象）：**

```bash
# benchmark.confのIPERF_SERVER_IPを確認してから
./iperf3_benchmark.sh host-pcore4
```

1回の起動でTCPを30秒、UDPを30秒測定し、それぞれJSONで保存します。10回測定する場合は、ネットワーク状態を確認しながらこのコマンドを**手動で10回**実行してください。各回で独立したタイムスタンプ付きディレクトリが作られます。

UDPは現状 `-b 1G`（目標送信レート1 Gbit/s）に固定されています。リンク速度・パケットロス・サーバー性能に応じて変更を検討し、変更した場合は研究条件にも明記してください。UDPの目標帯域と実効スループットは別物です。

接続確認：

```bash
nc -z -w 3 192.168.50.65 5201
```

ファイアウォール、IPアドレス、サーバーの起動状態、TCP/UDPの疎通を確認してください。

## 7. 結果の保存先と見方

保存先の例：

```text
~/benchmark/2026-10-14-13-00-00-host-pcore4/
├── metadata.txt
├── system_info/
├── sysbench/
│   ├── run01/cpu/sysbench_cpu_result.txt
│   └── run01/memory/sysbench_memory_read.txt
└── fio/
    └── run01/fio_seq_write.json
```

iperf3専用実行では `iperf3/iperf3_tcp.json` と `iperf3/iperf3_udp.json` が保存されます。

- sysbench CPU：`events per second`（イベント/秒）を比較します。
- sysbench memory：`transferred` に表示される転送レートを確認します。
- fio：JSON内の `read` / `write` の `bw_bytes`（バイト/秒）、`iops`、レイテンシ等を確認します。項目はfioのバージョンやジョブ構成で異なります。
- iperf3：TCPの受信側 `bits_per_second`、UDPの受信側スループット・loss・jitterを確認します。JSONの階層はバージョンによって異なります。

10回の代表値には、研究条件に合わせて**中央値**を用います。元データは削除せず、中央値のほか最小・最大値やばらつきも残すと比較しやすくなります。この配布版に中央値の自動集計機能はありません。

## 8. 集計値のグラフ化

`*_summary_avg_median.txt` を再帰的に読み込み、`Graph/` に比較用 PNG のみを出力します。`comparison_*.png` は最終値として中央値を使い、Host・KVM・Docker などの環境を横並びで比較します。ホスト名とOSも凡例に表示し、標準偏差が集計ファイルに含まれる場合はエラーバーとして表示します。

```powershell
python -m pip install matplotlib
python graph_summary.py
```

入力場所や出力場所を変更する場合：

```powershell
python graph_summary.py --root . --output-dir Graph
```

環境比較グラフの一覧は `Graph/comparison_index.csv` に記録されます。

## 9. GitHubアップロード

先に保存先リポジトリをcloneしておきます。

```bash
git clone <あなたのリポジトリURL> "$HOME/Laboratory-Data-File"
```

認証方式（SSH鍵または認証済みHTTPS）と `GIT_REMOTE`、`GIT_BRANCH` を確認してください。スクリプトは結果をコピーし、`git add`、`git commit`、`git push` を実行します。

**注意**：現行 `common.sh` は `git pull` が失敗した場合に `git stash --include-untracked` と `stash pop` を試みます。既存の未コミット変更がある場合、競合・意図しない退避が起こり得ます。実行前に以下を確認してください。

```bash
cd "$HOME/Laboratory-Data-File"
git status
```

安全のため、変更をコミットまたは別途バックアップし、作業ツリーをクリーンにしてから実行してください。通信エラーでpushに失敗しても、ローカルの実験データは保存されています。

## 9. よくあるエラー

| 症状 | 確認すること |
|---|---|
| `taskset: failed to set pid's affinity` | 指定したCPU番号が現在の環境で許可されているか、`taskset -pc $$` で確認 |
| `command not found` | `sysbench`、`fio`、`iperf3`、`git`、`nc`、`taskset` をインストール |
| `Permission denied` | `chmod +x *.sh`、保存先ディレクトリの権限 |
| fioが失敗する | 対象ディスクの空き容量、書込権限、`libaio` 対応、ファイル作成の可否 |
| iperf3接続失敗 | サーバー `iperf3 -s`、IP、5201番ポート、ファイアウォール |
| `git pull` / `git push` 失敗 | 作業ツリー、認証、ブランチ、リモートの状態を確認 |
| CPU測定値が不安定 | 他プロセス、CPU温度、周波数、Turbo、SMT、VMスケジューリングを確認 |

## 10. 卒業研究での測定上の注意

1. ホストOS・VM・Docker・VM上Dockerの各環境で、CPU数・RAM割当・ストレージ・ネットワーク・ベンチマーク条件を統一します。
2. Pコア固定条件では、ホストの物理コア、SMT兄弟関係、ゲストのvCPU割当を記録します。アフィニティ未固定条件と区別します。
3. CPU周波数ガバナー、Turbo Boost、ホストのバックグラウンド負荷、OS・カーネル・ツールのバージョンを記録します。
4. 測定順序と実行時刻を残し、温度・キャッシュ・ウォームアップの影響を考慮します。
5. fioの現在のREAD測定は入力ファイルの事前準備を保証していません。**本測定前にREAD用データの事前作成処理を追加**してください。
6. fioの `direct=1` と `ioengine=libaio` は指定されていますが、実際のI/O深度や対象ファイルシステム・ストレージ条件を確認してください。
7. `iperf3` のサーバー側もCPUやネットワークのボトルネックになり得るため、測定対象以外の条件を固定します。
8. `sysbench` のCPUイベント/秒は、汎用的なFLOPSやCPUクロック数そのものではありません。指標名を明記して比較します。

---

**推奨実行順序**：設定確認 → CPU番号確認 → 1回試運転 → 出力とGitHub保存の確認 → 研究条件を固定 → 10回本測定 → 中央値の算出・比較。
