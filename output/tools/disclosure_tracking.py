"""STEP_07: Disclosure Tracking (Wholesale Only).

7.1 review_broker_fee_agreements — CA/DE/IL executed broker fee agreements
7.2 review_les                    — initial & locked LE execution
7.3 review_icd                    — initial closing disclosure queue requirements
"""

import logging
from typing import Annotated

from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from ._helpers import (
    _profile,
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

BFA_STATES = {"CA", "DE", "IL"}
ICD_DAYS_BEFORE_ECD = 3


def _conditions_matching(conditions: list, *keywords: str) -> list:
    """Return conditions whose title contains any of the keywords (case-insensitive)."""
    kws = [k.lower() for k in keywords]
    out = []
    for c in conditions:
        title = cond_title(c).lower()
        if any(k in title for k in kws):
            out.append(c)
    return out


@tool
def review_broker_fee_agreements(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Verify executed Broker Fee Agreements (CA, DE, IL only).

    Access Disclosure Tracking (Tools / Disclosure Tracking). A populated received
    date indicates the disclosure was fully executed and returned.
    """
    prop_state = (_profile(state, "state") or "").upper()
    flags = []
    if prop_state in BFA_STATES:
        flags.append({"substep": "7.1", "title": f"Broker Fee Agreement required ({prop_state})", "severity": "warning",
                      "details": "CA/DE/IL require an executed Broker Fee Agreement. Confirm a populated received date in Disclosure Tracking (indicates fully executed & returned).",
                      "suggestion": "Obtain the executed Broker Fee Agreement."})
    else:
        flags.append({"substep": "7.1", "title": "Broker Fee Agreement not required", "severity": "info",
                      "details": f"Property state {prop_state or 'unknown'} is not CA/DE/IL; no broker fee agreement required.",
                      "suggestion": ""})
    return make_command(tool_call_id, "Broker fee agreement checklist raised.", flags=flags)


@tool
def review_les(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Verify Initial & Locked LEs via Disclosure Tracking.

    Initial LE executed by all parties (all loan types) → update condition to
    'cleared'. TRID loans: locked LE executed by all parties. Non-TRID loans:
    locked LE must be delivered (need not be executed).
    """
    conditions, cond_err = load_conditions(state)
    le_doc = _doc_present(state, "Loan Estimate")
    flags = [
        {"substep": "7.2", "title": "Initial LE", "severity": "info",
         "details": "Initial LE must be executed by all parties for all loan types; if so, update the condition to 'cleared'.",
         "suggestion": "Clear the initial LE condition once fully executed."},
        {"substep": "7.2", "title": "Locked LE", "severity": "info",
         "details": "TRID loans: locked LE executed by all parties. Non-TRID loans: locked LE must be delivered (does not need to be executed).",
         "suggestion": "Verify locked LE execution/delivery per TRID status."},
    ]

    # Disclosure Tracking: a populated received date = fully executed.
    le_received = _parse_date(_los(state, "le_received_date"))
    if le_received:
        flags.append({"substep": "7.2", "title": "Initial LE executed (received date populated)", "severity": "info",
                      "details": f"Disclosure Tracking shows the initial LE received {le_received} — fully executed by all parties.",
                      "suggestion": "Clear the initial LE condition (it is fully executed)."})

    if le_doc:
        flags.append({"substep": "7.2", "title": "Loan Estimate on file", "severity": "info",
                      "details": "A Loan Estimate was extracted from the eFolder.",
                      "suggestion": "Confirm execution/delivery in Disclosure Tracking."})
    else:
        flags.append({"substep": "7.2", "title": "Loan Estimate not found in eFolder", "severity": "warning",
                      "details": "No Loan Estimate document was extracted from the eFolder.",
                      "suggestion": "Confirm the LE has been disclosed and imaged."})

    if cond_err:
        flags.append({"substep": "7.2", "title": "Could not read conditions", "severity": "warning",
                      "details": f"LE condition status unavailable ({cond_err}); advisory only.",
                      "suggestion": "Verify LE conditions manually in Encompass."})
    else:
        le_conds = _conditions_matching(conditions, "loan estimate", "le ", "initial le", "locked le")
        if le_conds:
            for c in le_conds[:5]:
                st = cond_status(c) or "open"
                sev = "info" if st.lower() in ("cleared", "reviewed", "received") else "warning"
                flags.append({"substep": "7.2", "title": f"LE condition: {cond_title(c)}", "severity": sev,
                              "details": f"Status: {st}.",
                              "suggestion": "Clear once the LE is fully executed/delivered per TRID status."})
        else:
            flags.append({"substep": "7.2", "title": "No LE-specific condition found", "severity": "info",
                          "details": f"No LE condition among {len(conditions)} conditions.",
                          "suggestion": "Verify LE handling in Disclosure Tracking."})

    return make_command(tool_call_id, "LE conditions/documents reviewed.", flags=flags,
                        extra={"le_doc_present": le_doc, "condition_count": len(conditions)})


@tool
def review_icd(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Review Initial Closing Disclosure queue requirements (Wholesale TRID).

    ICD must be executed prior to CTC and at least 3 days prior to the ECD. Loans
    drop into the ICD queue when approved & locked, appraisal cleared, and the
    broker ICD form is uploaded to WS-Closing Condition (cleared if owner-occupied;
    waived if business purpose). RM verifies all ICD terms match Encompass (rate,
    LTV, fees, 3rd-party fees). POA → PTC condition present. NBS/non-borrowing
    title owners must execute on rescindable transactions.
    """
    conditions, cond_err = load_conditions(state)
    cd_doc = _doc_present(state, "Closing Disclosure")
    is_owner_occupied = bool(_profile(state, "is_owner_occupied"))

    # Data-driven ICD timing: CD received/executed must be ≥ 3 days before ECD.
    cd_received = _parse_date(_los(state, "cd_received_date"))
    ecd = _parse_date(_los(state, "estimated_closing_date"))
    if cd_received and ecd:
        lead = _days_between(cd_received, ecd)
        if lead is not None and lead < ICD_DAYS_BEFORE_ECD:
            icd_timing = {"substep": "7.3", "title": "ICD executed < 3 days before ECD", "severity": "critical",
                          "details": f"CD received/executed {cd_received} is only {lead} day(s) before ECD {ecd} (must be ≥ {ICD_DAYS_BEFORE_ECD}).",
                          "suggestion": "Adjust the ECD/closing timeline so the ICD is executed at least 3 days prior."}
        else:
            icd_timing = {"substep": "7.3", "title": f"ICD timing OK ({lead} days before ECD)", "severity": "info",
                          "details": f"CD received/executed {cd_received} is {lead} day(s) before ECD {ecd}.",
                          "suggestion": ""}
    else:
        icd_timing = {"substep": "7.3", "title": "ICD timing", "severity": "warning",
                      "details": "All Wholesale TRID loans: ICD executed prior to CTC AND at least 3 days prior to the ECD.",
                      "suggestion": "Confirm ICD executed within the 3-day window before ECD."}

    flags = [
        icd_timing,
        {"substep": "7.3", "title": "ICD queue prerequisites", "severity": "info",
         "details": "Approved & locked; appraisal cleared; broker ICD form uploaded to WS-Closing Condition with all docs. Owner-occupied → cleared; business purpose → waived.",
         "suggestion": "Verify all prerequisites before the loan drops into the ICD queue."},
        {"substep": "7.3", "title": "RM verifies ICD terms", "severity": "warning",
         "details": "Review all broker-provided info on the ICD form to ensure terms match Encompass: Rate, LTV, Fees, 3rd-party fees, etc.",
         "suggestion": "Reconcile ICD form against Encompass line by line."},
        {"substep": "7.3", "title": "3rd-party processing fee → NMLS", "severity": "info",
         "details": "If a 3rd-party processing fee is listed, pull NMLS data for the payee (nmlsconsumeraccess.org), print, and upload to the invoice section of the eFolder.",
         "suggestion": "Verify payee NMLS and upload evidence."},
        {"substep": "7.3", "title": "POA / NBS", "severity": "info",
         "details": "If closing via POA, confirm the PTC POA condition is on the loan. On rescindable transactions, non-borrowing spouses & non-borrowing title owners must execute the ICD (closing team adds NBS info).",
         "suggestion": "Confirm POA condition and NBS execution requirements.",},
    ]

    # Occupancy drives the WS-Closing Condition disposition (cleared vs waived).
    if is_owner_occupied:
        flags.append({"substep": "7.3", "title": "Owner-occupied → ICD condition cleared path", "severity": "info",
                      "details": "Occupancy is owner-occupied; the broker ICD form condition is cleared once uploaded.",
                      "suggestion": "Clear the WS-Closing Condition once the ICD form is uploaded."})
    else:
        flags.append({"substep": "7.3", "title": "Non-owner-occupied → ICD condition waived path", "severity": "info",
                      "details": f"Occupancy is '{_profile(state, 'occupancy') or 'unknown'}' (business purpose); the ICD form condition is waived.",
                      "suggestion": "Waive the WS-Closing Condition per business-purpose handling."})

    if cd_doc:
        flags.append({"substep": "7.3", "title": "Closing Disclosure on file", "severity": "info",
                      "details": "A Closing Disclosure was extracted from the eFolder.",
                      "suggestion": "Reconcile ICD terms against Encompass."})

    if cond_err:
        flags.append({"substep": "7.3", "title": "Could not read conditions", "severity": "warning",
                      "details": f"ICD condition status unavailable ({cond_err}); advisory only.",
                      "suggestion": "Verify ICD/closing conditions manually in Encompass."})
    else:
        icd_conds = _conditions_matching(conditions, "closing disclosure", "icd", "ws-closing", "initial cd")
        for c in icd_conds[:5]:
            st = cond_status(c) or "open"
            sev = "info" if st.lower() in ("cleared", "reviewed", "waived", "received") else "warning"
            flags.append({"substep": "7.3", "title": f"ICD condition: {cond_title(c)}", "severity": sev,
                          "details": f"Status: {st}.",
                          "suggestion": "Ensure ICD executed 3+ days before ECD and terms match Encompass."})

        # POA: if closing via POA, confirm the PTC POA condition is present.
        poa_conds = _conditions_matching(conditions, "poa", "power of attorney")
        closing_via_poa = bool((state.get("options") or {}).get("closing_via_poa"))
        if poa_conds:
            flags.append({"substep": "7.3", "title": "POA condition present", "severity": "info",
                          "details": "; ".join(f"{cond_title(c)} [{cond_status(c) or 'open'}]" for c in poa_conds[:3]),
                          "suggestion": "Confirm the PTC POA condition is satisfied for the POA closing."})
        elif closing_via_poa:
            flags.append({"substep": "7.3", "title": "POA closing but no POA condition found", "severity": "warning",
                          "details": "This loan is closing via POA but no PTC POA condition was found on the file.",
                          "suggestion": "Confirm UW added the PTC POA condition before closing via POA."})

    return make_command(tool_call_id, "ICD conditions/documents reviewed.", flags=flags,
                        extra={"cd_doc_present": cd_doc, "is_owner_occupied": is_owner_occupied,
                               "condition_count": len(conditions)})
