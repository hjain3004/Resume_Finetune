from pydantic import BaseModel, ConfigDict
from typing import Literal, Optional

# --- 1. Draft Phase ---
class Requirement(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    id: str
    source_span_id: str
    quote: str
    requirement: str
    importance: Literal["must_have", "nice_to_have"]
    evidence_ids: list[str]

class DraftedBullet(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    id: str
    entry_id: str
    section: str
    text: str
    supported_requirement_ids: list[str]
    evidence_ids: list[str]

class DraftResponse(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    requirements: list[Requirement]
    bullets: list[DraftedBullet]
    omitted_evidence_ids: dict[str, str]

# --- 2. Audit & Re-Audit Phases ---
class AuditBulletResult(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    index: int
    evidence_ids: list[str]
    supported_claims: list[str]
    unsupported_claims: list[str]
    metric_fidelity: Literal["ok", "altered", "invented"]
    technology_fidelity: Literal["ok", "altered", "invented"]
    ownership_fidelity: Literal["ok", "overstated"]
    relevance: Literal[1, 2, 3]
    coherence: Literal[1, 2, 3]
    readability: Literal[1, 2, 3]
    repair_required: bool
    reason: str

class AuditResponse(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    results: list[AuditBulletResult]

# --- 3. Repair Phase ---
class RepairedBullet(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    id: str
    text: str

class RepairResponse(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    repaired_bullets: list[RepairedBullet]
