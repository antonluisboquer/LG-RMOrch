"""STEP_04: Conditions Queue tools.

4.1 check_condition_sla              — SLA reminder for newly submitted conditions
4.2 identify_open_conditions         — list & categorize conditions by "Prior to"
4.3 review_condition_documentation   — verify fulfilled conditions have documents
4.4 update_condition_statuses        — update condition statuses (cleared/reviewed/re-requested)
4.5 check_unassigned_documents       — check the unassigned eFolder
4.6 resubmit_to_uw                   — complete the TPO Cond Submitted milestone (guarded)
4.7 mark_not_ready_for_resubmission  — uncheck "Cond's Ready for Review" (guarded)
"""

import json
import logging
from datetime import date
from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

logger = logging.getLogger(__name__)

RESUBMIT_MILESTONE = "TPO Cond Submitted"
MIN_CONDITIONS_FOR_RESUBMIT = 5


def _cond_owner(cond: dict) -> str:
    return str(cond.get("owner") or cond.get("conditionOwner") or cond.get("owningParty") or "").strip()


def _cond_docs(cond: dict) -> list:
    """Return the condition's attached supporting documents (best-effort)."""
    for k in ("supportingDocuments", "documents", "attachments", "associatedDocuments"):
        v = cond.get(k)
        if isinstance(v, list):
            return v
    return []


def _derive_status(cond: dict) -> str:
    """LC-owned conditions clear to 'Cleared'; all others to 'Reviewed'."""
    owner = _cond_owner(cond).lower()
    return "Cleared" if owner in ("lc", "loan coordinator", "loancoordinator") else "Reviewed"


def _format_rev_description(text: str, initials: str = "RM") -> str:
    """Prepend the SOP deficiency stamp `**Rev MM/DD Initials –` without ALL CAPS.

    Never edits existing UW verbiage — only prepends the RM's note. If a `**Rev`
    stamp is already present, the text is returned unchanged.
    """
    text = (text or "").strip()
    if text.lower().startswith("**rev"):
        return text
    stamp = f"**Rev {date.today().strftime('%m/%d')} {initials} \u2013 "
    body = text
    # Avoid shouting: only downcase if the note is entirely uppercase.
    if body and body.isupper():
        body = body.capitalize()
    return f"{stamp}{body}".rstrip()


def _prior_to_bucket(cond: dict) -> str:
    """Normalize a condition's 'Prior to' value to PTA/PTD/PTC/PTP/OTHER."""
    raw = str(cond.get("priorTo") or cond.get("priorToStatus") or cond.get("category") or "").lower()
    if "approval" in raw:
        return "PTA"
    if "doc" in raw:
        return "PTD"
    if "closing" in raw:
        return "PTC"
    if "purchase" in raw:
        return "PTP"
    return "OTHER"


def _cond_status(cond: dict) -> str:
    return str(cond.get("status") or cond.get("conditionStatus") or "").strip()


def _cond_title(cond: dict) -> str:
    return str(cond.get("title") or cond.get("name") or cond.get("description") or "").strip()


def _load_conditions(state: dict):
    """Return conditions from state, fetching from Encompass if not cached."""
    conditions = state.get("conditions")
    if conditions is not None:
        return conditions, None
    loan_id = state.get("loan_id")
    if not loan_id:
        return [], "No loan_id in state."
    try:
        from encompass_client import get_encompass_client
        client = get_encompass_client(state=state)
        conditions = client.get_conditions(loan_id)
        return conditions or [], None
    except Exception as e:
        logger.warning(f"[CONDITIONS] get_conditions failed: {e}")
        return [], str(e)


