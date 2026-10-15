from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    File,
    Form
)
from urllib.parse import urlsplit
from typing import Literal
import json

from sqlalchemy.orm import Session


from app.database.database import get_db
from app.core.rate_limit import ai_rate_limit_key, limiter


from app.schemas.product import (
    ProductCreate,
    ProductUpdate
)


from app.services.product_service import (
    ProductHasOrderHistoryError,
    create_new_product,
    get_all_products,
    get_single_product,
    update_existing_product,
    remove_product
)
from app.services.ai_features_service import (
    AIServiceUnavailableError,
    moderate_content,
    semantic_search_products,
)
from app.services.product_categories import canonicalize_product_categories, product_categories


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
    category: str | None = Query(default=None, max_length=100),
    db: Session = Depends(get_db)

):
    if category:
        try:
            category = canonicalize_product_categories([category])[0]
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    products = get_all_products(

        db,

        page,

        limit,

        search,

        min_price,

        max_price,

        stock_available,

        search_mode,
        category

    )


    return success_response(

        data=products,

        message="Products fetched successfully"

    )


@router.get("/categories")
def get_product_categories():
    return success_response(
        data=product_categories(),
        message="Product categories fetched successfully",
    )


@router.get("/semantic-search")
@limiter.limit("20/minute", key_func=ai_rate_limit_key)
def search_products_semantically(
    request: Request,
    response: Response,
    q: str = Query(min_length=2, max_length=200),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=100),
    min_price: float | None = Query(default=None, ge=0),
    max_price: float | None = Query(default=None, ge=0),
    stock_available: bool | None = None,
    category: str | None = Query(default=None, max_length=100),
    db: Session = Depends(get_db),
):
    if min_price is not None and max_price is not None and min_price > max_price:
        raise HTTPException(status_code=422, detail="Minimum price cannot exceed maximum price.")
    if category:
        try:
            category = canonicalize_product_categories([category])[0]
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    try:
        products = semantic_search_products(
            db,
            q.strip(),
            min_price=min_price,
            max_price=max_price,
            stock_available=stock_available,
            category=category,
        )
    except AIServiceUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    offset = (page - 1) * limit
    return success_response(
        data={
            "page": page,
            "limit": limit,
            "total": len(products),
            "items": products[offset : offset + limit],
        },
        message="Semantic product search completed",
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
@limiter.limit("12/minute", key_func=ai_rate_limit_key)
def create_product(
    request: Request,
    response: Response,

    name: str = Form(...),

    description: str | None = Form(default=None, max_length=2000),

    brand: str | None = Form(default=None, max_length=100),

    category: str | None = Form(default=None, max_length=100),

    categories: str = Form(default="[]"),

    feature_details: str | None = Form(default=None, max_length=4000),

    features: str | None = Form(default=None, max_length=4000),

    specifications: str = Form(default="{}"),

    price: float = Form(...),

    stock: int = Form(...),

    image_url: str | None = Form(None),

    image: UploadFile = File(None),

    db: Session = Depends(get_db),

    current_user: User = Depends(get_current_admin)

):

    if image is not None and image_url and image_url.strip():
        raise HTTPException(status_code=400, detail="Choose either an image URL or an uploaded image, not both.")

    if description and description.strip():
        try:
            moderation = moderate_content(description)
        except AIServiceUnavailableError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        if not moderation.approved:
            raise HTTPException(
                status_code=422,
                detail=f"Product description was rejected by content moderation ({moderation.category}).",
            )

    try:
        parsed_specifications = json.loads(specifications)
        if not isinstance(parsed_specifications, dict):
            raise ValueError("Specifications must be a JSON object.")
        parsed_categories = json.loads(categories)
        if not isinstance(parsed_categories, list) or not all(
            isinstance(item, str) for item in parsed_categories
        ):
            raise ValueError("Categories must be a JSON array of category names.")
        if not parsed_categories and category and category.strip():
            parsed_categories = [category.strip()]
        parsed_categories = canonicalize_product_categories(parsed_categories)
        product_data = ProductCreate(
            name=name,
            description=description,
            brand=brand,
            category=parsed_categories[0] if parsed_categories else None,
            categories=parsed_categories,
            feature_details=feature_details,
            features=features,
            specifications=parsed_specifications,
            price=price,
            stock=stock,
            image_url=validate_image_url(image_url) if image is None else None,
        )
    except (json.JSONDecodeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=f"Invalid product data: {error}") from error

    image_path = save_image(image) if image is not None else None
    if image_path:
        product_data.image_url = image_path

    product = create_new_product(

        db,

        product_data,

        current_user.id

    )



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
@limiter.limit("12/minute", key_func=ai_rate_limit_key)
def update_product(
    request: Request,
    response: Response,

    product_id: int,

    product_data: ProductUpdate,

    db: Session = Depends(get_db),

    current_user: User = Depends(get_current_admin)

):
    if (
        "description" in product_data.model_fields_set
        and product_data.description
        and product_data.description.strip()
    ):
        try:
            moderation = moderate_content(product_data.description)
        except AIServiceUnavailableError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        if not moderation.approved:
            raise HTTPException(
                status_code=422,
                detail=f"Product description was rejected by content moderation ({moderation.category}).",
            )

    if "image_url" in product_data.model_fields_set:
        product_data.image_url = validate_image_url(product_data.image_url)

    if "categories" in product_data.model_fields_set:
        product_data.category = product_data.categories[0] if product_data.categories else None
    elif "category" in product_data.model_fields_set:
        try:
            product_data.categories = (
                canonicalize_product_categories([product_data.category])
                if product_data.category
                else []
            )
            product_data.category = product_data.categories[0] if product_data.categories else None
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

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

    try:
        deleted = remove_product(
            db,
            product_id
        )
    except ProductHasOrderHistoryError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


    if not deleted:

        raise HTTPException(

            status_code=404,

            detail="Product not found"

        )


    return success_response(

        data=None,

        message="Product deleted successfully"

    )
