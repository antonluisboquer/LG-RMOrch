"""STEP_14: Prepare the File for Closing.

14.1 request_ctc_audit   — request the CTC audit (3rd Party Tracking)
14.2 submit_ctc_review   — complete TPO Conds Submitted + check CTC Review (guarded)
14.3 ctc_final_steps     — CTC final steps (Wholesale)
"""

import logging
from datetime import datetime, timezone
from typing import Annotated

from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from ._helpers import _profile, _los, make_command, load_conditions, cond_title, cond_status

logger = logging.getLogger(__name__)

CTC_MILESTONE = "TPO Cond Submitted"

# ── PLACEHOLDER write field IDs (confirm on instance) ──
CTC_AUDIT_REQUESTED_FIELD = "CX.CTC.AUDIT.REQUESTED"   # 3rd Party Tracking "CTC Audit Request" checkbox
CTC_AUDIT_NOTES_FIELD = "CX.CTC.AUDIT.NOTES"           # 3rd Party Tracking review comments
CTC_REVIEW_FIELD = "CX.CTC.REVIEW"                     # Loan Notes "CTC Review" checkbox


def _channel(state: dict) -> str:
    options = state.get("options") or {}
    ch = str(options.get("channel") or "").strip().lower()
    return ch if ch in ("wholesale", "ndc", "correspondent") else "unknown"


def _audit_clear(state: dict):
    """Derive whether the CTC audit is clear from the read fields.

    Returns (clear | None, defects | None, status_str). None = unknown.
    """
    defects_raw = _los(state, "ctc_audit_defects")
    status = str(_los(state, "ctc_audit_status") or "").strip()
    s = status.lower()

    defects = None
    try:
        defects = int(float(str(defects_raw).strip()))
    except (TypeError, ValueError):
        pass

    if defects is not None:
        return (defects == 0), defects, status
    if s:
        if "no issue" in s or "clear" in s:
            return True, defects, status
        if "issue" in s or "open" in s or "defect" in s:
            return False, defects, status
    return None, defects, status


