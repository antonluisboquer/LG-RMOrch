"""STEP_09: Third Party Orders (Wholesale only — Encompass-contained actions).

9.1 order_credit_refresh   — initiate + review refresh; mark condition Reviewed; Doc-Exp date
9.2 order_credit_supplement— initiate + on receipt mark Ready-for-UW + resubmit milestone
9.3 order_ssa_verification — initiate; SS-89 verification reminder
9.4 order_tax_transcripts  — 3rd-party screen Requested -> Form Ready
9.5 order_vvoe             — read VVOE, Doc-Exp date, verify vs URLA (not DSCR)
9.6 validate_str_permit    — review Property Guard findings; mark condition Reviewed + resubmit
9.7 verify_pl              — ensure no open P&L conditions before requesting

Does not apply to Correspondent files. The actual third-party ordering (CIC /
MeridianLink / Property Guard) is performed by the internal team on external sites,
and broker outreach is external — those are out of scope. Only the RM's Encompass
actions are modeled. Custom-form / Doc-Expiration field IDs are PLACEHOLDERS
pending confirmation (see docs/ENCOMPASS_FIELD_CONFIRMATION.md).
"""

import logging
from typing import Annotated

from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from ._helpers import (
    _los,
    _profile,
    make_command,
    load_conditions,
    cond_title,
    cond_status,
    _doc_present,
)

logger = logging.getLogger(__name__)

# ── PLACEHOLDER field IDs (confirm on instance) ──
# Document Expiration Dates screen
DOCEXP_CREDIT_REFRESH_DATE = "CX.DOCEXP.CREDIT.REFRESH"   # placeholder
DOCEXP_VVOE_DATE = "CX.DOCEXP.VVOE"                       # placeholder
# 3rd Party Order Tracking screen
TPO_TAX_REQUESTED = "CX.TPO.TAX.REQUESTED"               # placeholder
TPO_TAX_FORM_READY = "CX.TPO.TAX.FORMREADY"             # placeholder

TPO_RESUBMIT_MILESTONE = "TPO Cond Submitted"           # unconfirmed

RESUBMIT_STATUS = "Reviewed"


def _channel(state: dict) -> str:
    options = state.get("options") or {}
    ch = str(options.get("channel") or "").strip().lower()
    return ch if ch in ("wholesale", "ndc", "correspondent") else "unknown"


def _cond_id(cond: dict) -> str:
    return str(cond.get("id") or cond.get("conditionId") or cond.get("Id") or "").strip()


def _find_conditions(conditions: list, *keywords: str) -> list:
    kws = [k.lower() for k in keywords]
    return [c for c in conditions if any(k in cond_title(c).lower() for k in kws)]


def _is_open(cond: dict) -> bool:
    return cond_status(cond).lower() not in ("cleared", "reviewed", "waived", "received", "complete")


def _correspondent_guard(state: dict, substep: str):
    """Return a flag if the file is Correspondent (section does not apply), else None."""
    if _channel(state) == "correspondent":
        return {"substep": substep, "title": "Not applicable to Correspondent", "severity": "info",
                "details": "Third Party Orders do not apply to Correspondent files.",
                "suggestion": "Skip this substep for Correspondent."}
    return None


