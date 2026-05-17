"""Persistent JSON cache for Guide Retriever LLM routing decisions (D30).

Schema (canonical, matches HANDOFF.md ~line 148):

    {
      "schema_version": 1,
      "manifest_fingerprint": "sha256:<hex>",
      "entries": {
        "<normalized_goal>": {"sop_name": "<name|<none>>", "count": <int|null>}
      }
    }

Cache lives at brain/.cache/sop_routes.json (gitignored). The cache directory
is auto-created on first save. Manifest-fingerprint mismatch on load drops all
entries, which is correct: the SOP catalog has changed and old routes may
point to renamed or removed SOPs.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from src.sops.loader import manifest_fingerprint

SCHEMA_VERSION = 1
NONE_SENTINEL = "<none>"  # used when LLM confirms no SOP matches the goal


def _default_cache_path() -> Path:
    """brain/.cache/sop_routes.json resolved relative to this file."""
    return Path(__file__).resolve().parent.parent.parent / ".cache" / "sop_routes.json"


def _index_path() -> Path:
    """brain/src/sops/index.yaml — fingerprint target."""
    return Path(__file__).resolve().parent / "index.yaml"


def normalize_goal(goal: str) -> str:
    """Lowercase + collapse whitespace. No article-stripping. No stemming."""
    return re.sub(r"\s+", " ", goal.lower()).strip()


class SOPRouteCache:
    def __init__(self, cache_path: Path | None = None) -> None:
        self._path = cache_path or _default_cache_path()
        self._data: dict | None = None  # lazy-loaded on first access

    def _current_fingerprint(self) -> str:
        """Read live index.yaml fingerprint. Returns '' if index missing."""
        idx = _index_path()
        if not idx.exists():
            return ""
        return manifest_fingerprint(idx)

    def load(self) -> dict:
        """Read cache file. Drop entries on fingerprint mismatch. Memoize."""
        if self._data is not None:
            return self._data
        empty = {
            "schema_version": SCHEMA_VERSION,
            "manifest_fingerprint": self._current_fingerprint(),
            "entries": {},
        }
        if not self._path.exists():
            self._data = empty
            return self._data
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self._data = empty
            return self._data
        current_fp = self._current_fingerprint()
        if data.get("manifest_fingerprint") != current_fp:
            # invalidation: fingerprint mismatch drops all entries
            self._data = {
                "schema_version": SCHEMA_VERSION,
                "manifest_fingerprint": current_fp,
                "entries": {},
            }
        else:
            # ensure shape
            data.setdefault("schema_version", SCHEMA_VERSION)
            data.setdefault("entries", {})
            self._data = data
        return self._data

    def get(self, goal: str) -> dict | None:
        key = normalize_goal(goal)
        return self.load().get("entries", {}).get(key)

    def set(self, goal: str, sop_name: str, count: int | None) -> None:
        key = normalize_goal(goal)
        data = self.load()
        # Refresh fingerprint to current on write (post-invalidation case).
        data["manifest_fingerprint"] = self._current_fingerprint()
        data.setdefault("entries", {})[key] = {"sop_name": sop_name, "count": count}
        self._save(data)

    def clear(self) -> None:
        """Wipe the cache file: empty entries + current fingerprint."""
        data = {
            "schema_version": SCHEMA_VERSION,
            "manifest_fingerprint": self._current_fingerprint(),
            "entries": {},
        }
        self._save(data)
        self._data = data

    def _save(self, data: dict) -> None:
        """Atomic write: tempfile in same dir + os.replace."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(self._path.parent), prefix=".sop_routes_", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, sort_keys=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise


def _cli(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] != "clear":
        print("usage: python -m src.sops.cache clear", file=sys.stderr)
        return 2
    cache = SOPRouteCache()
    cache.clear()
    print(f"cleared {cache._path}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
