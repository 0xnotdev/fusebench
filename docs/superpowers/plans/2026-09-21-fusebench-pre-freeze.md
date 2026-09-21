# FuseBench Pre-Freeze Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and validate FuseBench through CP-12, producing an auditable 60-case development evaluation while stopping before creation of the frozen test set.

**Architecture:** Implement the benchmark as small Python modules with Pydantic contracts at the center, a deterministic oracle and simulator beneath two provider-agnostic agents, and append-only records consumed by pure metrics/reporting code. Live Codex App Server and TypeSafe adapters remain at the boundary; all ordinary tests use deterministic mocks, and benchmark-visible payloads pass through explicit allowlisted serializers.

**Tech Stack:** Python 3.11+, uv, Pydantic v2, Typer, asyncio, httpx, typesafe-sdk, NumPy, pandas, SciPy, matplotlib, pytest, pytest-asyncio, Ruff.

**Spec:** `spec(4).md`

## Global Constraints

- `spec(4).md` is authoritative; MUST, MUST NOT, and INVARIANT requirements are non-negotiable.
- Implement checkpoints in order and do not begin CP-13 or generate `data/test/cases.jsonl`.
- Use deterministic Python only for gold labels; neither Terra nor Jev may generate or validate them.
- Never expose hidden truth, evaluator metadata, dataset files, oracle code, or gold labels to either provider.
- Use exactly five terminal actions: `REFUND`, `RESHIP`, `REQUEST_INFO`, `WAIT`, `ESCALATE`.
- Use exactly five trusted read tools after the pre-freeze 1.0.1 correction; `get_customer_risk(customer_id)` is the sole model-visible source for prior-refund count and trusted-record conflict and is mandatory before an otherwise-selected `REFUND` or `RESHIP`.
- Use fresh Terra state per case and stateless Jev calls; model-side web access is disabled.
- Use mocks before live providers and minimize paid/live calls to contract validation and CP-12 dev evaluation.
- Preserve raw events, canonicalize JSON with sorted keys and finite values, hash provider-bound payloads, and redact secrets.
- Pin Terra to `gpt-5.6-terra` with `medium` reasoning; do not fall back to another model or effort.
- Guard Jev usage with a default `$1.00` hard cap and atomic usage accounting.
- Work and generated artifacts remain under `D:\fusebench`.
- Commit each checkpoint only after its PASS commands succeed; push sequential commits to `https://github.com/0xnotdev/fusebench.git`.

## Review Focus

- Malformed or partially missing provider events must fail closed without leaking secrets or manufacturing a scored action; CP-05/CP-06 parser tests cover this.
- Windows path and process behavior must preserve per-case filesystem isolation; CP-07 runs an external canary denial test.
- Resumed runs must not duplicate completed `(run_id, case_id, system, repetition)` records; CP-12 scheduler/recorder tests cover this.
- Temporary and persistent tool failures must have identical simulator transitions for both systems; CP-03 integration tests cover retry accounting and reset behavior.
- Probability edge cases (`NaN`, infinity, missing keys, sums outside tolerance, all-zero distributions) must produce deterministic invalid/fallback records; CP-01 and CP-08 tests cover this.

---

### Task 1: CP-00 — Repository Bootstrap

**Files:**
- Create: `spec.md` as a byte-for-byte copy of `spec(4).md`
- Create: `pyproject.toml`, `.python-version`, `.gitignore`, `.env.example`, `README.md`, `EXPERIMENT.md`
- Create: `src/fusebench/__init__.py`, `src/fusebench/cli.py`, `src/fusebench/config.py`, `src/fusebench/constants.py`
- Create: package `__init__.py` files for every spec directory
- Create: `tests/unit/test_cli.py`, `tests/unit/test_spec_copy.py`
- Create: `artifacts/implementation-log.md`

**Interfaces:**
- Consumes: authoritative bytes from `spec(4).md`; Python 3.11+; `uv` executable.
- Produces: `fusebench.cli:app`, `fusebench.config:Settings`, version `fusebench.__version__`, and an installable `fusebench` console script.

- [ ] **Step 1: Initialize Git metadata and remote**

Run `git init -b main`, set `origin` to the requested GitHub URL, and configure no repository-local secrets.

- [ ] **Step 2: Write bootstrap tests first**

