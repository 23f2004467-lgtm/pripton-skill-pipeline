"""Content-hash cache for pipeline idempotency.

Cache keys are SHA-256 hashes of the input bytes (source_id). This makes
the cache content-addressed: same input → same output, regardless of
how many times the pipeline runs.

See PLAN.md Section 10 for the full specification.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional, Union

from skillpipeline.models import RunMetadata, SkillMap


class CacheEntry:
    """A cache entry containing the skill map and metadata."""

    skill_map: dict  # Serialized SkillMap
    run_metadata: dict  # Serialized RunMetadata
    cached_at: str  # ISO 8601 timestamp

    def __init__(self, skill_map: SkillMap, run_metadata: RunMetadata) -> None:
        self.skill_map = skill_map.model_dump()
        self.run_metadata = run_metadata.model_dump()
        self.cached_at = datetime.now(UTC).isoformat()


class Cache:
    """Content-addressed cache for pipeline results.

    - Keys: source_id (SHA-256 of input bytes)
    - Values: CacheEntry with skill_map and run_metadata
    - Location: .cache/{source_id}.json
    """

    def __init__(self, cache_dir: Union[Path, str] = ".cache") -> None:
        """Initialize the cache with a specific directory.

        Args:
            cache_dir: Path to cache directory (default: .cache)
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)

    def _get_cache_path(self, source_id: str) -> Path:
        """Get the cache file path for a given source_id."""
        return self.cache_dir / f"{source_id}.json"

    def get(self, source_id: str) -> Optional[CacheEntry]:
        """Retrieve a cached entry if it exists.

        Args:
            source_id: The SHA-256 hash of the input bytes

        Returns:
            CacheEntry if hit, None if miss
        """
        cache_path = self._get_cache_path(source_id)

        if not cache_path.exists():
            return None

        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))

            # Reconstruct objects from dicts
            skill_map = SkillMap(**data["skill_map"])
            run_metadata = RunMetadata(**data["run_metadata"])

            # Create a CacheEntry-like object (bypass __init__ to avoid re-serializing)
            entry = CacheEntry.__new__(CacheEntry)
            entry.skill_map = skill_map
            entry.run_metadata = run_metadata
            entry.cached_at = data["cached_at"]

            return entry
        except (json.JSONDecodeError, KeyError, TypeError):
            # Corrupt cache entry - treat as miss
            return None

    def put(
        self,
        source_id: str,
        skill_map: SkillMap,
        run_metadata: RunMetadata,
    ) -> None:
        """Store a pipeline result in the cache.

        Args:
            source_id: The SHA-256 hash of the input bytes
            skill_map: The output skill map
            run_metadata: The run metadata (must have status="complete")
        """
        cache_path = self._get_cache_path(source_id)

        entry = {
            "skill_map": skill_map.model_dump(),
            "run_metadata": run_metadata.model_dump(),
            "cached_at": datetime.now(UTC).isoformat(),
        }

        cache_path.write_text(json.dumps(entry, indent=2), encoding="utf-8")

    def should_cache(self, run_metadata: RunMetadata) -> bool:
        """Determine whether a run should be cached.

        Per PLAN.md Section 10:
        - Flagged runs are NOT cached
        - Runs in awaiting_review state are NOT cached

        Args:
            run_metadata: The run metadata to check

        Returns:
            True if the run should be cached, False otherwise
        """
        if run_metadata.status != "complete":
            return False
        return True

    def clear(self) -> None:
        """Clear all cache entries."""
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink()

    def list_entries(self) -> list[dict]:
        """List all cache entries with metadata.

        Returns:
            List of dicts with source_id, cached_at, and status
        """
        entries = []
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                source_id = cache_file.stem  # filename without .json
                entries.append({
                    "source_id": source_id,
                    "cached_at": data.get("cached_at", "unknown"),
                    "status": data.get("run_metadata", {}).get("status", "unknown"),
                })
            except (json.JSONDecodeError, KeyError):
                # Skip corrupt entries
                continue
        return entries


# Default cache instance for convenience
_default_cache: Optional[Cache] = None


def get_cache(cache_dir: Union[Path, str] = ".cache") -> Cache:
    """Get the default cache instance (singleton pattern).

    Args:
        cache_dir: Path to cache directory (only used on first call)

    Returns:
        The Cache instance
    """
    global _default_cache
    if _default_cache is None:
        _default_cache = Cache(cache_dir)
    return _default_cache
