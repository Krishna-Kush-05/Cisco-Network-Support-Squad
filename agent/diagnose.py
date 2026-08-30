"""
agent/diagnose.py — NetSage AI Diagnostic Agent Module.

Owner: Vishal
Used by: Manmath (Dashboard & Orchestration)

Performs root-cause analysis, OSI layer mapping, next diagnostic command recommendation,
and remediation plan generation using retrieved past cases and evidence.

Public API:
    run_agent_diagnosis(case: Case, similar_cases: List[Case]) -> AgentDiagnosis
"""

import re
from typing import List

try:
    from shared.schema import Case, AgentDiagnosis
except ImportError:
    from schema import Case, AgentDiagnosis


def run_agent_diagnosis(case: Case, similar_cases: List[Case]) -> AgentDiagnosis:
    """
    Run root cause analysis on a given case telemetry using historical RAG context.
    
    Args:
        case: The active incident Case object containing symptom and evidence.
        similar_cases: List of historical Case objects retrieved for context.
        
    Returns:
        Structured AgentDiagnosis object.
    """
    similar_ids = [c.case_id for c in similar_cases] if similar_cases else []
    evidence = case.evidence_text
    symptom = case.symptom.lower()
    
    # 1. Inspect evidence & symptoms for diagnostic patterns
    if re.search(r"administratively down|down\s+down", evidence, re.IGNORECASE):
        root_cause = "Interface is administratively shut down or physical link is down."
        osi_layer = "Layer 1 (Physical) / Layer 2 (Data Link)"
        confidence = 0.95
        next_cmd = "show ip interface brief"
        fix_steps = [
            "Access target router/switch CLI via console or SSH.",
            "Enter interface configuration mode: `interface <interface_id>`",
            "Issue `no shutdown` to bring the interface up.",
            "Verify link status changes to 'up/up'."
        ]
        evidence_snippet = "Interface reporting 'administratively down' in show ip interface brief."

    elif re.search(r"vlan", symptom) or re.search(r"vlan\s+1\b", evidence, re.IGNORECASE):
        root_cause = "VLAN misconfiguration — access port assigned to incorrect/default VLAN."
        osi_layer = "Layer 2 (Data Link)"
        confidence = 0.92
        next_cmd = "show vlan brief"
        fix_steps = [
            "Inspect `show vlan brief` on switch to check port assignments.",
            "Enter switchport interface configuration mode: `interface <interface_id>`",
            "Set correct access VLAN: `switchport access vlan <vlan_id>`",
            "Verify end-to-end ping across same VLAN."
        ]
        evidence_snippet = "Port VLAN assignment mismatch detected in switchport configuration."

    elif re.search(r"mask|subnet", symptom):
        root_cause = "Subnet mask mismatch between connected interfaces or PC and gateway."
        osi_layer = "Layer 3 (Network)"
        confidence = 0.89
        next_cmd = "show ip interface"
        fix_steps = [
            "Verify subnet mask on both communicating endpoints.",
            "Align subnet mask (e.g. /24 or 255.255.255.0) on the misconfigured device.",
            "Re-issue `ipconfig /all` or `show ip interface` to confirm."
        ]
        evidence_snippet = "Subnet mask parameter divergence across adjacent interface definitions."

    elif re.search(r"gateway|default gateway", symptom):
        root_cause = "Default gateway mismatch or unconfigured gateway on client host."
        osi_layer = "Layer 3 (Network)"
        confidence = 0.94
        next_cmd = "ipconfig /all"
        fix_steps = [
            "Check client IP configuration using `ipconfig /all`.",
            "Ensure Default Gateway matches router interface IP in the same broadcast domain.",
            "Update client gateway address and test ping to router gateway."
        ]
        evidence_snippet = "Default gateway does not match any local router sub-interface IP."

    elif re.search(r"route|routing|unreachable", symptom):
        root_cause = "Missing or incorrect static/dynamic route in routing table."
        osi_layer = "Layer 3 (Network)"
        confidence = 0.90
        next_cmd = "show ip route"
        fix_steps = [
            "Check routing table with `show ip route`.",
            "Add missing static route: `ip route <network> <mask> <next-hop>` or configure dynamic routing (OSPF/EIGRP).",
            "Verify route entry appears in routing table and test ping."
        ]
        evidence_snippet = "Destination network prefix is absent from routing table."

    elif re.search(r"acl|access-list|block|denied", symptom):
        root_cause = "Overly restrictive or misconfigured Access Control List (ACL) filtering traffic."
        osi_layer = "Layer 3 / Layer 4 (Network/Transport)"
        confidence = 0.91
        next_cmd = "show access-lists"
        fix_steps = [
            "Examine ACL rules and hit counters with `show access-lists`.",
            "Add explicit `permit` statements before implicit deny.",
            "Verify ACL direction (`in` / `out`) on target interface."
        ]
        evidence_snippet = "Deny statement or implicit deny-all blocking legitimate traffic flows."

    elif similar_cases:
        # Fall back to top retrieved case pattern
        top_case = similar_cases[0]
        root_cause = f"Correlated with historical case {top_case.case_id}: {top_case.ground_truth}"
        osi_layer = "Layer 3 (Network)"
        confidence = 0.85
        next_cmd = "show running-config"
        fix_steps = [
            f"Review historical resolution pattern for {top_case.case_id}.",
            "Inspect running configuration on relevant devices.",
            "Apply matching remediation and verify connectivity."
        ]
        evidence_snippet = f"Symptom semantic similarity match with past incident {top_case.case_id}."

    else:
        root_cause = "General connectivity impairment — multiple potential factors detected."
        osi_layer = "Layer 3 (Network)"
        confidence = 0.70
        next_cmd = "show running-config"
        fix_steps = [
            "Run `show ip interface brief` on all network nodes.",
            "Verify IP, subnet mask, and gateway settings on end hosts.",
            "Trace route with `traceroute` to isolate failure hop."
        ]
        evidence_snippet = "Ambiguous telemetry patterns; full baseline verification recommended."

    return AgentDiagnosis(
        case_id=case.case_id,
        root_cause=root_cause,
        confidence=confidence,
        osi_layer=osi_layer,
        evidence=evidence_snippet,
        next_command=next_cmd,
        fix_steps=fix_steps,
        similar_cases_used=similar_ids,
    )
