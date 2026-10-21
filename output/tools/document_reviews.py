"""STEP_06: Document Reviews.

6.1 review_signed_1003        — executed broker/lender 1003
6.2 review_credit_reports     — re-issued credit verification
6.3 review_preliminary_title  — title standards + mortgagee clause
6.4 review_cpl                — closing protection letter
6.5 review_eo_wiring          — E&O policy + wiring instructions
6.6 review_payoff_statements  — payoff letters (refi only)
"""

import logging
from typing import Annotated

from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from ._helpers import _profile, make_command, _doc_present, _los, doc_field, to_number, _parse_date, _days_between

logger = logging.getLogger(__name__)

MC_NY = "Great Home Mortgage of New York, in lieu of true name NP, Inc. ISAOA/ATIMA, 4800 N Federal Hwy, Bldg. E, Suite 200, Boca Raton, FL 33431 (include NQMF loan number)"
MC_OTHER = "NQM Funding, LLC. ISAOA/ATIMA, 4800 N Federal Hwy, Bldg. E, Suite 200, Boca Raton, FL 33431 (include NQMF loan number)"


def _mortgagee_clause(prop_state: str) -> str:
    if prop_state == "NY":
        return MC_NY
    if prop_state == "TX":
        return "ISAOA/ATIMA clause NOT required for TX loans; " + MC_OTHER
    return MC_OTHER


