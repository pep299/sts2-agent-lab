# Mentorを使うChatの操作手順

このファイルを読み、Pythonから同梱のMentor Rustシミュレータを操作する。ゲーム処理に実ゲームDLL、Godot、学習モデル、外部サーバーは使わない。ユーザーの明示指示は、この文書の進行・表示の既定値より優先する。

## 起動

1. artifact ZIPを展開し、`manifest.json`を読む。使用するZIPの取得元とmanifestの`lab_commit`・`mentor_commit`を記録する。
2. `platform`・`architecture`・`python_minimum`が実行環境と合うかを確認する。読み込みに失敗した場合は例外全文を報告する。別エンジンや言語だけの模擬進行で代用しない。
3. ユーザーが指定したゲーム版を使う。指定がなければv0.113.0を要求する。`version_probes`の`accepted`はコンストラクターが受理したという意味であり、全コンテンツの対応完了を意味しない。`null`は未実行なので、実際に`Session.start`して受理結果を記録する。要求版が受理されない場合は停止して報告し、無断でv0.111へ切り替えない。
4. Pythonの検索パスの先頭に展開先を追加し、次の形で開始する。`/mnt/data/mentor-chat`は実際の展開先へ置き換える。

```python
import json
import sys
from pathlib import Path

package = Path('/mnt/data/mentor-chat')
sys.path.insert(0, str(package))
from mentor_chat import Session

session = Session.start(
    game_version='v0.113.0',
    seed=7,                 # ユーザー指定があれば置き換える。文字列seedも渡せる。
    character='Ironclad',
    ascension_level=10,
    act1='roll',
)
state = session.observe()
```

最初の返答で使用ゲーム版・キャラクター・アセンション・seedを示す。**現在Actのマップと、ネオー等のエンシェントの全選択肢を提示して停止する。** この時点では選択や移動をしない。

## 取得・行動

```python
state = session.observe()
actions = state['actions']                 # Mentorが現在提示する行動
act_map = session.rm.act_map()              # [{col, row, point_type, children}, ...]
full_map = session.rm.full_map()
event_options = session.rm.event_option_infos()

# ユーザーまたはChatが選んだ辞書をそのまま渡す。actions[0]を自動選択しない。
chosen = actions[chosen_index]
record = session.act(chosen)
state = record['after']
session.save('/mnt/data/run-active.json')
```

- 通常の進行は必ず`session.act`経由にする。`session.rm`は参照に使い、`take_action`・`force_*`・`debug_*`・`set_player`などを直接呼ばない。戦闘状態は複製なので、`combat_state().apply()`でランを進めない。
- 行動直前の選択肢を取り直す。手札・敵・報酬の添字を、前の行動のまま再利用しない。辞書の項目名と添字はエンジン値を保持する。
- 行動の戻り値が成功以外なら補助スクリプトが例外にする。採用中の状態は更新されない。エラーの行動辞書・例外・直前状態を報告し、その箇所で停止する。
- `observe()`の`combat`は戦闘中だけ入る。終了後のHP等は`record['after']`、敵行動を含む戦闘ログは`record['combat_log']`から取得する。`combat_log_dropped > 0`ならログ欠落を明記する。
- 戦闘中の現在HPは`state['combat']['player']['hp']`、ブロック・エナジーも同じ`player`から読む。`run_hp`と`run_max_hp`はラン側の保持値であり、戦闘中のHPとして表示しない。非戦闘時はラン側の値を使う。
- 新しいイベントの確定は補助スクリプトが行う。`event_options`の本文と有効・無効を読んで提示する。説明が不足する効果を記憶から断定しない。
- カードの効果を確認するときは、手札・選択肢・エンジンが公開する説明を使う。表示だけでは判断できない場合は不明点を示して停止し、追加データが必要な箇所を報告する。
- `manifest.json`の`localization_versions`に要求版がある場合は、`localization/<要求版>/cards.json`・`relics.json`・`potions.json`等から同じ版の名前と説明を参照できる。キーは`BASH.title`・`BASH.description`等。説明中の未解決の`{変数}`を推測した数値で埋めない。要求版の説明がない場合は不足を明記し、v0.107等の別版の説明を同じ仕様として流用しない。
- 学習方策、`random_playout`、`mcts_pick_action`、`surrogate_resolve_combat`で自動進行させない。判断はChatが行い、ルールの適用はMentorが行う。

