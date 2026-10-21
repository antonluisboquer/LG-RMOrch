"""STEP_03: Loan Requests (Encompass-contained substeps only).

3.1 submit_exception     — Non-QM v2 Exception Tracking + 2nd Level Review submit (guarded)
3.2 submit_rush_request  — Rush Request Form data entry (info only, NO submit-for-review)
3.3 submit_condo_review  — Condo Review form + submit, gated on eFolder condo docs (guarded)

Only the in-Encompass RM actions are modeled. The external/inbound parts —
discussing with the UW, the Exception/Condo Desk decisions and uploads, and the
rush-approval email to pipeline managers — are handled outside this workflow.

NOTE: the custom-form field IDs below are PLACEHOLDERS and must be confirmed on
the Encompass instance before dry_run is turned off (see
docs/ENCOMPASS_FIELD_CONFIRMATION.md).
"""

import logging
from datetime import date
from typing import Annotated

from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from ._helpers import (
    _los,
    _profile,
    _parse_date,
    _days_between,
    make_command,
    load_conditions,
    cond_title,
    _doc_present,
)

logger = logging.getLogger(__name__)

# ── PLACEHOLDER custom-form field IDs (confirm on instance) ──
# Non-QM v2 — Exception Tracking section
EXCEPTION_TYPE_FIELD = "CX.NONQM.EXCEPTION.TYPE"          # placeholder
EXCEPTION_SUMMARY_FIELD = "CX.NONQM.EXCEPTION.SUMMARY"    # placeholder
# 2nd Level Review form
SECOND_REVIEW_EXCEPTION_FLAG = "CX.2NDREVIEW.EXCEPTION"   # placeholder (Type of Review = Exception)
SECOND_REVIEW_FINDINGS_FIELD = "CX.2NDREVIEW.FINDINGS"    # placeholder (Underwriter's Findings)
SECOND_REVIEW_SUBMIT_FIELD = "CX.2NDREVIEW.SUBMIT"        # placeholder (Submit for Review & Notify Users)
# Rush Request Form
RUSH_REASON_FIELD = "CX.RUSH.REASON"                      # placeholder
RUSH_TITLE_AVAIL_FIELD = "CX.RUSH.TITLE.AVAIL"            # placeholder
# Condo Review form
CONDO_REVIEW_NOTES_FIELD = "CX.CONDO.REVIEW.NOTES"        # placeholder
CONDO_REVIEW_SUBMIT_FIELD = "CX.CONDO.REVIEW.SUBMIT"      # placeholder

# Rush policy timing (calendar days after CTC that docs are needed)
RUSH_MAX_DAYS_STANDARD = 2
RUSH_MAX_DAYS_TX = 3


