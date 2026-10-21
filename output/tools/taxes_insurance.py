"""STEP_05: Taxes & Insurance.

5.1 review_hazard_flood_insurance — verify HOI/flood policy vs NQMF standards
5.2 review_property_taxes         — verify tax bill/amount vs NQMF standards
5.3 update_itemization           — Section 900/1000 of the 2015 Itemization
5.4 update_aggregate_escrow      — Aggregate Escrow Account setup for impounds
"""

import logging
from typing import Annotated

from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from ._helpers import _los, _profile, make_command, _doc_present, _doc_status, doc_field, to_number

logger = logging.getLogger(__name__)


def _channel(state: dict) -> str:
    """Best-effort channel: 'wholesale' | 'ndc' | 'correspondent' | 'unknown'."""
    options = state.get("options") or {}
    ch = str(options.get("channel") or "").strip().lower()
    if ch in ("wholesale", "ndc", "correspondent"):
        return ch
    return "unknown"


@tool
def review_hazard_flood_insurance(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Review hazard & flood insurance against NQMF standards.

    Verifies loss-payee/loan number, insured name, property address, effective
    date/term, premium payment, deductibles, wind/hail coverage, coverage
    amounts, and DSCR/condo-specific requirements per the RM Job Aid.
    """
    channel = _channel(state)
    purpose = (_profile(state, "purpose") or "").lower()
    is_refi = _profile(state, "is_refinance")

    hoi_doc = _doc_present(state, "Evidence of Insurance")
    flood_doc = _doc_present(state, "Flood Insurance")
    flood_cert = _doc_present(state, "Flood Certificate")

    loss_payee = (
        "NQMF Loan Number" if channel == "wholesale"
        else "lender name & lender loan number" if channel == "ndc"
        else "correct loss-payee for the channel (Wholesale=NQMF #, NDC=lender name+#)"
    )
    flags = [
        {"substep": "5.1", "title": "Insurance policy — core checks", "severity": "info",
         "details": (
             f"Loss payee clause & loan number: {loss_payee}. Proposed insured matches borrower/entity exactly. "
             "Policy matches subject property address exactly. Effective as of note date with a 12-month term."
         ),
         "suggestion": "Confirm each field on the declaration page before clearing the HOI/Flood condition."},
        {"substep": "5.1", "title": "Deductibles", "severity": "info",
         "details": "HOI deductible ≤ 5% of policy face value. Flood deductible ≤ $10K ($25K for Condo/PUD).",
         "suggestion": "Reject/return policies with deductibles above these limits."},
        {"substep": "5.1", "title": "Wind / Hail / Hurricane coverage", "severity": "info",
         "details": "HOI must include wind/hail/hurricane (special coverage form or all-perils). If wind/hail excluded, require a separate policy.",
         "suggestion": "Verify coverage form; request separate wind/hail policy if excluded."},
        {"substep": "5.1", "title": "Coverage amounts", "severity": "info",
         "details": (
             "HOI coverage ≥ lesser of loan amount or replacement cost. Flood coverage = lesser of UPB, replacement/insured "
             "value of improvements, or NFIP maximum."
         ),
         "suggestion": "Compute against loan amount / replacement cost and confirm adequacy."},
        {"substep": "5.1", "title": "DSCR & Condo specifics", "severity": "info",
         "details": (
             "DSCR loans: HOI must include 6 months PITIA rent-loss coverage (actual-loss-sustained not acceptable without max months). "
             "Condos: if master policy lacks walls-in coverage, obtain a separate HO6 (deductible ≤ 5% of dwelling coverage)."
         ),
         "suggestion": "Apply DSCR/condo add-on requirements where applicable."},
    ]
    if purpose.startswith("purch") or "purchase" in purpose:
        flags.append({"substep": "5.1", "title": "Purchase — effective-date rule", "severity": "warning",
                      "details": "If effective date is >15 days before note date, require an updated declaration page from the agent.",
                      "suggestion": "Request updated dec page if effective date is >15 days pre-note."})
    if is_refi:
        flags.append({"substep": "5.1", "title": "Refinance — premium/binder rules", "severity": "warning",
                      "details": "Premiums due within 60 days of closing must be paid in full prior to/at closing. New-policy binder cannot be dated >15 days before note date if not paid in full. No gap in coverage allowed.",
                      "suggestion": "Confirm premiums paid and no coverage gap."})
    flags.append({"substep": "5.1", "title": "Invoices filing", "severity": "info",
                  "details": "All premium invoices must be filed in the ICD placeholder AND assigned to the HOI/Flood condition.",
                  "suggestion": "File invoices in ICD placeholder and assign to condition."})

    # ── Data-driven comparisons from extracted policy fields (Step 0.3) ──
    if hoi_doc:
        subject_addr = _profile(state, "property_address") or ""
        borrower = " ".join(p for p in [_los(state, "borrower_first_name"), _los(state, "borrower_last_name")] if p).strip()

        insured = doc_field(state, "evidence_of_insurance", "insured_name", "named_insured", "borrower")
        if insured and borrower:
            if borrower.split()[-1].lower() not in insured.lower():
                flags.append({"substep": "5.1", "title": "Insured name mismatch", "severity": "warning",
                              "details": f"Policy insured '{insured}' does not appear to match borrower '{borrower}'.",
                              "suggestion": "Confirm the insured matches the borrower/entity exactly."})
            else:
                flags.append({"substep": "5.1", "title": "Insured name matches", "severity": "info",
                              "details": f"Policy insured aligns with '{borrower}'.", "suggestion": ""})

        pol_addr = doc_field(state, "evidence_of_insurance", "insured_location", "insured_mailing_address", "property_address")
        if pol_addr and subject_addr:
            a, b = pol_addr.lower(), subject_addr.lower()
            street = b.split(",")[0].strip()
            if street and street not in a and a.split(",")[0].strip() not in b:
                flags.append({"substep": "5.1", "title": "Policy address mismatch", "severity": "warning",
                              "details": f"Policy address '{pol_addr}' does not match subject '{subject_addr}'.",
                              "suggestion": "Return the policy if it does not match the subject property."})
            else:
                flags.append({"substep": "5.1", "title": "Policy address matches", "severity": "info",
                              "details": "Policy property address aligns with the subject property.", "suggestion": ""})

        coverage = to_number(doc_field(state, "evidence_of_insurance", "dwelling_coverage", "hazard_insurance_coverage", "coverage_a"))
        deductible = to_number(doc_field(state, "evidence_of_insurance", "deductible"))
        if coverage and deductible is not None:
            if deductible > 0.05 * coverage:
                flags.append({"substep": "5.1", "title": "HOI deductible exceeds 5%", "severity": "warning",
                              "details": f"Deductible {deductible:,.0f} is > 5% of coverage {coverage:,.0f} ({0.05*coverage:,.0f}).",
                              "suggestion": "Return the policy; deductible must be ≤ 5% of the face value."})
            else:
                flags.append({"substep": "5.1", "title": "HOI deductible within 5%", "severity": "info",
                              "details": f"Deductible {deductible:,.0f} ≤ 5% of coverage {coverage:,.0f}.", "suggestion": ""})
        loan_amount = to_number(_los(state, "loan_amount"))
        if coverage and loan_amount and coverage < loan_amount:
            flags.append({"substep": "5.1", "title": "HOI coverage below loan amount", "severity": "warning",
                          "details": f"Coverage {coverage:,.0f} is below the loan amount {loan_amount:,.0f} (must be ≥ lesser of loan amount or replacement cost).",
                          "suggestion": "Verify replacement cost; if lower coverage isn't justified, require more coverage."})

        eff = doc_field(state, "evidence_of_insurance", "coverage_start_date", "effective_date", "effective")
        exp = doc_field(state, "evidence_of_insurance", "coverage_end_date", "expiration_date", "expiration")
        if not (eff and exp):
            flags.append({"substep": "5.1", "title": "Policy dates not fully extracted", "severity": "info",
                          "details": f"Effective: {eff or 'n/a'}; Expiration/renewal: {exp or 'n/a'}. Confirm a 12-month term effective as of the note date.",
                          "suggestion": "Verify effective/expiration dates on the dec page."})

        # Flood deductible cap (10K, or 25K for Condo/PUD).
        flood_ded = to_number(doc_field(state, "flood_insurance", "deductible"))
        if flood_ded is not None:
            ptype = (_los(state, "property_type") or "").lower()
            cap = 25000 if ("condo" in ptype or "pud" in ptype) else 10000
            if flood_ded > cap:
                flags.append({"substep": "5.1", "title": "Flood deductible exceeds cap", "severity": "warning",
                              "details": f"Flood deductible {flood_ded:,.0f} exceeds the ${cap:,.0f} cap.",
                              "suggestion": "Return the flood policy; deductible over the cap is not acceptable."})

        flags.append({"substep": "5.1", "title": "Evidence of Insurance on file", "severity": "info",
                      "details": "An Evidence of Insurance / HOI declaration page was extracted; the checks above use its values.",
                      "suggestion": "Verify any fields that could not be auto-compared."})
    else:
        flags.append({"substep": "5.1", "title": "Evidence of Insurance not found in eFolder", "severity": "critical",
                      "details": "No Evidence of Insurance document was extracted. HOI is required to clear the insurance condition.",
                      "suggestion": "Obtain the HOI declaration page before clearing the condition."})
    if not (flood_doc or flood_cert):
        flags.append({"substep": "5.1", "title": "No flood documents in eFolder", "severity": "warning",
                      "details": "No Flood Insurance policy or Flood Certificate was extracted. Confirm the flood-zone determination and whether flood coverage is required.",
                      "suggestion": "Obtain the Flood Certificate; if in a flood zone, require a flood policy."})

    return make_command(tool_call_id, "Hazard & flood insurance reviewed (docs + checklist).", flags=flags,
                        extra={"hoi_doc_present": hoi_doc, "flood_doc_present": flood_doc,
                               "flood_cert_present": flood_cert})


@tool
def review_property_taxes(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Review property taxes against NQMF standards.

    Confirms a current tax bill exists for items due within 60 days and validates
    the tax amount using the purpose-specific method (New Construction, CA
    purchase, purchases with exemptions, refinances) per the RM Job Aid.
    """
    purpose = (_profile(state, "purpose") or "").lower()
    prop_state = (_profile(state, "state") or "").upper()

    flags = [{
        "substep": "5.2", "title": "Taxes due within 60 days need a current bill", "severity": "warning",
        "details": (
            "If any items are due within 60 days of closing, a current tax bill must be in the Property Taxes eFolder. "
            "If none from title, request one or pull from https://publicrecords.netronline.com/. Without current/verified "
            "figures the tax condition cannot be cleared."
        ),
        "suggestion": "Locate/obtain a current tax bill before clearing the tax condition.",
    }]

    is_refi = _profile(state, "is_refinance")
    is_purchase = "purchase" in purpose or purpose.startswith("purch")

    flags.append({
        "substep": "5.2", "title": "New Construction tax calculation", "severity": "info",
        "details": (
            "Use Title-confirmed rate (millage × greater of sales price or appraised value). If unavailable, use "
            "https://smartasset.com/taxes/property-taxes. If neither applies, calculate 1.5% of improved value."
        ),
        "suggestion": "Document the method used via processor cert or Notepad.",
    })
    if prop_state == "CA" and is_purchase:
        flags.append({
            "substep": "5.2", "title": "CA purchase tax calculation", "severity": "warning",
            "details": "Use Title-confirmed amount; if not confirmed, 1.25% of revised assessed value (or smartasset for lower-rate counties).",
            "suggestion": "Confirm CA tax figure with Title first.",
        })
    if is_purchase:
        flags.append({
            "substep": "5.2", "title": "Purchases with exemptions", "severity": "info",
            "details": (
                "Confirm current-year taxes (smartasset not allowed for purchase of an existing dwelling). Verify prior-owner "
                "exemptions (e.g. homestead) are NOT applied to the buyer's estimate for non-primary transactions. Review the "
                "tax bill/certificate under 'Property: Property Taxes' for discounts/exemptions."
            ),
            "suggestion": "Exclude prior-owner exemptions; document any non-bill amount used.",
        })
    if is_refi:
        flags.append({
            "substep": "5.2", "title": "Refinance taxes", "severity": "info",
            "details": "Confirm current-year taxes (smartasset not allowed for existing dwelling). Without current/verified figures the tax condition cannot be cleared.",
            "suggestion": "Obtain/verify current tax figures.",
        })
    flags.append({
        "substep": "5.2", "title": "Document non-bill amounts", "severity": "info",
        "details": "Any time an amount other than the tax bill is used, add a processor cert to Property: Property Taxes (TPO) or detail the calculation in Notepad.",
        "suggestion": "Always evidence how the tax figure was derived.",
    })
    tax_doc = _doc_present(state, "Tax Summary")
    if tax_doc:
        annual = doc_field(state, "tax_summary", "annual_tax", "total_tax", "tax_amount", "annual_amount", "amount")
        due = doc_field(state, "tax_summary", "due_date", "due", "delinquent")
        bits = [b for b in [f"annual tax: {annual}" if annual else None, f"due: {due}" if due else None] if b]
        detail = "A Tax Summary was extracted from the eFolder." + (" Extracted — " + "; ".join(bits) + "." if bits else "")
        flags.append({"substep": "5.2", "title": "Tax document on file", "severity": "info",
                      "details": detail,
                      "suggestion": "Confirm the escrow/itemization tax figure matches the extracted amount."})
    else:
        flags.append({"substep": "5.2", "title": "No tax document in eFolder", "severity": "warning",
                      "details": "No Tax Summary was extracted. A current tax bill is required for items due within 60 days.",
                      "suggestion": "Obtain a current tax bill and file under Property: Property Taxes."})
    return make_command(tool_call_id, "Property tax reviewed (docs + checklist).", flags=flags,
                        extra={"purpose": purpose, "state": prop_state, "tax_doc_present": tax_doc})


@tool
def update_itemization(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Guide the 2015 Itemization update (RM owns Sections 900 & 1000 only).

    Section 900: enter all tax & insurance premiums due (match dec page / eFolder
    tax info) and the "Pay To" payees. Taxes/water-sewer 60+ days delinquent go
    as a payoff on URLA Page 3, not Section 900. Other sections are owned by the
    Disclosure/COC/ICD/Closing teams. This is a form update (advisory).
    """
    flags = [
        {"substep": "5.3", "title": "Section 900 entries", "severity": "info",
         "details": "Enter all tax & insurance premiums due in Section 900; amounts must match the policy dec page and/or eFolder tax info. Enter the 'Pay To' payees for each T&I type.",
         "suggestion": "Match Section 900 amounts to source docs exactly."},
        {"substep": "5.3", "title": "Delinquent items → payoff", "severity": "warning",
         "details": "Taxes 60+ days delinquent must be a payoff on URLA Page 3 (not Section 900). Water/sewer due goes in Section 900; if 60+ days delinquent, list as payoff on URLA Page 3.",
         "suggestion": "Move 60+ day delinquencies to URLA Page 3 as payoffs."},
        {"substep": "5.3", "title": "Scope reminder", "severity": "info",
         "details": "RM is only responsible for Sections 900 and 1000. Do not edit other sections (Disclosure Desk/COC/ICD/Closing own those).",
         "suggestion": "Refer to the 2015 Itemization section of the closing job aid for details."},
    ]
    return make_command(tool_call_id, "Itemization (Section 900/1000) guidance raised.", flags=flags)


@tool
def update_aggregate_escrow(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Guide the Aggregate Escrow Account setup for impound loans.

    Applies to loans with impounds (not Correspondent). Update yearly tax and
    insurance amounts (matched to eFolder docs), run Setup with a 2-month cushion
    per disbursement type, input due dates (2 for semi-annual, 4 for quarterly),
    and note flood cannot be waived in a flood zone. Advisory (form update).
    """
    channel = _channel(state)
    flags = []
    if channel == "correspondent":
        flags.append({"substep": "5.4", "title": "Impounds N/A for Correspondent", "severity": "info",
                      "details": "Impounds do not apply to Correspondent loans; skip aggregate escrow setup.",
                      "suggestion": ""})
    flags.extend([
        {"substep": "5.4", "title": "Update yearly T&I amounts", "severity": "info",
         "details": "Update yearly amounts for each tax type and all property insurance types, matched against the eFolder tax/insurance docs.",
         "suggestion": "Match every amount to source documents."},
        {"substep": "5.4", "title": "Escrow Setup (if not waived)", "severity": "info",
         "details": "Cushion = 2 months per disbursement type. Input due dates (2 for semi-annual, 4 for quarterly). OK auto-calculates months + aggregate adjustment (always negative).",
         "suggestion": "Run Setup and verify the aggregate adjustment is negative."},
        {"substep": "5.4", "title": "Flood zone rule", "severity": "warning",
         "details": "In a flood zone, flood insurance MUST be impounded and cannot be waived (even if taxes/hazard are waived). All T&I due within 60 days of closing must be paid at closing.",
         "suggestion": "Do not waive flood escrow in a flood zone."},
    ])
    return make_command(tool_call_id, "Aggregate escrow setup guidance raised.", flags=flags)
