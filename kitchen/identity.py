"""Who a request acts as: the seam where real sign-in will go (shell zone).

There are no accounts yet (11/11/2026): the catalog's two roles (``workshop`` edits the workshop's layer, ``user`` the user's) are picked in
the page and sent as the ``X-Role`` header, which anyone can set. That is fine on one machine (the server listens on 127.0.0.1 only), not
on a network. An ``IdentityProvider`` turns a request's headers into an ``Identity``; the HTTP adapter asks the one it was given and never
reads a header itself. A real sign-in is a provider that checks a session or a token and fails with ``NotAllowed``.

* ``HeaderRole`` (default): the ``X-Role`` header, ``user`` when missing.
* ``FixedRole``: every request is the same role, whatever it sends (``KITCHEN_FIXED_ROLE=user``: a server where nobody can edit the
  workshop's layer from the page).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .catalog.kinds import ROLES
from .errors import InvalidInput


@dataclass(frozen=True)
class Identity:
    role: str                  # workshop | user
    user: str = "default"      # whose user layer (one user until accounts exist)


class Headers(Protocol):
    """A request's headers: a dict, or http.server's message (looked up without regard to case)."""
    def get(self, key: str, /) -> str | None: ...


class IdentityProvider(Protocol):
    def identify(self, headers: Headers) -> Identity: ...


class HeaderRole:
    """The role the page sends (``X-Role``). Not authentication."""

    def identify(self, headers: Headers) -> Identity:
        return Identity((headers.get("X-Role") or "user").strip().lower())


@dataclass(frozen=True)
class FixedRole:
    """Every request acts as ``role``."""
    role: str

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise InvalidInput(f"Unknown role {self.role!r}; use one of {', '.join(ROLES)}", code="bad-role")

    def identify(self, headers: Headers) -> Identity:
        return Identity(self.role)


def provider(fixed_role: str | None) -> IdentityProvider:
    """The provider the settings ask for: a fixed role when one is set, else the header."""
    return FixedRole(fixed_role) if fixed_role else HeaderRole()
