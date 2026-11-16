# Ubuntu Webリソースモニター

Ubuntu上で実行し、ブラウザで各論理CPU・メモリ・温度・電力・プロセス一覧を確認する軽量モニターです。Pコアを上段、Eコアを下段に表示します。HT/SMT有効時は物理コアごとではなく、htopと同じ論理CPUごとのバーです。バーにカーソルを合わせると物理コア・パッケージ番号を確認できます。

## 必要な環境

- Ubuntu / Linux、Python **3.10以上**。Ubuntu 22.04 / 24.04等のPythonで動作する構成です。
- `/proc` と `/sys` が読めること。対象Ubuntu本体で起動してください。コンテナやVMではホストの温度・電力・P/E情報が公開されない場合があります。
- 現行のFirefox / Chrome / Edgeなど。別PCからブラウザで閲覧可能です。
- pip、Node.js、npm、データベース、Dockerは不要です。
- 温度・電力はハードウェア、カーネルドライバー、読み取り権限次第です。未対応は「取得不可」と表示し、CPU・メモリの表示は継続します。

```bash
sudo apt update
sudo apt install --no-install-recommends python3
```

## 起動

このフォルダーをUbuntuにコピーし、その中で実行します。`monitor.py` と `index.html` を同じフォルダーに置いてください。

```bash
cd resource-monitor-20261116
python3 monitor.py
```

引数なしで **`0.0.0.0:8765`（全IPv4インターフェース）** に待ち受けます。Ubuntu自身のブラウザでは <http://127.0.0.1:8765>、別PCでは `http://UbuntuのIPアドレス:8765` を開きます。終了は `Ctrl+C` です。

**別PCから見る場合（LAN内）:**

```bash
python3 monitor.py
hostname -I
```

ブラウザで `http://UbuntuのIPアドレス:8765` を開きます。UFWが有効な場合は、閲覧するPCだけに許可できます。

```bash
sudo ufw allow from 閲覧PCのIPアドレス to any port 8765 proto tcp
```

このサーバーは認証・TLSを備えていません。プロセス名・ユーザー名も表示するため信頼するLAN内で使用してください。SSH接続できる環境なら、Ubuntuで `python3 monitor.py --host 127.0.0.1` としてlocalhostだけに待ち受け、閲覧PCから次の転送も使えます。

```bash
ssh -N -L 8765:127.0.0.1:8765 Ubuntuのユーザー名@UbuntuのIPアドレス
# 閲覧PCのブラウザで http://127.0.0.1:8765
```

## P/Eコアの分類

Intel hybrid PMUの以下のCPU一覧から自動分類します。周波数・CPU番号からの推測はしません。

- `/sys/bus/event_source/devices/cpu_core/cpus` → Pコア
- `/sys/bus/event_source/devices/cpu_atom/cpus` → Eコア

情報がないCPUは「未判別」にまとめます。単一種類のCPU、AMD/ARMなどは必要なら手動指定してください。片方だけ指定した場合も自動分類を使わず、未指定CPUは未判別になります。

このリポジトリのメモにある **P: 0〜7 / E: 8〜19** の構成なら:

```bash
python3 monitor.py --host 0.0.0.0 --p-cores 0-7 --e-cores 8-19
```

CPU番号は対象マシンで確認してください（SMTやBIOS設定で変わる場合があります）。範囲の重複は起動時エラーになります。オフラインCPUは表示対象外です。表示は使用中の論理CPUだけです。

```bash
cat /sys/bus/event_source/devices/cpu_core/cpus
cat /sys/bus/event_source/devices/cpu_atom/cpus
lscpu -e=CPU,SOCKET,CORE,ONLINE
```

## 計測方法

| 項目 | 取得方法 / 意味 |
| --- | --- |
| CPU | `/proc/stat` の差分。guestを二重加算せず、idleとI/O waitを使用率から除外。緑/青=user・nice、黄=system・IRQ・steal、紫=I/O wait。 |
| メモリ | `/proc/meminfo` の `MemTotal - MemAvailable`。再利用可能キャッシュをすべて使用中とは数えません。GiB = 1024³ bytes。 |
| Swap | `SwapTotal - SwapFree`。 |
| 温度 | hwmonの `temp*_input`。なければthermal zone。CPU以外のGPU・SSD等もセンサー名とともに表示。未公開の各コア温度は推定しません。 |
| 電力 | RAPL `energy_uj` の時間差からWを算出。hwmonの `power*_input` / `power*_average` も取得。 |
| プロセス | `/proc/PID/stat` とPIDディレクトリの所有者。CPU%はCPU時間差分 ÷ 経過実時間。RESはRSSページ数 × ページサイズ。 |

