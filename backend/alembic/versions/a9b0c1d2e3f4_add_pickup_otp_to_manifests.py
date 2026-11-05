"""add_pickup_otp_to_manifests

Delhivery-style Pickup Handover OTP Verification on `manifests` (Pickup Requests / PUR).

Strictly additive and idempotent (shared Supabase PostgreSQL instance):
  1. `manifests.pickup_otp` VARCHAR(6) NULL — 6-digit cryptographically random OTP
     generated with `secrets.randbelow(900_000) + 100_000` when a Pickup Request
     (`Manifest`, including blind pickups) is created or lazily accessed while open.
  2. `manifests.pickup_otp_verified_at` TIMESTAMP WITH TIME ZONE NULL — UTC timestamp
     when the pickup executive verified the OTP (or Owner/Admin overrode it) on dispatch.
  3. `manifests.pickup_otp_verified_by` UUID NULL REFERENCES "user"(id) ON DELETE SET NULL —
     actor who verified or overrode the pickup OTP.
  4. `manifests.pickup_otp_override_reason` VARCHAR(255) NULL — mandatory audit reason
     when an Owner/Admin overrides pickup OTP verification.
  5. Backfills a 6-digit `secrets`-generated `pickup_otp` for any existing open
     (`SCHEDULED`, `OUT_FOR_PICKUP`) manifests where `pickup_otp IS NULL`.

Revision ID: a9b0c1d2e3f4
Revises: f9a0b1c2d3e4
Create Date: 2026-11-05 03:49:00.000000

"""
import secrets
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a9b0c1d2e3f4"
down_revision: Union[str, Sequence[str], None] = "f9a0b1c2d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _generate_pickup_otp() -> str:
    return f"{secrets.randbelow(900_000) + 100_000:06d}"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE manifests ADD COLUMN IF NOT EXISTS pickup_otp VARCHAR(6) NULL"
    )
    op.execute(
        "ALTER TABLE manifests ADD COLUMN IF NOT EXISTS pickup_otp_verified_at "
        "TIMESTAMP WITH TIME ZONE NULL"
    )
    op.execute(
        "ALTER TABLE manifests ADD COLUMN IF NOT EXISTS pickup_otp_verified_by "
        'UUID NULL REFERENCES "user"(id) ON DELETE SET NULL'
    )
    op.execute(
        "ALTER TABLE manifests ADD COLUMN IF NOT EXISTS pickup_otp_override_reason "
        "VARCHAR(255) NULL"
    )

    bind = op.get_bind()
    open_ids = (
        bind.execute(
            sa.text(
                "SELECT id FROM manifests "
                "WHERE status::text IN ('SCHEDULED', 'OUT_FOR_PICKUP') "
                "AND pickup_otp IS NULL"
            )
        )
        .scalars()
        .all()
    )
    for manifest_id in open_ids:
        bind.execute(
            sa.text(
                "UPDATE manifests SET pickup_otp = :otp "
                "WHERE id = :manifest_id AND pickup_otp IS NULL"
            ),
            {"otp": _generate_pickup_otp(), "manifest_id": manifest_id},
        )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE manifests DROP COLUMN IF EXISTS pickup_otp_override_reason"
    )
    op.execute("ALTER TABLE manifests DROP COLUMN IF EXISTS pickup_otp_verified_by")
    op.execute("ALTER TABLE manifests DROP COLUMN IF EXISTS pickup_otp_verified_at")
    op.execute("ALTER TABLE manifests DROP COLUMN IF EXISTS pickup_otp")
