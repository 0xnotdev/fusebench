# Pre-freeze development tuning and correction log

## Experimental tuning

No outcome-driven tuning was performed. The final Terra prompt, Jev questions, policy,
oracle, loss matrix, dataset definitions, metric definitions, provider settings, and Jev
information threshold remained unchanged after development results were inspected. The
frozen information threshold is 0.50.

## CP-03 pre-freeze specification correction

The original specification made `prior_exception_refunds_90d` and
`trusted_records_conflict` oracle-relevant without a permitted trusted read surface. Per
the user's explicit correction, v1.0.1 added `get_customer_risk(customer_id)` as the fifth
trusted read and made it mandatory before an otherwise autonomous `REFUND` or `RESHIP`.
The result may override that candidate to `ESCALATE` under the existing global policy.
The two hidden fields remain absent from `VisibleCase` and unrelated tool responses; no
oracle threshold or global safety rule changed. This was a specification bug fix, not an
experiment redesign, and occurred before test freeze.

## External-API accommodations

- Codex currently reports ambient effort on `thread/start`; FuseBench sends and validates
  `effort: medium` on every scored `turn/start`.
- On this Windows host, built-in execution, file, browser, app, plugin, skill, dependency,
  and multi-agent surfaces are disabled; only the five benchmark dynamic reads are exposed.
- TypeSafe's accepted concrete model is pinned to `jev-1.13.0`.

## Non-semantic CP-12 corrections

- Raw outputs were placed at the specified `artifacts/raw/<run_id>` root.
- Semantic invalid Terra outputs retain provider events and token usage.
