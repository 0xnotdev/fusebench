"""Mechanical CP-13 fairness audit with no provider calls or outcome inspection."""

from __future__ import annotations

import asyncio
import inspect
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any

from fusebench.agents.responder import ResponseStageResult
from fusebench.agents.terra_jev import TerraJevAgent
from fusebench.agents.terra_jev import _finalize_decision as finalize_jev_decision
from fusebench.agents.terra_only import TerraOnlyAgent
from fusebench.benchmark.runner import _build_record
from fusebench.contracts.actions import Action, IssueType
from fusebench.contracts.case import BenchmarkCase, HiddenTruth, PaymentRecord, VisibleCase
from fusebench.contracts.results import RunRecord
from fusebench.contracts.tools import ReadTool
from fusebench.dataset.validation import canonical_json, serialize_visible_case
from fusebench.jev.parsing import JevDecision
from fusebench.jev.state import build_initial_state
from fusebench.metrics.efficiency import summarize_efficiency
from fusebench.providers.codex_app_server import (
    TerraFinalDecision,
    TerraTurnResult,
    TerraUsage,
    terra_output_schema,
    terra_read_tool_definitions,
)
from fusebench.simulator.environment import SimulatorEnvironment
from fusebench.simulator.tool_runtime import ToolRuntime

ACCEPTED_CP12_COMMIT = "1e06731306a2f9cc3d85ec1aef1c1dac3bc6c587"

# These are the existing experimental semantics the user required to remain
# byte-for-byte unchanged during the final mechanical audit.
FAIRNESS_SEMANTIC_PATHS = (
    ".env.example",
    "pyproject.toml",
    "prompts/terra_agent.md",
    "prompts/terra_response.md",
    "spec.md",
    "spec(4).md",
    "src/fusebench/agents/base.py",
    "src/fusebench/agents/responder.py",
    "src/fusebench/agents/terra_jev.py",
    "src/fusebench/agents/terra_only.py",
    "src/fusebench/benchmark/runner.py",
    "src/fusebench/benchmark/scheduler.py",
    "src/fusebench/config.py",
    "src/fusebench/constants.py",
    "src/fusebench/contracts/actions.py",
    "src/fusebench/contracts/case.py",
    "src/fusebench/contracts/decisions.py",
    "src/fusebench/contracts/events.py",
    "src/fusebench/contracts/results.py",
    "src/fusebench/contracts/tools.py",
    "src/fusebench/jev/parsing.py",
    "src/fusebench/jev/questions.py",
    "src/fusebench/jev/state.py",
    "src/fusebench/metrics/calibration.py",
    "src/fusebench/metrics/consistency.py",
    "src/fusebench/metrics/correctness.py",
    "src/fusebench/metrics/coverage.py",
    "src/fusebench/metrics/efficiency.py",
    "src/fusebench/metrics/report.py",
    "src/fusebench/metrics/statistics.py",
    "src/fusebench/policy/loss.py",
    "src/fusebench/policy/oracle.py",
    "src/fusebench/policy/policy.md",
    "src/fusebench/providers/base.py",
    "src/fusebench/providers/codex_app_server.py",
    "src/fusebench/providers/codex_protocol.py",
    "src/fusebench/providers/isolation.py",
    "src/fusebench/providers/typesafe_jev.py",
    "src/fusebench/simulator/environment.py",
    "src/fusebench/simulator/failures.py",
    "src/fusebench/simulator/fixtures.py",
    "src/fusebench/simulator/tool_runtime.py",
    "uv.lock",
)


def _hash(data: bytes) -> str:
    return sha256(data).hexdigest()


def _git_bytes(root: Path, ref: str, relative_path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{ref}:{relative_path}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"cannot read {relative_path} at {ref}")
    return completed.stdout


def _mechanical_case() -> BenchmarkCase:
    visible = VisibleCase(
        case_id="AUDIT_0001",
        customer_id="CUS-AUDIT",
        order_id="ORD-AUDIT",
        sku="SKU-AUDIT",
        customer_message="Tracking has not moved for seven days.",
        amount_inr=3499,
        basic_status="shipped",
    )
    return BenchmarkCase(
        visible=visible,
        hidden=HiddenTruth(
            issue_type=IssueType.SHIPPING,
            days_without_carrier_movement=7,
            carrier_status="in_transit",
            inventory_available=2,
            payment_records=(
                PaymentRecord(charge_id="CH-AUDIT", amount_inr=3499, status="settled"),
            ),
            damage_evidence_required=True,
            damage_evidence_present=True,
            damage_evidence_valid=True,
            prior_exception_refunds_90d=0,
            trusted_records_conflict=False,
        ),
        category="clean",
        gold_action=Action.RESHIP,
        minimal_required_read_tools=frozenset(
            {"get_tracking", "get_inventory", "get_customer_risk"}
        ),
        allowed_autonomous_actions=frozenset({Action.RESHIP}),
        generation_metadata={"audit_fixture": True},
    )


