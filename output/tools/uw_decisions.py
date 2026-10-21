"""STEP_02: Initial & Updated Underwriting Decisions.

2.1 review_approval  — review the Conditional Approval and required actions
2.2 review_suspense  — suspense / recommendations for denials, TRID timelines
"""

import logging
from datetime import date
from typing import Annotated

from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from ._helpers import (
    _los,
    _parse_date,
    _days_between,
    make_command,
    load_conditions,
    cond_title,
    cond_status,
    _doc_present,
)

logger = logging.getLogger(__name__)

TRID_DECISION_DEADLINE_DAYS = 30
RESUBMIT_BY_DAY = 25


@tool
def review_approval(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Review the Conditional Approval and take required action.

    Per the job aid, when a loan is approved: review the Conditional Approval,
    ensure all conditions are understood (clarify unclear conditions with the UW
    and request verbiage updates), act on anything needing attention (appraisal
    corrections, lock adjustments), and check for a Misc-Counteroffer condition
    (restructure with Client/AE if present). An automated approval email is sent
    to the client; replies land in the RM inbox.
    """
    milestone = _los(state, "current_milestone") or "Unknown"
    conditions, cond_err = load_conditions(state)
    approval_doc = _doc_present(state, "Approval Form")

    flags = []

    # Approval document presence (from eFolder extraction, Step 0.3).
    if approval_doc:
        flags.append({
            "substep": "2.1",
            "title": "Approval / Underwriting Decision on file",
            "severity": "info",
            "details": "An Approval Form was extracted from the eFolder. Read the full decision and ensure all conditions are understood.",
            "suggestion": "Clarify any ambiguous conditions with the underwriter; request verbiage updates if needed.",
        })
    else:
        flags.append({
            "substep": "2.1",
            "title": "Approval / Underwriting Decision not found in eFolder",
            "severity": "warning",
            "details": "No Approval Form was extracted from the eFolder. The loan may not be approved yet, or the decision has not been imaged.",
            "suggestion": "Confirm the underwriting decision exists in the eFolder before acting on conditions.",
        })

    # Misc-Counteroffer detection (data-driven from live conditions).
    if cond_err:
        flags.append({
            "substep": "2.1",
            "title": "Could not read conditions",
            "severity": "warning",
            "details": f"Condition list unavailable ({cond_err}); counteroffer check is advisory only.",
            "suggestion": "Verify manually whether a Misc-Counteroffer condition is present.",
        })
    else:
        counteroffers = [
            c for c in conditions
            if "counteroffer" in cond_title(c).lower() or "counter offer" in cond_title(c).lower()
        ]
        if counteroffers:
            titles = "; ".join(f"{cond_title(c)} [{cond_status(c) or 'open'}]" for c in counteroffers[:5])
            flags.append({
                "substep": "2.1",
                "title": f"Misc-Counteroffer condition present ({len(counteroffers)})",
                "severity": "critical",
                "details": f"Counteroffer condition(s) found — the loan needs restructuring: {titles}",
                "suggestion": "Ensure Client and AE are aware and restructure per the counteroffer terms.",
            })
        else:
            flags.append({
                "substep": "2.1",
                "title": "No Misc-Counteroffer condition",
                "severity": "info",
                "details": f"No counteroffer condition found among {len(conditions)} conditions.",
                "suggestion": "Proceed with standard condition handling.",
            })

    flags.append({
        "substep": "2.1",
        "title": "Act on items needing attention",
        "severity": "info",
        "details": "Handle appraisal corrections and lock adjustments identified in the approval.",
        "suggestion": "Coordinate appraisal (Step 8) and lock changes (Step 11) as needed.",
    })

    return make_command(
        tool_call_id,
        "Conditional approval reviewed (conditions + approval doc checked).",
        flags=flags,
        extra={
            "current_milestone": milestone,
            "approval_doc_present": approval_doc,
            "condition_count": len(conditions),
        },
    )


@tool
def review_suspense(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Review suspense / denial timelines against the TRID 30-day rule.

    TRID files need a credit decision (approved or denied) within 30 days of the
    Initial Submittal Date. Reach out weekly to clear PTA conditions. The loan
    must be back in UW with all Prior-to-Approval conditions by day 25; if all
    PTAs are not received by day 25, submit the loan for cancellation (DFT).
    """
    today = date.today()
    submittal = _parse_date(_los(state, "initial_submittal_date"))
    flags = []
    checks = {"initial_submittal_date": str(submittal) if submittal else None}

    if not submittal:
        flags.append({
            "substep": "2.2",
            "title": "Initial Submittal Date missing",
            "severity": "warning",
            "details": "Cannot evaluate the TRID 30-day decision timeline without the Initial Submittal Date (TPO Information screen).",
            "suggestion": "Confirm the Initial Submittal Date to track the 30-day credit-decision deadline.",
        })
    else:
        elapsed = _days_between(submittal, today) or 0
        checks["days_since_submittal"] = elapsed
        if elapsed >= RESUBMIT_BY_DAY:
            flags.append({
                "substep": "2.2",
                "title": f"Day {elapsed} — resubmit deadline reached/passed",
                "severity": "critical",
                "details": (
                    f"{elapsed} days since Initial Submittal. Loan must be back in UW with all PTAs by day {RESUBMIT_BY_DAY}. "
                    f"If all PTAs are not received, submit for cancellation (Step 1.3 DFT)."
                ),
                "suggestion": "Confirm all PTA conditions received and resubmit, or submit DFT.",
            })
        elif elapsed >= RESUBMIT_BY_DAY - 5:
            flags.append({
                "substep": "2.2",
                "title": f"Day {elapsed} — resubmit deadline approaching",
                "severity": "warning",
                "details": f"{elapsed} days since Initial Submittal; must be back in UW with all PTAs by day {RESUBMIT_BY_DAY}.",
                "suggestion": "Push the client for outstanding PTA conditions this week.",
            })
        else:
            flags.append({
                "substep": "2.2",
                "title": f"Day {elapsed} — within decision window",
                "severity": "info",
                "details": f"{elapsed} days since Initial Submittal (TRID decision required within {TRID_DECISION_DEADLINE_DAYS}).",
                "suggestion": "Reach out weekly to clear PTA conditions.",
            })

    # ── Data-driven PTA condition tracking (Prior To = Approval) ──
    conditions, cond_err = load_conditions(state)
    if cond_err:
        flags.append({
            "substep": "2.2",
            "title": "Could not read conditions for PTA tracking",
            "severity": "warning",
            "details": f"Condition list unavailable ({cond_err}); PTA tracking is advisory only.",
            "suggestion": "Reach out weekly to clear Prior-to-Approval conditions.",
        })
    else:
        def _is_pta(c):
            return "approval" in str(c.get("priorTo") or c.get("priorToStatus") or c.get("category") or "").lower()

        def _received(c):
            return cond_status(c).lower() in ("fulfilled", "submitted", "ready for review", "cleared", "reviewed", "received", "waived")

        ptas = [c for c in conditions if _is_pta(c)]
        open_ptas = [c for c in ptas if not _received(c)]
        recv_ptas = [c for c in ptas if _received(c)]
        checks["pta_total"] = len(ptas)
        checks["pta_open"] = len(open_ptas)
        if ptas:
            if open_ptas:
                titles = "; ".join(f"{cond_title(c)} [{cond_status(c) or 'open'}]" for c in open_ptas[:8])
                sev = "critical" if (submittal and checks.get("days_since_submittal", 0) >= RESUBMIT_BY_DAY) else "warning"
                flags.append({
                    "substep": "2.2",
                    "title": f"{len(open_ptas)} of {len(ptas)} PTA condition(s) still open",
                    "severity": sev,
                    "details": f"Open Prior-to-Approval conditions: {titles}",
                    "suggestion": "Push the client for these PTAs; all must be received/back in UW by day 25 or submit a DFT.",
                })
            else:
                flags.append({
                    "substep": "2.2",
                    "title": f"All {len(ptas)} PTA condition(s) received",
                    "severity": "info",
                    "details": f"{len(recv_ptas)} PTA condition(s) received/cleared — the file can be resubmitted to UW.",
                    "suggestion": "Resubmit to UW (Step 4.6) now that all PTAs are in.",
                })
        else:
            flags.append({
                "substep": "2.2",
                "title": "No Prior-to-Approval conditions found",
                "severity": "info",
                "details": f"No PTA conditions among {len(conditions)} conditions.",
                "suggestion": "Reach out weekly to clear any outstanding conditions.",
            })

    return make_command(
        tool_call_id,
        "Suspense/denial timeline reviewed.",
        flags=flags,
        extra={"checks": checks},
    )
