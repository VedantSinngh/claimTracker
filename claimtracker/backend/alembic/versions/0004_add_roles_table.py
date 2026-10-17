"""Normalise users.role into a `roles` lookup table.

Replaces the `users.role` enum column with `users.role_id` → `roles.id`.

Why: adding a role to a Postgres ENUM requires ALTER TYPE (which cannot run
inside a transaction block) and removing one is impossible; role metadata also
had nowhere to live. A lookup table makes both an ordinary DML statement and
puts `description` in 3NF — it depends on the role, not on the user.

The three role names are preserved exactly ("user", "reviewer", "admin"), so
JWT claims and the `require_role` guards are unaffected.

Upgrade is data-preserving: every existing user is matched to the seeded role
with the same name before the old column is dropped. Downgrade reverses it,
restoring the enum column and its values.

Revision ID: 0004
Revises: 0003
Create Date: 2024-01-04 00:00:00.000000
"""
import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Fixed UUIDs so the seed is deterministic across environments — fixtures and
# the downgrade path can rely on them.
ROLE_SEED: list[tuple[str, str, str]] = [
    (
        "11111111-1111-1111-1111-111111111111",
        "user",
        "Submits claims and views only their own.",
    ),
    (
        "22222222-2222-2222-2222-222222222222",
        "reviewer",
        "Works the NEEDS_REVIEW queue; can approve, reject or override a decision.",
    ),
    (
        "33333333-3333-3333-3333-333333333333",
        "admin",
        "Full access: handbook ingestion, exclusions management, all claims.",
    ),
]

_DEFAULT_ROLE = "user"


def _roles_table() -> sa.Table:
    """Lightweight table definition for bulk_insert / DML in this migration."""
    return sa.table(
        "roles",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    # ── 1. roles table ─────────────────────────────────────────────
    op.create_table(
        "roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_roles_name"),
    )
    op.create_index("ix_roles_name", "roles", ["name"], unique=True)

    # ── 2. Seed the three canonical roles ──────────────────────────
    now = datetime.now(timezone.utc)
    op.bulk_insert(
        _roles_table(),
        [
            {
                # SQLAlchemy's Uuid type wants a uuid.UUID on both backends
                # (it stores CHAR(32) on SQLite, native uuid on Postgres).
                "id": uuid.UUID(role_id),
                "name": name,
                "description": description,
                "created_at": now,
            }
            for role_id, name, description in ROLE_SEED
        ],
    )

    # ── 3. Add the FK column, nullable for now ─────────────────────
    op.add_column(
        "users",
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # ── 4. Data migration: match each user to the role of the same name ──
    op.execute(
        """
        UPDATE users
           SET role_id = (SELECT r.id FROM roles r WHERE r.name = users.role)
        """
    )
    # Safety net: any row whose enum value somehow has no matching role
    # (should be impossible given the enum) falls back to 'user' so that
    # the NOT NULL constraint below cannot fail.
    op.execute(
        f"""
        UPDATE users
           SET role_id = (SELECT r.id FROM roles r WHERE r.name = '{_DEFAULT_ROLE}')
         WHERE role_id IS NULL
        """
    )

    # ── 5. Enforce NOT NULL + FK, then drop the old enum column ────
    # batch_alter_table so SQLite (dev) gets a table rebuild and Postgres
    # gets plain ALTERs.
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column(
            "role_id",
            existing_type=postgresql.UUID(as_uuid=True),
            nullable=False,
        )
        batch_op.create_foreign_key(
            "fk_users_role_id_roles",
            "roles",
            ["role_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.drop_column("role")

    op.create_index("ix_users_role_id", "users", ["role_id"])

    # ── 6. The enum type is now unreferenced ───────────────────────
    if not is_sqlite:
        postgresql.ENUM(name="user_role_enum").drop(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    # ── 1. Recreate the enum type ──────────────────────────────────
    user_role = postgresql.ENUM("user", "reviewer", "admin", name="user_role_enum")
    if not is_sqlite:
        user_role.create(bind, checkfirst=True)

    op.drop_index("ix_users_role_id", table_name="users")

    # ── 2. Re-add the enum column, nullable so existing rows survive ──
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.Enum("user", "reviewer", "admin", name="user_role_enum"),
            nullable=True,
            server_default=_DEFAULT_ROLE,
        ),
    )

    # ── 3. Data migration back: role_id → role name ────────────────
    # Cast is required on Postgres because the target column is an enum.
    if is_sqlite:
        op.execute(
            """
            UPDATE users
               SET role = (SELECT r.name FROM roles r WHERE r.id = users.role_id)
            """
        )
    else:
        op.execute(
            """
            UPDATE users
               SET role = (
                     SELECT r.name FROM roles r WHERE r.id = users.role_id
                   )::user_role_enum
            """
        )
    op.execute(
        f"UPDATE users SET role = '{_DEFAULT_ROLE}' WHERE role IS NULL"
    )

    # ── 4. Enforce NOT NULL, drop the FK column ────────────────────
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column(
            "role",
            existing_type=sa.Enum("user", "reviewer", "admin", name="user_role_enum"),
            nullable=False,
        )
        batch_op.drop_constraint("fk_users_role_id_roles", type_="foreignkey")
        batch_op.drop_column("role_id")

    # ── 5. Drop the lookup table ───────────────────────────────────
    op.drop_index("ix_roles_name", table_name="roles")
    op.drop_table("roles")
