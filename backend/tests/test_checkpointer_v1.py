"""
Persistent LangGraph checkpoint tier tests (PCAD-LG-004 / cloud-infrastructure skill).

Proves that thread state survives a process-equivalent restart and that cloud
tier failures degrade without crashing graph construction.
"""

from __future__ import annotations

from typing import TypedDict

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.checkpointing import (
    FileSaver,
    last_resolution,
    reset_checkpointer_cache,
    resolve_checkpointer,
)


@pytest.fixture(autouse=True)
def _clean_checkpointer_env(monkeypatch, tmp_path):
    monkeypatch.delenv("PHOTOCAD_CHECKPOINTER", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///" + str(tmp_path / "photocad.db"))
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("PHOTOCAD_CHECKPOINT_PATH", str(tmp_path / "checkpoints.json"))
    reset_checkpointer_cache()
    yield
    reset_checkpointer_cache()


def _stateful_graph(checkpointer):
    class State(TypedDict):
        marker: str

    def write_marker(state: State) -> dict:
        return {"marker": state.get("marker", "") + "done"}

    builder = StateGraph(State)
    builder.add_node("writer", write_marker)
    builder.add_edge(START, "writer")
    builder.add_edge("writer", END)
    return builder.compile(checkpointer=checkpointer)


def test_file_saver_round_trips_typed_payload():
    path = __import__("pathlib").Path(str(_env_checkpoint_path()))
    first = FileSaver(path=path)
    config = {"configurable": {"thread_id": "roundtrip", "checkpoint_ns": ""}}
    first.put(
        config,
        {
            "v": 1,
            "id": "cp-1",
            "ts": "2026-01-01T00:00:00+00:00",
            "channel_values": {"marker": "persisted"},
            "channel_versions": {"marker": 1},
            "versions_seen": {},
        },
        {"source": "test"},
        {"marker": 1},
    )

    second = FileSaver(path=path)
    restored = second.get(config)
    assert restored is not None
    assert restored["channel_values"]["marker"] == "persisted"


def _env_checkpoint_path() -> str:
    import os

    return os.environ["PHOTOCAD_CHECKPOINT_PATH"]


@pytest.mark.asyncio
async def test_resolver_defaults_to_durable_file_tier():
    saver = await resolve_checkpointer()
    assert isinstance(saver, FileSaver)
    assert last_resolution()["tier"] == "file"


@pytest.mark.asyncio
async def test_resolver_degrades_from_bad_postgres_to_file(monkeypatch):
    monkeypatch.setenv("PHOTOCAD_CHECKPOINTER", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://nobody:wrong@127.0.0.1:1/none")
    reset_checkpointer_cache()

    saver = await resolve_checkpointer()
    assert isinstance(saver, FileSaver)
    resolution = last_resolution()
    assert resolution["tier"] == "file"
    assert "postgres:" in (resolution["reason"] or "")


@pytest.mark.asyncio
async def test_explicit_memory_override(monkeypatch):
    monkeypatch.setenv("PHOTOCAD_CHECKPOINTER", "memory")
    reset_checkpointer_cache()
    saver = await resolve_checkpointer()
    assert isinstance(saver, MemorySaver)
    assert last_resolution()["tier"] == "memory"


@pytest.mark.asyncio
async def test_thread_history_survives_process_equivalent_restart():
    import asyncio
    import os

    path = __import__("pathlib").Path(os.environ["PHOTOCAD_CHECKPOINT_PATH"])
    config = {"configurable": {"thread_id": "restart-thread"}, "recursion_limit": 10}

    first = await asyncio.to_thread(_stateful_graph, FileSaver(path=path))
    await first.ainvoke({"marker": ""}, config=config)

    # Simulate a fresh process: no shared saver instance, only the JSON file.
    restarted = await asyncio.to_thread(_stateful_graph, FileSaver(path=path))
    snapshot = await restarted.aget_state(config)
    assert snapshot.values["marker"] == "done"
