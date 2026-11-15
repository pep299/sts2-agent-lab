# ChatでMentorを使う

artifactの取得先を渡すかZIPを添付し、次を指示する。

```text
artifact内のREADME.mdに従ってランを開始して。
v0.113.0、アイアンクラッド、A10、seed=7。
まずマップとエンシェントの全選択肢を見せて止めて。
```

再開する場合は、開始時と同じartifact ZIPと保存JSONを渡す。

```text
README.mdに従い、添付の保存JSONを再開して。
現在地、HP、デッキ、レリック、ポーション、選択肢を示して止めて。
```

## Chatの操作手順

Chatが行動を判断し、Mentorがゲームルールを適用する。以下の進行・表示の既定値よりユーザーの明示指示を優先する。

### 起動

artifactを展開し、Python 3.11以降から同梱の拡張を読み込む。`manifest.json`にはビルド元コミットと拡張・補助コードのハッシュが入る。

```python
import sys
from pathlib import Path

package = Path('/mnt/data/mentor-chat')  # 実際の展開先へ置き換える
sys.path.insert(0, str(package))
from mentor_chat import Session

session = Session.start(
    game_version='v0.113.0', seed=7, character='Ironclad',
    ascension_level=10, act1='roll',
)
state = session.observe()
```

開始条件はユーザー指定に置き換える。文字列seedも渡せる。起動時に要求版が拒否されたら例外全文を報告し、別版で進めない。

最初にゲーム版・キャラクター・アセンション・seed、現在Actのマップとエンシェントの全選択肢を提示し、選択・移動前に停止する。

### 取得・行動

```python
state = session.observe()
actions = state['actions']
act_map = session.rm.act_map()  # ノードのcol・row・point_type・children
full_map = session.rm.full_map()

chosen = actions[chosen_index]  # ユーザーまたはChatが選んだ行動
record = session.act(chosen)
session.save('/mnt/data/run-active.json')
```

- 進行には`session.act`を使い、`session.rm`は参照に使う。`take_action`・`force_*`・`debug_*`・`set_player`を直接呼ばない。`combat_state()`は複製なので、その`apply()`ではラン本体を進められない。
- 行動の直前に選択肢を取り直す。手札・敵・報酬の添字を前の行動から再利用しない。
- 戦闘中の現在HP・ブロック・エナジーは`state['combat']['player']`から読む。`run_hp`・`run_max_hp`は非戦闘時に使う。
- イベントは`state['event_options']`、休憩は`rest_options`、報酬は`card_reward`、ショップは`shop`を読む。カード削除・強化等の追加選択肢は`session.rm.card_removal_options()`・`smith_options()`等を参照する。
- 名前と説明は、要求版と同じ`localization/<ゲーム版>/cards.json`・`relics.json`・`potions.json`等を参照できる。キーは`BASH.title`・`BASH.description`等。未解決の`{変数}`を推測した数値で埋めず、別版の説明を流用しない。
- 操作例外や未対応処理は、行動辞書と直前状態を添えて報告し、そこで停止する。ゲーム効果をChat側で補って進めない。
- 学習方策や`random_playout`等に進行を任せず、各行動をChatが選ぶ。

### 停止する場所

- 初期マップ、エンシェント、イベント、休憩、ショップ、カード・レリック報酬で選択肢を提示して停止する。既に指定された選択やルートの範囲は実行してよい。
- 「次の戦闘」では、その戦闘を進めて終了後に内容と報酬を示す。途中に未指定のイベント・休憩・ショップがあれば選択前に止まる。
- 戦闘中のカード・対象・カード選択はChatが判断する。ターン数の短縮だけで決めず、被ダメージと資源の消費を考慮する。
- ポーションは許可された範囲で使う。許可がない状態で使いたい場合は、使用案と温存案を提示して止まる。

### 表示する内容

マップはエンジンのノードと接続から、列・行・部屋種別・現在地が読める接続線付き画像を表示する。列番号は`col`値で統一する。画像を表示できなければノードと接続の表を示す。

戦闘では次を示す。

1. 開始時：自分と敵全員のHP・ブロック・状態・意図、エナジー、デッキ、レリック、ポーション。
2. 各ターン：開始手札の全カードと現在コスト、敵意図、プレイ順・対象・追加ドロー・効果、実際の敵行動、終了時HPと資源。
3. 終了時：ターン数、HP変化、使用ポーション、残り資源、報酬の全選択肢。

根拠は`session.history`内の`before`・`after`・`combat_log`。`after['combat']`は非戦闘時には入らない。戦闘終了時の敵行動や効果は行動記録の`combat_log`を読む。`combat_log_dropped > 0`なら欠落を明記する。取得できない値や履歴を、結果から再構成しない。

### 分岐・保存再開

```python
session.save('/mnt/data/run-original.json')
trial = session.fork(after_steps=2)  # 指定地点までに実行した行動数
# trial.observe()['actions']から別案を選び、trial.act(...)で進める
trial.save('/mnt/data/run-trial.json')
```

0行動は開始直後。比較中は元の`session`を保持し、変更行動・終了地点・HP・消耗品・デッキの差を示す。別案の採用が指示されたら`session = trial`とし、採用中の保存JSONを更新する。

再開は、元のartifactを読み込んだ後に行う。

```python
session = Session.load('/mnt/data/run-active.json')
state = session.observe()
```

選択・戦闘終了・分岐採用後に保存し、返答で採用中の保存JSONへのダウンロードリンクを渡す。開始時のZIPへのリンクも渡し、**ZIPと保存JSONを両方保管**するよう伝える。公開artifactは更新時に削除されるため、保存JSONだけでは元の実行ファイルを取り戻せない。

再開は同じ拡張・補助コードで行動履歴を再生する。バイナリの不一致や再生結果の分岐を検出したらエラーを報告し、元のartifactで再開する。HP等を書き換えて合わせない。
