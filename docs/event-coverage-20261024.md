# v0.111 イベント接続の初回走査

65件の登録済みイベントへ両環境で直接入場し、公開されたイベント選択肢とMentorによる後続処理を検査した。全条件の網羅対応は未完了であり、この結果だけで学習中の追加対応が不要とは判断できない。

## 対象と検査の意味

- 対象DLL: SHA-256 `9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`。
- `ModelDb`の実登録は通常イベント57件とエンシェント8件。終盤専用のTheArchitectは通常登録外として別記。基底・非推奨・Mock型は母数から除外した。
- 一覧は`tests/events/catalog.json`。`optionStringLiterals`は一次DLLの文字列であり、生成用prefixやロック表示を含むため合法分岐数ではない。
- fixture（診断用の初期状態）はソロ・Ironclad・A0・Act1/floor1、初期デッキ、Burning Blood、ポーションなし、HP40/80、gold100、seed `EVENTCOVER111`。gold999の追加走査も実施した。
- 初期イベントへの直接入場とHP・goldだけを設定し、選択後のカード変更、戦闘、報酬、死亡は実DLLの処理を使う。自然出現条件の検証ではない。エンシェント入場時の回復などにより実際の初期状態は指定値と異なる場合があるため、前状態も保存する。
- イベント選択肢を順次強制し、カード選択・戦闘・報酬はMentorへ渡す。固定の先頭カード選択による代替は無効。
- `completed`は公開境界がmapまたはterminalへ進み、正常終了したこと。効果の仕様一致、最善手、勝率、全乱数結果の認定ではない。
- 記録は`fixture=true`・`expertData=false`。自然な完走ランの教師データに混ぜない。

## 責務

```text
catalog → 各backendの診断用入口 → 共通の公開状態・合法候補
                                      ↓
                      イベント分岐を強制／後続はMentor
                                      ↓
                         実際の後状態・終了・エラー記録
                                      ↓
                          learn/nativeの記録フィールド比較
```

`sts2/selection.py`は公開された親行動からカード選択の意味を保持する。`agents/mentor/noncombat.py`はその意味をMentorの採点面へ変換する。backendは入力と観測を担当し、診断用入口は通常の方策候補へ渡さない。

## 修正と確認

| 対象 | 修正 | 確認 |
|---|---|---|
| カード選択19分岐 | 一次DLLでremove/transform/upgrade/grant/enchantと付与種類を確認し、公開親キーとの対応を追加 | 未対応だった6イベント14経路、追加のZen Weaverを含む再検査で進行 |
| エンシェント | Mentorの既存ビルダーが読む`relic_id`を渡す | 6種のエンシェントについて実Rustビルダー・配布モデルで候補順を反転して対応確認。通常イベントのレリック候補は従来面を維持 |
| nativeの汎用カード選択 | `FromSimpleGridForRewards`と`FromDeckGeneric`は効果を表さないため、既知の公開親文脈に解決させる | Brain Leech、Room Full of Cheese、Wood Carvingsの失敗経路が進行。未知の親は引き続き停止 |
| native診断ランの死亡 | 直接入場後にゲーム本来の保存APIを使い、死亡時のbackup削除エラーを解消 | Abyssal Bathsの9入力後の死亡、Punch Off・Slippery Bridge・The Lantern Keyの旧失敗経路を再現し正常終了 |
| nativeのTrial | 選択済みの致死`IsProceed`が開く放棄確認だけYesを押し、放棄・死亡まで待つ | REJECT→DOUBLE_DOWN→死亡を実機確認。汎用modalの自動承認やmap強制表示は行わない |
| 検査コード | Trialの非seed参加者番号だけを再生照合で正規化。再生不一致から新規分岐を増殖させない | 本文の他の変化、候補・所持資源・カード変更は照合に残す |
| 比較・終了判定 | summary参照先の欠落・不整合とnative異常終了を失敗にする | 独立レビューの2指摘を再現する回帰テストを追加 |

## 実行結果

各経路の入力、モデル診断、前後状態、実装ハッシュ、終了情報はGit対象外の`local/`へ保存した。以下はその相対パス。

