// PhotoCAD gate verification runner.
// Portable Node entrypoint used by GATES.md; every check exits non-zero on failure
// and prints a single success-only token after all assertions pass.

// Node emits DEP0190 when shell:true is used on Windows; commands here are fixed literals.
process.noDeprecation = true;

import { spawnSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const BACKEND = join(ROOT, 'backend');
const FRONTEND = join(ROOT, 'frontend');
const PY = join(
  BACKEND,
  '.venv',
  process.platform === 'win32' ? 'Scripts' : 'bin',
  process.platform === 'win32' ? 'python.exe' : 'python',
);

function run(command, args, cwd, label) {
  const result = spawnSync(command, args, {
    cwd,
    encoding: 'utf8',
    shell: process.platform === 'win32',
    maxBuffer: 32 * 1024 * 1024,
  });
  const output = `${result.stdout || ''}${result.stderr || ''}`;
  if (result.error || result.status !== 0) {
    console.error(`[verify] ${label} failed (status ${result.status}):\n${output.slice(-6000)}`);
    process.exit(1);
  }
  return output;
}

function assert(condition, message) {
  if (!condition) {
    console.error(`[verify] assertion failed: ${message}`);
    process.exit(1);
  }
}

function expectToken(output, token, label) {
  assert(output.includes(token), `${label} did not emit ${token}`);
}

function read(relPath) {
  const abs = join(ROOT, relPath);
  assert(existsSync(abs), `missing required file: ${relPath}`);
  return readFileSync(abs, 'utf8');
}

function requireMarkers(relPath, markers) {
  const text = read(relPath);
  for (const marker of markers) {
    assert(text.includes(marker), `${relPath} missing marker: ${marker}`);
  }
}

const checks = {
  baseline() {
    const out = run(PY, ['-m', 'pytest', 'tests/', '-q'], BACKEND, 'backend pytest');
    assert(/[0-9]+ passed/.test(out), 'pytest did not report a passing count');
    assert(!/\b(failed|error)\b/i.test(out.split('\n').slice(-3).join('\n')), 'pytest summary reports failures');
    run('uv', ['run', 'python', '-m', 'compileall', '-q', 'app'], BACKEND, 'uv run compile');
    console.log('BASELINE_OK');
  },

  skills() {
    const required = {
      'skills/cloud-infrastructure.skill.md': ['Modal', 'Supabase', 'Redis', 'R2', 'lifecycle'],
      'skills/rag-pgvector.skill.md': ['pgvector', 'HNSW', 'embedding', 'fallback'],
      'skills/scale-calibration.skill.md': ['ArUco', 'ID-1', 'mm_per_unit', 'aspect'],
      'skills/auth-multitenancy.skill.md': ['JWT', 'tenant_id', 'owner', 'bypass'],
      'skills/cicd.skill.md': ['ruff', 'mypy', 'pytest', 'typecheck', 'schema sync'],
      'skills/nurbs-surfaces.skill.md': ['C2', 'B-spline', 'watertight', 'build123d'],
    };
    for (const [file, markers] of Object.entries(required)) requireMarkers(file, markers);
    console.log('SKILLS_OK');
  },

  checkpointer() {
    const out = run(PY, ['-m', 'pytest', 'tests/test_checkpointer_v1.py', '-q'], BACKEND, 'checkpointer tests');
    expectToken(out, 'passed', 'checkpointer tests');
    console.log('CHECKPOINTER_OK');
  },

  rag() {
    const out = run(PY, ['-m', 'pytest', 'tests/test_rag.py', 'tests/test_rag_pgvector_v1.py', '-q'], BACKEND, 'rag tests');
    expectToken(out, 'passed', 'rag tests');
    console.log('RAG_OK');
  },

  calibration() {
    run('npm', ['run', 'typecheck'], FRONTEND, 'frontend typecheck');
    run('npm', ['run', 'build'], FRONTEND, 'frontend build');
    const out = run('npm', ['test', '--', '--run'], FRONTEND, 'frontend unit tests');
    assert(/Test Files\s+\d+ passed/.test(out) || /passed/.test(out), 'frontend tests did not report passing');
    console.log('CALIBRATION_OK');
  },

  auth() {
    const out = run(PY, ['-m', 'pytest', 'tests/test_auth_v1.py', '-q'], BACKEND, 'auth tests');
    expectToken(out, 'passed', 'auth tests');
    console.log('AUTH_OK');
  },

  nurbs() {
    const out = run(PY, ['-m', 'pytest', 'tests/test_nurbs_v1.py', '-q'], BACKEND, 'nurbs tests');
    expectToken(out, 'passed', 'nurbs tests');
    console.log('NURBS_OK');
  },

  cicd() {
    const workflow = read('.github/workflows/ci.yml');
    for (const marker of ['ruff check', 'mypy', 'pytest', 'typecheck', 'schema-sync']) {
      assert(workflow.includes(marker), `CI workflow missing: ${marker}`);
    }
    run('uv', ['run', 'ruff', 'check', '.', '../gpu_workers'], BACKEND, 'backend lint');
    run('uv', ['run', 'mypy', 'app'], BACKEND, 'backend types');
    const syncOut = run(PY, ['scripts/check_schema_sync.py'], BACKEND, 'schema sync');
    expectToken(syncOut, 'SCHEMA_SYNC_OK', 'schema sync');
    run('npm', ['run', 'typecheck'], FRONTEND, 'frontend typecheck');
    console.log('CICD_OK');
  },

  docs() {
    const deployment = read('docs/DEPLOYMENT.md');
    for (const marker of ['modal deploy', 'pgvector', 'lifecycle', 'AsyncPostgresSaver', 'RedisSaver']) {
      assert(deployment.includes(marker), `DEPLOYMENT.md missing: ${marker}`);
    }
    const plan = read('docs/PROJECT_PLAN.md');
    assert(plan.includes('v1.1'), 'PROJECT_PLAN.md not updated for v1.1');
    console.log('DOCS_OK');
  },
};

const name = process.argv[2];
assert(Boolean(checks[name]), `unknown check: ${name ?? '(none)'}`);
checks[name]();
