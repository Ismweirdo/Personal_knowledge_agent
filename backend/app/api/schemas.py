from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=128)


class VisitorAccessRequest(BaseModel):
    access_key: str = Field(min_length=1, max_length=128)


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
    task_id: str | None = None


class BatchDocumentItemResponse(BaseModel):
    filename: str
    success: bool
    result: DocumentUploadResponse | None = None
    error_code: str | None = None
    message: str | None = None


class BatchDocumentUploadResponse(BaseModel):
    total: int
    succeeded: int
    failed: int
    items: list[BatchDocumentItemResponse]


class KnowledgeSourceResponse(BaseModel):
    id: str
    knowledge_base_id: str
    source_type: str
    display_name: str
    source_locator: str | None
    status: str
    active_version_id: str | None
    latest_version_id: str | None
    latest_version_status: str | None
    version_count: int
    chunk_count: int
    size_bytes: int | None
    task_status: str | None
    task_progress: int | None
    last_synced_at: datetime | None
    created_at: datetime


class IngestionTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
    source_version_id: str
    task_type: str
    status: str
    progress: int
    retry_count: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ConversationCreate(BaseModel):
    knowledge_base_id: str
    title: str = Field(default="New conversation", min_length=1, max_length=200)


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    knowledge_base_id: str = Field(validation_alias="kb_id")
    title: str
    created_at: datetime


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    role: str
    content: str
    status: str
    created_at: datetime


class ChatRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class VisitorFeedbackCreate(BaseModel):
    conversation_id: str | None = None
    position: str = Field(min_length=1, max_length=120)
    comment: str = Field(min_length=1, max_length=2000)


class VisitorFeedbackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    conversation_id: str | None
    position: str
    comment: str
    created_at: datetime


class KnowledgeReviewRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class ReviewGradeRequest(BaseModel):
    grade: int = Field(ge=0, le=5)


class WebSourceRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


class GitSourceRequest(BaseModel):
    repository_path: str = Field(min_length=1, max_length=2000)
