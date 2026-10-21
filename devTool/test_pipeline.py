#!/usr/bin/env python3
"""End-to-end test: run the full RM workflow directly (no langgraph server, no LLM).

Deterministically walks every step/substep in workflow order, calling each tool's
underlying function against Encompass (real reads) and merging the state updates —
so you can validate reads + dry-run actions without the model in the loop.

Tests: auth -> find loan -> read RM fields -> per-step tools -> flags + dry-run ledger.

Usage:  python3 devTool/test_pipeline.py [loan_number] [env] [--write]

  loan_number  defaults to 2601926378
  env          TEST | PROD   (defaults to TEST)
  --write      perform REAL writes (default is dry-run / read-only)
"""

import json
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "output"))
sys.path.insert(0, os.path.join(ROOT, "output", "tools"))

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))

logging.basicConfig(level=logging.INFO, format="%(message)s")

_args = [a for a in sys.argv[1:] if not a.startswith("--")]
LOAN_NUMBER = _args[0] if len(_args) > 0 else "2601926378"
ENV = (_args[1] if len(_args) > 1 else "TEST").upper()
FORCE_WRITE = "--write" in sys.argv[1:]


def _merge_state(state: dict, update: dict) -> None:
    """Apply a tool Command.update into state, honoring the workflow reducers."""
    for k, v in update.items():
        if v is None:
            continue
        if k in ("messages", "flags", "field_writes_ledger"):
            state.setdefault(k, [])
            state[k].extend(v if isinstance(v, list) else [v])
        elif k in ("los_fields", "doc_fields", "loan_profile", "step_reports"):
            if isinstance(v, dict):
                state.setdefault(k, {}).update(v)
            else:
                state[k] = v
        else:
            state[k] = v


def main():
    from registry import STEP_ORDER, DEV_MODE, get_step_config
    from tools import get_all_tools

    # Safety: default to dry-run unless --write is explicitly passed. write_fields
    # reads DEV_MODE from output.registry first, falling back to registry — set both.
    if not FORCE_WRITE:
        DEV_MODE.dry_run = True
        try:
            from output.registry import DEV_MODE as OUTPUT_DEV_MODE
            OUTPUT_DEV_MODE.dry_run = True
        except Exception:
            pass

    print(f"Pipeline dry_run: {DEV_MODE.dry_run}")
    print(f"Loan: {LOAN_NUMBER}, env: {ENV}\n")

    by_name = {t.name: t for t in get_all_tools()}

    state = {
        "loan_number": LOAN_NUMBER,
        "env": ENV,
        "options": {},
        "messages": [],
    }

    print("Running workflow...\n")
    for step_id in STEP_ORDER:
        cfg = get_step_config(step_id)
        if not cfg:
            continue
        print(f"── {step_id}: {cfg.name}")
        for ss_key in sorted(cfg.substeps.keys(), key=lambda x: int(x)):
            ss = cfg.substeps[ss_key]
            for tool_name in ss.tools:
                tool = by_name.get(tool_name)
                if tool is None:
                    print(f"   [{step_id}.{ss_key}] {tool_name}: NOT REGISTERED")
                    continue
                fn = getattr(tool, "func", None) or getattr(tool, "coroutine", None)
                try:
                    cmd = fn(tool_call_id=f"test-{tool_name}", state=state)
                    _merge_state(state, cmd.update)
                    # Pull the tool's own JSON result message for a one-line status
                    msg = cmd.update.get("messages", [])
                    tail = ""
                    if msg:
                        try:
                            payload = json.loads(msg[-1].content)
                            tail = payload.get("message") or payload.get("error") or ""
                        except Exception:
                            tail = ""
                    print(f"   [{step_id}.{ss_key}] {tool_name}: {tail}")
                except Exception as e:
                    print(f"   [{step_id}.{ss_key}] {tool_name}: ERROR — {str(e)[:120]}")
        print()

    # ---- Summary ----
    print("=" * 60)
    print("FINAL STATE SUMMARY")
    print("=" * 60)
    print(f"\nloan_id: {state.get('loan_id', 'NOT SET')}")

    profile = state.get("loan_profile", {})
    if profile:
        print("\nLoan Profile:")
        print(f"  Purpose: {profile.get('purpose')}  (refi={profile.get('is_refinance')})")
        print(f"  State: {profile.get('state')}   Type: {profile.get('loan_type')}")

    los = state.get("los_fields", {})
    if los:
        present = {k: v.get("value") for k, v in los.items() if v.get("value") not in (None, "", "//")}
        print(f"\nLOS Fields read: {len(present)}/{len(los)} populated")
        for k, v in present.items():
            print(f"  {k}: {v}")

    conditions = state.get("conditions")
    if conditions is not None:
        print(f"\nConditions loaded: {len(conditions)}")

    ledger = state.get("field_writes_ledger", [])
    if ledger:
        print(f"\nAction / Field-Writes Ledger: {len(ledger)} entries")
        for e in ledger:
            mode = "DRY-RUN" if e.get("dry_run") else "WRITTEN"
            target = e.get("field_id") or e.get("target") or e.get("action") or "—"
            detail = e.get("value", e.get("detail", ""))
            print(f"  [{mode}] {e.get('substep','')} {e.get('action','write')}: {target} = {str(detail)[:60]}")

    flags = state.get("flags", [])
    if flags:
        sev_order = ["critical", "warning", "info-overwrite", "info"]
        sev_label = {
            "critical": "CRITICAL",
            "warning": "WARNING",
            "info-overwrite": "AUTO-ACTION (dry-run, nothing applied)",
            "info": "INFO",
        }
        by_sev = {}
        for f in flags:
            by_sev.setdefault(f.get("severity", "info"), []).append(f)

        print("\n" + "=" * 60)
        print(f"  FLAGS ({len(flags)})")
        print("=" * 60)
        for sev in sev_order + [s for s in by_sev if s not in sev_order]:
            group = by_sev.get(sev, [])
            if not group:
                continue
            print(f"\n{sev_label.get(sev, sev.upper())}  ({len(group)})")
            for f in group:
                src = f.get("substep") or f.get("substep_name") or "—"
                print(f"  • [{src}] {f.get('title')}")
                details = (f.get("details") or "").strip()
                if details:
                    print(f"      {details}")
                sug = (f.get("suggestion") or "").strip()
                if sug:
                    print(f"      -> {sug}")

    out_path = os.path.join(os.path.dirname(__file__), "test_pipeline_output.json")
    save_state = {k: v for k, v in state.items() if k != "messages"}
    with open(out_path, "w") as f:
        json.dump(save_state, f, indent=2, default=str)
    print(f"\nFull state saved: {out_path}")


if __name__ == "__main__":
    main()
