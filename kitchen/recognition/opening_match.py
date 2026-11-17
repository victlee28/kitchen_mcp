"""Which catalog opening type a door or window seen in a picture is (proposal "nhận diện cửa chính xác hơn", P1). Pure (rule R1).

Every opening type of the catalog has features read from its own data: kind, how its leaves open, how many open or slide, whether it has a
transom (a row of fixed panes above the leaves) and of how many panes, where its middle dividers sit, which leaves carry a handle. What a
recognizer saw has the same features. Each type is scored against them; the best one is used, so a type added to the catalog is recognised
without code. When none matches in kind of opening, number of leaves and transom, the best is still used and a note says what was seen,
so the user can save the result as a type of its own (the right-click "save to the catalog" command).
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..catalog import Catalog
from ..jsonview import as_dict, as_list

STYLE_OF = {"tilt-turn": "swing", "bottom-hung": "top-hung"}    # leaf operations a picture tells apart less well
W_STYLE, W_LEAVES, W_LEAF_STEP, W_TRANSOM, W_PANES, W_AXES, W_HANDLES, W_FRONTS = 10.0, 6.0, 2.0, 4.0, 2.0, 2.0, 1.0, 1.0


@dataclass(frozen=True)
class Features:
    kind: str
    style: str                                 # swing | sliding | folding | fixed | top-hung | none
    leaves: int                                # leaves that open or slide (not the fixed panes)
    transom: bool
    transom_panes: int | None = None           # None: not known
    axes_ratio: tuple[float, ...] | None = None  # the middle vertical dividers, 0..1 from the left; None: not known
    handles: tuple[int, ...] | None = None     # the leaves (by index) with a handle; None: not known
    fronts: tuple[int, ...] | None = None      # sliding leaves on the front rail (by index); None: not known or no rails


@dataclass(frozen=True)
class Match:
    type_id: str
    score: float
    exact: bool                                # same kind of opening, number of leaves and transom (and panes when known)
    seen: Features
    features: Features


def _ints(value: Any) -> tuple[int, ...]:
    return tuple(int(v) for v in as_list(value) or [] if isinstance(v, int) and not isinstance(v, bool))


def _floats(value: Any) -> tuple[float, ...]:
    return tuple(float(v) for v in as_list(value) or [] if isinstance(v, (int, float)) and not isinstance(v, bool))


def type_features(data: Mapping[str, Any]) -> Features:
    """The features of one opening type, from its catalog data."""
    leaves = [as_dict(x) or {} for x in as_list(data.get("leaves")) or []]
    main = [lf for lf in leaves if (_ints(lf.get("rows")) or (0,))[0] == 0]
    upper = [lf for lf in leaves if (_ints(lf.get("rows")) or (0,))[0] >= 1]
    moving = [lf for lf in main if lf.get("operation") != "fixed"]
    if moving:
        op = str(moving[0].get("operation") or "swing")
        style = STYLE_OF.get(op, op)
    else:
        style = "fixed" if leaves else "none"
    transom = bool(upper) or bool(_floats(data.get("hAxesFromSill"))) or bool(_floats(data.get("hAxesRatio")))
    handle = as_dict(data.get("handle")) or {}
    chosen = _ints(handle.get("leaves")) if "leaves" in handle else None
    kind = str(data.get("kind") or "door")
    has_handles = handle.get("kind", "lever" if kind != "passage" else "none") != "none"
    handles = chosen if chosen is not None else (tuple(i for i, lf in enumerate(leaves) if lf.get("operation") != "fixed") if has_handles else ())
    tracks = [lf.get("track") for lf in leaves]
    on = [t for t in tracks if isinstance(t, int) and not isinstance(t, bool)]
    fronts = tuple(i for i, t in enumerate(tracks) if on and t == max(on)) if on and len(set(on)) > 1 else None
    return Features(kind, style, len(moving), transom, len(upper) if upper else (1 if transom else 0), _floats(data.get("axesRatio")),
                    handles, fronts)


def score(seen: Features, of_type: Features) -> float | None:
    """How well a type's features fit what was seen; None for another kind of opening."""
    if seen.kind != of_type.kind:
        return None
    s = W_STYLE if seen.style == of_type.style else 0.0
    s += W_LEAVES if seen.leaves == of_type.leaves else -W_LEAF_STEP * abs(seen.leaves - of_type.leaves)
    s += W_TRANSOM if seen.transom == of_type.transom else -W_TRANSOM
    if seen.transom and seen.transom_panes is not None and of_type.transom_panes is not None:
        s += W_PANES if seen.transom_panes == of_type.transom_panes else -W_PANES
    if seen.axes_ratio is not None and of_type.axes_ratio is not None and len(seen.axes_ratio) == len(of_type.axes_ratio) and seen.axes_ratio:
        off = sum(abs(a - b) for a, b in zip(sorted(seen.axes_ratio), sorted(of_type.axes_ratio))) / len(seen.axes_ratio)
        s += W_AXES * max(0.0, 1.0 - 4.0 * off)
    if seen.handles is not None and of_type.handles is not None:
        s += W_HANDLES if set(seen.handles) == set(of_type.handles) else 0.0
    if seen.fronts is not None and of_type.fronts is not None:
        s += W_FRONTS if set(seen.fronts) == set(of_type.fronts) else 0.0
    return s


def _exact(seen: Features, of_type: Features) -> bool:
    panes = not seen.transom or seen.transom_panes is None or seen.transom_panes == of_type.transom_panes
    return seen.style == of_type.style and seen.leaves == of_type.leaves and seen.transom == of_type.transom and panes


def ranked(seen: Features, catalog: Catalog) -> list[Match]:
    """Every catalog type of the same kind of opening, best first (catalog order on a tie)."""
    out: list[Match] = []
    for item in catalog.all("opening-type"):
        f = type_features(item.data)
        s = score(seen, f)
        if s is not None:
            out.append(Match(item.id, s, _exact(seen, f), seen, f))
    return sorted(out, key=lambda m: -m.score)          # sorted() is stable: catalog order among equal scores


def best(seen: Features, catalog: Catalog) -> Match | None:
    """The catalog type that fits best (the first one in catalog order on a tie); None when the catalog has no type of that kind."""
    found = ranked(seen, catalog)
    return found[0] if found else None


def describe(f: Features) -> str:
    """What was seen, in a few words (for notes)."""
    parts = [f.kind, f.style, f"{f.leaves} leaves"]
    if f.transom:
        parts.append(f"transom of {f.transom_panes} panes" if f.transom_panes else "transom")
    if f.handles is not None:
        parts.append("handles on leaves " + ",".join(str(i + 1) for i in f.handles) if f.handles else "no handles")
    if f.fronts is not None:
        parts.append("front rail: leaves " + ",".join(str(i + 1) for i in f.fronts))
    return ", ".join(parts)


def note(match: Match) -> list[str]:
    """A note when the type used is only the closest one."""
    if match.exact:
        return []
    return [f"opening-type-closest: the picture shows {describe(match.seen)}; no catalog type has that, {match.type_id} is the closest "
            f"({describe(match.features)}). Adjust it, then save it as a type of its own (right-click: save to the catalog)."]


def seen_features(kind: str, style: str, leaves: int, transom: bool, axes_ratio: Sequence[float] | None = None,
                  transom_panes: int | None = None, handles: Sequence[int] | None = None, fronts: Sequence[int] | None = None) -> Features:
    return Features(kind, style, leaves, transom, transom_panes, tuple(axes_ratio) if axes_ratio is not None else None,
                    tuple(handles) if handles is not None else None, tuple(fronts) if fronts is not None else None)
