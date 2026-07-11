from fastapi import APIRouter
from sqlalchemy import select

from app.api.dependencies import AdminUserId, Session
from app.api.schemas import IngestionTaskResponse
from app.infrastructure.errors import ApplicationError
from app.infrastructure.models import IngestionTask

router = APIRouter(prefix="/admin/tasks", tags=["admin-tasks"])


@router.get("", response_model=list[IngestionTaskResponse])
async def list_tasks(
    session: Session,
    user_id: AdminUserId,
    status: str | None = None,
) -> list[IngestionTask]:
    query = (
        select(IngestionTask)
        .where(IngestionTask.user_id == user_id)
        .order_by(IngestionTask.created_at.desc())
        .limit(100)
    )
    if status:
        query = query.where(IngestionTask.status == status.upper())
    return list(await session.scalars(query))


@router.get("/{task_id}", response_model=IngestionTaskResponse)
async def get_task(task_id: str, session: Session, user_id: AdminUserId) -> IngestionTask:
    return await _task(session, user_id, task_id)


@router.post("/{task_id}:retry", response_model=IngestionTaskResponse)
async def retry_task(task_id: str, session: Session, user_id: AdminUserId) -> IngestionTask:
    task = await _task(session, user_id, task_id)
    if task.status != "FAILED":
        raise ApplicationError(
            "TASK_NOT_RETRYABLE", "Only failed tasks can be retried", status_code=409
        )
    task.status = "PENDING"
    task.progress = 0
    task.retry_count = 0
    task.error_code = None
    task.error_message = None
    task.next_retry_at = None
    task.finished_at = None
    await session.commit()
    return task


async def _task(session: Session, user_id: str, task_id: str) -> IngestionTask:
    task = await session.scalar(
        select(IngestionTask).where(
            IngestionTask.id == task_id,
            IngestionTask.user_id == user_id,
        )
    )
    if task is None:
        raise ApplicationError("TASK_NOT_FOUND", "Ingestion task not found", status_code=404)
    return task