| 記録 | 結果・制限 |
|---|---|
| `local/events/learn-baseline-001/summary.json` | 初回162行: completed150・fault11・終盤専用未実行1。Fake MerchantとポーションなしのThe Future of Potionsは初期mapを旧検査がcompletedと数えたため、対応成功に数えない |
| `local/native_headless/results/event-baseline-001/summary.json` | 初回194行: completed148・fault44・limit1・終盤専用未実行1。faultの31件は同じTrialの表示番号による再生不一致で、31個のイベント欠陥ではない |
| `local/events/learn-repaired-001/summary.json` | 未対応だった6イベントの14経路を修正後に再実行し、14経路completed |
| `local/events/learn-final-pilot-001/summary.json` | gold999、Amalgamator・Brain Leech・Room Full of Cheese・Zen Weaverの9経路completed |
| `local/native_headless/results/event-final-pilot-001/summary.json` | 同条件の上記4種にWood Carvings・Trialを加え、6種16経路completed |
| `local/events/compare-final-pilot-001.json` | 同じ公開選択列で対になる9経路は記録フィールド一致。nativeだけの7経路はmissing_case。比較全体の終了コードは1であり、全件一致とはしていない |
| `local/native_headless/results/event-native-fixes-001/verification.json` | Abyssal BathsとTrialの死亡経路。初期save/backupの実在→死亡後削除、exit0・回収済み・未確認エラー0を確認 |
| `local/native_headless/results/event-death-recheck-001/summary.json` | Punch Off・Slippery Bridge・The Lantern Keyの旧失敗3経路を同じprefixで再実行し、3経路completed |

9経路の比較はHP・最大HP・gold・Act/floor・終了面、デッキの公開コスト/動的値/付与、レリックとカウンター類、ポーションを対象とする。内部処理や未記録の効果の同値性は認定していない。

Python検査127件成功、診断用C#ホストとnative modはビルド警告・エラー0。独立エージェントによるレビュー後に、上記の偽成功を防ぐ2件を修正した。

## 未完了と次の受け入れ条件

| 項目 | 原因・必要な対応 | 次の確認 |
|---|---|---|
| Fake Merchant / learn | `GameHost.CurrentMerchantRoom`、`InventoryFor`、`GameStateProjection.ProjectShop`、Recorderが通常のMerchantRoomだけを店と扱う。実在する`FakeMerchant.Inventory`が公開JSONに出ない。Python adapterだけでは購入対応できない | learn forkで通常店とイベント店の在庫取得を共通化。商品6件、資金不足、購入後の金額/在庫/レリック、複数購入、退出、Foul Potionによる戦闘・未購入レリック報酬、通常店の回帰 |
| Fake Merchant / native | イベント内の専用商店UIを通常の`NMerchantInventory`処理へ接続していない | 同上。候補なしを自動退出や成功扱いにしない |
| Crystal Sphere / 両環境 | nativeは専用ミニゲーム未接続。learnの既存投影には未公開アイテム情報が含まれるためRecorderが意図的に拒否する | 未発掘セル・道具・残回数・実際に見えた結果だけを公開し、合法座標入力と方策を接続。隠れた配置を変えても未公開段階の入力が変わらないこと。ガード削除だけでは不可 |
| 致死イベント候補 / learn | `GameHost.BuildEventOptions`は`IsProceed`と`WillKillPlayer`を除外。nativeで選べるTrial.DOUBLE_DOWNなどが欠落する | 実ゲームの合法性と方策による回避を分け、同一状態で候補を照合し、選択した場合は本来の死亡まで進むこと |
| 条件で出る追加候補 | ポーション、Power/Exhaustカード、変更不可カード、複数レリック、Act2以降などが初期デッキでは満たせない | Stone of All Time/The Future of Potions/Ranwidのポーション、Self Help BookのSwift対象、Grave of the ForgottenのExhaust対象、Relic Traderのレリック5個、出現条件を満たす状態を追加。利用可能/不可の両側を確認 |
| 資金・HP境界と乱数 | gold999は支払可能側であり、全価格境界ではない。1seedの3レリック提示は全エンシェント候補ではない | 支払額の前後、StoneのHP6/7、Trial/Tinkerの別結果、エンシェントの未提示候補を対象に条件を追加 |
| TheArchitect | 通常出現プールに登録されず終盤文脈が必要 | 該当する終盤状態から実行し、終了処理まで確認 |
| Mentorの表現上の限界 | 複数選択は単独スコアの上位k枚（top-k）。StoneやWaterloggedの可変付与量などを配布モデルが十分に表現しない | 操作可能性と判断品質を分離し、必要な入力拡張・別方策を判断。今回の進行成功を高品質な採点の証拠にしない |

learnは調査時のfork commit `1c7212841aa65c44527e435314fc928cecfb2af8`と配布済み公開ホストを使用した。検査後、参照先cloneのビルド出力がなくなったことを確認しており、追加のlearn検査には固定断面のホスト再ビルドが必要。ソースは変更していない。保存済みログにはゲーム・Harness・Recorderのハッシュが残る。

ゲームアプリは追加複製していない。検査中に差し替えた専用アプリのmodは通常mainソース版へ戻し、通常入口でNeow・診断無効・exit0・回収済み・未確認エラー0を確認した。記録は`local/native_headless/runtime-restoration-20261024.json`。このイベントブランチを再検査する際は、同ブランチのソースからmodを再ビルドする必要がある。

次の実装はFake Merchantの在庫共通化と、learnの致死候補差の解消から進める。その後にCrystal Sphereの公開情報設計、条件付きfixtureを追加する。単にイベント名が65件実行されたことを完了条件にしない。
