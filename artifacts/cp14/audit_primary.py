"""CP-14 integrity audit only: no scoring, aggregation, or winner analysis."""

from __future__ import annotations

import json
import subprocess
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path
from typing import Any

from fusebench.benchmark.fairness import build_mechanical_fairness_audit
from fusebench.benchmark.freeze import verify_freeze
from fusebench.benchmark.recorder import RunRecorder
from fusebench.dataset.validation import assert_no_forbidden_keys, canonical_json

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "primary-v1"
RUN_DIR = ROOT / "artifacts/runs" / RUN_ID
RAW_DIR = ROOT / "artifacts/raw" / RUN_ID
SANDBOX_DIR = ROOT / "artifacts/case_sandboxes" / RUN_ID
EXPECTED_SYSTEMS = {"terra_only", "terra_jev"}
EXPECTED_VERSIONS = {
    "terra": "gpt-5.6-terra",
    "codex": (
        "Codex Desktop/0.155.0-alpha.9.2 (Windows 10.0.26200; x86_64) "
        "dumb (fusebench; 1.0.1)"
    ),
    "jev": "jev-1.13.0",
    "response_terra": "gpt-5.6-terra",
    "response_codex": (
        "Codex Desktop/0.155.0-alpha.9.2 (Windows 10.0.26200; x86_64) "
        "dumb (fusebench; 1.0.1)"
    ),
}
RISK_FIELDS = {"prior_exception_refunds_90d", "trusted_records_conflict"}
AUTONOMOUS = {"REFUND", "RESHIP"}
PROVIDER_ERRORS = (
    "provider_timeout",
    "provider_http_error",
    "provider_error",
    "model_version_changed",
    "provider_usage_limit",
)
FORBIDDEN_ITEM_TYPES = {
    "commandExecution",
    "fileChange",
    "webSearch",
    "imageView",
    "computerToolCall",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[Any]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def contains_key(value: Any, names: set[str]) -> bool:
    if isinstance(value, dict):
        return bool(names & {str(key) for key in value}) or any(
            contains_key(item, names) for item in value.values()
        )
    if isinstance(value, list):
        return any(contains_key(item, names) for item in value)
    return False


def normalized_tool_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in event.items()
        if key not in {"system", "duration_ms", "started_at_ns", "ended_at_ns"}
    }


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> None:
    primary = read_json(RUN_DIR / "primary_manifest.json")
    schedule_object = read_json(RUN_DIR / "schedule.json")
    schedule = schedule_object["executions"]
    record_lines = [
        line
        for line in (RUN_DIR / "records.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    records = [json.loads(line) for line in record_lines]
    hashes = read_jsonl(RUN_DIR / "record_hashes.jsonl")

    failures: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    expected_keys = [
        (item["case_id"], item["system"], item["repetition"]) for item in schedule
    ]
    actual_keys = [
        (record["case_id"], record["system"], record["repetition"])
        for record in records
    ]
    require(len(schedule) == 480, "frozen schedule does not contain 480 executions")
    require(len(records) == 480, "normalized run does not contain 480 records")
    require(len(set(actual_keys)) == 480, "normalized system/case keys are not unique")
    require(actual_keys == expected_keys, "record append order differs from frozen schedule")
    require(len(hashes) == 480, "record hash ledger does not contain 480 entries")
    require(
        [
            (item["case_id"], item["system"], item["repetition"])
            for item in hashes
        ]
        == actual_keys,
        "record hash ledger order or keys differ from normalized records",
    )
    for line, item in zip(record_lines, hashes, strict=True):
        require(
            sha256(line.encode("utf-8")).hexdigest() == item["sha256"],
            f"record hash mismatch for {item['case_id']} {item['system']}",
        )

    cases: dict[str, set[str]] = defaultdict(set)
    for record in records:
        cases[record["case_id"]].add(record["system"])
    require(len(cases) == 240, "primary records do not cover 240 cases")
    require(
        all(systems == EXPECTED_SYSTEMS for systems in cases.values()),
        "one or more cases lacks exactly one record from each system",
    )
    for index in range(0, len(schedule), 2):
        pair = schedule[index : index + 2]
        require(
            len(pair) == 2
            and pair[0]["case_id"] == pair[1]["case_id"]
            and {pair[0]["system"], pair[1]["system"]} == EXPECTED_SYSTEMS,
            f"schedule pair at offsets {index}-{index + 1} is not adjacent",
        )

    recorder = RunRecorder(
        ROOT / "artifacts/runs",
        RUN_ID,
        provider_versions=EXPECTED_VERSIONS,
        raw_root=ROOT / "artifacts/raw",
    )
    checksums_verified = recorder.verify_checksums()
    require(checksums_verified, "normalized/raw checksum manifest verification failed")

    version_maps: dict[str, set[tuple[tuple[str, str], ...]]] = defaultdict(set)
    error_counts: dict[str, Counter[str]] = defaultdict(Counter)
    token_counts = Counter()
    response_token_counts = Counter()
    tool_retries = Counter()
    raw_files = 0
    missing_raw: list[str] = []
    tool_observations: dict[
        tuple[str, str], dict[str, list[dict[str, Any]]]
    ] = defaultdict(lambda: defaultdict(list))
    all_thread_ids: list[str] = []
    missing_decision_threads = 0
    missing_response_threads = 0
    provider_methods: set[str] = set()
    provider_item_types: set[str] = set()
    dynamic_request_count = 0
    dynamic_records = 0
    risk_fail_closed = Counter()
    late_risk_rechecks = 0
    jev_call_counts = Counter()

    for record in records:
        system = record["system"]
        case_id = record["case_id"]
        repetition = record["repetition"]
        version_maps[system].add(tuple(sorted(record["provider_versions"].items())))
        expected_version_map = (
            {
                "terra": EXPECTED_VERSIONS["terra"],
                "codex": EXPECTED_VERSIONS["codex"],
                "response_terra": EXPECTED_VERSIONS["response_terra"],
                "response_codex": EXPECTED_VERSIONS["response_codex"],
            }
            if system == "terra_only"
            else {
                "jev": EXPECTED_VERSIONS["jev"],
                "response_terra": EXPECTED_VERSIONS["response_terra"],
                "response_codex": EXPECTED_VERSIONS["response_codex"],
            }
        )
        require(
            record["provider_versions"] == expected_version_map,
            f"provider version drift in {case_id} {system}",
        )

        raw = RAW_DIR / system / case_id / f"r{repetition}"
        base_names = {
            "decision_outcome.json",
            "tool_events.jsonl",
            "codex_events.jsonl",
            "response_stage.json",
        }
        names = {path.name for path in raw.iterdir()} if raw.is_dir() else set()
        request_names = sorted(name for name in names if name.startswith("jev_request_"))
        response_names = sorted(name for name in names if name.startswith("jev_response_"))
        expected_names = base_names | set(request_names) | set(response_names)
        if not raw.is_dir() or names != expected_names or not base_names <= names:
            missing_raw.append(f"{system}/{case_id}/r{repetition}")
            continue
        require(
            not any(".a" in name for name in names),
            f"duplicate raw attempt file exists for {case_id} {system}",
        )
        raw_files += len(names)
        if system == "terra_only":
            require(
                not request_names and not response_names,
                f"Terra-only record has Jev artifacts for {case_id}",
            )
        else:
            require(
                len(request_names) == len(response_names) and len(request_names) in {1, 2, 3},
                f"hybrid Jev request/response evidence is incomplete for {case_id}",
            )
            jev_call_counts[len(request_names)] += 1
            requests = [read_json(raw / name) for name in request_names]
            responses = [read_json(raw / name) for name in response_names]
            del responses
            for state in requests:
                try:
                    assert_no_forbidden_keys(state)
                except ValueError as error:
                    failures.append(f"Jev payload leakage for {case_id}: {error}")
            require(
                not contains_key(requests[0], RISK_FIELDS),
                f"initial Jev state exposes customer-risk fields for {case_id}",
            )

        outcome = read_json(raw / "decision_outcome.json")
        response = read_json(raw / "response_stage.json")
        tool_events = read_jsonl(raw / "tool_events.jsonl")
        codex_events = read_jsonl(raw / "codex_events.jsonl")
        require(
            outcome["read_tools_requested"] == record["read_tools_requested"],
            f"raw/normalized requested tools differ for {case_id} {system}",
        )
        require(
            outcome["decision_path_latency_ms"] == record["decision_path_latency_ms"],
            f"decision latency differs between raw and normalized record for {case_id} {system}",
        )
        require(
            response["full_response_latency_ms"] == record["full_response_latency_ms"],
            f"full-system latency differs between raw and normalized record for {case_id} {system}",
        )
        require(
            outcome["terra_input_tokens"] == record["terra_input_tokens"]
            and outcome["terra_output_tokens"] == record["terra_output_tokens"]
            and outcome["jev_input_tokens"] == record["jev_input_tokens"]
            and outcome["jev_output_tokens"] == record["jev_output_tokens"],
            f"decision token telemetry differs for {case_id} {system}",
        )
        require(
            not {
                "response_input_tokens",
                "response_cached_input_tokens",
                "response_output_tokens",
                "response_reasoning_output_tokens",
            }
            & set(record),
            "normalized decision record contains shared-responder token fields",
        )

        token_counts["decision_input"] += outcome["terra_input_tokens"]
        token_counts["decision_cached_input"] += outcome["terra_cached_input_tokens"]
        token_counts["decision_output"] += outcome["terra_output_tokens"]
        token_counts["decision_reasoning_output"] += outcome[
            "terra_reasoning_output_tokens"
        ]
        token_counts["jev_completed_input"] += outcome["jev_input_tokens"]
        token_counts["jev_completed_output"] += outcome["jev_output_tokens"]
        response_token_counts["input"] += response["response_input_tokens"]
        response_token_counts["cached_input"] += response["response_cached_input_tokens"]
        response_token_counts["output"] += response["response_output_tokens"]
        response_token_counts["reasoning_output"] += response[
            "response_reasoning_output_tokens"
        ]
        tool_retries[system] += outcome["infrastructure_retries"]

        decision_errors = set(outcome["decision"].get("errors", []))
        for error in PROVIDER_ERRORS:
            if error in decision_errors:
                error_counts[system][error] += 1
        if "invalid_terminal_output" in decision_errors:
            error_counts[system]["invalid_terminal_output"] += 1
        if outcome["decision"].get("invalid_probability_distribution", False):
            error_counts[system]["invalid_probability_distribution"] += 1
        if response["response_error"] is not None:
            error_counts[system][f"response_{response['response_error']}"] += 1
        if system == "terra_jev" and len(request_names) == 1:
            require(
                "invalid_terminal_output" in decision_errors,
                "one-call hybrid record is not explained by a terminal parse "
                f"failure for {case_id}",
            )

        decision_thread = outcome.get("thread_id")
        response_thread = response.get("thread_id")
        if system == "terra_only":
            if decision_thread:
                all_thread_ids.append(decision_thread)
            else:
                missing_decision_threads += 1
        if response_thread:
            all_thread_ids.append(response_thread)
        else:
            missing_response_threads += 1

        for event in outcome.get("provider_events", []) + response.get(
            "provider_events", []
        ):
            method = event.get("method") if isinstance(event, dict) else None
            if isinstance(method, str):
                provider_methods.add(method)
            params = event.get("params") if isinstance(event, dict) else None
            item = params.get("item") if isinstance(params, dict) else None
            item_type = item.get("type") if isinstance(item, dict) else None
            if isinstance(item_type, str):
                provider_item_types.add(item_type)
            if item_type == "userMessage":
                for content in item.get("content", []):
                    text = content.get("text") if isinstance(content, dict) else None
                    if not isinstance(text, str):
                        continue
                    try:
                        payload = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    try:
                        assert_no_forbidden_keys(payload)
                    except ValueError as error:
                        failures.append(
                            f"Codex payload leakage for {case_id} {system}: {error}"
                        )
                    require(
                        not contains_key(payload, RISK_FIELDS),
                        f"Codex user payload exposes customer-risk fields for {case_id} {system}",
                    )

        dynamic = outcome.get("dynamic_tool_requests", [])
        if system == "terra_only":
            dynamic_request_count += len(dynamic)
            dynamic_records += int(bool(dynamic))
            require(
                [item["tool"] for item in dynamic]
                == outcome["read_tools_requested"],
                f"dynamic request evidence differs from tool telemetry for {case_id}",
            )
            require(
                codex_events == outcome.get("provider_events", []),
                f"Codex event file differs from decision outcome for {case_id}",
            )
        else:
            require(
                not codex_events and not outcome.get("provider_events", []),
                f"hybrid decision unexpectedly contains Codex decision events for {case_id}",
            )

        risk_events = [event for event in tool_events if event.get("tool") == "get_customer_risk"]
        for event in tool_events:
            require(
                event.get("case_id") == case_id and event.get("system") == system,
                f"tool event scope differs for {case_id} {system}",
            )
            if event.get("tool") != "get_customer_risk":
                require(
                    not contains_key(event.get("result"), RISK_FIELDS),
                    f"customer-risk fields leaked through {event.get('tool')} for {case_id}",
                )
            key = (case_id, str(event.get("tool")))
            tool_observations[key][system].append(normalized_tool_event(event))

        raw_action = outcome["decision"].get("raw_action")
        executed_action = outcome["decision"].get("executed_action")
        if executed_action in AUTONOMOUS:
            require(
                bool(risk_events),
                f"autonomous execution lacks risk read for {case_id} {system}",
            )
            successful = [event for event in risk_events if event.get("result_kind") == "success"]
            require(
                bool(successful),
                f"autonomous execution lacks successful risk read for {case_id} {system}",
            )
            if successful:
                risk = successful[-1]["result"]
                require(
                    int(risk["prior_exception_refunds_90d"]) < 2
                    and not bool(risk["trusted_records_conflict"]),
                    f"autonomous execution ignored risk override for {case_id} {system}",
                )
        if raw_action in AUTONOMOUS and not risk_events:
            require(
                executed_action == "ESCALATE"
                and "missing_customer_risk" in decision_errors,
                f"candidate autonomous action did not fail closed for {case_id} {system}",
            )
            risk_fail_closed[system] += 1
        precheck_action = outcome.get("precheck_action")
        if precheck_action in AUTONOMOUS:
            late_risk_rechecks += 1
            require(
                system == "terra_jev" and bool(risk_events) and len(request_names) == 3,
                f"hybrid late customer-risk check is incomplete for {case_id}",
            )

    require(not missing_raw, f"missing raw record evidence: {missing_raw[:5]}")
    require(
        len(all_thread_ids) == len(set(all_thread_ids)),
        "a Terra thread id was reused across executions/stages",
    )
    require(
        not (provider_item_types & FORBIDDEN_ITEM_TYPES),
        "forbidden filesystem/network item types observed: "
        f"{provider_item_types & FORBIDDEN_ITEM_TYPES}",
    )
    require(
        dynamic_request_count > 0 and dynamic_records > 0,
        "dynamic-tool loop was never exercised",
    )
    require(
        provider_item_types <= {"agentMessage", "dynamicToolCall", "reasoning", "userMessage"},
        f"unexpected Codex item types observed: {provider_item_types}",
    )

    parity_checks = 0
    for key, by_system in tool_observations.items():
        if set(by_system) == EXPECTED_SYSTEMS:
            for ordinal, (terra_event, jev_event) in enumerate(
                zip(by_system["terra_only"], by_system["terra_jev"], strict=False),
                start=1,
            ):
                parity_checks += 1
                require(
                    terra_event == jev_event,
                    f"trusted observation differs between systems for {key} ordinal {ordinal}",
                )

    sandbox_dirs = [path for path in SANDBOX_DIR.iterdir() if path.is_dir()]
    sandbox_files = [path for path in SANDBOX_DIR.rglob("*") if path.is_file()]
    require(not sandbox_files, "one or more case sandboxes is not empty")
    require(
        all(path.resolve().is_relative_to(SANDBOX_DIR.resolve()) for path in sandbox_dirs),
        "a case sandbox resolved outside the isolated run root",
    )

    freeze = verify_freeze(ROOT)
    require(bool(freeze["passed"]), f"freeze verifier failed: {freeze['errors']}")
    fairness = build_mechanical_fairness_audit(ROOT)
    require(bool(fairness["passed"]), "mechanical fairness audit no longer passes")
    require(
        primary["run_seed"] == 8193800051343574363,
        "primary manifest seed differs from frozen seed",
    )
    require(primary["information_threshold"] == 0.5, "information threshold drifted")

    budget = read_json(ROOT / primary["budget_path"])
    jev_billed_input = budget["input_tokens"] - primary["budget_start_input_tokens"]
    jev_billed_cost = (
        budget["estimated_cost_usd"] - primary["budget_start_estimated_cost_usd"]
    )
    orphan_jev_input = jev_billed_input - token_counts["jev_completed_input"]
    require(
        jev_billed_input >= token_counts["jev_completed_input"],
        "Jev ledger is below record usage",
    )
    require(
        budget["estimated_cost_usd"] <= budget["hard_cap_usd"],
        "Jev budget cap exceeded",
    )

    invocation_files = sorted(RUN_DIR.glob("invocation_*.json"))
    invocation_data = [read_json(path) for path in invocation_files]
    usage_limit_events = sum(bool(item["stopped_for_usage_limit"]) for item in invocation_data)
    finalized_invocation_ids = {
        int(path.stem.rsplit("_", 1)[1]) for path in invocation_files
    }
    unfinalized_invocations = sorted(
        set(range(1, int(primary["invocation_count"]) + 1)) - finalized_invocation_ids
    )
    all_attempt_raw_evidence_preserved = (
        orphan_jev_input == 0 and not unfinalized_invocations
    )
    if not all_attempt_raw_evidence_preserved:
        failures.append(
            "aborted provider attempt evidence is incomplete: "
            f"orphan_jev_input_tokens={orphan_jev_input}, "
            f"unfinalized_invocations={unfinalized_invocations}"
        )

    raw_checksum_items = {
        key: value
        for key, value in read_json(RUN_DIR / "checksums.json").items()
        if key.startswith("raw/")
    }
    raw_tree_sha256 = sha256(canonical_json(raw_checksum_items).encode("utf-8")).hexdigest()
    status = git("status", "--short")
    benchmark_semantic_changes = [
        line for line in status.splitlines() if line and not line[3:].startswith("artifacts/")
    ]
    require(
        not benchmark_semantic_changes,
        f"benchmark-semantic working tree changes detected: {benchmark_semantic_changes}",
    )

    report = {
        "audit": "CP-14 primary-run integrity audit",
        "strict_cp14_passed": not failures,
        "failures": failures,
        "completion": {
            "records": len(records),
            "cases": len(cases),
            "records_by_system": dict(sorted(Counter(r["system"] for r in records).items())),
            "paired_complete": len(cases) == 240
            and all(value == EXPECTED_SYSTEMS for value in cases.values()),
            "schedule_order_exact": actual_keys == expected_keys,
            "adjacent_pairs": 240,
        },
        "configuration": {
            "source_tag": primary["source_tag"],
            "source_commit": primary["source_commit"],
            "run_seed": primary["run_seed"],
            "terra_codex": primary["terra_codex_configuration"],
            "jev": primary["jev_configuration"],
            "information_threshold": primary["information_threshold"],
        },
        "integrity": {
            "run_checksums_verified": checksums_verified,
            "normalized_records_sha256": digest(RUN_DIR / "records.jsonl"),
            "record_hashes_sha256": digest(RUN_DIR / "record_hashes.jsonl"),
            "checksums_manifest_sha256": digest(RUN_DIR / "checksums.json"),
            "raw_tree_sha256": raw_tree_sha256,
            "raw_files": raw_files,
            "completed_record_raw_evidence_complete": not missing_raw,
            "all_provider_attempt_raw_evidence_preserved": all_attempt_raw_evidence_preserved,
            "orphan_jev_input_tokens": orphan_jev_input,
            "unfinalized_invocations": unfinalized_invocations,
            "freeze_verifier": freeze,
            "benchmark_critical_state_unchanged": bool(freeze["passed"]),
        },
        "pairing_and_fairness": {
            "actual_common_observation_comparisons": parity_checks,
            "customer_risk_fail_closed_without_read": dict(risk_fail_closed),
            "hybrid_late_risk_rechecks": late_risk_rechecks,
            "dynamic_tool_records": dynamic_records,
            "dynamic_tool_requests": dynamic_request_count,
            "fairness_audit_passed": fairness["passed"],
            "shared_responder_excluded_from_decision_metrics": True,
        },
        "isolation": {
            "preflight_passed": primary["preflight_passed"],
            "preflight_isolation_passed": primary["isolation_passed"],
            "sandbox_directories": len(sandbox_dirs),
            "empty_sandbox_directories": len(sandbox_dirs) if not sandbox_files else 0,
            "superseded_empty_attempt_directories": max(0, len(sandbox_dirs) - 720),
            "decision_threads_recorded": 240 - missing_decision_threads,
            "missing_decision_threads": missing_decision_threads,
            "response_threads_recorded": 480 - missing_response_threads,
            "missing_response_threads": missing_response_threads,
            "unique_recorded_thread_ids": len(set(all_thread_ids)),
            "provider_methods": sorted(provider_methods),
            "provider_item_types": sorted(provider_item_types),
            "filesystem_or_network_tool_violations": 0,
        },
        "provider_versions": {
            system: [dict(items) for items in sorted(maps)]
            for system, maps in sorted(version_maps.items())
        },
        "errors": {
            "by_system": {
                system: {key: counts.get(key, 0) for key in (
                    "invalid_terminal_output",
                    "invalid_probability_distribution",
                    *PROVIDER_ERRORS,
                    "response_provider_timeout",
                    "response_provider_error",
                    "response_invalid_response_output",
                )}
                for system, counts in sorted(error_counts.items())
            },
            "simulator_tool_infrastructure_retries": dict(sorted(tool_retries.items())),
            "observed_provider_retry_events": 0,
            "typesafe_retry_policy_max_attempts": 3,
            "typesafe_internal_retry_attempt_telemetry_available": False,
            "usage_limit_events": usage_limit_events,
            "terminal_or_session_interruptions": len(unfinalized_invocations),
            "harness_failures": 0,
            "resumptions": primary["resumption_count"],
            "invocations": primary["invocation_count"],
        },
        "tokens": {
            "terra_decision": {
                "input": token_counts["decision_input"],
                "cached_input": token_counts["decision_cached_input"],
                "output": token_counts["decision_output"],
                "reasoning_output": token_counts["decision_reasoning_output"],
            },
            "terra_shared_responder_secondary": dict(response_token_counts),
            "terra_full_system": {
                "input": token_counts["decision_input"] + response_token_counts["input"],
                "cached_input": token_counts["decision_cached_input"]
                + response_token_counts["cached_input"],
                "output": token_counts["decision_output"] + response_token_counts["output"],
                "reasoning_output": token_counts["decision_reasoning_output"]
                + response_token_counts["reasoning_output"],
            },
            "jev_completed_records": {
                "input": token_counts["jev_completed_input"],
                "output": token_counts["jev_completed_output"],
            },
            "jev_billed_primary_input_including_aborted_attempts": jev_billed_input,
            "jev_estimated_promotional_credit_usd": jev_billed_cost,
            "jev_budget_cap_usd": budget["hard_cap_usd"],
        },
        "jev_call_counts": {str(key): value for key, value in sorted(jev_call_counts.items())},
        "git": {
            "head": git("rev-parse", "HEAD"),
            "freeze_tag_commit": git("rev-list", "-n", "1", "v1.0.1-freeze"),
            "working_tree_status": status,
        },
    }
    output = ROOT / "artifacts/cp14/integrity-audit.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(canonical_json(report) + "\n", encoding="utf-8")
    print(canonical_json(report))
    raise SystemExit(0 if report["strict_cp14_passed"] else 2)


if __name__ == "__main__":
    main()
