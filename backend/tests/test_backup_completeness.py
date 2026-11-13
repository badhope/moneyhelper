"""备份契约：模拟盘、净值快照、家庭议案、再平衡/定投/财报必须可导出并可恢复。

此前这些表不在 JSON 备份里，换机后净值曲线、模拟盘历史、家庭议案会静默丢失；
本用例锁住"导出有键 + 恢复有行"的完整往返。
"""

from __future__ import annotations

from app import db


async def test_backup_includes_and_restores_extended_tables(temp_db) -> None:
    conn = await db._conn()
    await conn.executemany(
        "INSERT INTO paper_accounts(user_id,account_id,name,initial_cash,created_at)"
        " VALUES(0,?,?,?,?)",
        [("acc-1", "团队一号", 100000.0, "2026-01-01T00:00:00+08:00")],
    )
    await conn.execute(
        "INSERT INTO paper_trades(user_id,account_id,date,symbol,name,side,price,shares,fee,amount)"
        " VALUES(0,'acc-1','2026-01-02T09:30:00+08:00','600519','贵州茅台','buy',1500,10,5,15000)"
    )
    await conn.execute(
        "INSERT INTO paper_snapshots(user_id,account_id,date,equity,cash,market_value)"
        " VALUES(0,'acc-1','2026-01-02',101000,85000,16000)"
    )
    await conn.execute(
        "INSERT INTO net_worth_snapshots(user_id,date,total_assets,total_liabilities,"
        "net_worth,cash,market_value,source,created_at)"
        " VALUES(0,'2026-01-02',120000,20000,100000,30000,90000,'quotes','2026-01-02')"
    )
    await conn.execute(
        "INSERT INTO family_motions(user_id,id,title,amount,category,note,proposer_id,status,created_at,decided_at)"
        " VALUES(0,'m-1','换车',200000,'大额','',1,'voting','2026-01-01','')"
    )
    await conn.execute(
        "INSERT INTO family_votes(user_id,motion_id,member_id,vote,note,created_at)"
        " VALUES(0,'m-1',1,'yes','','2026-01-01')"
    )
    await conn.execute(
        "INSERT INTO allocation_targets(user_id,symbol,name,target_pct,updated_at)"
        " VALUES(0,'600519','贵州茅台',20,'2026-01-01')"
    )
    await conn.execute(
        "INSERT INTO dca_plans(user_id,id,symbol,name,amount,frequency,day,start_date,note,active,created_at)"
        " VALUES(0,'d-1','000001','沪深300',3000,'monthly',10,'2026-01-01','',1,'2026-01-01')"
    )
    await conn.execute(
        "INSERT INTO financial_statements(user_id,id,company,currency,payload,report,created_at)"
        " VALUES(0,'f-1','示例公司','CNY','{}','', '2026-01-01')"
    )
    await conn.commit()

    data = await db.export_data()
    for key in (
        "paper_accounts",
        "paper_trades",
        "paper_snapshots",
        "net_worth_snapshots",
        "family_motions",
        "family_votes",
        "allocation_targets",
        "dca_plans",
        "financial_statements",
    ):
        assert data.get(key), f"备份缺少 {key}"

    counts = await db.import_backup(data)
    for key in (
        "paper_accounts",
        "paper_trades",
        "paper_snapshots",
        "net_worth_snapshots",
        "family_motions",
        "family_votes",
        "allocation_targets",
        "dca_plans",
        "financial_statements",
    ):
        assert counts.get(key) == 1, f"{key} 恢复行数={counts.get(key)}"
