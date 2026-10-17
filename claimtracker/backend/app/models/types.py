"""
app/models/types.py
────────────────────
Shared column types that have to behave on both backends.

The stack targets PostgreSQL in production and SQLite for local dev and most
tests, through the same models and the same Alembic chain. `postgresql.JSONB`
does not survive that: SQLite's type compiler cannot render it, so both
`create_all` and `alembic upgrade head` fail with

    CompileError: ... Compiler <SQLiteTypeCompiler> can't render element of
    type JSONB

`with_variant` fixes it at the type level — JSONB on Postgres (so the GIN
indexing and containment operators stay available), plain JSON elsewhere.
SQLAlchemy stores JSON as TEXT on SQLite and serialises transparently, so model
code reads and writes ordinary dicts and lists either way.

Use `JSONColumn` for every JSON column, in models *and* in migrations, so the
two never drift.

Note that `postgresql.UUID(as_uuid=True)` needs no equivalent: in SQLAlchemy
2.0 it subclasses the cross-dialect `Uuid` type and renders as CHAR(32) on
SQLite already.
"""
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

#: JSONB on PostgreSQL, JSON (TEXT-backed) on SQLite and anything else.
JSONColumn = JSON().with_variant(JSONB(), "postgresql")

__all__ = ["JSONColumn"]
