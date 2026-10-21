#!/usr/bin/env python3
"""Offline pipeline test for the RMOrch agent.

Verifies — without a live Encompass connection or the LLM — that:
1. The workflow config loads and the step map is correct.
2. Step ordering advances through all 15 steps (STEP_00 -> ... -> STEP_14).
3. Every tool named in the config has a backing implementation, and tool
   scoping exposes the right step-specific tools per step.
4. Dry-run action I/O records ledger entries + info-overwrite flags without
   touching Encompass.

Usage:  python3 devTool/test_agent_pipeline.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "output"))
sys.path.insert(0, os.path.join(ROOT, "output", "tools"))

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))

import registry
from registry import (
    STEP_ORDER, DEV_MODE, is_step_skipped, get_next_step,
    get_step_config, get_step_tools_excluding_skipped, GENERAL_TOOLS,
)

FAILURES = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}")
    if not cond:
        FAILURES.append(name)


def simulate_progression() -> list:
    """Walk the step order the way the write_todo state machine would:
    start at the first step, auto-skip skip-listed steps, land on the next
    active step, repeat until COMPLETED. Returns the list of *active* steps hit.
    """
    active_path = []
    current = STEP_ORDER[0]
    # If the first step is skipped, advance to first active.
    while current and is_step_skipped(current):
        current = get_next_step(current)

    guard = 0
    while current and guard < 100:
        guard += 1
        active_path.append(current)
        nxt = get_next_step(current)
        while nxt and is_step_skipped(nxt):
            nxt = get_next_step(nxt)
        current = nxt
    return active_path


def main():
    print("=" * 64)
    print("  RMOrch Agent — Offline Pipeline Test")
    print("=" * 64)

    # 1. Config / step map (all 15 Encompass-contained steps active)
    print("\n--- Config & Step Map ---")
    check("15 steps in step_order", len(STEP_ORDER) == 15)
    check("STEP_03 (Loan Requests) included", "STEP_03" in STEP_ORDER)
    check("STEP_09 (Third Party Orders) included", "STEP_09" in STEP_ORDER)
    check("dry_run enabled by default", DEV_MODE.dry_run is True)
    check("STEP_00 = Data Gathering", get_step_config("STEP_00").name == "Data Gathering")
    check("STEP_01 = Pipeline Management", get_step_config("STEP_01").name == "Pipeline Management")
    check("STEP_04 = Conditions Queue", get_step_config("STEP_04").name == "Conditions Queue")
    check("STEP_01 has 4 substeps", len(get_step_config("STEP_01").substeps) == 4)
    check("STEP_04 has 7 substeps", len(get_step_config("STEP_04").substeps) == 7)

    # 2. Skip logic + progression (all steps active for full e2e coverage)
    print("\n--- Skip Logic & Progression ---")
    check("no steps skipped", not DEV_MODE.skip_steps)
    check("all steps active", all(not is_step_skipped(s) for s in STEP_ORDER))

    path = simulate_progression()
    print(f"  Active step path: {path}")
    check("Progression covers all steps in order", path == list(STEP_ORDER))

    # 3. Full SOP coverage: every config tool is implemented + tool scoping
    print("\n--- SOP Tool Coverage ---")
    from tools import get_all_tools
    registered = {t.name for t in get_all_tools()}

    config_tools = set()
    missing = []
    for step_id in STEP_ORDER:
        cfg = get_step_config(step_id)
        for ss in cfg.substeps.values():
            for tname in ss.tools:
                config_tools.add(tname)
                if tname not in registered:
                    missing.append(f"{step_id}:{tname}")
    check(f"all {len(config_tools)} config tools implemented", not missing)
    if missing:
        print(f"    MISSING: {missing}")

    check("STEP_00 tools scoped", get_step_tools_excluding_skipped("STEP_00") - GENERAL_TOOLS
          == {"find_loan", "fetch_rm_fields", "fetch_doc_fields"})
    check("STEP_02 tools scoped", get_step_tools_excluding_skipped("STEP_02") - GENERAL_TOOLS
          == {"review_approval", "review_suspense"})
    check("STEP_03 tools scoped", get_step_tools_excluding_skipped("STEP_03") - GENERAL_TOOLS
          == {"submit_exception", "submit_rush_request", "submit_condo_review"})
    check("STEP_09 has 7 order tools",
          get_step_tools_excluding_skipped("STEP_09") - GENERAL_TOOLS
          == {"order_credit_refresh", "order_credit_supplement", "order_ssa_verification",
              "order_tax_transcripts", "order_vvoe", "validate_str_permit", "verify_pl"})
    check("STEP_08 has 4 appraisal tools",
          get_step_tools_excluding_skipped("STEP_08") - GENERAL_TOOLS
          == {"receive_appraisal", "review_secondary_appraisal",
              "request_appraisal_corrections", "review_disaster_inspection"})
    check("STEP_14 tools scoped", get_step_tools_excluding_skipped("STEP_14") - GENERAL_TOOLS
          == {"request_ctc_audit", "submit_ctc_review", "ctc_final_steps"})

    # 4. Dry-run action I/O (no network)
    print("\n--- Dry-Run Action I/O ---")
    from shared.conditions_io import (
        add_conversation_log_note, update_condition_status, complete_milestone,
        flush_action_ledger, flush_action_flags,
    )
    from shared.encompass_io import (
        write_fields, flush_field_writes_ledger, flush_field_writes_flags,
    )

    fake_loan = "0" * 32
    add_conversation_log_note(fake_loan, "RM file touch test note", substep="1.2")
    update_condition_status(fake_loan, "cond-123", "Cleared", substep="4.4",
                            condition_title="Test Condition")
    complete_milestone(fake_loan, "TPO Cond Submitted", substep="4.6")

    action_ledger = flush_action_ledger()
    action_flags = flush_action_flags()
    check("3 dry-run actions recorded in ledger", len(action_ledger) == 3)
    check("3 info-overwrite flags for actions",
          all(f.get("severity") == "info-overwrite" for f in action_flags) and len(action_flags) == 3)
    check("all actions marked dry_run", all(a.get("dry_run") for a in action_ledger))

    write_fields(fake_loan, {"763": "08/15/2026"}, node_id="validate_ecd", substep="1.4",
                 title="ECD Updated", details="test")
    field_ledger = flush_field_writes_ledger()
    field_flags = flush_field_writes_flags()
    check("1 dry-run field write recorded", len(field_ledger) == 1)
    check("field write is dry_run", field_ledger and field_ledger[0].get("dry_run") is True)
    check("1 info-overwrite field flag", len(field_flags) == 1)

    print("\n" + "=" * 64)
    if FAILURES:
        print(f"  RESULT: {len(FAILURES)} FAILURE(S): {FAILURES}")
        print("=" * 64)
        return 1
    print("  RESULT: ALL CHECKS PASSED")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
