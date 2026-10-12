from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_user
from app.core.rate_limit import limiter
from app.database.database import get_db
from app.models.user import User
from app.schemas.order import OrderCreate, OrderStatusUpdate
from app.services.order_service import (
    cancel_order,
    get_all_orders,
    get_order,
    get_orders,
    place_order,
    update_order_status,
)
from app.utils.response import success_response
from app.websocket.manager import manager

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.post("/")
@limiter.limit("20/minute")
async def create_order(
    request: Request,
    response: Response,
    order_data: OrderCreate | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    shipping_address = order_data.shipping_address.model_dump() if order_data and order_data.shipping_address else None
    requested_items = [item.model_dump() for item in order_data.items] if order_data and order_data.items else None
    payment_method = order_data.payment_method if order_data else None
    order = place_order(db, current_user.id, shipping_address, requested_items, payment_method)
    await manager.publish_order_change(order, current_user.name)
    return success_response(data=order, message="Order placed successfully")


@router.get("/")
def read_orders(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    orders = get_orders(db, current_user.id)
    data = [
        {
            "id": order.id,
            "user_id": order.user_id,
            "total_amount": order.total_amount,
            "status": order.status,
            "created_at": order.created_at,
            "shipping_address": order.shipping_address,
            "payment_method": order.payment_method,
            "items": [
                {
                    "id": item.id,
                    "product_id": item.product_id,
                    "product_name": item.product.name if item.product else f"Product #{item.product_id}",
                    "quantity": item.quantity,
                    "price": item.price,
                }
                for item in order.items
            ],
        }
        for order in orders
    ]
    return success_response(data=data, message="Orders fetched successfully")


@router.get("/admin/all")
def read_all_orders(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    orders = get_all_orders(db)
    customer_ids = {order.user_id for order in orders}
    customers = {
        customer.id: customer
        for customer in db.query(User).filter(User.id.in_(customer_ids)).all()
    } if customer_ids else {}
    data = []
    for order in orders:
        customer = customers.get(order.user_id)
        data.append({
            "id": order.id,
            "user_id": order.user_id,
            "customer": {
                "name": customer.name,
                "email": customer.email,
            } if customer else None,
            "total_amount": order.total_amount,
            "status": order.status,
            "created_at": order.created_at,
            "shipping_address": order.shipping_address,
            "payment_method": order.payment_method,
            "items": [
                {
                    "id": item.id,
                    "product_id": item.product_id,
                    "product_name": item.product.name if item.product else f"Product #{item.product_id}",
                    "quantity": item.quantity,
                    "price": item.price,
                }
                for item in order.items
            ],
        })

    return success_response(data=data, message="All orders fetched successfully")


@router.get("/{order_id}")
def read_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = None if current_user.role == "admin" else current_user.id
    order = get_order(db, order_id, user_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return success_response(data=order, message="Order fetched successfully")


@router.patch("/{order_id}/cancel")
async def cancel_user_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = None if current_user.role == "admin" else current_user.id
    order, error = cancel_order(db, order_id, user_id)
    if error:
        status_code = 404 if "not found" in error.lower() else 400
        raise HTTPException(status_code=status_code, detail=error)
    await manager.publish_order_change(order)
    return success_response(data=order, message="Order cancelled successfully")


@router.patch("/{order_id}/complete")
async def complete_pending_order(
    order_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    order, error = update_order_status(db, order_id, "Completed")
    if error:
        status_code = 404 if "not found" in error.lower() else 400
        raise HTTPException(status_code=status_code, detail=error)
    await manager.publish_order_change(order)
    return success_response(data=order, message="Order marked as completed")


@router.patch("/{order_id}/status")
async def update_order_status_by_admin(
    order_id: int,
    status_update: OrderStatusUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    order, error = update_order_status(db, order_id, status_update.status)
    if error:
        status_code = 404 if "not found" in error.lower() else 400
        raise HTTPException(status_code=status_code, detail=error)
    await manager.publish_order_change(order)
    return success_response(data=order, message=f"Order status updated to {order.status}")
