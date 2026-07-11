import argparse
import asyncio
from getpass import getpass

from sqlalchemy import select

from app.infrastructure.database import SessionFactory
from app.infrastructure.models import User
from app.infrastructure.security import password_hash


async def bootstrap(email: str, password: str) -> None:
    async with SessionFactory() as session:
        user = await session.scalar(select(User).where(User.email == email.lower()))
        if user is None:
            user = User(
                email=email.lower(), password_hash=password_hash.hash(password), role="ADMIN"
            )
            session.add(user)
        else:
            user.role = "ADMIN"
            user.password_hash = password_hash.hash(password)
        await session.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or promote the sole administrator")
    parser.add_argument("email")
    args = parser.parse_args()
    password = getpass("Administrator password: ")
    if len(password) < 8:
        raise SystemExit("Password must contain at least 8 characters")
    asyncio.run(bootstrap(args.email, password))


if __name__ == "__main__":
    main()
