-- PhotoCAD auth-multitenancy.skill.md
-- Supabase / PostgreSQL tenant scoping. Safe to re-run.
-- The application also applies this migration idempotently at startup.

ALTER TABLE projects ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'public';
ALTER TABLE scan_sessions ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'public';
ALTER TABLE cad_generations ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'public';

CREATE INDEX IF NOT EXISTS ix_projects_tenant_id ON projects (tenant_id);
CREATE INDEX IF NOT EXISTS ix_scan_sessions_tenant_id ON scan_sessions (tenant_id);
CREATE INDEX IF NOT EXISTS ix_cad_generations_tenant_id ON cad_generations (tenant_id);

-- Row Level Security: JWT claim `tenant_id` / `organization_id` scopes every row.
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE scan_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE cad_generations ENABLE ROW LEVEL SECURITY;

-- One isolation policy per table: RLS without a policy denies every non-owner role.
DROP POLICY IF EXISTS photocad_tenant_isolation ON projects;
CREATE POLICY photocad_tenant_isolation ON projects
    USING (tenant_id = COALESCE(current_setting('request.jwt.claim.tenant_id', true),
                                current_setting('request.jwt.claim.organization_id', true),
                                'public'));

DROP POLICY IF EXISTS photocad_tenant_isolation ON scan_sessions;
CREATE POLICY photocad_tenant_isolation ON scan_sessions
    USING (tenant_id = COALESCE(current_setting('request.jwt.claim.tenant_id', true),
                                current_setting('request.jwt.claim.organization_id', true),
                                'public'));

DROP POLICY IF EXISTS photocad_tenant_isolation ON cad_generations;
CREATE POLICY photocad_tenant_isolation ON cad_generations
    USING (tenant_id = COALESCE(current_setting('request.jwt.claim.tenant_id', true),
                                current_setting('request.jwt.claim.organization_id', true),
                                'public'));
