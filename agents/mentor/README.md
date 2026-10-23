# Mentor

必要環境はPython 3.11以上、`external/spire-mentor/sts2-rs/rust-toolchain.toml`のRust/Cargo、C/C++ビルド環境。実行ファイルをPATHへ通すか、`PYTHON`・`MENTOR_CARGO`で指定する。

```bash
make mentor-deps mentor-build mentor-test
python3 runners/mentor_native.py --help
```

実行には[準備済みnative環境](../../backends/native_headless/README.md)が必要。設定を変える場合は`config/mentor.example.toml`を`config/mentor.local.toml`へコピーする。

`--allow-selection-fallback`は未対応の子選択を先頭の必要枚数で処理し、休憩をHEAL/SMITHに限定する。省略時は未対応として停止する。