@tool
def check_condition_sla(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Check condition-review SLA and surface newly submitted/fulfilled conditions.

    SLA: conditions received before 2pm → review same day; after 2pm → by noon
    next business day. This inspects fulfilled conditions awaiting review.
    """
    conditions, err = _load_conditions(state)
    flags = []

    if err:
        flags.append({
            "substep": "4.1",
            "title": "Could not load conditions",
            "severity": "warning",
            "details": f"Condition list unavailable: {err[:200]}",
            "suggestion": "Verify Encompass access; review the Conditions tab manually.",
        })

    fulfilled = [c for c in conditions if _cond_status(c).lower() in ("fulfilled", "submitted", "ready for review")]

    flags.append({
        "substep": "4.1",
        "title": "Condition review SLA",
        "severity": "info",
        "details": (
            f"{len(fulfilled)} condition(s) are fulfilled/awaiting review. "
            "SLA: received before 2pm → same day; after 2pm → by noon next business day."
        ),
        "suggestion": "Review fulfilled conditions within SLA and update statuses.",
    })

    result = {
        "success": True,
        "conditions_total": len(conditions),
        "fulfilled_awaiting_review": len(fulfilled),
        "message": f"SLA check: {len(fulfilled)} fulfilled condition(s) awaiting review.",
    }
    return Command(update={
        "conditions": conditions,
        "flags": flags,
        "messages": [ToolMessage(content=json.dumps(result), tool_call_id=tool_call_id)],
    })


@tool
def identify_open_conditions(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """List and categorize open conditions by their 'Prior to' bucket.

    PTA = Prior to Approval (suspended → resubmit once received)
    PTD = Prior to Docs (approved, not CTC → resubmit once received)
    PTC/PTP = Prior to Closing/Purchase (no resubmission required)
    """
    conditions, err = _load_conditions(state)
    flags = []

    buckets = {"PTA": [], "PTD": [], "PTC": [], "PTP": [], "OTHER": []}
    open_conditions = []
    for c in conditions:
        status = _cond_status(c).lower()
        is_open = status not in ("cleared", "waived")
        if is_open:
            open_conditions.append(c)
            buckets[_prior_to_bucket(c)].append(_cond_title(c) or c.get("id"))

    if err:
        flags.append({
            "substep": "4.2",
            "title": "Could not load conditions",
            "severity": "warning",
            "details": f"Condition list unavailable: {err[:200]}",
            "suggestion": "Review the Conditions tab in the eFolder manually.",
        })

    summary_bits = [f"{k}: {len(v)}" for k, v in buckets.items() if v]
    flags.append({
        "substep": "4.2",
        "title": "Open conditions categorized",
        "severity": "info",
        "details": (
            f"{len(open_conditions)} open condition(s). "
            + ("; ".join(summary_bits) if summary_bits else "None open.")
            + " PTA/PTD require resubmission to UW once received; PTC/PTP do not."
        ),
        "suggestion": "Work PTA/PTD conditions toward resubmission; PTC/PTP are pre-closing/purchase.",
    })

    result = {
        "success": True,
        "open_conditions": len(open_conditions),
        "buckets": {k: len(v) for k, v in buckets.items()},
        "bucket_titles": buckets,
        "message": f"Identified {len(open_conditions)} open condition(s).",
    }
    return Command(update={
        "conditions": conditions,
        "flags": flags,
        "messages": [ToolMessage(content=json.dumps(result), tool_call_id=tool_call_id)],
    })


@tool
def review_condition_documentation(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Verify fulfilled conditions have documents and meet NQMF standards (advisory).

    Fulfilled conditions should have a document attached, with the most recent
    doc pinned first. This raises the fulfilled conditions for RM review against
    current guidelines.
    """
    conditions, _ = _load_conditions(state)
    flags = []

    fulfilled = [c for c in conditions if _cond_status(c).lower() in ("fulfilled", "submitted", "ready for review")]

    missing_docs = []
    if not fulfilled:
        flags.append({
            "substep": "4.3",
            "title": "No fulfilled conditions to review",
            "severity": "info",
            "details": "No conditions are currently in a fulfilled/awaiting-review state.",
            "suggestion": "",
        })
    else:
        titles = [(_cond_title(c) or str(c.get("id"))) for c in fulfilled][:20]
        # Data-driven: flag fulfilled conditions with no attached supporting document.
        missing_docs = [c for c in fulfilled if not _cond_docs(c)]
        flags.append({
            "substep": "4.3",
            "title": f"{len(fulfilled)} fulfilled condition(s) need documentation review",
            "severity": "info",
            "details": (
                "Review each against current NQMF guidelines; ensure the most recent doc is pinned first, "
                "and documents are not duplicated across conditions. Conditions: " + ", ".join(titles)
            ),
            "suggestion": "Clear (LC) or mark reviewed those that meet standards; re-request deficient ones (4.4).",
        })
        if missing_docs:
            names = [(_cond_title(c) or str(c.get("id"))) for c in missing_docs][:20]
            flags.append({
                "substep": "4.3",
                "title": f"{len(missing_docs)} fulfilled condition(s) have NO attached document",
                "severity": "warning",
                "details": "These are marked fulfilled but have no supporting document attached: " + ", ".join(names),
                "suggestion": "Attach/pin the supporting document before clearing, or re-request (4.4).",
            })

    result = {
        "success": True,
        "fulfilled_conditions": len(fulfilled),
        "fulfilled_missing_documents": len(missing_docs),
        "message": f"Documentation review: {len(fulfilled)} fulfilled condition(s).",
    }
    return Command(update={
        "flags": flags,
        "messages": [ToolMessage(content=json.dumps(result), tool_call_id=tool_call_id)],
    })


@tool
def update_condition_statuses(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Update condition statuses in Encompass (cleared / reviewed / re-requested).

    Applies updates supplied via `options.condition_updates`, a list of
    {"id": "...", "status": "Cleared|Reviewed|Requested", "description": "..."}.
    LC conditions → 'Cleared' when met; others → 'Reviewed'. Deficient → 'Requested'
    with an updated description. If no updates are supplied, this raises an
    advisory flag listing candidates. All writes are dry-run gated.
    """
    from shared.conditions_io import (
        update_condition_status, flush_action_ledger, flush_action_flags,
    )

    options = state.get("options") or {}
    updates = options.get("condition_updates") or []
    auto_status = bool(options.get("auto_status"))
    initials = str(options.get("rm_initials") or "RM").strip() or "RM"
    conditions, _ = _load_conditions(state)
    loan_id = state.get("loan_id")

    # Map id -> title/condition for nicer flags + owner-derived status
    title_by_id = {str(c.get("id")): (_cond_title(c) or str(c.get("id"))) for c in conditions}
    cond_by_id = {str(c.get("id")): c for c in conditions}

    flags = []
    ledger_entries = []
    applied = 0

    fulfilled = [c for c in conditions if _cond_status(c).lower() in ("fulfilled", "submitted", "ready for review")]

    # Auto-build updates from fulfilled conditions when requested (owner → status).
    if not updates and auto_status:
        updates = [{"id": str(c.get("id")), "status": _derive_status(c)} for c in fulfilled if c.get("id")]

    if not updates:
        preview = "; ".join(f"{(_cond_title(c) or c.get('id'))} → {_derive_status(c)}" for c in fulfilled[:10])
        flags.append({
            "substep": "4.4",
            "title": "No condition-status updates supplied",
            "severity": "info",
            "details": (
                f"{len(fulfilled)} fulfilled condition(s) could be cleared/reviewed "
                f"(LC-owned → Cleared, others → Reviewed): {preview or 'none'}. "
                "Pass options.auto_status=true to apply the derived statuses, or options.condition_updates for explicit changes."
            ),
            "suggestion": "Use options.auto_status=true or condition_updates=[{id,status,description}].",
        })
    else:
        for upd in updates:
            cid = str(upd.get("id") or "").strip()
            status = str(upd.get("status") or "").strip()
            description = upd.get("description")
            # Deficient/re-requested conditions get the SOP Rev stamp, never editing UW verbiage.
            if status.lower() == "requested" and description:
                description = _format_rev_description(description, initials)
            if not cid or not status:
                flags.append({
                    "substep": "4.4",
                    "title": "Skipped invalid condition update",
                    "severity": "warning",
                    "details": f"Update missing id/status: {upd}",
                    "suggestion": "Each update needs an 'id' and a 'status'.",
                })
                continue
            try:
                update_condition_status(
                    loan_id=loan_id,
                    condition_id=cid,
                    status=status,
                    description=description,
                    state=state,
                    substep="4.4",
                    substep_name="Update Condition Statuses",
                    condition_title=title_by_id.get(cid, cid),
                )
                applied += 1
            except Exception as e:
                logger.error(f"[UPDATE_COND] {cid} failed: {e}")
                flags.append({
                    "substep": "4.4",
                    "title": f"Condition update failed: {title_by_id.get(cid, cid)}",
                    "severity": "warning",
                    "details": f"Could not set status '{status}': {str(e)[:200]}",
                    "suggestion": "Update the condition status manually in Encompass.",
                })
        ledger_entries = flush_action_ledger()
        flags.extend(flush_action_flags())

    result = {
        "success": True,
        "updates_applied": applied,
        "message": f"Condition status update: {applied} applied.",
    }
    return Command(update={
        "flags": flags,
        "field_writes_ledger": ledger_entries,
        "messages": [ToolMessage(content=json.dumps(result), tool_call_id=tool_call_id)],
    })


@tool
def check_unassigned_documents(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Check the unassigned eFolder — nothing should remain besides the CTC Audit Checklist.

    Uses the eFolder service to list documents; flags anything unassigned that
    should be labeled and assigned to the applicable condition.
    """
    flags = []
    unassigned = []
    try:
        from shared.efolder_client import EfolderClient
        env = (state.get("env") or "test").lower()
        client = EfolderClient()
        resp = client.get_documents(state.get("loan_number"), include_fields=False)
        docs = resp.get("documents", []) if isinstance(resp, dict) else []
        for d in docs:
            title = str(d.get("DocumentTitle") or d.get("DocType") or "").strip()
            container = str(d.get("Container") or d.get("Folder") or "").strip().lower()
            if "unassigned" in container:
                unassigned.append(title)
    except Exception as e:
        logger.warning(f"[UNASSIGNED] eFolder check failed: {e}")
        flags.append({
            "substep": "4.5",
            "title": "Unassigned-folder check unavailable",
            "severity": "info",
            "details": f"Could not query the eFolder service: {str(e)[:200]}",
            "suggestion": "Manually confirm the unassigned folder only holds the CTC Audit Checklist.",
        })

    leftover = [t for t in unassigned if "ctc audit" not in t.lower()]
    if leftover:
        flags.append({
            "substep": "4.5",
            "title": f"{len(leftover)} unassigned document(s)",
            "severity": "warning",
            "details": "Documents in the unassigned folder: " + ", ".join(leftover[:20]),
            "suggestion": "Label and assign each to the applicable condition.",
        })
    else:
        flags.append({
            "substep": "4.5",
            "title": "Unassigned folder clean",
            "severity": "info",
            "details": "No unassigned documents remain (besides the CTC Audit Checklist, if present).",
            "suggestion": "",
        })

    result = {
        "success": True,
        "unassigned_count": len(leftover),
        "message": f"Unassigned documents: {len(leftover)} needing assignment.",
    }
    return Command(update={
        "flags": flags,
        "messages": [ToolMessage(content=json.dumps(result), tool_call_id=tool_call_id)],
    })


@tool
def resubmit_to_uw(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Re-submit the loan to UW by completing the TPO Cond Submitted milestone (guarded).

    Only completes the milestone when it is warranted — typically ≥5 UW conditions
    received, or an appraisal was received, or `options.allow_resubmit = true`.
    Otherwise raises an advisory flag and takes no action. Dry-run gated.
    """
    from shared.conditions_io import (
        complete_milestone, flush_action_ledger, flush_action_flags,
    )

    options = state.get("options") or {}
    allow_resubmit = bool(options.get("allow_resubmit"))
    conditions, _ = _load_conditions(state)
    loan_id = state.get("loan_id")

    fulfilled = [c for c in conditions if _cond_status(c).lower() in ("fulfilled", "submitted", "ready for review")]
    has_appraisal = any("appraisal" in (_cond_title(c) or "").lower() for c in fulfilled)
    warranted = allow_resubmit or has_appraisal or len(fulfilled) >= MIN_CONDITIONS_FOR_RESUBMIT

    flags = []
    ledger_entries = []

    if not warranted:
        flags.append({
            "substep": "4.6",
            "title": "Resubmission not warranted yet",
            "severity": "info",
            "details": (
                f"{len(fulfilled)} fulfilled condition(s); typically wait for ≥{MIN_CONDITIONS_FOR_RESUBMIT} "
                "(an appraisal warrants immediate resubmit). No milestone completed."
            ),
            "suggestion": "Re-run with options.allow_resubmit=true to force resubmission when appropriate.",
        })
    else:
        try:
            complete_milestone(
                loan_id=loan_id,
                milestone_name=RESUBMIT_MILESTONE,
                state=state,
                substep="4.6",
                substep_name="Re-Submit to UW",
            )
            ledger_entries = flush_action_ledger()
            flags.extend(flush_action_flags())
        except Exception as e:
            logger.error(f"[RESUBMIT] Error: {e}")
            flags.append({
                "substep": "4.6",
                "title": "Resubmission failed",
                "severity": "warning",
                "details": f"Could not complete '{RESUBMIT_MILESTONE}': {str(e)[:200]}",
                "suggestion": "Complete the TPO Cond Submitted milestone manually.",
            })

    result = {
        "success": True,
        "resubmitted": bool(ledger_entries),
        "fulfilled_conditions": len(fulfilled),
        "message": "Resubmit to UW: " + ("milestone completed." if ledger_entries else "no action (advisory)."),
    }
    return Command(update={
        "flags": flags,
        "field_writes_ledger": ledger_entries,
        "messages": [ToolMessage(content=json.dumps(result), tool_call_id=tool_call_id)],
    })


@tool
def mark_not_ready_for_resubmission(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Mark the loan not ready for UW resubmission (uncheck 'Cond's Ready for Review').

    When conditions provided do not meet resubmit standards, uncheck the TPO
    Information 'Cond's Ready for Review' box to remove it from the pending
    conditions pipeline views. Applies when `options.mark_not_ready = true`;
    otherwise advisory. Dry-run gated.
    """
    from encompass_client import FieldIds

    options = state.get("options") or {}
    mark_not_ready = bool(options.get("mark_not_ready"))
    loan_id = state.get("loan_id")

    flags = []
    ledger_entries = []

    if not mark_not_ready:
        flags.append({
            "substep": "4.7",
            "title": "Not-ready update not requested",
            "severity": "info",
            "details": (
                "If the conditions do not warrant a UW resubmit, uncheck 'Cond's Ready for Review' "
                "on the TPO Information page and communicate with the client."
            ),
            "suggestion": "Re-run with options.mark_not_ready=true to uncheck the box automatically.",
        })
    else:
        from shared.encompass_io import (
            write_fields, flush_field_writes_ledger, flush_field_writes_flags,
        )
        try:
            write_fields(
                loan_id=loan_id,
                updates={FieldIds.CONDS_READY_FOR_REVIEW: "N"},
                state=state,
                node_id="mark_not_ready_for_resubmission",
                substep="4.7",
                substep_name="Loans not ready for UW Resubmission",
                title="Cond's Ready for Review unchecked",
                details="Unchecked 'Cond's Ready for Review' on TPO Information to remove from pending views.",
            )
            ledger_entries = flush_field_writes_ledger()
            flags.extend(flush_field_writes_flags())
        except Exception as e:
            logger.error(f"[NOT_READY] Error: {e}")
            flags.append({
                "substep": "4.7",
                "title": "Not-ready update failed",
                "severity": "warning",
                "details": f"Could not uncheck 'Cond's Ready for Review': {str(e)[:200]}",
                "suggestion": "Uncheck the box manually on the TPO Information page.",
            })

    result = {
        "success": True,
        "updated": bool(ledger_entries),
        "message": "Not-ready update: " + ("applied." if ledger_entries else "advisory only."),
    }
    return Command(update={
        "flags": flags,
        "field_writes_ledger": ledger_entries,
        "messages": [ToolMessage(content=json.dumps(result), tool_call_id=tool_call_id)],
    })
