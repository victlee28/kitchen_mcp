"""Measure how well right-click sentences are read: the rules alone, or the rules + a language model of any provider.

    python tools/measure_commands.py                         # rules only
    python tools/measure_commands.py --llm                   # rules, then the model of KITCHEN_LLM_PROVIDER (.env) when they cannot read it
    python tools/measure_commands.py --llm --provider openai:gpt-x
    python tools/measure_commands.py --llm --record answers/  # keep the model's replies (to compare later without paying again)
    python tools/measure_commands.py --llm --replay answers/  # use the kept replies only (no network)

Each case of tests/data/commands/commands.json is said on a fresh design, routed as the menu does (a sentence about a door / window with a
clicked point -> opening_command, else interpret with the clicked cabinet as scope). A case is right when the operation contains what
``expect`` says (strings: "contains", case-insensitive; numbers within 1), or when the answer is the expected "clarify" / "unsupported".
Prints a table and the totals (right, wrong, model calls, tokens, seconds); --json writes them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CASES = ROOT / "tests" / "data" / "commands" / "commands.json"


def matches(expected: Any, got: Any) -> bool:
    """Whether ``got`` holds what ``expected`` says (a subset; strings contained, case-insensitive; numbers within 1)."""
    if isinstance(expected, dict):
        return isinstance(got, dict) and all(k in got and matches(v, got[k]) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(got, list) and len(expected) <= len(got) and all(matches(a, b) for a, b in zip(expected, got))
    if isinstance(expected, bool) or isinstance(got, bool):
        return expected == got
    if isinstance(expected, (int, float)) and isinstance(got, (int, float)):
        return abs(float(expected) - float(got)) <= 1
    if isinstance(expected, str) and isinstance(got, str):
        return expected.casefold() in got.casefold()
    return expected == got


def outcome(answer: dict[str, Any]) -> tuple[str, Any]:
    """(kind, operation) of an answer of interpret / opening_command: ok + operation, clarify, unsupported."""
    status = answer.get("status")
    if status == "ok":
        return "ok", answer.get("operation")
    if status in ("clarify", "ask"):
        return "clarify", None
    return "unsupported", None


def judge(expect: Any, kind: str, op: Any) -> bool:
    if expect in ("clarify", "unsupported"):
        return kind == expect
    return kind == "ok" and matches(expect, op)


def run_case(svc: Any, design: dict[str, Any], case: dict[str, Any], use_llm: bool) -> dict[str, Any]:
    from kitchen import edit_intent
    from kitchen.intent import KitchenTemplate
    did = svc.create_from_template(KitchenTemplate.model_validate(design["template"]), "measure")["id"]
    for op in case.get("setup") or []:
        svc.apply(did, op, svc.get(did)["rev"], "measure")
    rev = svc.get(did)["rev"]
    text = case["text"]
    answer: dict[str, Any] | None = None
    if case.get("place") and edit_intent.opening_wish(text, svc.catalog()) is not None:
        answer = svc.opening_command(did, text, case["place"], "user", rev)
        if answer.get("status") == "not-opening":
            answer = None
    if answer is None:
        answer = svc.interpret(did, text, rev, case.get("scope"), None, use_llm, None)
    kind, op = outcome(answer)
    return {"text": text, "kind": kind, "operation": op, "right": judge(case["expect"], kind, op),
            "llm": (answer.get("llm") or {}).get("status") if isinstance(answer.get("llm"), dict) else None,
            "message": answer.get("question") or answer.get("message")}


class Recorder:
    """A transport that keeps (``--record``) or replays (``--replay``) the model's replies, keyed by the request body."""

    def __init__(self, inner: Any, folder: Path, replay: bool):
        self.inner, self.folder, self.replay = inner, folder, replay
        folder.mkdir(parents=True, exist_ok=True)

    def __call__(self, url: str, headers: Any, body: Any, timeout: float) -> Any:
        key = hashlib.sha1(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        path = self.folder / f"{key}.json"
        if self.replay:
            if not path.exists():
                from kitchen.model_contract import ModelError
                raise ModelError("No kept reply for this request", code="model-http")
            return json.loads(path.read_text(encoding="utf-8"))
        data = self.inner(url, headers, body, timeout)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return data


def measure(svc: Any, cases_doc: dict[str, Any], use_llm: bool) -> dict[str, Any]:
    rows, started = [], time.monotonic()
    before = svc.models.usage()
    for case in cases_doc["cases"]:
        rows.append(run_case(svc, cases_doc["design"], case, use_llm))
    after = svc.models.usage()
    right = sum(1 for r in rows if r["right"])
    return {"cases": len(rows), "right": right, "wrong": len(rows) - right, "share": round(right / max(len(rows), 1), 3),
            "modelCalls": after["calls"] - before["calls"],
            "tokens": (after["inputTokens"] + after["outputTokens"]) - (before["inputTokens"] + before["outputTokens"]),
            "usd": round(after["usd"] - before["usd"], 4), "seconds": round(time.monotonic() - started, 1),
            "provider": svc.models.primary() if use_llm else None, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--llm", action="store_true", help="let the model read what the rules cannot")
    ap.add_argument("--provider", help="provider[:model] (default: KITCHEN_LLM_PROVIDER)")
    ap.add_argument("--record", type=Path, help="keep the model's replies in this folder")
    ap.add_argument("--replay", type=Path, help="answer from the kept replies only")
    ap.add_argument("--cases", type=Path, default=CASES)
    ap.add_argument("--json", type=Path, help="write the results here")
    a = ap.parse_args()
    if a.provider:
        name, _, model = a.provider.partition(":")
        os.environ["KITCHEN_LLM_PROVIDER"] = name
        if model:
            os.environ["KITCHEN_LLM_MODEL"] = model
    from kitchen.service import KitchenService
    tmp = Path(tempfile.mkdtemp())
    try:
        svc = KitchenService(tmp / "measure.db", tmp / "renders")
        if a.record or a.replay:
            svc.models.transport = Recorder(svc.models.transport, a.replay or a.record, bool(a.replay))
        result = measure(svc, json.loads(a.cases.read_text(encoding="utf-8")), a.llm)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for r in result["rows"]:
        mark = "ĐÚNG" if r["right"] else "SAI "
        print(f"{mark}  {r['text'][:46]:46}  {r['kind']:11}  {json.dumps(r['operation'], ensure_ascii=False)[:70] if r['operation'] else (r['message'] or '')[:70]}")
    print(f"\n{result['right']}/{result['cases']} đúng ({result['share']:.0%}) · gọi model {result['modelCalls']} lần · {result['tokens']} token · "
          f"${result['usd']} · {result['seconds']} s · {result['provider'] or 'chỉ luật'}")
    if a.json:
        a.json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
