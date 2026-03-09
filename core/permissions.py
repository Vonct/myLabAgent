from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PermissionLevel(str, Enum):
    READ_ONLY = "read_only"
    NETWORK = "network"
    FILE_WRITE = "file_write"
    EXEC = "exec"


@dataclass(frozen=True)
class PermissionResult:
    allowed: bool
    reason: str = ""


class PermissionManager:
    """Applies lightweight permission rules before a tool can run."""

    def __init__(self, allowed_levels: set[PermissionLevel] | None = None):
        self.allowed_levels = allowed_levels or {
            PermissionLevel.READ_ONLY,
            PermissionLevel.NETWORK,
        }

    def check(self, level: PermissionLevel) -> PermissionResult:
        if level in self.allowed_levels:
            return PermissionResult(True, "")
        return PermissionResult(
            False,
            f"Tool permission `{level.value}` is blocked by the current runtime policy.",
        )
