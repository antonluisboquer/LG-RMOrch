"""STEP_11: Locked Loans.

11.1 review_lock          — lock expiration vs disbursement + variance review
11.2 update_loan_number   — NDC lender loan number update (field 305)
"""

import logging
from datetime import date
from typing import Annotated

from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from ._helpers import _los, _profile, _parse_date, _days_between, make_command

logger = logging.getLogger(__name__)

LOCK_WARNING_DAYS = 7


def _num(v):
    try:
        return float(str(v).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None


def _dscr_band(v):
    """Return the SOP DSCR band label for a value, or None if between listed bands."""
    if v is None:
        return None
    if v > 1.24:
        return ">1.24"
    if 1.0 <= v <= 1.14:
        return "1–1.14"
    if 0.75 <= v < 1.0:
        return ".75–1"
    if v < 0.75:
        return "<.75"
    return "1.14–1.24 (unlisted)"


@tool
def review_lock(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Review lock expiration and lock variance.

    Confirm the lock expires AFTER the disbursement date (Processing Summary),
    notify Broker/AE/SA if the lock is close to expiring, and use the UW Lock
    Compare screen to ensure 'Value on lock' matches 'current values'. Update any
    outdated data (credit scores, debts). If variances exceed tolerances, contact
    the AE/SA to adjust pricing.
    """
    today = date.today()
    lock_exp = _parse_date(_los(state, "lock_expiration_date"))
    disb = _parse_date(_los(state, "disbursement_date"))
    flags = []
    checks = {
        "lock_expiration_date": str(lock_exp) if lock_exp else None,
        "disbursement_date": str(disb) if disb else None,
    }

    if not lock_exp:
        flags.append({"substep": "11.1", "title": "Lock expiration date missing", "severity": "info",
                      "details": "No lock expiration date available; confirm lock status manually and that the lock expires after the disbursement date.",
                      "suggestion": "Verify lock details via the lock icon on the Processing Summary."})
    else:
        days_left = _days_between(today, lock_exp)
        checks["days_to_lock_expiration"] = days_left
        if days_left is not None and days_left <= 0:
            flags.append({"substep": "11.1", "title": "Lock expired", "severity": "critical",
                          "details": f"Lock expiration {lock_exp} has passed. The lock must expire AFTER the disbursement date.",
                          "suggestion": "Contact AE/SA immediately regarding re-lock/extension."})
        elif days_left is not None and days_left <= LOCK_WARNING_DAYS:
            flags.append({"substep": "11.1", "title": f"Lock expiring in {days_left} day(s)", "severity": "warning",
                          "details": f"Lock expires {lock_exp}. Notify Broker/AE/SA and confirm it still expires after the disbursement date.",
                          "suggestion": "Notify Broker/AE/SA about the approaching lock expiration."})
        else:
            flags.append({"substep": "11.1", "title": "Lock within window", "severity": "info",
                          "details": f"Lock expires {lock_exp} ({days_left} days out).",
                          "suggestion": "Verify disbursement date vs lock expiration on Processing Summary."})

        # Core SOP rule: the lock MUST expire after the disbursement date.
        if disb:
            if lock_exp <= disb:
                flags.append({"substep": "11.1", "title": "Lock expires on/before disbursement", "severity": "critical",
                              "details": f"Lock expiration ({lock_exp}) is not after the disbursement date ({disb}). This violates the lock rule.",
                              "suggestion": "Contact AE/SA immediately to extend the lock past disbursement."})
            else:
                checks["lock_days_past_disbursement"] = _days_between(disb, lock_exp)
                flags.append({"substep": "11.1", "title": "Lock expires after disbursement", "severity": "info",
                              "details": f"Lock ({lock_exp}) expires {checks['lock_days_past_disbursement']} day(s) after disbursement ({disb}).",
                              "suggestion": ""})
        else:
            flags.append({"substep": "11.1", "title": "Disbursement date missing", "severity": "info",
                          "details": "No disbursement date available to confirm the lock expires after disbursement.",
                          "suggestion": "Confirm the disbursement date on the Processing Summary."})

    # ── UW Lock Compare variance (data-driven where fields are available) ──
    options = state.get("options") or {}
    dti_current = _num(_los(state, "dti_total"))
    dti_at_lock = _num(_los(state, "dti_at_lock"))
    dscr_current = _num(_los(state, "dscr_current"))
    dscr_at_lock = _num(_los(state, "dscr_at_lock"))
    is_dscr = bool(options.get("is_dscr")) or dscr_current is not None or dscr_at_lock is not None

    checks["is_dscr"] = is_dscr

    if is_dscr:
        # DSCR loans: current & lock DSCR must fall in the same band.
        cur_band = _dscr_band(dscr_current)
        lock_band = _dscr_band(dscr_at_lock)
        checks["dscr_current"] = dscr_current
        checks["dscr_at_lock"] = dscr_at_lock
        if cur_band and lock_band:
            if cur_band == lock_band:
                flags.append({"substep": "11.1", "title": "DSCR variance within tolerance", "severity": "info",
                              "details": f"DSCR at lock ({dscr_at_lock}) and current ({dscr_current}) are both in band {cur_band}.",
                              "suggestion": ""})
            else:
                flags.append({"substep": "11.1", "title": "DSCR variance OUT of tolerance", "severity": "warning",
                              "details": f"DSCR moved bands: lock {dscr_at_lock} [{lock_band}] → current {dscr_current} [{cur_band}].",
                              "suggestion": "Contact AE/SA ASAP to adjust loan pricing."})
        else:
            flags.append({"substep": "11.1", "title": "DSCR variance — verify manually", "severity": "warning",
                          "details": "Could not read DSCR at-lock/current values from UW Lock Compare.",
                          "suggestion": "Confirm DSCR stays in the same lock band (>1.24; 1–1.14; .75–1; <.75)."})
    else:
        # Non-DSCR lock variance: the rule compares final DTI against the DTI at
        # lock. Variance is acceptable if final DTI ≤ 43% OR the DTI at lock was
        # already > 43%. We can only assert an OUT-of-tolerance variance when the
        # at-lock DTI is actually known; otherwise the variance is unevaluable
        # (a high current DTI alone is NOT a violation — NonQM routinely exceeds
        # 43%), so we degrade to an advisory instead of a false warning.
        checks["dti_current"] = dti_current
        checks["dti_at_lock"] = dti_at_lock
        if dti_current is None:
            flags.append({"substep": "11.1", "title": "DTI variance — verify manually", "severity": "warning",
                          "details": "Could not read the current DTI to evaluate the variance tolerance.",
                          "suggestion": "Non-DSCR: final DTI up to 43% permitted, or if DTI at lock was above 43%."})
        elif dti_current <= 43.0 or (dti_at_lock is not None and dti_at_lock > 43.0):
            flags.append({"substep": "11.1", "title": "DTI variance within tolerance", "severity": "info",
                          "details": (f"Final DTI {dti_current}% is within tolerance"
                                      + (f" (DTI at lock was {dti_at_lock}% > 43%)." if dti_at_lock is not None and dti_at_lock > 43.0
                                         else " (≤ 43%).")),
                          "suggestion": ""})
        elif dti_at_lock is not None:
            # We know both values and the variance is not excused → real finding.
            flags.append({"substep": "11.1", "title": "DTI variance OUT of tolerance", "severity": "warning",
                          "details": f"Final DTI {dti_current}% exceeds 43% and DTI at lock was {dti_at_lock}% (not above 43%).",
                          "suggestion": "Contact AE/SA ASAP to adjust loan pricing."})
        else:
            # Current DTI > 43% but the at-lock DTI is unknown — can't evaluate the
            # variance. Advisory only, not an out-of-tolerance assertion.
            flags.append({"substep": "11.1", "title": "DTI variance — verify manually", "severity": "warning",
                          "details": f"Final DTI is {dti_current}% (> 43%), but the DTI at lock is unavailable, so the "
                                     "lock variance cannot be evaluated automatically.",
                          "suggestion": "Compare final DTI to the DTI at lock on UW Lock Compare; a high DTI alone is not a violation on NonQM."})

    flags.append({"substep": "11.1", "title": "UW Lock Compare — other values", "severity": "info",
                  "details": (
                      "Use UW Lock Compare so 'Value on lock' matches 'current values'; review the last page "
                      "of the approval vs Encompass and update outdated data (credit scores, debts, program, "
                      "amortization type). Escalate out-of-tolerance variances to the AE/SA for repricing."
                  ),
                  "suggestion": "Verify credit score / program / amortization on lock vs current; update stale data."})

    return make_command(tool_call_id, "Lock review completed.", flags=flags, extra={"checks": checks})


@tool
def update_loan_number(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Update the NDC lender loan number (URLA Lender screen, field 305).

    Applies when an NDC client requests a lender loan number update. Provide
    options.new_loan_number to write field 305. Dry-run gated; otherwise advisory.
    """
    options = state.get("options") or {}
    new_number = str(options.get("new_loan_number") or "").strip()
    channel = str(options.get("channel") or "").strip().lower()
    flags = []
    ledger = []

    if channel and channel != "ndc":
        flags.append({"substep": "11.2", "title": "Loan number update is NDC-only", "severity": "warning",
                      "details": f"This file's channel is '{channel}', but the lender loan number update (field 305) applies to NDC files only.",
                      "suggestion": "Only update field 305 for NDC clients."})

    if not new_number:
        flags.append({"substep": "11.2", "title": "No loan-number update requested", "severity": "info",
                      "details": "NDC only. Provide options.new_loan_number to update the lender loan number (URLA Lender screen, field 305).",
                      "suggestion": "Pass options.new_loan_number to apply the change."})
    else:
        from shared.encompass_io import write_fields, flush_field_writes_ledger, flush_field_writes_flags
        try:
            write_fields(
                loan_id=state.get("loan_id"), updates={"305": new_number}, state=state,
                node_id="update_loan_number", substep="11.2", substep_name="Loan Number Update (NDC only)",
                title="Lender loan number updated", details=f"Set URLA Lender field 305 to {new_number}.",
            )
            ledger = flush_field_writes_ledger()
            flags.extend(flush_field_writes_flags())
        except Exception as e:
            logger.error(f"[LOAN_NUM] update failed: {e}")
            flags.append({"substep": "11.2", "title": "Loan number update failed", "severity": "warning",
                          "details": f"Could not set field 305: {str(e)[:200]}",
                          "suggestion": "Update field 305 manually on the URLA Lender screen."})

    return make_command(tool_call_id, "Loan number update handled.", flags=flags, ledger=ledger)
