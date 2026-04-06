"""
run.py  —  Start the Payroll Reconciliation Tool
─────────────────────────────────────────────────
Usage:
    python run.py
    python run.py --port 8080
    python run.py --reload      (dev mode — auto-restarts on code changes)
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Payroll Reconciliation Tool")
    parser.add_argument("--host",   default="127.0.0.1", help="Host (default: 127.0.0.1)")
    parser.add_argument("--port",   default=8000, type=int, help="Port (default: 8000)")
    parser.add_argument("--reload", action="store_true",   help="Auto-reload on code changes")
    args = parser.parse_args()

    print(f"\n  Payroll Reconciliation Tool")
    print(f"  Open in browser → http://{args.host}:{args.port}\n")

    uvicorn.run(
        "backend.api.main:app",
        host      = args.host,
        port      = args.port,
        reload    = args.reload,
        log_level = "info",
    )
