"""Authentication module for user management and JWT tokens."""
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr
from sqlalchemy import Boolean, Column, DateTime, Integer, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # Enable debug logging

# Configuration
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")  # nosec B105
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1380"))  # 23 hours

# Database setup
DATABASE_URL = os.getenv(
    "AUTH_DATABASE_URL",
    "postgresql://langfuse:changeme@langfuse-postgres.llm-stack.svc.cluster.local:5432/ragauth",  # pragma: allowlist secret
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# HTTP Bearer security
security = HTTPBearer()


# --- DATABASE MODELS ---


class User(Base):  # type: ignore[misc,valid-type]
    """User model for authentication."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(255), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)


# --- PYDANTIC MODELS ---


class UserCreate(BaseModel):
    """User registration schema."""

    username: str
    email: EmailStr
    password: str
    full_name: Optional[str] = None


class UserLogin(BaseModel):
    """User login schema."""

    username: str
    password: str


class UserResponse(BaseModel):
    """User response schema (without password)."""

    id: int
    username: str
    email: str
    full_name: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    """Token response schema."""

    access_token: str
    token_type: str
    username: str


# --- PASSWORD HASHING ---


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


# --- JWT TOKENS ---


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# --- DATABASE OPERATIONS ---


def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_user_by_username(db: Session, username: str) -> Optional[User]:
    """Get user by username."""
    return db.query(User).filter(User.username == username).first()


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    """Get user by email."""
    return db.query(User).filter(User.email == email).first()


def get_user_by_id(db: Session, user_id: str) -> Optional[User]:
    """Get user by ID."""
    try:
        user_int_id = int(user_id)
        return db.query(User).filter(User.id == user_int_id).first()
    except (ValueError, AttributeError):
        return None


def create_user(db: Session, user: UserCreate) -> User:
    """Create a new user."""
    logger.debug(f"Creating user '{user.username}' with password length: {len(user.password)}")
    hashed_pwd = hash_password(user.password)
    logger.debug(f"Generated hash: {hashed_pwd[:20]}... (length: {len(hashed_pwd)})")
    db_user = User(
        username=user.username,
        email=user.email,
        hashed_password=hashed_pwd,
        full_name=user.full_name,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    logger.info(f"User created successfully: {user.username}")
    return db_user


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    """Authenticate a user."""
    user = get_user_by_username(db, username)
    if not user:
        logger.warning(f"Authentication failed: User '{username}' not found")
        return None

    logger.debug(f"Login attempt - Username: {username}, Password length: {len(password)}")
    logger.debug(f"Stored hash: {user.hashed_password[:20]}... (length: {len(user.hashed_password)})")

    if not verify_password(password, user.hashed_password):
        logger.warning(f"Authentication failed: Invalid password for user '{username}'")
        return None
    logger.info(f"Authentication successful for user '{username}'")
    if not user.is_active:
        return None
    return user


# --- DEPENDENCIES ---


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """Get current authenticated user from JWT token."""
    token = credentials.credentials
    logger.debug(f"Validating token: {token[:20]}...")

    try:
        payload = decode_access_token(token)
        logger.debug(f"Token decoded successfully: {payload}")
    except Exception as e:
        logger.error(f"Token decode failed: {e}")
        raise

    user_id: str = payload.get("sub")
    if user_id is None:
        logger.error("Token payload missing 'sub' field")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.debug(f"Looking up user with ID: {user_id}")
    user = get_user_by_id(db, user_id)
    if user is None:
        logger.error(f"User with ID {user_id} not found in database")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")

    return user


# --- INITIALIZATION ---


def init_db():
    """Initialize database tables."""
    Base.metadata.create_all(bind=engine)
