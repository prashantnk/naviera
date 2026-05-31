"""add_product_category_enum

Revision ID: 216a08d0513c
Revises: 6394446c4c94
Create Date: 2026-05-31 12:40:09.231314

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '216a08d0513c'
down_revision: Union[str, Sequence[str], None] = '6394446c4c94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Add the new nullable other_category_description column
    op.add_column('pickups', sa.Column('other_category_description', sa.String(), nullable=True))
    
    # 2. Create the PostgreSQL native ENUM type
    product_category_enum = sa.Enum(
        'HOUSEHOLD_PERSONAL', 'VEHICLE', 'DOCUMENTS', 'HAZARDOUS', 
        'COMMERCIAL', 'ELECTRONICS', 'APPAREL', 'OTHER', 
        name='productcategory'
    )
    product_category_enum.create(op.get_bind(), checkfirst=True)

    # 3. Data Migration: Standardise, clean, and map existing values
    
    # Step A: Map empty/null values to OTHER with a default explanation
    op.execute(
        "UPDATE pickups SET "
        "other_category_description = COALESCE(other_category_description, 'Legacy Booking'), "
        "product_category = 'OTHER' "
        "WHERE product_category IS NULL OR TRIM(product_category) = ''"
    )

    # Step B: Standardise recognized free-text terms case-insensitively to the strict enums
    op.execute(
        "UPDATE pickups SET product_category = 'ELECTRONICS' "
        "WHERE LOWER(product_category) IN ('electronics', 'laptop', 'computer', 'phone', 'phones')"
    )
    op.execute(
        "UPDATE pickups SET product_category = 'APPAREL' "
        "WHERE LOWER(product_category) IN ('apparel', 'clothing', 'clothes', 'garments', 'shoes')"
    )
    op.execute(
        "UPDATE pickups SET product_category = 'VEHICLE' "
        "WHERE LOWER(product_category) IN ('vehicle', 'vehicles', 'car', 'bike', 'scooter')"
    )
    op.execute(
        "UPDATE pickups SET product_category = 'DOCUMENTS' "
        "WHERE LOWER(product_category) IN ('documents', 'document', 'papers', 'paper', 'letters')"
    )
    op.execute(
        "UPDATE pickups SET product_category = 'HAZARDOUS' "
        "WHERE LOWER(product_category) IN ('hazardous', 'hazard', 'chemical', 'chemicals', 'battery')"
    )
    op.execute(
        "UPDATE pickups SET product_category = 'COMMERCIAL' "
        "WHERE LOWER(product_category) IN ('commercial', 'b2b', 'cargo', 'wholesale')"
    )
    op.execute(
        "UPDATE pickups SET product_category = 'HOUSEHOLD_PERSONAL' "
        "WHERE LOWER(product_category) IN ('household_personal', 'household', 'personal', 'home', 'furniture')"
    )

    # Step C: For any arbitrary unrecognized string remaining, move it to description and map category to OTHER
    op.execute(
        "UPDATE pickups SET "
        "other_category_description = product_category, "
        "product_category = 'OTHER' "
        "WHERE product_category NOT IN ("
        "  'HOUSEHOLD_PERSONAL', 'VEHICLE', 'DOCUMENTS', 'HAZARDOUS', "
        "  'COMMERCIAL', 'ELECTRONICS', 'APPAREL', 'OTHER'"
        ")"
    )

    # 4. Cast the standard VARCHAR column to the new PG Enum type and alter it to NOT NULL
    op.execute(
        "ALTER TABLE pickups "
        "ALTER COLUMN product_category TYPE productcategory "
        "USING product_category::productcategory"
    )
    op.execute(
        "ALTER TABLE pickups "
        "ALTER COLUMN product_category SET NOT NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    # 1. Convert enum column back to standard nullable VARCHAR
    op.execute(
        "ALTER TABLE pickups "
        "ALTER COLUMN product_category TYPE VARCHAR USING product_category::VARCHAR"
    )
    op.execute(
        "ALTER TABLE pickups "
        "ALTER COLUMN product_category DROP NOT NULL"
    )
    
    # 2. Drop other_category_description column
    op.drop_column('pickups', 'other_category_description')
    
    # 3. Drop the PostgreSQL custom ENUM type
    sa.Enum(name='productcategory').drop(op.get_bind(), checkfirst=True)
