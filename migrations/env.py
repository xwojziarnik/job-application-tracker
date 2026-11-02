import asyncio
from logging.config import fileConfig

from alembic import context
from alembic.operations.ops import MigrationScript
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from job_tracker.core.config import get_settings
from job_tracker.models import Base

config = context.config
if config.config_file_name is not None:
    # Keep loggers that already exist: when migrations run inside the application's
    # process (e.g. the test fixtures), the default would silence the app's loggers.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def get_url() -> str:
    # Lets callers (e.g. tests) override the URL; falls back to app settings.
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def number_new_revision(
    _context: MigrationContext, _revision: object, directives: list[MigrationScript]
) -> None:
    """Give a new migration the next number as its revision ID: 001, 002, ... (D-18).

    Alembic calls this before it writes a new migration file. The numbering assumes a
    single line of migrations; with several heads ``get_current_head()`` raises, and the
    migration of the later branch has to be renumbered.
    """
    if not directives:
        return
    head = ScriptDirectory.from_config(config).get_current_head()
    number = 1 if head is None else int(head) + 1
    directives[0].rev_id = f"{number:03d}"


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        process_revision_directives=number_new_revision,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        process_revision_directives=number_new_revision,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(get_url())
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
