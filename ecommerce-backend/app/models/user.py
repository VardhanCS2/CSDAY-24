from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime
)

from sqlalchemy.orm import relationship

from app.database.base import Base
from app.core.time import utcnow_naive



class User(Base):

    __tablename__ = "users"


    id = Column(
        Integer,
        primary_key=True,
        index=True
    )


    name = Column(
        String(100),
        nullable=False
    )


    email = Column(
        String(100),
        unique=True,
        index=True,
        nullable=False
    )


    hashed_password = Column(
        String,
        nullable=False
    )


    role = Column(
        String(20),
        default="customer",
        nullable=False
    )


    created_at = Column(
        DateTime,
        default=utcnow_naive
    )


    updated_at = Column(
        DateTime,
        default=utcnow_naive,
        onupdate=utcnow_naive
    )


    products = relationship(
        "Product",
        back_populates="owner"
    )