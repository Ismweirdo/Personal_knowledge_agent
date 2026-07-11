"""Add versioned sources and document chunks."""

import sqlalchemy as sa

from alembic import op

revision = "20260711_03"
down_revision = "20260711_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("kb_id", sa.String(36), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE")),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("active_version_id", sa.String(36)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "source_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_id", sa.String(36), sa.ForeignKey("knowledge_sources.id", ondelete="CASCADE")
        ),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("kb_id", sa.String(36), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE")),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_message", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("source_id", "content_hash", name="uq_source_hash"),
    )
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_version_id",
            sa.String(36),
            sa.ForeignKey("source_versions.id", ondelete="CASCADE"),
        ),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("kb_id", sa.String(36), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE")),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("token_count", sa.Integer, nullable=False),
        sa.Column("chunk_metadata", sa.JSON),
        sa.UniqueConstraint("source_version_id", "chunk_index", name="uq_chunk_index"),
    )
    for table, columns in {
        "knowledge_sources": ("user_id", "kb_id", "active_version_id", "status"),
        "source_versions": ("source_id", "user_id", "kb_id", "status"),
        "document_chunks": ("source_version_id", "user_id", "kb_id"),
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    op.drop_table("document_chunks")
    op.drop_table("source_versions")
    op.drop_table("knowledge_sources")
