from dotenv import load_dotenv
load_dotenv(override=True)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, Optional, List
from src.models.schema import (
    WorkflowDefinition,
    WorkflowExecution,
    NaturalLanguagePromptRequest,
    ApprovalActionRequest
)
from src.database.db import (
    save_workflow,
    get_workflow,
    list_workflows,
    get_execution
)
from src.engine.runner import WorkflowRunner
from src.generator.groq_client import generate_workflow_from_prompt
from src.generator.templates import get_predefined_templates, get_template_as_workflow

app = FastAPI(
    title="Natural Language Workflow Generator API",
    description="Transforms natural language requirements into validated, executable DAG workflows.",
    version="1.0.0"
)

# Enable CORS for local dashboards
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup_populate_templates():
    """Ensure baseline templates exist in SQLite on startup."""
    for t in get_predefined_templates():
        if not get_workflow(t["id"]):
            wf = get_template_as_workflow(t["id"])
            save_workflow(wf)

@app.get("/api/health")
def health_check():
    return {"status": "healthy", "service": "workflow-engine"}

@app.post("/api/workflows/generate", response_model=WorkflowDefinition)
def generate_workflow(req: NaturalLanguagePromptRequest):
    """
    Translates a natural language business objective into an executable workflow DAG using Groq LLM.
    """
    try:
        wf = generate_workflow_from_prompt(req.prompt, api_key=req.api_key, model=req.model)
        save_workflow(wf)
        return wf
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")

@app.get("/api/workflows", response_model=List[WorkflowDefinition])
def get_all_workflows():
    return list_workflows()

@app.get("/api/workflows/{workflow_id}", response_model=WorkflowDefinition)
def get_single_workflow(workflow_id: str):
    wf = get_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return wf

@app.post("/api/workflows/{workflow_id}/execute", response_model=WorkflowExecution)
def execute_workflow(workflow_id: str, input_payload: Optional[Dict[str, Any]] = None):
    """
    Initializes and starts running a workflow execution. Pauses automatically if Human Approval is required.
    """
    wf = get_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    exec_obj = WorkflowRunner.initialize_execution(wf, input_payload)
    updated_exec = WorkflowRunner.run_step_by_step(exec_obj.id)
    return updated_exec

@app.get("/api/executions/{execution_id}", response_model=WorkflowExecution)
def get_execution_status(execution_id: str):
    exec_obj = get_execution(execution_id)
    if not exec_obj:
        raise HTTPException(status_code=404, detail="Execution not found")
    return exec_obj

@app.post("/api/executions/{execution_id}/decision", response_model=WorkflowExecution)
def resolve_human_approval(execution_id: str, action: ApprovalActionRequest):
    """
    Resumes a paused workflow execution when a human approver submits APPROVE or REJECT.
    """
    try:
        resumed_exec = WorkflowRunner.resume_approval(execution_id, action.decision, action.comment)
        return resumed_exec
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
