# Ubuntu Webリソースモニター

Ubuntu上で実行し、ブラウザで各論理CPU・メモリ・温度・電力を確認する軽量モニターです。Pコアを上段、Eコアを下段に表示します。HT/SMT有効時は物理コアごとではなく、htopと同じ論理CPUごとのバーです。バーにカーソルを合わせると物理コア・パッケージ番号を確認できます。

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

Ubuntu自身のブラウザから <http://127.0.0.1:8765> を開きます。終了は `Ctrl+C` です。

**別PCから見る場合（LAN内）:**

```bash
python3 monitor.py --host 0.0.0.0 --port 8765
hostname -I
```

ブラウザで `http://UbuntuのIPアドレス:8765` を開きます。UFWが有効な場合は、閲覧するPCだけに許可できます。

```bash
sudo ufw allow from 閲覧PCのIPアドレス to any port 8765 proto tcp
```

このサーバーは認証・TLSを備えていません。信頼するLAN内で使用してください。SSH接続できる環境なら、既定のlocalhost待受のまま、閲覧PCから次の転送も使えます。

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
find -L /sys/class/powercap -name energy_uj -exec ls -l {} \;
```

RAPLは一般ユーザーに読み取りが許可されていないことがあります。電力が必須なら、管理者が**必要な `energy_uj` ファイルだけ**を専用グループへ読み取り許可する運用にしてください。sysfsの権限変更は再起動やドライバー再ロードで戻るため、永続化は対象環境に合わせて設定します。Webサーバーをrootで動かす必要はありません。未対応機種では権限を変えても取得できません。

## メモリ・負荷を抑える設計

- Python標準ライブラリのみ。Webフレームワーク、プロセスごとの収集、外部コマンド実行なし。
- 単一プロセス・単一スレッド。アクセスがない間は計測しません。
- 最新スナップショットと直前カウンターだけを保持。履歴・時系列DB・アクセスログを保存しません。
- 標準2秒更新。複数ブラウザでも最小計測間隔内は同じキャッシュを返します。
- ブラウザのタブが非表示・一時停止中は、そのタブからのポーリングを止めます。
- フロントは素のHTML/CSS/JS。外部ライブラリ・フォント・CDNなし。

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

`resource-monitor.service` を編集し、`ExecStart` のフォルダーを実際の絶対パスに直してください。初期値はlocalhostのみ待受です。

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

模擬proc/sysを使ってCPU差分・分類・メモリ・電力の折り返し・取得失敗からの復帰・HTTP応答を検証します。開発ホストにNode.jsがある場合のみJavaScript構文検証も行います（実行環境へのNode.js導入は不要）。開発環境はWindowsのため、実機Ubuntuでのセンサー取得、ブラウザ描画、RSS測定は別途確認が必要です。

実装日: 2026-11-16。対象: Ubuntu/Linuxリソース計測。実行コマンド・必要環境は上記参照。

仕様の参照先: [Linux /proc](https://docs.kernel.org/filesystems/proc.html)、[Intel hybrid PMU](https://github.com/torvalds/linux/blob/master/tools/perf/Documentation/intel-hybrid.txt)、[hwmon](https://docs.kernel.org/hwmon/sysfs-interface.html)、[powercap / RAPL](https://docs.kernel.org/power/powercap/powercap.html)。
