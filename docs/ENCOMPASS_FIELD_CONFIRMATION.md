# Encompass Field / Milestone / Status Confirmation Checklist

Before turning `dry_run` off (real writes), confirm the following against the target
Encompass instance. IDs/names marked **PLACEHOLDER** or **UNCONFIRMED** are best-effort
and will write to the wrong place — or fail — until verified.

How to verify a field ID quickly (read-only):

```bash
python3.11 -c "
import sys; sys.path.insert(0,'.'); sys.path.insert(0,'output')
from dotenv import load_dotenv; load_dotenv('.env')
import logging; logging.disable(logging.CRITICAL)
from encompass_client import get_encompass_client
c = get_encompass_client(env='TEST')
loan_id='<LOAN_GUID>'
for fid in ['762','742','740','2553']:
    print(fid, '=', c.read_fields(loan_id,[fid]).get(fid))
"
```

---

## 1. Field IDs — WRITES (must be exact)

| Purpose | Tool | Current ID | Status |
|---------|------|-----------|--------|
| Estimated Closing Date | `validate_ecd` (1.4) | `763` | ✅ confirmed (reads back a date) |
| Lender loan number (NDC) | `update_loan_number` (11.2) | `305` | ✅ confirmed — Job Aid names field 305 = URLA Loan Identifier (URLA Lender screen) |
| DFT reason | `submit_dft` (1.3) | `CX.DFT.REASON` | ❌ **PLACEHOLDER** — get the real DFT Form radio/reason field ID(s) |
| Cond's Ready for Review checkbox | `mark_not_ready_for_resubmission` (4.7) | `CX.TPO.CONDS.READY` | ❌ **PLACEHOLDER** — get the TPO Information "Cond's Ready for Review" field ID |
| TPO Submission Date | (read, `review_suspense` timeline) | `CX.TPO.SUBMISSION.DATE` | ❌ **PLACEHOLDER** — currently we use `3142` (Initial Submittal Date) instead; confirm which the SOP means |
| CTC Audit Request checkbox | `request_ctc_audit` (14.1) | `CX.CTC.AUDIT.REQUESTED` | ❌ **PLACEHOLDER** — 3rd Party Tracking "CTC Audit Request" box (value `"Y"`?) |
| CTC Audit review comments | `request_ctc_audit` (14.1) | `CX.CTC.AUDIT.NOTES` | ❌ **PLACEHOLDER** — 3rd Party Tracking audit comments |
| CTC Review checkbox | `submit_ctc_review` (14.2) | `CX.CTC.REVIEW` | ❌ **PLACEHOLDER** — Loan Notes "CTC Review" box (value `"Y"`?) |
| CTC Audit # of defects (read) | `submit_ctc_review` gate (14.2) | `CX.CTC.AUDIT.DEFECTS` | ❌ **PLACEHOLDER** — used to auto-derive a clear audit |
| CTC Audit status (read) | `submit_ctc_review` gate (14.2) | `CX.CTC.AUDIT.STATUS` | ❌ **PLACEHOLDER** — used to auto-derive a clear audit |

## 2. Field IDs — READS (confirm they map correctly)

