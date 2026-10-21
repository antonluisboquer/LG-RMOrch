"""STEP_12: File Contacts (Wholesale Only).

12.1 verify_file_contacts — verify Encompass File Contacts are complete & accurate.
"""

import logging
from typing import Annotated

from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from ._helpers import _profile, make_command, doc_field

logger = logging.getLogger(__name__)


def _channel(state: dict) -> str:
    options = state.get("options") or {}
    ch = str(options.get("channel") or "").strip().lower()
    return ch if ch in ("wholesale", "ndc", "correspondent") else "unknown"


@tool
def verify_file_contacts(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Verify Encompass File Contacts are complete and accurate (Wholesale).

    Access Tools → File Contacts and confirm each required contact's data. Where the
    relevant document is in the eFolder, the extracted values (insurance policy
    details, appraiser info) are surfaced to help verify the contact entries match.
    """
    channel = _channel(state)
    flags = []

    if channel not in ("wholesale", "unknown"):
        flags.append({"substep": "12.1", "title": "File Contacts review is Wholesale-only", "severity": "info",
                      "details": f"This file's channel is '{channel}'; the File Contacts review is a Wholesale-only RM step.",
                      "suggestion": "Skip File Contacts verification for non-Wholesale files."})
        return make_command(tool_call_id, "File contacts skipped (non-Wholesale).", flags=flags)

    is_purchase = "purchase" in (_profile(state, "purpose") or "").lower()

    flags.append({"substep": "12.1", "title": "Core file contacts", "severity": "info",
                  "details": (
                      "Title insurance company: company name, address, title, case #, officer name, title, email, phone, NMLS & license #. "
                      "Escrow company (if applicable): company name, address, escrow case #, officer name, phone, email, NMLS & license #. "
                      "Settlement agent: company name, address, officer name, phone, email, NMLS & license #."
                  ),
                  "suggestion": "Complete every required field for each contact."})

    # ── Homeowners & Flood insurance contact — enrich from extracted docs ──
    policy = doc_field(state, "evidence_of_insurance", "policy_number") or doc_field(state, "flood_insurance", "policy_number")
    coverage = doc_field(state, "evidence_of_insurance", "dwelling_coverage", "hazard_insurance_coverage")
    premium = doc_field(state, "evidence_of_insurance", "total_policy_premium", "hazard_insurance_premium")
    deductible = doc_field(state, "evidence_of_insurance", "deductible")
    renewal = doc_field(state, "evidence_of_insurance", "coverage_end_date", "expiration_date")
    ins_bits = [b for b in [
        f"policy #: {policy}" if policy else None,
        f"coverage: {coverage}" if coverage else None,
        f"premium: {premium}" if premium else None,
        f"deductible: {deductible}" if deductible else None,
        f"renewal/expiration: {renewal}" if renewal else None,
    ] if b]
    if ins_bits:
        flags.append({"substep": "12.1", "title": "Insurance contact — extracted values", "severity": "info",
                      "details": "From the insurance doc(s): " + "; ".join(ins_bits) + ".",
                      "suggestion": "Confirm the File Contacts insurance entry matches these extracted values."})
    else:
        flags.append({"substep": "12.1", "title": "Homeowners & Flood insurance contact", "severity": "info",
                      "details": "Agent info, policy #, coverage amount, premium, renewal date & deductible.",
                      "suggestion": "Complete the insurance contact; no insurance doc values were extracted to cross-check."})

    # ── Appraiser contact — enrich from extracted appraisal ──
    appr_name = doc_field(state, "appraisal_report", "appraiser_name", "appraiser")
    appr_license = doc_field(state, "appraisal_report", "appraiser_license", "license_number", "license")
    appr_company = doc_field(state, "appraisal_report", "appraisal_company", "company_name", "company")
    appr_bits = [b for b in [
        f"name: {appr_name}" if appr_name else None,
        f"license #: {appr_license}" if appr_license else None,
        f"company: {appr_company}" if appr_company else None,
    ] if b]
    if appr_bits:
        flags.append({"substep": "12.1", "title": "Appraiser contact — extracted values", "severity": "info",
                      "details": "From the Appraisal Report: " + "; ".join(appr_bits) + ".",
                      "suggestion": "Confirm the File Contacts appraiser entry matches these extracted values."})
    else:
        flags.append({"substep": "12.1", "title": "Appraiser contact", "severity": "info",
                      "details": "Appraiser name, license number & company name.",
                      "suggestion": "Complete the appraiser contact; no appraisal values were extracted to cross-check."})

    if is_purchase:
        flags.append({"substep": "12.1", "title": "Purchase-only contacts", "severity": "warning",
                      "details": "Buyer & Seller's agents: company name, company license #, agent name, agent license #, agent email, agent phone. Seller: include all data points.",
                      "suggestion": "Complete buyer/seller agent and seller contact data for purchases."})

    return make_command(tool_call_id, "File contacts verified (checklist + extracted cross-checks).", flags=flags)