@tool
def request_ctc_audit(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Request the CTC audit (offshore team) via 3rd Party Tracking.

    Only request when the loan is believed ready for a Final Clear to Close (all
    conditions reviewed, all tasks completed). Enter review notes, check the CTC
    Audit Request box to initiate. Audits complete within ~1 hour; results appear
    in the unassigned eFolder. Loans cannot be submitted to CTC without a clear
    audit. Set options.request_ctc_audit=true to check the request box + record
    initiation (dry-run gated); pass options.ctc_review_notes for the comments.
    """
    options = state.get("options") or {}
    flags = [{
        "substep": "14.1", "title": "CTC audit prerequisites", "severity": "warning",
        "details": (
            "Only request when the loan is ready for Final CTC (all conditions reviewed & tasks complete). "
            "Refer to the Wholesale/NDC QC Audit Checklist. Results appear in the unassigned eFolder within ~1 hour. "
            "If the audit finds open issues, cure them before requesting CTC, then email the audit team to update/complete."
        ),
        "suggestion": "Ensure the file is truly ready before requesting the audit.",
    }]

    # Report any existing audit state.
    clear, defects, status = _audit_clear(state)
    if status or defects is not None:
        detail = "Current CTC audit:" + (f" status='{status}'" if status else "") + (f", defects={defects}" if defects is not None else "")
        sev = "info" if clear else ("warning" if clear is False else "info")
        flags.append({"substep": "14.1", "title": "Existing CTC audit result", "severity": sev,
                      "details": detail + ".",
                      "suggestion": "Cure open issues before submitting to CTC." if clear is False else "Audit appears clear." if clear else "Confirm audit completion."})

    ledger = []
    if options.get("request_ctc_audit"):
        from shared.encompass_io import write_fields, flush_field_writes_ledger, flush_field_writes_flags
        from shared.conditions_io import add_conversation_log_note, flush_action_ledger, flush_action_flags
        loan_id = state.get("loan_id")
        updates = {CTC_AUDIT_REQUESTED_FIELD: "Y"}
        notes = str(options.get("ctc_review_notes") or "").strip()
        if notes:
            updates[CTC_AUDIT_NOTES_FIELD] = notes
        try:
            write_fields(loan_id=loan_id, updates=updates, state=state,
                         node_id="request_ctc_audit", substep="14.1", substep_name="CTC Audits",
                         title="CTC Audit requested", details="Checked the CTC Audit Request box on 3rd Party Tracking.")
            ledger = flush_field_writes_ledger()
            flags.extend(flush_field_writes_flags())
        except Exception as e:
            logger.error(f"[CTC_AUDIT] request write failed: {e}")
            flags.append({"substep": "14.1", "title": "CTC audit request write failed", "severity": "warning",
                          "details": f"Could not set the CTC Audit Request field(s): {str(e)[:200]}",
                          "suggestion": "Check the CTC Audit Request box manually on 3rd Party Tracking."})
        stamp = datetime.now(timezone.utc).strftime("%m/%d/%Y")
        add_conversation_log_note(
            loan_id, f"CTC audit requested {stamp} via 3rd Party Tracking.",
            state=state, substep="14.1", substep_name="CTC Audits",
        )
        ledger = (ledger or []) + flush_action_ledger()
        flags.extend(flush_action_flags())

    return make_command(tool_call_id, "CTC audit request handled.", flags=flags, ledger=ledger)


@tool
def submit_ctc_review(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Submit to UW for CTC review (guarded).

    Complete the TPO Conds Submitted milestone, then check the CTC Review box
    (Loan Notes) to initiate. The CTC checkbox is unavailable until a clear CTC
    audit is completed. Requires options.submit_ctc=true; the clear-audit gate is
    auto-derived from the CTC audit fields (# of defects / status) and can be
    overridden with options.ctc_audit_clear. Dry-run gated.
    """
    options = state.get("options") or {}
    submit = bool(options.get("submit_ctc"))

    derived_clear, defects, status = _audit_clear(state)
    if "ctc_audit_clear" in options:
        audit_clear = bool(options.get("ctc_audit_clear"))
        clear_source = "option"
    else:
        audit_clear = bool(derived_clear)
        clear_source = "derived"

    flags = []
    ledger = []

    if not submit:
        flags.append({"substep": "14.2", "title": "CTC review not requested", "severity": "info",
                      "details": "Set options.submit_ctc=true to complete the milestone and check the CTC Review box (requires a clear CTC audit).",
                      "suggestion": "Confirm a clear CTC audit, then submit."})
    elif not audit_clear:
        detail = "The CTC Review checkbox is unavailable until a CLEAR CTC audit is completed. No action taken."
        if clear_source == "derived":
            detail += f" (Derived from audit fields: status='{status or 'unknown'}', defects={defects if defects is not None else 'unknown'}.)"
        flags.append({"substep": "14.2", "title": "CTC review blocked — audit not clear", "severity": "critical",
                      "details": detail,
                      "suggestion": "Cure all audit issues and confirm a clear audit; or pass options.ctc_audit_clear=true if the audit is confirmed clear."})
    else:
        from shared.encompass_io import write_fields, flush_field_writes_ledger, flush_field_writes_flags
        from shared.conditions_io import complete_milestone, flush_action_ledger, flush_action_flags
        loan_id = state.get("loan_id")
        try:
            complete_milestone(loan_id=loan_id, milestone_name=CTC_MILESTONE, state=state,
                               substep="14.2", substep_name="Submit to UW for CTC Review")
            ledger = flush_action_ledger()
            flags.extend(flush_action_flags())
        except Exception as e:
            logger.error(f"[CTC] milestone failed: {e}")
            flags.append({"substep": "14.2", "title": "CTC milestone failed", "severity": "warning",
                          "details": f"Could not complete '{CTC_MILESTONE}': {str(e)[:200]}",
                          "suggestion": "Complete the TPO Conds Submitted milestone manually."})
        try:
            write_fields(loan_id=loan_id, updates={CTC_REVIEW_FIELD: "Y"}, state=state,
                         node_id="submit_ctc_review", substep="14.2", substep_name="Submit to UW for CTC Review",
                         title="CTC Review box checked", details="Checked the CTC Review box on Loan Notes to initiate CTC review.")
            ledger = (ledger or []) + flush_field_writes_ledger()
            flags.extend(flush_field_writes_flags())
        except Exception as e:
            logger.error(f"[CTC] review checkbox write failed: {e}")
            flags.append({"substep": "14.2", "title": "CTC Review box write failed", "severity": "warning",
                          "details": f"Could not check the CTC Review box: {str(e)[:200]}",
                          "suggestion": "Check the CTC Review box manually on Loan Notes."})

    return make_command(tool_call_id, "CTC review submission handled.", flags=flags, ledger=ledger)


@tool
def ctc_final_steps(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """CTC final steps (Wholesale).

    Confirm closing date/time (update Closing Information on Processor Summary),
    verify the final ECD is within the NQMF closing SLA (rush if needed), note POA/
    mail-away in Notes to the Closer, and honor the TX owner-occupied cash-out
    refi rule (borrower must receive the final CD one day prior to closing).
    Generate the Closing Validation Form and send to TPO contacts to verify details.
    """
    channel = _channel(state)
    flags = []

    if channel not in ("wholesale", "unknown"):
        flags.append({"substep": "14.3", "title": "CTC final steps are Wholesale-only", "severity": "info",
                      "details": f"This file's channel is '{channel}'; these CTC final steps are a Wholesale-only RM step.",
                      "suggestion": "Skip CTC final steps for non-Wholesale files."})
        return make_command(tool_call_id, "CTC final steps skipped (non-Wholesale).", flags=flags)

    prop_state = (_profile(state, "state") or "").upper()
    is_owner_occupied = _profile(state, "is_owner_occupied")
    is_refi = _profile(state, "is_refinance")

    flags.extend([
        {"substep": "14.3", "title": "Confirm closing date/time", "severity": "info",
         "details": "Update Closing Information on the Processor Summary. Verify the final ECD is within the NQMF closing SLA (Daily Turn Time email); if a rush is needed, follow the Closing Rush section. Escalate issues to management.",
         "suggestion": "Confirm ECD is within SLA and closing details are set."},
        {"substep": "14.3", "title": "POA / mail-away notes", "severity": "info",
         "details": "If closing with a POA or mail-away, include this in the Notes to the Closer section.",
         "suggestion": "Add POA/mail-away notes for the closer."},
        {"substep": "14.3", "title": "Closing Validation Form", "severity": "info",
         "details": "Generate the Closing Validation Form and send to TPO contacts to verify all details; update transaction data as needed based on feedback.",
         "suggestion": "Send the Closing Validation Form to TPO contacts."},
    ])

    # POA detection from conditions.
    conditions, err = load_conditions(state)
    if not err:
        poa = [c for c in conditions if any(k in cond_title(c).lower() for k in ("poa", "power of attorney"))]
        if poa:
            flags.append({"substep": "14.3", "title": "POA condition detected", "severity": "warning",
                          "details": "; ".join(f"{cond_title(c)} [{cond_status(c) or 'open'}]" for c in poa[:3]),
                          "suggestion": "Note the POA closing in Notes to the Closer and confirm the PTC POA condition is satisfied."})

    # TX owner-occupied cash-out CD rule (data-driven where possible).
    if prop_state == "TX":
        qualifier = "" if (is_owner_occupied and is_refi) else " (verify owner-occupancy & cash-out applicability)"
        flags.append({"substep": "14.3", "title": "TX owner-occupied cash-out CD rule", "severity": "warning",
                      "details": f"TX owner-occupied cash-out refinances must allow the borrower to receive the final CD one day prior to closing{qualifier}. Ensure the ECD timeline allows for this.",
                      "suggestion": "Build the extra CD day into the TX cash-out timeline."})

    return make_command(tool_call_id, "CTC final steps checklist raised.", flags=flags, extra={"state": prop_state})