@tool
def review_signed_1003(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Confirm receipt of the executed broker/lender 1003.

    Verify a wet signature or e-sign certification with the signature. For
    Wholesale files, ensure it is the NQMF application that is signed.
    """
    doc_present = _doc_present(state, "1003 URLA")
    flags = [{
        "substep": "6.1", "title": "Executed 1003 verification", "severity": "info",
        "details": "Confirm wet signature OR e-sign certification with the signature. Wholesale: ensure the signed application is the NQMF application.",
        "suggestion": "Return for correct/complete signatures if missing.",
    }]
    if doc_present:
        flags.append({"substep": "6.1", "title": "1003 URLA on file", "severity": "info",
                      "details": "A 1003 URLA was extracted from the eFolder; verify signatures/execution.",
                      "suggestion": "Confirm it is the signed NQMF application (Wholesale)."})
    else:
        flags.append({"substep": "6.1", "title": "1003 URLA not found in eFolder", "severity": "warning",
                      "details": "No 1003 URLA was extracted from the eFolder.",
                      "suggestion": "Obtain the executed broker/lender 1003."})
    return make_command(tool_call_id, "Signed 1003 reviewed (doc + checklist).", flags=flags,
                        extra={"doc_present": doc_present})


@tool
def review_credit_reports(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Verify a broker-submitted new credit report was re-issued via the TPO Portal.

    Compare the Credit Ref# in Encompass vs the # on the report. Notify the UW via
    the conversation log of new credit, ensure all debts pulled through, and check
    whether the new report pushed DTI above the program maximum.
    """
    flags = [
        {"substep": "6.2", "title": "Verify credit re-issue", "severity": "warning",
         "details": "Before submitting to UW, compare the Credit Ref# in Encompass to the # on the report to confirm it was re-issued through the TPO Portal.",
         "suggestion": "Reject reports not re-issued through the portal."},
        {"substep": "6.2", "title": "Notify UW & check impact", "severity": "info",
         "details": "Notify the UW via conversation log that new credit was provided. Ensure all debts pulled through. Check whether DTI increased above the program maximum.",
         "suggestion": "Log the new credit note and re-check DTI against program limits."},
    ]
    dti = _profile(state, "dti_total")
    if dti not in (None, "", "//"):
        flags.append({"substep": "6.2", "title": f"Current DTI on file: {dti}", "severity": "info",
                      "details": "Compare a new/re-issued credit report's impact against this DTI and the program maximum.",
                      "suggestion": "Flag if a new report pushes DTI above the program max."})
    if _doc_present(state, "Credit Report"):
        flags.append({"substep": "6.2", "title": "Credit Report on file", "severity": "info",
                      "details": "A Credit Report was extracted from the eFolder; compare the Credit Ref# against Encompass.",
                      "suggestion": "Confirm re-issue via the TPO Portal."})
    return make_command(tool_call_id, "Credit report reviewed (doc + checklist).", flags=flags,
                        extra={"dti_total": dti})


@tool
def review_preliminary_title(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Review the Preliminary Title against NQMF standards.

    Checks mortgagee clause (state-specific), borrower/entity name per vesting,
    lender coverage ≥ loan amount, and Title Effective Date within 90 days of
    closing (matching the doc-expiration screen/conditions).
    """
    prop_state = (_profile(state, "state") or "").upper()
    clause = _mortgagee_clause(prop_state)
    flags = [
        {"substep": "6.3", "title": "Mortgagee clause", "severity": "warning",
         "details": (
             f"Wholesale must reflect the correct NQMF mortgagee clause with ISAOA/ATIMA. For this state ({prop_state or 'unknown'}): {clause}. "
             "Correspondent: correct lender name/address (ISAOA/ATIMA not required)."
         ),
         "suggestion": "Verify the exact clause text for the property state."},
        {"substep": "6.3", "title": "Title core standards", "severity": "info",
         "details": "Correct borrower/entity name per vesting. Lender coverage ≥ loan amount. Title Effective Date within 90 days of closing (dates must match the doc-expiration screen & expiration conditions).",
         "suggestion": "Confirm coverage amount and effective date window."},
    ]
    title_doc = _doc_present(state, "Title Report")
    if title_doc:
        # Data-driven: lender coverage ≥ loan amount, effective date ≤ 90 days of closing.
        coverage = to_number(doc_field(state, "title_report", "lender_coverage", "loan_policy", "coverage", "liability"))
        loan_amount = to_number(_los(state, "loan_amount"))
        if coverage and loan_amount:
            if coverage < loan_amount:
                flags.append({"substep": "6.3", "title": "Title coverage below loan amount", "severity": "warning",
                              "details": f"Lender coverage {coverage:,.0f} is below the loan amount {loan_amount:,.0f}.",
                              "suggestion": "Require the title policy coverage to be ≥ the loan amount."})
            else:
                flags.append({"substep": "6.3", "title": "Title coverage adequate", "severity": "info",
                              "details": f"Lender coverage {coverage:,.0f} ≥ loan amount {loan_amount:,.0f}.", "suggestion": ""})

        eff = _parse_date(doc_field(state, "title_report", "effective_date", "effectivedate", "effective", "commitment_date"))
        closing = _parse_date(_los(state, "estimated_closing_date"))
        if eff and closing:
            gap = _days_between(eff, closing)
            if gap is not None and gap > 90:
                flags.append({"substep": "6.3", "title": "Title Effective Date > 90 days from closing", "severity": "warning",
                              "details": f"Title effective {eff} is {gap} days before closing {closing} (must be within 90 days).",
                              "suggestion": "Obtain an updated title commitment within 90 days of closing."})
            else:
                flags.append({"substep": "6.3", "title": "Title Effective Date within 90 days", "severity": "info",
                              "details": f"Title effective {eff} is {gap} day(s) before closing {closing}.", "suggestion": ""})

        flags.append({"substep": "6.3", "title": "Title Report on file", "severity": "info",
                      "details": "A Title Report/commitment was extracted from the eFolder; the checks above use its values.",
                      "suggestion": "Confirm mortgagee clause and vesting (not auto-compared)."})
    else:
        flags.append({"substep": "6.3", "title": "Title Report not found in eFolder", "severity": "warning",
                      "details": "No Title Report was extracted from the eFolder.",
                      "suggestion": "Obtain the preliminary title/commitment before clearing title conditions."})
    return make_command(tool_call_id, "Preliminary title reviewed (doc + checklist).", flags=flags,
                        extra={"state": prop_state, "mortgagee_clause": clause, "title_doc_present": title_doc})


@tool
def review_cpl(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Review the Closing Protection Letter (does not apply to Correspondent).

    Checks mortgagee clause, correct NQMF loan number, borrower/entity per vesting,
    agent name matching the title commitment and E&O policy, and that the CPL is
    unexpired with an effective date within 60 days of closing.
    """
    prop_state = (_profile(state, "state") or "").upper()
    clause = _mortgagee_clause(prop_state)
    flags = [
        {"substep": "6.4", "title": "CPL standards", "severity": "info",
         "details": (
             f"Wholesale mortgagee clause with ISAOA/ATIMA ({prop_state or 'state'}): {clause}. Correct NQMF Loan Number. "
             "Borrower/entity per vesting. Agent name matches title commitment & E&O policy. Unexpired; effective date within 60 days of closing."
         ),
         "suggestion": "Confirm agent-name consistency across CPL, title, and E&O."},
    ]
    cpl_doc = _doc_present(state, "Closing Protection Letter")
    if cpl_doc:
        flags.append({"substep": "6.4", "title": "CPL on file", "severity": "info",
                      "details": "A Closing Protection Letter was extracted from the eFolder; verify clause, loan number, agent name, and dates.",
                      "suggestion": "Confirm CPL is unexpired and matches the title agent."})
    else:
        flags.append({"substep": "6.4", "title": "CPL not found in eFolder", "severity": "warning",
                      "details": "No Closing Protection Letter was extracted (does not apply to Correspondent).",
                      "suggestion": "Obtain the CPL for Wholesale/NDC files."})
    return make_command(tool_call_id, "CPL reviewed (doc + checklist).", flags=flags,
                        extra={"mortgagee_clause": clause, "cpl_doc_present": cpl_doc})


@tool
def review_eo_wiring(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Review E&O policy & wiring instructions (does not apply to Correspondent).

    E&O: minimum coverage $1M ($500K for an attorney) and not expired; agent name
    matches the CPL and title commitment. Wire instructions: beneficiary matches
    the agent on the title commitment.
    """
    flags = [
        {"substep": "6.5", "title": "E&O coverage", "severity": "warning",
         "details": "E&O minimum coverage $1M ($500K for an attorney), not expired. E&O agent name matches the CPL and title commitment.",
         "suggestion": "Reject expired/under-limit E&O."},
        {"substep": "6.5", "title": "Wiring instructions", "severity": "warning",
         "details": "Wire instructions beneficiary must match the agent on the title commitment.",
         "suggestion": "Confirm beneficiary matches title agent to prevent wire fraud.",},
    ]
    return make_command(tool_call_id, "E&O & wiring checklist raised.", flags=flags)


@tool
def review_payoff_statements(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Review payoff statements (refinance transactions paying off existing liens).

    Confirms the payoff letter is unexpired and matches Encompass dates, per-diem
    interest is reflected, the mortgage is current (≤30 days past due), and the
    Encompass payoff amount covers per-diem through the disbursement date.
    """
    is_refi = _profile(state, "is_refinance")
    flags = []
    if not is_refi:
        flags.append({"substep": "6.6", "title": "Payoff N/A (not a refinance)", "severity": "info",
                      "details": "Payoff review applies only to refinances paying off existing liens.",
                      "suggestion": ""})
    flags.extend([
        {"substep": "6.6", "title": "Payoff letter validity", "severity": "warning",
         "details": "Payoff letter not expired; effective/expiration dates match Encompass. If void after a date, obtain an updated letter. Per-diem interest reflected; mortgage current (≤30 days past due).",
         "suggestion": "Request an updated payoff if expired/mismatched."},
        {"substep": "6.6", "title": "Payoff amount coverage", "severity": "info",
         "details": "Ensure the Encompass payoff amount covers per-diem through the disbursement date; update the payoff field within the liability in Encompass.",
         "suggestion": "Update the liability payoff amount to cover per-diem through disbursement."},
    ])
    return make_command(tool_call_id, "Payoff statement checklist raised.", flags=flags)
