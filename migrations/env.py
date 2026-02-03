"""Alembic environment configuration."""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

config = context.config

# Override sqlalchemy.url from environment
postgres_url = os.getenv("POSTGRES_URL")
if postgres_url:
    # Convert asyncpg URL to psycopg2 for Alembic (sync operations)
    if postgres_url.startswith("postgresql://"):
        sync_url = postgres_url.replace("postgresql://", "postgresql+psycopg2://")
    else:
        sync_url = postgres_url
    config.set_main_option("sqlalchemy.url", sync_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    from sqlalchemy import create_engine

    url = config.get_main_option("sqlalchemy.url")

    # Use sync engine for migrations
    connectable = create_engine(url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
