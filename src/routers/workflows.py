from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from src.db.repo import Repository
from src.schemas.workflows import WorkflowTemplateSchema, WorkflowTemplateUpsertRequest
from src.utils.deps import get_repo

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.get("", response_model=list[WorkflowTemplateSchema])
def list_workflows(repo: Repository = Depends(get_repo)) -> list[dict]:
    return repo.list_workflow_templates()


@router.get("/{template_id}", response_model=WorkflowTemplateSchema)
def get_workflow(template_id: str, repo: Repository = Depends(get_repo)) -> dict:
    workflow = repo.get_workflow_template(template_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow template not found")
    return workflow


@router.post("", response_model=WorkflowTemplateSchema)
def upsert_workflow(
    payload: WorkflowTemplateUpsertRequest,
    repo: Repository = Depends(get_repo),
) -> dict:
    repo.upsert_workflow_template(payload.model_dump())
    workflow = repo.get_workflow_template(payload.id)
    if not workflow:
        raise HTTPException(status_code=500, detail="Failed to persist workflow template")
    return workflow
