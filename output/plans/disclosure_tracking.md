# Step 7: Disclosure Tracking (Wholesale Only)

Access Disclosure Tracking (Tools / Disclosure Tracking). A populated received date
indicates the disclosure was fully executed and returned.

## Important Rules
- Wholesale TRID: ICD must be executed prior to CTC and at least 3 days prior to the ECD.
- On rescindable transactions, non-borrowing spouses & title owners must execute the ICD.

## Substeps

### 7.1 — Broker Fee Agreements
Call `review_broker_fee_agreements`. CA/DE/IL require an executed Broker Fee Agreement.

### 7.2 — Initial & Locked LEs
Call `review_les`. Initial LE executed by all parties (all loan types) → clear the
condition. TRID: locked LE executed by all parties. Non-TRID: locked LE delivered
(need not be executed).

### 7.3 — Initial Closing Disclosures
Call `review_icd`. Loans drop into the ICD queue when approved & locked, appraisal
cleared, and the broker ICD form is uploaded to WS-Closing Condition (cleared if
owner-occupied; waived if business purpose). Verify all ICD terms match Encompass
(rate, LTV, fees, 3rd-party fees). 3rd-party processing fee → pull NMLS data and
upload. POA → confirm the PTC POA condition.
