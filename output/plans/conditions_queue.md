# Step 4: Conditions Queue

Review and manage all open conditions, then resubmit to UW when warranted.

## Important Rules
- Categorize by 'Prior to': PTA (suspended) and PTD (approved, not CTC) require
  resubmission once received; PTC/PTP do not.
- LC conditions → 'Cleared' when met; all others → 'Reviewed'. Deficient LC
  conditions → 're-requested' with an updated description (**Rev MM/DD Initials –**).
- Only resubmit to UW when warranted — typically ≥5 UW conditions, or an appraisal
  (appraisal warrants an immediate resubmit).
- The unassigned folder should hold nothing but the CTC Audit Checklist.

## Substeps

### 4.1 — Service Level Agreement (SLA)
Call `check_condition_sla` to surface fulfilled conditions awaiting review and the
SLA (before 2pm → same day; after 2pm → noon next business day).

### 4.2 — Identify & Manage Open Conditions
Call `identify_open_conditions` to list open conditions bucketed by PTA/PTD/PTC/PTP.

### 4.3 — Review Documentation
Call `review_condition_documentation` to review fulfilled conditions against NQMF
guidelines (advisory).

### 4.4 — Update Condition Statuses
Call `update_condition_statuses`. Applies `options.condition_updates`
(`[{id,status,description}]`) to set cleared/reviewed/re-requested statuses (dry-run
gated). With no updates supplied, it lists candidates.

### 4.5 — Unassigned Documents
Call `check_unassigned_documents` to verify the unassigned eFolder is clean.

### 4.6 — Re-Submit to UW
Call `resubmit_to_uw` to complete the "TPO Cond Submitted" milestone when warranted
(≥5 conditions, appraisal received, or `options.allow_resubmit=true`). Dry-run gated.

### 4.7 — Loans not ready for UW Resubmission
Call `mark_not_ready_for_resubmission` to uncheck "Cond's Ready for Review" on the
TPO Information page when conditions do not warrant a resubmit
(`options.mark_not_ready=true`). Dry-run gated.
