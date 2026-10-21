# Step 13: NonQM - Document Expirations

Ensure all expiration dates are accurate per the current documentation in Encompass and
that documents expire after the closing date.

## Substeps

### 13.1 — Verify Document Expirations
Call `verify_document_expirations`. Reads the closing date (ECD) and each item's
Expiration Date from the Document Expirations screen, then flags any item that expires
on/before closing as **critical**. Items checked:
- Income Documentation, Asset Documentation, Credit Report, Appraisal, Verbal VOE, Flood
  (if applicable), Title, CPL, Lock
- Credit Refresh (skipped for correspondent or DSCR loans); VVOE (skipped for
  correspondent) — driven by `options.channel` / `options.is_dscr`

If any item expires before closing, check the eFolder for updated documents; if not found,
request updated documents from the broker. Falls back to advisory when the expiration
fields can't be read.
