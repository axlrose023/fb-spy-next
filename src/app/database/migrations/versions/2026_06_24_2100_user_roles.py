"""user_roles

Add a role column to users and seed the first admin account.

Revision ID: 9f1c4a7b2e80
Revises: 2b0ed0ccf524
Create Date: 2026-06-24 21:00:00.000000

"""

import os
from collections.abc import Sequence

import bcrypt
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9f1c4a7b2e80"
down_revision: str | None = "2b0ed0ccf524"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(length=16),
            nullable=False,
            server_default="user",
        ),
    )
    op.create_index(op.f("users_role_idx"), "users", ["role"], unique=False)

    _seed_admin()


def downgrade() -> None:
    op.drop_index(op.f("users_role_idx"), table_name="users")
    op.drop_column("users", "role")


def _seed_admin() -> None:
    username = os.getenv("INITIAL_ADMIN_USERNAME", "admin")
    password = os.getenv("INITIAL_ADMIN_PASSWORD", "admin")

    bind = op.get_bind()
    existing = bind.execute(
        sa.text("SELECT 1 FROM users WHERE username = :username"),
        {"username": username},
    ).first()
    if existing:
        return

    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode(
        "utf-8"
    )
    bind.execute(
        sa.text(
            "INSERT INTO users (username, password, role, is_active) "
            "VALUES (:username, :password, 'admin', true)"
        ),
        {"username": username, "password": hashed},
    )
