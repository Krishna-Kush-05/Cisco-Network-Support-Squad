"""
Shared data contract for NetSage AI.

Everyone on the team imports from this file — do not redefine these
models elsewhere. If this file already exists (e.g. Manmath created it),
diff before overwriting.
"""

from pydantic import BaseModel


class Case(BaseModel):
    case_id: str
    topology: str
    fault_type: str
    symptom: str
    evidence_text: str
    ground_truth: str


class RuleResult(BaseModel):
    case_id: str
    duplicate_ip: bool
    wrong_mask: bool
    gateway_mismatch: bool
    interface_down: bool
    missing_vlan: bool
    missing_route: bool
    bad_acl: bool
    rule_verdict: str  # one short sentence summarizing the flags
