# v0.111 イベント操作・観測・Mentor接続

更新: 2026-10-26。

登録65イベント（通常57・エンシェント8）と終盤専用TheArchitectについて、洗い出した操作接続の不足を修正した。両環境で公開候補から後続選択・戦闘・報酬・終了まで検査した。対象はソロIronclad・A0。全状態の組合せ、自然出現率、判断の最適性、全ラン勝率の認定ではない。

## 実装の責務

```text
v0.111実ゲームの処理
  ├─ learn: GameHost / Recorder（Godot互換環境）
  └─ native: 実UI・コマンド・画面ハンドラー
             ↓ 公開状態・合法候補
backend adapter → 共通STS2観測
             ↓
sts2/selection.py: 公開した親イベント・取得レリックから子選択の効果を保持
             ↓
agents/mentor: PPO採点 / 戦闘MCTS / 明示した固定・代理方策
             ↓ 行動ID・選択indices
backend adapter → 実ゲームの処理 → 次の公開境界

tests/events: 診断状態へ直接入場し、イベント分岐を強制して上記経路を検査
```

backendはレリックから戦略を推測しない。ドメイン層はモデルを呼ばない。Mentorはbackend固有の候補番号を推測しない。fixture（診断用初期状態）の設定・専用操作は通常方策の入力から除外する。元の効果を独自の結果で置き換えず、ゲームの購入・カード変更・戦闘・報酬処理を使用する。

## 修正内容

| 対象 | 変更と確認範囲 |
|---|---|
| Fake Merchant | 閉店・開店・閉じる・退出を別操作にし、開いた在庫だけを公開。資金不足、複数購入、在庫更新、閉じて再開、通常店の回帰を確認 |
| Foul Potion | 実ポーション使用から店の戦闘へ遷移し、古い店境界を返さない。合法な戦闘・報酬取得でMapへ復帰。未購入の偽物レリックとRugを保持。高HP合成状態での撃破は強さの証拠にしない |
| Crystal Sphere | 開閉マップで正解マップをマスクし、開いたセルの座標と内容だけを公開。未開セルは座標のみ。内容はempty/gold/potion/card_reward/relic/curse。実クリックと報酬完了を待つ。AnyTimeポーションと破棄も合法候補として保持 |
| 致死候補・Trial | learnでも合法な致死候補を除外しない。実際の放棄・死亡まで進行。nativeは終端昇格後の旧選択context・候補を消し、中断中の効果へ戻さない |
| TheArchitect | 最終Actから実WinRunを呼び、HP0でもvictoryと記録。RunManager.OnEndedの最初の結果をrunごとに保持し、後続の死亡通知で上書きしない |
| 子カード選択 | 通常イベントの公開親キーと公開レリックから用途を解決。GraveのSOULS_POWER、PAELS_GROWTHのCLONE等を補完。未知の親は停止を維持 |
| 任意取得・カード束 | 0枚選択、複数取得、束選択を接続。learnの旧CardViewと完全投影の違い、nativeの束ラッパーと汎用画面名の違いを実入力で検出・修正 |
| 報酬からの選択 | 公開RelicRewardのrelic_idを親として継承。NEOWS_BONES→LEAD_PAPERWEIGHT/POMANDER→Mentorの子選択→Mapを実確認 |
| カードの公開数値 | 付与後に古い表示キャッシュを読んでいたlearnの投影を修正。DynamicVarSetのコピーへ実ゲームのpreview処理を適用し、元変数・乱数を保持。nativeにも適用 |
| 既存driver | C# AutoPlayerのFake閉店停止、Python学習例のCloseShop/OpenShop循環を再現・修正。通常店と既存採点順位を保持 |
| 通常ショップ取得時選択 | Dollyのcopy、Hammer/Kifuda/Punch/Royalの付与名を親の購入情報から継承。learnは購入Taskを子選択中も保持し、選択後の実効果・在庫消費まで待つ。カード除去の購入完了処理にも同じ追跡を使用 |

## 方策として固定・近似している部分

| 判断 | 現在の方式 | 評価していないこと |
|---|---|---|
| 固定枚数のカード選択 | 既存PPOの単カード採点から必要枚数の上位を選ぶ | 組合せの相互作用、返還効果、付与量の価値 |
| 0〜N枚の取得 | 同じcard_reward推論でskipより高い候補を上限まで取得。同点はskip | 複数枚同時取得に最適化した学習 |
| CLAWS / Hammer / Kifudaの枚数 | 最大合法枚数を選ぶ固定規則。対象順位だけ既存transform/enchant採点 | 変化・付与を前提にした枚数・対象の最適性 |
| Dollyの複製対象 | 既存grant採点による代理評価。診断sourceはppo_copy_via_grant_proxy | 複製専用のモデル・学習 |
| SCROLL_BOXES | 同じ推論内の単カードgrant対数確率を束ごとに平均する代理採点 | 専用の束モデル、束全体の相乗効果 |
| Crystal | 公開セルの内容と既知形状から全合法配置を仮説化し、範囲が一意のものだけ採用。既知呪いの完成回避→報酬完成数→報酬への進捗→新規セル数。道具同点は現道具、座標同点は行・列順 | 同型が並ぶ場合の境界推定、報酬種類ごとの価値、最適な先読み |
| 店・ポーション | 閉店時は在庫を開く。Mentorは閉じる操作と戦闘外ポーション使用・破棄を選ばない | 戦闘外ポーションを使う戦略。合法候補自体はbackendから消さない |

