"""STEP_00: Data Gathering — find_loan, fetch_rm_fields, fetch_doc_fields.

Establishes the loan GUID, reads the Encompass LOS fields the RM workflow needs,
and extracts eFolder document fields (cache-first) so downstream verification
steps can check document presence and values.
Reuses the shared encompass_client / encompass_io / efolder_client.
"""

import json
import logging
import re
from typing import Annotated, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

logger = logging.getLogger(__name__)

# Encompass field IDs the RM workflow reads. Keys are internal friendly names
# used by the tools via _helpers._los(state, key).
FIELD_MAP = {
    "364":  {"key": "loan_number", "field_name": "Loan Number", "category": "loan"},
    "4000": {"key": "borrower_first_name", "field_name": "Borrower First Name", "category": "borrower"},
    "4002": {"key": "borrower_last_name", "field_name": "Borrower Last Name", "category": "borrower"},
    "19":   {"key": "loan_purpose", "field_name": "Loan Purpose", "category": "loan"},
    "1109": {"key": "loan_amount", "field_name": "Loan Amount", "category": "loan"},
    "1172": {"key": "loan_type", "field_name": "Loan Type", "category": "loan"},
    "1811": {"key": "occupancy", "field_name": "Occupancy", "category": "property"},
    "11":   {"key": "property_street", "field_name": "Subject Property Address", "category": "property"},
    "12":   {"key": "property_city", "field_name": "Subject Property City", "category": "property"},
    "14":   {"key": "property_state", "field_name": "Property State", "category": "property"},
    "15":   {"key": "property_zip", "field_name": "Subject Property Zip", "category": "property"},
    "742":  {"key": "dti_total", "field_name": "Total Debt Ratio (DTI)", "category": "ratios"},
    "740":  {"key": "housing_ratio", "field_name": "Housing Expense Ratio", "category": "ratios"},
    "763":  {"key": "estimated_closing_date", "field_name": "Estimated Closing Date", "category": "dates"},
    "3142": {"key": "initial_submittal_date", "field_name": "Initial Submittal Date", "category": "dates"},
    "2553": {"key": "disbursement_date", "field_name": "Disbursement Date", "category": "dates"},
    "MS.STATUS": {"key": "current_milestone", "field_name": "Current Milestone Name", "category": "status"},
    "762":  {"key": "lock_expiration_date", "field_name": "Lock Expiration Date", "category": "dates"},
    # Appraisals (STEP_08) — property characteristics + secondary-appraisal signal.
    # 16 (# units) / 1041 (property type) are standard IDs. FNMA SSR score confirmed
    # against the field catalog (CX.SSRSCOREFNMA). CDA (Collateral Desk Analysis)
    # tracking has no standard/custom field in the catalog — left as a gap.
    "16":   {"key": "property_units", "field_name": "No. of Units", "category": "property"},
    "1041": {"key": "property_type", "field_name": "Subject Property Type", "category": "property"},
    "CX.SSRSCOREFNMA": {"key": "fnma_ssr_score", "field_name": "SSR Score (FNMA)", "category": "appraisal"},
    # Locked Loans (STEP_11) — current DSCR confirmed (CX.DEBTSERVICECOVERAGERATIO).
    # Current DTI is 742. The UW Lock Compare "at lock" snapshots (DTI/DSCR on lock)
    # have no standard field in the catalog — left as a gap (variance stays advisory).
    "CX.DEBTSERVICECOVERAGERATIO": {"key": "dscr_current", "field_name": "DSCR", "category": "ratios"},
    # NonQM Document Expirations (STEP_13) — eFolder document-tracking Expiration Date.
    # Confirmed against the catalog: Document.ExpirationDate.<DOC NAME>. Income/Asset/
    # VVOE/CPL/Credit-Refresh have no document-tracking expiration field in this
    # instance's eFolder config — left as gaps (Lock uses 762).
    "Document.ExpirationDate.CREDIT REPORT": {"key": "docexp_credit", "field_name": "Credit Report Expiration", "category": "docexp"},
    "Document.ExpirationDate.APPRAISAL": {"key": "docexp_appraisal", "field_name": "Appraisal Expiration", "category": "docexp"},
    "Document.ExpirationDate.FLOOD CERTIFICATE": {"key": "docexp_flood", "field_name": "Flood Expiration", "category": "docexp"},
    "Document.ExpirationDate.TITLE REPORT": {"key": "docexp_title", "field_name": "Title Expiration", "category": "docexp"},
    # Disclosure Tracking (STEP_07) — a populated received date = fully executed.
    # Confirmed against the catalog: 3153 (LE received), 3978 (CD received).
    "3153": {"key": "le_received_date", "field_name": "LE Initial TIL Disclosure Rcvd Date", "category": "disclosure"},
    "3978": {"key": "cd_received_date", "field_name": "Closing Disclosure Received Date", "category": "disclosure"},
    # NOTE (gaps): CDA ordered/received, DTI/DSCR at-lock, Income/Asset/VVOE/CPL/
    # Credit-Refresh doc expirations, and the CTC/QC audit status+defects have no
    # confirmed field in the catalog. Prefunding-QC candidates (CX.QCAUDITCOMPLETE,
    # CX.QCAUDITFINDINGS) exist but their mapping to the RM "CTC Audit" is unconfirmed;
    # see docs/ENCOMPASS_FIELD_CONFIRMATION.md. Those tools degrade to advisory.
}

