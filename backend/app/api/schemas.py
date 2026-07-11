from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CurrentUserResponse(BaseModel):
    id: str
    email: EmailStr
    role: str


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    is_published: bool = False


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    is_published: bool | None = None


class KnowledgeBaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    embedding_model: str | None
    is_published: bool
    created_at: datetime
    updated_at: datetime


class DocumentUploadResponse(BaseModel):
    source_id: str
    version_id: str
    status: str
    content_hash: str
    chunk_count: int
    unchanged: bool = False


class ConversationCreate(BaseModel):
    knowledge_base_id: str
    title: str = Field(default="New conversation", min_length=1, max_length=200)


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    knowledge_base_id: str = Field(validation_alias="kb_id")
    title: str
    created_at: datetime


class ChatRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class KnowledgeReviewRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class ReviewGradeRequest(BaseModel):
    grade: int = Field(ge=0, le=5)


class WebSourceRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


class GitSourceRequest(BaseModel):
    repository_path: str = Field(min_length=1, max_length=2000)
