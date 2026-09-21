# Codex App Server schemas

These files were generated from the locally installed `codex-cli
0.155.0-alpha.9.2` on 2026-09-21:

```text
codex app-server generate-json-schema --out schemas/codex
codex app-server generate-json-schema --experimental --out schemas/codex/experimental
```

The generated output is version-specific. The stable v2 bundle does not expose
`thread/start.dynamicTools`; the experimental v2 bundle does, behind
`initialize.params.capabilities.experimentalApi = true`. A synthetic live contract test
successfully exercised the `item/tool/call` callback, structured final output, exact
`gpt-5.6-terra` routing, explicit `medium` turn effort, and token usage. FuseBench therefore
selects `dynamic_tools` for all development and future frozen runs.

The installed Windows App Server cannot enforce a split-readable-root profile: elevated
sandbox setup requires effective root read, and the unelevated sandbox refuses split read
policies. FuseBench therefore follows the specification's shell-disabled path: the App
Server process is launched with command, filesystem-view, browser, app/plugin, workspace
dependency, and multi-agent tool features disabled. Only the five benchmark dynamic tools
remain. The live isolation attack confirmed zero command/file/web events and no access to
the external canary, oracle, or dataset paths.

See `manifest.json` for hashes and `artifacts/preflight/codex-contract.json` for sanitized
live evidence. Protocol behavior was checked against the official Codex App Server
documentation: <https://developers.openai.com/codex/app-server>.
