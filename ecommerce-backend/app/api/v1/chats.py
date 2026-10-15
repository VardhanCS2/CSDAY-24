from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session
from sqlalchemy.orm import aliased

from app.api.deps import get_current_user
from app.database.database import get_db
from app.models.chat_message import ChatMessage
from app.models.user import User
from app.utils.response import success_response

router = APIRouter(prefix="/chats", tags=["Chats"])


@router.get("/conversations")
def get_chat_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator access is required.")

    sender = aliased(User)
    recipient = aliased(User)
    customer_id = case(
        (sender.role == "admin", ChatMessage.recipient_id),
        else_=ChatMessage.sender_id,
    )
    latest_messages = (
        db.query(
            func.max(ChatMessage.id).label("message_id"),
            customer_id.label("customer_id"),
        )
        .join(sender, sender.id == ChatMessage.sender_id)
        .join(recipient, recipient.id == ChatMessage.recipient_id)
        .filter(
            or_(
                and_(sender.role == "admin", recipient.role != "admin"),
                and_(sender.role != "admin", recipient.role == "admin"),
            )
        )
        .group_by(customer_id)
        .subquery()
    )
    conversations = (
        db.query(User, ChatMessage)
        .join(latest_messages, latest_messages.c.customer_id == User.id)
        .join(ChatMessage, ChatMessage.id == latest_messages.c.message_id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .all()
    )
    result = [
        {
            "customer_id": customer.id,
            "customer_name": customer.name,
            "customer_email": customer.email,
            "last_message": message.text,
            "last_sender_id": message.sender_id,
            "last_message_at": message.created_at,
        }
        for customer, message in conversations
    ]
    return success_response(data=result, message="Chat conversations fetched")


@router.get("/")
def get_chat_history(
    customer_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(ChatMessage)
    if current_user.role == "admin":
        if customer_id is not None:
            customer = db.query(User).filter(User.id == customer_id, User.role != "admin").first()
            if customer is None:
                raise HTTPException(status_code=404, detail="Customer not found")
            query = query.filter(
                (ChatMessage.sender_id == customer_id) | (ChatMessage.recipient_id == customer_id)
            )
    else:
        if customer_id is not None and customer_id != current_user.id:
            raise HTTPException(status_code=403, detail="You can only access your own conversation.")
        query = query.filter(
            (ChatMessage.sender_id == current_user.id) | (ChatMessage.recipient_id == current_user.id)
        )

    messages = query.order_by(ChatMessage.created_at.desc()).limit(500).all()
    messages.reverse()
    user_ids = {user_id for message in messages for user_id in (message.sender_id, message.recipient_id)}
    users = {
        user.id: user
        for user in db.query(User).filter(User.id.in_(user_ids)).all()
    } if user_ids else {}
    result = [
        {
            "id": message.id,
            "sender_id": message.sender_id,
            "sender_name": users[message.sender_id].name if message.sender_id in users else "Former user",
            "recipient_id": message.recipient_id,
            "recipient_name": users[message.recipient_id].name if message.recipient_id in users else "Former user",
            "text": message.text,
            "created_at": message.created_at,
        }
        for message in messages
    ]
    return success_response(data=result, message="Chat history fetched")
