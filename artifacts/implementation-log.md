# FuseBench implementation log

This append-only log records checkpoint deliverables, validation commands, results, and
external-interface deviations. The authoritative build requirements remain in
`spec(4).md`.

## Planning and repository initialization — 2026-09-21

- Added the authoritative specification and the CP-00–CP-12 implementation plan.
- Initialized `main`, configured `origin` as `https://github.com/0xnotdev/fusebench.git`,
  and pushed the planning commit.
- Tooling deviation: the Superpowers SDD bookkeeping scripts require Bash, which is not
  available on this Windows host. Their ignored ledger/workspace protocol is being
  maintained manually; benchmark behavior is unaffected.
- Planning ruling: `EXPERIMENT.md` is intentionally not created in CP-00 because section
  43 requires it to be generated at CP-13 freeze. Creating preregistration content now
  would conflict with the source of truth.

## CP-00 — Repository bootstrap — 2026-09-21

- Created the Python 3.11+ uv project, complete package skeleton, Typer CLI command
  surface, environment settings, ignore rules, README, and exact canonical `spec.md`
  copy.
- `uv sync`: PASS; 50 packages resolved and the local package installed.
- RED evidence: bootstrap tests failed during collection with
  `ModuleNotFoundError: No module named 'fusebench'` before package creation.
- `uv run pytest tests/unit/test_cli.py tests/unit/test_spec_copy.py -v`: PASS, 3 tests.
- `uv run pytest -v`: PASS, 3 tests.
- `uv run ruff check .`: PASS.
- Deviation: the lock resolver reported an upstream `typesafe-sdk` metadata warning for
  a quoted version specifier; uv normalized it without changing the requested package.

## CP-01 — Contracts — 2026-09-21

- Added exact action/issue/tool/error/failure enums; strict immutable Pydantic case,
  tool, event, decision, and normalized run-record contracts; and explicit probability
  validation/renormalization.
- RED evidence: six contract test modules failed collection because the contract modules
  did not exist.
- `uv run pytest tests/unit/contracts -v`: PASS, 25 tests.
- Initial full verification found 10 Ruff-only findings (Python 3.11 `StrEnum`, line
  wrapping, and one assertion order). Root cause was the configured modernization/style
  rule set, not behavioral failures; those sources were corrected.
- `uv run ruff check .`: PASS.
- `uv run pytest -v`: PASS, 28 tests.
- No benchmark-semantic deviations.

## CP-02 — Policy and deterministic oracle — 2026-09-21

- Added the frozen human-readable policy, pure deterministic oracle, minimal required
  read-tool metadata, autonomous-action allowlists, reason codes, and the exact frozen
  business-loss matrix.
- RED evidence: policy tests failed collection because `policy.oracle` and `policy.loss`
  did not exist.
- `uv run pytest tests/unit/policy -v`: PASS, 28 tests covering every stated threshold,
  issue rule, persistent data failure, and global precedence interaction.
- `uv run pytest -q`: PASS, 56 tests.
- `uv run ruff check .`: PASS.
- Pre-CP-03 design issue: `prior_exception_refunds_90d` and the generic
  `trusted_records_conflict` are hidden oracle inputs, but sections 11 and 16 specify no
  read tool or trusted observation that can expose them to either scored system. This is
  not silently resolved in CP-02 because doing so would change the experiment interface.
