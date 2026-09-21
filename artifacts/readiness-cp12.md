# FuseBench CP-00–CP-12 readiness report

Date: 2026-09-22 (Asia/Calcutta)

Authoritative specification: `spec(4).md`, pre-freeze version 1.0.1

Final development run: `dev-cp12-v2`

Freeze status: **not started**

## Readiness decision

**READY FOR EXPLICIT CP-13 AUTHORIZATION.** Every CP-00–CP-12 pass condition and every
pre-freeze requirement in the authoritative specification is satisfied. The frozen test
set has not been generated, inspected, or executed. The primary benchmark, repeatability
run, and primary analysis have not run.

## Checkpoint status

| Checkpoint | Status | Evidence |
|---|---|---|
| CP-00 Repository bootstrap | PASS | uv project, package/CLI, lockfile, tests/lint; commit `755b3af` |
| CP-01 Contracts | PASS | strict action/case/tool/event/decision/result schemas; commit `ae45565` |
| CP-02 Policy and oracle | PASS | threshold/precedence tests and frozen loss matrix; commit `42c1544` |
| CP-03 Simulator | PASS | five reads/five actions, deterministic failures/retry/telemetry; commits `dfdf353`, `110e071` |
| CP-04 Dev dataset | PASS | deterministic 60 cases, quotas/uniqueness/oracle validation; commit `c14e5c4` |
| CP-05 TypeSafe adapter | PASS | SDK wrapper, batched questions, strict parsing, budget, live contract; commits `9028b1b`, `5908270` |
| CP-06 Codex adapter | PASS | exact Terra/medium App Server contract and dynamic tools; commits `f79111c` |
| CP-07 Isolation | PASS | live canary and benchmark-path attack blocked; commit `3063b35` |
| CP-08 Terra-only | PASS | bounded dynamic-tool agent, safety override, seven mocked scenarios; commit `f17fe42` |
| CP-09 Terra+Jev | PASS | batched information/terminal calls, concurrent reads, risk recheck; commit `ba18ea1` |
| CP-10 Shared responder | PASS | fresh no-tool thread, action immutable, separate telemetry; commit `e437e6e` |
| CP-11 Metrics/reporting | PASS | golden metrics, paired statistics, tables and four plots; commit `211764c` |
| CP-12 Dev evaluation | PASS | preflight, audited 120-record paired run, analysis, recovery; commits `29ef879`, `eb2e491` plus this readiness commit |

## Final validation results

- `uv sync`: PASS.
- `uv run pytest -q`: PASS — 213 offline tests; 3 live tests deliberately deselected.
- `uv run ruff check .`: PASS.
- `uv run fusebench preflight`: PASS.
  - provider live contracts: 3 passed;
  - simulator contract/replay gate: 14 passed;
  - all 11 report checks passed.
- `uv run fusebench dev-run --systems terra_only,terra_jev --run-id dev-cp12-v2
  --seed 20260921 --information-threshold 0.50`: PASS — 120/120 durable records.
- Run checksum verification: PASS.
- Dev input manifest verification: PASS, no drift.
- Git secret search and final artifact credential scan: PASS, zero credential occurrences.
- `data/test/cases.jsonl`: absent.
- The final v2 raw, normalized, budget, and analysis artifacts are included in this
  readiness commit; the non-authoritative v1 runtime artifacts remain ignored locally.
- `.gitattributes` enforces LF for text and binary handling for PNGs so a Windows checkout
  cannot rewrite checksummed evidence bytes.

## Codex / Terra integration

- Exact model: `gpt-5.6-terra`; provider fallback disabled and mismatches abort.
- Exact scored-turn reasoning effort: `medium`.
- Selected and consistently used tool protocol: `dynamic_tools`.
- Codex/App Server: `codex-cli 0.155.0-alpha.9.2`; final live user agent reports
  `Codex Desktop/0.155.0-alpha.9.2`.
- Generated stable schema SHA-256:
  `5a4d50ed04afa9cd1b383d011f67ec055960a35ca7fdeab222ed65e70fca8f0b`.
- Generated experimental schema SHA-256:
  `48368bf71d00498557245665dd4581f9b0d5381561a2c8ba1ef4eb26ea4a1632`.
- Fresh isolated thread per case and per shared response; full turn events and token usage
  retained, including semantic invalid-output cases.
- No response-stage failures occurred in the final dev run.

## TypeSafe / Jev integration

- SDK: `typesafe-sdk==0.7.0`.
- Alias probe reported `jev-1.13.0`; a separate tiny live call proved TypeSafe accepts
  `jev-1.13.0` as the request model. FuseBench is pinned to that exact version.
- Final run: 120 request states, 120 provider responses, all reported `jev-1.13.0`.
- No model drift, HTTP, timeout, usage-limit, or parser errors.
- Final dev usage: 152,099 input tokens; estimated promotional-credit cost
  `$0.006388158`, below the `$1.00` hard cap.