| Key | ID | Status |
|-----|-----|--------|
| loan_number `364`, borrower `4000/4002`, purpose `19`, amount `1109`, type `1172` | — | ✅ confirmed |
| occupancy `1811`, property street/city/state/zip `11/12/14/15` | — | ✅ confirmed (read real values) |
| estimated_closing_date `763`, initial_submittal_date `3142`, disbursement_date `2553` | — | ✅ confirmed |
| current_milestone `MS.STATUS` | — | ✅ confirmed (reads `Conds in Review/CTC`) — replaced invalid `MSTAT.X44` that was breaking the bulk read |
| lock_expiration_date `762` | — | ✅ correct field (empty when unlocked) |
| dti_total `742`, housing_ratio `740` | — | ✅ correct fields (empty until ratios calculated) |
| property_units `16` (`review_secondary_appraisal` 8.2) | — | ✅ confirmed (reads # units) |
| property_type `1041` (8.2) | — | ✅ confirmed (reads subject property type, e.g. PUD) |
| fnma_ssr_score `CX.SSRSCOREFNMA` (8.2) | — | ✅ confirmed valid (SSR Score FNMA; empty until an SSR is on file). FHLMC = `CX.SSRSCOREFHLMC` |
| dscr_current `CX.DEBTSERVICECOVERAGERATIO` (11.1) | — | ✅ confirmed valid (DSCR; reads `0` on non-DSCR loans) |
| Doc Expiration — Credit `Document.ExpirationDate.CREDIT REPORT` (13.1) | — | ✅ confirmed valid eFolder tracking field |
| Doc Expiration — Appraisal `Document.ExpirationDate.APPRAISAL` (13.1) | — | ✅ confirmed valid |
| Doc Expiration — Flood `Document.ExpirationDate.FLOOD CERTIFICATE` (13.1) | — | ✅ confirmed valid |
| Doc Expiration — Title `Document.ExpirationDate.TITLE REPORT` (13.1) | — | ✅ confirmed valid |
| Initial LE Received `3153` (`review_les` 7.2) | — | ✅ confirmed valid ("LE Intl TIL Disclosure Rcvd Date") |
| CD Received/Executed `3978` (`review_icd` 7.3) | — | ✅ confirmed valid ("Closing Disclosure Received Date"); revised CD = `3980` |
| **GAPS — no confirmed field in catalog** (tools degrade to advisory): | | |
| cda_ordered_date / cda_received_waived (8.2) | — | ❌ no CDA/Collateral-Desk field found — instance-specific NonQM v2 custom field, or track via condition |
| dti_at_lock / dscr_at_lock (11.1) | — | ❌ no UW Lock Compare "on lock" snapshot field found — variance stays advisory |
| Doc Expiration — Income/Asset/VVOE/CPL/Credit-Refresh (13.1) | — | ❌ no `Document.ExpirationDate.<name>` entry in this instance's eFolder config |
| ctc_audit_defects / ctc_audit_status (14.2) | — | ❌ unconfirmed — prefunding-QC candidates `CX.QCAUDITCOMPLETE` / `CX.QCAUDITFINDINGS` exist but mapping to RM "CTC Audit" not verified |

## 3. Milestone names (must match Encompass exactly)

| Used by | Milestone string | Status |
|---------|-----------------|--------|
| `resubmit_to_uw` (4.6), `receive_appraisal` (8.1), `submit_ctc_review` (14.2) | `"TPO Cond Submitted"` | ⚠️ **UNCONFIRMED** — verify exact spelling/casing via `GET /loans/{id}/milestones` |

Verify milestone names:

```bash
python3.11 -c "
import sys; sys.path.insert(0,'.'); sys.path.insert(0,'output')
from dotenv import load_dotenv; load_dotenv('.env')
import logging; logging.disable(logging.CRITICAL)
from encompass_client import get_encompass_client
c=get_encompass_client(env='TEST')
for m in c.get_milestones('<LOAN_GUID>'):
    print(m.get('milestoneName') or m.get('name'), '->', m.get('id'))
"
```

## 4. Condition status verbs (must match Encompass condition workflow)

| Used by | Values written | Status |
|---------|---------------|--------|
| `update_condition_statuses` (4.4), `request_appraisal_corrections` (8.3) | `Cleared` / `Reviewed` / `Requested` (re-requested) | ⚠️ **UNCONFIRMED** — confirm the exact status strings the underwritingConditions API accepts |

Condition description edit format (per SOP): `**Rev MM/DD Initials –** ...` (do not edit UW verbiage).

## 5. Conversation log

`add_conversation_log_note` posts to `/loans/{id}/conversationLog`. ⚠️ Confirm the endpoint
shape/permissions on your instance; requires a user-context token for proper attribution.

## 6. eFolder document coverage (STEP_00 `fetch_doc_fields`)

Extracted via the EfolderConnect service (`EFOLDER_API_BASE_URL` / `EFOLDER_API_TOKEN`,
client id derived from `ENCOMPASS_ENV`). Doc types requested:

`Evidence of Insurance`, `Flood Insurance`, `Flood Certificate`, `Title Report`,
`Closing Protection Letter`, `Appraisal Report`, `Compliance Report`, `1003 URLA`,
`Credit Report`, `Tax Summary`, `Loan Estimate`, `Closing Disclosure`, `Approval Form`.

⚠️ Confirm the service's `ExtractedFields` keys per doc type so the verification tools can
compare specific values (currently they check document presence + expose raw extracted
fields under `state["efolder_documents"]` / namespaced `state["doc_fields"]`).

## 7. Auth note

`.env` has TEST client_id/secret/instance but no `TEST_ENCOMPASS_USERNAME` /
`_PASSWORD` / `_SUBJECT_USER_ID`. Auth falls back to **client_credentials** (integration
token). Reads work; user-attributed writes typically need the password-grant +
impersonation path — add those before enabling real writes.
