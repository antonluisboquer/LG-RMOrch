# Step 10: Mavent (Wholesale Only)

Review the loan's Mavent compliance report. All fails must be resolved prior to
requesting a CTC.

## Substeps

> Wholesale only — not applicable to Correspondent files (auto-skipped when
> `options.channel="correspondent"`).

### 10.1 — Mavent Compliance Review
Call `review_mavent`. Access the Mavent Report in the eFolder. When a Compliance Report
is extracted, the review status is read automatically and classified: **Pass** (info),
**Alert** (warning), **Fail** (critical). A Fail is acceptable only if it is a permitted
fail per the Mavent spreadsheet (intranet / Ops Resources) OR there are SPECIFIC
conversation-log notes from the Disclosure Desk Mgr / Ops Mgr justifying it for the
current loan structure. All other fails must be resolved before CTC (address with Team
Lead; if unresolved, open a support ticket). Copy all Mavent-fail communication in the
Conversation Log.
