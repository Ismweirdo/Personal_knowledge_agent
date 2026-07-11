"""Add durable ingestion task orchestration."""

import sqlalchemy as sa

from alembic import op

revision = "20260711_09"
down_revision = "20260711_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingestion_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column(
            "source_id", sa.String(36), sa.ForeignKey("knowledge_sources.id", ondelete="CASCADE")
        ),
        sa.Column(
            "source_version_id",
            sa.String(36),
            sa.ForeignKey("source_versions.id", ondelete="CASCADE"),
        ),
        sa.Column("task_type", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("progress", sa.Integer, nullable=False),
        sa.Column("retry_count", sa.Integer, nullable=False),
        sa.Column("max_retries", sa.Integer, nullable=False),
        sa.Column("error_code", sa.String(100)),
        sa.Column("error_message", sa.String(500)),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    for column in ("user_id", "source_id", "source_version_id", "status", "next_retry_at"):
        op.create_index(f"ix_ingestion_tasks_{column}", "ingestion_tasks", [column])


def downgrade() -> None:
    op.drop_table("ingestion_tasks")
