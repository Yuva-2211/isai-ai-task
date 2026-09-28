from enum import Enum
from typing import Dict, Any, List, Optional, Union
from pydantic import BaseModel, Field, model_validator
import uuid
import datetime

class NodeType(str, Enum):
    VALIDATION = "validation"
    TOOL = "tool"
    API = "api"
    TRANSFORM = "transform"
    CONDITION = "condition"
    HUMAN_APPROVAL = "human_approval"
    NOTIFICATION = "notification"

class ExecutionStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"

class NodeErrorPolicy(BaseModel):
    retry_count: int = Field(default=0, description="Number of retries upon error")
    fallback_node: Optional[str] = Field(default=None, description="Node ID to branch to on final error")
    fail_workflow: bool = Field(default=True, description="Fail entire workflow if error occurs and no fallback")

    @model_validator(mode='before')
    @classmethod
    def normalize_error_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if 'fallback_node' not in data and 'fallback_node_id' in data:
                data['fallback_node'] = data['fallback_node_id']
        return data

class WorkflowNode(BaseModel):
    id: str
    type: NodeType
    label: str
    description: Optional[str] = ""
    config: Dict[str, Any] = Field(default_factory=dict)
    on_error: Optional[NodeErrorPolicy] = Field(default_factory=NodeErrorPolicy)

class WorkflowEdge(BaseModel):
    from_node: str
    to_node: str
    condition_branch: Optional[str] = Field(
        default=None, 
        description="Branch evaluation trigger: 'true', 'false', or None for standard unconditional transition"
    )

    @model_validator(mode='before')
    @classmethod
    def normalize_edge_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if 'from_node' not in data:
                for k in ['from', 'source', 'fromNode', 'src']:
                    if k in data:
                        data['from_node'] = data[k]
                        break
            if 'to_node' not in data:
                for k in ['to', 'target', 'toNode', 'dest']:
                    if k in data:
                        data['to_node'] = data[k]
                        break
            if 'condition_branch' not in data:
                for k in ['condition_value', 'condition', 'branch', 'case']:
                    if k in data and data[k] is not None:
                        data['condition_branch'] = str(data[k]).lower()
                        break
            elif data.get('condition_branch') is not None:
                data['condition_branch'] = str(data['condition_branch']).lower()
        return data

class WorkflowDefinition(BaseModel):
    id: str = Field(default_factory=lambda: f"wf_{uuid.uuid4().hex[:8]}")
    name: str
    description: str
    entrypoint: str
    sample_input: Dict[str, Any] = Field(default_factory=dict)
    nodes: List[WorkflowNode]
    edges: List[WorkflowEdge]

    @model_validator(mode='before')
    @classmethod
    def normalize_definition_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if 'entrypoint' not in data:
                for k in ['entry_node_id', 'entry_node', 'entryPoint', 'start_node']:
                    if k in data:
                        data['entrypoint'] = data[k]
                        break
        return data

class StepLog(BaseModel):
    node_id: str
    node_type: str
    label: str
    status: str  # SUCCESS, FAILED, WAITING_APPROVAL, SKIPPED
    input_data: Dict[str, Any] = Field(default_factory=dict)
    output_data: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    execution_time_ms: float = 0.0
    timestamp: str = Field(default_factory=lambda: datetime.datetime.utcnow().isoformat())

class ApprovalRequest(BaseModel):
    id: str = Field(default_factory=lambda: f"appr_{uuid.uuid4().hex[:8]}")
    execution_id: str
    node_id: str
    prompt: str
    required_role: Optional[str] = "Admin"
    status: str = "PENDING"  # PENDING, APPROVED, REJECTED
    decision_comment: Optional[str] = None
    requested_at: str = Field(default_factory=lambda: datetime.datetime.utcnow().isoformat())
    resolved_at: Optional[str] = None

class WorkflowExecution(BaseModel):
    id: str = Field(default_factory=lambda: f"exec_{uuid.uuid4().hex[:8]}")
    workflow_id: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    current_node_id: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    logs: List[StepLog] = Field(default_factory=list)
    pending_approval: Optional[ApprovalRequest] = None
    started_at: str = Field(default_factory=lambda: datetime.datetime.utcnow().isoformat())
    completed_at: Optional[str] = None

class NaturalLanguagePromptRequest(BaseModel):
    prompt: str
    mock_input: Optional[Dict[str, Any]] = None
    api_key: Optional[str] = None
    model: Optional[str] = None

class ApprovalActionRequest(BaseModel):
    decision: str = Field(..., description="'APPROVE' or 'REJECT'")
    comment: Optional[str] = ""
