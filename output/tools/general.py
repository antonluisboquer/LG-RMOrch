"""General workflow tools — write_todo, get_workflow_status, save_step_report.

Battle-tested enforcement logic ensuring the agent cannot skip steps,
jump ahead, or mark steps complete without calling required tools.
Adapted from DocsOrch Agent Factory pattern.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from registry import (
    GENERAL_TOOLS,
    SKIP_STEP_TOOLS,
    STEP_ORDER,
    get_next_step,
    get_step_config,
    get_step_number,
    is_step_skipped,
    is_substep_skipped,
)

logger = logging.getLogger(__name__)


def _get_step_phase(step_id: str) -> str:
    cfg = get_step_config(step_id)
    return cfg.phase if cfg else "UNKNOWN"


def _get_step_name(step_id: str) -> str:
    cfg = get_step_config(step_id)
    return cfg.name if cfg else step_id


def _get_substep_name(step_id: str, substep_id: str) -> str:
    cfg = get_step_config(step_id)
    if cfg and cfg.substeps:
        parts = substep_id.split(".")
        if len(parts) == 2:
            sub_key = parts[1]
            ss = cfg.substeps.get(sub_key)
            if ss:
                return ss.name
    return substep_id


def _get_ordered_substep_ids(step_id: str) -> list:
    cfg = get_step_config(step_id)
    if not cfg or not cfg.substeps:
        return []
    step_num = get_step_number(step_id)
    return [f"{step_num}.{k}" for k in sorted(cfg.substeps.keys(), key=lambda x: int(x))]


def _collect_substep_flags(state: dict, substep_id: str) -> list:
    return [f for f in (state.get("flags") or []) if f.get("substep") == substep_id]


def _check_substep_tool_called(step_id: str, substep_id: str, messages: list) -> dict:
    cfg = get_step_config(step_id)
    if not cfg or not cfg.substeps:
        return {"passed": True, "required_tools": [], "called_tools": []}

    parts = substep_id.split(".")
    if len(parts) != 2:
        return {"passed": True, "required_tools": [], "called_tools": []}

    sub_key = parts[1]
    ss = cfg.substeps.get(sub_key)
    if not ss:
        return {"passed": True, "required_tools": [], "called_tools": []}

    required_tools = ss.tools if hasattr(ss, "tools") and ss.tools else []
    if not required_tools:
        return {"passed": True, "required_tools": [], "called_tools": []}

    called_tools = set()
    for msg in messages:
        if hasattr(msg, "tool_calls"):
            for tc in msg.tool_calls:
                called_tools.add(tc.get("name", ""))
        if hasattr(msg, "name") and msg.name:
            called_tools.add(msg.name)

    missing = [t for t in required_tools if t not in called_tools and t not in GENERAL_TOOLS]

    if missing:
        return {
            "passed": False,
            "required_tools": required_tools,
            "called_tools": list(called_tools),
            "missing_message": (
                f"Substep {substep_id} requires tool(s): {', '.join(missing)}. "
                f"Call the required tool(s) before marking this substep complete."
            ),
        }

    return {"passed": True, "required_tools": required_tools, "called_tools": list(called_tools)}


def _check_step_tools_called(step_id: str, messages: list, skip_substep_nums: set | None = None) -> dict:
    cfg = get_step_config(step_id)
    if not cfg or not cfg.substeps:
        return {"passed": True, "required_tools": [], "called_tools": [], "missing_substeps": []}

    called_tools = set()
    for msg in messages:
        if hasattr(msg, "tool_calls"):
            for tc in msg.tool_calls:
                called_tools.add(tc.get("name", ""))
        if hasattr(msg, "name") and msg.name:
            called_tools.add(msg.name)

    step_num = get_step_number(step_id)
    missing_substeps = []
    all_required = []

    for sub_key, ss in sorted(cfg.substeps.items(), key=lambda x: int(x[0])):
        full_id = f"{step_num}.{sub_key}"

        if skip_substep_nums and full_id in skip_substep_nums:
            continue
        if is_substep_skipped(step_id, full_id):
            continue

        tools = ss.tools if hasattr(ss, "tools") and ss.tools else []
        step_tools = [t for t in tools if t not in GENERAL_TOOLS]
        all_required.extend(step_tools)

        for t in step_tools:
            if t not in called_tools:
                missing_substeps.append(full_id)
                break

    if missing_substeps:
        return {
            "passed": False,
            "required_tools": all_required,
            "called_tools": list(called_tools),
            "missing_substeps": missing_substeps,
            "missing_message": (
                f"Step {step_id} has incomplete substeps: {', '.join(missing_substeps)}. "
                f"Call the required tools before marking the step complete."
            ),
        }

    return {"passed": True, "required_tools": all_required, "called_tools": list(called_tools), "missing_substeps": []}


def _auto_skip_steps(start_step: str, state_update: dict, timestamp: str) -> tuple:
    skipped = []
    current = start_step

    while current and is_step_skipped(current):
        cfg = get_step_config(current)
        state_update["step_reports"] = state_update.get("step_reports", {})
        state_update["step_reports"][f"{current}_status"] = {
            "step_id": current,
            "step_number": get_step_number(current),
            "step_name": cfg.name if cfg else current,
            "phase": cfg.phase if cfg else None,
            "substep_id": None,
            "substep_name": None,
            "status": "skipped",
            "timestamp": timestamp,
            "notes": "Auto-skipped (step is in skip list)",
            "flagged_items": [],
        }
        skipped.append(current)
        current = get_next_step(current)

    if current is None:
        return "COMPLETED", skipped
    return current, skipped


def _build_workflow_plan() -> dict:
    plan = {}
    for step_id in STEP_ORDER:
        cfg = get_step_config(step_id)
        if cfg:
            plan[step_id] = {
                "name": cfg.name,
                "phase": cfg.phase,
                "skipped": is_step_skipped(step_id),
            }
    return plan


@tool
def write_todo(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
    step_id: str,
    substep_id: Optional[str] = None,
    status: str = "pending",
    notes: Optional[str] = None,
    flagged_items: Optional[List[Dict[str, Any]]] = None,
) -> Command:
    """Update step/substep status in workflow state.

    IMPORTANT: Always track at substep level when executing substeps!
    - Step-level: write_todo(step_id="STEP_01", status="in_progress")
    - Substep-level: write_todo(step_id="STEP_01", substep_id="1.3", status="completed", notes="<detailed>")

    ENFORCEMENT: When marking a step as completed, at least one step-specific tool
    MUST have been called. The agent cannot skip steps.

    Args:
        step_id: Step ID (e.g., "STEP_01", "STEP_04")
        substep_id: Substep ID (e.g., "1.1", "4.3")
        status: One of: "pending", "in_progress", "completed", "cancelled"
        notes: Detailed substep report with check results, field IDs and values.
        flagged_items: Optional flagged items with remedies
    """
    phase = _get_step_phase(step_id)
    step_name = _get_step_name(step_id)
    step_num = get_step_number(step_id)

    if substep_id and is_step_skipped(step_id):
        return Command(update={"messages": [ToolMessage(
            content=json.dumps({
                "success": True, "step_id": step_id, "substep_id": substep_id,
                "status": "ignored",
                "message": f"Step {step_id} is SKIPPED. Just call write_todo(step_id='{step_id}', status='completed') once.",
            }),
            name="write_todo", tool_call_id=tool_call_id,
        )]})

    _is_config_ss_skipped = substep_id and is_substep_skipped(step_id, substep_id)
    _dynamic_skipping_list = state.get("dynamic_skipping", []) or []
    _is_dynamic_ss_skipped = substep_id and substep_id in _dynamic_skipping_list

    if _is_config_ss_skipped or _is_dynamic_ss_skipped:
        status = "skipped"
        if not notes:
            notes = "Auto-skipped (config)" if _is_config_ss_skipped else "Dynamically skipped"

    if status == "in_progress":
        step_reports = state.get("step_reports", {})
        check_key = f"{step_id}_{substep_id.replace('.', '_')}_status" if substep_id else f"{step_id}_status"
        existing = step_reports.get(check_key, {})
        existing_status = existing.get("status") if isinstance(existing, dict) else None
        if existing_status in ("completed", "skipped"):
            what = f"Substep {substep_id}" if substep_id else f"Step {step_id}"
            return Command(update={"messages": [ToolMessage(
                content=json.dumps({
                    "success": True, "step_id": step_id, "substep_id": substep_id,
                    "status": existing_status,
                    "message": f"{what} is already {existing_status}. Proceed with current workflow.",
                }),
                name="write_todo", tool_call_id=tool_call_id,
            )]})

        if not substep_id:
            current_step = state.get("current_step")
            if current_step and current_step != "COMPLETED" and step_id != current_step:
                current_status = step_reports.get(f"{current_step}_status", {})
                current_done = isinstance(current_status, dict) and current_status.get("status") in ("completed", "skipped")
                current_skipped = is_step_skipped(current_step)
                if not current_done and not current_skipped:
                    return Command(update={"messages": [ToolMessage(
                        content=json.dumps({
                            "success": False, "step_id": step_id, "status": "blocked",
                            "message": f"Cannot start {step_id}. Current step {current_step} is not completed yet.",
                        }),
                        name="write_todo", tool_call_id=tool_call_id,
                    )]})

    if status == "completed" and substep_id:
        messages = state.get("messages", [])
        enforcement = _check_substep_tool_called(step_id, substep_id, messages)
        if not enforcement["passed"]:
            return Command(update={"messages": [ToolMessage(
                content=json.dumps({
                    "success": False, "step_id": step_id, "substep_id": substep_id,
                    "status": "blocked", "enforcement_failed": True,
                    "required_tools": enforcement["required_tools"],
                    "message": enforcement["missing_message"],
                }),
                name="write_todo", tool_call_id=tool_call_id,
            )]})

    if status == "completed" and not substep_id:
        messages = state.get("messages", [])
        _dyn_skip_set = set(state.get("dynamic_skipping", []) or [])
        enforcement = _check_step_tools_called(step_id, messages, skip_substep_nums=_dyn_skip_set)
        if not enforcement["passed"]:
            return Command(update={"messages": [ToolMessage(
                content=json.dumps({
                    "success": False, "step_id": step_id, "status": "blocked",
                    "enforcement_failed": True,
                    "required_tools": enforcement["required_tools"],
                    "message": enforcement["missing_message"],
                }),
                name="write_todo", tool_call_id=tool_call_id,
            )]})

    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        status_entry = {
            "step_id": step_id, "step_number": step_num, "step_name": step_name,
            "phase": phase, "substep_id": substep_id,
            "substep_name": _get_substep_name(step_id, substep_id) if substep_id else None,
            "status": status, "timestamp": timestamp,
            "notes": notes, "flagged_items": flagged_items or [],
        }

        if substep_id and status in ("completed", "skipped"):
            auto_flags = _collect_substep_flags(state, substep_id)
            if auto_flags:
                existing = status_entry.get("flagged_items") or []
                seen_titles = {f.get("title") for f in existing}
                merged = existing + [f for f in auto_flags if f.get("title") not in seen_titles]
                status_entry["flagged_items"] = merged

        report_key = f"{step_id}_{substep_id.replace('.', '_')}_status" if substep_id else f"{step_id}_status"
        display_str = f"Substep {substep_id}" if substep_id else f"Step {step_num} - [{phase}] {step_name}"

        state_update: dict[str, Any] = {"step_reports": {report_key: status_entry}}

        if status == "in_progress":
            state_update["current_step"] = step_id
            if substep_id:
                state_update["current_substep"] = substep_id
                state_update["substep_started_at"] = timestamp
            else:
                state_update["current_substep"] = None
                state_update["substep_started_at"] = None
                if not state.get("step_start_message_index"):
                    state_update["step_start_message_index"] = len(state.get("messages", []))

        elif status == "completed" and not substep_id:
            immediate_next = get_next_step(step_id)
            if immediate_next:
                landing_step, skipped_steps = _auto_skip_steps(immediate_next, state_update, timestamp)
            else:
                landing_step, skipped_steps = "COMPLETED", []

            state_update["current_step"] = landing_step
            state_update["current_substep"] = None

            if landing_step != "COMPLETED":
                state_update["step_start_message_index"] = len(state.get("messages", []))
                landing_cfg = get_step_config(landing_step)
                state_update["step_reports"][f"{landing_step}_status"] = {
                    "step_id": landing_step,
                    "step_number": get_step_number(landing_step),
                    "step_name": landing_cfg.name if landing_cfg else landing_step,
                    "phase": landing_cfg.phase if landing_cfg else None,
                    "substep_id": None, "substep_name": None,
                    "status": "in_progress", "timestamp": timestamp,
                    "notes": f"Auto-started after {step_id}", "flagged_items": [],
                }
                state_update["workflow_plan"] = _build_workflow_plan()

        if status in ("completed", "skipped") and substep_id:
            state_update["substep_started_at"] = None

            ordered = _get_ordered_substep_ids(step_id)
            try:
                current_idx = ordered.index(substep_id)
            except ValueError:
                current_idx = -1
            if current_idx >= 0:
                for candidate_ss in ordered[current_idx + 1:]:
                    if is_substep_skipped(step_id, candidate_ss):
                        candidate_key = f"{step_id}_{candidate_ss.replace('.', '_')}_status"
                        state_update["step_reports"][candidate_key] = {
                            "step_id": step_id, "step_number": step_num,
                            "step_name": step_name, "phase": phase,
                            "substep_id": candidate_ss,
                            "substep_name": _get_substep_name(step_id, candidate_ss),
                            "status": "skipped", "timestamp": timestamp,
                            "notes": "Auto-skipped (dev mode)", "flagged_items": [],
                        }
                        continue
                    state_update["current_substep"] = candidate_ss
                    break

            existing_step_status = state.get("step_reports", {}).get(f"{step_id}_status", {})
            already_completed = isinstance(existing_step_status, dict) and existing_step_status.get("status") == "completed"

            if not already_completed:
                messages = state.get("messages", [])
                enforcement = _check_step_tools_called(step_id, messages)
                if enforcement["passed"]:
                    state_update["step_reports"][f"{step_id}_status"] = {
                        "step_id": step_id, "step_number": step_num,
                        "step_name": step_name, "phase": phase,
                        "substep_id": None, "substep_name": None,
                        "status": "completed", "timestamp": datetime.now(timezone.utc).isoformat(),
                        "notes": f"Auto-completed after substep {substep_id}", "flagged_items": [],
                    }
                    immediate_next = get_next_step(step_id)
                    if immediate_next:
                        landing_step, _ = _auto_skip_steps(immediate_next, state_update, timestamp)
                    else:
                        landing_step = "COMPLETED"

                    state_update["current_step"] = landing_step
                    state_update["current_substep"] = None

                    if landing_step != "COMPLETED":
                        state_update["step_start_message_index"] = len(state.get("messages", []))
                        landing_cfg = get_step_config(landing_step)
                        state_update["step_reports"][f"{landing_step}_status"] = {
                            "step_id": landing_step,
                            "step_number": get_step_number(landing_step),
                            "step_name": landing_cfg.name if landing_cfg else landing_step,
                            "phase": landing_cfg.phase if landing_cfg else None,
                            "substep_id": None, "substep_name": None,
                            "status": "in_progress",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "notes": f"Auto-started after {step_id} auto-completed",
                            "flagged_items": [],
                        }
                        state_update["workflow_plan"] = _build_workflow_plan()

        result = {
            "success": True, "step_id": step_id, "step_name": step_name,
            "phase": phase, "substep_id": substep_id, "status": status,
            "timestamp": timestamp,
            "message": f"Status updated: {display_str} -> {status}",
        }

        state_update["messages"] = [ToolMessage(
            content=json.dumps(result), name="write_todo", tool_call_id=tool_call_id,
        )]
        return Command(update=state_update)

    except Exception as e:
        logger.error(f"[WRITE_TODO] Error: {e}")
        return Command(update={"messages": [ToolMessage(
            content=json.dumps({"success": False, "error": str(e)}),
            name="write_todo", tool_call_id=tool_call_id,
        )]})


@tool
def get_workflow_status(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Get current workflow status summary including steps, flags, and progress."""
    current_step = state.get("current_step")
    current_substep = state.get("current_substep")
    step_reports = state.get("step_reports", {})

    steps_completed, steps_in_progress, steps_skipped = [], [], []

    for sid in STEP_ORDER:
        entry = step_reports.get(f"{sid}_status", {})
        st = entry.get("status") if isinstance(entry, dict) else None
        cfg = get_step_config(sid)
        info = {"step_id": sid, "name": cfg.name if cfg else sid, "phase": cfg.phase if cfg else ""}

        if st == "completed":
            steps_completed.append(info)
        elif st == "in_progress":
            steps_in_progress.append(info)
        elif st == "skipped":
            steps_skipped.append(sid)

    flags = state.get("flags", [])
    flags_by_severity = {}
    for f in flags:
        sev = f.get("severity", "unknown")
        flags_by_severity[sev] = flags_by_severity.get(sev, 0) + 1

    result = {
        "success": True,
        "current_step": current_step,
        "current_substep": current_substep,
        "steps_completed": len(steps_completed),
        "steps_in_progress": len(steps_in_progress),
        "steps_skipped": len(steps_skipped),
        "total_steps": len(STEP_ORDER),
        "flags_total": len(flags),
        "flags_unresolved": len([f for f in flags if not f.get("resolved")]),
        "flags_by_severity": flags_by_severity,
    }

    return Command(update={"messages": [ToolMessage(
        content=json.dumps(result), tool_call_id=tool_call_id,
    )]})


