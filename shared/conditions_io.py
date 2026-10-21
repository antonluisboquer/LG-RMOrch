"""Conditions / milestone / conversation-log I/O with dry-run gate and ledger.

Mirrors ``encompass_io`` but for the non-field actions the RM workflow takes:
- updating an underwriting condition's status/description
- completing a milestone (e.g. "TPO Cond Submitted")
- adding a conversation-log note

All actions go through this module so that:
- dry_run mode can intercept the action (log it, don't execute)
- every action is recorded in a ledger for the review/summary
- an info-overwrite flag is auto-generated so each action surfaces in review
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from encompass_client import get_encompass_client

logger = logging.getLogger(__name__)

_ACTION_LEDGER: List[Dict[str, Any]] = []
_ACTION_FLAGS: List[Dict[str, Any]] = []


def flush_action_ledger() -> List[Dict[str, Any]]:
    global _ACTION_LEDGER
    entries = _ACTION_LEDGER[:]
    _ACTION_LEDGER = []
    return entries


def flush_action_flags() -> List[Dict[str, Any]]:
    global _ACTION_FLAGS
    entries = _ACTION_FLAGS[:]
    _ACTION_FLAGS = []
    return entries


def _is_dry_run() -> bool:
    try:
        from output.registry import DEV_MODE
        return DEV_MODE.dry_run
    except Exception:
        try:
            from registry import DEV_MODE
            return DEV_MODE.dry_run
        except Exception:
            return False


def _record_action(
    action: str,
    target: str,
    detail: str,
    dry_run: bool,
    substep: str = "",
    substep_name: str = "",
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    _ACTION_LEDGER.append({
        "action": action,
        "target": target,
        "detail": detail,
        "payload": payload or {},
        "substep": substep,
        "dry_run": dry_run,
        "timestamp": ts,
    })
    verb = "Would" if dry_run else "Did"
    _ACTION_FLAGS.append({
        "substep": substep,
        "substep_name": substep_name,
        "title": f"{action}: {target}",
        "severity": "info-overwrite",
        "details": f"{verb} {action.lower()} — {detail}",
        "suggestion": detail,
        "resolved": True,
        "timestamp": ts,
    })


def update_condition_status(
    loan_id: str,
    condition_id: str,
    status: str,
    description: Optional[str] = None,
    state: dict = None,
    substep: str = "",
    substep_name: str = "",
    condition_title: str = "",
) -> bool:
    """Update a single underwriting condition's status (and optionally description).

    Dry-run gated. Records an action-ledger entry + info-overwrite flag.
    """
    updates: Dict[str, Any] = {"status": status}
    if description is not None:
        updates["description"] = description

    target = condition_title or condition_id
    detail = f"set status to '{status}'" + (f"; description updated" if description is not None else "")

    if _is_dry_run():
        logger.info(f"[DRY-RUN] Would update condition {condition_id}: {updates}")
        _record_action("Update Condition", target, detail, dry_run=True,
                       substep=substep, substep_name=substep_name, payload=updates)
        return True

    client = get_encompass_client(state=state)
    client.update_condition(loan_id, condition_id, updates)
    _record_action("Update Condition", target, detail, dry_run=False,
                   substep=substep, substep_name=substep_name, payload=updates)
    return True


def complete_milestone(
    loan_id: str,
    milestone_name: str,
    state: dict = None,
    substep: str = "",
    substep_name: str = "",
) -> Dict[str, Any]:
    """Complete a milestone by name. Dry-run gated."""
    if _is_dry_run():
        logger.info(f"[DRY-RUN] Would complete milestone '{milestone_name}'")
        _record_action("Complete Milestone", milestone_name,
                       f"mark milestone '{milestone_name}' complete", dry_run=True,
                       substep=substep, substep_name=substep_name)
        return {"success": True, "dry_run": True, "milestone_name": milestone_name}

    client = get_encompass_client(state=state)
    result = client.complete_milestone(loan_id, milestone_name)
    if result.get("success"):
        _record_action("Complete Milestone", milestone_name,
                       f"marked milestone '{milestone_name}' complete", dry_run=False,
                       substep=substep, substep_name=substep_name)
    return result


def add_conversation_log_note(
    loan_id: str,
    note: str,
    state: dict = None,
    substep: str = "",
    substep_name: str = "",
) -> Dict[str, Any]:
    """Append a conversation-log note. Dry-run gated."""
    preview = note if len(note) <= 120 else note[:117] + "..."
    if _is_dry_run():
        logger.info(f"[DRY-RUN] Would add conversation-log note: {preview}")
        _record_action("Conversation Log Note", "conversation_log", preview, dry_run=True,
                       substep=substep, substep_name=substep_name, payload={"note": note})
        return {"success": True, "dry_run": True, "note": note}

    client = get_encompass_client(state=state)
    result = client.add_conversation_log_note(loan_id, note)
    _record_action("Conversation Log Note", "conversation_log", preview, dry_run=False,
                   substep=substep, substep_name=substep_name, payload={"note": note})
    return result
