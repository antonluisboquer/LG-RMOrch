# Step 8: Appraisals

Verify received appraisals and the secondary-appraisal requirement within Encompass,
and handle the in-Encompass slivers of corrections and disaster inspections.

> The primary actions for ordering (TPO Portal), corrections/transfers, and disaster
> inspections are emails to the NQMF appraisal desk and ValueLink look-ups — those are
> external and handled outside this workflow. Only the RM's in-Encompass actions
> (condition status, conversation-log notes, milestone completion, field verification)
> are modeled here.

## Substeps

### 8.1 — Receipt of the Appraisal
Call `receive_appraisal`. Confirm the appraisal property address AND borrower name(s)
match Encompass exactly. When the Appraisal Report is in the eFolder, the extracted
address/borrower are compared automatically (mismatches raise a critical flag and
block resubmission). Once verified, finish TPO Cond's Submitted to resubmit — set
`options.appraisal_received=true` to complete the milestone (dry-run gated).

### 8.2 — Secondary Appraisal Reviews
Call `review_secondary_appraisal`. Reads the FNMA SSR score, # units / property type,
and the NonQM v2 CDA Ordered / CDA Received-Waived fields to determine the requirement:
SSR ≤ 2.5 → not required; SSR > 2.5 or 1–4 unit w/o SSR → CDA; Mixed Use / 5+ unit →
BPO; not required when 2 appraisals are on file. Verifies the CDA Ordered date (when
required) or the CDA Received/Waived field (when waived).

### 8.3 — Appraisal Corrections
Call `request_appraisal_corrections`. Surfaces appraisal correction/update conditions.
The correction request itself is an email to `appraisaldesk@nqmf.com` (wholesale,
NQMF-ordered only; transferred appraisals go through the prior lender). Set
`options.appraisal_correction_requested=true` to mark matching conditions **Requested**
and add a conversation-log note (dry-run gated).

### 8.4 — Disaster Inspections
Call `review_disaster_inspection`. Verifies whether UW has added a disaster/inspection
condition (required when a FEMA-declared disaster affects the property after the
appraisal date). Requesting the inspection is an email to `appraisaldesk@nqmf.com`
(external).
