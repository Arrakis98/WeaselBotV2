from __future__ import annotations

from dataclasses import dataclass


class ArcadiaManifestError(ValueError):
    """Raised when an Arcadia report family is unsafe."""


@dataclass(frozen=True)
class ArcadiaManifestOperation:
    relative_path: str