ALL_FIELD_IDS = set(FIELD_MAP.keys())


@tool
def find_loan(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
    loan_number: Optional[str] = None,
) -> Command:
    """Find the loan GUID from the loan number.

    Stores the GUID in state['loan_id'] for all subsequent tools.
    """
    ln = loan_number or state.get("loan_number")

    existing_loan_id = state.get("loan_id")
    if existing_loan_id:
        result = {
            "success": True, "loan_id": existing_loan_id, "loan_number": ln,
            "message": f"Loan ID already available: {existing_loan_id[:8]}...",
            "source": "state",
        }
        return Command(update={
            "loan_number": ln,
            "messages": [ToolMessage(content=json.dumps(result), tool_call_id=tool_call_id)],
        })

    if not ln:
        return Command(update={"messages": [ToolMessage(
            content=json.dumps({"error": "No loan_number provided"}),
            tool_call_id=tool_call_id,
        )]})

    logger.info(f"[FIND_LOAN] Searching for loan: {ln}")

    try:
        from encompass_client import get_encompass_client

        client = get_encompass_client(state=state)
        results = client.search_loans(loan_number=ln)

        if not results:
            return Command(update={"messages": [ToolMessage(
                content=json.dumps({"error": f"No loan found for {ln}"}),
                tool_call_id=tool_call_id,
            )]})

        loan_id = results[0].get("loanGuid") if isinstance(results[0], dict) else results[0]
        borrower_name = results[0].get("borrowerName") if isinstance(results[0], dict) else None

        result = {
            "success": True, "loan_id": loan_id, "loan_number": ln,
            "borrower_name": borrower_name,
            "message": f"Found loan GUID: {loan_id[:8]}...",
            "source": "encompass_search",
        }
        logger.info(f"[FIND_LOAN] Found: {loan_id[:8]}... loan_number={ln}")

        return Command(update={
            "loan_id": loan_id,
            "loan_number": ln,
            "borrower_name": borrower_name or state.get("borrower_name"),
            "messages": [ToolMessage(content=json.dumps(result), tool_call_id=tool_call_id)],
        })

    except Exception as e:
        logger.error(f"[FIND_LOAN] Error: {e}")
        return Command(update={"messages": [ToolMessage(
            content=json.dumps({"error": str(e)}),
            tool_call_id=tool_call_id,
        )]})


