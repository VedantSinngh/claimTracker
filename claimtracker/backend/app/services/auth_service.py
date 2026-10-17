"""
app/services/auth_service.py
─────────────────────────────
Business logic for registration and login.
No SQL here — delegates to UserRepository.
"""
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError, ConflictError, ValidationError
from app.core.logging import get_logger
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repositories.role_repo import RoleRepository
from app.repositories.user_repo import UserRepository
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse

logger = get_logger(__name__)
settings = get_settings()


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = UserRepository(session)
        self._role_repo = RoleRepository(session)
        self._session = session

    async def register(self, request: RegisterRequest) -> User:
        if await self._repo.email_exists(request.email):
            raise ConflictError(f"Email '{request.email}' is already registered.")

        # Resolve the role name to its FK. The names are seeded by migration
        # 0004, so a miss means the DB was not migrated.
        role = await self._role_repo.get_by_name(request.role)
        if role is None:
            raise ValidationError(
                f"Role '{request.role}' does not exist. "
                "Run `alembic upgrade head` to seed the roles table."
            )

        user = User(
            email=request.email,
            hashed_password=hash_password(request.password),
            full_name=request.full_name,
            role_id=role.id,
        )
        # Attach the loaded Role so `user.role` resolves without extra IO.
        user.role_obj = role
        user = await self._repo.create(user)
        await self._session.commit()
        logger.info("user_registered", user_id=str(user.id), role=user.role)
        return user

    async def login(self, request: LoginRequest) -> TokenResponse:
        user = await self._repo.get_by_email(request.email)
        if user is None or not verify_password(request.password, user.hashed_password):
            raise AuthenticationError("Invalid email or password.")
        if not user.is_active:
            raise AuthenticationError("Account is disabled.")

        expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        token = create_access_token(
            subject=str(user.id), role=user.role, expires_delta=expires
        )
        logger.info("user_logged_in", user_id=str(user.id))
        return TokenResponse(
            access_token=token,
            expires_in=int(expires.total_seconds()),
            user_id=user.id,
            role=user.role,
        )
