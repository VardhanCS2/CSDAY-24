from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    UploadFile,
    File,
    Form
)
from urllib.parse import urlsplit
from typing import Literal

from sqlalchemy.orm import Session


from app.database.database import get_db


from app.schemas.product import (
    ProductCreate,
    ProductUpdate
)


from app.services.product_service import (
    create_new_product,
    get_all_products,
    get_single_product,
    update_existing_product,
    remove_product
)


from app.api.deps import get_current_admin


from app.models.user import User


from app.utils.image import save_image


from app.utils.response import success_response



router = APIRouter(
    prefix="/products",
    tags=["Products"]
)



# Get products with pagination + filtering

@router.get("/")
def get_products(

    page: int = Query(default=1, ge=1),

    limit: int = Query(default=10, ge=1, le=100),

    search: str | None = Query(default=None, max_length=200),

    min_price: float | None = Query(default=None, ge=0),

    max_price: float | None = Query(default=None, ge=0),

    stock_available: bool | None = None,
    search_mode: Literal["hybrid", "full_text", "fuzzy"] = "hybrid",
    db: Session = Depends(get_db)

):

    products = get_all_products(

        db,

        page,

        limit,

        search,

        min_price,

        max_price,

        stock_available,
        search_mode

    )


    return success_response(

        data=products,

        message="Products fetched successfully"

    )



@router.get("/{product_id}")
def get_product(

    product_id: int,

    db: Session = Depends(get_db)

):

    product = get_single_product(

        db,

        product_id

    )


    if not product:

        raise HTTPException(

            status_code=404,

            detail="Product not found"

        )


    return success_response(

        data=product,

        message="Product fetched successfully"

    )


def validate_image_url(image_url: str | None) -> str | None:
    if image_url is None or not image_url.strip():
        return None
    normalized = image_url.strip()
    try:
        parsed = urlsplit(normalized)
        hostname = parsed.hostname
        parsed.port
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Image URL must be an absolute HTTP or HTTPS URL.") from error
    if parsed.scheme not in {"http", "https"} or not hostname or parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="Image URL must be an absolute HTTP or HTTPS URL.")
    return normalized


# Admin create product

@router.post("/")
def create_product(

    name: str = Form(...),

    description: str = Form(None),

    price: float = Form(...),

    stock: int = Form(...),

    image_url: str | None = Form(None),

    image: UploadFile = File(None),

    db: Session = Depends(get_db),

    current_user: User = Depends(get_current_admin)

):

    if image is not None and image_url and image_url.strip():
        raise HTTPException(status_code=400, detail="Choose either an image URL or an uploaded image, not both.")

    image_path = None

    if image:

        image_path = save_image(image)



    product_data = ProductCreate(

        name=name,

        description=description,

        price=price,

        stock=stock,

        image_url=validate_image_url(image_url) if image_path is None else None

    )


    product = create_new_product(

        db,

        product_data,

        current_user.id

    )



    if image_path:
        product.image_url = image_path

        db.commit()

        db.refresh(product)



    return success_response(

        data=product,

        message="Product created successfully"

    )


@router.post("/{product_id}/image")
def upload_product_image(
    product_id: int,
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    product = get_single_product(db, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    image_path = save_image(image)
    product.image_url = image_path
    db.commit()
    db.refresh(product)
    return success_response(data=product, message="Product image updated successfully")


@router.put("/{product_id}")
def update_product(

    product_id: int,

    product_data: ProductUpdate,

    db: Session = Depends(get_db),

    current_user: User = Depends(get_current_admin)

):
    if "image_url" in product_data.model_fields_set:
        product_data.image_url = validate_image_url(product_data.image_url)

    product = update_existing_product(

        db,

        product_id,

        product_data

    )


    if not product:

        raise HTTPException(

            status_code=404,

            detail="Product not found"

        )


    return success_response(

        data=product,

        message="Product updated successfully"

    )



@router.delete("/{product_id}")
def delete_product(

    product_id: int,

    db: Session = Depends(get_db),

    current_user: User = Depends(get_current_admin)

):

    deleted = remove_product(

        db,

        product_id

    )


    if not deleted:

        raise HTTPException(

            status_code=404,

            detail="Product not found"

        )


    return success_response(

        data=None,

        message="Product deleted successfully"

    )
