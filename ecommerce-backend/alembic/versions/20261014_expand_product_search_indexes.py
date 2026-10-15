"""Index all catalogue fields used by hybrid product search."""

from typing import Sequence, Union

from alembic import op


revision: str = "20261014_product_search_indexes"
down_revision: Union[str, Sequence[str], None] = "20261013_product_content"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS ix_products_search_vector")
    op.execute(
        "CREATE INDEX ix_products_search_vector ON products USING GIN "
        "(to_tsvector('english', "
        "coalesce(name, '') || ' ' || coalesce(description, '') || ' ' || "
        "coalesce(brand, '') || ' ' || coalesce(category, '') || ' ' || "
        "coalesce(feature_details, '') || ' ' || coalesce(features, '') || ' ' || "
        "coalesce(CAST(specifications AS VARCHAR), '')))"
    )
    op.execute(
        "CREATE INDEX ix_products_brand_trgm ON products USING GIN (brand gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_products_category_trgm ON products USING GIN (category gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_products_feature_details_trgm ON products "
        "USING GIN (feature_details gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_products_features_trgm ON products USING GIN (features gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_products_specifications_trgm ON products "
        "USING GIN ((CAST(specifications AS VARCHAR)) gin_trgm_ops)"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS ix_products_specifications_trgm")
    op.execute("DROP INDEX IF EXISTS ix_products_features_trgm")
    op.execute("DROP INDEX IF EXISTS ix_products_feature_details_trgm")
    op.execute("DROP INDEX IF EXISTS ix_products_category_trgm")
    op.execute("DROP INDEX IF EXISTS ix_products_brand_trgm")
    op.execute("DROP INDEX IF EXISTS ix_products_search_vector")
    op.execute(
        "CREATE INDEX ix_products_search_vector ON products USING GIN "
        "(to_tsvector('english', coalesce(name, '') || ' ' || coalesce(description, '')))"
    )
