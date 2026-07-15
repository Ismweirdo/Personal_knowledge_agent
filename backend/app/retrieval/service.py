import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.embedding import EmbeddingClient
from app.infrastructure.models import DocumentChunk, KnowledgeSource, SourceVersion


@dataclass(frozen=True)
class RetrievalResult:
    chunk_id: str
    content: str
    score: float
    metadata: dict[str, object] | None


@dataclass(frozen=True)
class _Candidate:
    chunk: DocumentChunk
    source: KnowledgeSource
    score: float


class RetrievalService:
    def __init__(self, session: AsyncSession, embedding_client: EmbeddingClient) -> None:
        self.session = session
        self.embedding_client = embedding_client

    async def search(
        self,
        user_id: str,
        knowledge_base_id: str,
        query: str,
        *,
        limit: int = 10,
    ) -> list[RetrievalResult]:
        intent = _profile_intent(query)
        if intent is not None:
            candidates = await self._profile_candidates(
                user_id, knowledge_base_id, query, intent
            )
        else:
            candidates = await self._vector_candidates(user_id, knowledge_base_id, query, limit)
        ranked = _balance_sources(candidates, limit)
        return [
            RetrievalResult(
                chunk_id=item.chunk.id,
                content=item.chunk.content,
                score=item.score,
                metadata={
                    **(item.chunk.chunk_metadata or {}),
                    "source_id": item.source.id,
                    "source_type": item.source.source_type,
                    "source_name": item.source.display_name,
                },
            )
            for item in ranked
        ]

    async def _active_chunks(
        self, user_id: str, knowledge_base_id: str
    ) -> list[tuple[DocumentChunk, KnowledgeSource]]:
        rows = await self.session.execute(
            select(DocumentChunk, KnowledgeSource)
            .join(SourceVersion, SourceVersion.id == DocumentChunk.source_version_id)
            .join(
                KnowledgeSource,
                (KnowledgeSource.id == SourceVersion.source_id)
                & (KnowledgeSource.active_version_id == SourceVersion.id),
            )
            .where(
                DocumentChunk.user_id == user_id,
                DocumentChunk.kb_id == knowledge_base_id,
                SourceVersion.status == "READY",
                KnowledgeSource.status == "READY",
            )
        )
        return list(rows.tuples())

    async def _profile_candidates(
        self, user_id: str, knowledge_base_id: str, query: str, intent: str
    ) -> list[_Candidate]:
        candidates: list[_Candidate] = []
        for chunk, source in await self._active_chunks(user_id, knowledge_base_id):
            score = _profile_score(query, intent, chunk, source)
            if score > 0:
                candidates.append(_Candidate(chunk, source, score))
        return sorted(candidates, key=lambda item: item.score, reverse=True)

    async def _vector_candidates(
        self, user_id: str, knowledge_base_id: str, query: str, limit: int
    ) -> list[_Candidate]:
        vectors = await self.embedding_client.embed(_expanded_queries(query))
        candidates: dict[str, _Candidate] = {}
        for vector in vectors:
            distance = DocumentChunk.embedding.cosine_distance(vector)
            rows = await self.session.execute(
                select(DocumentChunk, KnowledgeSource, distance.label("distance"))
                .join(SourceVersion, SourceVersion.id == DocumentChunk.source_version_id)
                .join(
                    KnowledgeSource,
                    (KnowledgeSource.id == SourceVersion.source_id)
                    & (KnowledgeSource.active_version_id == SourceVersion.id),
                )
                .where(
                    DocumentChunk.user_id == user_id,
                    DocumentChunk.kb_id == knowledge_base_id,
                    DocumentChunk.embedding.is_not(None),
                    SourceVersion.status == "READY",
                    KnowledgeSource.status == "READY",
                )
                .order_by(distance)
                .limit(max(limit * 3, 12))
            )
            for chunk, source, value in rows:
                vector_score = max(0.0, 1.0 - float(value))
                score = _combined_score(query, chunk, source, vector_score)
                current = candidates.get(chunk.id)
                if current is None or score > current.score:
                    candidates[chunk.id] = _Candidate(chunk, source, score)
        return sorted(candidates.values(), key=lambda item: item.score, reverse=True)


def _profile_intent(query: str) -> str | None:
    if any(word in query for word in ("项目", "经历", "做过", "作品", "亮点")):
        return "PROJECT"
    if any(word in query for word in ("技能", "技术", "技术栈", "会什么", "擅长")):
        return "SKILL"
    if any(word in query for word in ("岗位", "适合", "匹配", "优势")):
        return "JOB"
    return None


def _profile_score(
    query: str,
    intent: str,
    chunk: DocumentChunk,
    source: KnowledgeSource,
) -> float:
    text = chunk.content.lower()
    lexical = _lexical_overlap(query, chunk.content)
    if source.source_type == "FILE":
        signals = {
            "PROJECT": ("项目经历", "项目", "github"),
            "SKILL": ("专业技能", "技术", "java", "python"),
            "JOB": ("教育背景", "项目经历", "技术", "后端"),
        }[intent]
        return 1.0 + lexical if any(signal in text for signal in signals) else 0.72
    if source.source_type != "GIT":
        return lexical
    score = 0.0
    if "# 项目资料卡" in chunk.content or chunk.chunk_index == 0:
        score = 0.96
    elif "# 代码结构摘要" in chunk.content:
        score = 0.84 if intent in {"PROJECT", "SKILL"} else 0.62
    elif "# 项目文档" in chunk.content:
        score = 0.76
    elif "# 项目配置摘要" in chunk.content:
        score = 0.64 if intent == "SKILL" else 0.48
    if intent == "SKILL" and any(
        signal in text
        for signal in ("java", "python", "fastapi", "vue", "redis", "mysql", "docker")
    ):
        score += 0.1
    return score + lexical * 0.12


def _balance_sources(candidates: list[_Candidate], limit: int) -> list[_Candidate]:
    by_source: dict[str, list[_Candidate]] = {}
    for candidate in candidates:
        by_source.setdefault(candidate.source.id, []).append(candidate)
    ordered_sources = sorted(
        by_source,
        key=lambda source_id: by_source[source_id][0].score,
        reverse=True,
    )
    selected: list[_Candidate] = []
    depth = 0
    while len(selected) < limit:
        added = False
        for source_id in ordered_sources:
            values = by_source[source_id]
            if depth < len(values):
                selected.append(values[depth])
                added = True
                if len(selected) == limit:
                    break
        if not added:
            break
        depth += 1
    return selected


def _expanded_queries(query: str) -> list[str]:
    values = [query]
    if any(word in query for word in ("学习", "课程", "知识", "了解")):
        values.append(f"{query} 学习记录 课程 知识 笔记")
    return list(dict.fromkeys(values))


def _combined_score(
    query: str,
    chunk: DocumentChunk,
    source: KnowledgeSource,
    vector_score: float,
) -> float:
    lexical = _lexical_overlap(query, chunk.content)
    boost = 0.06 if source.source_type == "FILE" else 0.0
    return vector_score * 0.84 + lexical * 0.16 + boost


def _lexical_overlap(query: str, content: str) -> float:
    tokens = {token.lower() for token in re.findall(r"[\w\u4e00-\u9fff]{2,}", query)}
    if not tokens:
        return 0.0
    text = content.lower()
    hits = sum(1 for token in tokens if token in text)
    return min(1.0, hits / max(3, len(tokens)))
