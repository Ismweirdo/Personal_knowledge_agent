from fastapi import APIRouter

from app.api.dependencies import AdminUserId, Session
from app.api.schemas import ReviewGradeRequest
from app.learning.service import ReviewService

router = APIRouter(prefix="/admin/learning", tags=["admin-learning"])


@router.get("/review-tasks")
async def list_review_tasks(
    session: Session, user_id: AdminUserId, include_future: bool = False
) -> list[dict[str, object]]:
    rows = await ReviewService(session).due(user_id, include_future=include_future)
    return [
        {
            "id": task.id,
            "entityId": task.entity_id,
            "entityName": name,
            "mastery": task.mastery,
            "dueAt": task.due_at,
            "intervalDays": task.interval_days,
        }
        for task, name in rows
    ]


@router.post("/entities/{entity_id}/review")
async def grade_review(
    entity_id: str, payload: ReviewGradeRequest, session: Session, user_id: AdminUserId
) -> dict[str, object]:
    task = await ReviewService(session).grade(user_id, entity_id, payload.grade)
    return {
        "taskId": task.id,
        "mastery": task.mastery,
        "dueAt": task.due_at,
        "intervalDays": task.interval_days,
    }
