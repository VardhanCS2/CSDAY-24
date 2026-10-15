"""Add generic product content fields."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261013_product_content"
down_revision: Union[str, Sequence[str], None] = "20261008_jobs_chats_search"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("brand", sa.String(length=100), nullable=True))
    op.add_column("products", sa.Column("category", sa.String(length=100), nullable=True))
    op.add_column("products", sa.Column("feature_details", sa.String(), nullable=True))
    op.add_column("products", sa.Column("features", sa.String(), nullable=True))
    op.add_column(
        "products",
        sa.Column(
            "specifications",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("products", "specifications")
    op.drop_column("products", "features")
    op.drop_column("products", "feature_details")
    op.drop_column("products", "category")
    op.drop_column("products", "brand")
