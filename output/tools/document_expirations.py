"""STEP_13: NonQM - Document Expirations.

13.1 verify_document_expirations — verify docs expire after the closing date.
"""

import logging
from typing import Annotated

from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from ._helpers import _los, _parse_date, _days_between, make_command

logger = logging.getLogger(__name__)

# (display name, los key, applies to correspondent, applies to DSCR)
EXPIRATION_ITEMS = [
    ("Income Documentation", "docexp_income", True, True),
    ("Asset Documentation", "docexp_asset", True, True),
    ("Credit Report", "docexp_credit", True, True),
    ("Appraisal", "docexp_appraisal", True, True),
    ("Verbal Verification of Employment", "docexp_vvoe", False, True),
    ("Flood (if applicable)", "docexp_flood", True, True),
    ("Title", "docexp_title", True, True),
    ("CPL", "docexp_cpl", True, True),
    ("Credit Refresh", "docexp_credit_refresh", False, False),
    ("Lock", "lock_expiration_date", True, True),
]


@tool
def verify_document_expirations(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Verify document expiration dates all fall after the closing date.

    Confirms the closing date (Processing Summary), then reads each item on the
    Document Expirations screen and checks it expires AFTER closing. Items expiring
    on/before closing raise a critical flag (check the eFolder for updated docs; if
    not found, request updated docs from the broker). VVOE and Credit Refresh do not
    apply to Correspondent; Credit Refresh also does not apply to DSCR.
    """
    options = state.get("options") or {}
    channel = str(options.get("channel") or "").strip().lower()
    is_correspondent = channel == "correspondent"
    is_dscr = bool(options.get("is_dscr"))

    closing = _parse_date(_los(state, "estimated_closing_date"))
    flags = []
    checks = {"closing_date": str(closing) if closing else None}

    if not closing:
        flags.append({"substep": "13.1", "title": "Closing date unknown", "severity": "warning",
                      "details": "No closing date (ECD) available to benchmark expirations. Confirm the closing date on Processing Summary.",
                      "suggestion": "Set/confirm the closing date, then re-check expirations."})

    evaluated = 0
    for name, key, applies_corr, applies_dscr in EXPIRATION_ITEMS:
        if is_correspondent and not applies_corr:
            continue
        if is_dscr and not applies_dscr:
            continue

        exp = _parse_date(_los(state, key))
        checks[key] = str(exp) if exp else None

        if not exp:
            flags.append({"substep": "13.1", "title": f"{name}: expiration not populated", "severity": "info",
                          "details": f"No expiration date read for {name}.",
                          "suggestion": f"Verify {name} expiration on the Document Expirations screen."})
            continue

        evaluated += 1
        if closing:
            days = _days_between(closing, exp)
            if exp <= closing:
                flags.append({"substep": "13.1", "title": f"{name} expires on/before closing", "severity": "critical",
                              "details": f"{name} expires {exp}, on or before the closing date ({closing}).",
                              "suggestion": "Check the eFolder for updated docs; if not found, request updated docs from the broker."})
            else:
                flags.append({"substep": "13.1", "title": f"{name} valid through closing", "severity": "info",
                              "details": f"{name} expires {exp} ({days} day(s) after closing {closing}).",
                              "suggestion": ""})
        else:
            flags.append({"substep": "13.1", "title": f"{name}: expires {exp}", "severity": "info",
                          "details": f"{name} expiration is {exp}; compare against the confirmed closing date.",
                          "suggestion": "Confirm this is after the closing date."})

    if evaluated == 0:
        flags.append({"substep": "13.1", "title": "No expiration dates read", "severity": "warning",
                      "details": (
                          "Could not read any Document Expirations fields — verify manually that these expire AFTER closing: "
                          "Income, Asset, Credit Report, Appraisal, VVOE (not correspondent), Flood (if applicable), "
                          "Title, CPL, Credit Refresh (not correspondent/DSCR), Lock. "
                          "If any expires before closing, check the eFolder for updated docs; if not found, request from the broker."
                      ),
                      "suggestion": "Confirm the Document Expirations field IDs and re-run."})

    return make_command(tool_call_id, "Document expirations verified.", flags=flags, extra={"checks": checks})
