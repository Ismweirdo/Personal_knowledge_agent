"""Add web and Git synchronization metadata."""

import sqlalchemy as sa

from alembic import op

revision = "20260711_08"
down_revision = "20260711_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_sources", sa.Column("source_locator", sa.String(1000)))
    op.create_index("ix_knowledge_sources_source_locator", "knowledge_sources", ["source_locator"])
    op.add_column("source_versions", sa.Column("etag", sa.String(500)))
    op.add_column("source_versions", sa.Column("last_modified", sa.String(200)))
    op.add_column("source_versions", sa.Column("revision", sa.String(100)))


def downgrade() -> None:
    op.drop_column("source_versions", "revision")
    op.drop_column("source_versions", "last_modified")
    op.drop_column("source_versions", "etag")
    op.drop_index("ix_knowledge_sources_source_locator", table_name="knowledge_sources")
    op.drop_column("knowledge_sources", "source_locator")
