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

## Pre-freeze specification correction 1.0.1 — discovered during CP-03

- The user confirmed the missing trusted read surface was a specification bug, not an
  experiment redesign.
- Added exactly one isolated trusted read tool:
  `get_customer_risk(customer_id) -> {customer_id, prior_exception_refunds_90d,
  trusted_records_conflict}`.
- `get_customer_risk` is mandatory before an otherwise-selected `REFUND` or `RESHIP`;
  risk thresholds and global policy precedence are unchanged.
- The two risk fields remain absent from `VisibleCase` and every unrelated read response.
- Updated spec version from 1.0.0 to 1.0.1 before test-set generation or freeze. No test
  data exists and no live scored calls have occurred.
- Updated contracts and oracle required-tool metadata test-first. The simulator, dataset,
  prompts, Jev questions/state, agents, telemetry, mocks, and documentation will consume
  this corrected interface in their normal checkpoints.

## CP-03 — Simulator — 2026-09-21

- Added isolated per-case simulator state, deterministic system-independent replacement
  IDs, all five trusted read tools, five terminal action tools, failure plans, exactly-one
  automatic retry for `temporary_error`, explicit persistent errors, and nanosecond tool
  telemetry.
- `get_customer_risk` is the only read response containing prior-refund count or trusted
  conflict; tests verify those keys are absent from tracking and other unrelated outputs.
- Action tools validate schema, visible identity, and terminal uniqueness only. A
  deliberately wrong refund executes without consulting the oracle, preserving observable
  policy failures.
- RED evidence: four simulator test modules failed collection because simulator modules
  did not exist.
- `uv run pytest tests/unit/simulator tests/integration/test_simulator_replay.py -v`:
  PASS, 14 tests.
- `uv run pytest -q`: PASS, 73 tests.
- `uv run ruff check .`: PASS.
- `git diff --check`: PASS.

## CP-04 — Development dataset generator — 2026-09-21

- Added scenario-first structured generation, curated template banks (15 shipping, 15
  duplicate-payment, 15 damage, 10 unsupported, and 10 each terse/polite/noisy/adversarial),
  deterministic perturbations, canonical JSON, recursive leakage checks, validation,
  manifests, and a hard pre-CP-13 test-freeze refusal.
- Generated exactly 60 dev cases with all eight categories, all five actions, all four
  issue types, unique case/semantic IDs, and oracle-recomputed labels/tool metadata.
- Autonomous gold actions include `get_customer_risk` in required-tool metadata.
- RED evidence: four dataset test modules failed collection because dataset modules did
  not exist.
- `uv run pytest tests/unit/dataset -q`: PASS, 17 tests with no warnings.
- `uv run fusebench dataset build-dev`: PASS, wrote 60 cases.
- Dev dataset SHA-256:
  `887151cf54a2f975f32ce6a6d97a5be4b597e4ffe90078203015cdb725930422`.
- Confirmed `data/test/cases.jsonl` does not exist.

## CP-05 — TypeSafe adapter — implementation complete, live gate pending — 2026-09-21

- Revalidated the interface against official TypeSafe documentation, the official SDK
  source, PyPI metadata, and offline inspection of installed `typesafe-sdk 0.7.0`; findings
  are in `docs/research/typesafe-interface-2026-09-21.md`.
- Current interface matches the spec: Bearer-authenticated System One endpoint,
  same-state batched Choice/Noul/Score questions, full probability/confidence fields,
  concrete response model, token usage, and `$42/1B` input-token pricing.
- Current concrete model is documented as `jev-1.13.0`; `jev-latest` resolves to it. The
  adapter records and enforces one concrete reported model per run. Exact primary pinning
  remains a pre-freeze live verification.
- Provider-boundary details: responses are Pydantic models in SDK 0.7.0, Score criteria
  are ordered sequences, Score legend/probability keys become integers, usage fields are
  typed optional despite being required by HTTP docs, and the SDK default timeout is 10s.
  FuseBench passes 30s explicitly and fails closed on missing input usage.
- Added five-question information fan-out including `need_customer_risk`, four terminal
  questions, strict state allowlists/leakage checks, payload hashing, parsing, 3-attempt SDK
  retry policy, concrete-model drift detection, and atomic `$1.00` budget accounting.
- Pinned `typesafe-sdk==0.7.0` in project metadata.
- RED evidence: five Jev/provider/budget test modules failed collection because the
  implementation modules did not exist.
- Mocked targeted suite: PASS, 17 tests.
- Full suite: PASS, 107 tests with one live contract skipped.
- `uv run ruff check .`: PASS.
- Blocking live gate: `TYPESAFE_API_KEY` is absent, so the required tiny live System One
  call has not run. No TypeSafe credit has been consumed.
