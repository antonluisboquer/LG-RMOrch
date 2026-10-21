# Step 12: File Contacts (Wholesale Only)

Access Encompass File Contacts (Tools) and verify all data is entered completely and
accurately.

## Substeps

> Wholesale only — auto-skipped when `options.channel` is known and not Wholesale.

### 12.1 — Verify File Contacts
Call `verify_file_contacts`. Confirm each required contact. Where the source document
is in the eFolder, extracted values are surfaced to cross-check the entries: the
**insurance** contact against Evidence of Insurance / Flood Insurance (policy #,
coverage, premium, deductible, renewal), and the **appraiser** contact against the
Appraisal Report (name, license #, company).
- **Title insurance company**: name, address, title, case #, officer name, title, email,
  phone, NMLS & license #
- **Escrow company** (if applicable): name, address, escrow case #, officer name, phone,
  email, NMLS & license #
- **Settlement agent**: name, address, officer name, phone, email, NMLS & license #
- **Homeowners & Flood insurance**: agent info, policy #, coverage amount, premium,
  renewal date & deductible
- **Buyer & Seller's agents** (purchase only): company name/license #, agent name/license
  #, agent email/phone
- **Seller** (purchase only): all data points
- **Appraiser**: name, license number, company name
