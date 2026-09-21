# FuseBench analysis summary

| Metric | Terra-only | Terra + Jev | Paired difference |
|---|---:|---:|---:|
| Final action accuracy | 0.683333 | 0.983333 | 0.300000 |
| End-to-end success | 0.683333 | 0.983333 | 0.300000 |
| Unsafe autonomous action rate | 0.000000 | 0.000000 | 0.000000 |
| False escalation rate | 0.130435 | 0.000000 | -0.130435 |
| Multiclass Brier ↓ | 0.586207 | 0.038880 | -0.547327 |
| NLL ↓ | 8.098748 | 0.091126 | -8.007622 |
| ECE ↓ | 0.293103 | 0.064500 | N/A |
| ≥90% confidence error | 0.293103 | 0.000000 | N/A |
| ≥95% confidence error | 0.293103 | 0.000000 | N/A |
| Decision p50/median latency ↓ | 14399.252000 | 1283.614550 | -13115.637450 |
| Decision p95 latency ↓ | 24308.073820 | 1444.283845 | N/A |
| Read tools / case ↓ | 2.316667 | 2.733333 | 0.416667 |
| Extra read tools / case ↓ | 0.066667 | 0.633333 | N/A |
| Persistent failure handling ↑ | 0.666667 | 1.000000 | N/A |
| Adversarial accuracy ↑ | 0.571429 | 1.000000 | N/A |
| Repeatability flip rate ↓ | N/A | N/A | N/A |
| Normalized cost / 1k cases ↓ | 29.479833 | 0.106469 | N/A |

No single winner score is computed. Interpret effect sizes, confidence intervals, safety, calibration, automation coverage, latency, and cost together.