```python
from typer.testing import CliRunner
from fusebench.cli import app

def test_cli_help_lists_preflight() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "preflight" in result.stdout

def test_canonical_spec_copy_matches_authority() -> None:
    assert Path("spec.md").read_bytes() == Path("spec(4).md").read_bytes()
```

- [ ] **Step 3: Run tests and observe RED**

Run: `uv run pytest tests/unit/test_cli.py tests/unit/test_spec_copy.py -v`

Expected: collection/import failure because the package and canonical spec do not exist.

- [ ] **Step 4: Create the package, metadata, CLI skeleton, docs, and exact spec copy**

`pyproject.toml` defines Python `>=3.11`, runtime/dev dependencies, Ruff, pytest, and `fusebench = "fusebench.cli:app"`. `Settings` loads environment values without reading Codex account tokens. The CLI registers all commands from section 46 but unimplemented commands return a clear checkpoint-not-ready error.

- [ ] **Step 5: Sync and verify CP-00**

Run: `uv sync`

Expected: dependency resolution succeeds and `uv.lock` is created.

Run: `uv run pytest -v`

Expected: PASS.

Run: `uv run ruff check .`

Expected: PASS.

- [ ] **Step 6: Record, commit, and push**

Append the implementation summary and exact command results to `artifacts/implementation-log.md`; commit as `chore: bootstrap FuseBench repository`; push `main` to `origin`.

### Task 2: CP-01 — Contracts

**Files:**
- Create: `src/fusebench/contracts/actions.py`, `case.py`, `tools.py`, `events.py`, `decisions.py`, `results.py`
- Test: `tests/unit/contracts/test_actions.py`, `test_case.py`, `test_decisions.py`, `test_events.py`, `test_results.py`, `test_tools.py`

**Interfaces:**
- Consumes: Pydantic v2 and action names from the spec.
- Produces: immutable domain contracts, `normalize_action_probabilities`, `DecisionResult`, `RunRecord`, read/action input/output schemas, `FailurePlan`, and failure taxonomy enums.

- [ ] **Step 1: Write failing schema tests**

Tests assert exact enum values, visible/hidden separation, rejection of extra fields on provider-visible models, five-key probability validation, `[0.98, 1.02]` renormalization, invalid distribution flags, finite numeric fields, and JSON round trips.

- [ ] **Step 2: Observe RED**

Run: `uv run pytest tests/unit/contracts -v`

Expected: import failures for missing contract modules.

- [ ] **Step 3: Implement minimal Pydantic contracts**

Use `ConfigDict(extra="forbid")`, string enums, explicit optional/default fields, and a normalization result that preserves original sum and invalidity without inventing probabilities for all-zero input.

- [ ] **Step 4: Verify CP-01**

Run: `uv run pytest tests/unit/contracts -v`

Expected: PASS.

Run: `uv run pytest -v && uv run ruff check .`

Expected: PASS.

- [ ] **Step 5: Record, commit, and push**

Commit as `feat: add benchmark contracts`; push sequentially.

### Task 3: CP-02 — Frozen Policy and Deterministic Oracle

**Files:**
- Create: `src/fusebench/policy/policy.md`, `oracle.py`, `loss.py`
- Test: `tests/unit/policy/test_oracle.py`, `test_loss.py`, `test_policy_text.py`

**Interfaces:**
- Consumes: `BenchmarkCase`, `HiddenTruth`, `Action`, exact section 9 semantics.
- Produces: `OracleDecision(action, minimal_required_read_tools, allowed_autonomous_actions)`, `decide(case)`, and frozen business-loss lookup.

- [ ] **Step 1: Write failing policy boundary and precedence tests**

Cover amount `10000/10001`, prior refunds `1/2`, trusted conflict, shipping movement `4/5`, inventory `0/1`, delivered conflict, duplicate settled/pending combinations, damage evidence absent/invalid/valid, persistent trusted-source failure, and `OTHER`. Include interaction tests proving every global rule beats issue-specific eligibility.

- [ ] **Step 2: Observe RED**

Run: `uv run pytest tests/unit/policy -v`

Expected: missing oracle/loss imports.

- [ ] **Step 3: Implement policy, oracle, and loss matrix**

