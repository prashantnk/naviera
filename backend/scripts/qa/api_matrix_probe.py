"""Reusable API, Public SSR, and PostgreSQL Integrity Oracle probe (`logismart-test` ONLY).

Combines three standalone QA verification probes used in Phase-1 Handover QA:
1. `oracle` (Read-only SQL): Verifies directly against PostgreSQL inside a `READ ONLY`
   rolled-back transaction that:
   - Every `user_wallets.balance` equals the signed sum of its `COMPLETED` ledger rows
     and every transaction's `closing_balance == opening_balance +/- amount`.
   - Every GST document series (`LTST2627I`, `LTST2627C`, `LTST2627D`) is unique and
     contiguous from `1`.
   - Every non-`DRAFT` shipment has `>= 1` `ShipmentActivity` and `<= 1` `INVOICE`.
2. `pages` (Read-only HTTP SSR): Verifies all 14 public marketing, legal, auth, and
   tracking routes on `--frontend-url` (plus optional `--tracking-id` PII/freight mask
   check) return expected status codes, include tenant branding, and emit zero Next.js
   error markers.
3. `auth` (Throwaway QA signup/login probe on `logismart-test`): Verifies `POST
   /users/auth/signup` (201/409), wrong password (401), valid password `POST
   /users/auth/login` (200 + token), `/users/me` (200), `/wallet` (200), live-tenant
   refusal (403), owner deactivation (200), and deactivated login refusal (403).

Usage (from `backend/`):
    poetry run python -m scripts.qa.api_matrix_probe --mode oracle
    poetry run python -m scripts.qa.api_matrix_probe --mode pages --frontend-url http://localhost:3000
    poetry run python -m scripts.qa.api_matrix_probe --mode auth --api-url http://localhost:8000/api/v1
    poetry run python -m scripts.qa.api_matrix_probe --mode all
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

import httpx
from sqlalchemy import text

from app.core.db import AsyncSessionLocal
from app.models.wallet import WalletTxnDirection, WalletTxnType, wallet_txn_direction
from scripts.tenant_data_core import assert_test_tenant_slug
from scripts.tests.golden_journeys.golden_env import OWNER_EMAIL, headers, load_accounts

DEFAULT_SLUG = "logismart-test"
Q = Decimal("0.01")

PUBLIC_PAGES: list[tuple[str, int]] = [
    ("", 200),
    ("/about", 200),
    ("/services", 200),
    ("/contact", 200),
    ("/privacy", 200),
    ("/terms", 200),
    ("/refund-policy", 200),
    ("/prohibited-items", 200),
    ("/grievance", 200),
    ("/track", 200),
    ("/login", 200),
    ("/no-such-page-qa-probe", 404),
    ("/dashboard", 200),
    ("/b2b/shipments/new/reverse", 200),
]
ERROR_MARKERS = (
    "Application error",
    "Internal Server Error",
    "Unhandled Runtime Error",
    "__next_error__",
)


def _quantize(val: object) -> Decimal:
    return Decimal(str(val or 0)).quantize(Q, rounding=ROUND_HALF_UP)


async def run_sql_oracle(slug: str) -> dict[str, object]:
    assert_test_tenant_slug(slug)
    failures: list[str] = []
    out: dict[str, object] = {"failures": failures}
    async with AsyncSessionLocal() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        tid = (
            await session.execute(
                text("SELECT id FROM tenant WHERE slug = :s"), {"s": slug}
            )
        ).scalar_one()
        wallets = (
            (
                await session.execute(
                    text(
                        "SELECT id, user_id, balance FROM user_wallets "
                        "WHERE tenant_id = :t"
                    ),
                    {"t": tid},
                )
            )
            .mappings()
            .all()
        )
        txns = (
            (
                await session.execute(
                    text(
                        "SELECT wallet_id, txn_type::text AS t, status::text AS st, "
                        "amount, opening_balance, closing_balance, receipt_number "
                        "FROM wallet_transactions WHERE tenant_id = :t"
                    ),
                    {"t": tid},
                )
            )
            .mappings()
            .all()
        )
        by_wallet: dict[object, list[dict[str, object]]] = defaultdict(list)
        for row in txns:
            by_wallet[row["wallet_id"]].append(dict(row))

        wallet_ok = 0
        for wallet in wallets:
            ledger = Decimal("0.00")
            for row in by_wallet[wallet["id"]]:
                if row["st"] != "COMPLETED":
                    continue
                credit = (
                    wallet_txn_direction(WalletTxnType(str(row["t"])))
                    == WalletTxnDirection.CREDIT
                )
                signed = (
                    _quantize(row["amount"]) if credit else -_quantize(row["amount"])
                )
                if (
                    _quantize(row["closing_balance"])
                    != _quantize(row["opening_balance"]) + signed
                ):
                    failures.append(
                        f"txn {row['receipt_number']}: closing != opening + signed"
                    )
                ledger += signed
            if _quantize(wallet["balance"]) != ledger:
                failures.append(
                    f"wallet {wallet['id']} (user {wallet['user_id']}): "
                    f"balance {_quantize(wallet['balance'])} != ledger {ledger}"
                )
            else:
                wallet_ok += 1
        out["wallets"] = {
            "total": len(wallets),
            "balance_eq_ledger": wallet_ok,
            "txns": len(txns),
        }

        docs = (
            (
                await session.execute(
                    text(
                        "SELECT invoice_number, note_type::text AS nt, "
                        "original_invoice_id, merchant_user_id "
                        "FROM billing_invoices WHERE tenant_id = :t"
                    ),
                    {"t": tid},
                )
            )
            .mappings()
            .all()
        )
        series: dict[str, list[int]] = defaultdict(list)
        for doc in docs:
            mt = re.match(r"^(.*?)(\d+)$", str(doc["invoice_number"] or ""))
            if mt:
                series[mt.group(1)].append(int(mt.group(2)))
        seq_report: dict[str, dict[str, object]] = {}
        for prefix, nums in series.items():
            nums_sorted = sorted(nums)
            contiguous = nums_sorted == list(range(1, len(nums_sorted) + 1))
            seq_report[prefix] = {
                "count": len(nums),
                "max": max(nums),
                "unique": len(set(nums)) == len(nums),
                "contiguous_from_1": contiguous,
            }
            if len(set(nums)) != len(nums):
                failures.append(f"GST series {prefix}: duplicate numbers")
            if not contiguous:
                failures.append(
                    f"GST series {prefix}: gap in numbering {nums_sorted[:5]}.."
                )
        out["gst_series"] = seq_report
        gst_by_type: dict[str, int] = {}
        for doc in docs:
            nt = str(doc["nt"])
            gst_by_type[nt] = gst_by_type.get(nt, 0) + 1
        out["gst_by_type"] = gst_by_type

        statuses = (
            (
                await session.execute(
                    text(
                        "SELECT status::text AS st, count(*) AS n "
                        "FROM pickups WHERE tenant_id = :t GROUP BY 1 ORDER BY 1"
                    ),
                    {"t": tid},
                )
            )
            .mappings()
            .all()
        )
        out["shipments_by_status"] = {str(r["st"]): int(r["n"]) for r in statuses}
        no_activity = (
            (
                await session.execute(
                    text(
                        "SELECT p.tracking_id FROM pickups p "
                        "WHERE p.tenant_id = :t AND p.status::text <> 'DRAFT' "
                        "AND NOT EXISTS ("
                        "SELECT 1 FROM shipment_activities a WHERE a.pickup_id = p.id"
                        ")"
                    ),
                    {"t": tid},
                )
            )
            .scalars()
            .all()
        )
        out["shipments_without_activity"] = len(no_activity)
        if no_activity:
            failures.append(
                f"{len(no_activity)} non-draft shipments have no activity row: "
                f"{no_activity[:3]}"
            )
        multi_invoice = (
            await session.execute(
                text(
                    "SELECT shipment_id, count(*) FROM billing_invoices "
                    "WHERE tenant_id = :t AND note_type::text = 'INVOICE' "
                    "AND shipment_id IS NOT NULL GROUP BY 1 HAVING count(*) > 1"
                ),
                {"t": tid},
            )
        ).all()
        if multi_invoice:
            failures.append(f"{len(multi_invoice)} shipments with >1 INVOICE")
        out["activities"] = (
            await session.execute(
                text(
                    "SELECT count(*) FROM shipment_activities a "
                    "JOIN pickups p ON p.id = a.pickup_id WHERE p.tenant_id = :t"
                ),
                {"t": tid},
            )
        ).scalar_one()
        await session.rollback()

    out["result"] = "PASS" if not failures else "FAIL"
    print(json.dumps(out, indent=2, default=str))
    return out


def _fetch_page(url: str) -> tuple[int, str, float]:
    start = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": "naviera-qa-probe"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return (
                resp.status,
                resp.read().decode("utf-8", "replace"),
                time.time() - start,
            )
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode("utf-8", "replace"), time.time() - start


def run_pages_probe(
    slug: str, frontend_url: str, tracking_id: str = ""
) -> list[dict[str, object]]:
    assert_test_tenant_slug(slug)
    results: list[dict[str, object]] = []
    paths = list(PUBLIC_PAGES)
    if tracking_id:
        paths.append((f"/track/{tracking_id}", 200))
    base = frontend_url.rstrip("/")
    for path, expected in paths:
        url = f"{base}/{slug}{path}"
        status, body, secs = _fetch_page(url)
        problems: list[str] = []
        if status != expected:
            problems.append(f"status {status} != {expected}")
        if expected == 200:
            if "<html" not in body.lower():
                problems.append("no <html>")
            if "logismart" not in body.lower():
                problems.append("brand 'Logismart' missing")
            problems.extend(f"marker '{m}'" for m in ERROR_MARKERS if m in body)
        if path.startswith("/track/") and tracking_id:
            if re.search(r"(?<!\d)[6-9]\d{9}(?!\d)", body):
                problems.append("unmasked 10-digit phone in SSR HTML")
            if "₹" in body:
                problems.append("rupee amount in public tracking HTML")
        row = {
            "path": path or "/",
            "status": status,
            "secs": round(secs, 2),
            "ok": not problems,
            "problems": problems,
        }
        results.append(row)
        print(("PASS " if row["ok"] else "FAIL ") + json.dumps(row))
    ok_count = sum(1 for r in results if r["ok"])
    print(f"PAGES SUMMARY {ok_count} / {len(results)}")
    return results


async def run_auth_probe(
    slug: str, api_url: str, email: str
) -> list[dict[str, object]]:
    assert_test_tenant_slug(slug)
    pw = os.environ.get("QA_PROBE_PASSWORD") or (secrets.token_urlsafe(18) + "aA1!")
    tenant_hdr = {"X-Tenant-Slug": slug}
    rows: list[dict[str, object]] = []

    def rec(name: str, ok: bool, detail: str, secs: float) -> None:
        rows.append(
            {"check": name, "ok": ok, "detail": detail, "secs": round(secs, 2)}
        )

    async with httpx.AsyncClient(base_url=api_url.rstrip("/"), timeout=60) as client:
        t0 = time.time()
        r = await client.post(
            "/users/auth/signup",
            headers=tenant_hdr,
            json={
                "email": email,
                "password": pw,
                "full_name": "QA Auth Probe",
                "terms_accepted": True,
            },
        )
        rec(
            "signup 201 (or 409 if re-run)",
            r.status_code in (201, 409),
            str(r.status_code),
            time.time() - t0,
        )

        t0 = time.time()
        r = await client.post(
            "/users/auth/signup",
            headers=tenant_hdr,
            json={"email": email, "password": pw, "terms_accepted": True},
        )
        rec(
            "duplicate signup 409",
            r.status_code == 409,
            str(r.status_code),
            time.time() - t0,
        )

        t0 = time.time()
        r = await client.post(
            "/users/auth/login",
            headers=tenant_hdr,
            json={"email": email, "password": pw + "x"},
        )
        rec(
            "wrong password 401",
            r.status_code == 401,
            str(r.status_code),
            time.time() - t0,
        )

        t0 = time.time()
        r = await client.post(
            "/users/auth/login",
            headers=tenant_hdr,
            json={"email": email, "password": pw},
        )
        ok = r.status_code == 200 and bool(r.json().get("access_token"))
        rec(
            "password login 200 + access_token",
            ok,
            str(r.status_code),
            time.time() - t0,
        )
        token = r.json().get("access_token") if ok else None
        user_id = None
        if token:
            t0 = time.time()
            me = await client.get(
                "/users/me",
                headers={**tenant_hdr, "Authorization": f"Bearer {token}"},
            )
            body = me.json() if me.status_code == 200 else {}
            user_id = body.get("id")
            rec(
                "/users/me with real token -> customer",
                me.status_code == 200
                and body.get("role") == "customer"
                and body.get("email") == email,
                f"{me.status_code} role={body.get('role')}",
                time.time() - t0,
            )
            wallet = await client.get(
                "/wallet",
                headers={**tenant_hdr, "Authorization": f"Bearer {token}"},
            )
            rec(
                "new customer wallet readable",
                wallet.status_code == 200,
                str(wallet.status_code),
                0.0,
            )
            cross = await client.get(
                "/users/me",
                headers={
                    "X-Tenant-Slug": "logismart",
                    "Authorization": f"Bearer {token}",
                },
            )
            rec(
                "token refused on live tenant",
                cross.status_code in (401, 403, 404),
                str(cross.status_code),
                0.0,
            )
        if user_id:
            accounts = await load_accounts()
            owner_hdr = headers(accounts, OWNER_EMAIL)
            t0 = time.time()
            deact = await client.patch(
                f"/users/{user_id}", headers=owner_hdr, json={"is_active": False}
            )
            rec(
                "owner deactivates QA user",
                deact.status_code == 200,
                str(deact.status_code),
                time.time() - t0,
            )
            again = await client.post(
                "/users/auth/login",
                headers=tenant_hdr,
                json={"email": email, "password": pw},
            )
            if again.status_code == 200:
                me2 = await client.get(
                    "/users/me",
                    headers={
                        **tenant_hdr,
                        "Authorization": f"Bearer {again.json()['access_token']}",
                    },
                )
                rec(
                    "deactivated user cannot use the app",
                    me2.status_code in (401, 403),
                    f"login {again.status_code}, /me {me2.status_code}",
                    0.0,
                )
            else:
                rec(
                    "deactivated user cannot log in",
                    again.status_code in (401, 403),
                    str(again.status_code),
                    0.0,
                )

    for row in rows:
        print(("PASS " if row["ok"] else "FAIL ") + json.dumps(row))
    ok_count = sum(1 for r in rows if r["ok"])
    print(f"AUTH SUMMARY {ok_count} / {len(rows)}")
    return rows


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("oracle", "pages", "auth", "all"),
        default="all",
        help="Which probe(s) to execute",
    )
    parser.add_argument("--tenant", default=DEFAULT_SLUG, help="Test tenant slug")
    parser.add_argument(
        "--api-url",
        default=os.environ.get("QA_API_URL", "http://localhost:8000/api/v1"),
        help="Base API v1 URL",
    )
    parser.add_argument(
        "--frontend-url",
        default=os.environ.get("QA_FRONTEND_URL", "http://localhost:3000"),
        help="Base Frontend URL",
    )
    parser.add_argument(
        "--tracking-id",
        default="",
        help="Optional tracking_id for /track/<id> SSR PII/rupee mask check",
    )
    parser.add_argument(
        "--auth-email",
        default=os.environ.get(
            "QA_AUTH_EMAIL",
            f"qa-probe-{int(time.time())}@logismart-test.invalid",
        ),
        help="Throwaway email for --mode auth",
    )
    parser.add_argument(
        "--include-auth",
        action="store_true",
        help="Include throwaway signup/login probe when running --mode all",
    )
    return parser.parse_args()


async def _async_main() -> int:
    args = _parse_args()
    assert_test_tenant_slug(args.tenant)
    ok = True
    if args.mode in ("oracle", "all"):
        res = await run_sql_oracle(args.tenant)
        if res.get("result") != "PASS":
            ok = False
    if args.mode in ("pages", "all"):
        page_rows = run_pages_probe(args.tenant, args.frontend_url, args.tracking_id)
        if not all(r["ok"] for r in page_rows):
            ok = False
    if args.mode == "auth" or (args.mode == "all" and args.include_auth):
        auth_rows = await run_auth_probe(args.tenant, args.api_url, args.auth_email)
        if not all(r["ok"] for r in auth_rows):
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_async_main()))
