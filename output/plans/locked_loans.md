# Step 11: Locked Loans

Review the lock, ensure it expires after disbursement, and validate lock-vs-current
variances against tolerances.

## Important Rules
- The lock must expire AFTER the disbursement date (Processing Summary).
- Notify Broker/AE/SA when the lock is close to expiring.
- Variances outside tolerance require the AE/SA to adjust pricing.

## Substeps

### 11.1 — Lock Expiration & Variance Review
Call `review_lock`. Compares the lock expiration to the disbursement date (lock must
expire AFTER disbursement) and evaluates the UW Lock Compare variance from the read
fields: **Non-DSCR** — final DTI ≤ 43% (or DTI at lock > 43%) is within tolerance;
**DSCR** — current DSCR must stay in the same lock band (>1.24; 1–1.14; .75–1; <.75).
DSCR loans are detected via `options.is_dscr` or the presence of DSCR values. Out-of-
tolerance variances raise a warning to contact the AE/SA for repricing. Credit score /
program / amortization comparisons remain advisory.

### 11.2 — Loan Number Update (NDC only)
Call `update_loan_number`. For NDC clients requesting a lender loan number update, write
URLA Lender field 305. Provide `options.new_loan_number` (dry-run gated).

> Loan program changes are excluded from this workflow — they follow an external
> procedure (TPO Program Changes Procedure.pdf) rather than an Encompass action.
