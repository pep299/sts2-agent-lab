# sts2-agent-lab

Slay the Spire 2のAIエージェント開発に向けた調査・実験。

[比較・分析用の補完ログ](data/spire-codex/README.md)は `data/spire-codex/*.jsonl` に置く。各ログ内に元ログの所在と補完値の出所を記録する。

[実ゲームheadless実行器](backends/native_headless/README.md)と、[MentorのDLLホスト](external/spire-mentor/sts2-pycli/README.md)を扱う。Mentorのソースは`external/spire-mentor`で管理する。

Mentorの推論拡張を手元で作る場合は`make mentor-deps mentor-build`、確認済み拡張があれば設定の`paths.extension`へ指定する。方策の設定例は`config/mentor.example.toml`。

ChatでRustシミュレータを操作する方法は[Chat利用手順](chat/README.md)を参照。取得先を一度登録すると「gh artifactからパッケージ取得してラン開始」で起動する。既定値はv0.113.0・アイアンクラッド・A10・ランダムseedで、指定した項目だけ上書きする。GitHub Actionsの`mentor-chat` artifactにPython拡張・手順・保存と分岐の補助・対象版の説明データを同梱する。

```bash
python3 -m agents.mentor --help
python3 backends/native_headless/src/batch.py --help
```

nativeの`--policy-command`へ`python3 -m agents.mentor`を指定して接続する。`--policy-command`は最後に置き、その後ろへ方策の引数を渡す。実行時のログ・ゲーム資産は`local/`に保存する。

nativeのイベント回帰検証は`python3 tests/events/run.py --case <case名> --output local/events/<実行名>`で実行する。固定条件と期待する分岐は`tests/events/cases.json`にある。
