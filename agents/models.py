"""
Shared Pydantic models for the AI-agent toolkit research pipeline.
"""

from __future__ import annotations
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class SelfServeStatus(str, Enum):
    SELF_SERVE_FREE = "self_serve_free"
    SELF_SERVE_TRIAL = "self_serve_trial"
    GATED_PAID_PLAN = "gated_paid_plan"
    GATED_APPROVAL = "gated_approval"
    GATED_PARTNERSHIP = "gated_partnership"
    OPEN_SOURCE_SELF_HOST = "open_source_self_host"


class APISurface(str, Enum):
    REST = "rest"
    GRAPHQL = "graphql"
    REST_AND_GRAPHQL = "rest_and_graphql"
    SDK_ONLY = "sdk_only"
    NONE_PUBLIC = "none_public"


class APIBreadth(str, Enum):
    BROAD = "broad"
    MODERATE = "moderate"
    NARROW = "narrow"


class MCPStatus(str, Enum):
    OFFICIAL = "official"
    COMMUNITY_UNOFFICIAL = "community_unofficial"
    NONE = "none"
    UNKNOWN = "unknown"


class BuildabilityVerdict(str, Enum):
    READY = "ready"
    READY_WITH_FRICTION = "ready_with_friction"
    BLOCKED = "blocked"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AppResearch(BaseModel):
    id: int
    app: str
    category: str
    one_liner: str = Field(description="One sentence description of what the app does")
    auth_methods: List[str] = Field(description="Auth methods supported, e.g. ['oauth2', 'api_key']")
    self_serve_status: SelfServeStatus
    gating_evidence_note: str = Field(description="Short evidence note for self_serve_status classification")
    api_surface: APISurface
    api_breadth: APIBreadth
    has_mcp: MCPStatus
    buildability_verdict: BuildabilityVerdict
    main_blocker: str = Field(description="'none' if verdict is ready, otherwise describe the blocker")
    evidence_urls: List[str] = Field(description="Actual URLs fetched as evidence")
    confidence: Confidence
    error: Optional[str] = Field(default=None, description="Set if research failed, describes reason")


class AppInput(BaseModel):
    id: int
    app: str
    category: str
    hint: str
