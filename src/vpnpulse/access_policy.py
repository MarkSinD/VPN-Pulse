"""Fail-closed feature policy for self-service profile operations.

Address pools, provisioner hosts and filesystem paths intentionally live outside the public
configuration. This module only answers whether a future write action may be exposed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


AccessBlock = Literal[
    "member_registry_disabled",
    "grants_disabled",
    "issuance_disabled",
    "server_not_found",
    "server_issuance_disabled",
    "server_maintenance",
]


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    code: AccessBlock | None = None


def issuance_decision(config: dict[str, Any], server_id: str) -> AccessDecision:
    """Return a stable, non-secret reason when profile issuance is unavailable."""
    access = config.get("access") or {}
    if access.get("member_registry_enabled") is not True:
        return AccessDecision(False, "member_registry_disabled")
    if access.get("grants_enabled") is not True:
        return AccessDecision(False, "grants_disabled")
    if access.get("issuance_enabled") is not True:
        return AccessDecision(False, "issuance_disabled")

    server = next((item for item in config.get("servers", []) if item.get("id") == server_id), None)
    if server is None:
        return AccessDecision(False, "server_not_found")
    server_access = server.get("access") or {}
    if server_access.get("maintenance") is True:
        return AccessDecision(False, "server_maintenance")
    if server_access.get("issuance_enabled") is not True:
        return AccessDecision(False, "server_issuance_disabled")
    return AccessDecision(True)
