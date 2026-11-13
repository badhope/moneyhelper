"""Seed the demo ledger into the data dir selected by MONEYHELPER_DATA_DIR.

Usage (PowerShell):
  $env:MONEYHELPER_DATA_DIR="D:\Moneyhelper\.tmp\demo"
  $env:PYTHONPATH="D:\Moneyhelper\backend"
  D:\Moneyhelper\.venv\Scripts\python.exe scripts\seed-demo.py

This only touches the selected data dir; it never falls back to the real ledger
unless MONEYHELPER_DATA_DIR is unset.
"""

from __future__ import annotations

import asyncio
import os

from app import db


async def main() -> None:
    data_dir = os.environ.get("MONEYHELPER_DATA_DIR", "").strip()
    if not data_dir:
        raise SystemExit("Refusing to seed without MONEYHELPER_DATA_DIR (safety guard).")
    await db.init_db()
    await db.reset_to_seed()
    positions = await db.list_positions()
    transactions = await db.list_transactions()
    print(
        f"seeded into {data_dir}: positions={len(positions)} "
        f"transactions={len(transactions)}"
    )
    await db.close_db()


if __name__ == "__main__":
    asyncio.run(main())