- All provider request/response artifacts are redacted and checksummed.

## Filesystem and isolation verification

- Initial broad-read live attack during CP-07 failed and blocked progress as required.
- Final design disables every built-in shell, unified execution, file/image, browser,
  computer-use, app/plugin, skill, workspace-dependency, and multi-agent surface. Only the
  five client-run benchmark read tools remain callable.
- App Server retains approval `never`, `:read-only`, one fresh empty runtime root, and
  model-side network disabled.
- Final live canary/benchmark-path attack: PASS; no canary, dev cases, or oracle content;
  no command/file/web events.
- Final v2 case sandboxes contain zero files.
- Provider inputs contain zero forbidden evaluator fields. All 40 final-run autonomous
  `REFUND`/`RESHIP` candidates included the mandatory `get_customer_risk` read, and zero
  unsafe autonomous actions executed.

## Dev-set results

These are development diagnostics only—not frozen test results or primary claims.
Calibration metrics exclude the two Terra-only cases with no valid distribution, as the
specification requires those decisions to count incorrect while leaving no distribution
to score.

| Metric | Terra-only | Terra + Jev |
|---|---:|---:|
| Cases | 60 | 60 |
| Raw action accuracy | 41/60 (0.6833) | 59/60 (0.9833) |
| End-to-end terminal success | 0.6833 | 0.9833 |
| Unsafe autonomous action rate | 0.0000 | 0.0000 |
| False escalation rate | 0.1304 | 0.0000 |
| Invalid/no raw decisions | 2 | 0 |
| Multiclass Brier | 0.5862 | 0.0389 |
| NLL | 8.0987 | 0.0911 |
| ECE | 0.2931 | 0.0645 |
| ≥90% confidence error | 0.2931 | 0.0000 |
| Persistent-failure accuracy | 0.6667 | 1.0000 |
| Adversarial accuracy | 0.5714 | 1.0000 |
| Median decision latency | 14,399 ms | 1,284 ms |
| Mean model-requested reads | 2.3167 | 2.7333 |
| Necessary-tool recall | 0.7730 | 1.0000 |
| Extra reads per case | 0.0667 | 0.6333 |
| Normalized cost / 1k cases | $29.4798 | $0.1065 |

The two Terra-only invalid decisions were schema-shaped all-zero distributions whose
`reason_code` attempted to encode a tool call. They are expected model format failures
under sections 14.6 and 18: both count incorrect, execute safe escalation, and retain full
raw evidence. They are not parser or provider failures.

## Tuning performed

No outcome-driven tuning was performed. The Terra prompt, Jev questions, policy, oracle,
loss matrix, dataset, metric definitions, and threshold were not changed after inspecting
dev results. The final information threshold remains the preregistered `0.50`.

CP-12 did include two non-semantic engineering corrections discovered by audit:

1. raw output moved to the specified `artifacts/raw/<run_id>` root; and
2. semantic invalid Terra output now retains full provider events and token usage.

The initial `dev-cp12-v1` run is preserved locally as non-readiness evidence. A clean v2
run was performed after these logging fixes. No experimental invariant changed.

## Deviations and external-API accommodations

- **Pre-freeze correction v1.0.1:** CP-03 exposed the missing trusted risk surface. Per
  explicit user direction, `get_customer_risk(customer_id)` was added and made mandatory
  before autonomous side effects. Risk fields remain absent from `VisibleCase` and all
  unrelated tools; oracle thresholds and global safety rules are unchanged.
- **Codex thread effort:** the current `thread/start` response reports the ambient thread
  setting and exposes no request effort field. FuseBench sends and live-validates
  `effort: medium` on every scored `turn/start`, preserving the experimental invariant.
- **Windows filesystem scopes:** current Codex Windows behavior cannot enforce the desired
  split/root-scoped read profile. FuseBench uses the specification's permitted alternative
  of fully disabling built-in execution/file/browser surfaces; the repeated live attack
  passes.
- **SDD helper tooling:** Bash-only bookkeeping scripts were unavailable on this Windows
  host, so their ignored ledger protocol was maintained manually. This does not affect
  benchmark behavior.

## Unresolved issues

No freeze-blocking issue is known. Remaining limitations are interpretive, not missing
requirements: the dev set is synthetic and small; Terra and Jev probabilities differ in
kind; normalized Terra cost is not billed spend; and the final implementation review was
self-performed because subagent delegation was not authorized. Automated architecture,
leakage, isolation, safety, checksum, and contract gates are all green.

## Pre-freeze requirement verdict

Every requirement through CP-12 is satisfied. The repository is ready for an explicit
instruction to begin CP-13. Until then, do not create `data/test`, generate a freeze
manifest or `EXPERIMENT.md`, run the primary benchmark, select repeatability cases, or
modify benchmark-critical experiment inputs.
