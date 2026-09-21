# FuseBench v1 preregistered experiment

Frozen at CP-13 under specification `1.0.1` and benchmark version
`1.0.0`. Source commit: `61e7be3fc28e21d1b83e0248462fb68bcd768e6e`. Frozen test dataset SHA-256:
`c47099493205a239950233962bf4a23802db181d4c3c6aaa81dfe9257db331fb`.

## Primary research question

> For a bounded, policy-governed, tool-using agent workflow, does inserting Jev as the
> decision layer improve the reliability-calibration-efficiency tradeoff compared with
> allowing GPT-5.6 Terra to make the same decisions itself?

## Systems

- `terra_only`: Terra selects trusted reads and the scored terminal action.
- `terra_jev`: Jev selects trusted reads and the scored terminal action; Terra is used
  only for the shared, post-action customer response.

No other scored system is part of v1. Both systems receive the same policy semantics,
case semantics, trusted simulator, action tools, and post-action Terra responder.

## Primary metrics

- final action accuracy;
- unsafe autonomous action rate;
- end-to-end terminal success;
- risk/coverage.

## Secondary metrics

All other frozen metrics, including calibration, business loss, category breakdowns,
tool use, decision-path latency, decision-path normalized cost, full-system response
latency, paired statistics, adversarial behavior, persistent-failure behavior, and
repeatability. Decision-path latency and normalized decision cost exclude the shared
Terra responder; full-response latency and responder usage are retained separately.

## Dataset

- 60-case development set used only before freeze;
- 240-case frozen test set;
- exactly 30 cases in each of eight categories;
- exactly 48 cases for each of the five gold actions;
- deterministic scenario-first labels from the frozen oracle, with curated templates and
  seeded perturbations and no model-generated labels or messages.

The 50 repeatability cases are selected before inference by the frozen seeded procedure:
10 each from boundary, conflicting-evidence, adversarial, tool-failure, and multi-tool.

## Frozen configuration

- Terra: `gpt-5.6-terra`, reasoning effort `medium`, Codex dynamic tools, fresh isolated
  read-only/network-off thread per decision and response.
- Jev: requested and reported `jev-1.13.0`, `typesafe-sdk==0.7.0`, hard cap USD 1.00.
- Jev information-read threshold: `0.50`.
- Mandatory shared pre-action safety read: `get_customer_risk(customer_id)` before an
  otherwise autonomous `REFUND` or `RESHIP`.

## Freeze statement

> No benchmark cases, policies, prompts, Jev questions, provider settings, thresholds,
> labels, or metric definitions will be modified after the frozen test set is evaluated.
> If a material bug is found, the benchmark version will be incremented and both systems
> will be rerun.

At creation of this preregistration, zero Terra or Jev inference calls had been made on
the frozen test set and no test outcomes had been observed.