いずれもエラー時の先頭候補代替ではない。固定規則・代理採点を診断のsourceへ明記する。Mentor実行のselection_fallbackは全検査でfalse。MentorのRustエンジン・ニューラル重みは変更していない。

## 検証結果

生ログ・失敗時の記録・再検査はGit対象外のlocal/に保持する。再検査で元の失敗を上書きしていない。経路数には同じ状態からの別選択を含むため、独立した自然ラン数ではない。

completedはイベント退出後のMapまたは実終端へ到達し、ホスト終了検査も通ったこと。Mapで検査を打ち切ったnativeランはoutcome=interrupted・dataValid=falseとなる。これらの記録は自然完走ランとして学習へ渡さない。

| 検査 | 結果 |
|---|---|
| 登録65件の基本走査 | learn162経路completed＋ポーションなしFutureのno_public_decision。native163経路completed。接続fault/limitなし |
| 条件付き状態 / learn | 14条件28経路＋Exhaust2候補の2経路が完了。さらにPower2候補3経路で実カード選択を確認 |
| 価格の両側 / learn | 18条件39経路完了。Waterlogged55/99、Zen125/250、Tea50/150、Wongo100/200/300の直前・丁度で合法候補が全一致 |
| 条件付き状態 / native | 18条件40経路中のStone HP6失敗を修正。同じ致死枝・HP7・通常選択・Architectの8経路で再確認。Power2候補の3経路も完了 |
| Ancient・Trial・Tinker / learn | 19設定64経路中のSCROLL1失敗を修正。同seed3経路を再検査し全対象が完了 |
| Ancient・Trial・Tinker / native | 16設定53経路中のNeow4失敗を修正。同seed6経路とBattlewornDummy3経路を再検査し完了。12対象の提示欠落なし |
| 報酬→カード選択 / learn | EVSEED0087のNEOWS_BONESで公開報酬の親ID→grant/upgrade→現Mentor→Map、exit0・回収済み |
| 公開数値の比較 | 基本走査で149経路の記録フィールドが一致。付与値が異なった5経路を原因修正後に同入力再生し5/5一致 |
| 通常ショップの追加検査 | native5種は実購入→Mentor子選択→効果・在庫消費→Map。learnは5種＋任意0枚の2件で同処理を確認し、別出力の7件で公開MoveToから次の戦闘部屋への実入場まで確認 |
| Crystalの公開内容による実接続 | nativeは3判断で実Weak Potion取得後Map、learnは14操作で実報酬を経てMap。両環境で全Crystal境界の未開セル＝座標のみ、開セル＝座標＋content、盤面の完全分割を検査 |
| Python回帰試験 | Mentor69、STS2共通6、learn24、native19、transport8、イベント30の計156件通過 |
| C#回帰試験 | Shop10、既存Crystal3、公開セル投影12、既存Bundle1、既存CardOrRelicSet3の計29件通過。外側の部屋Taskが残る場合にも、購入の束選択・カスタム報酬は購入Taskを先に再開して在庫を確定する |

基本走査のFutureはポーションなしでIsAllowed=false。nativeの単一PROCEEDとlearnの自動Mapは終了UIの差であり、昇格効果の検証には数えない。2ポーションを持つ3構成で別途検査した。通常登録外TheArchitectを基本走査がunsupported_fixtureとする行は、専用Act3検査と区別する。

比較全体を「全件一致」とはしていない。Neowの3経路はnativeの再入場による階・回復がlearnと異なる。DollRoomの5選択列はID.titleと翻訳済み名のキー差で自動対応できず、両側10行のmissing_caseになる。これらを効果不一致や一致へ勝手に分類しない。付与値5経路の再比較にも他158経路のmissing_caseがあり、5経路だけの局所一致である。

証拠（リポジトリ相対）:

