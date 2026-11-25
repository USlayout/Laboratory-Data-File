# 仮想化環境性能比較 ベンチマーク実行マニュアル

## Tkinter解析GUI（Windows）

`tools` は独立したuvプロジェクトです。初回起動時に必要な依存関係が自動で導入されます。

```powershell
cd tools
uv run tools
```

依存関係だけを先に導入する場合（`tools` 内で実行）：

```powershell
uv sync
```

1. 「データ解析」で測定フォルダと環境名を指定し「解析する」を押します。サブフォルダも検索するので、10回分を含む実験フォルダを選択してください。古いiperf3のように複数の実験フォルダをまとめた親フォルダにも対応します。同じ環境・同じ測定条件のデータだけを選び、HostとKVMなどを一緒に集計しないでください。
2. 平均値・中央値・標本標準偏差・外れ値件数を一覧で確認します。指標をクリックすると、元ファイル名と各測定値、外れ値を除いた参考値を確認できます。
3. 「JSON・CSV保存」で解析JSON、集計CSV、元ファイル名付きの測定値CSVを保存します。元の測定ファイルは変更しません。
4. 「環境比較グラフ」でHost・KVM・Docker・KVM上Dockerの解析JSONを各行に指定します。環境名は編集可能で、2～4環境に対応します。
5. 共通指標を選び「グラフ表示」。中央値・平均値・標準偏差の3パネルを表示し、PNGまたはSVGに保存できます。CPU・メモリなど別の解析結果は、比較したい種類に応じてJSONを入れ替えます。

### 集計の定義と注意表示

- 標準偏差は**測定回ごとの標本標準偏差（ddof=1）**です。fio自身が出力するI/Oごとの標準偏差とは異なります。1件では「算出不可」、グラフではN/Aと表示します。
- 外れ値は四分位範囲（IQR）の1.5倍によるTukey法です。四分位数はinclusive方式、4件未満では判定しません。IQRが0の場合も同じ規則を使用します。
- 既定で外れ値の割合が20%以上なら「外れ値が多い」と表示します。閾値は画面で変更できます。少数回の測定での外れ値判定は参考情報です。
- **外れ値は自動削除しません。**通常の統計は全測定値を使用します。比較画面で「外れ値除外の参考値」を選ぶと、除外後の値も比較できます。
- 壊れたJSON・失敗した測定は集計せず注意欄に記録します。iperf3の `.attempt*.json` は再試行記録として表示し、通常の成功JSONと二重集計しません。iperf3のスループットは受信側の集計を使用します。
- fioのスループットはMiB/s、総レイテンシ平均はµs、iperf3のスループットはMbit/sです。複数fioジョブでは帯域・IOPSを合計し、レイテンシはI/O件数で重み付けします。
- 比較は指標名・単位が一致する共通項目のみです。全環境で揃わない指標と注意件数を画面に表示します。スレッド数・CPU割当・測定時間などの条件一致を自動保証するものではありません。保存JSONには元のmetadata.txtと各測定値の出典を含めます。
- 旧 `*_summary_avg_median.txt` は測定値を含まないため、このGUIでは直接読み込みません。元の測定フォルダから解析JSONを作ってください。既存の `graph_summary.py` は引き続き利用できます。

解析ロジックの確認：

```powershell
uv run python -m unittest discover -s tests -v
```

この文書は `benchmark_reviewed.zip` に含まれるスクリプトに対応します。ホストOS・VM・Docker・VM上Dockerなどの実験環境で、sysbench（CPU/メモリ）、fio（ストレージ）、iperf3（ネットワーク）を測定します。

> **注意**：この配布版は構文チェック済みですが、実機でのベンチマーク完走は未確認です。fioの読み込み用ファイルの事前準備、Gitの自動stash処理、中央値の自動集計には改善余地があります。本測定前に試運転してください。

## 1. ファイル一覧

| ファイル | 役割 |
|---|---|
| `benchmark.conf` | 実験回数、CPU番号、測定時間、保存先などを設定 |
| `common.sh` | 共通設定、環境情報収集、GitHubアップロード |
| `sysbench_cpu_benchmark.sh` | CPUを独立して指定回数測定 |
| `sysbench_memory_benchmark.sh` | メモリREAD/WRITEを独立して指定回数測定 |
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
chmod +x sysbench_cpu_benchmark.sh sysbench_memory_benchmark.sh fio_benchmark.sh iperf3_benchmark.sh
bash -n common.sh sysbench_cpu_benchmark.sh sysbench_memory_benchmark.sh fio_benchmark.sh iperf3_benchmark.sh
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

## 5. CPU・メモリ・fioを個別に実行

`run_all.sh` と旧 `sysbench_benchmark.sh` は廃止しました。各スクリプトが環境情報収集・結果保存・最後のGitHubアップロードまで行います。

```bash
# 1回の試運転（ラベルは任意）
bash sysbench_cpu_benchmark.sh --runs 1 host-pcore4
bash sysbench_memory_benchmark.sh --runs 1 host-pcore4
bash fio_benchmark.sh --runs 1 host-pcore4

# それぞれ10回の本測定
bash sysbench_cpu_benchmark.sh --runs 10 host-pcore4
bash sysbench_memory_benchmark.sh --runs 10 host-pcore4
bash fio_benchmark.sh --runs 10 host-pcore4
```

`--runs` を省略すると `BENCHMARK_RUNS`（既定10回）を使用します。メモリはREAD/WRITE、fioは4種類のI/Oを1セットとして数えます。CPUとメモリは別の実験ディレクトリに保存します。`--help` で使用方法を表示します。

途中で失敗すると停止し、結果はローカルに残ります。最後まで完走しない場合はGitHubアップロードを行いません。

## 6. iperf3を1回または10回実行

サーバー側で起動します（単発終了する `-1` は付けません）。

```bash
iperf3 -s
```

クライアント側：

```bash
bash iperf3_benchmark.sh --runs 1 host-pcore4
bash iperf3_benchmark.sh --runs 10 host-pcore4
```

省略時は `IPERF_RUNS=1` を使用します。1セットはTCPとUDP各30秒です。UDPの目標送信レートは従来通り1 Gbit/sです。

`benchmark.conf` の以下の値でサーバー待機を調整できます。

```bash
IPERF_RUNS=1
IPERF_INTERVAL_SECONDS=10
IPERF_RETRIES=3
IPERF_RETRY_INTERVAL_SECONDS=10
```

TCP→UDP間と各セット間に10秒待ちます。失敗した測定は10秒待って最大3回再試行します（初回を含め最大4試行）。成功した結果だけを通常のJSON名で保存し、失敗した試行のJSONと各試行のstderrも残します。上限を超えると該当回に `FAILED.txt` を保存して停止します。待機や再試行でも、停止中・未起動のサーバー自体は復旧できません。

## 7. 結果の保存先と見方

保存先の例：

```text
~/benchmark/2026-10-14-sysbench-cpu-host-pcore4/
├── metadata.txt
├── system_info/
├── sysbench/
│   ├── run01/cpu/sysbench_cpu_result.txt
│   └── run01/memory/sysbench_memory_read.txt
└── fio/
    └── run01/fio_seq_write.json
```

iperf3専用実行では `iperf3/run01/iperf3_tcp.json` と `iperf3/run01/iperf3_udp.json` が保存されます。

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