The oracle is pure and deterministic. It returns the minimal trusted reads needed to establish the action, and autonomous allowlists contain side-effect actions only where safe. Missing customer-suppliable evidence yields `REQUEST_INFO`; persistent required backend failure yields `ESCALATE`.

- [ ] **Step 4: Verify CP-02**

Run: `uv run pytest tests/unit/policy -v`

Expected: PASS for every boundary and precedence case.

Run: `uv run pytest -v && uv run ruff check .`

Expected: PASS.

- [ ] **Step 5: Record, commit, and push**

Commit as `feat: implement frozen policy oracle`; push sequentially.

### Task 4: CP-03 — Simulator and Tool Runtime

**Files:**
- Create: `src/fusebench/simulator/environment.py`, `fixtures.py`, `tool_runtime.py`, `failures.py`
- Test: `tests/unit/simulator/test_environment.py`, `test_failures.py`, `test_tool_runtime.py`
- Test: `tests/integration/test_simulator_replay.py`

**Interfaces:**
- Consumes: contract tool schemas, immutable `BenchmarkCase`, `FailurePlan`.
- Produces: `SimulatorEnvironment.from_case(case, seed)`, `ToolRuntime.call_read`, `ToolRuntime.execute_action`, all five isolated read responses including customer risk, immutable telemetry events, exactly-one infrastructure retry, and deterministic replacement IDs independent of system.

- [ ] **Step 1: Write failing simulator tests**

Assert hidden-to-tool mapping, schema/identity validation, customer risk appears only from `get_customer_risk`, read idempotency, action side effects, duplicate terminal rejection, deliberately wrong actions still execute, temporary retry success, persistent failure surfacing, infrastructure retry separation, and semantic equality after paired resets.

- [ ] **Step 2: Observe RED**

Run: `uv run pytest tests/unit/simulator tests/integration/test_simulator_replay.py -v`

Expected: missing simulator imports.

- [ ] **Step 3: Implement environment and runtime**

Never import the oracle from action execution. Tool clocks use `perf_counter_ns`; event payloads include attempts, retry flags, durations, and structured error kinds.

- [ ] **Step 4: Verify CP-03**

Run: `uv run pytest tests/unit/simulator tests/integration/test_simulator_replay.py -v`

Expected: PASS, including deterministic replay.

Run: `uv run pytest -v && uv run ruff check .`

Expected: PASS.

- [ ] **Step 5: Record, commit, and push**

Commit as `feat: add deterministic simulator`; push sequentially.

### Task 5: CP-04 — Deterministic Development Dataset

**Files:**
- Create: `src/fusebench/dataset/scenarios.py`, `messages.py`, `perturbations.py`, `generator.py`, `validation.py`, `freeze.py`
- Create: `data/dev/cases.jsonl`, `data/dev/manifest.json`
- Test: `tests/unit/dataset/test_messages.py`, `test_generator.py`, `test_validation.py`, `test_serialization.py`

**Interfaces:**
- Consumes: oracle, case contracts, seeded `random.Random`.
- Produces: `build_dev_dataset(seed) -> list[BenchmarkCase]`, canonical JSONL, manifest counts/hash, model-visible serialization that exposes only `VisibleCase`, and required-tool metadata that includes `get_customer_risk` before autonomous gold actions.

- [ ] **Step 1: Write failing dataset tests**

Assert 60 dev cases, all eight categories represented, all five actions represented, unique IDs, oracle recomputation equality, deterministic bytes for a fixed seed, at least the required template-family counts, adversarial snippets retained as untrusted text, and recursive absence of forbidden evaluator keys.

- [ ] **Step 2: Observe RED**

Run: `uv run pytest tests/unit/dataset -v`

Expected: missing dataset modules.

- [ ] **Step 3: Implement scenario-first generation**

Create structured hidden states, lock oracle results, then render and perturb messages. `freeze.py` exposes helpers but refuses test creation unless an explicit CP-13 freeze command is used; no test dataset is created in this plan.

- [ ] **Step 4: Build and validate the dev set**

Run: `uv run fusebench dataset build-dev`

Expected: exactly 60 validated cases and a manifest containing seed, SHA-256, category/action/issue counts.

Run: `uv run pytest tests/unit/dataset -v && uv run pytest -v && uv run ruff check .`

Expected: PASS.

- [ ] **Step 5: Record, commit, and push**

