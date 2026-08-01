import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
import src.workers.merchant_commands as mc

sent: list[str] = []


async def fake_send_text(to: str, text: str) -> None:
    sent.append((to, text))


async def main():
    mc.send_text = fake_send_text
    engine = create_async_engine("postgresql+asyncpg://postgres:postgres@localhost:5433/whatappseller")
    async with AsyncSession(engine) as db:
        await mc.handle_code(db, "rs-ifqd", "+256700000002")
        await mc.handle_code(db, "RS-NOPE", "+256700000002")
        await mc.handle_code(db, "", "+256700000002")
    await engine.dispose()

    for to, text in sent:
        print(f"--- To {to} ---")
        print(text)


asyncio.run(main())
