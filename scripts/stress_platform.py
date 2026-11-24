"""4.17.0 可复现压测：个人千万资产、企业多主体总账、SQLite 并发读写。

不碰真实数据：启动前把 MONEYHELPER_DATA_DIR 指到临时目录。
输出 docs/stress-4.17.0.json，失败样本一并保留。
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["MONEYHELPER_DATA_DIR"] = tempfile.mkdtemp(prefix="mh-stress-")
os.environ.setdefault("VAULT_PASSPHRASE", "stress-passphrase-1234567890")
os.environ.setdefault("JWT_SECRET", "stress-jwt-secret-1234567890")

from app import db  # noqa: E402
from app.calculations import calculate_health_score, tax_summary  # noqa: E402
from app.calculations.health import HealthInputs  # noqa: E402


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    idx = min(len(values) - 1, max(0, round((len(values) - 1) * p)))
    return round(values[idx], 3)


async def personal_10m() -> dict:
    positions = [
        {
            "name": f"资产-{i:04d}",
            "kind": "股票" if i % 3 else "基金",
            "market_value": 10_000_000 / 2000,
        }
        for i in range(2000)
    ]
    positions.append({"name": "现金", "kind": "现金", "market_value": 200_000})
    inputs = HealthInputs(
        monthly_income=80_000,
        monthly_expense=45_000,
        monthly_debt_payment=12_000,
        cash_balance=200_000,
        essential_monthly_expense=30_000,
        positions=positions,
    )
    times: list[float] = []
    for _ in range(100):
        t0 = time.perf_counter()
        score = calculate_health_score(inputs)
        times.append((time.perf_counter() - t0) * 1000)
    return {
        "positions": len(positions),
        "total_market_value": round(sum(p["market_value"] for p in positions), 2),
        "runs": len(times),
        "p50_ms": _pct(times, 0.50),
        "p95_ms": _pct(times, 0.95),
        "max_ms": round(max(times), 3),
        "score_sample": score.score,
        "grade_sample": score.grade,
    }


async def tax_multi_entity() -> dict:
    times: list[float] = []
    entities = 100
    months = 12
    failures = 0
    total_tax = 0.0
    for e in range(entities):
        for m in range(months):
            revenue = 2_000_000 + e * 15_000 + m * 8_000
            cost = revenue * (0.52 + (m % 5) * 0.01)
            t0 = time.perf_counter()
            try:
                out = tax_summary(
                    revenue=revenue,
                    cost=cost,
                    expenses=revenue * 0.12,
                    vat_rate=0.13 if e % 4 else 0.09,
                    payroll_gross=80_000 + e * 500,
                    payroll_months=12,
                )
                total_tax += float(out["total_tax"])
            except Exception:  # noqa: BLE001 — 压测保留失败计数
                failures += 1
            times.append((time.perf_counter() - t0) * 1000)
    return {
        "entities": entities,
        "months_per_entity": months,
        "runs": len(times),
        "failures": failures,
        "p50_ms": _pct(times, 0.50),
        "p95_ms": _pct(times, 0.95),
        "max_ms": round(max(times), 3),
        "total_tax": round(total_tax, 2),
    }


async def enterprise_ledger() -> dict:
    await db.init_db()
    entities = 10
    periods = 12
    entries_per_period = 20
    t0 = time.perf_counter()
    created = 0
    for tenant in range(entities):
        await db.gl_bootstrap(tenant, ref_date=date.today().isoformat())
        accounts = await db.gl_list_accounts(tenant)
        cash = next(a for a in accounts if str(a["code"]) == "1001")
        rent = next(a for a in accounts if str(a["code"]) == "6602")
        existing = {
            (int(p["year"]), int(p["month"])) for p in await db.gl_list_periods(tenant)
        }
        for m in range(periods):
            if (2026, m + 1) not in existing:
                await db.gl_create_period(tenant, 2026, m + 1)
            day = date(2026, m + 1, 15).isoformat()
            for n in range(entries_per_period):
                await db.gl_create_entry(
                    tenant,
                    day,
                    f"压测-{tenant}-{m}-{n}",
                    [
                        {"account_id": cash["id"], "debit": 100 + n, "credit": 0},
                        {"account_id": rent["id"], "debit": 0, "credit": 100 + n},
                    ],
                )
                created += 1
    elapsed = time.perf_counter() - t0
    return {
        "entities": entities,
        "periods": periods,
        "entries_per_period": entries_per_period,
        "entries": created,
        "elapsed_s": round(elapsed, 3),
        "entries_per_s": round(created / elapsed, 1),
    }


async def sqlite_concurrency() -> dict:
    writers = 32
    each = 20
    errors: list[str] = []
    latencies: list[float] = []

    async def writer(w: int) -> None:
        for n in range(each):
            t0 = time.perf_counter()
            try:
                await db.add_transaction(
                    "2026-11-24", f"并发-{w}-{n}", "测试", 1.25 + n * 0.01
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{type(exc).__name__}: {exc}")
            latencies.append((time.perf_counter() - t0) * 1000)

    t0 = time.perf_counter()
    await asyncio.gather(*(writer(i) for i in range(writers)))
    elapsed = time.perf_counter() - t0
    return {
        "writers": writers,
        "writes_per_writer": each,
        "writes": writers * each,
        "errors": len(errors),
        "error_samples": errors[:5],
        "elapsed_s": round(elapsed, 3),
        "writes_per_s": round((writers * each) / elapsed, 1),
        "p50_ms": _pct(latencies, 0.50),
        "p95_ms": _pct(latencies, 0.95),
        "max_ms": round(max(latencies), 3),
    }


async def main() -> None:
    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "personal_10m": await personal_10m(),
        "tax_multi_entity": await tax_multi_entity(),
        "enterprise_ledger": await enterprise_ledger(),
        "sqlite_concurrency": await sqlite_concurrency(),
        "boundary": "确定性计算与本地 SQLite 压测；不含税局/银行外部接口，不等于 100% 场景覆盖。",
    }
    path = ROOT / "docs" / "stress-4.17.0.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"written: {path}")
    await db.close_db()


if __name__ == "__main__":
    asyncio.run(main())
