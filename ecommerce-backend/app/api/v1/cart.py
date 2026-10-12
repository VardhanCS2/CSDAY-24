from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)

from sqlalchemy.orm import Session

from app.database.database import get_db

from app.api.deps import get_current_user

from app.models.user import User
from app.models.product import Product
from app.redis.cache import get_cart as read_cart_state


from app.services.cart_service import (
    add_product_to_cart,
    get_user_cart,
    remove_product_from_cart,
    update_product_in_cart
)


from app.utils.response import success_response



router = APIRouter(
    prefix="/cart",
    tags=["Cart"]
)



@router.post("/add")
def add_cart(
    product_identifier: str = Query(min_length=1, max_length=100),
    quantity: int = Query(gt=0, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Add product to cart using product ID or product name.
    """

    product = None


    # Search by ID
    if product_identifier.strip().isdigit():

        product = (
            db.query(Product)
            .filter(
                Product.id == int(product_identifier)
            )
            .first()
        )


    # Search by name
    if not product:

        product = (
            db.query(Product)
            .filter(
                Product.name.ilike(
                    product_identifier.strip()
                )
            )
            .first()
        )


    if not product:

        raise HTTPException(
            status_code=404,
            detail=f"Product '{product_identifier}' not found"
        )

    cart = read_cart_state(current_user.id)
    existing_quantity = int(cart.get(str(product.id), 0))
    if existing_quantity + quantity > product.stock:
        raise HTTPException(
            status_code=400,
            detail=f"Not enough stock for {product.name}"
        )

    cart = add_product_to_cart(
        current_user.id,
        product.id,
        quantity
    )


    return success_response(
        data=cart,
        message=f"'{product.name}' added to cart successfully"
    )



@router.get("/")
def get_cart(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    cart = get_user_cart(
        db,
        current_user.id
    )


    return success_response(
        data=cart,
        message="Cart fetched successfully"
    )



@router.delete("/remove/{product_id}")
def remove_cart_item(
    product_id: int,
    current_user: User = Depends(get_current_user)
):

    cart = remove_product_from_cart(
        current_user.id,
        product_id
    )


    return success_response(
        data=cart,
        message="Product removed from cart successfully"
    )



@router.put("/edit")
def edit_cart_item(
    product_id: int,
    quantity: int = Query(ge=0, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update product quantity in cart.
    quantity=0 removes product.
    """


    if quantity > 0:
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            raise HTTPException(
                status_code=404,
                detail="Product not found"
            )
        if quantity > product.stock:
            raise HTTPException(
                status_code=400,
                detail=f"Not enough stock for {product.name}"
            )

    cart = update_product_in_cart(
        current_user.id,
        product_id,
        quantity
    )


    message = (
        "Product removed from cart"
        if quantity == 0
        else "Cart updated successfully"
    )


    return success_response(
        data=cart,
        message=message
    )