Commit as `feat: generate deterministic dev dataset`; push sequentially.

### Task 6: CP-05 — TypeSafe Jev Adapter

**Files:**
- Create: `src/fusebench/providers/base.py`, `typesafe_jev.py`
- Create: `src/fusebench/jev/questions.py`, `state.py`, `parsing.py`
- Create: `src/fusebench/benchmark/budget.py`
- Test: `tests/unit/providers/test_typesafe_jev.py`, `tests/unit/jev/test_questions.py`, `test_state.py`, `test_parsing.py`, `tests/unit/benchmark/test_budget.py`
- Test: `tests/contract/test_typesafe_live.py`

**Interfaces:**
- Consumes: provider-visible case payload, policy bytes, TypeSafe SDK/current official API, `JEV_HARD_CAP_USD`.
- Produces: `JevDecisionProvider.infer_information_needs`, `infer_terminal_action`, batched `Choice/Noul/Score` questions, parsed full action probabilities, model/usage/latency records, and atomic budget ledger.

- [ ] **Step 1: Revalidate current TypeSafe official interface**

Inspect installed SDK signatures and current official docs. Record concrete deviations from section 5 in the implementation log; adapt only this provider boundary.

- [ ] **Step 2: Write failing mock/parser/budget tests**

Tests cover batched initial questions including `need_customer_risk`, structured paths, explicit prompt-injection boundary, success parsing, missing/unknown answers, malformed probabilities, usage absence, model-version capture/change, budget precheck, atomic update, and secret redaction.

- [ ] **Step 3: Observe RED**

Run: `uv run pytest tests/unit/providers/test_typesafe_jev.py tests/unit/jev tests/unit/benchmark/test_budget.py -v`

Expected: missing adapter modules.

- [ ] **Step 4: Implement adapter with injected transport**

The default transport wraps current `TypeSafeClient`; unit tests inject a fake. Retry only network/5xx failures, maximum three attempts; semantic parse failures are not retried.

- [ ] **Step 5: Verify mocked CP-05 and conditionally run one tiny live contract call**

Run: `uv run pytest tests/unit/providers/test_typesafe_jev.py tests/unit/jev tests/unit/benchmark/test_budget.py -v`

Expected: PASS.

If `TYPESAFE_API_KEY` is present, run: `uv run pytest tests/contract/test_typesafe_live.py -v -m live`

Expected: one call passes and records Choice/Noul/Score, concrete model, and usage. If the key is absent or the current API is incompatible, mark CP-05 live status unresolved and do not fake PASS.

- [ ] **Step 6: Verify, record, commit, and push**

Run full tests and Ruff; commit as `feat: add TypeSafe Jev provider`; push sequentially.

### Task 7: CP-06 — Codex App Server Adapter

**Files:**
- Create: `src/fusebench/providers/codex_app_server.py`, `codex_protocol.py`
- Create: `src/fusebench/prompts/terra_agent.md`, `terra_response.md`
- Create: `schemas/codex/.gitkeep`
- Test: `tests/unit/providers/test_codex_protocol.py`, `test_codex_app_server.py`
- Test: `tests/contract/test_codex_app_server_live.py`

**Interfaces:**
- Consumes: newline-delimited JSON-RPC App Server, generated installed-version schemas, Terra model/effort settings, per-case sandbox path.
- Produces: one managed App Server process, initialize/initialized handshake, model/account capability checks, fresh thread/session creation, structured-loop or dynamic-tool protocol selection, output-schema parsing, raw token-usage events, timeouts, and usage-limit classification.

- [ ] **Step 1: Use current official Codex documentation and generated schemas**

Generate schemas under `schemas/codex/`, hash them, identify exact request/event shapes, and record any spec drift. Do not guess undocumented fields.

- [ ] **Step 2: Write failing protocol tests with a fake subprocess**

Cover request IDs, notifications, concurrent event routing, process death, malformed JSON, timeout, output-schema success/failure, token event capture, model mismatch/reroute, and no semantic retries.

- [ ] **Step 3: Observe RED**

Run: `uv run pytest tests/unit/providers/test_codex_protocol.py tests/unit/providers/test_codex_app_server.py -v`

Expected: missing adapter imports.

- [ ] **Step 4: Implement lifecycle and selected tool protocol**

