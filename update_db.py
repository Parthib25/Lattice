import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def update_db():
    engine = create_async_engine('postgresql+asyncpg://postgres:Parthib%40123@host.docker.internal:5432/Lattice')
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE main.chat_sessions SET model = 'gemini-3.5-flash' WHERE provider = 'gemini'"))
        print('Updated successfully to 3.5 flash')
    await engine.dispose()

asyncio.run(update_db())
