"""RMOrch Agent v1.0.0 — LangGraph agent entry point.

Adapted from the DocsOrch Agent Factory pattern (see ARCHITECTURE.md of
LG-ConstructionEncompass). Same architecture:
- Step-based workflow with dynamic tool scoping per step
- Per-step plan injection
- Middleware for state schema, system-message normalization, workflow guard

This agent models the TPO Relationship Manager (RM) Job Aid as an ordered
workflow: Data Gathering (STEP_00), then the downstream job-aid sections
(Pipeline Management, Conditions Queue, ...).
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Annotated, Any

try:
    from typing import NotRequired
except ImportError:
    from typing_extensions import NotRequired

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

load_dotenv()

_MIN_RECURSION_LIMIT = int(os.getenv("LANGGRAPH_DEFAULT_RECURSION_LIMIT", "100000"))

import langgraph._internal._config as _lg_cfg

_lg_cfg.DEFAULT_RECURSION_LIMIT = _MIN_RECURSION_LIMIT

_original_merge_configs = _lg_cfg.merge_configs

def _patched_merge_configs(*configs):
    result = _original_merge_configs(*configs)
    if result.get("recursion_limit", 0) < _MIN_RECURSION_LIMIT:
        result["recursion_limit"] = _MIN_RECURSION_LIMIT
    return result

_lg_cfg.merge_configs = _patched_merge_configs

try:
    import langgraph.pregel.main as _pregel_main
    if hasattr(_pregel_main, "merge_configs"):
        _pregel_main.merge_configs = _patched_merge_configs
except Exception:
    pass

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PARENT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if PARENT_ROOT not in sys.path:
    sys.path.insert(0, PARENT_ROOT)

from copilotagent import create_deep_agent
from langchain.agents.middleware.types import AgentMiddleware, AgentState, OmitFromInput
from langgraph.graph.message import add_messages

logger = logging.getLogger(__name__)

try:
    from copilotkit import CopilotKitMiddleware
    HAS_COPILOTKIT = True
except ImportError:
    HAS_COPILOTKIT = False
    logger.info("[INIT] copilotkit package not found — running without CopilotKit middleware")

from registry import (
    STEP_ORDER,
    get_step_config,
    get_step_number,
    is_step_skipped,
    is_substep_skipped,
    get_next_step,
    get_step_tools_excluding_skipped,
    generate_workflow_overview,
    GENERAL_TOOLS,
    SKIP_STEP_TOOLS,
)
from step_loader import load_plan_content

MAX_TOOL_RESULT_SIZE = 15000


# ═══════════════════════════════════════════════════════════════════════
# Reducers
# ═══════════════════════════════════════════════════════════════════════

def merge_dicts(existing: dict | None, new: dict | None) -> dict:
    if existing is None:
        return new or {}
    if new is None:
        return existing
    result = {**existing}
    for key, value in new.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def last_value_reducer(existing: Any | None, new: Any | None) -> Any | None:
    return new if new is not None else existing


def _load_substep_names() -> dict[str, str]:
    if hasattr(_load_substep_names, "_cache"):
        return _load_substep_names._cache
    names: dict[str, str] = {}
    try:
        cfg_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "config", "workflow_config.json"
        )
        with open(cfg_path, "r") as f:
            cfg = json.load(f)
        for step_id, step_data in cfg.get("steps", {}).items():
            step_num = str(int(step_id.replace("STEP_", "")))
            for ss_key, ss_data in (step_data.get("substeps") or {}).items():
                name = ss_data.get("name", "")
                if name:
                    names[f"{step_num}.{ss_key}"] = name
    except Exception:
        pass
    _load_substep_names._cache = names
    return names


def dedupe_flags(existing: list | None, new: list | None) -> list:
    substep_names = _load_substep_names()
    all_flags = (existing or []) + (new or [])
    order: list[tuple[str, str]] = []
    by_key: dict[tuple[str, str], dict] = {}
    for flag in all_flags:
        if not isinstance(flag, dict):
            continue
        key = (flag.get("substep", ""), flag.get("title", ""))
        if "resolved" not in flag:
            flag["resolved"] = flag.get("severity") == "info-overwrite"
        if "timestamp" not in flag:
            flag["timestamp"] = datetime.now(timezone.utc).isoformat()
        flag.pop("hard_stop", None)

        ss = flag.get("substep", "")
        if ss and "substep_name" not in flag:
            if " — " in ss:
                parts = ss.split(" — ", 1)
                flag["substep"] = parts[0]
                flag["substep_name"] = parts[1]
            else:
                flag["substep_name"] = substep_names.get(ss, "")

        if key not in by_key:
            by_key[key] = flag
            order.append(key)
        else:
            prev = by_key[key]
            if not prev.get("resolved") and flag.get("resolved"):
                by_key[key] = flag
    return [by_key[k] for k in order]


def append_list(existing: list | None, new: list | None) -> list:
    return (existing or []) + (new or [])


def truncate_messages(existing: list | None, new: list | None) -> list:
    merged = add_messages(existing, new)
    truncated = []
    for msg in merged:
        if isinstance(msg, ToolMessage):
            content = msg.content
            if isinstance(content, str) and len(content) > MAX_TOOL_RESULT_SIZE:
                truncated_content = content[:MAX_TOOL_RESULT_SIZE] + "\n... [TRUNCATED]"
                truncated.append(ToolMessage(
                    content=truncated_content,
                    tool_call_id=msg.tool_call_id,
                    name=msg.name if hasattr(msg, "name") else None,
                ))
            else:
                truncated.append(msg)
        else:
            truncated.append(msg)
    return truncated


# ═══════════════════════════════════════════════════════════════════════
# State Schema
# ═══════════════════════════════════════════════════════════════════════

class RMOrchState(AgentState):
    """State schema for the RMOrch agent."""

    # Input fields
    loan_number: str
    env: str
    borrower_name: NotRequired[str]
    # Per-run options (e.g. {"allow_dft": false, "dft_reason": "..."}).
    options: NotRequired[dict]
    # When true, bypass the eFolder cache and re-extract documents.
    force_extract: NotRequired[bool]

    # Core data (gathered in STEP_00)
    loan_id: Annotated[NotRequired[str], OmitFromInput, last_value_reducer]
    los_fields: Annotated[NotRequired[dict], OmitFromInput, merge_dicts]
    doc_fields: Annotated[NotRequired[dict], OmitFromInput, merge_dicts]
    efolder_documents: Annotated[NotRequired[dict], OmitFromInput, merge_dicts]
    conditions: Annotated[NotRequired[list], OmitFromInput, last_value_reducer]
    loan_summary: Annotated[NotRequired[dict], OmitFromInput, last_value_reducer]
    loan_profile: Annotated[NotRequired[dict], OmitFromInput, last_value_reducer]

    # Issues and tracking
    flags: Annotated[NotRequired[list[dict]], OmitFromInput, dedupe_flags]

    # Workflow progress
    current_step: Annotated[NotRequired[str | None], OmitFromInput, last_value_reducer]
    current_substep: Annotated[NotRequired[str | None], OmitFromInput, last_value_reducer]
    workflow_plan: Annotated[NotRequired[dict | None], OmitFromInput, last_value_reducer]
    dynamic_skipping: Annotated[NotRequired[list[str]], OmitFromInput, last_value_reducer]
    step_reports: Annotated[NotRequired[dict[str, dict]], OmitFromInput, merge_dicts]
    step_fullReports: Annotated[NotRequired[dict[str, dict]], OmitFromInput, merge_dicts]

    # Action ledger (field writes + condition/milestone/log actions)
    field_writes_ledger: Annotated[NotRequired[list[dict]], OmitFromInput, append_list]

    # Substep timeout tracking
    substep_started_at: Annotated[NotRequired[str | None], OmitFromInput, last_value_reducer]

    # Audit
    step_start_message_index: Annotated[NotRequired[int], OmitFromInput, last_value_reducer]

    # Messages
    messages: Annotated[list, truncate_messages]


# ═══════════════════════════════════════════════════════════════════════
# Step Detection
# ═══════════════════════════════════════════════════════════════════════

def get_current_step_from_state(state: dict) -> str:
    current_step = state.get("current_step")

    if current_step == "COMPLETED":
        return "COMPLETED"

    if current_step:
        step_reports = state.get("step_reports", {})
        step_status = step_reports.get(f"{current_step}_status", {}).get("status")

        if step_status in ("completed", "skipped"):
            candidate = get_next_step(current_step)
            while candidate:
                cand_status = step_reports.get(f"{candidate}_status", {}).get("status")
                if cand_status not in ("completed", "skipped"):
                    return candidate
                candidate = get_next_step(candidate)
            return "COMPLETED"
        return current_step

    step_reports = state.get("step_reports", {})

    for key, value in step_reports.items():
        if key.endswith("_status") and isinstance(value, dict):
            if value.get("status") == "in_progress":
                step_id = value.get("step_id")
                if step_id:
                    return step_id

    completed_nums = set()
    for key, value in step_reports.items():
        if key.endswith("_status") and isinstance(value, dict):
            parts = key.replace("_status", "").split("_")
            if len(parts) == 2 and parts[0] == "STEP" and value.get("status") == "completed":
                step_id = value.get("step_id")
                if step_id:
                    try:
                        completed_nums.add(int(step_id.replace("STEP_", "")))
                    except ValueError:
                        pass

    if completed_nums:
        last_num = max(completed_nums)
        next_num = last_num + 1
        max_step = max(int(s.replace("STEP_", "")) for s in STEP_ORDER)
        if next_num <= max_step:
            return f"STEP_{next_num:02d}"
        return "COMPLETED"

    return STEP_ORDER[0] if STEP_ORDER else "STEP_00"


# ═══════════════════════════════════════════════════════════════════════
# Resolvers
# ═══════════════════════════════════════════════════════════════════════

_ALL_TOOLS_REF = None


def resolve_tools_for_step(state: dict) -> list:
    global _ALL_TOOLS_REF

    if _ALL_TOOLS_REF is None:
        logger.warning("[TOOL_RESOLVER] _ALL_TOOLS_REF not initialized, returning []")
        return []

    current_step = get_current_step_from_state(state)

    if current_step == "COMPLETED":
        completed_tools = [t for t in _ALL_TOOLS_REF
                           if getattr(t, "name", getattr(t, "__name__", "")) in SKIP_STEP_TOOLS]
        logger.info(f"[TOOL_RESOLVER] Workflow COMPLETED — {len(completed_tools)} tools")
        return completed_tools

    if is_step_skipped(current_step):
        skip_tools = [t for t in _ALL_TOOLS_REF
                      if getattr(t, "name", getattr(t, "__name__", "")) in SKIP_STEP_TOOLS]
        logger.info(f"[TOOL_RESOLVER] {current_step} SKIPPED — {len(skip_tools)} tools")
        return skip_tools

    dynamic_skipping = set(state.get("dynamic_skipping", []) or [])

    allowed_names = get_step_tools_excluding_skipped(
        current_step, extra_skip_substeps=dynamic_skipping
    )

    filtered = [t for t in _ALL_TOOLS_REF
                if getattr(t, "name", getattr(t, "__name__", "")) in allowed_names]

    tool_names = sorted(getattr(t, "name", getattr(t, "__name__", "")) for t in filtered)
    step_tools = [n for n in tool_names if n not in GENERAL_TOOLS]
    logger.info(
        f"[TOOL_RESOLVER] {current_step} — "
        f"{len(filtered)} tools ({len(step_tools)} step-specific: {step_tools})"
    )
    return filtered


def resolve_plan_for_step(state: dict) -> str | None:
    current_step = get_current_step_from_state(state)

    if current_step == "COMPLETED":
        return None
    if is_step_skipped(current_step):
        return None

    try:
        return load_plan_content(current_step)
    except Exception as e:
        logger.warning(f"[PLAN_RESOLVER] Could not load plan for {current_step}: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════
# Middleware
# ═══════════════════════════════════════════════════════════════════════

class RMOrchMiddleware(AgentMiddleware):
    state_schema = RMOrchState


class SystemMessageNormalizerMiddleware(AgentMiddleware):
    async def awrap_model_call(self, request, handler):
        messages = list(request.messages)
        system_msgs = [m for m in messages if getattr(m, "type", None) in ("system", "developer")]
        non_system_msgs = [m for m in messages if getattr(m, "type", None) not in ("system", "developer")]
        if len(system_msgs) > 1 or (system_msgs and non_system_msgs and messages.index(system_msgs[0]) > 0):
            request = request.override(messages=system_msgs + non_system_msgs)
        return await handler(request)

    def wrap_model_call(self, request, handler):
        messages = list(request.messages)
        system_msgs = [m for m in messages if getattr(m, "type", None) in ("system", "developer")]
        non_system_msgs = [m for m in messages if getattr(m, "type", None) not in ("system", "developer")]
        if len(system_msgs) > 1 or (system_msgs and non_system_msgs and messages.index(system_msgs[0]) > 0):
            request = request.override(messages=system_msgs + non_system_msgs)
        return handler(request)


class WorkflowGuardMiddleware(AgentMiddleware):
    MAX_RETRIES = 2
    SUBSTEP_TIMEOUT_SECONDS = 600

    def _is_workflow_done(self, state: dict) -> bool:
        return get_current_step_from_state(state) == "COMPLETED"

    def _check_substep_timeout(self, state: dict):
        started_at = state.get("substep_started_at")
        if not started_at:
            return
        try:
            start_dt = datetime.fromisoformat(started_at)
            elapsed = (datetime.now(timezone.utc) - start_dt).total_seconds()
        except (ValueError, TypeError):
            return
        if elapsed > self.SUBSTEP_TIMEOUT_SECONDS:
            step = state.get("current_step", "unknown")
            substep = state.get("current_substep", "unknown")
            from langgraph.types import interrupt
            interrupt(
                f"TIMEOUT: Substep {substep} in {step} has been running for "
                f"{elapsed / 60:.1f} minutes (limit: {self.SUBSTEP_TIMEOUT_SECONDS // 60} min). "
                f"The run has been halted."
            )

    @staticmethod
    def _get_ai_message(result):
        if isinstance(result, AIMessage):
            return result
        if hasattr(result, "result") and result.result:
            return result.result[0]
        return None

    def _has_tool_calls(self, result) -> bool:
        ai_msg = self._get_ai_message(result)
        return bool(ai_msg and getattr(ai_msg, "tool_calls", None))

    def _nudge_message(self, state: dict) -> HumanMessage:
        step = state.get("current_step", "unknown")
        substep = state.get("current_substep", "unknown")
        return HumanMessage(
            content=(
                f"You are at {step} substep {substep}. The workflow is NOT complete. "
                "You MUST call the designated tool for this substep. Call the tool now."
            ),
            additional_kwargs={"lc_source": "workflow_guard"},
        )

    def wrap_model_call(self, request, handler):
        self._check_substep_timeout(request.state)
        result = handler(request)
        if self._has_tool_calls(result) or self._is_workflow_done(request.state):
            return result

        for attempt in range(1, self.MAX_RETRIES + 1):
            self._check_substep_timeout(request.state)
            logger.warning(
                f"[WorkflowGuard] Text-only response at "
                f"{request.state.get('current_step')}, retry {attempt}/{self.MAX_RETRIES}"
            )
            ai_msg = self._get_ai_message(result)
            nudge = self._nudge_message(request.state)
            retry_messages = list(request.messages)
            if ai_msg is not None:
                retry_messages.append(ai_msg)
            retry_messages.append(nudge)
            request = request.override(messages=retry_messages)
            result = handler(request)
            if self._has_tool_calls(result) or self._is_workflow_done(request.state):
                return result

        return result

    async def awrap_model_call(self, request, handler):
        self._check_substep_timeout(request.state)
        result = await handler(request)
        if self._has_tool_calls(result) or self._is_workflow_done(request.state):
            return result

        for attempt in range(1, self.MAX_RETRIES + 1):
            self._check_substep_timeout(request.state)
            ai_msg = self._get_ai_message(result)
            nudge = self._nudge_message(request.state)
            retry_messages = list(request.messages)
            if ai_msg is not None:
                retry_messages.append(ai_msg)
            retry_messages.append(nudge)
            request = request.override(messages=retry_messages)
            result = await handler(request)
            if self._has_tool_calls(result) or self._is_workflow_done(request.state):
                return result

        return result


# ═══════════════════════════════════════════════════════════════════════
# Agent Creation
# ═══════════════════════════════════════════════════════════════════════

def create_agent():
    global _ALL_TOOLS_REF

    from tools import get_all_tools
    all_tools = get_all_tools()
    _ALL_TOOLS_REF = all_tools

    plans_dir = os.path.join(PROJECT_ROOT, "plans")
    with open(os.path.join(plans_dir, "system_prompt.template.md"), "r") as f:
        system_prompt = f.read()

    overview = generate_workflow_overview()
    system_prompt = system_prompt.replace("{{WORKFLOW_OVERVIEW}}", overview)

    middleware_stack = [RMOrchMiddleware()]
    if HAS_COPILOTKIT:
        middleware_stack.append(CopilotKitMiddleware())
        logger.info("[INIT] CopilotKit middleware enabled")
    middleware_stack.append(SystemMessageNormalizerMiddleware())
    middleware_stack.append(WorkflowGuardMiddleware())

    agent = create_deep_agent(
        model="claude-sonnet-4-5",
        tools=all_tools,
        system_prompt=system_prompt,
        middleware=tuple(middleware_stack),
        tool_resolver=resolve_tools_for_step,
        plan_resolver=resolve_plan_for_step,
        name="rmorch_agent",
    )

    return agent


graph = create_agent()
graph.config["recursion_limit"] = _MIN_RECURSION_LIMIT