Prefer dynamic tools only if the live contract proves them stable; otherwise freeze `structured_loop` for both dev systems. Every case starts a fresh thread rooted in its empty sandbox with approvals `never`, network disabled, and restricted read access.

- [ ] **Step 5: Verify mocked and live CP-06**

Run mocked tests first. Then run one minimal live contract case confirming Terra, medium effort, structured output, token usage, and selected protocol.

Expected: PASS or a documented blocking current-interface incompatibility; never substitute another model.

- [ ] **Step 6: Verify, record, commit, and push**

Run full tests and Ruff; commit as `feat: add Codex App Server provider`; push sequentially.

### Task 8: CP-07 — Codex Filesystem Isolation

**Files:**
- Create: `src/fusebench/providers/isolation.py`
- Create: `scripts/preflight.ps1`, `scripts/preflight.sh`
- Test: `tests/unit/providers/test_isolation.py`
- Test: `tests/contract/test_codex_isolation_live.py`
- Generate when live: `artifacts/preflight/isolation.json`

**Interfaces:**
- Consumes: Codex provider, case sandbox root under artifacts, restricted-read schema supported by installed App Server.
- Produces: unique empty per-case sandbox, external canary, denial evidence, logged unexpected file/shell exploration, and a hard boolean freeze gate.

- [ ] **Step 1: Write failing sandbox construction tests**

Assert resolved paths stay under `artifacts/case_sandboxes`, no symlink/reparse escape, no benchmark files copied in, network disabled, approval `never`, and readable roots contain only the case sandbox.

- [ ] **Step 2: Observe RED and implement safe construction**

Run unit tests for RED, implement, and rerun for GREEN.

- [ ] **Step 3: Run the live canary attack**

Create a randomized secret outside the readable root, ask Terra to locate `ground_truth.py`, `cases.jsonl`, `oracle.py`, and return the canary; verify access is denied/unavailable and store redacted evidence.

Expected: model cannot read the canary or benchmark paths. Any leak blocks all later live dev execution.

- [ ] **Step 4: Verify, record, commit, and push**

Run full tests and Ruff; commit as `security: enforce Codex case isolation`; push sequentially.

### Task 9: CP-08 — Terra-Only Agent

**Files:**
- Create: `src/fusebench/agents/base.py`, `terra_only.py`
- Test: `tests/unit/agents/test_terra_only.py`
- Test: `tests/integration/test_terra_only_smoke.py`

**Interfaces:**
- Consumes: `TerraDecisionProvider`, `ToolRuntime`, visible case, policy, read-tool contracts.
- Produces: bounded six-turn/eight-read decision loop, maximum two requests per read tool, raw/executed action separation, action execution, probabilities, reason code, telemetry, loop-limit and invalid-output fallbacks.

- [ ] **Step 1: Write failing agent tests**

Use scripted fake providers for every gold action, the mandatory customer-risk check before autonomous actions, required/unnecessary/repeated tools, bad IDs, unknown tools, probability tolerance/invalid/all-zero cases, provider errors, six-turn/eight-read limits, and persistent failure escalation.

- [ ] **Step 2: Observe RED**

Run: `uv run pytest tests/unit/agents/test_terra_only.py tests/integration/test_terra_only_smoke.py -v`

Expected: missing agent implementation.

- [ ] **Step 3: Implement bounded loop**

The agent never imports the oracle, never receives hidden data, and executes the selected top action through the simulator. Invalid/no raw decision counts incorrect while simulator fallback executes `ESCALATE`.

- [ ] **Step 4: Verify CP-08**

Run targeted and full suites plus Ruff; expect PASS.

- [ ] **Step 5: Record, commit, and push**

Commit as `feat: implement Terra-only agent`; push sequentially.

### Task 10: CP-09 — Terra + Jev Hybrid Agent

**Files:**
- Create: `src/fusebench/agents/terra_jev.py`
- Test: `tests/unit/agents/test_terra_jev.py`
- Test: `tests/integration/test_terra_jev_smoke.py`

**Interfaces:**
- Consumes: `JevDecisionProvider`, threshold setting, shared policy, visible case, `ToolRuntime`.
- Produces: one batched information-needs request, concurrent independent reads above frozen dev threshold, explicit observation errors, one terminal request, auxiliary diagnostics, raw/executed action and telemetry.

