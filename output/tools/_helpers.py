"""Shared helpers for tool functions.

Provides state-access utilities used by all substep tool files.
Adapted from DocsOrch Agent Factory pattern.
"""

import json
import re
from datetime import date, datetime

from langchain_core.messages import ToolMessage
from langgraph.types import Command

_EMPTY_MARKERS = {"//", "N/A", ""}

_DATE_FORMATS = (
    "%m/%d/%Y %I:%M:%S %p",
    "%m/%d/%Y %I:%M %p",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%m-%d-%Y",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%B %d, %Y",
    "%b %d, %Y",
)


def _parse_date(val, default=None) -> "date | None":
    """Parse a date string into a date object.

    Handles the common formats produced by Encompass LOS and documents.
    """
    if not val:
        return default
    val_str = str(val).strip()
    if not val_str or val_str in _EMPTY_MARKERS:
        return default

    clean = re.sub(r"[+-]\d{2}:\d{2}$", "", val_str)
    clean = clean.rstrip("Z")

    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(clean, fmt).date()
        except (ValueError, TypeError):
            continue
    return default


def _los(state: dict, key: str, default=None):
    """Get a LOS field value from state['los_fields'].

    Normalises Encompass empty markers to the default value.
    """
    entry = state.get("los_fields", {}).get(key, {})
    val = entry.get("value", default) if isinstance(entry, dict) else default
    if isinstance(val, str) and val.strip() in _EMPTY_MARKERS:
        return default
    return val


def _doc(state: dict, key: str, default=None):
    """Get a doc field value from state['doc_fields'] (namespaced key)."""
    entry = state.get("doc_fields", {}).get(key, {})
    return entry.get("value", default) if isinstance(entry, dict) else default


def _doc_status(state: dict, doc_type: str) -> str:
    """Return the extraction status for a doc type from state['efolder_documents']."""
    entry = state.get("efolder_documents", {}).get(doc_type, {})
    return str(entry.get("status", "")) if isinstance(entry, dict) else ""


def _doc_present(state: dict, doc_type: str) -> bool:
    """True if the doc type was found/extracted in the eFolder."""
    return _doc_status(state, doc_type).lower() in ("completed", "success", "stored_no_extraction")


def doc_field(state: dict, slug: str, *needles: str):
    """Best-effort read of an extracted field from a doc-slug namespace.

    doc_fields keys are namespaced '<doc_slug>.<raw_key>' (e.g.
    'evidence_of_insurance.policy_number'). Needles are tried in PRIORITY order:
    an exact raw_key match wins first, then a key that ends with the needle, then
    a substring match — so specific needles (e.g. 'insured_name') aren't shadowed
    by looser ones (e.g. a key merely containing 'insured'). Returns None if none
    of the needles resolve to a populated value.
    """
    fields = {}
    for key, entry in (state.get("doc_fields") or {}).items():
        if not key.startswith(f"{slug}."):
            continue
        raw_key = key.split(".", 1)[1].lower()
        fields[raw_key] = entry.get("value") if isinstance(entry, dict) else entry

    def _valid(v):
        return v not in (None, "", "//", "None")

    for matcher in (
        lambda k, n: k == n,
        lambda k, n: k.endswith(n),
        lambda k, n: n in k,
    ):
        for n in (x.lower() for x in needles):
            for k, v in fields.items():
                if matcher(k, n) and _valid(v):
                    return str(v)
    return None


def to_number(v):
    """Parse a numeric/currency/percent string into a float, or None."""
    if v is None:
        return None
    s = str(v).strip().replace(",", "").replace("$", "").replace("%", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def load_conditions(state: dict):
    """Return (conditions, error). Uses cached state['conditions'] or fetches once.

    Lazy-imports the Encompass client to avoid import cycles at module load.
    """
    conditions = state.get("conditions")
    if conditions is not None:
        return conditions, None
    loan_id = state.get("loan_id")
    if not loan_id:
        return [], "No loan_id in state."
    try:
        from encompass_client import get_encompass_client
        client = get_encompass_client(state=state)
        conditions = client.get_conditions(loan_id)
        return conditions or [], None
    except Exception as e:
        return [], str(e)


def cond_title(cond: dict) -> str:
    return str(cond.get("title") or cond.get("name") or cond.get("description") or "").strip()


def cond_status(cond: dict) -> str:
    return str(cond.get("status") or cond.get("conditionStatus") or "").strip()


def _profile(state: dict, key: str, default=None):
    """Get a loan-profile value from state['loan_profile']."""
    return state.get("loan_profile", {}).get(key, default)


def _days_between(start: "date | None", end: "date | None") -> "int | None":
    """Whole days from start to end (end - start). None if either is missing."""
    if not start or not end:
        return None
    return (end - start).days


def make_command(
    tool_call_id: str,
    message: str,
    flags: list | None = None,
    ledger: list | None = None,
    extra: dict | None = None,
) -> Command:
    """Build a standard tool Command(update=...).

    Appends a ToolMessage with a JSON result, and optionally merges `flags`
    and a `field_writes_ledger` (action ledger) into state.
    """
    result = {"success": True, "message": message}
    if extra:
        result.update(extra)
    update: dict = {"messages": [ToolMessage(content=json.dumps(result, default=str), tool_call_id=tool_call_id)]}
    if flags:
        update["flags"] = flags
    if ledger:
        update["field_writes_ledger"] = ledger
    return Command(update=update)