@tool
def order_credit_refresh(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Initiate & review a Credit Refresh; mark the condition Reviewed and set the Doc-Exp date.

    Order is placed by the internal team on CIC after the RM initiates via the 3rd
    Party Order screen. The RM reviews the refresh (no new debt, balances/payments
    not increased, no new inquiries), then marks the refresh condition Reviewed (not
    Cleared) so UW addresses new items, and updates the Credit Refresh date on the
    Document Expiration screen. The invoice must be uploaded.

    Options: credit_refresh_reviewed=true, credit_refresh_date="MM/DD/YYYY".
    """
    options = state.get("options") or {}
    loan_id = state.get("loan_id")
    conditions, cond_err = load_conditions(state)

    flags = []
    corr = _correspondent_guard(state, "9.1")
    if corr:
        return make_command(tool_call_id, "Credit refresh N/A (Correspondent).", flags=[corr])

    flags.append({"substep": "9.1", "title": "Review the credit refresh", "severity": "warning",
                  "details": "Confirm: (1) no new debt opened — if yes, submit to UW; (2) balances/payments not increased — if yes, update the amount in Encompass; (3) no new inquiries — reach out to LOX to confirm no new debt.",
                  "suggestion": "Work each check, then mark the refresh Reviewed (not Cleared) so UW re-confirms guidelines."})
    flags.append({"substep": "9.1", "title": "Invoice must be uploaded", "severity": "info",
                  "details": "The credit refresh invoice must be uploaded to the file.",
                  "suggestion": "Upload the CIC invoice to the eFolder."})

    ledger = []
    refresh_conds = _find_conditions(conditions, "credit refresh", "refresh")
    if options.get("credit_refresh_reviewed") and refresh_conds:
        from shared.conditions_io import update_condition_status, flush_action_ledger, flush_action_flags
        for c in refresh_conds[:3]:
            try:
                update_condition_status(loan_id=loan_id, condition_id=_cond_id(c), status=RESUBMIT_STATUS,
                                        state=state, substep="9.1", substep_name="Credit Refresh",
                                        condition_title=cond_title(c))
            except Exception as e:
                logger.error(f"[CREDIT_REFRESH] {e}")
        ledger += flush_action_ledger()
        flags.extend(flush_action_flags())
    elif options.get("credit_refresh_reviewed") and cond_err:
        flags.append({"substep": "9.1", "title": "Could not read conditions", "severity": "warning",
                      "details": f"Cannot mark the refresh condition Reviewed ({cond_err}).",
                      "suggestion": "Mark the credit refresh condition Reviewed manually."})

    refresh_date = str(options.get("credit_refresh_date") or "").strip()
    if refresh_date:
        from shared.encompass_io import write_fields, flush_field_writes_ledger, flush_field_writes_flags
        try:
            write_fields(loan_id=loan_id, updates={DOCEXP_CREDIT_REFRESH_DATE: refresh_date}, state=state,
                         node_id="order_credit_refresh", substep="9.1", substep_name="Credit Refresh",
                         title="Credit Refresh Doc-Exp Date", details=f"Set Credit Refresh date to {refresh_date}.")
            ledger += flush_field_writes_ledger()
            flags.extend(flush_field_writes_flags())
        except Exception as e:
            logger.error(f"[CREDIT_REFRESH] doc-exp {e}")

    return make_command(tool_call_id, "Credit refresh reviewed.", flags=flags, ledger=ledger,
                        extra={"refresh_conditions": len(refresh_conds)})


@tool
def order_credit_supplement(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Initiate a Credit Supplement; on receipt mark Ready-for-UW and resubmit.

    While waiting, set the supplement condition to Requested. When received, upload
    the supplement to the condition, mark it Ready for UW, and return to UW by
    completing the TPO Conditions received milestone. Judgment: if the supplement is
    the only open condition AND shows no derogatory history, do NOT submit to TPO
    Conditions unless it's the last prior-to-doc condition open.

    Options: supplement_received=true (mark Ready + resubmit), else marks Requested.
    """
    options = state.get("options") or {}
    loan_id = state.get("loan_id")
    conditions, cond_err = load_conditions(state)

    corr = _correspondent_guard(state, "9.2")
    if corr:
        return make_command(tool_call_id, "Credit supplement N/A (Correspondent).", flags=[corr])

    flags = []
    supp_conds = _find_conditions(conditions, "supplement")
    if cond_err:
        flags.append({"substep": "9.2", "title": "Could not read conditions", "severity": "warning",
                      "details": f"Supplement condition unverified ({cond_err}).",
                      "suggestion": "Manage the supplement condition manually."})

    flags.append({"substep": "9.2", "title": "Supplement submission judgment", "severity": "info",
                  "details": "If the supplement is the only condition open AND shows no derogatory payment history, do not submit to TPO Conditions until the client provides more conditions — unless it is the last prior-to-doc condition open.",
                  "suggestion": "Only resubmit when appropriate per the derogatory/last-condition rule."})

    ledger = []
    received = bool(options.get("supplement_received"))
    if supp_conds:
        from shared.conditions_io import (
            update_condition_status, complete_milestone, flush_action_ledger, flush_action_flags,
        )
        status = "Reviewed" if received else "Requested"
        for c in supp_conds[:3]:
            try:
                update_condition_status(loan_id=loan_id, condition_id=_cond_id(c), status=status,
                                        state=state, substep="9.2", substep_name="Credit Supplement",
                                        condition_title=cond_title(c))
            except Exception as e:
                logger.error(f"[SUPPLEMENT] {e}")
        if received:
            try:
                complete_milestone(loan_id=loan_id, milestone_name=TPO_RESUBMIT_MILESTONE, state=state,
                                   substep="9.2", substep_name="Credit Supplement")
            except Exception as e:
                logger.error(f"[SUPPLEMENT] milestone {e}")
        ledger += flush_action_ledger()
        flags.extend(flush_action_flags())
    else:
        flags.append({"substep": "9.2", "title": "No supplement condition found", "severity": "info",
                      "details": f"No supplement condition among {len(conditions)}.",
                      "suggestion": "Confirm the supplement condition exists before ordering."})

    return make_command(tool_call_id, "Credit supplement handled.", flags=flags, ledger=ledger)


@tool
def order_ssa_verification(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Initiate an SSA Verification (PreciseID); handle the SS-89 fallback.

    The order is placed on CIC (Fraud Detection / PreciseID). On results: a positive
    SSN match (green check) → share/print and upload to Encompass. If NO match, an
    SS-89 form is required — verify it was signed during the disclosure process; if
    not, it must be obtained.

    Options: ssa_match=true|false to tailor the reminder.
    """
    options = state.get("options") or {}
    corr = _correspondent_guard(state, "9.3")
    if corr:
        return make_command(tool_call_id, "SSA verification N/A (Correspondent).", flags=[corr])

    flags = [{"substep": "9.3", "title": "SSA verification results", "severity": "info",
              "details": "Reference # = NQMF Loan Number. On a positive SSN match, share/print the report and upload to Encompass.",
              "suggestion": "Upload the PreciseID result to the eFolder."}]

    match = options.get("ssa_match")
    if match is False:
        flags.append({"substep": "9.3", "title": "No match — SS-89 required", "severity": "warning",
                      "details": "No SSN match: an SS-89 form is required by NQMF. Verify it was signed during the disclosure process.",
                      "suggestion": "If the SS-89 was not signed at disclosure, obtain it."})
    else:
        flags.append({"substep": "9.3", "title": "SS-89 fallback", "severity": "info",
                      "details": "If no match is found, an SS-89 is required — verify it was signed during disclosure, otherwise obtain it.",
                      "suggestion": "Confirm SS-89 status only if the result shows no match."})
    return make_command(tool_call_id, "SSA verification handled.", flags=flags)


@tool
def order_tax_transcripts(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Initiate Tax Transcripts on the 3rd Party Order screen (Requested -> Form Ready).

    Use the 4506C box or the transcript box. Click Requested to have the internal
    team prep the form into the unassigned folder; the RM then gets broker signatures
    (external — not the borrower). When the signed doc returns, click Form Ready to
    notify the third-party team to complete the request.

    Options: transcripts_requested=true, transcripts_form_ready=true.
    """
    options = state.get("options") or {}
    loan_id = state.get("loan_id")
    corr = _correspondent_guard(state, "9.4")
    if corr:
        return make_command(tool_call_id, "Tax transcripts N/A (Correspondent).", flags=[corr])

    flags = [{"substep": "9.4", "title": "Broker signatures (external)", "severity": "info",
              "details": "After Requested, the RM contacts the broker for the required borrower signatures — NOT the borrower directly.",
              "suggestion": "Coordinate signatures with the broker, then set Form Ready."}]

    updates = {}
    if options.get("transcripts_requested"):
        updates[TPO_TAX_REQUESTED] = "Y"
    if options.get("transcripts_form_ready"):
        updates[TPO_TAX_FORM_READY] = "Y"

    ledger = []
    if updates:
        from shared.encompass_io import write_fields, flush_field_writes_ledger, flush_field_writes_flags
        try:
            write_fields(loan_id=loan_id, updates=updates, state=state, node_id="order_tax_transcripts",
                         substep="9.4", substep_name="Tax Transcripts", title="Tax Transcript Tracking",
                         details=f"Updated 3rd-party tax tracking: {', '.join(updates.keys())}.")
            ledger += flush_field_writes_ledger()
            flags.extend(flush_field_writes_flags())
        except Exception as e:
            logger.error(f"[TAX_TRANSCRIPTS] {e}")
            flags.append({"substep": "9.4", "title": "Tracking update failed", "severity": "warning",
                          "details": f"Could not update the 3rd-party tax tracking fields: {str(e)[:200]}",
                          "suggestion": "Update the 3rd Party Order screen manually."})
    else:
        flags.append({"substep": "9.4", "title": "No tracking update requested", "severity": "info",
                      "details": "Provide options.transcripts_requested / transcripts_form_ready to update the screen.",
                      "suggestion": "Set the flags to record Requested / Form Ready."})
    return make_command(tool_call_id, "Tax transcript tracking handled.", flags=flags, ledger=ledger)


@tool
def order_vvoe(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Handle the Verbal VOE (not DSCR): review, Doc-Exp date, verify vs URLA.

    On completion, access the eFolder 'Income: Verbal VOE', review the effective date
    and enter it on the Doc Expiration screen, ensure the status reflects actively
    employed, and verify the employment dates on the VVOE match URLA Page 2.

    Options: vvoe_date="MM/DD/YYYY" to set the Doc-Exp date.
    """
    options = state.get("options") or {}
    loan_id = state.get("loan_id")
    corr = _correspondent_guard(state, "9.5")
    if corr:
        return make_command(tool_call_id, "VVOE N/A (Correspondent).", flags=[corr])

    flags = []
    # DSCR exclusion.
    program = f"{_profile(state, 'loan_type') or ''} {(_los(state, 'loan_program') or '')}".lower()
    if "dscr" in program:
        flags.append({"substep": "9.5", "title": "VVOE not required (DSCR)", "severity": "info",
                      "details": "VVOE does not apply to DSCR loans.",
                      "suggestion": "Skip VVOE for DSCR."})
        return make_command(tool_call_id, "VVOE N/A (DSCR).", flags=flags)

    vvoe_doc = _doc_present(state, "Verbal VOE")
    flags.append({"substep": "9.5", "title": "VVOE review", "severity": "warning",
                  "details": (
                      "Review the VVOE effective date and confirm the status reflects actively employed. "
                      "Verify the employment dates on the VVOE match URLA Page 2. "
                      f"(VVOE doc extracted: {vvoe_doc})"
                  ),
                  "suggestion": "Enter the VVOE effective date on the Doc Expiration screen."})

    ledger = []
    vvoe_date = str(options.get("vvoe_date") or "").strip()
    if vvoe_date:
        from shared.encompass_io import write_fields, flush_field_writes_ledger, flush_field_writes_flags
        try:
            write_fields(loan_id=loan_id, updates={DOCEXP_VVOE_DATE: vvoe_date}, state=state,
                         node_id="order_vvoe", substep="9.5", substep_name="Verbal VOE",
                         title="VVOE Doc-Exp Date", details=f"Set VVOE date to {vvoe_date}.")
            ledger += flush_field_writes_ledger()
            flags.extend(flush_field_writes_flags())
        except Exception as e:
            logger.error(f"[VVOE] {e}")
    return make_command(tool_call_id, "VVOE handled.", flags=flags, ledger=ledger,
                        extra={"vvoe_doc_present": vvoe_doc})


@tool
def validate_str_permit(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Review the STR Permit (Property Guard) findings; mark condition Reviewed + resubmit.

    NQMF requires a Property Guard report on all transactions using short-term rental
    income. The RM reviews the findings to verify the property is eligible. Whether
    compliant or not, mark the condition Reviewed and resubmit to UW (UW validates on
    the NonQM v2 screen). If not compliant, resubmit immediately.

    Options: str_reviewed=true to mark the STR condition Reviewed + resubmit.
    """
    options = state.get("options") or {}
    loan_id = state.get("loan_id")
    conditions, cond_err = load_conditions(state)

    corr = _correspondent_guard(state, "9.6")
    if corr:
        return make_command(tool_call_id, "STR permit N/A (Correspondent).", flags=[corr])

    flags = [{"substep": "9.6", "title": "Review STR permit findings", "severity": "warning",
              "details": "Verify the property is eligible per the Property Guard report. UW validates on NonQM v2 (STR Permit Validated). If not compliant, resubmit to UW immediately.",
              "suggestion": "Mark the STR condition Reviewed and resubmit to UW."}]

    ledger = []
    str_conds = _find_conditions(conditions, "short term rental", "str", "rental permit", "permit")
    if options.get("str_reviewed") and str_conds:
        from shared.conditions_io import (
            update_condition_status, complete_milestone, flush_action_ledger, flush_action_flags,
        )
        for c in str_conds[:3]:
            try:
                update_condition_status(loan_id=loan_id, condition_id=_cond_id(c), status=RESUBMIT_STATUS,
                                        state=state, substep="9.6", substep_name="Short Term Rental Permit Validation",
                                        condition_title=cond_title(c))
            except Exception as e:
                logger.error(f"[STR] {e}")
        try:
            complete_milestone(loan_id=loan_id, milestone_name=TPO_RESUBMIT_MILESTONE, state=state,
                               substep="9.6", substep_name="Short Term Rental Permit Validation")
        except Exception as e:
            logger.error(f"[STR] milestone {e}")
        ledger += flush_action_ledger()
        flags.extend(flush_action_flags())
    elif options.get("str_reviewed") and cond_err:
        flags.append({"substep": "9.6", "title": "Could not read conditions", "severity": "warning",
                      "details": f"STR condition unverified ({cond_err}).",
                      "suggestion": "Mark the STR condition Reviewed manually."})
    return make_command(tool_call_id, "STR permit validation handled.", flags=flags, ledger=ledger,
                        extra={"str_conditions": len(str_conds)})


@tool
def verify_pl(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """P&L Verification (P&L Only loans): ensure no open P&L conditions before requesting.

    NQMF requires verbal verification of the P&L on all P&L-Only loans (UW may also
    add the condition for questionable P&L docs). Before requesting the verification,
    ensure there are no open conditions regarding the P&L so the verification is
    accurate.
    """
    conditions, cond_err = load_conditions(state)
    corr = _correspondent_guard(state, "9.7")
    if corr:
        return make_command(tool_call_id, "P&L verification N/A (Correspondent).", flags=[corr])

    flags = []
    if cond_err:
        flags.append({"substep": "9.7", "title": "Could not read conditions", "severity": "warning",
                      "details": f"Cannot verify open P&L conditions ({cond_err}).",
                      "suggestion": "Confirm no open P&L conditions manually before requesting."})
    else:
        pl_conds = _find_conditions(conditions, "p&l", "profit and loss", "profit & loss")
        open_pl = [c for c in pl_conds if _is_open(c)]
        if open_pl:
            flags.append({"substep": "9.7", "title": f"Open P&L condition(s) — do not request yet ({len(open_pl)})", "severity": "warning",
                          "details": "; ".join(f"{cond_title(c)} [{cond_status(c) or 'open'}]" for c in open_pl[:5]),
                          "suggestion": "Clear/resolve open P&L conditions before requesting the P&L verification."})
        else:
            flags.append({"substep": "9.7", "title": "No open P&L conditions", "severity": "info",
                          "details": f"No open P&L condition among {len(conditions)}. Safe to request the verification.",
                          "suggestion": "Initiate the P&L verification via the 3rd Party Order screen."})
    return make_command(tool_call_id, "P&L verification prerequisite checked.", flags=flags)
