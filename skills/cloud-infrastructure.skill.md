# Cloud Infrastructure Skill (`cloud-infrastructure.skill.md`)

*Apply whenever modifying `backend/app/core/cloud_config.py`, `backend/app/agents/checkpointing.py`, `gpu_workers/modal_app.py`, or production deployment docs.*

## Non-negotiable rules

1. **Managed tiers only.** Secrets arrive from `.env` / host secrets. Never add mandatory local Docker Compose services; every tier has a deterministic local fallback so development stays zero-heat.
2. **No secret literals.** Treat any value containing `your-`, empty strings, or placeholder tokens as *unconfigured*. `is_valid_secret()` is the single source of truth.
3. **Capability, not identity, decides the engine.** Modal tokens + billing decide whether SAM/DA3/Open3D run remotely; otherwise the visual-hull fallback is used. Cloud diagnostics must report `dev_mock_connected`, `not_deployed`, or `connected` honestly — never fake `connected`.
4. **Checkpointer tier order is fixed:** `AsyncPostgresSaver` (Supabase) → `AsyncRedisSaver` (Redis Cloud / Upstash) → durable `FileSaver` → `MemorySaver`. A failed higher tier degrades to the next tier and records the reason; it never crashes the graph.
5. **Async setup happens once.** `AsyncPostgresSaver`/`AsyncRedisSaver` require `await setup()`. Keep the provider's async context manager alive for the process lifetime; never open/close it per request.
6. **Binary blobs never enter Postgres or Redis.** Only R2 object keys are persisted; local dev maps keys under `storage/`.
7. **Modal workers keep `gpu="L4"`, `scaledown_window=60`, and a persistent `modal.Volume`.** The CAD sandbox additionally sets `block_network=True`.
8. **R2 privacy is a lifecycle rule, not application code.** `uploads/*` expires after 24 hours; application code must not silently delete user artifacts. Document the dashboard step as an external handoff.

## Verification checklist

- `uv run pytest tests/test_cloud_health.py tests/test_checkpointer_v1.py -q`
- Health output contains all four tier keys and never reports `connected` for unconfigured credentials.
- Restart simulation: build two graph instances with the same `thread_id`; the second sees the first thread's checkpoint.

## External handoffs (never claim as code-complete)

- Modal account with billing + `modal deploy gpu_workers/modal_app.py`.
- Supabase PostgreSQL 16 instance with `vector` extension.
- Redis Cloud / Upstash instance and `REDIS_URL`.
- Cloudflare R2 dashboard lifecycle rule on `uploads/*`.
