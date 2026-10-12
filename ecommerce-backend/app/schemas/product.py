from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field



class ProductCreate(BaseModel):

    name: str
    description: str | None = Field(default=None, max_length=2000)
    price: float
    stock: int
    image_url: str | None = None



class ProductUpdate(BaseModel):

    name: str | None = None
    description: str | None = Field(default=None, max_length=2000)
    price: float | None = None
    stock: int | None = None
    image_url: str | None = None



class ProductResponse(BaseModel):

    id: int
    name: str
    description: str | None
    price: float
    stock: int
    image_url: str | None
    owner_id: int
    created_at: datetime


    model_config = ConfigDict(
        from_attributes=True
    )