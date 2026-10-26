# 比較・分析用の補完ログ

人間勝利ランの元ログへ、調査で得た選択・対象・状態を追加したJSON Lines形式の資料。判断の比較・分析に使う。各ファイルだけで原本の所在と補完値の出所を確認できる。

このディレクトリの `<run_id>.jsonl` が各ランのログ。ファイル名にはSpire CodexのランIDを使う。

## 読み方

先頭の `record_type: metadata` に元ログID、原本と公開履歴のリポジトリ基準の保存先・公開URL・SHA-256がある。保存先はGit管理外の `local/spire_codex/` 配下。原本を取得し直す場合はURLを使い、同じ内容かハッシュで確認できる。

`record_type` のない行は元の人間ログをそのまま保持したもの。追加行は `record_type: supplement` とし、`source_sequence` で元ログの連番 `s` に結び付ける。

| `origin` | 出所 |
|---|---|
| `source_inference` | 元ログ・公開履歴から推定・補完した情報 |
| `native_reexecution` | 当方の実ゲーム再実行で観測した選択・状態。元ランの未記録値と同一かは未確認 |
| `unknown_original` | 元ランでは記録されず、元の値を確定できない項目 |

`resolved_action` は実行した対象・選択カード・店の購入等を表す。`observed_context` は対応する操作直前の再実行状態。例えば未記録の敵HPを読む場合も、`related_unrecorded_sequences` の効果直後を直接観測した値と取り違えない。`instance` と敵 `id` は `native_segment` 内の再実行個体IDで、元ログのカード `c`・敵 `cid` とは別のID。

元ランにない値を人間の実測値へ上書きせず、分かる値と出所を同じログ内へ置く。追加行を取り除いたバイト列が、先頭に記録した原本のSHA-256と一致するように作成する。
