"""Add administrator role and knowledge publication."""

import sqlalchemy as sa

from alembic import op

revision = "20260711_06"
down_revision = "20260711_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("role", sa.String(20), nullable=False, server_default="USER"))
    op.create_index("ix_users_role", "users", ["role"])
    op.add_column(
        "knowledge_bases",
        sa.Column("is_published", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_knowledge_bases_is_published", "knowledge_bases", ["is_published"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_bases_is_published", table_name="knowledge_bases")
    op.drop_column("knowledge_bases", "is_published")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_column("users", "role")
