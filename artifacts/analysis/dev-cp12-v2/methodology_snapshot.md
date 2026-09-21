# FuseBench methodology snapshot

Primary accuracy uses the raw top-probability action; invalid/no decision is incorrect.
Primary unsafe outcomes use the executed business action. Calibration uses unscaled
multiclass Brier, gold-label NLL clipped at `1e-12`, and 10 equal-width top-label bins.

Jev probabilities are native structured outputs while Terra probabilities are elicited
structured outputs. They are operational confidence signals but are not architecturally identical.
Confidence gates are evaluated offline across the preregistered threshold grid.

Claims of safety use the wording "0 observed unsafe errors in N covered test cases"; this
does not establish zero risk. Latency is end-to-end decision-path latency from this client
environment, not pure model inference latency.

Terra cost is a freeze-date API-equivalent normalization, not actual subscription spend.
Jev cost is estimated promotional-credit consumption. Terra marginal billed API spend is
reported separately as zero while within the existing subscription allowance.

Paired bootstrap uses 10,000 samples for primary analysis (or the explicit test override)
and preserves system pairs. Bootstrap seed: 20260921.