- 基本走査: local/events/learn-final-sweep-20261026/summary.json、local/native_headless/results/event-final-sweep-20261026/summary.json。
- learnの条件・価格: local/events/learn-conditional-20261026/scenarios.json、local/events/learn-grave-two-20261026/summary.json、local/events/learn-prices-20261026/scenarios.json。
- native条件と再検査: local/native_headless/results/event-conditional-20261026/scenarios.json、local/native_headless/results/event-terminal-recheck-20261026/scenarios.json、local/native_headless/results/event-selfhelp-two-powers-20261026/summary.json。
- 追加選択: local/events/learn-ancient-conditional-20261026/scenarios.json、local/events/learn-bundle-recheck-20261026/summary.json、local/native_headless/results/event-ancient-conditional-20261026/scenarios.json、local/native_headless/results/event-final-recheck-20261026/scenarios.json。
- 報酬の親継承: local/events/learn-bones-card-child-20261026-001/verification.json。
- 比較: local/events/compare-final-sweep-20261026.json、local/events/learn-enchantment-replay-20261026/compare-existing-native.json。
- 試験: local/events/final-python-tests-20261026.log、local/events/learn-driver-compatibility-final-20261026.json。
- native最終集計・元失敗と再検査の対応: local/events/native-final-verification-20261026.json。
- 静的調査: local/events/ancient-public-choices-review-20261026.corrected.json、local/events/random-relic-closure-review-20261026.json。
- 通常ショップ5種: local/events/learn-shop-five-verification-20261026.json、local/events/native-shop-five-verification-20261026.json。Dolly複製1枚、HammerのSHARP3を3枚、KifudaのADROIT3を3枚、PunchのMOMENTUM5、RoyalのROYALLY_APPROVED1を実カードinstanceで照合。learnのHammer/Kifudaは0枚も購入完了を確認。
- learn通常ショップの実退出: local/events/learn-shop-exit-verification-20261026.json。
- Crystal公開セルの実接続: local/events/native-crystal-masked-verification-20261026.json、local/events/learn-crystal-contents-completion-20261026/report.json。nativeのこのseedで観測した分類はempty/potion/card_reward。全6分類は実アイテム変種を使ったC#検査で確認。
- 公開内容の回帰: local/events/crystal-content-python-tests-20261026.log、local/events/learn-crystal-cell-content-tests-20261026.log。C#は未開Itemや全Items・実原点・サイズ等のgetterが呼ばれると失敗する試験を含む。Pythonは未開内容の変更に対する入力・判断不変、gold/potionの大きさの曖昧性、同型隣接の保留を確認。
- 購入の親Task順序: local/events/learn-shop-parent-order-repro-affordable-20261026.log、local/events/learn-crystal-shop-parent-fixed-20261026.log。実SCROLL_BOXES/Orrery購入と、部屋退出を待つ未完了Taskを使った回帰。旧順序のTimeoutを再現し修正後に通過した。自然ランの復元で同じ故障が発生したと主張する検査ではない。

### Crystalの公開セルと正解マップの境界

両backendは同じCrystalSphereProjectionを使う。各セルのIsHiddenを先に確認し、開いたセルだけItemの型から内容を取り出す。hiddenCellsは{col,row}、revealedCellsは{col,row,content}で、contentはempty/gold/potion/card_reward/relic/curse。画像資産・描画・画像辞書・追加の起動設定は不要。

環境は正解配置を保持するが、未開セルの内容、盤面全体のItems一覧、個体ID、アイテムの原点・全体サイズ・rarityは出力しない。開いたセルの内容を知ることと、そこに触れるアイテム全体の配置を知ることを区別する。未知の公開型はemptyへ代替せず明示的に停止する。

Mentorのcrystal.pyは公開セルの内容だけを使用する。既知の形状について、空セルを含む全公開内容に矛盾しない配置を列挙し、境界を一意に推測できる場合だけ採点へ使う。金は1×1/2×1、ポーションは1×3/2×2の両候補を残す。同型の隣接セルを同一アイテムと断定しない。曖昧な部分には新規セル数の基準を使う。inference.inferredItemsとselectedScoreが推測と選択の診断情報であり、環境から得た正解範囲ではない。

この観測は、開いたセルの中身を直接扱う記号表現である。スクリーンショットの断片から種類が判別できるかを再現する入力ではない。未開セルの内容を学習入力・方策へ渡さないことを検査する。

### 追加選択を提示する再現条件

全てHP40/最大80/gold100、追加fixtureなし。seed接頭辞はEVSEED。

| イベント | seed番号 | 実行した対象 |
|---|---|---|
| Tanx / Orobas | 0000 | CLAWS / SEA_GLASS |
| Neow | 0001 | POMANDER |
| Neow | 0004 | SCROLL_BOXES、HEFTY_TABLET |
| Neow | 0007 | LEAD_PAPERWEIGHT |
| Neow | 0023 | NEOWS_BONES |
| Tezcatara | 0000 / 0007 | BIIIG_HUG / YUMMY_COOKIE |
| Darv | 0005 | EMPTY_CAGE |
| Pael | 0005 / 0008 | PAELS_TOOTH / PAELS_GROWTH |
| Trial | 0001 / 0004 | NOBLE / NONDESCRIPT。それぞれGUILTY/INNOCENTを実選択。MERCHANTは既存EVENTCOVER111 |
| TinkerTime | 0000 / 0001 / 0004 | 既存EVENTCOVER111と合わせ、3type・9riderを実選択 |

