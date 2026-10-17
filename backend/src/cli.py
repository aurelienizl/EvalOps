"""Create/reset a local operator-managed account without exposing passwords."""

import argparse
import asyncio
import getpass
from .core.config import load_settings
from .core.security import hash_password
from .database.connection import open_pool


async def run(email, role):
    password = getpass.getpass("Password (at least 12 characters): ")
    if len(password) < 12 or password != getpass.getpass("Confirm password: "):
        raise SystemExit("Password mismatch or too short")
    pool = await open_pool(load_settings())
    try:
        async with pool.acquire() as c, c.transaction():
            user_id = await c.fetchval(
                """INSERT INTO users(email,password_hash,role) VALUES($1,$2,$3)
                ON CONFLICT(email) DO UPDATE SET password_hash=$2,role=$3 RETURNING id""",
                email.strip().lower(),
                hash_password(password),
                role,
            )
            await c.execute("DELETE FROM sessions WHERE user_id=$1", user_id)
        print("Account saved:", email)
    finally:
        await pool.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email")
    parser.add_argument("--role", choices=["student", "admin"], default="student")
    args = parser.parse_args()
    asyncio.run(run(args.email, args.role))
