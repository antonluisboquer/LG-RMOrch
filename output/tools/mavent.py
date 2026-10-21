"""STEP_10: Mavent (Wholesale Only).

10.1 review_mavent — review the loan's Mavent compliance report.
"""

import logging
from typing import Annotated

from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from ._helpers import make_command, _doc_present

logger = logging.getLogger(__name__)


def _channel(state: dict) -> str:
    """Best-effort channel: 'wholesale' | 'ndc' | 'correspondent' | 'unknown'."""
    options = state.get("options") or {}
    ch = str(options.get("channel") or "").strip().lower()
    return ch if ch in ("wholesale", "ndc", "correspondent") else "unknown"


def _mavent_status(state: dict):
    """Best-effort read of the extracted Mavent 'Review Status' from doc_fields.

    Keys are namespaced 'compliance_report.<raw_key>'; the raw key names vary, so
    match the first key that looks like a review status/result.
    """
    for key, entry in (state.get("doc_fields") or {}).items():
        if not key.startswith("compliance_report."):
            continue
        raw_key = key.split(".", 1)[1].lower()
        if any(n in raw_key for n in ("review_status", "review status", "status", "result")):
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                return str(val).strip()
    return None


@tool
def review_mavent(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """Review the Mavent compliance report (Wholesale).

    Access the Mavent Report in the eFolder. Status must be Pass or Alert. A Fail
    is acceptable only if it is a permitted fail per the Mavent spreadsheet (intranet
    / Ops Resources) OR there are SPECIFIC conversation-log notes from the Disclosure
    Desk Mgr / Ops Mgr explaining why it's acceptable for the current loan structure.
    All other fails MUST be resolved before requesting a CTC (address with Team Lead;
    if unresolved, place a support ticket). Copy all Mavent-fail communication in the
    Conversation Log. Wholesale only — not applicable to Correspondent files.
    """
    channel = _channel(state)
    flags = []

    if channel == "correspondent":
        flags.append({"substep": "10.1", "title": "Not applicable to Correspondent", "severity": "info",
                      "details": "Mavent review is a Wholesale-only RM step; Correspondent files are out of scope here.",
                      "suggestion": "Skip Mavent for Correspondent."})
        return make_command(tool_call_id, "Mavent skipped (Correspondent).", flags=flags)

    mavent_doc = _doc_present(state, "Compliance Report")
    status = _mavent_status(state) if mavent_doc else None

    # Auto-evaluate the extracted status when available.
    if status:
        s = status.lower()
        if "pass" in s:
            flags.append({"substep": "10.1", "title": f"Mavent status: {status}", "severity": "info",
                          "details": "Extracted Mavent status is a Pass — no compliance blockers.",
                          "suggestion": "OK to proceed toward CTC on the compliance check."})
        elif "alert" in s:
            flags.append({"substep": "10.1", "title": f"Mavent status: {status}", "severity": "warning",
                          "details": "Extracted Mavent status is an Alert — review the alerts before CTC.",
                          "suggestion": "Confirm alerts are acceptable for the loan structure."})
        elif "fail" in s:
            flags.append({"substep": "10.1", "title": f"Mavent status: {status}", "severity": "critical",
                          "details": "Extracted Mavent status is a FAIL. All fails must be resolved before requesting a CTC "
                                     "unless it is a permitted fail (Mavent spreadsheet) or justified via conversation-log notes.",
                          "suggestion": "Resolve the fail with your Team Lead / open a support ticket, or confirm it is a permitted fail."})
        else:
            flags.append({"substep": "10.1", "title": f"Mavent status: {status}", "severity": "warning",
                          "details": "Could not classify the extracted Mavent status; verify manually (Pass/Alert/Fail).",
                          "suggestion": "Open the Mavent report and confirm the review status."})
    else:
        flags.append({"substep": "10.1", "title": "Mavent status", "severity": "warning",
                      "details": "Verify status is Pass or Alert. All fails must be resolved prior to requesting a CTC.",
                      "suggestion": "Do not request CTC with unresolved Mavent fails."})

    flags.extend([
        {"substep": "10.1", "title": "Permitted fails", "severity": "info",
         "details": "A Fail is OK only if it is a permitted fail per the Mavent spreadsheet (intranet / Ops Resources), OR there are SPECIFIC conversation-log notes from the Disclosure Desk Mgr / Ops Mgr justifying it for the current loan structure.",
         "suggestion": "Verify permitted-fail justification or escalate to management/original approver."},
        {"substep": "10.1", "title": "Resolving fails", "severity": "info",
         "details": "For non-permitted fails: address with your Team Lead; if unresolved, place a support ticket. Copy all Mavent-fail communication in the Conversation Log.",
         "suggestion": "Document all Mavent-fail resolution in the conversation log."},
    ])

    if not mavent_doc:
        flags.append({"substep": "10.1", "title": "Mavent report not found in eFolder", "severity": "warning",
                      "details": "No Compliance Report was extracted. Mavent must be run and reviewed before CTC.",
                      "suggestion": "Run Mavent and image the report."})

    return make_command(tool_call_id, "Mavent reviewed (doc + status + checklist).", flags=flags,
                        extra={"mavent_doc_present": mavent_doc, "mavent_status": status})
