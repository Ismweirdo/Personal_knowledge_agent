"""Add visitor feedback."""

import sqlalchemy as sa

from alembic import op

revision = "20260714_01"
down_revision = "20260711_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "visitor_feedback",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
        ),
        sa.Column("position", sa.String(120), nullable=False),
        sa.Column("comment", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_visitor_feedback_user_id", "visitor_feedback", ["user_id"])
    op.create_index(
        "ix_visitor_feedback_conversation_id", "visitor_feedback", ["conversation_id"]
    )


def downgrade() -> None:
    op.drop_table("visitor_feedback")
