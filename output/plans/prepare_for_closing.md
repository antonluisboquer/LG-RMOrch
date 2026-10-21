# Step 14: Prepare the File for Closing

Once all conditions are reviewed and all tasks completed, submit the loan for CTC.

## Important Rules
- Loans cannot be submitted to CTC without a **clear** CTC audit.
- The CTC Review checkbox is unavailable until a clear audit is completed.

## Substeps

### 14.1 — CTC Audits
Call `request_ctc_audit`. The offshore team audits each file before final UW submission.
Reports any existing CTC audit result (status / # of defects). Request via 3rd Party
Tracking only when the loan is truly ready for a Final CTC (refer to the Wholesale/NDC QC
Audit Checklist). Set `options.request_ctc_audit=true` to check the CTC Audit Request box
and log the initiation (dry-run gated); pass `options.ctc_review_notes` for the comments.

### 14.2 — Submit to UW for CTC Review
Call `submit_ctc_review`. Completes the TPO Conds Submitted milestone and checks the CTC
Review box (Loan Notes). Requires `options.submit_ctc=true`; the clear-audit gate is
**auto-derived** from the CTC audit fields (# of defects == 0 / status) and can be
overridden with `options.ctc_audit_clear`. Blocked (critical) if the audit isn't clear.
Dry-run gated.

### 14.3 — CTC Final Steps (Wholesale Only)
Call `ctc_final_steps`. Auto-skips non-Wholesale files. Confirm closing date/time
(Processor Summary), verify the final ECD is within the NQMF closing SLA (rush if needed),
note POA/mail-away in Notes to the Closer (POA conditions are auto-detected), honor the TX
owner-occupied cash-out final-CD-one-day-prior rule (data-driven on state/occupancy/
purpose), and generate the Closing Validation Form for TPO contacts to verify.
