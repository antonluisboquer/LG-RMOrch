# Step 9: Third Party Orders (Wholesale Only)

Does not apply to Correspondent files. The RM initiates and manages orders via the
3rd Party Order Tracking screen in Encompass; the internal team places the actual
orders on the external sites.

> Out of scope: the actual CIC / MeridianLink / Property Guard ordering and broker
> outreach. Custom-form and Document-Expiration field IDs used below are
> placeholders pending confirmation (see docs/ENCOMPASS_FIELD_CONFIRMATION.md).

## Substeps

### 9.1 — Credit Refresh
Call `order_credit_refresh`. Review the refresh (no new debt → submit to UW;
balances/payments not increased → update amount; no new inquiries → LOX). Mark the
refresh condition **Reviewed** (not Cleared) so UW re-confirms guidelines, update
the **Credit Refresh date** on the Doc Expiration screen, and upload the invoice.
Options: `credit_refresh_reviewed`, `credit_refresh_date`.

### 9.2 — Credit Supplement
Call `order_credit_supplement`. Set the supplement condition to **Requested** while
waiting; when received, mark **Ready for UW** and resubmit (complete the TPO
Conditions received milestone). Judgment: don't submit to TPO Conditions if the
supplement is the only open condition with no derogatory history (unless it's the
last prior-to-doc condition). Option: `supplement_received`.

### 9.3 — SSA Verifications
Call `order_ssa_verification`. Reference # = NQMF Loan Number. On a positive SSN
match, share/print and upload. If no match, an **SS-89** is required — verify it was
signed during disclosure, otherwise obtain it. Option: `ssa_match`.

### 9.4 — Tax Transcripts
Call `order_tax_transcripts`. On the 3rd Party Order screen (4506C / transcript
box) click **Requested** to prep the form; get broker signatures (external), then
click **Form Ready**. Options: `transcripts_requested`, `transcripts_form_ready`.

### 9.5 — Verbal Verification of Employment (VVOE)
Call `order_vvoe` (not DSCR). Review the VVOE effective date, enter it on the Doc
Expiration screen, confirm actively employed, and verify employment dates against
URLA Page 2. Option: `vvoe_date`.

### 9.6 — Short Term Rental Permit Validation
Call `validate_str_permit`. Review the Property Guard findings; mark the STR
condition **Reviewed** and resubmit to UW (UW validates on NonQM v2). If not
compliant, resubmit immediately. Option: `str_reviewed`.

### 9.7 — P&L Verification (P&L Only loans)
Call `verify_pl`. Ensure there are **no open P&L conditions** before requesting the
verbal verification, so the verification is accurate.
