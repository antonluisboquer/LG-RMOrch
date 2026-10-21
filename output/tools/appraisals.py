"""STEP_08: Appraisals (Encompass-contained substeps only).

8.1 receive_appraisal            — verify received appraisal & resubmit to UW
8.2 review_secondary_appraisal   — verify CDA/BPO requirement via SSR + NonQM v2 fields
8.3 request_appraisal_corrections— mark correction condition Requested + log note
8.4 review_disaster_inspection   — verify UW added the disaster-inspection condition

The primary actions for corrections / transfers / disaster inspections are emails to
the NQMF appraisal desk (external); only the RM's in-Encompass slivers (marking the
condition Requested, adding a conversation-log note, verifying the UW condition) are
modeled here. Ordering via the TPO Portal and ValueLink look-ups are out of scope.
Custom NonQM v2 / SSR / CDA field IDs are PLACEHOLDERS pending confirmation
(see docs/ENCOMPASS_FIELD_CONFIRMATION.md).
"""

import logging
import re
from typing import Annotated

from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from ._helpers import (
    make_command,
    _doc_present,
    _profile,
    _los,
    load_conditions,
    cond_title,
    cond_status,
    doc_field,
)

logger = logging.getLogger(__name__)

APPRAISAL_DESK_EMAIL = "appraisaldesk@nqmf.com"
APPRAISAL_TRANSFER_EMAIL = "appraisaltransfers@nqmf.com"
RESUBMIT_MILESTONE = "TPO Cond Submitted"

REQUESTED_STATUS = "Requested"


def _cond_id(cond: dict) -> str:
    return str(cond.get("id") or cond.get("conditionId") or cond.get("Id") or "").strip()


def _find_conditions(conditions: list, *keywords: str) -> list:
    kws = [k.lower() for k in keywords]
    return [c for c in conditions if any(k in cond_title(c).lower() for k in kws)]


def _norm(text) -> str:
    """Loosely normalise a name/address string for comparison."""
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _appraisal_field(state: dict, *needles: str):
    """Best-effort read of an extracted Appraisal Report field (priority-matched)."""
    return doc_field(state, "appraisal_report", *needles)


def _appraisal_address(state: dict):
    """Assemble the appraisal subject address from its components.

    Prefer the street line; append city/state/zip when present so comparisons
    aren't made against a bare ZIP fragment.
    """
    street = doc_field(state, "appraisal_report", "property_address", "subject_address", "subject_property_address")
    if not street:
        return None
    city = doc_field(state, "appraisal_report", "property_city", "subject_city")
    st = doc_field(state, "appraisal_report", "property_state", "subject_state")
    zip5 = doc_field(state, "appraisal_report", "property_zip", "subject_zip")
    if zip5:
        zip5 = str(zip5).split("-", 1)[0]  # normalise ZIP+4 → 5-digit
    parts = [p for p in [street, city, st, zip5] if p]
    return ", ".join(parts)


