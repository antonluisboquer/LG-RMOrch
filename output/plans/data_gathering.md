# Step 0: Data Gathering

Establish the loan context all downstream RM steps depend on.

## Substeps

### 0.1 — Find Loan
Call `find_loan` to resolve the loan GUID from the loan number. The GUID is stored
in `state['loan_id']` for every later tool.

### 0.2 — Fetch RM Fields
Call `fetch_rm_fields` to batch-read the RM-relevant Encompass fields (loan number,
borrower, purpose, amount, occupancy, property address, DTI/housing ratio, Estimated
Closing Date, initial submittal date, disbursement date, current milestone, lock
expiration) into `state['los_fields']` and build a small `state['loan_profile']`
(purpose, is_refinance, state, occupancy, address, ratios). Report how many fields
were found.

### 0.3 — Fetch eFolder Document Fields
Call `fetch_doc_fields` to extract the RM document set from the loan eFolder
(cache-first via the EfolderConnect service; re-extracts only when the cache is empty
or `force_extract` is set). Populates `state['efolder_documents']` (per-doc inventory
with status and extracted fields) and `state['doc_fields']` (namespaced extracted
values, e.g. `evidence_of_insurance.expiration_date`). Downstream verification steps
(Taxes & Insurance, Document Reviews, Appraisals, Mavent, Disclosure Tracking) use
this to check document presence and compare real values instead of only restating the
checklist. Report how many of the requested docs were found and any that are missing.