learnの12対象は、除去枚数、強化枚数、CLONE量4、CLAWSのMAUL6枚、取得indicesに対応する追加枚数、束3枚、報酬レリック2個を公開後状態で局所照合した。HEFTY_TABLETは取得カードに加えて必須INJURYがある。v0.111のSCROLL_BOXESにgold費用はない。旧版Mentorの説明を対象版仕様に置き換えない。証拠: local/events/learn-ancient-effect-checks-20261026.json。

## 母数・根拠・残る制限

- tests/events/catalog.jsonは対象DLLのModelDb登録から作成。optionStringLiteralsは合法分岐数ではない。基本型・非推奨・Mockは除外。
- エンシェントの直接候補102種を対象版資料と実DLLで確認。全300レリックの選択API呼出しも静的照合した。Shop限定のDOLLYS_MIRROR、GNARLED_HAMMER、KIFUDA、PUNCH_DAGGER、ROYAL_STAMPは通常ショップで別途実購入検査した。Fake Merchantは専用の偽物9種から6種であり、この5種を含まない。
- IsAllowedの記録と直接入場は、自然生成のpool・epoch・既出イベント条件の検査とは別。WarHistorianRepyは登録されるが対象DLLのIsAllowedはfalse。マルチプレイ、他キャラクター、他Ascension、全デッキ/乱数結果は未検証。
- Crystalは開いたセルの内容を投影する。未開セルの内容・同型セル間の個体境界を実装から取得しない。全配置・全状態組合せの操作検証ではない。
- 現PPOはv0.111語彙を拡張した旧重み。対象版向け学習なし、新ID埋め込みは旧未知IDからの初期値。操作の通過は、効果をモデルが正しく評価する証拠ではない。
- 物理的に別個の同IDカードの価値差、全カード・対象別の戦闘preview、終了済み保存のWinTime=0からの勝利復元は未検証。
- 既存EventOptionSweepはChooseEventOptionだけを数え、shop面を網羅しない。今回の専用検査の代用にしない。
- 基本走査後の終端・束・表示値の修正は該当経路と通常戦闘で再検査した。最終ビルドの実行検証範囲はその追加・再検査に限られ、基本全経路の再走査はしていない。

## 固定断面と再実行

- ゲームDLL SHA-256: 9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4。
- PPO SHA-256: b8bb1c85a497598bfa3430ad14b9bf5ca2335c7f3cf4b81101527098ceaa76c8。拡張build: f79727f1fd49a8e22e8403084b1a82210c82b2ae。
- learnの最終Gitlinkは8cec593。ショップ5種、購入Task順序修正、Crystal公開セル形式の実接続では実行断面が異なるため、各記録のruntime/source hashを参照する。元GHQ cloneは変更していない。公開セル形式ではRecorder・TUI・fixtureのビルドも確認した。
- tests/events/run.pyの各case.jsonにsource hash、実際の初期状態、policy identity、入力・後状態・終了情報を保存。専用probeの記録形式は個別のverification/reportを参照する。fixture=true・expertData=falseであり、教師データへ混ぜない。

```bash
# 既存のローカル環境設定を使用。モデル・runtimeの準備は別に行う。
uv run --offline --no-project python -B tests/events/run.py \
  --backend native --catalog tests/events/catalog.json \
  --events Neow --seed EVSEED0004 --output local/native_headless/results/new-neow-check

# learnは --backend learn と、既存dotnet/ホスト出力を明示する。
# 条件付き状態は --fixture tests/events/fixtures/<name>.json、HP/goldは個別引数。
# TheArchitectは --include-special --events TheArchitect とact-three.jsonを指定する。
```

検査後、共有専用アプリのmodを開始前の正確なバイト列へ戻した。mainのmanifest・ソースは変更していない。通常入口でNeow、diagnosticFixture=false、exit0、回収済み、未確認エラー0を確認した。最終証拠はlocal/native_headless/runtime-restoration-crystal-masked-20261026.json。このブランチのnativeコードを再実行する際はnative-buildでこの断面へ切り替える。最終fixture DLLはlocal/native_headless/fixture-runtime-crystal-masked-20261026へ保存。元のイベント検査と追補前の復旧記録もlocal/内に保持する。

新しいゲームアプリのコピー・ランタイム導入はない。コードと文書のみローカルコミットし、push・PR作成・mainへの統合はしていない。
