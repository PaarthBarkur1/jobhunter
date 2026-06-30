import os
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.exc import SQLAlchemyError
import logging

from .models import Base

# Setup basic logging
logger = logging.getLogger(__name__)

# Ensure data directory exists
os.makedirs('data', exist_ok=True)

# Database URL
DATABASE_URL = "sqlite+aiosqlite:///data/jobs.db"

# Create async engine with pool_pre_ping for stability
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True
)

# Create an async session maker
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

@asynccontextmanager
async def get_db_session():
    """
    Context manager for database sessions.
    Usage:
        async with get_db_session() as session:
            # perform database operations
    """
    session = AsyncSessionLocal()
    try:
        yield session
        await session.commit()
    except SQLAlchemyError as e:
        logger.error(f"Database error occurred: {e}")
        await session.rollback()
        raise
    except Exception as e:
        logger.error(f"Unexpected error in DB session: {e}")
        await session.rollback()
        raise
    finally:
        await session.close()
