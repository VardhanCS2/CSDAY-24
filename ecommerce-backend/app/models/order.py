from sqlalchemy import (
    Column,
    Integer,
    Float,
    String,
    DateTime,
    ForeignKey,
    JSON,
)

from sqlalchemy.orm import relationship

from app.database.base import Base
from app.core.time import utcnow_naive



class Order(Base):

    __tablename__ = "orders"


    id = Column(
        Integer,
        primary_key=True,
        index=True
    )


    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )


    total_amount = Column(
        Float,
        nullable=False
    )


    status = Column(
        String(50),
        default="Pending"
    )


    created_at = Column(
        DateTime,
        default=utcnow_naive
    )

    shipping_address = Column(
        JSON,
        nullable=True
    )

    payment_method = Column(
        String(30),
        nullable=True
    )


    items = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete"
    )