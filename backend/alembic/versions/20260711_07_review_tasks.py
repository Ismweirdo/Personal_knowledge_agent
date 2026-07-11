"""Add administrator spaced-review tasks."""

import sqlalchemy as sa

from alembic import op

revision = "20260711_07"
down_revision = "20260711_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column(
            "entity_id", sa.String(36), sa.ForeignKey("knowledge_entities.id", ondelete="CASCADE")
        ),
        sa.Column("repetitions", sa.Integer, nullable=False),
        sa.Column("interval_days", sa.Integer, nullable=False),
        sa.Column("ease_factor", sa.Float, nullable=False),
        sa.Column("mastery", sa.Float, nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "entity_id", name="uq_review_user_entity"),
    )
    for column in ("user_id", "entity_id", "due_at", "status"):
        op.create_index(f"ix_review_tasks_{column}", "review_tasks", [column])


def downgrade() -> None:
    op.drop_table("review_tasks")
