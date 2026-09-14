"""Switch embeddings to the local 1024-dimensional BGE-M3 model."""

from alembic import op

revision = "20260914_01"
down_revision = "20260714_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_document_chunks_embedding_hnsw", table_name="document_chunks")
    # Vectors from a different model cannot be compared with BGE-M3 vectors.
    op.execute("UPDATE document_chunks SET embedding = NULL")
    op.execute(
        "ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(1024) "
        "USING embedding::vector(1024)"
    )
    op.create_index(
        "ix_document_chunks_embedding_hnsw",
        "document_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    # Keep raw chunks, but require the reindex script to generate BGE-M3 vectors.
    op.execute("UPDATE source_versions SET status = 'PARSED' WHERE status = 'READY'")
    op.execute("UPDATE knowledge_sources SET status = 'PROCESSING', active_version_id = NULL")


def downgrade() -> None:
    op.drop_index("ix_document_chunks_embedding_hnsw", table_name="document_chunks")
    op.execute("UPDATE document_chunks SET embedding = NULL")
    op.execute(
        "ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(1536) "
        "USING embedding::vector(1536)"
    )
    op.create_index(
        "ix_document_chunks_embedding_hnsw",
        "document_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
