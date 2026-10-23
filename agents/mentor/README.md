# Mentor方策

Spire Mentorの配布ONNX方策で経路・イベント・カード取得・店・休憩・宝箱・エンシェントを選び、戦闘は公開観測を再構成してMonte Carlo Tree Search（MCTS）で選ぶ。学習処理は含まない。対象はv0.111.0・ソロIronclad A0。

## 準備

Python 3.11以上、Mentorの`sts2-rs/rust-toolchain.toml`が指定するRustとCargo、C/C++ビルド環境を使用する。Python側は標準ライブラリのみ。推論にPyTorch・maturinは不要。以下はリポジトリルートで実行する。

```bash
make mentor-setup
make mentor-build
make mentor-test
```

`MENTOR_PYTHON`・`MENTOR_CARGO`で導入済み実行ファイルを指定できる。ビルドはCargo.lockを固定し、既定2並列で行う。依存がキャッシュ済みなら`python3 -B agents/mentor/build.py --offline`を使用できる。Rustのツールチェーン管理は各自の環境で行う。

ソースはsubmoduleのcommit、モデルと拡張の識別は`config/mentor.example.toml`で固定する。拡張は`local/mentor/sts2_rs.abi3.so`、ビルド中間物は`local/mentor/target`へ出力する。初回ビルドにはRust依存の取得と数分のコンパイルが必要。モデルはsubmoduleに含まれる。

設定を変える場合は例を`config/mentor.local.toml`へコピーする。省略時はlocal設定、なければexampleを使う。設定内の相対パスはリポジトリルート基準。実行時にモデルSHA256と拡張のbuild_gitを照合する。探索予算は設定の`search`を使用し、指定したCLI引数だけが上書きする。

## native headlessで実行

[実行器](../../backends/native_headless/README.md)の準備・資格確認を先に完了する。この入口はアプリを複製しない。

```bash
python3 -B agents/mentor/run_native.py \
  --seed 6C2W9K5M3R \
  --config config/mentor.example.toml \
  --output local/native_headless/results/mentor-001 \
  --allow-selection-fallback
```

出力先は存在しないディレクトリを指定する。`--seconds`（既定600秒）・`--max-steps`（1500）でラン上限、`--sims`・`--boss-sims`で探索回数を指定できる。方策の1応答には30秒の上限がある。

各ランの結果・公開境界・プロフィールは実行器のresults、判断理由は隣の`*.policy-stderr.log`へ保存する。判断ログにはソースと設定のSHA256、使用予算、PPO確率、MCTSの対応・敵行動の仮定、固定処理を記録する。これらはGit管理しない。方策への入力は公開観測・合法候補・decision_idで、seed・保存データ・内部ホスト状態は渡さない。

## 制限と評価

- 敵の内部行動状態は公開intentとMentorの行動定義から推定する。同じintentの候補が複数あれば仮定をログへ残す。内部状態の完全再現ではない。
- 戦闘子選択は直前行動の再生と公開状態が一致する場合に探索する。比較対象にない内部カウンターの一致までは保証しない。
- `--allow-selection-fallback`は未対応カード選択で必要枚数の先頭を選び、任意なら空を選ぶ。この固定判断の効果を理解したとは扱わない。同フラグでは休憩のHEAL/SMITH以外も除外する。省略時は未対応として停止する。
- 報酬回収・進行は固定処理。ポーション廃棄と非戦闘使用は行わず、満杯時のポーション報酬はスキップする。
- ペット、方向・付与元・対象付きpower、一部特殊カード状態などは未対応として停止する。任意seedを走破できる保証はない。

CIはゲームを必要としない公開観測の変換・探索状態の再生・通信期限の回帰試験を行う。実ゲームでの完走確認とは別に扱う。seedを選んだ少数の勝利を勝率の推定に使わず、障害・中断も含めて評価する。
