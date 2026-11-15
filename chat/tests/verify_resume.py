"""別プロセスでの保存再開テストに使う、JSON値による比較。"""

import argparse
import json
from pathlib import Path

from mentor_chat import Session


def resume_summary(session):
    value = dict(
        history_steps=len(session.history), current_state=session.observe(),
        rng_counters=session.rm.rng_counters(),
        checksum=session.history[-1]["check"] if session.history else session.initial_check,
    )
    return json.loads(json.dumps(value, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("save", type=Path)
    parser.add_argument("--expected", type=Path)
    args = parser.parse_args()
    actual = resume_summary(Session.load(args.save))
    result = {"summary": actual}
    if args.expected is not None:
        expected = json.loads(args.expected.read_text())
        result["comparison"] = {key: actual[key] == expected[key] for key in actual}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if args.expected is not None and not all(result["comparison"].values()):
        raise SystemExit("保存再開の比較が一致しません: " + str(result["comparison"]))
