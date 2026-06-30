import asyncio
from core.database import engine
from core.models import Base

async def init_db():
    print("Initializing database...")
    async with engine.begin() as conn:
        # Create all tables defined in Base
        await conn.run_sync(Base.metadata.create_all)
    print("Tables created successfully!")
    # Close the engine connections
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(init_db())