## 停止する場所

- マップの初回提示、エンシェント、イベント、休憩、ショップ、カード・レリック報酬では、選択肢を示してユーザーの選択を待つ。既に選択やルートが指定されている範囲は実行してよい。
- 「次の戦闘」と言われたら、指定ルートに沿ってその戦闘を進め、終了後に内容と報酬を提示して停止する。途中に未指定のイベント・休憩・ショップがあれば、その選択前に停止する。
- 戦闘中のカードと対象はChatが選んで進める。戦闘内のカード選択も含む。ターン数の短縮だけで判断せず、被ダメージと消費する資源を考慮する。
- ポーションはユーザーが許可した範囲で使う。許可がない状態で使用したい場合は、使用案と温存案を提示して停止する。
- 先の階や次の戦闘へ、ユーザーが指示した範囲を超えて進めない。

## 表示する内容

### マップ

`act_map()`または`full_map()`のノードと接続をそのまま使い、列・行・部屋種別・接続線・現在地が読める画像を表示する。列番号はエンジンの`col`値で統一する。隣接しているという理由で接続線を補わない。

画像表示ができない場合は、その旨とノード・接続の表を示す。「表示した」とだけ返したり、ユーザー側から開けないローカルパスだけを返したりしない。ルート提案では踏む部屋を順に列挙し、休憩やエリートの数を画像と照合する。

### 戦闘

1. 開始時：階、敵全員のHP・ブロック・状態・意図、自分のHP・ブロック・エナジー・状態、デッキ、レリック、ポーション。
2. 各ターン：開始手札の全カードと現在コスト、敵の意図、プレイ順・対象・ドロー・ダメージ・ブロック等の結果、実際の敵行動、ターン終了時のHPと資源。プレイ中に追加ドローしたカードも示す。
3. 終了時：ターン数、HP変化、使用したポーション、残った資源、報酬の全選択肢。ペット等のHPが取得できない場合は未取得と明記する。

数値・ドロー・発生した効果は`session.history`内の`before`・`after`・`combat_log`を根拠にする。開始からの履歴がない戦闘を、結果だけから再構成しない。不明な挙動をゲーム仕様として断定しない。

## やり直し・比較

ユーザーが指定した時点を、`session.history`の行動番号と状態に対応させる。`after_steps=N`は「先頭N行動を実行済みの地点」で、0は開始直後。

```python
session.save('/mnt/data/run-original.json')
trial = session.fork(after_steps=2)  # 実際の分岐地点へ置き換える
# trial.observe()['actions']から別案を選び、trial.act(...)で進める
trial.save('/mnt/data/run-trial.json')
```

比較中は`session`を置き換えない。比較結果として開始条件、変更行動、終了地点、HP・消耗品・デッキ等の差を示す。ユーザーが別案を採用したら`session = trial`とし、`run-active.json`を保存して、採用した分岐を明記する。

## 保存・再開

各選択・戦闘終了・分岐採用後に保存し、返答の末尾で採用中の保存JSONへのダウンロードリンクを渡す。

```python
session.save('/mnt/data/run-active.json')

# 新しいPython実行環境で、元のartifactを展開してパスを追加した後
session = Session.load('/mnt/data/run-active.json')
state = session.observe()
```

保存JSONは実行ファイルを含まない。開始時のartifact ZIPもユーザーが取得できるリンクを渡し、保存JSONと一緒に保管するよう伝える。GitHub上の古いartifactは削除・期限切れになり得るので、最新artifactだけで過去ランを再開できるとは扱わない。

再開は記録済みの行動を同じ拡張と補助スクリプトで再生する。ハッシュ不一致や再生の分岐を検出したら停止して、例外全文と元のartifactが必要であることを報告する。新しい版への保存移行や、HP等の書き換えで辻褄を合わせない。

## 対応状況

このパッケージはv0.113のゲーム挙動の完全対応を保証しない。`version_probes`は起動受理の確認だけである。特にMentor側のWuppy戦闘処理等は、対応済みかを別途確認する必要がある。効果が実装されていないものをChat側で足し算して補わず、不足するエンジン処理として報告する。
