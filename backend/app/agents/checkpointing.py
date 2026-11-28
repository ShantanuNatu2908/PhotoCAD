"""
PhotoCAD - Tiered LangGraph Checkpoint Persistence
Document ID: PCAD-LG-004 / cloud-infrastructure.skill.md

Resolves a durable checkpointer in this order:
  1. AsyncPostgresSaver (Supabase PostgreSQL, when DATABASE_URL is postgres)
  2. AsyncRedisSaver (Redis Cloud / Upstash, when REDIS_URL is configured)
  3. FileSaver (durable local JSON file, zero-heat development)
  4. MemorySaver (explicit ephemeral override only)

A failed higher tier degrades to the next tier and records the reason in
`last_resolution()`. The graph never crashes because a cloud tier is offline.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from app.core.config import settings

# Pydantic ADTs may cross the checkpoint boundary; msgpack must know them explicitly.
# Several FileSaver instances (one per graph import path) can share one JSON file.
# A process-wide lock and unique temp names prevent the Windows replace() race.
_PERSISTENCE_LOCK = threading.RLock()

ALLOWED_ADT_MODULES: List[Tuple[str, str]] = [
    ("app.schemas.adt", "Open3DGeometryReport"),
    ("app.schemas.adt", "CSGFeatureTree"),
    ("app.schemas.adt", "ValidationMetrics"),
    ("app.schemas.adt", "FeatureStep"),
    ("app.schemas.adt", "DetectedPlane"),
    ("app.schemas.adt", "DetectedCylinder"),
]


def build_serde() -> JsonPlusSerializer:
    """Returns the shared ADT-aware JsonPlus serializer for every checkpoint tier."""
    return JsonPlusSerializer(allowed_msgpack_modules=ALLOWED_ADT_MODULES)


def _pack_typed(value: Tuple[str, bytes]) -> List[Any]:
    return [value[0], base64.b64encode(bytes(value[1])).decode("ascii")]


def _unpack_typed(value: Any) -> Tuple[str, bytes]:
    return str(value[0]), base64.b64decode(value[1])


def _encode_key(key: Any) -> str:
    """JSON-string keys keep tuple-keyed inner maps round-trippable."""
    if isinstance(key, tuple):
        return json.dumps(list(key), separators=(",", ":"))
    return str(key)


def _decode_key(key: str) -> Any:
    if key.startswith("["):
        try:
            decoded = json.loads(key)
            if isinstance(decoded, list):
                return tuple(decoded)
        except (ValueError, TypeError):
            pass
    return key


class FileSaver(MemorySaver):
    """MemorySaver with atomic JSON persistence, so thread state survives restarts."""

    def __init__(self, path: Optional[Path] = None, serde: Any = None):
        super().__init__(serde=serde or build_serde())
        self.path = Path(path) if path else (settings.STORAGE_DIR / "checkpoints.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._load()

    # -- persistence -----------------------------------------------------
    def _snapshot(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "storage": {
                str(thread): {
                    str(ns): {
                        str(cid): [_pack_typed(saved[0]), _pack_typed(saved[1]), saved[2]]
                        for cid, saved in checkpoints.items()
                    }
                    for ns, checkpoints in namespaces.items()
                }
                for thread, namespaces in self.storage.items()
            },
            "blobs": {_encode_key(key): _pack_typed(value) for key, value in self.blobs.items()},
            "writes": {
                _encode_key(outer): {
                    _encode_key(inner): [
                        saved[0], saved[1], _pack_typed(saved[2]), saved[3]
                    ]
                    for inner, saved in inner_writes.items()
                }
                for outer, inner_writes in self.writes.items()
            },
        }

    def flush(self) -> None:
        """Atomically writes the current in-memory checkpoint state to disk."""
        payload = json.dumps(self._snapshot(), separators=(",", ":"))
        tmp = self.path.with_name(
            f"{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        with _PERSISTENCE_LOCK:
            try:
                for attempt in range(5):
                    try:
                        tmp.write_text(payload, encoding="utf-8")
                        tmp.replace(self.path)
                        return
                    except PermissionError:
                        if attempt == 4:
                            raise
                        time.sleep(0.01 * (attempt + 1))
            finally:
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data: Dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return
        if data.get("version") != 1:
            return

        with self._lock:
            for thread, namespaces in (data.get("storage") or {}).items():
                for ns, checkpoints in namespaces.items():
                    storage_target = self.storage[thread][ns]
                    for cid, saved in checkpoints.items():
                        storage_target[cid] = (
                            _unpack_typed(saved[0]),
                            _unpack_typed(saved[1]),
                            saved[2],
                        )
            for key, value in (data.get("blobs") or {}).items():
                self.blobs[_decode_key(key)] = _unpack_typed(value)
            for outer, inner_writes in (data.get("writes") or {}).items():
                writes_target = self.writes[_decode_key(outer)]
                for inner, saved in inner_writes.items():
                    writes_target[_decode_key(inner)] = (
                        saved[0], saved[1], _unpack_typed(saved[2]), saved[3]
                    )

    # -- MemorySaver hooks ------------------------------------------------
    def put(self, config: Any, checkpoint: Any, metadata: Any, new_versions: Any) -> Any:
        with self._lock:
            result = super().put(config, checkpoint, metadata, new_versions)
            self.flush()
            return result

    def put_writes(self, config: Any, writes: Any, task_id: str, task_path: str = "") -> None:
        with self._lock:
            super().put_writes(config, writes, task_id, task_path)
            self.flush()

    def delete_thread(self, thread_id: str) -> None:
        with self._lock:
            super().delete_thread(thread_id)
            self.flush()

    def delete_for_runs(self, run_ids: Sequence[str]) -> None:
        with self._lock:
            super().delete_for_runs(run_ids)
            self.flush()


# -- Resolution ----------------------------------------------------------

_CACHED_CHECKPOINTER: Optional[BaseCheckpointSaver] = None
_CACHED_CONTEXT_MANAGERS: List[Any] = []
_RESOLUTION_LOCK = asyncio.Lock()
_LAST_RESOLUTION: Dict[str, Any] = {"tier": "unresolved", "reason": None}


def last_resolution() -> Dict[str, Any]:
    """Returns diagnostic metadata for the most recent checkpointer resolution."""
    return dict(_LAST_RESOLUTION)


def reset_checkpointer_cache() -> None:
    """Test helper: drops the cached saver without closing process-lifetime providers."""
    global _CACHED_CHECKPOINTER
    _CACHED_CHECKPOINTER = None
    _LAST_RESOLUTION.update({"tier": "unresolved", "reason": None})


def _configured_tier() -> str:
    forced = os.getenv("PHOTOCAD_CHECKPOINTER", "").strip().lower()
    if forced in {"postgres", "redis", "file", "memory"}:
        return forced
    db_url = os.getenv("DATABASE_URL", "")
    if db_url.startswith("postgresql") or db_url.startswith("postgres://"):
        return "postgres"
    redis_url = os.getenv("REDIS_URL", "")
    if redis_url and "your-endpoint" not in redis_url:
        return "redis"
    return "file"


def _record(tier: str, reason: str | None = None) -> None:
    _LAST_RESOLUTION.update({"tier": tier, "reason": reason})


async def _resolve_postgres() -> BaseCheckpointSaver:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    db_url = os.getenv("DATABASE_URL", "")
    # from_conn_string is an async context manager; keep it alive for process lifetime.
    ctx = AsyncPostgresSaver.from_conn_string(db_url, serde=build_serde())
    saver = await ctx.__aenter__()
    await saver.setup()
    _CACHED_CONTEXT_MANAGERS.append(ctx)
    return saver


async def _resolve_redis() -> BaseCheckpointSaver:
    from langgraph.checkpoint.redis.aio import AsyncRedisSaver

    saver = AsyncRedisSaver(redis_url=os.getenv("REDIS_URL", ""))
    saver.serde = build_serde()
    await saver.setup()
    return saver


async def resolve_checkpointer(force: bool = False) -> BaseCheckpointSaver:
    """Returns the highest available durable checkpointer, degrading safely."""
    global _CACHED_CHECKPOINTER
    async with _RESOLUTION_LOCK:
        if _CACHED_CHECKPOINTER is not None and not force:
            return _CACHED_CHECKPOINTER

        requested = _configured_tier()
        if requested == "memory":
            _CACHED_CHECKPOINTER = MemorySaver(serde=build_serde())
            _record("memory", "explicit PHOTOCAD_CHECKPOINTER=memory")
            return _CACHED_CHECKPOINTER

        attempts: List[Tuple[str, Any]] = []
        redis_url = os.getenv("REDIS_URL", "")
        redis_configured = bool(redis_url) and "your-endpoint" not in redis_url
        if requested == "postgres":
            attempts.append(("postgres", _resolve_postgres))
        if requested == "redis" or (requested == "postgres" and redis_configured):
            attempts.append(("redis", _resolve_redis))
        attempts.append(("file", lambda: asyncio.sleep(0, result=FileSaver())))
        attempts.append(("memory", lambda: asyncio.sleep(0, result=MemorySaver(serde=build_serde()))))

        failures: List[str] = []
        for tier, factory in attempts:
            try:
                saver = await factory()
                _CACHED_CHECKPOINTER = saver
                _record(tier, "; ".join(failures) if failures else None)
                return saver
            except Exception as exc:  # provider/SDK absence or connection failure
                failures.append(f"{tier}: {type(exc).__name__}: {exc}")

        # Defensive: the memory factory never fails, but keep a safe terminal state.
        _CACHED_CHECKPOINTER = MemorySaver(serde=build_serde())
        _record("memory", "; ".join(failures))
        return _CACHED_CHECKPOINTER
