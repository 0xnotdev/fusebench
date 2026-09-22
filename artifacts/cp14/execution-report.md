# CP-14 Primary Run Execution Report

## Status

**CP-14 FAILED.** All 480 scheduled primary records completed and all completed-record
integrity checks passed. The strict CP-14 evidence requirement failed because one aborted
pre-record Jev attempt consumed 2,506 input tokens but its raw Jev request/response was not
durably flushed. Invocation 2 was also interrupted before its invocation summary was written.

No CP-15 repeatability run, statistical analysis, winner comparison, or tuning was performed.

## Completion and pairing

- Frozen source: tag `v1.0.1-freeze`, commit
  `c3f6b66b0b31c7fa8f1ecc60dd01162b0ab0bf99`
- Primary seed: `8193800051343574363`
- Completion: `480/480`
- `terra_only`: 240 records
- `terra_jev`: 240 records
- Complete cases: 240/240, exactly one record per system and case
- Frozen schedule order: exact match
- Pair adjacency: 240/240 pairs adjacent
- Resumptions: 2 across 3 invocations
- Clean usage-limit stops: 1
- Terminal/session interruptions: 1 (invocation 2 did not finalize its summary)

## Frozen provider configuration

### Terra / Codex

- Model: `gpt-5.6-terra`
- Reasoning effort: `medium`
- Tool protocol: `dynamic_tools`
- Codex CLI: `codex-cli 0.155.0-alpha.9.2`
- Codex user agent:
  `Codex Desktop/0.155.0-alpha.9.2 (Windows 10.0.26200; x86_64) dumb (fusebench; 1.0.1)`
- Dynamic trusted read tools: 5
- Permission profile: `:read-only`
- Model-side network: disabled
- Provider fallback: disabled
- Threads: ephemeral
- App Server disabled capabilities: shell tool, unified exec, image viewing, browser/computer
  use, apps, plugins, skill search, workspace dependencies, and multi-agent facilities

### Jev / TypeSafe

- Requested model: `jev-1.13.0`
- Reported model: `jev-1.13.0`
- TypeSafe SDK: `0.7.0`
- Information threshold: `0.50`
- Protocol: one information fan-out, one terminal call, and a conditional post-risk terminal
  call when required
- Hard budget cap: `$1.00`
- Provider-version drift: none

## Artifact integrity

- Normalized records SHA-256:
  `c4a6f1e8f1bcb39da9ee41dcae514a3d38e1cd3c2abb4eac4052d6c58f4102c2`
- Record-hash ledger SHA-256:
  `9b024e626b58248bf8236451d42471265e89bb147e0ae8dbd7aaeeaabc5b2d3e`
- Run checksum manifest SHA-256:
  `a253e524af5b3995fb04f8c8249f5d9643867e28d7d7e6e40482b3a2989216ee`
- Raw-tree checksum-map SHA-256:
  `2f93286598a22bc91560379b52987acec8e59a777fc2fd2dc9395433a4b0339a`
- Raw files covered by the run checksum manifest: 2,878
- RunRecorder normalized/raw checksum verification: PASS
- Every completed record has its required raw decision, tool, provider, response, and (for
  hybrid records) Jev evidence: PASS
- All-provider-attempt evidence: FAIL — the aborted attempt's 2,506 billed Jev input tokens
  have no corresponding raw request/response artifact

## Fairness, leakage, and isolation

- Mechanical fairness audit: PASS
- `get_customer_risk` pre-action semantics: PASS for both architectures
- Hidden customer-risk fields absent from VisibleCase and initial provider payloads: PASS
- Autonomous side effects require a successful safe customer-risk observation: PASS
- Actual equivalent trusted-observation comparisons: 286, all matched
- Terra dynamic-tool loop: 403 requests across 151 records; raw event evidence confirms
  dynamic tool calls occurred within the decision turn rather than being forced directly to
  terminal output
- Decision-path latency and decision token/cost telemetry exclude the shared Terra responder;
  full-system latency and responder tokens remain separate secondary telemetry: PASS
- Provider-bound forbidden-key scan: PASS
- Model-side filesystem/network tool events: 0
- Sandboxes: 722 directories, all empty; 720 completed execution/stage sandboxes plus 2 empty
  superseded attempt directories
- Recorded thread IDs: 522, all unique and never reused
- Missing decision thread IDs: 65, corresponding to provider failures before a thread was
  durably returned
- Missing response thread IDs: 133, corresponding to provider failures before a response
  thread was durably returned
- Frozen isolation preflight: PASS
- Freeze verifier: PASS — 834 critical files and 240 frozen cases
- Benchmark-critical hashes after CP-14: unchanged

## Infrastructure and format events

| Event | `terra_only` | `terra_jev` |
|---|---:|---:|
| Invalid terminal/model-format output | 12 | 1 |
| Invalid probability distribution | 0 | 0 |
| Decision provider timeout | 69 | 0 |
| Shared responder provider timeout | 70 | 70 |
| Provider HTTP error | 0 | 0 |
| Other provider error | 0 | 0 |
| Model-version change | 0 | 0 |
| Response invalid-output error | 0 | 0 |
| Simulator/tool infrastructure retries | 15 | 25 |

- Observed provider retry events: 0
- TypeSafe retry policy: at most 3 provider attempts (`max_retries=2`)
- Exact internal TypeSafe retry-attempt telemetry: not exposed by SDK 0.7.0
- Harness failures: 0
- Usage-limit events: 1
- Legitimate model-format failures remained benchmark records and were not retried or tuned

## Token and budget accounting

### Terra decision path

- Input: 2,431,606
- Cached input: 2,243,584
- Output: 14,003
- Reasoning output: 4,956

### Shared Terra responder (secondary full-system telemetry)

- Input: 4,375,366
- Cached input: 3,711,744
- Output: 8,856
- Reasoning output: 540

### Terra full system

- Input: 6,806,972
- Cached input: 5,955,328
- Output: 22,859
- Reasoning output: 5,496

### Jev

- Completed-record input: 607,118
- Completed-record output: 59,455
- Billed primary input including the aborted attempt: 609,624
- Aborted-attempt input without raw request/response evidence: 2,506
- Estimated promotional-credit consumption: `$0.025604208`
- Budget cap respected: PASS (`$0.025604208 < $1.00`)

## Validation commands

- `uv run python artifacts/cp14/audit_primary.py` — expected non-zero strict result; the sole
  failure is the aborted-attempt evidence gap documented above
- `uv run fusebench freeze verify` — PASS, 834 critical files and 240 cases
- `uv run pytest -q` — PASS, 220 passed and 3 deselected
- `uv run ruff check artifacts/cp14/audit_primary.py` — PASS

## Final determination

The paired primary dataset itself is complete and internally consistent, but the user's
explicit requirement to preserve all raw provider evidence includes aborted attempts. Because
that condition cannot be verified or reconstructed without inventing missing evidence, CP-14
is not declared complete.

`CP-14 FAILED — aborted provider attempt raw evidence is incomplete`
