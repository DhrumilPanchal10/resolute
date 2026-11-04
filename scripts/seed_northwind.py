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
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent

TENANT_NAMES = ["Northwind Corp", "Acme Inc"]
PLANS = ["starter", "pro", "enterprise"]
MRR_BY_PLAN = {"starter": 49.0, "pro": 199.0, "enterprise": 999.0}
INVOICE_STATUSES = ["open", "paid", "paid", "paid", "void"]  # mostly paid


def _rand_str(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=n))


async def run(tenants: int, accounts_per_tenant: int) -> None:
    import os

    import psycopg
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        sys.exit("DATABASE_URL is not set — add it to .env")

    conn_dsn = dsn.replace("postgresql+psycopg://", "postgresql://")
    async with await psycopg.AsyncConnection.connect(conn_dsn, autocommit=False) as conn, conn.cursor() as cur:
            for t_idx in range(tenants):
                tenant_id = str(uuid.uuid4())
                tenant_name = TENANT_NAMES[t_idx] if t_idx < len(TENANT_NAMES) else f"Tenant {t_idx + 1}"
                print(f"Seeding tenant {tenant_name} ({tenant_id})…")

                await cur.execute(
                    "INSERT INTO tenants (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (tenant_id, tenant_name),
                )

                for a_idx in range(accounts_per_tenant):
                    account_id = str(uuid.uuid4())
                    plan = random.choice(PLANS)
                    mrr = MRR_BY_PLAN[plan]
                    created_at = datetime.now(UTC) - timedelta(days=random.randint(30, 730))

                    await cur.execute(
                        "INSERT INTO accounts (id, tenant_id, name, email, plan, mrr_usd, created_at)"
                        " VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                        (
                            account_id,
                            tenant_id,
                            f"{tenant_name} Customer {a_idx + 1}",
                            f"customer{a_idx + 1}@{_rand_str(6)}.example.com",
                            plan,
                            mrr,
                            created_at,
                        ),
                    )

                    # 2–5 invoices per account
                    for inv_idx in range(random.randint(2, 5)):
                        inv_id = str(uuid.uuid4())
                        amount = round(mrr * random.uniform(0.9, 1.1), 2)
                        status = random.choice(INVOICE_STATUSES)
                        issued_at = created_at + timedelta(days=30 * inv_idx)
                        due_at = issued_at + timedelta(days=30)
                        paid_at = issued_at + timedelta(days=random.randint(1, 25)) if status == "paid" else None

                        await cur.execute(
                            "INSERT INTO invoices"
                            " (id, tenant_id, account_id, amount_usd, status, issued_at, due_at, paid_at)"
                            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                            (
                                inv_id,
                                tenant_id,
                                account_id,
                                amount,
                                status,
                                issued_at,
                                due_at,
                                paid_at,
                            ),
                        )

                await conn.commit()
                print(f"  → {accounts_per_tenant} accounts seeded for {tenant_name}")

    print("Done.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenants", type=int, default=2)
    parser.add_argument("--accounts-per-tenant", type=int, default=30)
    args = parser.parse_args()
    asyncio.run(run(args.tenants, args.accounts_per_tenant))


if __name__ == "__main__":
    main()
