param(
    [switch]$Live
)

$ErrorActionPreference = "Stop"

uv run pytest -q
if ($LASTEXITCODE -ne 0) { throw "Offline test suite failed" }

uv run ruff check .
if ($LASTEXITCODE -ne 0) { throw "Ruff failed" }

if ($Live) {
    uv run pytest tests/contract/test_typesafe_live.py -v -m live
    if ($LASTEXITCODE -ne 0) { throw "TypeSafe live contract failed" }

    uv run pytest tests/contract/test_codex_app_server_live.py -v -m live
    if ($LASTEXITCODE -ne 0) { throw "Codex live contract failed" }

    uv run pytest tests/contract/test_codex_isolation_live.py -v -m live
    if ($LASTEXITCODE -ne 0) { throw "Codex isolation contract failed" }
}