- [ ] **Step 1: Write failing hybrid tests**

Assert one initial batch including `need_customer_risk`, `>=0.50` threshold behavior, concurrent selected reads, zero-read path, persistent-error state, action Choice alone controls normal execution, auxiliary judgments never override action, two normal Jev calls, the permitted third decision call when an autonomous candidate lacks a prior risk read, complete probability capture, and no hidden/evaluator keys.

- [ ] **Step 2: Observe RED**

Run: `uv run pytest tests/unit/agents/test_terra_jev.py tests/integration/test_terra_jev_smoke.py -v`

Expected: missing hybrid agent.

- [ ] **Step 3: Implement hybrid flow and verify**

Run targeted tests, then full suite and Ruff; expect PASS.

- [ ] **Step 4: Record, commit, and push**

Commit as `feat: implement Terra Jev hybrid`; push sequentially.

### Task 11: CP-10 — Shared Terra Responder

**Files:**
- Create: `src/fusebench/agents/responder.py`
- Test: `tests/unit/agents/test_responder.py`
- Test: `tests/integration/test_response_action_lock.py`

**Interfaces:**
- Consumes: only `customer_message`, immutable `executed_action`, and `action_result`.
- Produces: short unscored customer response and separate response latency/usage, with no action mutation path.

- [ ] **Step 1: Write failing responder tests**

Assert allowlisted input excludes policy/hidden/gold fields, output cannot express or mutate an action, responder failure leaves decision record unchanged, and both agents call the same responder implementation.

- [ ] **Step 2: Observe RED, implement, and verify**

Run targeted tests for RED, implement the provider call contract, rerun GREEN, then full suite and Ruff.

- [ ] **Step 3: Record, commit, and push**

Commit as `feat: add shared response stage`; push sequentially.

### Task 12: CP-11 — Metrics, Statistics, Reports, and Plots

**Files:**
- Create: `src/fusebench/metrics/correctness.py`, `calibration.py`, `coverage.py`, `consistency.py`, `efficiency.py`, `statistics.py`, `report.py`
- Create: `src/fusebench/plots/calibration.py`, `risk_coverage.py`, `latency.py`, `cost.py`
- Test: `tests/unit/metrics/test_correctness.py`, `test_calibration.py`, `test_coverage.py`, `test_consistency.py`, `test_efficiency.py`, `test_statistics.py`, `test_report.py`

**Interfaces:**
- Consumes: validated normalized `RunRecord` pairs only; no provider calls.
- Produces: exact section 20–31 metrics, threshold sweep, category/action/issue tables, 10,000 paired bootstrap samples, McNemar results, CSV/JSON/Markdown outputs, and four headline plots.

- [ ] **Step 1: Write failing hand-calculated golden tests**

Pin accuracy, unsafe rate and denominators, end-to-end success, false escalation, Brier, NLL clipping, 10-bin ECE/counts, high-confidence error, coverage/error thresholds, necessary-tool recall with empty-set N/A, extras, business loss, flip rate, pairwise disagreement, confidence variance, token cost, paired bootstrap shape/seed, McNemar contingency, and missing-pair rejection.

- [ ] **Step 2: Observe RED**

Run: `uv run pytest tests/unit/metrics -v`

Expected: missing metric modules.

- [ ] **Step 3: Implement pure metrics and outputs**

Reports use neutral language and distinguish actual spend, promotional Jev cost, and Terra normalized API-equivalent cost. Plots read analysis tables rather than providers/raw secrets.

- [ ] **Step 4: Verify CP-11**

Run targeted suite, full suite, and Ruff; expect PASS.

- [ ] **Step 5: Record, commit, and push**

Commit as `feat: add benchmark metrics and reporting`; push sequentially.

### Task 13: CP-12 — Runner, Preflight, Dev Evaluation, and Tuning Freeze

**Files:**
- Create: `src/fusebench/benchmark/runner.py`, `scheduler.py`, `recorder.py`, `manifest.py`, `preflight.py`
- Modify: `src/fusebench/cli.py`, `README.md`
- Create: `artifacts/freeze/dev_tuning_log.md`
- Test: `tests/unit/benchmark/test_scheduler.py`, `test_recorder.py`, `test_manifest.py`, `test_preflight.py`, `test_runner.py`
- Test: `tests/integration/test_mocked_end_to_end.py`, `test_architecture_boundaries.py`, `test_payload_leakage.py`
- Generate: `artifacts/preflight/report.json`, development run artifacts only

