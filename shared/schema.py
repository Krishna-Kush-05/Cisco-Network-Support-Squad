"""
shared/schema.py
================
NetSage AI — Shared Integration Contract
Cisco Network Support Squad

Owner: Manmath (Dashboard & Orchestration Lead)
Used by: Krishna (Data/Demo), Pratik (Rule Engine), Vishal (Agent/RAG), Manmath (Dashboard)

This file defines the single source of truth data contract for all components.
All teammates must import directly from shared.schema.
"""

from typing import List
from pydantic import BaseModel, Field


class Case(BaseModel):
    """
    Represents a networking incident case and its telemetry evidence.
    """
    case_id: str
    topology: str = ""
    fault_type: str = ""
    symptom: str
    evidence_text: str
    ground_truth: str = ""


class RuleResult(BaseModel):
    """
    Structured outcome of the deterministic rule checker.
    """
    case_id: str
    duplicate_ip: bool = False
    wrong_mask: bool = False
    gateway_mismatch: bool = False
    interface_down: bool = False
    missing_vlan: bool = False
    missing_route: bool = False
    bad_acl: bool = False
    rule_verdict: str  # Short sentence summarizing findings/verdict


class AgentDiagnosis(BaseModel):
    """
    Structured output from the LLM/RAG Diagnostic Agent.
    """
    case_id: str
    root_cause: str
    confidence: float
    osi_layer: str
    evidence: str
    next_command: str
    fix_steps: List[str] = Field(default_factory=list)
    similar_cases_used: List[str] = Field(default_factory=list)


class ReviewResult(BaseModel):
    """
    Human-in-the-loop review decision and notes.
    """
    case_id: str
    status: str          # "accepted" | "edited" | "rejected"
    reviewer_note: str = ""
