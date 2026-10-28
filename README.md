# sts2-agent-lab

Slay the Spire 2のAIエージェント開発に向けた調査・実験。

[比較・分析用の補完ログ](data/spire-codex/README.md)は `data/spire-codex/*.jsonl` に置く。各ログ内に元ログの所在と補完値の出所を記録する。

[実ゲームheadless実行器](backends/native_headless/README.md)と、`external/sts2-sim`の独立シミュレーターを扱う。

[learnの公開観測ホスト](backends/learn_dll/batch.py)にも同じ方策コマンドを接続できる。

Mentorの推論拡張を手元で作る場合は`make mentor-deps mentor-build`、確認済み拡張があれば設定の`paths.extension`へ指定する。方策の設定例は`config/mentor.example.toml`。

```bash
python3 -m agents.mentor --help
python3 backends/native_headless/src/batch.py --help
```

nativeの`--policy-command`へ`python3 -m agents.mentor`を指定して接続する。`--policy-command`は最後に置き、その後ろへ方策の引数を渡す。実行時のログ・ゲーム資産は`local/`に保存する。
