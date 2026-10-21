"""STEP_01: Pipeline Management tools.

1.1 review_duties        — verify pipeline duties, raise a monitoring checklist
1.2 record_file_touch    — record a file touch (conversation-log note)
1.3 submit_dft           — cancel loan / submit for DFT (guarded, destructive)
1.4 validate_ecd         — validate the Estimated Closing Date vs SLA, update if requested
"""

import json
import logging
from datetime import date, datetime, timezone
from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from ._helpers import _los, _profile, _parse_date, _days_between, _doc_present, doc_field

logger = logging.getLogger(__name__)

ESTIMATED_CLOSING_DATE_FIELD_ID = "763"
# ECD SLA windows (calendar days from today) — best-effort defaults.
REFI_ECD_TARGET_DAYS = 30


@tool
def review_duties(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Review the RM pipeline duties for this loan and raise a monitoring checklist.

    This is a verification/advisory substep: it inspects the loan's current
    milestone, ECD, and lock, and raises info/warning flags for items the RM must
    monitor (new/updated approvals, ECDs, SLAs, DFT candidates). It does not
    write to Encompass.
    """
    flags = []
    checks = []

    milestone = _los(state, "current_milestone") or "Unknown"
    ecd = _parse_date(_los(state, "estimated_closing_date"))
    lock_exp = _parse_date(_los(state, "lock_expiration_date"))
    today = date.today()

    checks.append({"check": "current_milestone", "value": milestone})

    if not ecd:
        flags.append({
            "substep": "1.1",
            "title": "ECD missing",
            "severity": "warning",
            "details": "No Estimated Closing Date is set. RM must set/verify the ECD (see substep 1.4).",
            "suggestion": "Set the ECD on the Borrower Summary and confirm with the client.",
        })
    else:
        days = _days_between(today, ecd)
        checks.append({"check": "ecd", "value": str(ecd), "days_out": days})
        if days is not None and days < 0:
            flags.append({
                "substep": "1.1",
                "title": "ECD is in the past",
                "severity": "warning",
                "details": f"ECD {ecd} is {abs(days)} day(s) in the past — file may be stagnant.",
                "suggestion": "Contact the client and move the ECD, or submit for DFT if dead.",
            })
        elif days is not None and days <= 15:
            flags.append({
                "substep": "1.1",
                "title": "ECD within 15 days — on the radar",
                "severity": "info",
                "details": f"ECD {ecd} is {days} day(s) out. Confirm final conditions deadlines with the client.",
                "suggestion": "Use the ECD communication template to remind the client of deadlines.",
            })

    if lock_exp:
        lock_days = _days_between(today, lock_exp)
        checks.append({"check": "lock_expiration", "value": str(lock_exp), "days_out": lock_days})
        if lock_days is not None and lock_days <= 7:
            flags.append({
                "substep": "1.1",
                "title": "Lock expiring soon",
                "severity": "warning",
                "details": f"Lock expires {lock_exp} ({lock_days} day(s)). Notify Broker/AE and verify it expires after disbursement.",
                "suggestion": "Coordinate a lock extension if needed.",
            })

    # Standing monitoring duties (always surfaced as info)
    flags.append({
        "substep": "1.1",
        "title": "Pipeline duties reminder",
        "severity": "info",
        "details": (
            "Monitor: new/updated UW decisions, RM condition queue, ECDs for the upcoming week, "
            "ICD & COCs, Reg B, SLAs, and stagnant loans for DFT. Touch each file at least once every 3 days."
        ),
        "suggestion": "Work the RM pipeline views in Encompass and update the Roadmap/Conversation Log.",
    })

    result = {
        "success": True,
        "current_milestone": milestone,
        "checks": checks,
        "flags_raised": len(flags),
        "message": f"Pipeline duties reviewed: {len(flags)} item(s) flagged for attention.",
    }
    return Command(update={
        "flags": flags,
        "messages": [ToolMessage(content=json.dumps(result), tool_call_id=tool_call_id)],
    })


@tool
def record_file_touch(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Record a file touch in the Roadmap & Conversation Log.

    RMs must touch each file at least once every 3 days. This appends a
    conversation-log note documenting the touch (dry-run gated).
    """
    from shared.conditions_io import (
        add_conversation_log_note,
        flush_action_ledger,
        flush_action_flags,
    )

    loan_id = state.get("loan_id")
    if not loan_id:
        return Command(update={"messages": [ToolMessage(
            content=json.dumps({"error": "No loan_id in state. Run find_loan first."}),
            tool_call_id=tool_call_id,
        )]})

    milestone = _los(state, "current_milestone") or "Unknown"
    ecd = _los(state, "estimated_closing_date") or "not set"
    stamp = datetime.now(timezone.utc).strftime("%m/%d/%Y")
    note = (
        f"RM file touch {stamp}: reviewed pipeline status. "
        f"Current milestone: {milestone}. ECD: {ecd}. "
        f"File progressing toward closing."
    )

    flags = []
    ledger_entries = []
    try:
        add_conversation_log_note(
            loan_id, note, state=state, substep="1.2", substep_name="File Touches",
        )
        ledger_entries = flush_action_ledger()
        flags.extend(flush_action_flags())
    except Exception as e:
        logger.error(f"[FILE_TOUCH] Error: {e}")
        flags.append({
            "substep": "1.2",
            "title": "File touch note failed",
            "severity": "warning",
            "details": f"Could not add conversation-log note: {str(e)[:200]}",
            "suggestion": "Add the touch note manually in the Conversation Log.",
        })

    result = {
        "success": True,
        "note": note,
        "actions_recorded": len(ledger_entries),
        "message": "Recorded file touch in conversation log.",
    }
    return Command(update={
        "flags": flags,
        "field_writes_ledger": ledger_entries,
        "messages": [ToolMessage(content=json.dumps(result), tool_call_id=tool_call_id)],
    })


@tool
def submit_dft(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Submit the loan for cancellation (Deal Fell Through), if allowed.

    DESTRUCTIVE. Only submits when run options explicitly allow it
    (`options.allow_dft = true`) AND a reason is provided (`options.dft_reason`).
    Otherwise it raises an advisory flag and takes no action.
    """
    from encompass_client import FieldIds

    options = state.get("options") or {}
    allow_dft = bool(options.get("allow_dft"))
    reason = str(options.get("dft_reason") or "").strip()

    loan_id = state.get("loan_id")

    if not allow_dft or not reason:
        flags = [{
            "substep": "1.3",
            "title": "DFT not submitted (guarded)",
            "severity": "info",
            "details": (
                "Loan cancellation is destructive and was not submitted. "
                f"allow_dft={allow_dft}, reason={'set' if reason else 'missing'}."
            ),
            "suggestion": (
                "If this loan should be cancelled, re-run with options.allow_dft=true and "
                "options.dft_reason set, or submit the DFT form manually in Encompass."
            ),
        }]
        result = {
            "success": True, "submitted": False,
            "message": "DFT guarded — no action taken (advisory flag raised).",
        }
        return Command(update={
            "flags": flags,
            "messages": [ToolMessage(content=json.dumps(result), tool_call_id=tool_call_id)],
        })

    from shared.encompass_io import (
        write_fields, flush_field_writes_ledger, flush_field_writes_flags,
    )

    flags = []
    ledger_entries = []
    try:
        write_fields(
            loan_id=loan_id,
            updates={FieldIds.DFT_REASON: reason},
            state=state,
            node_id="submit_dft",
            substep="1.3",
            substep_name="Cancelling Loans / Submitting for DFT",
            title="DFT Reason Set",
            details=f"Set DFT reason to '{reason}' and submitted for review.",
        )
        ledger_entries = flush_field_writes_ledger()
        flags.extend(flush_field_writes_flags())
    except Exception as e:
        logger.error(f"[SUBMIT_DFT] Error: {e}")
        flags.append({
            "substep": "1.3",
            "title": "DFT submission failed",
            "severity": "critical",
            "details": f"Could not submit DFT: {str(e)[:200]}",
            "suggestion": "Submit the DFT form manually in Encompass.",
        })

    result = {
        "success": True, "submitted": True, "reason": reason,
        "message": f"Submitted loan for DFT with reason: {reason}",
    }
    return Command(update={
        "flags": flags,
        "field_writes_ledger": ledger_entries,
        "messages": [ToolMessage(content=json.dumps(result), tool_call_id=tool_call_id)],
    })


@tool
def validate_ecd(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Validate the Estimated Closing Date against NQMF SLAs, and update if requested.

    - Purchase: ECD should reflect the purchase-contract closing date.
    - Refinance: ECD set ~30 days out unless closing sooner.

    If `options.target_ecd` (MM/DD/YYYY) is provided, this writes that ECD to
    Encompass (dry-run gated). Otherwise it validates the current ECD and flags.
    """
    options = state.get("options") or {}
    target_ecd_raw = str(options.get("target_ecd") or "").strip()

    loan_id = state.get("loan_id")
    today = date.today()
    is_refi = bool(_profile(state, "is_refinance"))
    current_ecd = _parse_date(_los(state, "estimated_closing_date"))

    flags = []
    checks = []
    ledger_entries = []

    checks.append({
        "check": "current_ecd",
        "value": str(current_ecd) if current_ecd else None,
        "is_refinance": is_refi,
    })

    # Purchase: compare ECD to the Purchase Agreement contract closing date.
    if not is_refi and _doc_present(state, "Purchase Agreement"):
        contract_close = _parse_date(doc_field(state, "purchase_agreement", "closing_date", "close_of_escrow", "settlement_date", "closing"))
        if contract_close:
            checks.append({"check": "purchase_contract_closing_date", "value": str(contract_close)})
            if current_ecd and current_ecd != contract_close:
                flags.append({
                    "substep": "1.4",
                    "title": "ECD does not match purchase contract",
                    "severity": "warning",
                    "details": f"ECD {current_ecd} differs from the Purchase Agreement closing date {contract_close}.",
                    "suggestion": "Set the ECD to the contract closing date (or confirm an agreed extension).",
                })
            elif not current_ecd:
                flags.append({
                    "substep": "1.4",
                    "title": "Use purchase contract closing date for ECD",
                    "severity": "info",
                    "details": f"Purchase Agreement closing date is {contract_close}; set the ECD accordingly.",
                    "suggestion": f"Provide options.target_ecd={contract_close.strftime('%m/%d/%Y')} to set it.",
                })

    if not current_ecd and not target_ecd_raw:
        flags.append({
            "substep": "1.4",
            "title": "ECD missing",
            "severity": "warning",
            "details": "No ECD is set and no target ECD was provided.",
            "suggestion": (
                "Refinance: set ~30 days out. Purchase: use the contract closing date. "
                "Provide options.target_ecd to have the agent set it."
            ),
        })
    elif current_ecd and not target_ecd_raw:
        days = _days_between(today, current_ecd)
        if days is not None and days < 0:
            flags.append({
                "substep": "1.4",
                "title": "ECD is in the past",
                "severity": "warning",
                "details": f"Current ECD {current_ecd} is {abs(days)} day(s) in the past.",
                "suggestion": "Contact the client to reset the ECD (or update stagnant files to 12/31).",
            })
        elif is_refi and days is not None and days > REFI_ECD_TARGET_DAYS + 5:
            flags.append({
                "substep": "1.4",
                "title": "Refinance ECD far out",
                "severity": "info",
                "details": f"Refi ECD {current_ecd} is {days} days out (target ~{REFI_ECD_TARGET_DAYS}).",
                "suggestion": "Confirm the timeline with the client; adjust if closing sooner.",
            })
        else:
            flags.append({
                "substep": "1.4",
                "title": "ECD looks reasonable",
                "severity": "info",
                "details": f"Current ECD {current_ecd} ({days} days out). Confirm feasibility with the client.",
                "suggestion": "No change needed unless the client indicates otherwise.",
            })

    # Optional update when a target ECD is supplied
    if target_ecd_raw:
        target_ecd = _parse_date(target_ecd_raw)
        if not target_ecd:
            flags.append({
                "substep": "1.4",
                "title": "Invalid target ECD",
                "severity": "warning",
                "details": f"Could not parse options.target_ecd='{target_ecd_raw}'.",
                "suggestion": "Provide the target ECD as MM/DD/YYYY.",
            })
        elif current_ecd == target_ecd:
            flags.append({
                "substep": "1.4",
                "title": "ECD already set to target",
                "severity": "info",
                "details": f"ECD is already {target_ecd}; no update needed.",
                "suggestion": "",
            })
        else:
            from shared.encompass_io import (
                write_fields, flush_field_writes_ledger, flush_field_writes_flags,
            )
            try:
                write_fields(
                    loan_id=loan_id,
                    updates={ESTIMATED_CLOSING_DATE_FIELD_ID: target_ecd.strftime("%m/%d/%Y")},
                    state=state,
                    node_id="validate_ecd",
                    substep="1.4",
                    substep_name="ECD Validation & Updates",
                    title="ECD Updated",
                    details=f"Updated ECD from '{current_ecd}' to '{target_ecd}'.",
                )
                ledger_entries = flush_field_writes_ledger()
                flags.extend(flush_field_writes_flags())
            except Exception as e:
                logger.error(f"[VALIDATE_ECD] Error: {e}")
                flags.append({
                    "substep": "1.4",
                    "title": "ECD update failed",
                    "severity": "critical",
                    "details": f"Could not write ECD: {str(e)[:200]}",
                    "suggestion": "Set the ECD manually on the Borrower Summary.",
                })

    result = {
        "success": True,
        "checks": checks,
        "ecd_updated": bool(ledger_entries),
        "message": f"ECD validation complete: {len(flags)} flag(s).",
    }
    return Command(update={
        "flags": flags,
        "field_writes_ledger": ledger_entries,
        "messages": [ToolMessage(content=json.dumps(result), tool_call_id=tool_call_id)],
    })