async def _equivalent_observations(case: BenchmarkCase) -> dict[str, Any]:
    terra = ToolRuntime(SimulatorEnvironment.from_case(case, seed=17), "terra_only")
    jev = ToolRuntime(SimulatorEnvironment.from_case(case, seed=17), "terra_jev")
    arguments = {
        ReadTool.GET_TRACKING: {"order_id": case.visible.order_id},
        ReadTool.GET_PAYMENT: {"order_id": case.visible.order_id},
        ReadTool.GET_INVENTORY: {"sku": case.visible.sku},
        ReadTool.GET_DAMAGE_EVIDENCE: {"order_id": case.visible.order_id},
        ReadTool.GET_CUSTOMER_RISK: {"customer_id": case.visible.customer_id},
    }
    observations: dict[str, Any] = {}
    for tool in ReadTool:
        terra_result = await terra.call_read(tool, arguments[tool])
        jev_result = await jev.call_read(tool, arguments[tool])
        if terra_result.result != jev_result.result or terra_result.error != jev_result.error:
            raise AssertionError(f"trusted observation differs for {tool.value}")
        observations[tool.value] = terra_result.result
    return observations


def _terra_result(action: Action) -> TerraTurnResult:
    probabilities = {candidate: 0.0 for candidate in Action}
    probabilities[action] = 1.0
    return TerraTurnResult(
        thread_id="audit-thread",
        turn_id="audit-turn",
        output=TerraFinalDecision(
            kind="final",
            action_probabilities=probabilities,
            reason_code="MECHANICAL_AUDIT",
        ),
        raw_text="{}",
        usage=TerraUsage(
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            reasoning_output_tokens=0,
        ),
        raw_token_events=(),
    )


def _jev_result(action: Action) -> JevDecision:
    probabilities = {candidate: 0.0 for candidate in Action}
    probabilities[action] = 1.0
    return JevDecision(
        action=action,
        action_probabilities=probabilities,
        action_confidence=1.0,
        information_sufficient=1.0,
        requires_human=0.0,
        risk_score=1.0,
        risk_confidence=1.0,
        risk_legend={1: "low"},
        risk_probabilities={1: 1.0},
        reported_model="jev-1.13.0",
        input_tokens=0,
        output_tokens=0,
        latency_ms=0.0,
    )


def _risk_outcomes(
    action: Action,
    risk: dict[str, Any] | None,
    *,
    unavailable: bool = False,
) -> tuple[Action, Action]:
    terra = TerraOnlyAgent._finalize_decision(
        _terra_result(action),
        errors=[],
        loop_limit_exceeded=False,
        risk_result=risk,
        risk_unavailable=unavailable,
        risk_requested=risk is not None or unavailable,
    )
    jev = finalize_jev_decision(
        _jev_result(action),
        observations={"customer_risk": risk} if risk is not None else {},
        observation_errors=(
            {"customer_risk": {"kind": "unavailable", "persistent": True}}
            if unavailable
            else {}
        ),
        late_risk_unavailable=unavailable,
        harness_errors=[],
    )
    return terra.executed_action, jev.executed_action