**Interfaces:**
- Consumes: 60-case dev dataset, both agents, provider adapters, budget/isolation gates, deterministic run seed.
- Produces: paired interleaved schedule, immediate append/flush, unique completion keys, safe resume, raw provider folders, normalized/checksummed records, provider retry classification, preflight report, dev evaluation, dev tuning log, and CP-00–CP-12 readiness report data.

- [ ] **Step 1: Write failing runner/integrity tests**

Assert paired randomized order with adjacent systems, concurrency one, equivalent simulator resets, no silent overwrite, deterministic resume, append-only JSONL, per-record/file checksums, secret redaction, raw artifact layout, model-version consistency, usage-limit checkpoint/stop, architecture import ban on `policy.oracle`, allowlisted provider payloads, and refusal to run without passing preflight/isolation.

- [ ] **Step 2: Observe RED**

Run: `uv run pytest tests/unit/benchmark tests/integration/test_mocked_end_to_end.py tests/integration/test_architecture_boundaries.py tests/integration/test_payload_leakage.py -v`

Expected: missing runner modules and CLI behavior.

- [ ] **Step 3: Implement runner, recorder, manifest, preflight, and CLI wiring**

Provider retries are at most three for network/5xx only. The dev runner never reads or creates test data. Results include raw/executed actions, full probabilities, tool/usage/latency/error fields, provider versions, and hashes.

- [ ] **Step 4: Run full mocked validation**

Run: `uv run pytest -v`

Expected: PASS with no live provider dependency.

Run: `uv run ruff check .`

Expected: PASS.

- [ ] **Step 5: Run live preflight**

Run: `uv run fusebench preflight`

Expected: Python/dependencies/artifact writes pass; Codex App Server initializes, authenticates, lists Terra, accepts medium effort, returns schema/token usage, and passes isolation; TypeSafe performs one tiny parsed request with usage if a key is available. Any mandatory failure remains a reported blocker rather than being overridden.

- [ ] **Step 6: Run 60-case development evaluation only when preflight gates pass**

Run: `uv run fusebench dev-run --systems terra_only,terra_jev`

Expected: 120 complete auditable system-case records, no critical provider/parser errors, no data leaks, budget cap respected. Never read or create `data/test/cases.jsonl`.

- [ ] **Step 7: Tune only permitted dev settings and revalidate**

Permitted changes are prompt wording, Jev question wording, information threshold, tool descriptions, provider protocol fixes, and state formatting. Record every change with before/after rationale in `artifacts/freeze/dev_tuning_log.md`; prohibit case-ID/phrase hacks, oracle imports, scenario deletion, and test-data access. Rerun affected tests and final dev evaluation only when justified.

- [ ] **Step 8: Run pre-freeze integrity audit**

Verify model-visible payloads, filesystem isolation, policy precedence, action-tool non-enforcement, test-set absence, provider version capture, dev dataset hash, all tests, Ruff, and Git cleanliness. Confirm CP-13 commands have not run.

- [ ] **Step 9: Record, commit, and push CP-12**

Commit as `feat: complete pre-freeze dev evaluation`; push sequentially.

- [ ] **Step 10: Stop and report**

Produce the requested CP-00–CP-12 readiness report with checkpoint status, exact test commands/results, Codex/Terra and Jev status, isolation evidence, dev-set metrics/tuning, deviations/blockers, and a yes/no assessment of every pre-freeze requirement. Do not run `fusebench freeze create`, do not create the frozen test set, and do not begin CP-13.

## Plan Self-Review Record

- Spec coverage: sections 0–80 were mapped to CP-00–CP-12 tasks; freeze, primary, repeatability, and final analysis execution remain intentionally out of scope until explicit authorization.
- Placeholder scan: no deferred implementation placeholders are used; external live compatibility is an explicit checkpoint gate rather than hidden future work.
- Type consistency: contracts flow from CP-01 into oracle/simulator, then agents, normalized records, metrics, and runner without provider-to-metrics coupling.
- Review focus: each listed failure mode is assigned to a concrete test task above.
