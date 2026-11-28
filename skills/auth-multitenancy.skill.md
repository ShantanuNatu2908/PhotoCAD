# Auth & Multi-Tenancy Skill (`auth-multitenancy.skill.md`)

*Apply whenever modifying `backend/app/core/security.py`, ORM models, API routers, or WebSocket auth.*

## Non-negotiable rules

1. **Dev bypass is explicit.** With no `JWT_SECRET`/`SUPABASE_JWT_SECRET`, the API stays in open local-developer mode and diagnostics say so. Setting a secret turns enforcement on for every write/read route.
2. **Verify JWTs locally and offline.** Use PyJWT with HS256 (Supabase compatible) and validate `exp`, `iat`, `iss` when configured. Never call a remote auth endpoint on the request hot path.
3. **Tenant scope is derived, never trusted from the body.** `tenant_id` comes from verified claims (`tenant_id` / `app_metadata.tenant_id` / `organization_id`), or defaults to `public` in dev mode. Request bodies cannot override it.
4. **Ownership checks are row-level.** Every project, scan, generation, export, and WebSocket channel resolves the owner tenant via a single dependency before returning data. A mismatched tenant returns 404 (never 403 with resource details).
5. **Claim-less tokens are still scoped.** If a valid token lacks a tenant claim, use the immutable `sub` as a stable tenant namespace so two users cannot read each other's scans.
6. **No secrets in logs or errors.** Never echo tokens, and never include tenant ids in unauthenticated 404 bodies.
7. **Backward compatibility:** existing rows without `tenant_id` are treated as `public`, so the current local database keeps working after migration.

## Verification checklist

- With auth off: existing E2E scan/generate tests pass unchanged.
- With auth on: missing token → 401; valid token for another tenant → 404; matching tenant → 200.
- WebSocket handshake rejects a mismatched tenant before accepting the connection.
- Migration adds nullable `tenant_id` columns with a `public` default and indexes; SQLite path is idempotent.
