"""Authentication and authorization utilities."""

from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        # Fallback to direct bcrypt if passlib fails
        try:
            import bcrypt
            return bcrypt.checkpw(
                plain_password.encode('utf-8'),
                hashed_password.encode('utf-8')
            )
        except Exception:
            return False


def get_password_hash(password: str) -> str:
    """Hash a password."""
    return pwd_context.hash(password)


def create_access_token(data: dict,
                        expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.access_token_expire_minutes
        )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode, settings.secret_key, algorithm=settings.algorithm
    )
    return encoded_jwt


def get_user_by_username(db: Session, username: str) -> Optional[User]:
    """Get user by username."""
    return db.query(User).filter(User.username == username).first()


def authenticate_user(db: Session, username: str,
                     password: str) -> Optional[User]:
    """Authenticate a user."""
    user = get_user_by_username(db, username)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """Get current authenticated user."""
    from app.database import get_db
    db = next(get_db())
    try:
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
        try:
            payload = jwt.decode(
                token, settings.secret_key, algorithms=[settings.algorithm]
            )
            username: str = payload.get("sub")
            if username is None:
                raise credentials_exception
        except JWTError:
            raise credentials_exception

        user = get_user_by_username(db, username)
        if user is None:
            raise credentials_exception
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive"
            )
        return user
    finally:
        db.close()


def require_role(allowed_roles: list[str]):
    """Dependency to require specific roles."""
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required role: {', '.join(allowed_roles)}"
            )
        return current_user
    return role_checker


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Require admin role."""
    if current_user.role != 'admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user


def require_full_or_admin(current_user: User = Depends(get_current_user)) -> User:
    """Require full or admin role (for sync operations)."""
    if current_user.role not in ['full', 'admin']:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Full access or admin role required for this operation"
        )
    return current_user


def init_default_user() -> None:
    """Initialize default admin user."""
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        existing_user = get_user_by_username(
            db, settings.default_username
        )
        if not existing_user:
            # Pre-initialize bcrypt by hashing a dummy password first
            # This helps avoid initialization issues during actual password hashing
            try:
                _ = get_password_hash("dummy")
            except Exception:
                pass  # Ignore initialization errors
            
            # Now hash the actual password
            try:
                hashed_password = get_password_hash(settings.default_password)
            except (ValueError, Exception) as e:
                # If bcrypt still fails, skip user creation
                print(f"Warning: Could not hash password: {e}")
                return
            
            user = User(
                username=settings.default_username,
                hashed_password=hashed_password,
                role='admin',  # Default user is admin
                is_active=True
            )
            db.add(user)
            db.commit()
            print(f"Created default admin user: {settings.default_username}")
        else:
            # Update existing user to admin role if not set
            if not existing_user.role:
                existing_user.role = 'admin'
                db.commit()
                print(f"Updated existing user {settings.default_username} to admin role")
    except Exception as e:
        print(f"Warning: Could not initialize default user: {e}")
        db.rollback()
    finally:
        db.close()

