"""
app/api/auth.py
────────────────
Auth router — register and login endpoints only.
No business logic here; delegates to AuthService.
"""
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, CurrentUser
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Register a new user account."""
    svc = AuthService(db)
    user = await svc.register(body)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate and return a JWT."""
    svc = AuthService(db)
    return await svc.login(body)


@router.get("/me", response_model=UserResponse)
async def me(current_user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Return the currently authenticated user's profile."""
    from app.repositories.user_repo import UserRepository
    repo = UserRepository(db)
    user = await repo.get_by_id(current_user.user_id)
    return user