### 温度のCore番号について

`coretemp · Core 12` の「12」はハードウェアの**物理コアID**で、画面上の `CPU 12`（論理CPU番号）とは異なります。物理コアIDには欠番があり、SMTの2つの論理CPUに同じ温度センサーが対応する場合もあります。番号を0から振り直すと対応が失われるため、元のIDを残します。

以前はセンサーファイルを文字列順（`temp1, temp10, temp11, ..., temp2`）に表示していました。現在はCPU package → P → E → 未判別を基本に、各グループを物理コアIDの数値順で表示します。`temp1_label` のpackage番号と各CPUの `topology/core_id`・`physical_package_id` が一致する場合、例えば **`P · CPU 0,1 · Core 12 / package 0`** と対応を併記します。対応が確認できないセンサーは元のラベルのまま表示します。[coretemp公式仕様](https://docs.kernel.org/hwmon/coretemp.html)

### htop風プロセス一覧

- PID / USER / PRI / NI / VIRT / RES / THR / S / CPU% / MEM% / TIME / NAME を表示。
- CPU・メモリ・PID・CPU累積時間・名前で並べ替え。PID・ユーザー・名前の検索、実行中（R）の絞り込みに対応。
- 標準50行ずつ描画。25 / 50 / 100行とページ切替が可能です。取得可能な全プロセスをページで閲覧できます。
- CPU **100% = 論理CPU 1個分**。複数スレッドを使うプロセスは100%を超えます。新規プロセスの初回値は差分待ちの `—` です。
- MEM% = RES ÷ 総メモリ。共有ページを含むため、プロセスのRES合計はシステムの実使用量とは一致しません。
- TIMEはプロセスの累積CPU時間（分:秒）、THRはスレッド数、Sは状態（R=実行中、S=待機、D=I/O等の待機、Z=ゾンビ等）です。
- NAMEはカーネル公開のプロセス名（`comm`）で、コマンド引数の全体ではありません。プロセス単位の表示で、個別スレッド行・ツリー・終了操作はありません。
- 読み取り中に終了したプロセスや、`hidepid` 等で読めないプロセスはスキップします。rootでの起動は不要です。

一覧の取得負荷も省きたいときは `python3 monitor.py --no-processes` で無効にできます。

RAPLはCPU package、core、uncore、DRAMなどハードウェアが公開するドメインの値です。**PC全体の消費電力ではありません**。親ドメインと子ドメインは重複するので合算しません。初回は差分待ちです。長時間アクセスがなかった場合も再計測を待ちます。通常のカウンター1周の折り返しは補正しますが、短時間に複数周する状況は識別できません。

温度の確認には任意で `lm-sensors` を使用できます。モニター自体は `sensors` コマンドを呼びません。

```bash
sudo apt install --no-install-recommends lm-sensors
sensors
# Intel CPUでcoretempが未ロードの場合（対応ハードウェアのみ）
sudo modprobe coretemp
```

RAPLの存在・読み取り権限は次で確認します。

```bash
ls -l /sys/class/powercap/
find /sys/devices/virtual/powercap -type f -name energy_uj -exec ls -l {} \;
```

RAPLは一般ユーザーに読み取りが許可されていないことがあります。以下で専用グループとudevルールを登録すれば、RAPLデバイスの生成時にも `energy_uj` だけ読み取り権限を付与できます。Webサーバーをrootで動かす必要はありません。未対応機種では権限を変えても取得できません。

```bash
sudo groupadd -f rapl-read
sudo usermod -aG rapl-read "$USER"
sudo tee /etc/udev/rules.d/99-rapl-read.rules >/dev/null <<'EOF'
ACTION=="add|change", SUBSYSTEM=="powercap", KERNEL=="*rapl*", TEST=="energy_uj", RUN+="/usr/bin/chgrp rapl-read /sys%p/energy_uj", RUN+="/usr/bin/chmod g+r /sys%p/energy_uj"
EOF
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=powercap --action=add
sudo udevadm settle
```

追加したグループはSSH再接続などの新しいログインで反映します。既存端末では `newgrp rapl-read` を単独で実行し、その後に起動してください。モニターが既に動いている場合も再起動します。端末ごとにudevルールを作り直す必要はありません。

```bash
id -nG
find /sys/devices/virtual/powercap -type f -name energy_uj -exec cat {} \;
```

`find -L /sys/class/powercap` はsysfsの循環リンクで警告が出るため、実体のある上記パスを確認に使います。RAPLとRAPL-MMIOが同じ対象を公開することもあり、電力表示の各項目は合算しません。

## メモリ・負荷を抑える設計

- Python標準ライブラリのみ。Webフレームワーク・外部コマンド実行なし。
- 単一プロセス・単一スレッド。アクセスがない間は計測しません。
- 最新スナップショットと直前カウンターだけを保持。履歴・時系列DB・アクセスログを保存しません。
- 標準2秒更新。複数ブラウザでも最小計測間隔内は同じキャッシュを返します。
- ブラウザのタブが非表示・一時停止中は、そのタブからのポーリングを止めます。
- フロントは素のHTML/CSS/JS。外部ライブラリ・フォント・CDNなし。
- プロセス一覧は前回のPID別カウンターと最新一覧のみ保持。終了したPIDのカウンターは次回計測で破棄。個別スレッド・コマンド引数は収集せず、画面は最大100行だけ描画します。プロセス数に応じたメモリ・走査負荷は追加されます。

さらに更新を減らす場合:

```bash
python3 monitor.py --interval 5
```

`--interval` はサーバーの最小計測間隔です。画面の更新設定と比べて長い方がポーリング間隔になります。0.5秒以上を指定できます。起動直後やCPU追加直後は差分の基準がなく、使用率が `—` になる場合があります。

Python本体のメモリは必要です。対象Ubuntuでの使用量は未測定であり、一定のMB以下を保証するものではありません。実際のRSSは別の端末から確認できます。RSS表示単位はKiBです。ブラウザ側のメモリは別途必要です。

```bash
pgrep -af 'python3 monitor.py'
ps -p 上で確認したPID -o pid,rss,vsz,%cpu,etime,cmd
```

## 自動起動（任意 / systemdユーザーサービス）

`resource-monitor.service` を編集し、`ExecStart` のフォルダーを実際の絶対パスに直してください。初期値は `0.0.0.0:8765` 待受です。

```bash
mkdir -p ~/.config/systemd/user
cp resource-monitor.service ~/.config/systemd/user/
editor ~/.config/systemd/user/resource-monitor.service
systemctl --user daemon-reload
systemctl --user enable --now resource-monitor
systemctl --user status resource-monitor
# ログアウト後も動作させ、起動時から開始する場合
sudo loginctl enable-linger "$USER"
```

停止・無効化: `systemctl --user disable --now resource-monitor`

## 検証と範囲

```bash
python3 -m unittest discover -s tests -v
```

模擬proc/sysを使ってCPU差分・分類・メモリ・電力の折り返し・取得失敗からの復帰・プロセスCPU/RSS・PID再利用・温度対応付け・HTTP応答を検証します。開発ホストにNode.jsがある場合のみJavaScript構文検証も行います（実行環境へのNode.js導入は不要）。Windows上のブラウザでは模擬データで表示・検索・並べ替え・ページ切替・実行中フィルターを確認済みです。実機Ubuntuでの追加プロセス機能・温度対応付けとRSS測定は未確認です。

開発時の模擬画面は `python3 tests/preview.py` で確認できます（localhost:8876、実測値ではありません）。

実装日: 2026-11-16。対象: Ubuntu/Linuxリソース計測。実行コマンド・必要環境は上記参照。

仕様の参照先: [Linux /proc](https://docs.kernel.org/filesystems/proc.html)、[Intel hybrid PMU](https://github.com/torvalds/linux/blob/master/tools/perf/Documentation/intel-hybrid.txt)、[hwmon](https://docs.kernel.org/hwmon/sysfs-interface.html)、[powercap / RAPL](https://docs.kernel.org/power/powercap/powercap.html)。
