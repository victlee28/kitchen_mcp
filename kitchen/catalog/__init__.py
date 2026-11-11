"""The catalog: business data (appliances, materials, cabinet types, layouts, wording...) kept out of the code (data-driven design).

Three layers, a later one overriding an earlier one item by item: ``builtin`` (files under ``data/``, kept in git), ``workshop`` and
``user:<name>`` (rows of the database, edited in the app). This package is portable core: it never reads files or the database; the shell
(``kitchen.catalog_files``, ``kitchen.store``, ``kitchen.service``) loads the entries and passes them in.

* ``model``     ``Item`` and the read-only ``Catalog`` the core functions take.
* ``kinds``     ``KindInfo``: what a kind is (label, who may write it, references to other kinds, where a design uses it).
* ``merge``     ``Entry`` (one stored row) and ``merge``: the layers into one ``Catalog``.
* ``check``     who may write what, and references between items.
* ``snapshot``  the items a design uses, saved with each revision so an old revision is rebuilt as it was.
"""
from __future__ import annotations

from .check import Problem, check_refs, check_write, scope_for
from .kinds import KindInfo, kind_info
from .merge import BUILTIN, WORKSHOP, Entry, layer_rank, merge, user_scope
from .model import EMPTY, Catalog, Item
from .snapshot import used_items, with_snapshot

__all__ = ["BUILTIN", "WORKSHOP", "EMPTY", "Catalog", "Entry", "Item", "KindInfo", "Problem", "check_refs", "check_write", "kind_info",
           "layer_rank", "merge", "scope_for", "used_items", "user_scope", "with_snapshot"]
