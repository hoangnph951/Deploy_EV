"""Add account authentication and user vehicles.

Revision ID: 20260815_0010
Revises: 20260812_1845
"""

import sqlalchemy as sa
from alembic import op

revision = "20260815_0010"
down_revision = "20260812_1845"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("phone", sa.String(length=24), nullable=True),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"], unique=True)
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])

    op.create_table(
        "user_vehicles",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "vehicle_profile_id",
            sa.String(length=64),
            sa.ForeignKey("vehicle_profiles.id"),
            nullable=False,
        ),
        sa.Column("nickname", sa.String(length=80), nullable=True),
        sa.Column("license_plate", sa.String(length=24), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "vehicle_profile_id", "license_plate", name="uq_user_vehicle_identity"
        ),
    )
    op.create_index("ix_user_vehicles_user_id", "user_vehicles", ["user_id"])
    op.create_index("ix_user_vehicles_vehicle_profile_id", "user_vehicles", ["vehicle_profile_id"])
    op.create_index("ix_user_vehicles_is_default", "user_vehicles", ["is_default"])


def downgrade() -> None:
    op.drop_index("ix_user_vehicles_is_default", table_name="user_vehicles")
    op.drop_index("ix_user_vehicles_vehicle_profile_id", table_name="user_vehicles")
    op.drop_index("ix_user_vehicles_user_id", table_name="user_vehicles")
    op.drop_table("user_vehicles")
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_token_hash", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
