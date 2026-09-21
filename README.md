# FuseBench

FuseBench is a controlled benchmark for comparing a bounded Terra-only order-exception
agent with the same application using TypeSafe Jev as its decision layer. The experiment
is under construction; no benchmark claims have been produced.

The authoritative build specification is [`spec(4).md`](spec(4).md). `spec.md` is kept as
an exact canonical copy for the repository layout required by that specification.

## Development

```powershell
uv sync
uv run pytest
uv run ruff check .
```

Live provider setup, preflight, development evaluation, freezing, and analysis commands
will be documented as their checkpoints are completed. The frozen test set must not be
created or executed before CP-13 authorization.
