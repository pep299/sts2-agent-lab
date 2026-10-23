# learn DLL実行環境

Godot互換層で実ゲームDLLを動かすlearn-the-spireの公開観測ホストへ接続する。Mentorの判断処理は[共通方策](../../agents/mentor/README.md)を使う。

## 準備・実行

Python 3.11以上、共通方策のRust拡張とモデル、learnの`global.json`を満たす.NET 9 SDKが必要。公開観測アドオンはMac arm64 v0.111.0の`sts2.dll`（SHA256 `9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`）、ソロIronclad A0を要求する。これらはlearn本体全般の制約ではない。

```bash
make mentor-setup mentor-build
make learn-setup
make learn-build LEARN_GAME_LIBS=/absolute/path/to/data_sts2_macos_arm64
make mentor-test learn-test
python3 -B agents/mentor/run_learn.py \
  --dotnet /absolute/path/to/dotnet \
  --config config/mentor.example.toml \
  --seed 6C2W9K5M3R \
  --output local/learn_dll/results/mentor-001 \
  --allow-selection-fallback
```

`LEARN_DOTNET`・`MENTOR_PYTHON`・`MENTOR_CARGO`は導入済み実行ファイルの指定に使う。ビルドは既存の管理DLLディレクトリを参照し、必要なDLLだけを出力へ配置する。アプリの複製、別の`lib/`の作成は行わない。参照一覧はlearnの`Directory.Build.targets`に従い、実物のGodotSharp.dllを参照しない。

`--learn-root`は既定で固定submoduleを使う。別checkoutも指定でき、そのcommitを再現情報に記録する。ソースに追跡済みファイルの未コミット変更があれば停止する。出力先は存在しないパスを指定する。`--seconds`（900秒）・`--max-steps`（5000）でラン上限、探索予算は共通設定を使用し、`--sims`・`--boss-sims`で上書きする。

`make learn-test`は偽ホストによる通信・候補番号・期限・回収の試験で、ゲームは不要。実ホスト自体の回帰試験は次のとおり所有するDLLで行う。

```bash
cd external/learn-the-spire
dotnet test addons/public-observation/public-observation.sln -c Release --no-build
```

## 境界と結果

`learn_observation.py`は公開観測を共通方策の候補表現へ変換する。イベント等の親行動から保持した選択目的を使い、未知の非戦闘選択の目的を候補カードから推測しない。ホストへ渡す操作は直前の合法候補の`nativeOptionIndex`または公開選択候補のカード番号。seed・保存・内部ホストは方策へ渡さない。

`seeded_all_unlocked`でActを生成する。全解放・チュートリアル無効であり、所有者プロフィールそのものの再現ではない。learnのGodot互換層と実Godotの完全な同値性を保証しない。CrystalSphereなどホスト未対応の状態や方策未対応状態での停止は、敗北として数えない。

`local/learn_dll/results`へ`result.json`、判断ログ、ホスト診断、イベント、最後の公開境界、再現情報を保存する。再現情報にはseed・learn commit・ホストと設定のSHA256・使用予算を含む。生ログ・再現情報は非公開入力を含むためGit管理外に置く。成功・敗北・障害・上限中断を区別し、プロセス回収とログSHAを結果へ残す。詳細ログがあるだけで専門家データや実ゲームとの同値性の証拠にはしない。
