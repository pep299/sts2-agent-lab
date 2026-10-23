# learn DLL環境

Python 3.11以上、learnの`global.json`を満たす.NET 9 SDK、Mac arm64 v0.111.0の管理DLLが必要。公開観測アドオンの対象はソロIronclad A0。

```bash
make learn-deps
make learn-build LEARN_GAME_LIBS=/absolute/path/to/data_sts2_macos_arm64
make learn-test
uv run python -m backends.learn_dll.batch --help
```

`LEARN_DOTNET`・`PYTHON`で導入済み実行ファイルを指定する。`LEARN_GAME_LIBS`は既存DLLの参照先で、アプリを複製しない。

`--policy-command`を最後に置き、その後ろにJSON Lines方策のコマンドを指定する。Mentorは`uv run python -m agents.mentor`で呼び出す。結果は`local/learn_dll/results`へ保存する。`seeded_all_unlocked`は全解放状態であり、所有者プロフィールの再現ではない。