def build_mechanical_fairness_audit(
    root: Path,
    *,
    baseline_ref: str = ACCEPTED_CP12_COMMIT,
) -> dict[str, Any]:
    """Return a code/config-only fairness report and raise on any failed invariant."""

    root = root.resolve()
    semantic_hashes: dict[str, str] = {}
    changed: list[str] = []
    for relative in FAIRNESS_SEMANTIC_PATHS:
        current = (root / relative).read_bytes()
        baseline = _git_bytes(root, baseline_ref, relative)
        semantic_hashes[relative] = _hash(current)
        if current != baseline:
            changed.append(relative)
    if changed:
        raise RuntimeError(f"fairness-critical semantics changed since CP-12: {changed}")

    case = _mechanical_case()
    visible = serialize_visible_case(case)
    initial_jev = build_initial_state("identical-policy-bytes", case)
    hidden_names = {"prior_exception_refunds_90d", "trusted_records_conflict"}
    if hidden_names & set(visible) or hidden_names & set(initial_jev["visible_case"]):
        raise RuntimeError("customer risk fields are exposed without a tool read")

    observations = asyncio.run(_equivalent_observations(case))
    risk = observations[ReadTool.GET_CUSTOMER_RISK.value]
    assert isinstance(risk, dict)
    unrelated = {
        key: value
        for key, value in observations.items()
        if key != ReadTool.GET_CUSTOMER_RISK.value
    }
    if any(hidden_names & set(value or {}) for value in unrelated.values()):
        raise RuntimeError("customer risk fields leaked through an unrelated read tool")

    safe = dict(risk)
    risky_refunds = {**safe, "prior_exception_refunds_90d": 2}
    risky_conflict = {**safe, "trusted_records_conflict": True}
    risk_results = {
        action.value: {
            "missing": _risk_outcomes(action, None),
            "unavailable": _risk_outcomes(action, None, unavailable=True),
            "safe": _risk_outcomes(action, safe),
            "prior_refund_limit": _risk_outcomes(action, risky_refunds),
            "trusted_conflict": _risk_outcomes(action, risky_conflict),
        }
        for action in (Action.REFUND, Action.RESHIP)
    }
    expected = {
        action.value: {
            "missing": (Action.ESCALATE, Action.ESCALATE),
            "unavailable": (Action.ESCALATE, Action.ESCALATE),
            "safe": (action, action),
            "prior_refund_limit": (Action.ESCALATE, Action.ESCALATE),
            "trusted_conflict": (Action.ESCALATE, Action.ESCALATE),
        }
        for action in (Action.REFUND, Action.RESHIP)
    }
    if risk_results != expected:
        raise RuntimeError(f"customer risk pre-action semantics differ: {risk_results}")

    tools = terra_read_tool_definitions()
    if [tool["name"] for tool in tools] != [tool.value for tool in ReadTool]:
        raise RuntimeError("Terra does not expose exactly the five trusted read tools")
    if "action_probabilities" not in terra_output_schema().get("properties", {}):
        raise RuntimeError("Terra terminal schema is not the final-decision schema")
    provider_source = (root / "src/fusebench/providers/codex_app_server.py").read_text(
        encoding="utf-8"
    )
    dynamic_markers = (
        '"dynamicTools": dynamic_tools',
        '"outputSchema": terra_output_schema()',
        "while True:",
        "self._handle_tool_request(",
        "if events_task in done:",
    )
    if not all(marker in provider_source for marker in dynamic_markers):
        raise RuntimeError("Terra dynamic-tool event loop protocol is incomplete")

    runner_source = inspect.getsource(_build_record)
    efficiency_source = inspect.getsource(summarize_efficiency)
    response_fields = set(ResponseStageResult.model_fields)
    run_fields = set(RunRecord.model_fields)
    latency_cost_ok = (
        "decision_path_latency_ms=outcome.decision_path_latency_ms" in runner_source
        and "response.full_response_latency_ms" in runner_source
        and "record.decision_path_latency_ms" in efficiency_source
        and "response_input_tokens" in response_fields
        and "response_output_tokens" in response_fields
        and "response_input_tokens" not in run_fields
        and "response_output_tokens" not in run_fields
    )
    if not latency_cost_ok:
        raise RuntimeError("decision and shared-responder telemetry are not separated")

    terra_agent_source = inspect.getsource(TerraOnlyAgent)
    jev_agent_source = inspect.getsource(TerraJevAgent)
    if "self.policy_text = policy_text" not in terra_agent_source or (
        "self.policy_text = policy_text" not in jev_agent_source
    ):
        raise RuntimeError("both architectures do not retain the same injected policy bytes")

    checks = {
        "customer_risk_pre_action_parity": {
            "passed": True,
            "detail": (
                "Both architectures fail closed without risk, permit a safe read, and "
                "override REFUND/RESHIP for either frozen global-risk condition."
            ),
        },
        "customer_risk_not_free": {
            "passed": True,
            "detail": (
                "Hidden risk fields are absent from VisibleCase, initial Jev state, and all "
                "four unrelated trusted read responses."
            ),
        },
        "terra_dynamic_tool_loop": {
            "passed": True,
            "detail": (
                "Five dynamic tools are attached at thread/start; item/tool/call requests are "
                "handled until turn completion; outputSchema constrains only the final message."
            ),
        },
        "decision_vs_responder_accounting": {
            "passed": True,
            "detail": (
                "Decision latency/tokens drive primary efficiency; full latency and responder "
                "tokens remain separate secondary/raw telemetry."
            ),
        },
        "policy_and_observation_parity": {
            "passed": True,
            "detail": (
                "Both agents receive the same policy bytes and the same ToolRuntime produced "
                "equivalent results for every trusted read."
            ),
        },
        "frozen_semantics_unchanged": {
            "passed": True,
            "detail": (
                "Prompts, Jev questions, thresholds, policy/oracle/loss, tool schemas, provider "
                "settings, metrics, scoring, and runtime match the accepted CP-12 commit."
            ),
        },
    }
    return {
        "audit": "CP-13 final mechanical fairness audit",
        "baseline_commit": baseline_ref,
        "passed": all(check["passed"] for check in checks.values()),
        "scope": "code_and_configuration_only",
        "dev_outcomes_read": False,
        "provider_calls": 0,
        "test_inference_calls": 0,
        "checks": checks,
        "semantic_file_hashes": semantic_hashes,
    }


def write_mechanical_fairness_audit(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(report) + "\n", encoding="utf-8")