@tool
def save_step_report(
    tool_call_id: Annotated[str, InjectedToolCallId],
    step_name: str,
    status: str,
    summary: str,
    details: Optional[Dict[str, Any]] = None,
    issues: Optional[List[Dict[str, Any]]] = None,
    metrics: Optional[Dict[str, Any]] = None,
) -> Command:
    """Save a detailed step report for audit trail and UI access.

    Args:
        step_name: Step ID (e.g., "STEP_01")
        status: "completed", "partial", "failed", "skipped"
        summary: Brief summary
        details: Optional detailed results
        issues: Optional list of issues
        metrics: Optional metrics dict
    """
    step_key = step_name.upper().replace("-", "_")
    if not step_key.startswith("STEP_"):
        num = step_key.replace("STEP", "").replace("_", "")
        if num.isdigit():
            step_key = f"STEP_{int(num):02d}"

    timestamp = datetime.now(timezone.utc).isoformat()

    report = {
        "step_name": step_key, "status": status, "summary": summary,
        "timestamp": timestamp, "details": details or {},
        "issues": issues or [], "metrics": metrics or {},
    }

    result = {
        "success": True, "step_name": step_key, "status": status,
        "message": f"Report saved for {step_key}: {status}",
    }

    return Command(update={
        "step_fullReports": {step_key: report},
        "messages": [ToolMessage(content=json.dumps(result), tool_call_id=tool_call_id)],
    })
