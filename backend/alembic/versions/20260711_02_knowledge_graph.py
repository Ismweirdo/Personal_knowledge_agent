"""Add evidence-backed knowledge graph and learning events."""

import sqlalchemy as sa

from alembic import op

revision = "20260711_02"
down_revision = "20260711_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_entities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("kb_id", sa.String(36), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE")),
        sa.Column("canonical_name", sa.String(200), nullable=False),
        sa.Column("normalized_name", sa.String(200), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("summary", sa.Text),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("extractor_version", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("kb_id", "entity_type", "normalized_name", name="uq_entity_identity"),
    )
    _create_entity_indexes()
    _create_relation_table()
    _create_evidence_table()
    _create_revision_table()
    _create_learning_event_table()


def _create_entity_indexes() -> None:
    for column in ("user_id", "kb_id", "status"):
        op.create_index(f"ix_knowledge_entities_{column}", "knowledge_entities", [column])


def _create_relation_table() -> None:
    op.create_table(
        "knowledge_relations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("kb_id", sa.String(36), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE")),
        sa.Column(
            "source_entity_id",
            sa.String(36),
            sa.ForeignKey("knowledge_entities.id", ondelete="CASCADE"),
        ),
        sa.Column("predicate", sa.String(100), nullable=False),
        sa.Column(
            "target_entity_id",
            sa.String(36),
            sa.ForeignKey("knowledge_entities.id", ondelete="CASCADE"),
        ),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("extractor_version", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "kb_id", "source_entity_id", "predicate", "target_entity_id", name="uq_relation"
        ),
    )
    for column in ("user_id", "kb_id", "source_entity_id", "target_entity_id", "status"):
        op.create_index(f"ix_knowledge_relations_{column}", "knowledge_relations", [column])


def _create_evidence_table() -> None:
    op.create_table(
        "knowledge_evidence",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("kb_id", sa.String(36), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE")),
        sa.Column(
            "entity_id", sa.String(36), sa.ForeignKey("knowledge_entities.id", ondelete="CASCADE")
        ),
        sa.Column(
            "relation_id",
            sa.String(36),
            sa.ForeignKey("knowledge_relations.id", ondelete="CASCADE"),
        ),
        sa.Column("source_version_id", sa.String(36), nullable=False),
        sa.Column("chunk_id", sa.String(36), nullable=False),
        sa.Column("locator", sa.String(500)),
        sa.Column("quote_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "(entity_id IS NOT NULL AND relation_id IS NULL) OR "
            "(entity_id IS NULL AND relation_id IS NOT NULL)",
            name="ck_evidence_single_target",
        ),
    )


def _create_revision_table() -> None:
    op.create_table(
        "knowledge_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("kb_id", sa.String(36), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE")),
        sa.Column("target_type", sa.String(30), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("before_value", sa.JSON),
        sa.Column("after_value", sa.JSON),
        sa.Column("reason", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def _create_learning_event_table() -> None:
    op.create_table(
        "learning_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("kb_id", sa.String(36), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE")),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column(
            "topic_entity_id",
            sa.String(36),
            sa.ForeignKey("knowledge_entities.id", ondelete="SET NULL"),
        ),
        sa.Column("source_id", sa.String(36)),
        sa.Column("event_metadata", sa.JSON),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    for table in (
        "learning_events",
        "knowledge_revisions",
        "knowledge_evidence",
        "knowledge_relations",
        "knowledge_entities",
    ):
        op.drop_table(table)
