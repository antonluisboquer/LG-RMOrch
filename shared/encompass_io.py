"""Encompass I/O with dry-run gate and field-writes ledger.

All read/write operations go through this module so that:
- dry_run mode can intercept writes
- every write is recorded in a ledger for the review node
- info-overwrite flags are auto-generated for each write batch
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from encompass_client import get_encompass_client

logger = logging.getLogger(__name__)

_FIELD_WRITES_LEDGER: List[Dict[str, Any]] = []
_FIELD_WRITES_FLAGS: List[Dict[str, Any]] = []


def flush_field_writes_ledger() -> List[Dict[str, Any]]:
    """Drain and return all accumulated field-write entries since the last flush."""
    global _FIELD_WRITES_LEDGER
    entries = _FIELD_WRITES_LEDGER[:]
    _FIELD_WRITES_LEDGER = []
    return entries


def flush_field_writes_flags() -> List[Dict[str, Any]]:
    """Drain and return all accumulated info-overwrite flags since the last flush."""
    global _FIELD_WRITES_FLAGS
    entries = _FIELD_WRITES_FLAGS[:]
    _FIELD_WRITES_FLAGS = []
    return entries


def get_field_writes_count() -> int:
    return len(_FIELD_WRITES_LEDGER)


def _record_writes(
    updates: Dict[str, Any],
    node_id: str,
    dry_run: bool,
    substep: str = "",
    substep_name: str = "",
    title: str = "",
    details: str = "",
    relevant_documents: List[str] = None,
) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    resolved_substep = substep or node_id

    for fid, val in updates.items():
        _FIELD_WRITES_LEDGER.append({
            "field_id": fid,
            "value": val,
            "substep": resolved_substep,
            "dry_run": dry_run,
            "timestamp": ts,
        })

    field_writes_list = [{"field_id": fid, "value": str(val)} for fid, val in updates.items()]
    writes_summary = "; ".join(f"{fid}={val}" for fid, val in updates.items())

    _FIELD_WRITES_FLAGS.append({
        "substep": resolved_substep,
        "title": title or f"Fields Written ({len(updates)})",
        "severity": "info-overwrite",
        "details": details or f"{'Would write' if dry_run else 'Wrote'} {len(updates)} field(s): {writes_summary}",
        "suggestion": f"{'Will write' if dry_run else 'Written'}: {writes_summary}",
        "resolved": True,
        "timestamp": ts,
        "relevant_documents": relevant_documents or [],
        "substep_name": substep_name,
        "field_writes": field_writes_list,
    })


def read_fields(
    loan_id: str,
    field_ids: List[str],
    state: dict = None,
) -> Dict[str, Any]:
    """Read multiple fields from a loan via fieldReader.

    If the bulk request fails (400), falls back to reading fields one-by-one
    so that unsupported field IDs don't block the entire read.
    """
    if not field_ids:
        return {}

    unique_ids = list(dict.fromkeys(field_ids))
    client = get_encompass_client(state=state)

    try:
        result = client.read_fields(loan_id, unique_ids)
    except Exception as e:
        logger.warning(f"Bulk fieldReader failed ({e}); falling back to individual reads")
        result = {}
        for fid in unique_ids:
            try:
                single = client.read_fields(loan_id, [fid])
                result.update(single)
            except Exception:
                logger.debug(f"  Field {fid}: read failed, treating as empty")
                result[fid] = None

    normalized = {}
    for field_id in unique_ids:
        value = result.get(field_id)
        if value is not None and str(value).strip() != "":
            normalized[field_id] = value
        else:
            normalized[field_id] = None
    return normalized


def write_fields(
    loan_id: str,
    updates: Dict[str, Any],
    state: dict = None,
    node_id: str = "",
    substep: str = "",
    substep_name: str = "",
    title: str = "",
    details: str = "",
    relevant_documents: List[str] = None,
) -> bool:
    """Write multiple fields to a loan.

    When ``dry_run`` is enabled in the registry, logs what would be written
    and returns ``True`` without touching Encompass.

    Automatically records writes to ledger and generates an info-overwrite flag.
    """
    if not updates:
        return True

    dry_run = False
    try:
        from output.registry import DEV_MODE
        dry_run = DEV_MODE.dry_run
    except Exception:
        try:
            from registry import DEV_MODE
            dry_run = DEV_MODE.dry_run
        except Exception:
            pass

    record_kwargs = dict(
        substep=substep,
        substep_name=substep_name,
        title=title,
        details=details,
        relevant_documents=relevant_documents or [],
    )

    if dry_run:
        logger.info(f"[DRY-RUN:{node_id}] Would write {len(updates)} fields to {loan_id[:12]}: {updates}")
        _record_writes(updates, node_id, dry_run=True, **record_kwargs)
        return True

    try:
        client = get_encompass_client(state=state)
        client.write_fields(loan_id, updates)
        _record_writes(updates, node_id, dry_run=False, **record_kwargs)
        return True
    except Exception as e:
        logger.error(f"Error writing fields: {e}")
        raise
