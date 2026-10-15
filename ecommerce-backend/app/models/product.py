from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    ForeignKey,
    Index,
    JSON,
)


from sqlalchemy.orm import relationship


from app.database.base import Base
from app.core.time import utcnow_naive




class Product(Base):

    __tablename__ = "products"



    id = Column(
        Integer,
        primary_key=True,
        index=True
    )



    name = Column(
        String(100),
        nullable=False
    )



    description = Column(
        String,
        nullable=True
    )

    brand = Column(String(100), nullable=True)

    category = Column(String(100), nullable=True)

    categories = Column(JSON, nullable=False, default=list)

    feature_details = Column(String, nullable=True)

    features = Column(String, nullable=True)

    specifications = Column(JSON, nullable=False, default=dict)



    price = Column(
        Float,
        nullable=False
    )



    stock = Column(
        Integer,
        default=0,
        nullable=False
    )



    image_url = Column(
        String,
        nullable=True
    )



    owner_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )



    created_at = Column(
        DateTime,
        default=utcnow_naive
    )



    owner = relationship(
        "User",
        back_populates="products"
    )



    # Database indexes for faster search/filtering

    __table_args__ = (

        Index(
            "idx_product_name",
            "name"
        ),

        Index(
            "idx_product_price",
            "price"
        ),

        Index(
            "idx_product_stock",
            "stock"
        ),

    )