@tool
def submit_exception(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Submit an exception request via Non-QM v2 + 2nd Level Review (guarded).

    Verifies an exception condition is on the file, then (when allowed) fills the
    Non-QM v2 Exception Tracking fields and the 2nd Level Review form (Type of
    Review = Exception, Underwriter's Findings = date/initials/summary) and submits
    for review to notify the exception desk. All writes are dry-run gated.

    Run options:
      - options.submit_exception = true      → perform the writes/submit
      - options.exception_type   = "5% LTV"  → what is being requested
      - options.exception_summary = "9-9-24 / lk / LTV exception requested"
      - options.compensating_factors = [ ... ]  (need >= 2)
    """
    options = state.get("options") or {}
    loan_id = state.get("loan_id")
    conditions, cond_err = load_conditions(state)

    flags = []

    # Prereq: an exception condition should exist on the file.
    exc_conds = [c for c in conditions if "exception" in cond_title(c).lower()]
    if cond_err:
        flags.append({"substep": "3.1", "title": "Could not read conditions", "severity": "warning",
                      "details": f"Exception-condition prerequisite unverified ({cond_err}).",
                      "suggestion": "Confirm an exception condition is on the file before submitting."})
    elif exc_conds:
        flags.append({"substep": "3.1", "title": f"Exception condition on file ({len(exc_conds)})", "severity": "info",
                      "details": "; ".join(cond_title(c) for c in exc_conds[:5]),
                      "suggestion": "Proceed with the exception request for this condition."})
    else:
        flags.append({"substep": "3.1", "title": "No exception condition found", "severity": "warning",
                      "details": f"No condition mentioning 'exception' among {len(conditions)}. Exceptions are added by UW after initial review.",
                      "suggestion": "Confirm the exception condition exists before submitting."})

    # Compensating factors: >= 2 required (judgment).
    factors = options.get("compensating_factors") or []
    if isinstance(factors, str):
        factors = [f.strip() for f in factors.split(";") if f.strip()]
    if len(factors) < 2:
        flags.append({"substep": "3.1", "title": "Provide 2+ compensating factors", "severity": "warning",
                      "details": f"{len(factors)} compensating factor(s) provided; a minimum of 2 relevant factors is required, and more improves approval odds.",
                      "suggestion": "Add compensating factors that tell the borrower's story for the specific request."})

    exc_type = str(options.get("exception_type") or "").strip()
    summary = str(options.get("exception_summary") or "").strip()
    allow = bool(options.get("submit_exception"))

    ledger = []
    if not (allow and exc_type and summary):
        flags.append({"substep": "3.1", "title": "Exception not submitted (guarded)", "severity": "info",
                      "details": (
                          f"allow={allow}, exception_type={'set' if exc_type else 'missing'}, "
                          f"summary={'set' if summary else 'missing'}. No writes performed."
                      ),
                      "suggestion": "Re-run with options.submit_exception=true, options.exception_type, and options.exception_summary."})
        return make_command(tool_call_id, "Exception request guarded — advisory only.", flags=flags,
                            extra={"exception_conditions": len(exc_conds)})

    from shared.encompass_io import (
        write_fields, flush_field_writes_ledger, flush_field_writes_flags,
    )
    try:
        write_fields(
            loan_id=loan_id,
            updates={
                EXCEPTION_TYPE_FIELD: exc_type,
                EXCEPTION_SUMMARY_FIELD: summary,
                SECOND_REVIEW_EXCEPTION_FLAG: "Y",
                SECOND_REVIEW_FINDINGS_FIELD: summary,
                SECOND_REVIEW_SUBMIT_FIELD: "Y",
            },
            state=state,
            node_id="submit_exception",
            substep="3.1",
            substep_name="Exceptions",
            title="Exception Request Submitted",
            details=f"Non-QM v2 exception ({exc_type}) + 2nd Level Review submitted: {summary}",
        )
        ledger = flush_field_writes_ledger()
        flags.extend(flush_field_writes_flags())
    except Exception as e:
        logger.error(f"[SUBMIT_EXCEPTION] Error: {e}")
        flags.append({"substep": "3.1", "title": "Exception submission failed", "severity": "critical",
                      "details": f"Could not write exception/2nd-level-review fields: {str(e)[:200]}",
                      "suggestion": "Complete the Non-QM v2 + 2nd Level Review forms manually."})

    # LLPA reminder based on lock status.
    locked = _parse_date(_los(state, "lock_expiration_date")) is not None
    if not locked:
        flags.append({"substep": "3.1", "title": "Unlocked — ensure exception LLPA at lock", "severity": "warning",
                      "details": "Loan is not locked. The RM must ensure the exception LLPA is applied at time of lock (or request it be added).",
                      "suggestion": "Track the exception LLPA and confirm it is applied when the loan locks."})
    else:
        flags.append({"substep": "3.1", "title": "Locked — LLPA handled by Exception Desk", "severity": "info",
                      "details": "Loan is locked; the Exception Desk requests the exception LLPA from the lock desk.",
                      "suggestion": "Confirm the LLPA is reflected once the desk responds."})

    return make_command(tool_call_id, "Exception request submitted (2nd Level Review).", flags=flags,
                        ledger=ledger, extra={"exception_type": exc_type})


@tool
def submit_rush_request(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Enter Closing Rush Request info in Encompass (info only — do NOT submit).

    Per the job aid, rush approvals are emailed to pipeline managers (handled
    outside this workflow). In Encompass the RM only *populates the Rush Request
    Form* — "add in information only", do not click Submit for Review. This tool
    writes the rush reason and Title/Attorney availability (dry-run gated) and
    checks the eligibility rules.

    Run options:
      - options.rush_reason              = "why the rush is needed"
      - options.title_atty_availability  = "Title confirmed 9/12 10am"
      - options.ctc_audit_clear          = true (required by policy)
    """
    options = state.get("options") or {}
    loan_id = state.get("loan_id")
    prop_state = (_profile(state, "state") or "").upper()

    flags = []

    # CTC audit must be clear.
    if not options.get("ctc_audit_clear"):
        flags.append({"substep": "3.2", "title": "CTC Audit must be clear", "severity": "warning",
                      "details": "A rush requires a clear CTC Audit. Confirm the CTC audit is clear before requesting.",
                      "suggestion": "Set options.ctc_audit_clear=true once the CTC audit is clean."})

    # Timing rule (advisory — needs the actual 'docs needed by' date to enforce).
    max_days = RUSH_MAX_DAYS_TX if prop_state == "TX" else RUSH_MAX_DAYS_STANDARD
    flags.append({"substep": "3.2", "title": "Rush eligibility (timing)", "severity": "info",
                  "details": (
                      f"Only use a rush if docs are needed sooner than {max_days} days after CTC "
                      f"({'Texas' if prop_state=='TX' else 'standard'}). Must adhere to the NQM Rush Policy."
                  ),
                  "suggestion": "Confirm the docs-needed date falls inside the rush window."})

    # External step reminder (excluded action).
    flags.append({"substep": "3.2", "title": "Rush approval is emailed (external)", "severity": "info",
                  "details": "The rush request itself must be emailed to the pipeline managers for approval — this is done outside the agent.",
                  "suggestion": "Email the pipeline managers per the Rush Policy after populating the form."})

    reason = str(options.get("rush_reason") or "").strip()
    title_avail = str(options.get("title_atty_availability") or "").strip()

    ledger = []
    if not reason:
        flags.append({"substep": "3.2", "title": "Rush form not populated (guarded)", "severity": "info",
                      "details": "No options.rush_reason provided; nothing written to the Rush Request Form.",
                      "suggestion": "Provide options.rush_reason (and options.title_atty_availability) to populate the form."})
        return make_command(tool_call_id, "Rush request guarded — advisory only.", flags=flags)

    from shared.encompass_io import (
        write_fields, flush_field_writes_ledger, flush_field_writes_flags,
    )
    try:
        updates = {RUSH_REASON_FIELD: reason}
        if title_avail:
            updates[RUSH_TITLE_AVAIL_FIELD] = title_avail
        write_fields(
            loan_id=loan_id,
            updates=updates,
            state=state,
            node_id="submit_rush_request",
            substep="3.2",
            substep_name="Closing Rush Requests",
            title="Rush Request Form Populated (info only)",
            details=f"Rush reason recorded; NOT submitted for review (per policy). {reason}",
        )
        ledger = flush_field_writes_ledger()
        flags.extend(flush_field_writes_flags())
    except Exception as e:
        logger.error(f"[SUBMIT_RUSH] Error: {e}")
        flags.append({"substep": "3.2", "title": "Rush form write failed", "severity": "warning",
                      "details": f"Could not write Rush Request Form fields: {str(e)[:200]}",
                      "suggestion": "Populate the Rush Request Form manually (info only)."})

    return make_command(tool_call_id, "Rush Request Form populated (info only, not submitted).",
                        flags=flags, ledger=ledger)


@tool
def submit_condo_review(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Initiate a Condo Review in Encompass (guarded), gated on required docs.

    Condo project approval runs through the NQM Condo Desk and should be initiated
    once the Master Insurance Policy and HOA Questionnaire are received. In
    Encompass the RM enters notes on the Condo Review form and clicks Submit to
    initiate; supporting docs live in the eFolder Condo Conditions. Dry-run gated.

    Run options:
      - options.submit_condo_review = true
      - options.condo_notes         = "notes for the reviewer"
    """
    options = state.get("options") or {}
    loan_id = state.get("loan_id")
    conditions, cond_err = load_conditions(state)

    flags = []

    # Required supporting docs: Master Insurance Policy + HOA Questionnaire.
    master_ins = _doc_present(state, "Evidence of Insurance")  # best-available proxy for master policy
    condo_conds = [c for c in conditions if "condo" in cond_title(c).lower() or "hoa" in cond_title(c).lower()]
    flags.append({"substep": "3.3", "title": "Condo review prerequisites", "severity": "warning",
                  "details": (
                      "Initiate only once the Master Insurance Policy AND HOA Questionnaire are received; "
                      "supporting docs must be uploaded to the eFolder Condo Conditions. "
                      f"(Insurance doc present: {master_ins}; condo/HOA conditions found: {len(condo_conds)})"
                  ),
                  "suggestion": "Confirm Master Insurance Policy + HOA Questionnaire are in the eFolder Condo Conditions."})
    if cond_err:
        flags.append({"substep": "3.3", "title": "Could not read conditions", "severity": "warning",
                      "details": f"Condo-condition prerequisite unverified ({cond_err}).",
                      "suggestion": "Verify condo conditions manually."})

    notes = str(options.get("condo_notes") or "").strip()
    allow = bool(options.get("submit_condo_review"))

    ledger = []
    if not (allow and notes):
        flags.append({"substep": "3.3", "title": "Condo review not submitted (guarded)", "severity": "info",
                      "details": f"allow={allow}, condo_notes={'set' if notes else 'missing'}. No writes performed.",
                      "suggestion": "Re-run with options.submit_condo_review=true and options.condo_notes."})
        return make_command(tool_call_id, "Condo review guarded — advisory only.", flags=flags,
                            extra={"condo_conditions": len(condo_conds)})

    from shared.encompass_io import (
        write_fields, flush_field_writes_ledger, flush_field_writes_flags,
    )
    try:
        write_fields(
            loan_id=loan_id,
            updates={CONDO_REVIEW_NOTES_FIELD: notes, CONDO_REVIEW_SUBMIT_FIELD: "Y"},
            state=state,
            node_id="submit_condo_review",
            substep="3.3",
            substep_name="Condo Reviews",
            title="Condo Review Submitted",
            details=f"Condo Review notes entered and submitted to initiate review: {notes}",
        )
        ledger = flush_field_writes_ledger()
        flags.extend(flush_field_writes_flags())
    except Exception as e:
        logger.error(f"[SUBMIT_CONDO] Error: {e}")
        flags.append({"substep": "3.3", "title": "Condo review submission failed", "severity": "critical",
                      "details": f"Could not write Condo Review fields: {str(e)[:200]}",
                      "suggestion": "Complete and submit the Condo Review form manually."})

    return make_command(tool_call_id, "Condo review initiated.", flags=flags, ledger=ledger)
