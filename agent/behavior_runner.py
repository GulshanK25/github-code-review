"""Trusted harness copied into Docker for opt-in before/after behavior probes.

This file is never used to execute reviewed code on the host. The harness
receives one small JSON case, executes each revision in an isolated namespace
inside the container, and writes a machine-readable result to stdout.
"""

import contextlib
import copy
import io
import json
import sys


def _call(source: str, function: str, probe: dict) -> dict:
    namespace = {"__name__": "__behavior_probe__"}
    try:
        # Ordinary print statements should not corrupt the JSON protocol.
        # This is not a defense against actively malicious stdout writes.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            exec(compile(source, "<sandboxed-revision>", "exec"), namespace)
            target = namespace[function]
            outcome = target(
                *copy.deepcopy(probe.get("args", [])),
                **copy.deepcopy(probe.get("kwargs", {})),
            )
        # Only support values representable in strict JSON. This deliberately
        # avoids serializing arbitrary Python objects or invoking repr().
        normalized = json.loads(json.dumps(outcome, allow_nan=False))
        return {"kind": "value", "value": normalized}
    except BaseException as exc:
        return {"kind": "exception", "type": type(exc).__name__}


def execute_case(payload: dict) -> dict:
    results = []
    for probe in payload["probes"]:
        results.append({
            "before": _call(payload["old_code"], payload["function"], probe),
            "after": _call(payload["new_code"], payload["function"], probe),
        })
    return {"results": results}


def main() -> None:
    with open("/workspace/case.json", encoding="utf-8") as handle:
        payload = json.load(handle)
    print(json.dumps(execute_case(payload), allow_nan=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
