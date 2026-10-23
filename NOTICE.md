# 第三者コード

| 対象 | 採用元 | 許諾文 |
|---|---|---|
| `backends/native_headless/mod`のブリッジ基盤 | [spire-jev](https://github.com/liu-x27/spire-jev/tree/f52b17980bbb27046a5c2743d2a367ce42d1308a)、間接派生元[divine-sts2](https://github.com/favet/divine-sts2/tree/7cb715916fc9abfb0281c0adf4939c74468e05a4) | [MIT・Xinyu Liu](THIRD_PARTY_NOTICES/spire-jev.txt)、[MIT・divine-sts2 contributors](THIRD_PARTY_NOTICES/divine-sts2.txt) |
| `mod/shared-public` | [STS2-Tools](https://github.com/Jtshieh/STS2-Tools)を作業したローカル拡張。公開commitそのものではない | [MIT・Jtshieh and contributors](THIRD_PARTY_NOTICES/STS2-Tools.txt) |

nativeブリッジと共有投影は**独自保守**とし、上流HEADへの定期同期・自動更新はしない。公開観測の制限と入力・効果完了の同期を独自に変更しており、上流の挙動を一括で受け入れられないため。

ゲーム対応更新や不具合修正では、上流差分から原因に関係する変更だけを選び、この実行器の回帰試験を通して採用する。採用元のcommitは取り込みcommitに記録する。通信型・描画抑制を含めmod全体がこちらの保守対象となる。

`external/sts2-sim`は独立したsubmoduleで、そちらのライセンスに従う。ゲーム本体・資源・保存データはこのrepoのMIT許諾対象ではない。本プロジェクトはMega Critの公式製品・提携プロジェクトではない。

`external/spire-mentor`は[Spire Mentor](https://github.com/tfriedel/spire-mentor)の固定commitを参照するsubmodule。ソース・配布学習済みネットワークのMIT許諾は同submoduleの`LICENSE`・`NOTICE`に従う。`agents/mentor`はそのRust推論API・モデルを利用する公開観測アダプターで、上流ソースを複製・変更しない。更新時はcommit・モデルSHA・入力対応の回帰試験を揃えて変更する。
