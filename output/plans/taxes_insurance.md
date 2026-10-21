# Step 5: Taxes & Insurance

Verify insurance and taxes meet NQMF standards, then reflect T&I in the 2015
Itemization and Aggregate Escrow Account screens.

## Important Rules
- Without current/verified tax figures, the tax condition cannot be cleared.
- Any non-bill tax amount used must be documented (processor cert or Notepad).
- In a flood zone, flood insurance must be impounded and cannot be waived.
- RM owns only Sections 900 & 1000 of the 2015 Itemization.

## Substeps

### 5.1 — Hazard & Flood Insurance
Call `review_hazard_flood_insurance`. Verify loss-payee/loan number, insured name,
property address, note-date effectiveness + 12-month term, premium payment,
deductibles (HOI ≤ 5%; Flood ≤ $10K / $25K condo-PUD), wind/hail coverage, coverage
amounts, DSCR 6-mo PITIA rent-loss, and condo HO6 requirements. File invoices in the
ICD placeholder and assign to the HOI/Flood condition.

### 5.2 — Property Taxes
Call `review_property_taxes`. Ensure taxes due within 60 days have a current bill.
Validate the amount by method: New Construction (Title millage × greater of price/value,
else smartasset, else 1.5% improved value), CA purchases (1.25% revised assessed / Title),
purchases with exemptions (exclude prior-owner exemptions), and refinances.

### 5.3 — 2015 Itemization
Call `update_itemization`. Enter all T&I premiums due in Section 900 (match dec page /
eFolder), with the correct "Pay To" payees. Taxes 60+ days delinquent → payoff on URLA
Page 3. Water/sewer due → Section 900 (60+ days delinquent → URLA Page 3 payoff).

### 5.4 — Aggregate Escrow Account
Call `update_aggregate_escrow`. For impound loans (not Correspondent), update yearly
tax/insurance amounts, run Setup (2-month cushion; due dates: 2 semi-annual / 4
quarterly). Flood in a flood zone cannot be waived; T&I due within 60 days paid at closing.
