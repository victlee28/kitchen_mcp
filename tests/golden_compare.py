"""Compare an actual JSON value with a golden one: exact for everything except floats, which use an absolute tolerance."""
from __future__ import annotations


def differences(actual, expected, tol: float, path: str = "$") -> list[str]:
    if isinstance(expected, bool) or isinstance(actual, bool):
        return [] if actual is expected else [f"{path}: {actual!r} != {expected!r}"]
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if isinstance(expected, int) and isinstance(actual, int):
            return [] if actual == expected else [f"{path}: {actual} != {expected}"]
        return [] if abs(actual - expected) <= tol else [f"{path}: {actual} != {expected} (tol {tol})"]
    if isinstance(expected, dict) and isinstance(actual, dict):
        out = []
        for k in sorted(set(expected) | set(actual)):
            if k not in actual:
                out.append(f"{path}.{k}: missing")
            elif k not in expected:
                out.append(f"{path}.{k}: unexpected")
            else:
                out += differences(actual[k], expected[k], tol, f"{path}.{k}")
        return out
    if isinstance(expected, list) and isinstance(actual, list):
        if len(actual) != len(expected):
            return [f"{path}: length {len(actual)} != {len(expected)}"]
        return [d for i, (a, e) in enumerate(zip(actual, expected)) for d in differences(a, e, tol, f"{path}[{i}]")]
    return [] if actual == expected and type(actual) is type(expected) else [f"{path}: {actual!r} != {expected!r}"]