@tool
def fetch_rm_fields(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Batch-read the RM LOS fields and build the loan profile.

    Populates state['los_fields'] keyed by internal field key, and a small
    state['loan_profile'] (purpose, state, is_refinance) for downstream tools.
    """
    from shared.encompass_io import read_fields

    loan_id = state.get("loan_id")
    if not loan_id:
        return Command(update={"messages": [ToolMessage(
            content=json.dumps({"error": "No loan_id in state. Run find_loan first."}),
            tool_call_id=tool_call_id,
        )]})

    logger.info(f"[FETCH_RM] Reading {len(ALL_FIELD_IDS)} fields for loan {loan_id[:8]}...")

    try:
        raw = read_fields(loan_id, list(ALL_FIELD_IDS), state=state)

        los_fields = {}
        found = 0
        for field_id, mapping in FIELD_MAP.items():
            value = raw.get(field_id)
            stripped = str(value).strip() if value is not None else ""
            has_value = value is not None and stripped != "" and stripped != "//"
            los_fields[mapping["key"]] = {
                "value": value if has_value else None,
                "field_id": field_id,
                "field_name": mapping["field_name"],
                "category": mapping["category"],
            }
            if has_value:
                found += 1

        def _v(key):
            entry = los_fields.get(key, {})
            v = entry.get("value")
            if isinstance(v, str) and v.strip() in ("//", "N/A", ""):
                return None
            return v

        purpose = (_v("loan_purpose") or "").strip()
        is_refi = "refi" in purpose.lower() or "refinance" in purpose.lower()
        prop_state = (_v("property_state") or "").upper()

        occupancy = (_v("occupancy") or "").strip()
        occ_lower = occupancy.lower()
        is_owner_occupied = "primary" in occ_lower or "owner" in occ_lower
        is_investment = "investor" in occ_lower or "investment" in occ_lower

        address_parts = [
            _v("property_street"),
            _v("property_city"),
            prop_state,
            _v("property_zip"),
        ]
        property_address = ", ".join(str(p).strip() for p in address_parts if p and str(p).strip())

        loan_profile = {
            "purpose": purpose or "Unknown",
            "is_refinance": is_refi,
            "state": prop_state,
            "loan_type": _v("loan_type") or "Unknown",
            "occupancy": occupancy or "Unknown",
            "is_owner_occupied": is_owner_occupied,
            "is_investment": is_investment,
            "property_address": property_address or "Unknown",
            "dti_total": _v("dti_total"),
            "housing_ratio": _v("housing_ratio"),
        }

        result = {
            "success": True,
            "fields_found": found,
            "total_fields": len(ALL_FIELD_IDS),
            "loan_profile": loan_profile,
            "message": f"Fetched {found}/{len(ALL_FIELD_IDS)} RM fields",
        }
        logger.info(f"[FETCH_RM] {result['message']}")

        return Command(update={
            "los_fields": los_fields,
            "loan_profile": loan_profile,
            "messages": [ToolMessage(content=json.dumps(result), tool_call_id=tool_call_id)],
        })

    except Exception as e:
        logger.error(f"[FETCH_RM] Error: {e}")
        return Command(update={"messages": [ToolMessage(
            content=json.dumps({"error": str(e)}),
            tool_call_id=tool_call_id,
        )]})


# ─────────────────────────────────────────────────────────────────────────
# eFolder document extraction (STEP_00 substep 3)
# ─────────────────────────────────────────────────────────────────────────

# Doc types the RM verification steps depend on. Must match the EfolderConnect
# service's supported DocType names (see shared/efolder_client.ALL_DOCUMENT_TYPES).
RM_DOCUMENT_TYPES = [
    "Evidence of Insurance",   # 5.1 hazard/HOI
    "Flood Insurance",         # 5.1 flood
    "Flood Certificate",       # 5.1 flood zone determination
    "Title Report",            # 6.3 preliminary title
    "Closing Protection Letter",  # 6.4 CPL
    "Appraisal Report",        # 8.1 appraisal receipt
    "Compliance Report",       # 10.1 Mavent
    "1003 URLA",               # 6.1 signed application
    "Credit Report",           # 6.2 credit
    "Tax Summary",             # 5.2 property taxes
    "Loan Estimate",           # 7.2 LE tracking
    "Closing Disclosure",      # 7.3 ICD tracking
    "Approval Form",           # 2.1 approval / conditions
    "Verbal VOE",              # 9.5 VVOE review
    "Purchase Agreement",      # 1.4 purchase ECD vs contract closing date
]


def _doc_slug(doc_type: str) -> str:
    """Snake-case a doc type for namespacing (e.g. 'Evidence of Insurance' -> 'evidence_of_insurance')."""
    return re.sub(r"[^a-z0-9]+", "_", str(doc_type).lower()).strip("_")


def _extracted_fields(doc: dict) -> dict:
    """Return the ExtractedFields dict from a doc regardless of GET/POST key casing."""
    return doc.get("ExtractedFields") or doc.get("extracted_fields") or {}


def _field_value(raw) -> tuple:
    """Normalize an extracted field entry into (value, confidence)."""
    if isinstance(raw, dict):
        return raw.get("value", raw.get("Value")), raw.get("confidence", raw.get("Confidence"))
    return raw, None


def _normalize_efolder(documents: list) -> tuple:
    """Build (doc_fields, efolder_documents) from a list of eFolder docs.

    - doc_fields: namespaced {"<doc_slug>.<raw_key>": {value, source_document, confidence, raw_key}}
    - efolder_documents: {doc_type: {status, extracted_fields, count, title, attachment_id, source}}
    """
    doc_fields: dict = {}
    inventory: dict = {}
    for doc in documents:
        doc_type = doc.get("DocType") or doc.get("doc_type") or ""
        if not doc_type:
            continue
        status = str(doc.get("Status") or doc.get("status") or "").lower()
        if status == "success":
            status = "completed"
        fields = _extracted_fields(doc)
        slug = _doc_slug(doc_type)
        for raw_key, raw_val in (fields.items() if isinstance(fields, dict) else []):
            value, confidence = _field_value(raw_val)
            doc_fields[f"{slug}.{raw_key}"] = {
                "value": value,
                "source_document": doc_type,
                "confidence": confidence,
                "raw_key": raw_key,
            }
        inventory[doc_type] = {
            "doc_type": doc_type,
            "status": status or "unknown",
            "extracted_fields": fields if isinstance(fields, dict) else {},
            "extracted_fields_count": doc.get("ExtractedFieldsCount") or (len(fields) if isinstance(fields, dict) else 0),
            "document_title": doc.get("DocumentTitle") or doc.get("document_title") or "",
            "attachment_id": doc.get("AttachmentID") or doc.get("attachment_id") or "",
            "source": doc.get("source") or "efolder",
        }
    return doc_fields, inventory


@tool
def fetch_doc_fields(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Extract RM document fields from the loan eFolder (cache-first).

    Reads the EfolderConnect cache via GET /efolder; if empty (or state
    ['force_extract'] is set) triggers extraction for the RM document set.
    Populates state['doc_fields'] (namespaced values) and
    state['efolder_documents'] (per-doc inventory) so verification steps can
    check document presence and compare extracted values.
    """
    loan_number = state.get("loan_number")
    if not loan_number:
        return Command(update={"messages": [ToolMessage(
            content=json.dumps({"error": "No loan_number in state."}),
            tool_call_id=tool_call_id,
        )]})

    env = (state.get("env") or "test").lower()
    force_extract = bool(state.get("force_extract", False))

    logger.info(f"[FETCH_DOCS] loan={loan_number} env={env} force={force_extract}")

    try:
        from shared.efolder_client import EfolderClient, ExtractionRequest

        client = EfolderClient()

        documents = []
        if not force_extract:
            get_resp = client.get_documents(loan_number, include_fields=True)
            if not get_resp.get("error"):
                cached = get_resp.get("documents", []) or []
                wanted = {d.lower() for d in RM_DOCUMENT_TYPES}
                documents = [
                    d for d in cached
                    if str(d.get("DocType") or d.get("doc_type") or "").lower() in wanted
                ]

        source = "cache"
        if not documents or force_extract:
            source = "extract"
            req = ExtractionRequest(
                loan_number=loan_number,
                document_types=RM_DOCUMENT_TYPES,
                environment="prod" if env in ("prod", "production") else "test",
                selection_mode="Best",
                use_cache=not force_extract,
                override_not_found=True,
            )
            ext = client.extract_documents(req)
            documents = ext.documents or []

        doc_fields, inventory = _normalize_efolder(documents)

        completed = [dt for dt, d in inventory.items() if d["status"] in ("completed", "stored_no_extraction")]
        missing = [dt for dt in RM_DOCUMENT_TYPES if dt not in completed]

        inventory["_meta"] = {
            "loan_number": loan_number,
            "requested": RM_DOCUMENT_TYPES,
            "completed": completed,
            "missing": missing,
            "source": source,
        }

        result = {
            "success": True,
            "source": source,
            "docs_found": len(completed),
            "docs_requested": len(RM_DOCUMENT_TYPES),
            "fields_extracted": len(doc_fields),
            "missing": missing,
            "message": f"eFolder: {len(completed)}/{len(RM_DOCUMENT_TYPES)} docs, {len(doc_fields)} fields ({source})",
        }
        logger.info(f"[FETCH_DOCS] {result['message']}")

        return Command(update={
            "doc_fields": doc_fields,
            "efolder_documents": inventory,
            "messages": [ToolMessage(content=json.dumps(result), tool_call_id=tool_call_id)],
        })

    except Exception as e:
        logger.error(f"[FETCH_DOCS] Error: {e}")
        return Command(update={"messages": [ToolMessage(
            content=json.dumps({"error": str(e), "note": "eFolder extraction failed; downstream doc checks will be advisory only."}),
            tool_call_id=tool_call_id,
        )]})
