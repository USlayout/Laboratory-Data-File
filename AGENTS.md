# 研究データ解析指示

## 研究目的
Host、Docker、KVM、KVM上のDockerにおける
性能差および性能差が生じる要因を調査する。

## 解析対象
- CPU（sysbench）
- メモリ（sysbench）
- ストレージ（fio）
- ネットワーク（iperf3）
- PコアとEコアの性能差

## 名前について
- Host
- KVM
- Docker
- DOK Docker On KVM

## 解析手順
1. 測定データとグラフを確認する。
2. 平均値、中央値、標準偏差を確認する。
3. 環境間の相対性能を算出する。
4. 不自然な性能差や異常値を抽出する。
5. 測定スクリプトと設定ファイルを確認する。
6. 異常が発生した原因の仮説を立てる。
7. 測定条件の改善案を提示する。
8. 再測定すべき項目を整理する。

## 重点調査項目
- PコアとEコアの性能逆転
- 仮想環境における極端な性能低下
- メモリとCPUキャッシュの影響
- CPUアフィニティとCPUピニング
- ストレージキャッシュの影響
- ネットワークの測定条件

## 解析場所
- D:\Laboratory-Data-File\Agent_Analysisの内部のみ
- D:\Laboratory-Data-File\Agent_Analysis\PCore
- D:\Laboratory-Data-File\Agent_Analysis\ECore
- D:\Laboratory-Data-File\Agent_Analysis\scripts

## 解析結果の出力
以下の項目を日本語でまとめる。
- 出力場所D:\Laboratory-Data-File\Agent_Analysis\Analysis_results
- 日付を必ずつけてください
- 発見した問題
- 根拠となる測定データ
- 推定原因
- 原因の確度
- 確認すべきスクリプトと該当行
- 設定の改善案
- 再測定の方法
- 調査の優先度

## 禁止事項
- 測定生データの改変
- 根拠のない原因の断定
- 存在しない測定値の生成
- 許可のない測定スクリプトの変更

## 注意事項
測定事実と推測を明確に区別すること。
確認できない情報は不明と記載すること。