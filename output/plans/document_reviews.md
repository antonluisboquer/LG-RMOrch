# Step 6: Document Reviews

Review the loan's core documents against NQMF standards before submission/closing.

## Important Rules
- Mortgagee clause is state-specific (NY vs all other states; ISAOA/ATIMA not required
  for TX). Wholesale requires the NQMF clause; Correspondent uses lender name/address.
- CPL and E&O do not apply to Correspondent loans.
- Payoff review applies only to refinances paying off existing liens.

## Substeps

### 6.1 — Broker / Lender Signed 1003
Call `review_signed_1003`. Confirm a wet signature or e-sign certification. Wholesale:
ensure the signed application is the NQMF application.

### 6.2 — Credit Reports
Call `review_credit_reports`. Verify a new report was re-issued via the TPO Portal
(compare Credit Ref# in Encompass vs the report). Notify UW via conversation log,
confirm all debts pulled through, and check DTI against the program maximum.

### 6.3 — Preliminary Title
Call `review_preliminary_title`. Verify the mortgagee clause, borrower/entity per
vesting, lender coverage ≥ loan amount, and Title Effective Date within 90 days of
closing (matching the doc-expiration screen).

### 6.4 — CPL (Closing Protection Letter)
Call `review_cpl`. Verify clause, correct NQMF loan number, vesting, agent name matches
title commitment & E&O, unexpired with effective date within 60 days of closing.

### 6.5 — E&O & Wiring Instructions
Call `review_eo_wiring`. E&O minimum $1M ($500K attorney), not expired, agent matches
CPL/title. Wire beneficiary matches the agent on the title commitment.

### 6.6 — Payoff Statement(s)
Call `review_payoff_statements`. (Refi only.) Payoff not expired and matches Encompass
dates, per-diem interest reflected, mortgage current (≤30 days past due), and the
payoff amount covers per-diem through disbursement.

> NY closing-attorney verification is excluded from this workflow — it relies on an
> external approved-attorney list and a compliance submission outside Encompass.
