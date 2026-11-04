# Issue #19 トリアージ

2026-11-04時点。対象は <https://github.com/pep299/sts2-agent-lab/issues/19>。

## 判定と影響範囲

確定不具合として扱い、優先度は高とする。A10の最終Act第1ボス後に通常報酬を生成すると、所持Gold・デッキ・報酬乱数が変わり、第2ボスの勝敗と評価結果を汚染する。依存先の更新だけでIssueを閉じず、配布バイナリと再評価まで追跡する。

対象はMentorの`RunManager`でラン全体を進める実行経路。実ゲームから公開観測と合法候補を受け取る[`agents.mentor`](../agents/mentor/policy.py)は、[提示済みの報酬候補を処理](../agents/mentor/noncombat.py)し、報酬自体を生成しない。後者で得た実ゲームの評価結果まで、この不具合の影響ありと一括判定しない。

## 上流の対応

- 修正は上流の公開スナップショット`86512aa3`に含まれる。Issueが引用する`52bfee16`にも修正は存在するが、そのコミットが導入した修正ではない。
- 最終Act第1ボス後は通常カード報酬を空にし、通常Gold・ポーション生成を呼ばず、レリックの報酬フックを通して第2ボスへ進む。
- 第2ボス撃破時のラン終了と、Act1/Act2の通常ボス報酬は別分岐で維持される。

実装と既存の回帰テスト：

<https://github.com/tfriedel/spire-mentor/blob/92095ad53416808ed234bc0f9cd75aeaa3f4f4b9/sts2-rs/crates/sts2-core/src/run_manager.rs#L2510-L2585>

<https://github.com/tfriedel/spire-mentor/blob/92095ad53416808ed234bc0f9cd75aeaa3f4f4b9/sts2-rs/crates/sts2-core/src/run_manager.rs#L10538-L10682>

## 検証と残作業

既存の`double_boss_first_act3_boss_win_is_not_run_over`と`double_boss_first_act3_boss_win_gives_no_rewards`を、`v0.107.1`と報告条件の`v0.111.0`の両方で実行する。前者は第2ボス撃破時の終了も検証する。通常報酬コールバックが呼ばれず、Gold・カード報酬・報酬乱数が変化しないことを後者で検証する。

forkの統合コミットは`2e5da07698b54d365e97bab49bff4783e739d810`。上記の固定条件テストを含むRust 9,174件が通過し、19件はスキップされた。`check --workspace --all-targets`、`clippy --workspace --all-targets -- -D warnings`、`fmt --check`、`test --workspace --doc`、`wasm32-unknown-unknown`向けの`sts2-workbench-wasm`チェックも通過した。macOS拡張を使う親リポジトリのMentorテスト106件も通過した。

<https://github.com/pep299/spire-mentor/commit/2e5da07698b54d365e97bab49bff4783e739d810>

配布版の更新確認と全ランの再評価は今回のトリアージでは実施していないため、IssueはOpenを維持する。

配布更新後も、以下を残す。

1. 配布された`mentor-chat`のビルドコミットと拡張ライブラリSHA-256を記録し、修正を含むバイナリであることを確認する。
2. seed25を同じキャラクター・A10・ゲーム版・モデル・探索予算で再実行し、第1ボス後の報酬と第2ボスへの遷移を生ログで確認する。
3. 修正済みエンジン上でA10の固定seedパネルを再評価し、旧結果とは別の評価条件として記録する。

原報告にはseed25 JSONLの取得先がなく、今回、記載されたGold増減の原ログとの独立照合はしていない。再評価時はJSONLの所在とSHA-256を残す。旧Artifact `12859363235`は調査時点で取得可能だが、親リポジトリの配布ワークフローは新規配布後に旧Artifactを削除するため、旧条件を再実行するなら更新前の配布物も保存する。

上流の現行Ironcladモデルは`cont300_it1150`へ変更されている。エンジン修正の影響だけを比較するときは旧`cardmods_it850`のモデルとSHA-256を固定する。現行モデルへ同時に切り替えた結果を、不具合修正単独の勝率改善として報告しない。
