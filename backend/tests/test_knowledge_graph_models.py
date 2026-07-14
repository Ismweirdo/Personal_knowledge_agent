from app.infrastructure.models import Base


def test_knowledge_graph_and_learning_tables_are_registered() -> None:
    expected_tables = {
        "knowledge_entities",
        "knowledge_relations",
        "knowledge_evidence",
        "knowledge_revisions",
        "learning_events",
    }

    assert expected_tables <= set(Base.metadata.tables)


def test_evidence_requires_exactly_one_target() -> None:
    table = Base.metadata.tables["knowledge_evidence"]
    constraint_names = {constraint.name for constraint in table.constraints}

    assert "ck_evidence_single_target" in constraint_names


def test_entity_identity_is_unique_within_knowledge_base() -> None:
    table = Base.metadata.tables["knowledge_entities"]
    constraint_names = {constraint.name for constraint in table.constraints}

    assert "uq_entity_identity" in constraint_names


def test_document_chunks_have_vector_embedding_column() -> None:
    column = Base.metadata.tables["document_chunks"].c.embedding

    assert column.type.dim == 1536


def test_conversation_tables_are_registered() -> None:
    assert {"conversations", "messages", "message_citations", "visitor_feedback"} <= set(
        Base.metadata.tables
    )


def test_review_task_table_is_registered() -> None:
    assert "review_tasks" in Base.metadata.tables
