#!/usr/bin/env python3
"""Seed the database with 2 tenants × 30 accounts, invoices, and synthetic logs.

Used by T4.3 (accounts MCP server) and T7.3 (action scenarios).
Requires DATABASE_URL in .env.

Usage:
    python scripts/seed_northwind.py
    python scripts/seed_northwind.py --tenants 2 --accounts-per-tenant 30
"""
from __future__ import annotations

import argparse
import asyncio
import random
import string
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _rand_str(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=n))


async def run(tenants: int, accounts_per_tenant: int) -> None:
    import os

    from dotenv import load_dotenv
    import psycopg

    load_dotenv(ROOT / ".env")
    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        sys.exit("DATABASE_URL is not set — add it to .env")

    # psycopg async connection
    conn_dsn = dsn.replace("postgresql+psycopg://", "postgresql://")
    async with await psycopg.AsyncConnection.connect(conn_dsn) as conn:
        async with conn.cursor() as cur:
            for t_idx in range(tenants):
                tenant_id = f"tenant-{_rand_str(6)}"
                print(f"Seeding tenant {tenant_id}…")

                # Insert tenant
                await cur.execute(
                    "INSERT INTO tenants (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (tenant_id, f"Northwind Corp {t_idx + 1}"),
                )

                for a_idx in range(accounts_per_tenant):
                    account_id = f"acct-{_rand_str(8)}"
                    plan = random.choice(["starter", "pro", "enterprise"])
                    await cur.execute(
                        "INSERT INTO accounts (id, tenant_id, name, plan, created_at)"
                        " VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                        (
                            account_id,
                            tenant_id,
                            f"Customer {a_idx + 1}",
                            plan,
                            datetime.now(UTC) - timedelta(days=random.randint(1, 365)),
                        ),
                    )

                    # 1-3 invoices per account
                    for _ in range(random.randint(1, 3)):
                        inv_id = f"inv-{_rand_str(8)}"
                        amount = round(random.uniform(49.0, 999.0), 2)
                        await cur.execute(
                            "INSERT INTO invoices (id, account_id, tenant_id, amount_usd, status, created_at)"
                            " VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                            (
                                inv_id,
                                account_id,
                                tenant_id,
                                amount,
                                random.choice(["paid", "unpaid", "overdue"]),
                                datetime.now(UTC) - timedelta(days=random.randint(0, 90)),
                            ),
                        )

                    # 2-5 log entries per account
                    for _ in range(random.randint(2, 5)):
                        await cur.execute(
                            "INSERT INTO logs (account_id, tenant_id, level, message, occurred_at)"
                            " VALUES (%s, %s, %s, %s, %s)",
                            (
                                account_id,
                                tenant_id,
                                random.choice(["INFO", "WARN", "ERROR"]),
                                f"Synthetic log entry for {account_id}",
                                datetime.now(UTC) - timedelta(minutes=random.randint(0, 10080)),
                            ),
                        )

                await conn.commit()
                print(f"  → {accounts_per_tenant} accounts seeded for {tenant_id}")

    print("Done.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenants", type=int, default=2)
    parser.add_argument("--accounts-per-tenant", type=int, default=30)
    args = parser.parse_args()
    asyncio.run(run(args.tenants, args.accounts_per_tenant))


if __name__ == "__main__":
    main()
