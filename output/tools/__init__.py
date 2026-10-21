"""Tools package — all tool imports and registration.

Each substep tool lives in a step file. The workflow covers the RM Job Aid steps
whose actions are contained within Encompass (read/verify fields, conditions,
milestones, condition statuses, conversation-log notes, Encompass screens/forms
such as Non-QM v2, 2nd Level Review, Rush Request, Condo Review, and the 3rd Party
Order Tracking screen). For each substep, only the RM's in-Encompass actions are
modeled; the external/inbound parts (emailing/calling parties, and the actual
ordering on outside sites like CIC/MeridianLink/Property Guard, or desk decisions)
are excluded and surfaced as reminders.

Advisory tools encode the job-aid checklists as review flags; action tools perform
dry-run-gated writes / milestone completions / condition updates.
"""

# General tools (always available)
from .general import write_todo, get_workflow_status, save_step_report

# STEP_00: Data Gathering
from .data_gathering import find_loan, fetch_rm_fields, fetch_doc_fields

# STEP_01: Pipeline Management
from .pipeline_management import (
    review_duties,
    record_file_touch,
    submit_dft,
    validate_ecd,
)

# STEP_02: Initial & Updated Underwriting Decisions
from .uw_decisions import review_approval, review_suspense

# STEP_03: Loan Requests
from .loan_requests import submit_exception, submit_rush_request, submit_condo_review

# STEP_04: Conditions Queue
from .conditions_queue import (
    check_condition_sla,
    identify_open_conditions,
    review_condition_documentation,
    update_condition_statuses,
    check_unassigned_documents,
    resubmit_to_uw,
    mark_not_ready_for_resubmission,
)

# STEP_05: Taxes & Insurance
from .taxes_insurance import (
    review_hazard_flood_insurance,
    review_property_taxes,
    update_itemization,
    update_aggregate_escrow,
)

# STEP_06: Document Reviews
from .document_reviews import (
    review_signed_1003,
    review_credit_reports,
    review_preliminary_title,
    review_cpl,
    review_eo_wiring,
    review_payoff_statements,
)

# STEP_07: Disclosure Tracking (Wholesale)
from .disclosure_tracking import (
    review_broker_fee_agreements,
    review_les,
    review_icd,
)

# STEP_08: Appraisals
from .appraisals import (
    receive_appraisal,
    review_secondary_appraisal,
    request_appraisal_corrections,
    review_disaster_inspection,
)

# STEP_09: Third Party Orders (Wholesale)
from .third_party_orders import (
    order_credit_refresh,
    order_credit_supplement,
    order_ssa_verification,
    order_tax_transcripts,
    order_vvoe,
    validate_str_permit,
    verify_pl,
)

# STEP_10: Mavent (Wholesale)
from .mavent import review_mavent

# STEP_11: Locked Loans
from .locked_loans import review_lock, update_loan_number

# STEP_12: File Contacts (Wholesale)
from .file_contacts import verify_file_contacts

# STEP_13: NonQM - Document Expirations
from .document_expirations import verify_document_expirations

# STEP_14: Prepare the File for Closing
from .prepare_for_closing import request_ctc_audit, submit_ctc_review, ctc_final_steps


def get_all_tools() -> list:
    """Return all implemented tool functions."""
    return [
        # General
        write_todo,
        get_workflow_status,
        save_step_report,
        # STEP_00: Data Gathering
        find_loan,
        fetch_rm_fields,
        fetch_doc_fields,
        # STEP_01: Pipeline Management
        review_duties,
        record_file_touch,
        submit_dft,
        validate_ecd,
        # STEP_02: UW Decisions
        review_approval,
        review_suspense,
        # STEP_03: Loan Requests
        submit_exception,
        submit_rush_request,
        submit_condo_review,
        # STEP_04: Conditions Queue
        check_condition_sla,
        identify_open_conditions,
        review_condition_documentation,
        update_condition_statuses,
        check_unassigned_documents,
        resubmit_to_uw,
        mark_not_ready_for_resubmission,
        # STEP_05: Taxes & Insurance
        review_hazard_flood_insurance,
        review_property_taxes,
        update_itemization,
        update_aggregate_escrow,
        # STEP_06: Document Reviews
        review_signed_1003,
        review_credit_reports,
        review_preliminary_title,
        review_cpl,
        review_eo_wiring,
        review_payoff_statements,
        # STEP_07: Disclosure Tracking
        review_broker_fee_agreements,
        review_les,
        review_icd,
        # STEP_08: Appraisals
        receive_appraisal,
        review_secondary_appraisal,
        request_appraisal_corrections,
        review_disaster_inspection,
        # STEP_09: Third Party Orders
        order_credit_refresh,
        order_credit_supplement,
        order_ssa_verification,
        order_tax_transcripts,
        order_vvoe,
        validate_str_permit,
        verify_pl,
        # STEP_10: Mavent
        review_mavent,
        # STEP_11: Locked Loans
        review_lock,
        update_loan_number,
        # STEP_12: File Contacts
        verify_file_contacts,
        # STEP_13: Document Expirations
        verify_document_expirations,
        # STEP_14: Prepare for Closing
        request_ctc_audit,
        submit_ctc_review,
        ctc_final_steps,
    ]


__all__ = [
    "get_all_tools",
    "write_todo", "get_workflow_status", "save_step_report",
    "find_loan", "fetch_rm_fields", "fetch_doc_fields",
    "review_duties", "record_file_touch", "submit_dft", "validate_ecd",
    "review_approval", "review_suspense",
    "submit_exception", "submit_rush_request", "submit_condo_review",
    "check_condition_sla", "identify_open_conditions", "review_condition_documentation",
    "update_condition_statuses", "check_unassigned_documents", "resubmit_to_uw",
    "mark_not_ready_for_resubmission",
    "review_hazard_flood_insurance", "review_property_taxes", "update_itemization",
    "update_aggregate_escrow",
    "review_signed_1003", "review_credit_reports", "review_preliminary_title", "review_cpl",
    "review_eo_wiring", "review_payoff_statements",
    "review_broker_fee_agreements", "review_les", "review_icd",
    "receive_appraisal", "review_secondary_appraisal",
    "request_appraisal_corrections", "review_disaster_inspection",
    "order_credit_refresh", "order_credit_supplement", "order_ssa_verification",
    "order_tax_transcripts", "order_vvoe", "validate_str_permit", "verify_pl",
    "review_mavent",
    "review_lock", "update_loan_number",
    "verify_file_contacts",
    "verify_document_expirations",
    "request_ctc_audit", "submit_ctc_review", "ctc_final_steps",
]