@tool
def receive_appraisal(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Verify a received appraisal and resubmit to UW (guarded).

    Use the 'Sr Loan Coord – Appraisals Received' view to find received-but-not-
    resubmitted appraisals. Confirm the property address AND borrower name on the
    appraisal match Encompass exactly, then finish the TPO Cond's Submitted
    milestone to resubmit. When the Appraisal Report is in the eFolder, this
    compares the extracted address/borrower against Encompass automatically. Set
    options.appraisal_received=true to complete the milestone (dry-run gated).
    """
    options = state.get("options") or {}
    appraisal_doc = _doc_present(state, "Appraisal Report")
    subject_addr = _profile(state, "property_address") or "Unknown"
    borrower = " ".join(
        p for p in [_los(state, "borrower_first_name"), _los(state, "borrower_last_name")] if p
    ).strip()

    flags = []
    mismatch = False

    if appraisal_doc:
        appr_addr = _appraisal_address(state)
        appr_borrower = _appraisal_field(state, "borrower_name", "borrower", "applicant", "owner_name")

        # Address comparison — compare on the street line so a city/zip formatting
        # difference doesn't trip a false mismatch. Fall back to full-string
        # substring match either direction after normalising.
        if appr_addr and subject_addr != "Unknown":
            appr_street = _norm(str(appr_addr).split(",", 1)[0])
            subj_street = _norm(str(subject_addr).split(",", 1)[0])
            a, b = _norm(appr_addr), _norm(subject_addr)
            street_ok = bool(appr_street and subj_street and (appr_street in b or subj_street in appr_street))
            if street_ok or (a and b and (a in b or b in a)):
                flags.append({"substep": "8.1", "title": "Appraisal address matches", "severity": "info",
                              "details": f"Appraisal address '{appr_addr}' aligns with subject '{subject_addr}'.",
                              "suggestion": "Address verified."})
            else:
                mismatch = True
                flags.append({"substep": "8.1", "title": "Appraisal address MISMATCH", "severity": "critical",
                              "details": f"Appraisal address '{appr_addr}' does not match subject '{subject_addr}'.",
                              "suggestion": "Do NOT resubmit; return the appraisal for correction."})
        else:
            flags.append({"substep": "8.1", "title": "Appraisal address not extracted", "severity": "warning",
                          "details": f"Could not read the appraisal address; verify manually vs subject '{subject_addr}'.",
                          "suggestion": "Confirm the appraisal address matches Encompass exactly."})

        # Borrower name comparison.
        if appr_borrower and borrower:
            if _norm(borrower).split()[-1] not in _norm(appr_borrower):
                mismatch = True
                flags.append({"substep": "8.1", "title": "Appraisal borrower MISMATCH", "severity": "critical",
                              "details": f"Appraisal borrower '{appr_borrower}' does not match Encompass '{borrower}'.",
                              "suggestion": "Do NOT resubmit; return the appraisal for correction."})
            else:
                flags.append({"substep": "8.1", "title": "Appraisal borrower matches", "severity": "info",
                              "details": f"Appraisal borrower aligns with '{borrower}'.",
                              "suggestion": "Borrower verified."})
        else:
            flags.append({"substep": "8.1", "title": "Appraisal borrower not extracted", "severity": "warning",
                          "details": f"Could not read the appraisal borrower; verify manually vs '{borrower or 'Encompass'}'.",
                          "suggestion": "Confirm the borrower name(s) match Encompass exactly."})
    else:
        flags.append({"substep": "8.1", "title": "Appraisal Report not found in eFolder", "severity": "warning",
                      "details": "No Appraisal Report was extracted from the eFolder yet.",
                      "suggestion": "Confirm the appraisal has been received/imaged before resubmitting."})

    ledger = []
    if mismatch:
        flags.append({"substep": "8.1", "title": "Resubmit blocked", "severity": "warning",
                      "details": "Address/borrower mismatch detected — resubmission is not appropriate until corrected.",
                      "suggestion": "Resolve the mismatch before finishing TPO Cond's Submitted."})
    elif options.get("appraisal_received"):
        from shared.conditions_io import complete_milestone, flush_action_ledger, flush_action_flags
        try:
            complete_milestone(
                loan_id=state.get("loan_id"), milestone_name=RESUBMIT_MILESTONE,
                state=state, substep="8.1", substep_name="Receipt of the Appraisal",
            )
            ledger = flush_action_ledger()
            flags.extend(flush_action_flags())
        except Exception as e:
            logger.error(f"[APPRAISAL] resubmit failed: {e}")
            flags.append({"substep": "8.1", "title": "Appraisal resubmit failed", "severity": "warning",
                          "details": f"Could not complete '{RESUBMIT_MILESTONE}': {str(e)[:200]}",
                          "suggestion": "Finish the TPO Cond's Submitted milestone manually."})
    else:
        flags.append({"substep": "8.1", "title": "Resubmit after verification", "severity": "info",
                      "details": "Once verified, finish the TPO Cond's Submitted milestone to resubmit to UW. Set options.appraisal_received=true to complete automatically.",
                      "suggestion": "Complete TPO Cond's Submitted after confirming the match."})

    return make_command(tool_call_id, "Appraisal receipt handled.", flags=flags, ledger=ledger)


@tool
def review_secondary_appraisal(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Verify the secondary appraisal product requirement (CDA/BPO/etc.).

    Required on every NonQM loan unless: FNMA SSR ≤ 2.5, a Field Review received, or
    a Second Full Appraisal received. Requirement is met by SSR ≤ 2.5, a CDA (1–4
    unit), a BPO (Mixed Use or 5–10 unit residential), a Field Review, or a Second
    Full Appraisal. CDA required when SSR > 2.5 OR 1–4 unit with no SSR; BPO for
    Mixed Use / 5+ unit. Not required when 2 appraisals received. Reads the FNMA
    SSR score, # units / property type, and the NonQM v2 CDA Ordered / CDA
    Received-Waived fields to determine and verify the requirement automatically.
    """
    ssr_raw = _los(state, "fnma_ssr_score")
    units_raw = _los(state, "property_units")
    prop_type = (_los(state, "property_type") or _profile(state, "property_type") or "").strip()
    cda_ordered = _los(state, "cda_ordered_date")
    cda_recwaived = _los(state, "cda_received_waived")

    def _num(v):
        try:
            return float(str(v).strip())
        except (TypeError, ValueError):
            return None

    ssr = _num(ssr_raw)
    units = _num(units_raw)
    ptype = prop_type.lower()
    is_mixed_use = "mixed" in ptype

    flags = []

    # ── Determine whether a secondary product is required ──
    if ssr is not None and ssr <= 2.5:
        flags.append({"substep": "8.2", "title": "Secondary product NOT required", "severity": "info",
                      "details": f"FNMA SSR score is {ssr} (≤ 2.5) — no secondary appraisal product required.",
                      "suggestion": "Verify the CDA Received/Waived field reflects the waiver on NonQM v2."})
        required_product = None
    else:
        # Requirement applies — determine CDA vs BPO.
        if is_mixed_use or (units is not None and units >= 5):
            required_product = "BPO"
            reason = "Mixed Use property" if is_mixed_use else f"{int(units)}-unit residential property"
        else:
            required_product = "CDA"
            reason = (f"SSR score is {ssr} (> 2.5)" if ssr is not None
                      else "no FNMA SSR score available on a 1–4 unit property")
        flags.append({"substep": "8.2", "title": f"{required_product} required", "severity": "warning",
                      "details": f"A {required_product} is required ({reason}).",
                      "suggestion": f"Ensure the {required_product} has been ordered/received (not required if 2 appraisals are on file)."})

    # ── Verify the NonQM v2 CDA tracking fields ──
    if required_product == "CDA":
        if cda_ordered:
            flags.append({"substep": "8.2", "title": "CDA Ordered date present", "severity": "info",
                          "details": f"NonQM v2 'CDA Ordered' = {cda_ordered}.",
                          "suggestion": "Resubmit to UW once the CDA is received."})
        else:
            flags.append({"substep": "8.2", "title": "CDA not yet ordered", "severity": "warning",
                          "details": "NonQM v2 'CDA Ordered' date is blank while a CDA appears required.",
                          "suggestion": f"Confirm the CDA has been ordered; if broker-ordered original, request SSRs via {APPRAISAL_DESK_EMAIL}."})
    elif required_product is None:
        if not cda_recwaived:
            flags.append({"substep": "8.2", "title": "Confirm CDA waived on NonQM v2", "severity": "warning",
                          "details": "Secondary product is not required, but NonQM v2 'CDA Received/Waived' is blank.",
                          "suggestion": "Set the CDA Received/Waived field on NonQM v2 to reflect the waiver."})

    # ── Fallback advisory when SSR / units couldn't be read ──
    if ssr is None and units is None:
        flags.append({"substep": "8.2", "title": "SSR / property data unavailable", "severity": "warning",
                      "details": "Could not read the FNMA SSR score or # units — the CDA/BPO determination is advisory only.",
                      "suggestion": ("Manually determine: CDA when SSR > 2.5 or 1–4 unit w/o SSR; BPO on Mixed Use / 5+ unit; "
                                     "not required with 2 appraisals or SSR ≤ 2.5.")})

    return make_command(tool_call_id, "Secondary appraisal requirement reviewed.", flags=flags)


@tool
def request_appraisal_corrections(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Handle appraisal correction/update requests (in-Encompass sliver).

    When UW requests appraisal corrections/updates on a wholesale loan ordered
    through the NQMF appraisal desk, the RM emails the desk (external), then marks
    the condition Requested and places a copy of the request in the conversation
    log. This tool surfaces the correction conditions, and — when
    options.appraisal_correction_requested=true — marks matching conditions
    Requested and adds a conversation-log note (both dry-run gated). Appraisals
    ordered externally/transferred in must be revised by the prior lender.
    """
    options = state.get("options") or {}
    conditions, err = load_conditions(state)
    flags = []
    ledger = []

    if err:
        flags.append({"substep": "8.3", "title": "Could not load conditions", "severity": "warning",
                      "details": f"Condition read failed: {err[:200]}",
                      "suggestion": "Review appraisal correction conditions manually."})

    corr_conds = _find_conditions(conditions, "appraisal", "1004d", "correction", "revision", "appraisal update")
    if corr_conds:
        flags.append({"substep": "8.3", "title": "Appraisal correction conditions", "severity": "info",
                      "details": "; ".join(f"{cond_title(c)} [{cond_status(c) or 'open'}]" for c in corr_conds[:5]),
                      "suggestion": f"Email {APPRAISAL_DESK_EMAIL} to request the correction, then mark the condition Requested."})
    else:
        flags.append({"substep": "8.3", "title": "No appraisal correction conditions", "severity": "info",
                      "details": "No open appraisal correction/update conditions were found.",
                      "suggestion": "No action needed unless UW adds a correction condition."})

    flags.append({"substep": "8.3", "title": "Correction request is external", "severity": "info",
                  "details": f"The actual correction request is an email to {APPRAISAL_DESK_EMAIL} (wholesale, NQMF-ordered only). "
                             "Externally-ordered/transferred appraisals must be revised by the prior lender.",
                  "suggestion": "Send the desk request outside this workflow; save a copy to the conversation log."})

    if options.get("appraisal_correction_requested") and corr_conds:
        from shared.conditions_io import (
            update_condition_status, add_conversation_log_note,
            flush_action_ledger, flush_action_flags,
        )
        note = options.get("appraisal_correction_note") or "Appraisal correction/update requested from the appraisal desk."
        loan_id = state.get("loan_id")
        for c in corr_conds:
            update_condition_status(loan_id=loan_id, condition_id=_cond_id(c), status=REQUESTED_STATUS,
                                    state=state, substep="8.3", substep_name="Appraisal Corrections",
                                    condition_title=cond_title(c))
        add_conversation_log_note(loan_id=loan_id, note=note, state=state,
                                  substep="8.3", substep_name="Appraisal Corrections")
        ledger = flush_action_ledger()
        flags.extend(flush_action_flags())

    return make_command(tool_call_id, "Appraisal corrections handled.", flags=flags, ledger=ledger)


@tool
def review_disaster_inspection(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Review disaster-inspection requirement (in-Encompass sliver).

    When a FEMA-declared disaster occurs after the original appraisal was received,
    a disaster inspection may be required. Ops circulates the declarations
    (external); the RM must verify the UW has added the appropriate inspection
    condition and then requests the inspection by emailing the appraisal desk
    (external). This tool verifies whether a disaster/inspection condition exists.
    """
    conditions, err = load_conditions(state)
    flags = []

    if err:
        flags.append({"substep": "8.4", "title": "Could not load conditions", "severity": "warning",
                      "details": f"Condition read failed: {err[:200]}",
                      "suggestion": "Review disaster-inspection conditions manually."})

    disaster_conds = _find_conditions(conditions, "disaster", "inspection", "fema")
    if disaster_conds:
        flags.append({"substep": "8.4", "title": "Disaster/inspection condition present", "severity": "info",
                      "details": "; ".join(f"{cond_title(c)} [{cond_status(c) or 'open'}]" for c in disaster_conds[:5]),
                      "suggestion": f"Request the inspection via {APPRAISAL_DESK_EMAIL}, then track the condition to clear."})
    else:
        flags.append({"substep": "8.4", "title": "No disaster-inspection condition", "severity": "info",
                      "details": "No disaster/inspection condition found. If the property is in a FEMA-declared "
                                 "disaster area affected after the appraisal date, UW must add the inspection condition.",
                      "suggestion": "Confirm with UW whether a disaster inspection condition is needed for affected loans."})

    return make_command(tool_call_id, "Disaster inspection reviewed.", flags=flags)
