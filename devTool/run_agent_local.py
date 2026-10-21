#!/usr/bin/env python3 -u
"""Run the RMOrch agent on a LOCAL langgraph dev server.

Expects ``langgraph dev`` running on http://127.0.0.1:2024.
Configure dry_run / skip_steps in output/config/workflow_config.json before running.

Usage:  python3 devTool/run_agent_local.py
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from langgraph_sdk import get_client

LOCAL_URL = "http://127.0.0.1:2024"
GRAPH_ID = "LG-RMOrch"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "runStates")

LOANS = [
    # {"loan_number": "2604964150", "env": "PROD", "label": "rm_test", "options": {}},
]


def log(msg=""):
    print(msg, flush=True)


async def run_loan(loan: dict):
    ln = loan["loan_number"]
    label = loan.get("label", ln)
    env = loan.get("env", "TEST")

    log(f"\n{'=' * 60}")
    log(f"  LOAN: {ln} | env={env} | label={label}")
    log(f"{'=' * 60}")

    client = get_client(url=LOCAL_URL)

    log("[1/4] Creating thread...")
    thread = await client.threads.create()
    thread_id = thread["thread_id"]
    log(f"  Thread: {thread_id}")

    run_input = {
        "loan_number": ln,
        "env": env,
        "options": loan.get("options", {}),
        "messages": [],
    }

    log("[2/4] Starting run...")
    run = await client.runs.create(
        thread_id=thread_id,
        assistant_id=GRAPH_ID,
        input=run_input,
        config={"configurable": {}},
    )
    run_id = run["run_id"]
    log(f"  Run: {run_id}")

    log("[3/4] Polling for completion...")
    start = time.time()
    last_log_time = 0

    while True:
        elapsed = time.time() - start
        try:
            r = await client.runs.get(thread_id=thread_id, run_id=run_id)
            status = r.get("status", "unknown")
        except Exception as e:
            status = "poll_error"
            log(f"  [{elapsed:.0f}s] Poll error: {e}")

        current_step = ""
        current_substep = ""
        try:
            st = await client.threads.get_state(thread_id)
            vals = st.get("values", {})
            current_step = vals.get("current_step", "")
            current_substep = vals.get("current_substep", "")
        except Exception:
            pass

        if elapsed - last_log_time >= 5:
            log(f"  [{elapsed:.0f}s] Status: {status} | Step: {current_step} | Substep: {current_substep}")
            last_log_time = elapsed

        if status in ("success", "error", "interrupted"):
            log(f"  [{elapsed:.0f}s] Final: {status} | Step: {current_step}")
            break

        if elapsed > 600:
            log(f"  [{elapsed:.0f}s] Timeout (10 min) — cancelling...")
            try:
                await client.runs.cancel(thread_id, run_id)
            except Exception as e:
                log(f"  Cancel failed: {e}")
            status = "timeout"
            break

        await asyncio.sleep(3)

    total = time.time() - start
    log(f"  Finished in {total:.1f}s — status: {status}")

    log("[4/4] Fetching final state...")
    await asyncio.sleep(1)
    try:
        state = await client.threads.get_state(thread_id=thread_id)
    except Exception as e:
        log(f"  State fetch failed: {e}")
        state = {"error": str(e), "thread_id": thread_id, "run_id": run_id, "status": status}

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    state_path = os.path.join(OUTPUT_DIR, f"agent_state_{ln}_{label}_{ts}.json")
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2, default=str)
    log(f"  State saved: {state_path}")

    values = state.get("values", state)

    step_reports = values.get("step_reports", {})
    if step_reports:
        log("\n  --- STEP REPORTS ---")
        for key in sorted(step_reports.keys()):
            val = step_reports[key]
            if not isinstance(val, dict):
                continue
            if not val.get("substep_id"):
                log(f"  {val.get('step_id', key)}: {val.get('status', '?')} — {val.get('step_name', '')}")

    all_flags = values.get("flags", [])
    if all_flags:
        critical = [f for f in all_flags if f.get("severity") == "critical" and not f.get("resolved")]
        warnings = [f for f in all_flags if f.get("severity") == "warning" and not f.get("resolved")]
        log(f"\n  Flags: {len(all_flags)} total, {len(critical)} critical, {len(warnings)} warning")
        for f in critical:
            log(f"    [CRITICAL] {f.get('title')}: {(f.get('details') or '')[:80]}")
        for f in warnings[:5]:
            log(f"    [WARNING] {f.get('title')}: {(f.get('details') or '')[:80]}")

    ledger = values.get("field_writes_ledger", [])
    log(f"\n  Action/Field ledger: {len(ledger)} entries")

    return status, state


async def main():
    if not LOANS:
        log("No loans configured. Edit the LOANS list in this file.")
        log('  LOANS = [{"loan_number": "2604964150", "env": "PROD", "label": "rm_test"}]')
        return

    log("=== RMOrch Agent — LOCAL Runner ===")
    log(f"Server: {LOCAL_URL}")
    log(f"Graph:  {GRAPH_ID}")
    log(f"Loans:  {len(LOANS)}")

    for i, loan in enumerate(LOANS):
        log(f"\n>>> Loan {i + 1}/{len(LOANS)}: {loan['loan_number']}")
        status, _ = await run_loan(loan)
        if status != "success" and i < len(LOANS) - 1:
            log(f"  WARNING: ended with '{status}', continuing...")

    log("\n=== ALL DONE ===")


if __name__ == "__main__":
    asyncio.run(main())
