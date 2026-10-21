# Step 1: Pipeline Management

Pipeline management is the RM's core responsibility: keep every file progressing
toward closing, keep ECDs accurate, and cancel dead files.

## Important Rules
- Touch each file at least once every 3 days; record the touch in the Roadmap &
  Conversation Log.
- ECDs must be accurate: Purchase = purchase-contract closing date; Refinance =
  ~30 days out unless closing sooner. Set stagnant/dead/new-construction files to 12/31.
- Cancelling a loan (DFT) is destructive — only the RM/authorized run should submit it.

## Substeps

### 1.1 — Duties
Call `review_duties` to inspect the loan's milestone, ECD, and lock, and raise a
monitoring checklist (new/updated approvals, ECDs, SLAs, DFT candidates). Advisory
only — no writes.

### 1.2 — File Touches
Call `record_file_touch` to log a file touch in the Conversation Log documenting the
current status. Dry-run gated.

### 1.3 — Cancelling Loans / Submitting for DFT
Call `submit_dft`. This is DESTRUCTIVE and guarded: it only submits when
`options.allow_dft = true` and `options.dft_reason` is provided. Otherwise it raises
an advisory recommendation.

### 1.4 — ECD Validation & Updates
Call `validate_ecd` to validate the Estimated Closing Date against SLA. If
`options.target_ecd` (MM/DD/YYYY) is provided, it writes the new ECD (dry-run gated);
otherwise it validates and flags.
