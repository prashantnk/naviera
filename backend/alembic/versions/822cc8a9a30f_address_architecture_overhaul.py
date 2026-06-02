"""address_architecture_overhaul

Revision ID: 822cc8a9a30f
Revises: e7f4d6d62064
Create Date: 2026-06-01 23:56:17.842019

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '822cc8a9a30f'
down_revision: Union[str, Sequence[str], None] = 'e7f4d6d62064'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Create ENUM types
    address_category_enum = postgresql.ENUM('HOME', 'OFFICE', 'WAREHOUSE', 'STOREFRONT', 'OTHER', name='addresscategory')
    address_category_enum.create(op.get_bind(), checkfirst=True)
    
    address_scope_enum = postgresql.ENUM('PRIVATE', 'TENANT', name='addressscope')
    address_scope_enum.create(op.get_bind(), checkfirst=True)

    # 2. Add columns with nullable=True initially so we can migrate data
    op.add_column('addresses', sa.Column('category', sa.Enum('HOME', 'OFFICE', 'WAREHOUSE', 'STOREFRONT', 'OTHER', name='addresscategory'), nullable=True))
    op.add_column('addresses', sa.Column('scope', sa.Enum('PRIVATE', 'TENANT', name='addressscope'), nullable=True))
    op.add_column('addresses', sa.Column('alternate_phone', sa.String(length=20), nullable=True))
    op.add_column('addresses', sa.Column('address_signature', sa.String(), nullable=True))

    # 3. Data migration using Raw SQL
    op.execute("""
        UPDATE addresses 
        SET category = 'WAREHOUSE'::addresscategory, scope = 'TENANT'::addressscope 
        WHERE address_type = 'WAREHOUSE'
    """)
    op.execute("""
        UPDATE addresses 
        SET category = 'HOME'::addresscategory, scope = 'PRIVATE'::addressscope 
        WHERE address_type = 'CUSTOMER'
    """)
    op.execute("""
        UPDATE addresses 
        SET category = 'OTHER'::addresscategory, scope = 'PRIVATE'::addressscope 
        WHERE address_type = 'OTHER'
    """)
    # Fill any other remaining nulls
    op.execute("""
        UPDATE addresses 
        SET category = 'HOME'::addresscategory, scope = 'PRIVATE'::addressscope 
        WHERE category IS NULL OR scope IS NULL
    """)

    # 4. Alter columns to nullable=False
    op.alter_column('addresses', 'category', nullable=False)
    op.alter_column('addresses', 'scope', nullable=False)

    # 5. Create index
    op.create_index(op.f('ix_addresses_address_signature'), 'addresses', ['address_signature'], unique=False)

    # 6. Drop old column
    op.drop_column('addresses', 'address_type')
    
    # Drop the legacy enum type 'addresstype'
    sa.Enum(name='addresstype').drop(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    """Downgrade schema."""
    # 1. Create the legacy ENUM type if it doesn't exist
    legacy_enum = postgresql.ENUM('WAREHOUSE', 'CUSTOMER', 'OTHER', name='addresstype')
    legacy_enum.create(op.get_bind(), checkfirst=True)

    # 2. Add legacy address_type column (nullable=True initially)
    op.add_column('addresses', sa.Column('address_type', sa.Enum('WAREHOUSE', 'CUSTOMER', 'OTHER', name='addresstype'), nullable=True))

    # 3. Roll back data mapping
    op.execute("""
        UPDATE addresses 
        SET address_type = 'WAREHOUSE'::addresstype 
        WHERE category = 'WAREHOUSE'
    """)
    op.execute("""
        UPDATE addresses 
        SET address_type = 'CUSTOMER'::addresstype 
        WHERE category != 'WAREHOUSE'
    """)
    op.execute("""
        UPDATE addresses 
        SET address_type = 'CUSTOMER'::addresstype 
        WHERE address_type IS NULL
    """)

    # 4. Set nullable=False on legacy column
    op.alter_column('addresses', 'address_type', nullable=False)

    # 5. Clean up new columns & indexes
    op.drop_index(op.f('ix_addresses_address_signature'), table_name='addresses')
    op.drop_column('addresses', 'address_signature')
    op.drop_column('addresses', 'alternate_phone')
    op.drop_column('addresses', 'scope')
    op.drop_column('addresses', 'category')

    # 6. Drop new Enum types
    sa.Enum(name='addresscategory').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='addressscope').drop(op.get_bind(), checkfirst=True)
