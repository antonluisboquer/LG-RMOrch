# RM Job Aid — SOP Coverage Gaps

Running list of gaps found while auditing each Job Aid section against the
implemented tools. These are the items to build/fix in a single pass. External
actions (emailing/calling parties, outside portals) are intentionally excluded
and are **not** listed as gaps.

Legend: ✅ integrated · ⚠️ partial · ❌ not integrated (in-Encompass gap)

---

## Step 1 — Pipeline Management

- ⚠️ **DFT form is incomplete** (`1.3 submit_dft`). Currently writes only
  `FieldIds.DFT_REASON = CX.DFT.REASON` (**PLACEHOLDER**). Missing:
  - Processor Details radio buttons: Borrower Cancelled / No Borrower Response /
    Critical Deal Changes / Low Value / Income (can't doc/source) / Assets /
    Drop in FICO Score.
  - Contact method: In e-mail / Over Phone / Letter or signed RTC.
  - Last Contact Attempt Date field.
  - Click **"Submit for Review"** (milestone / pipeline move to UW).
  - Add the required **Conversation Log note** with DFT details.
  - → Need real field IDs for all DFT form fields + the submit action.
- ⚠️ **File Touch writes Conversation Log but not the Roadmap Summary**
  (`1.2 record_file_touch`). Job aid says record in **Roadmap & Conversation
  Log**. Need the Roadmap Summary field/entry write.
- ⚠️ **Stagnant-file ECD → 12/31 rule not auto-applied** (`1.4`). Only mentioned
  as a suggestion. Could auto-set ECD to 12/31 for stagnant/dead/new-construction
  files (needs a "stagnant" signal).
- ✅ **Purchase ECD data-driven** (`1.4 validate_ecd`). `Purchase Agreement` added to
  the eFolder doc set; when present, the extracted contract closing date is compared to
  the ECD and a mismatch is flagged. (Depends on the Purchase Agreement extraction keys.)
- ❌ **COCs** — no dedicated check anywhere.
- ❌ **Reg B monitoring** — no explicit adverse-action / ECOA timer.
- ❌ **Pipeline Trending** (files → CTC for the week) — portfolio-wide metric;
  out of scope for a per-loan agent (confirm whether wanted).

## Step 2 — Initial & Updated Underwriting Decisions

- ⚠️ **Decision doc type mismatch** (`2.1 review_approval`). We check
  `Approval Form` presence; the job aid/eFolder shows the decision imaged as
  **"Underwriting Decision"**. Confirm the correct eFolder doc type name and add/
  rename in `RM_DOCUMENT_TYPES`.
- ⚠️ **Initial Submittal Date field unconfirmed** (`2.2 review_suspense`). Uses
  field **`3142`**; confirm it equals the TPO Information "Initial Submittal Date"
  (was empty on test loan `2601926378`).
- ✅ **PTA condition tracking data-driven** (`2.2`). Reads live conditions with
  `Prior To = Approval` and reports which PTAs are still open vs received; escalates to
  critical past day 25. (Falls back to advisory if conditions can't be read.)

## Step 3 — Loan Requests (RE-ADDED)

Was removed earlier; re-added because the RM actions are in Encompass. Built as
`submit_exception` (3.1), `submit_rush_request` (3.2), `submit_condo_review` (3.3).
Gaps to close before real writes:

- ❌ **All custom-form field IDs are placeholders** (`loan_requests.py`):
  - Non-QM v2 Exception Tracking: `CX.NONQM.EXCEPTION.TYPE`, `CX.NONQM.EXCEPTION.SUMMARY`
  - 2nd Level Review: `CX.2NDREVIEW.EXCEPTION` (Type=Exception), `CX.2NDREVIEW.FINDINGS`,
    `CX.2NDREVIEW.SUBMIT` (Submit for Review & Notify Users)
  - Rush Request Form: `CX.RUSH.REASON`, `CX.RUSH.TITLE.AVAIL`
  - Condo Review: `CX.CONDO.REVIEW.NOTES`, `CX.CONDO.REVIEW.SUBMIT`
- ⚠️ **2nd Level Review submit** is modeled as a field write; confirm whether it's a
  form-action/milestone instead.
- ⚠️ **Condo prerequisite docs**: uses `Evidence of Insurance` as a proxy for the
  Master Insurance Policy; **HOA Questionnaire is not in the eFolder doc set** and
  can't be checked yet. Add those doc types if we want true verification.
- ⚠️ **Rush timing** is advisory — no "docs needed by" date available to enforce the
  <2-day (<3 TX) window.

## Step 9 — Third Party Orders (RE-ADDED)

Was removed earlier; re-added because the RM actions (initiate on the 3rd Party
Order screen, condition status updates, Doc-Expiration date writes, milestone
completion, VVOE read) are in Encompass. Built as `order_credit_refresh` (9.1),
`order_credit_supplement` (9.2), `order_ssa_verification` (9.3),
`order_tax_transcripts` (9.4), `order_vvoe` (9.5), `validate_str_permit` (9.6),
`verify_pl` (9.7). Gaps to close before real writes:

- ❌ **Placeholder field IDs** (`third_party_orders.py`): Doc-Expiration dates
  `CX.DOCEXP.CREDIT.REFRESH`, `CX.DOCEXP.VVOE`; 3rd-party tracking
  `CX.TPO.TAX.REQUESTED`, `CX.TPO.TAX.FORMREADY`. Confirm the real Doc-Exp screen +
  3rd Party Order Tracking field IDs.
- ⚠️ **Condition-status verbs** (`Requested` / `Reviewed`) and the
  `"TPO Cond Submitted"` milestone are unconfirmed (shared with Step 4/8).
- ⚠️ **Credit refresh review is advisory** — no credit-refresh comparison doc is
  extracted, so "no new debt / balances not increased / no new inquiries" can't be
  auto-checked.
- ⚠️ **VVOE doc** — added `"Verbal VOE"` to the eFolder doc set; confirm the service
  supports that doc type and returns the effective/employment dates for a real
  vs-URLA-Page-2 comparison.
- ⚠️ **STR / P&L / supplement / SSA** rely on condition-title keyword matching; may
  need exact condition names for reliable detection.

## Step 4 — Conditions Queue

Strongest step (live condition reads + real actions). Remaining gaps:

- ✅ **`4.4` auto-derives Cleared vs Reviewed** from condition owner (`LC` → Cleared,
  others → Reviewed) via `options.auto_status=true`; the advisory listing now shows the
  derived status per fulfilled condition.
- ✅ **`4.4` description format applied**: deficient (`Requested`) conditions get the
  `**Rev MM/DD Initials –` stamp auto-prepended (never editing UW verbiage, ALL-CAPS
  softened). Initials via `options.rm_initials`.
- ✅ **`4.3` reads attached documents**: flags fulfilled conditions with no attached
  `supportingDocuments` (best-effort on the condition payload). Pinned-first / duplicate
  detection still needs richer document metadata.
- ⚠️ **`4.5` unassigned detection** relies on a `Container`/`Folder` field that the
  eFolder GET may not return. Confirm how the unassigned folder is represented (and
  that only the CTC Audit Checklist is expected to remain).
- ⚠️ **`4.6` resubmit prerequisites not checked**: SOP requires Roadmap +
  Conversation Logs updated and all statuses accurate before resubmit, and the TPO
  Cond Submitted milestone worksheet fields/tasks (e.g. Run Mavent) completed before
  clicking Finished. We only complete the milestone.
- ⚠️ Condition-status verbs (`Cleared`/`Reviewed`/`Requested`), the
  `"TPO Cond Submitted"` milestone, and `CX.TPO.CONDS.READY` (4.7) are unconfirmed
  (cross-cutting).

## Step 5 — Taxes & Insurance

Mostly advisory today; doc-presence wired in 5.1/5.2. Highest-value gaps because the
docs ARE extracted (Evidence of Insurance ~27 fields, Tax Summary ~8 fields on the
test loan):

- ✅ **5.1 compares extracted insurance values** (`review_hazard_flood_insurance`):
  insured name vs borrower, policy address vs subject, HOI deductible ≤ 5% of coverage,
  HOI coverage ≥ loan amount, flood deductible ≤ $10K ($25K Condo/PUD), and
  effective/expiration presence — all from `doc_fields`. Remaining: replacement-cost
  and note-date comparisons (fields not available); loss-payee match. Depends on the
  extraction key names.
- ✅ **5.2 surfaces extracted Tax Summary values** (`review_property_taxes`): annual tax
  amount / due date shown for cross-check. The purpose/state calculation methods (New
  Constr / CA purchase / exemptions / refi) remain advisory.
- ❌ **5.3 Itemization performs no writes** (`update_itemization`). Section 900/1000
  entries (T&I premiums, Pay-To payees) are guidance only — need the 2015
  Itemization Section 900/1000 field IDs to write amounts matched to the dec page /
  eFolder tax info; delinquent 60+ → URLA Page 3 payoff.
- ❌ **5.4 Aggregate Escrow performs no writes** (`update_aggregate_escrow`). Yearly
  T&I amounts + Setup (2-mo cushion, due dates, negative aggregate adjustment,
  flood-zone flood-can't-be-waived) are guidance only — need Aggregate Escrow screen
  field IDs / Setup action.
- ℹ️ Need a **note-date** field and (ideally) **replacement cost** to fully enforce
  5.1 effective-date and coverage rules.

## Step 6 — Document Reviews

Strong state-aware advisory (mortgagee clauses) + doc-presence for the 4 docs in the
set (1003, Credit Report, Title, CPL). Gaps:

- ⚠️ **6.2** doesn't read the **Credit Reference #** field to compare vs the report;
  doesn't auto-log the UW notification (conversation log); DTI shown but not compared
  to the program maximum.
- ✅ **6.3** compares **lender coverage ≥ loan amount** and **Title Effective Date ≤ 90
  days** of closing against the extracted title values (depends on the Title Report
  extraction keys). Mortgagee-clause/vesting text still advisory.
- ⚠️ **6.4/6.5 cross-doc agent-name match** (CPL ↔ title commitment ↔ E&O) not done;
  **Correspondent not auto-skipped** for CPL (6.4) and E&O/Wiring (6.5).
- ❌ **6.5 E&O / Wiring** and **6.6 Payoff** — the **extraction service does not
  support these doc types** (`ALL_DOCUMENT_TYPES` has no E&O/Wiring/Payoff), so they
  can't be presence/value-checked. Would require the service to add those doc types.
- ⚠️ **6.6** has `disbursement_date` but doesn't use it to verify the payoff amount
  covers per-diem through disbursement.
- ➖ **6.7 NY Closing Attorneys** intentionally excluded (external: intranet approved
  list + submit approval form to compliance). No Encompass action.

## Step 7 — Disclosure Tracking (Wholesale)

Reads LE/CD conditions + doc presence + occupancy-driven cleared/waived. Key gap: it
ignores the Disclosure Tracking screen dates (the SOP's source of truth).

- ⚠️ **Disclosure Tracking fields — partially wired**: added placeholder reads for
  **Initial LE Received** (`CX.DISC.LE.RECEIVED`) and **CD Received/Executed**
  (`CX.DISC.CD.RECEIVED`) — a populated received date = fully executed. Remaining
  fields (Revised LE/CD, SSPL, Safe Harbor, full Compliance Timeline) still need IDs.
- ✅ **7.2 auto-clears the LE condition** when the Initial LE received date is
  populated (suggests clearing). TRID vs non-TRID locked-LE branch still advisory.
- ✅ **7.3 computes ICD executed ≥ 3 days before ECD** from the CD received/executed
  date vs ECD (critical if < 3 days). Queue-prereq verification (approved & locked,
  appraisal cleared) and ICD term reconciliation (rate/LTV/fees) remain advisory.
- ✅ **7.3 POA** — scans conditions for a PTC POA condition; warns if closing via POA
  (`options.closing_via_poa`) but none is found.
- ➖ 3rd-party-fee NMLS lookup and NBS handling are external (excluded).

## Step 8 — Appraisals

Reads Appraisal Report doc + compares address/borrower (8.1), data-drives the CDA/BPO
requirement from SSR/units/NonQM v2 fields (8.2), and models the in-Encompass slivers
of corrections (8.3) and disaster inspections (8.4). The ordering (TPO Portal),
ValueLink look-ups, and desk emails are external and excluded.

- ❌ **Placeholder / unconfirmed field IDs** (`data_gathering.FIELD_MAP`): `FNMA SSR
  score` (`CX.APPR.FNMA.SSR`), `CDA Ordered` (`CX.NONQM.CDA.ORDERED`), `CDA
  Received/Waived` (`CX.NONQM.CDA.RECWAIVED`) are placeholders; `16` (# units) and
  `1041` (property type) are candidate standard IDs — all need confirmation on the
  instance. Until confirmed, 8.2 falls back to advisory.
- ⚠️ **8.1** address/borrower comparison relies on the Appraisal Report
  `ExtractedFields` raw-key names (matched fuzzily on "address"/"borrower"); confirm
  the extraction schema so the compare is reliable.
- ⚠️ **8.2** doesn't detect a **Field Review**, **Second Full Appraisal**, or **2
  appraisals on file** (which waive the secondary product) — no field/doc signal for
  these yet; still surfaced as advisory.
- ⚠️ **8.3** marks the correction condition **Requested** + logs a note, but the
  actual correction request is an email to `appraisaldesk@nqmf.com` (external). SSR
  score verb "Requested" needs confirmation.
- ⚠️ **8.4** verifies a disaster/inspection condition exists but the FEMA declaration
  circulation and the inspection request email are external.
- ➖ **Placing an Order**, **Transferred Appraisals**, and payment-approval steps are
  external (TPO Portal / transfer desk email / ValueLink) — intentionally excluded.

## Step 10 — Mavent (Wholesale)

Reads the Compliance Report doc, auto-classifies the extracted **Review Status**
(Pass=info / Alert=warning / Fail=critical), and auto-skips Correspondent files.

- ⚠️ **Status read depends on extraction schema** — the `Compliance Report`
  `ExtractedFields` "Review Status" raw-key name is matched fuzzily
  ("review_status"/"status"/"result"); confirm the actual key so the classification is
  reliable. Falls back to advisory when the status can't be read.
- ❌ **Permitted-fail justification is not verified automatically**: the SOP allows a
  Fail if it's on the Mavent permitted-fail spreadsheet (intranet, external) OR there
  are specific conversation-log notes from the Disclosure Desk/Ops Mgr. We don't read
  the **conversation log** to detect that justification (no read method wired), and the
  spreadsheet is external — both remain advisory.
- ➖ Fail resolution (Team Lead / support ticket) and copying communication to the
  conversation log are manual/external actions surfaced as reminders.

## Step 11 — Locked Loans

Data-drives the two core rules: lock expiration vs disbursement (uses `762`/`2553`),
and the UW Lock Compare DTI (Non-DSCR) / DSCR band (DSCR) variance tolerances. Loan
number update (11.2) writes URLA Lender field `305`.

- ❌ **Placeholder variance field IDs** (`data_gathering.FIELD_MAP`): `dti_at_lock`
  (`CX.LOCK.DTI`), `dscr_current` (`CX.DSCR.CURRENT`), `dscr_at_lock` (`CX.LOCK.DSCR`)
  are placeholders for the UW Lock Compare "at lock" snapshots. Current DTI uses `742`.
  Until confirmed, the DTI/DSCR checks fall back to advisory.
- ⚠️ **DSCR detection** relies on `options.is_dscr` or the presence of DSCR values —
  there's no confirmed loan-program field to auto-detect a DSCR product.
- ⚠️ **DSCR band gap**: the SOP lists >1.24, 1–1.14, .75–1, <.75 but not 1.14–1.24;
  values there are flagged "unlisted" for manual review.
- ⚠️ **Credit score / loan program / amortization** on-lock-vs-current comparisons are
  advisory only (no UW Lock Compare snapshot fields read for these yet).
- ➖ Notifying Broker/AE/SA (lock expiring / out-of-tolerance repricing) is external —
  surfaced as reminders. Loan-program changes follow the external TPO procedure.

## Step 12 — File Contacts (Wholesale)

Advisory checklist + extracted-value cross-checks (insurance & appraiser), auto-skips
non-Wholesale files, and branches purchase-only contacts by loan purpose.

- ❌ **File Contacts are not read from Encompass** (biggest gap): there is no client
  method or confirmed field IDs for the loan contacts (Title Insurance Co, Escrow,
  Settlement Agent, Appraiser, Buyer/Seller agents, etc.), so completeness/accuracy
  can't be auto-verified. Need the Encompass contacts endpoint (or the per-role
  contact field IDs) to compare entered vs required data points.
- ⚠️ **Extracted cross-checks depend on the extraction schema**: insurance policy #/
  coverage/premium/deductible/renewal (Evidence of Insurance, Flood Insurance) and
  appraiser name/license/company (Appraisal Report) are matched fuzzily on raw-key
  names; confirm the keys so the cross-check is reliable.
- ⚠️ **NMLS / license #** validity isn't checked against any external registry
  (out of scope) — only presence in the contact would be verifiable once contacts are
  readable.

## Step 13 — NonQM Document Expirations

Reads each Document Expirations item and compares to the closing date (ECD); items
expiring on/before closing raise a critical flag. Correspondent/DSCR applicability is
handled via `options.channel` / `options.is_dscr`. Lock uses the confirmed field `762`.

- ❌ **Placeholder expiration field IDs** (`data_gathering.FIELD_MAP`, category
  `docexp`): Income/Asset/Credit/Appraisal/VVOE/Flood/Title/CPL/Credit-Refresh
  Expiration Date fields (`CX.DOCEXP.*.EXP`) are placeholders — confirm the actual
  Document Expiration Dates form field IDs. Until then, the tool falls back to advisory.
- ⚠️ **Closing benchmark uses ECD (`763`)** — the SOP reads the Processing Summary
  closing date; confirm ECD equals the Processing Summary closing date (or add that
  field) so the comparison matches the screen.
- ⚠️ **Flood "if applicable"** is always evaluated when present; not conditioned on an
  actual flood-zone determination.
- ➖ Fetching updated docs from the eFolder / requesting them from the broker is
  manual/external — surfaced as the suggestion on any critical flag.

## Step 14 — Prepare the File for Closing

Requests the CTC audit (checkbox + comments write + conv-log note), auto-derives the
clear-audit gate from the audit fields, completes the TPO Conds Submitted milestone +
checks the CTC Review box (guarded), and runs the wholesale-only final steps with POA
detection and the TX cash-out CD rule.

- ❌ **Placeholder field IDs** (`prepare_for_closing.py` + `FIELD_MAP`): CTC Audit
  Request checkbox (`CX.CTC.AUDIT.REQUESTED`), audit comments (`CX.CTC.AUDIT.NOTES`),
  CTC Review checkbox (`CX.CTC.REVIEW`), and the read fields # defects
  (`CX.CTC.AUDIT.DEFECTS`) / status (`CX.CTC.AUDIT.STATUS`) — confirm the 3rd Party
  Tracking / Loan Notes field IDs. Checkbox write value assumed `"Y"` — confirm.
- ⚠️ **Clear-audit derivation** relies on the audit status/defects field values; when
  unreadable it treats the audit as not clear (safe default) unless
  `options.ctc_audit_clear=true` is passed.
- ⚠️ **Mail-away** flag isn't read from the Processing Summary "Mail Away" checkbox
  (surfaced only as a reminder); add the field ID to tailor the Notes-to-Closer prompt.
- ➖ External/manual: ECD-within-SLA check (Daily Turn Time email), curing audit issues +
  emailing the audit team, and generating/sending the Closing Validation Form to TPO.

## RM Tools & Templates — EXCLUDED (external)

The ECD Communication / Condition Review email templates, mortgagee-clause content, and
the "log into the TPO Portal → conditions tab → Ready for Review + Notify Lender"
instructions are all **client-facing email and external-portal actions** — out of scope
per the no-external-communication rule. Not modeled as a step.

- ➖ Email drafting/sending (Wholesale TRID can/can't-meet-ECD, NDC can/can't-meet,
  condition-review emails) and TPO Portal uploads are external.
- ✅ The Encompass-contained **decision signals** an RM uses to pick a template are
  already covered: ECD ≤ 15-day radar (`validate_ecd`, STEP_01), lock status
  (`review_lock`, STEP_11), appraisal cleared (STEP_08), final-conditions received
  (conditions queue, STEP_04), and property state / NY mortgagee-clause branch
  (`loan_profile`).

---

## Cross-cutting confirmations (see ENCOMPASS_FIELD_CONFIRMATION.md)

- Placeholder write field IDs: `CX.DFT.REASON`, `CX.TPO.CONDS.READY`.
- Milestone name `"TPO Cond Submitted"` (used by resubmit/appraisal/CTC).
- Condition status verbs (`Cleared` / `Reviewed` / `Requested`).
- eFolder `ExtractedFields` keys per doc type (to compare values, not just
  presence).
- Auth: no `TEST_ENCOMPASS_USERNAME/_PASSWORD` — writes run as client-credentials
  integration, not an impersonated user.
