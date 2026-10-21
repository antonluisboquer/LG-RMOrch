#!/usr/bin/env python3
"""Build the RMOrch agent input JSON.

The agent expects:
    {
      "loan_number": "...",
      "env": "Prod" | "Test",
      "options": { "allow_dft": false, "dft_reason": "", "target_ecd": "",
                    "allow_resubmit": false, "mark_not_ready": false,
                    "condition_updates": [] }
    }

Usage:
    python devTool/make_input.py 2605966627 --env Test --out input.json
    python devTool/make_input.py 2605966627 --target-ecd 08/15/2026
"""

import argparse
import json
import sys


def build_input(loan_number: str, env: str, options: dict) -> dict:
    return {
        "loan_number": str(loan_number).strip(),
        "env": env,
        "options": options,
        "messages": [],
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Build the RMOrch agent input JSON.")
    p.add_argument("loan_number", help="Encompass loan number")
    p.add_argument("--env", default="Prod", choices=["Prod", "Test"], help="Encompass environment")
    p.add_argument("--target-ecd", dest="target_ecd", default="", help="Target ECD (MM/DD/YYYY) to set in 1.4")
    p.add_argument("--allow-dft", dest="allow_dft", action="store_true", help="Allow DFT submission (1.3)")
    p.add_argument("--dft-reason", dest="dft_reason", default="", help="DFT cancellation reason")
    p.add_argument("--allow-resubmit", dest="allow_resubmit", action="store_true", help="Force resubmit to UW (4.6)")
    p.add_argument("--mark-not-ready", dest="mark_not_ready", action="store_true", help="Uncheck Cond's Ready (4.7)")
    p.add_argument("--out", default=None, help="Write to this file (default: stdout)")
    args = p.parse_args()

    options = {
        "allow_dft": args.allow_dft,
        "dft_reason": args.dft_reason,
        "target_ecd": args.target_ecd,
        "allow_resubmit": args.allow_resubmit,
        "mark_not_ready": args.mark_not_ready,
        "condition_updates": [],
    }

    payload = build_input(args.loan_number, args.env, options)
    text = json.dumps(payload, indent=2)

    if args.out:
        with open(args.out, "w") as f:
            f.write(text + "\n")
        print(f"wrote {args.out} | loan={args.loan_number} env={args.env}", file=sys.stderr)
    else:
        print(text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
