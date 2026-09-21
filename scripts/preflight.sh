#!/usr/bin/env bash
set -euo pipefail

uv run pytest -q
uv run ruff check .

if [[ "${1:-}" == "--live" ]]; then
  uv run pytest tests/contract/test_typesafe_live.py -v -m live
  uv run pytest tests/contract/test_codex_app_server_live.py -v -m live
  uv run pytest tests/contract/test_codex_isolation_live.py -v -m live
fi
