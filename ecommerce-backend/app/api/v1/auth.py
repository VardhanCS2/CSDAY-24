from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
)

from sqlalchemy.orm import Session


from app.database.database import get_db

from app.api.deps import get_current_user

from app.models.user import User


from app.schemas.user import (
    UserCreate,
    UserLogin
)
from app.schemas.token import TokenRefresh


from app.services.auth_service import (
    register_user,
    authenticate_user
)


from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.core.rate_limit import limiter


from app.utils.response import success_response



router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)



@router.post("/register")
@limiter.limit("5/minute")
def register(
    request: Request,
    response: Response,
    user_data: UserCreate,
    db: Session = Depends(get_db)
):

    try:
        user = register_user(
            db,
            user_data
        )
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )

    return success_response(
        data=user,
        message="User registered successfully"
    )



@router.post("/login")
@limiter.limit("5/minute")
def login(
    request: Request,
    response: Response,
    user_data: UserLogin,
    db: Session = Depends(get_db)
):

    user = authenticate_user(
        db,
        user_data.email,
        user_data.password
    )


    if not user:

        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )



    access_token = create_access_token(
        {
            "sub": str(user.id),
            "role": user.role
        }
    )


    refresh_token = create_refresh_token(
        {
            "sub": str(user.id)
        }
    )



    token_data = {

        "access_token": access_token,

        "refresh_token": refresh_token,

        "token_type": "bearer"

    }



    return success_response(
        data=token_data,
        message="Login successful"
    )



@router.get("/me")
def get_current_profile(
    current_user: User = Depends(get_current_user)
):

    return success_response(
        data={
            "id": current_user.id,
            "name": current_user.name,
            "email": current_user.email,
            "role": current_user.role,
            "created_at": str(current_user.created_at),
            "updated_at": str(current_user.updated_at)
        },
        message="User profile fetched successfully"
    )



@router.post("/refresh")
@limiter.limit("10/minute")
def refresh_tokens(
    request: Request,
    response: Response,
    token_data: TokenRefresh,
    db: Session = Depends(get_db),
):
    payload = decode_token(token_data.refresh_token)
    if not payload or payload.get("token_type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid refresh token data")

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    return success_response(
        data={
            "access_token": create_access_token({"sub": str(user.id), "role": user.role}),
            "refresh_token": create_refresh_token({"sub": str(user.id)}),
            "token_type": "bearer",
        },
        message="Tokens refreshed successfully",
    )