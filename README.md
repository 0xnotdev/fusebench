# FuseBench

FuseBench is a controlled synthetic benchmark comparing two bounded order-exception
decision architectures: a GPT-5.6 Terra tool-using agent and the same application with
TypeSafe Jev owning the scored decision layer. Both systems use the same policy, cases,
simulator, tools, oracle, terminal actions, and shared Terra customer-response stage.
CP-00 through CP-12 are complete; no frozen test set or primary benchmark exists yet.

The authoritative source is [`spec(4).md`](spec(4).md). [`spec.md`](spec.md) is its exact
canonical repository copy.

## Research question

> For a bounded, policy-governed, tool-using agent workflow, does inserting Jev as the
> decision layer improve the reliability–calibration–efficiency tradeoff compared with
> allowing GPT-5.6 Terra to make the same decisions itself?

The null or a negative result is valid. FuseBench does not test whether Jev replaces LLMs
in general.

## Architecture

```text
                     same visible case + policy
                                |
                 +--------------+--------------+
                 |                             |
          Terra-only decision          Jev decision layer
          dynamic read tools          batched info judgment
                 |                     + selected read tools
                 |                     + terminal judgment
                 +--------------+--------------+
                                |
                    isolated deterministic simulator
                                |
                         locked business action
                                |
                    shared response-only Terra stage
```

The five trusted reads are `get_tracking`, `get_payment`, `get_inventory`,
`get_damage_evidence`, and `get_customer_risk`. The last is a mandatory pre-action check
for autonomous `REFUND` or `RESHIP` candidates. It was added as the pre-freeze v1.0.1
specification correction recorded in [`artifacts/implementation-log.md`](artifacts/implementation-log.md).

## Setup

Requirements:

- Python 3.11 or later;
- [uv](https://docs.astral.sh/uv/);
- an authenticated `codex` executable with App Server support;
- a TypeSafe API key.

```powershell
uv sync
Copy-Item .env.example .env
```

Configure `.env` locally:

```dotenv
TYPESAFE_API_KEY=...
JEV_MODEL=jev-1.13.0
JEV_HARD_CAP_USD=1.0
```

`.env`, live budgets, case sandboxes, and generated run artifacts are ignored by default.
Credentials are redacted from durable artifacts. The audited final `dev-cp12-v2`
artifacts are force-committed as the pre-freeze readiness evidence.

## Validation and preflight

The normal suite is mock-only:

```powershell
uv run pytest
uv run ruff check .
```

The full live gate makes a small TypeSafe contract probe, a Codex dynamic-tool probe, and
an explicit filesystem-isolation attack:

```powershell
uv run fusebench preflight
```

It writes sanitized evidence to `artifacts/preflight/` and refuses a scored run when the
gate fails. `--reuse-evidence` performs a no-provider-call validation of existing evidence.

## Development evaluation

Build or verify the deterministic 60-case development set, then run the two systems in a
paired schedule:

```powershell
uv run fusebench dataset build-dev
uv run fusebench dev-run --systems terra_only,terra_jev --run-id dev-cp12-v2
```

Runs are append-only, checksummed, provider-version checked, and safely resumable. Raw
provider evidence is written under `artifacts/raw/<run-id>/`; normalized records and the
input manifest are under `artifacts/runs/<run-id>/`; record-only analysis and four plots
are under `artifacts/analysis/<run-id>/`.

The CP-12 readiness report is [`artifacts/readiness-cp12.md`](artifacts/readiness-cp12.md).
Development results are diagnostics, not primary benchmark claims.

## Freeze and primary benchmark

CP-13 is implemented as an inference-free sequence: run the mechanical fairness audit,
create the frozen dataset/manifest, then re-hash and validate the complete freeze:

```powershell
uv run fusebench freeze audit
uv run fusebench freeze create
uv run fusebench freeze verify
```

The freeze contains the 240-case test split, CSPRNG seeds, all critical-file hashes,
environment/provider versions, 50 preregistered repeatability IDs, the pre-freeze tuning
log, and `EXPERIMENT.md`. After freeze, benchmark-critical tuning is prohibited. The
primary command remains blocked until CP-14 is explicitly authorized:

```powershell
uv run fusebench run --split test --systems terra_only,terra_jev --run-id primary-v1
```

## Analysis

The implementation provides normalized-record-only correctness, safety, calibration,
risk/coverage, tool-use, latency, cost, McNemar, paired-bootstrap, repeatability, table,
and plot generation. Primary analysis commands remain blocked until a frozen primary run
exists:

```powershell
uv run fusebench analyze --run-id primary-v1
uv run fusebench plot --run-id primary-v1
uv run fusebench report --run-id primary-v1
```

## Reproducibility

Both datasets are deterministic for their recorded seeds and hash checked. Paired scheduling uses a fixed seed;
each system receives a fresh simulator state; every case and response uses a fresh empty
sandbox; provider/model changes abort or stop safely; normalized records are flushed
immediately; raw and normalized artifacts are covered by SHA-256 manifests. Frozen test
data is evaluator-only, and agents have no imports from the oracle.

## Current limitations

- Results currently cover only 60 synthetic development cases; they are not frozen test
  results and support no final comparative claim.
- Windows Codex App Server cannot enforce the desired root-scoped read policy. FuseBench
  therefore disables all built-in shell/file/browser/app/plugin capabilities and exposes
  only its five client-run read tools; the live canary attack passes under this design.
- Terra probabilities are elicited structured self-reports, while Jev probabilities are
  native structured judgments; calibration is operational rather than identical in kind.
- Terra cost is an API-equivalent normalization, not actual subscription spend. Jev cost
  is an estimate of promotional-credit consumption.
