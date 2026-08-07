# Refactoring baselines

Captured before stage 0 changes on 2026-08-07 from commit `fbcbbd5`.

## Regression suite

Command:

```bash
uv run pytest -q
```

Result: `317 passed in 27.84s`.

## Coverage

Command:

```bash
uv run pytest -q \
  --cov=app \
  --cov=cli \
  --cov-branch \
  --cov-report=term
```

Result:

- statements: `9,533`;
- covered statements: `6,055`;
- branches: `2,864`;
- covered branches: `1,371`;
- combined branch coverage: `59.90%`.

This is an observation, not a minimum threshold. Coverage must not decrease as
a side effect of moving a module, but a project-wide percentage gate will only
be introduced after migrated modules have explicit unit and contract coverage.

## Compatibility contracts

Stage 0 records compact executable contracts for:

- FastAPI paths, methods, and canonical OpenAPI schema;
- Typer and argparse `--help` output for public operational entrypoints;
- SQLAlchemy tables, columns, foreign keys, indexes, and unique constraints.

The readable route/table summaries identify broad contract changes. Canonical
SHA-256 values detect changes inside request schemas, response schemas, column
types, constraints, defaults shown in CLI help, and operational flags without
committing multi-thousand-line snapshots.

Contract hashes are updated only when a reviewed behavior or interface change
is intentional. A refactor-only stage must preserve them.

## Tooling observations

`npm run build` passes on the captured frontend lockfile. `npm audit` currently
reports five pre-existing findings: three moderate and two high. They originate
from the existing Vite/esbuild, React Router, and PostCSS dependency graph.
Resolving the Vite chain requires a major upgrade, so dependency remediation is
tracked separately and is not mixed into a behavior-preserving backend refactor.

The GitHub OAuth token can push source changes but does not have the `workflow`
scope. Local pre-commit guardrails are active; a GitHub Actions workflow remains
deferred until that scope is explicitly granted.

Gitleaks uses its complete default ruleset. One known fake signing secret from
the media-storage test fixture is allowlisted by exact value and exact path;
generic API-key findings remain enabled everywhere else.
