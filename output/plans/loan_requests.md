# Step 3: Loan Requests

Submit the internal loan reviews the transaction needs. Only the in-Encompass RM
actions are modeled here.

> External / inbound parts are out of scope: discussing the request with the UW,
> the Exception/Condo Desk decisions + their uploads/conditions, and emailing the
> rush request to the pipeline managers. Custom-form field IDs used below are
> placeholders pending confirmation (see docs/ENCOMPASS_FIELD_CONFIRMATION.md).

## Substeps

### 3.1 — Exceptions
Call `submit_exception`. An exception condition is added by UW after initial
review; the RM submits the request. The tool verifies an exception condition is on
the file and that 2+ compensating factors are provided, then (when
`options.submit_exception=true` with `options.exception_type` and
`options.exception_summary`) fills the Non-QM v2 Exception Tracking fields and the
2nd Level Review form (Type of Review = Exception, Underwriter's Findings =
date/initials/summary) and submits for review. If the loan is not locked, it
reminds the RM to ensure the exception LLPA is applied at lock.

### 3.2 — Closing Rush Requests
Call `submit_rush_request`. Rush approvals are emailed to the pipeline managers
(external). In Encompass the RM only *populates* the Rush Request Form — "add in
information only", do NOT click Submit for Review. The tool checks the CTC-audit-
clear requirement and the timing rule (docs needed < 2 days after CTC, < 3 for TX)
and writes the rush reason + Title/Attorney availability when
`options.rush_reason` is provided.

### 3.3 — Condo Reviews
Call `submit_condo_review`. Condo project approval runs through the NQM Condo Desk
and is initiated once the Master Insurance Policy and HOA Questionnaire are
received (supporting docs in the eFolder Condo Conditions). The tool checks those
prerequisites and, when `options.submit_condo_review=true` with
`options.condo_notes`, enters the Condo Review notes and submits to initiate the
review.
