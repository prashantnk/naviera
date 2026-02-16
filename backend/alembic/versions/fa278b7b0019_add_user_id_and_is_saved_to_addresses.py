"""add_user_id_and_is_saved_to_addresses

Revision ID: fa278b7b0019
Revises: b1bd54077869
Create Date: 2026-02-01 11:54:37.597885

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fa278b7b0019"
down_revision: Union[str, Sequence[str], None] = "b1bd54077869"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Add user_id (Nullable is fine here)
    op.add_column("addresses", sa.Column("user_id", sa.Uuid(), nullable=True))

    # 2. Add address_type
    # A. Define the Enum
    address_type_enum = sa.Enum("WAREHOUSE", "CUSTOMER", "OTHER", name="addresstype")

    # B. CRITICAL FIX: Create the Type in Postgres first!
    address_type_enum.create(op.get_bind())

    # C. Now use it in the column
    op.add_column(
        "addresses",
        sa.Column(
            "address_type", address_type_enum, nullable=False, server_default="CUSTOMER"
        ),
    )

    # 3. Add is_saved with a SERVER DEFAULT
    op.add_column(
        "addresses",
        sa.Column(
            "is_saved", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )

    # 4. Create Indexes
    op.create_index(
        op.f("ix_addresses_is_saved"), "addresses", ["is_saved"], unique=False
    )
    op.create_index(
        op.f("ix_addresses_user_id"), "addresses", ["user_id"], unique=False
    )

    # 5. Create Foreign Key with an EXPLICIT NAME
    op.create_foreign_key(
        "fk_addresses_user_id", "addresses", "user", ["user_id"], ["id"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    # 1. Drop Foreign Key by its EXPLICIT NAME
    op.drop_constraint("fk_addresses_user_id", "addresses", type_="foreignkey")

    # 2. Drop Indexes
    op.drop_index(op.f("ix_addresses_user_id"), table_name="addresses")
    op.drop_index(op.f("ix_addresses_is_saved"), table_name="addresses")

    # 3. Drop Columns
    op.drop_column("addresses", "is_saved")
    op.drop_column("addresses", "address_type")
    op.drop_column("addresses", "user_id")

    # 4. Clean up the Enum type (Postgres specific)
    op.execute("DROP TYPE IF EXISTS addresstype;")
