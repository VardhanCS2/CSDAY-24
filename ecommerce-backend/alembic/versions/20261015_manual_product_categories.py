"""Store admin-assigned product categories."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261015_manual_categories"
down_revision: Union[str, Sequence[str], None] = "20261014_product_search_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column(
            "categories",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.alter_column("products", "categories", server_default=None)
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_products_search_vector")
        op.execute(
            "CREATE INDEX ix_products_search_vector ON products USING GIN "
            "(to_tsvector('english', "
            "coalesce(name, '') || ' ' || coalesce(description, '') || ' ' || "
            "coalesce(brand, '') || ' ' || coalesce(category, '') || ' ' || "
            "coalesce(CAST(categories AS VARCHAR), '') || ' ' || "
            "coalesce(feature_details, '') || ' ' || coalesce(features, '') || ' ' || "
            "coalesce(CAST(specifications AS VARCHAR), '')))"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_products_search_vector")
        op.execute(
            "CREATE INDEX ix_products_search_vector ON products USING GIN "
            "(to_tsvector('english', "
            "coalesce(name, '') || ' ' || coalesce(description, '') || ' ' || "
            "coalesce(brand, '') || ' ' || coalesce(category, '') || ' ' || "
            "coalesce(feature_details, '') || ' ' || coalesce(features, '') || ' ' || "
            "coalesce(CAST(specifications AS VARCHAR), '')))"
        )
    op.drop_column("products", "categories")
