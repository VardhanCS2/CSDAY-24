from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.product_categories import canonicalize_product_categories


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    brand: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=100)
    categories: list[str] = Field(default_factory=list, max_length=3)
    feature_details: str | None = Field(default=None, max_length=4000)
    features: str | None = Field(default=None, max_length=4000)
    specifications: dict[str, str] = Field(default_factory=dict, max_length=50)
    price: float
    stock: int
    image_url: str | None = None

    @field_validator("brand", "category", "feature_details", "features")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        normalized = value.strip() if value else ""
        return normalized or None

    @field_validator("specifications")
    @classmethod
    def validate_specifications(cls, value: dict[str, str]) -> dict[str, str]:
        if any(not label.strip() or len(label) > 100 or len(specification) > 500 for label, specification in value.items()):
            raise ValueError("Specification labels must be 1-100 characters and values 500 characters or fewer.")
        return {label.strip(): specification.strip() for label, specification in value.items()}

    @field_validator("categories")
    @classmethod
    def validate_categories(cls, value: list[str]) -> list[str]:
        return canonicalize_product_categories(value)


class ProductUpdate(BaseModel):

    name: str | None = None
    description: str | None = Field(default=None, max_length=2000)
    brand: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=100)
    categories: list[str] | None = Field(default=None, max_length=3)
    feature_details: str | None = Field(default=None, max_length=4000)
    features: str | None = Field(default=None, max_length=4000)
    specifications: dict[str, str] | None = Field(default=None, max_length=50)
    price: float | None = None
    stock: int | None = None
    image_url: str | None = None

    @field_validator("brand", "category", "feature_details", "features")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        normalized = value.strip() if value else ""
        return normalized or None

    @field_validator("categories")
    @classmethod
    def validate_categories(cls, value: list[str] | None) -> list[str] | None:
        return canonicalize_product_categories(value) if value is not None else None

    @field_validator("specifications")
    @classmethod
    def validate_specifications(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is not None and any(
            not label.strip() or len(label) > 100 or len(specification) > 500
            for label, specification in value.items()
        ):
            raise ValueError("Specification labels must be 1-100 characters and values 500 characters or fewer.")
        return (
            {label.strip(): specification.strip() for label, specification in value.items()}
            if value is not None else None
        )



class ProductResponse(BaseModel):

    id: int
    name: str
    description: str | None
    brand: str | None
    category: str | None
    categories: list[str]
    feature_details: str | None
    features: str | None
    specifications: dict[str, str]
    price: float
    stock: int
    image_url: str | None
    owner_id: int
    created_at: datetime


    model_config = ConfigDict(
        from_attributes=True
    )