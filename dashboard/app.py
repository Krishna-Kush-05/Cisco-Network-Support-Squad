"""
dashboard/app.py — NetSage AI Orchestration & Review Dashboard.

Single entry point for the NetSage AI demo (Cisco Network Support Squad).
Orchestrates:
  1. Deterministic Rule Checker (Pratik)
  2. RAG Historical Case Retrieval (Vishal)
  3. LLM Diagnostic Agent (Vishal)
  4. Human-in-the-Loop Review & Log Appender (Manmath)
  5. Statistical Analytics & Agreement Dashboard (Manmath)

Author: Manmath (Dashboard & Orchestration Lead)
"""

import sys
import json
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

# Ensure project root is in sys.path for clean, standardized imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
import pandas as pd

# Core integration contract & teammate module imports
from shared.schema import Case, RuleResult, AgentDiagnosis, ReviewResult
from rules.checker import run_rule_check
from agent.retrieval import retrieve_similar_cases
from agent.diagnose import run_agent_diagnosis


# ---------------------------------------------------------------------------
# Streamlit Page Configuration & Modern Cisco-Themed Styling
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="NetSage AI — Cisco Network Support Squad",
    page_icon="🌐",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    /* Global Typography & Palette */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    code, pre {
        font-family: 'JetBrains Mono', monospace !important;
    }
    
    /* Header Card */
    .netsage-header {
        background: linear-gradient(135deg, #0A2540 0%, #005073 50%, #049FD9 100%);
        padding: 1.6rem 2rem;
        border-radius: 12px;
        color: white;
        margin-bottom: 1.5rem;
        box-shadow: 0 4px 20px rgba(0, 80, 115, 0.25);
    }
    .netsage-header h1 {
        margin: 0;
        font-size: 2rem;
        font-weight: 800;
        letter-spacing: -0.5px;
        color: #FFFFFF !important;
    }
    .netsage-header p {
        margin: 0.3rem 0 0 0;
        font-size: 1rem;
        color: #E0F2FE;
        opacity: 0.95;
    }
    
    /* Section Cards */
    .diagnostic-card {
        background: #FFFFFF;
        border-radius: 10px;
        padding: 1.2rem 1.4rem;
        border: 1px solid #E2E8F0;
        box-shadow: 0 2px 10px rgba(0,0,0,0.03);
        margin-bottom: 1.2rem;
    }
    
    /* Status Badges */
    .badge-success {
        background-color: #DEF7EC;
        color: #03543F;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.85rem;
        display: inline-block;
    }
    .badge-danger {
        background-color: #FDE8E8;
        color: #9B1C1C;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.85rem;
        display: inline-block;
    }
    .badge-info {
        background-color: #E1EFFE;
        color: #1E429F;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.85rem;
        display: inline-block;
    }
    
    /* Metric pill container */
    .metric-pill {
        background-color: #F8FAFC;
        border-left: 4px solid #049FD9;
        padding: 0.8rem 1rem;
        border-radius: 6px;
        margin-bottom: 0.8rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Path & Data Persistence Utilities
# ---------------------------------------------------------------------------

RESULTS_DIR = PROJECT_ROOT / "results"
RESULTS_FILE = RESULTS_DIR / "results.json"
CASES_DIR = PROJECT_ROOT / "data" / "cases"


def ensure_results_dir() -> None:
    """Ensure the results directory exists."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def to_dict(pydantic_obj: Any) -> Dict[str, Any]:
    """Helper to convert Pydantic model to dictionary across v1 and v2."""
    if hasattr(pydantic_obj, "model_dump"):
        return pydantic_obj.model_dump()
    elif hasattr(pydantic_obj, "dict"):
        return pydantic_obj.dict()
    return dict(pydantic_obj)


def append_result_to_json(
    case: Case,
    rule_result: RuleResult,
    agent_diagnosis: AgentDiagnosis,
    review_result: ReviewResult,
) -> None:
    """
    Append a complete diagnosis & review record to results/results.json in JSON lines format.
    """
    ensure_results_dir()
    record = {
        "timestamp": datetime.now().isoformat(),
        "case_id": case.case_id,
        "topology": case.topology,
        "fault_type": case.fault_type,
        "symptom": case.symptom,
        "evidence_text": case.evidence_text,
        "ground_truth": case.ground_truth,
        # Rule Results
        "duplicate_ip": rule_result.duplicate_ip,
        "wrong_mask": rule_result.wrong_mask,
        "gateway_mismatch": rule_result.gateway_mismatch,
        "interface_down": rule_result.interface_down,
        "missing_vlan": rule_result.missing_vlan,
        "missing_route": rule_result.missing_route,
        "bad_acl": rule_result.bad_acl,
        "rule_verdict": rule_result.rule_verdict,
        # Agent Results
        "root_cause": agent_diagnosis.root_cause,
        "confidence": agent_diagnosis.confidence,
        "osi_layer": agent_diagnosis.osi_layer,
        "evidence": agent_diagnosis.evidence,
        "next_command": agent_diagnosis.next_command,
        "fix_steps": agent_diagnosis.fix_steps,
        "similar_cases_used": agent_diagnosis.similar_cases_used,
        # Review Results
        "review_status": review_result.status,
        "reviewer_note": review_result.reviewer_note,
        # Nested schemas for full contract preservation
        "_raw_case": to_dict(case),
        "_raw_rule_result": to_dict(rule_result),
        "_raw_agent_diagnosis": to_dict(agent_diagnosis),
        "_raw_review_result": to_dict(review_result),
    }

    with open(RESULTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def load_all_results_df() -> pd.DataFrame:
    """Read every line of results/results.json into a pandas DataFrame."""
    if not RESULTS_FILE.exists() or RESULTS_FILE.stat().st_size == 0:
        return pd.DataFrame()

    records = []
    with open(RESULTS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if line_str:
                try:
                    records.append(json.loads(line_str))
                except Exception:
                    continue

    if not records:
        return pd.DataFrame()

    return pd.DataFrame(records)


def compute_agreement(row: pd.Series) -> bool:
    """
    Check if the rule checker flags and agent root cause point at the same fault category.
    """
    rule_verdict = str(row.get("rule_verdict", "")).lower()
    root_cause = str(row.get("root_cause", "")).lower()
    osi_layer = str(row.get("osi_layer", "")).lower()

    flag_keywords = {
        "duplicate_ip": ["duplicate", "conflict", "ip"],
        "wrong_mask": ["mask", "subnet", "prefix"],
        "gateway_mismatch": ["gateway", "default gateway", "gw"],
        "interface_down": ["interface", "shutdown", "link down", "down", "physical"],
        "missing_vlan": ["vlan", "switchport", "access vlan", "trunk"],
        "missing_route": ["route", "routing", "unreachable", "next-hop"],
        "bad_acl": ["acl", "access-list", "deny", "filter"],
    }

    active_flags = [flag for flag in flag_keywords if row.get(flag) is True]

    if not active_flags:
        # Rule found no violations -> agreement if agent also sees no hard rule violation or ambiguous
        return "no rule violations" in rule_verdict or "general" in root_cause

    # Check if agent root cause or OSI layer touches any active flag keywords
    for flag in active_flags:
        keywords = flag_keywords[flag]
        if any(kw in root_cause or kw in osi_layer for kw in keywords):
            return True

    return False


def load_sample_cases_from_disk() -> Dict[str, Dict[str, str]]:
    """Load sample cases from data/cases for quick loading during live demos."""
    samples = {}
    if not CASES_DIR.exists():
        return samples

    case_re = re.compile(
        r"CASE_ID\s*:\s*(?P<case_id>.*?)\n"
        r"TOPOLOGY\s*:\s*(?P<topology>.*?)\n"
        r"FAULT_TYPE\s*:\s*(?P<fault_type>.*?)\n"
        r"SYMPTOM\s*:\s*(?P<symptom>.*?)\n"
        r"GROUND_TRUTH\s*:\s*(?P<ground_truth>.*?)\n"
        r"---\s*EVIDENCE START\s*---\n"
        r"(?P<evidence_text>.*?)"
        r"---\s*EVIDENCE END\s*---",
        re.DOTALL | re.IGNORECASE,
    )

    for case_file in sorted(CASES_DIR.glob("case_*.txt")):
        try:
            content = case_file.read_text(encoding="utf-8")
            m = case_re.search(content)
            if m:
                cid = m.group("case_id").strip()
                samples[f"{cid} ({m.group('fault_type').strip()})"] = {
                    "case_id": cid,
                    "topology": m.group("topology").strip(),
                    "fault_type": m.group("fault_type").strip(),
                    "symptom": m.group("symptom").strip(),
                    "ground_truth": m.group("ground_truth").strip(),
                    "evidence_text": m.group("evidence_text").strip(),
                }
        except Exception:
            continue
    return samples


# ---------------------------------------------------------------------------
# Sidebar: Squad Information & Pipeline Architecture
# ---------------------------------------------------------------------------

with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/0/08/Cisco_logo_blue_2016.svg", width=120)
    st.title("NetSage AI")
    st.markdown("**Cisco Network Support Squad**")
    st.caption("AI-Powered Autonomous Network Triage & Verification")
    
    st.divider()
    
    st.markdown("### 👥 Team Modules & Ownership")
    st.markdown("- **Manmath** — Dashboard, Orchestration, Docker (`shared/schema.py`)")
    st.markdown("- **Krishna** — Packet Tracer Topologies & Telemetry Ingestion")
    st.markdown("- **Pratik** — Deterministic Rule Checker (`rules/checker.py`)")
    st.markdown("- **Vishal** — RAG Retrieval & Diagnostic Agent (`agent/`)")

    st.divider()
    st.markdown("### 🔄 Orchestration Flow")
    st.markdown("`Fault` ➔ `Evidence` ➔ `Rules + Agent` ➔ `Compare` ➔ `Human Review` ➔ `Fix & Verify`")


# ---------------------------------------------------------------------------
# Main App Header
# ---------------------------------------------------------------------------

st.markdown(
    """
    <div class="netsage-header">
        <h1>🌐 NetSage AI — Network Diagnostic Studio</h1>
        <p>Real-time autonomous telemetry analysis, deterministic rule verification, and human-in-the-loop remediation</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# Initialize Session State
if "active_case" not in st.session_state:
    st.session_state.active_case = None
if "active_rule_result" not in st.session_state:
    st.session_state.active_rule_result = None
if "active_agent_diagnosis" not in st.session_state:
    st.session_state.active_agent_diagnosis = None
if "active_similar_cases" not in st.session_state:
    st.session_state.active_similar_cases = []
if "review_submitted" not in st.session_state:
    st.session_state.review_submitted = False

tab1, tab2 = st.tabs(["🔍 Diagnose a Case", "📊 Dashboard & Analytics"])


# ===========================================================================
# TAB 1: DIAGNOSE A CASE
# ===========================================================================

with tab1:
    st.markdown("### 1. Ingest Case & Telemetry Evidence")
    
    sample_cases = load_sample_cases_from_disk()
    
    # Preset sample selector for quick demoing
    col_preset, col_clear = st.columns([4, 1])
    with col_preset:
        preset_options = ["-- Custom / Manual Entry --"] + list(sample_cases.keys())
        selected_preset = st.selectbox("⚡ Quick Load Sample Case (Live Demo)", preset_options)
    
    with col_clear:
        st.write("")
        st.write("")
        if st.button("🧹 Clear Form", use_container_width=True):
            st.session_state.active_case = None
            st.session_state.active_rule_result = None
            st.session_state.active_agent_diagnosis = None
            st.session_state.active_similar_cases = []
            st.session_state.review_submitted = False
            st.rerun()

    # Pre-fill values if sample selected
    default_symptom = ""
    default_evidence = ""
    default_topology = "topo_A"
    default_fault_type = ""
    default_ground_truth = ""
    
    if selected_preset != "-- Custom / Manual Entry --" and selected_preset in sample_cases:
        chosen = sample_cases[selected_preset]
        default_symptom = chosen["symptom"]
        default_evidence = chosen["evidence_text"]
        default_topology = chosen["topology"]
        default_fault_type = chosen["fault_type"]
        default_ground_truth = chosen["ground_truth"]

    # Input Fields
    symptom_input = st.text_area(
        "🚨 Reported Symptom (Observed Network Failure)",
        value=default_symptom,
        placeholder="e.g. PC0 cannot reach the default gateway or web server at 192.168.2.10...",
        height=90,
    )
    
    evidence_input = st.text_area(
        "📋 Raw Telemetry & Command Evidence (Krishna pastes live during demo)",
        value=default_evidence,
        placeholder="Paste CLI outputs here (e.g., Switch#show vlan brief, Router#show ip int brief, PC>ipconfig /all)...",
        height=180,
    )
    
    with st.expander("⚙️ Optional Metadata (For Logging & Evaluation Only — Not Shown to AI)", expanded=False):
        col_m1, col_m2, col_m3 = st.columns(3)
        with col_m1:
            topology_input = st.text_input("Topology Identifier", value=default_topology)
        with col_m2:
            fault_type_input = st.text_input("Fault Type Category", value=default_fault_type, placeholder="e.g. vlan_mismatch")
        with col_m3:
            ground_truth_input = st.text_input("Ground Truth Root Cause", value=default_ground_truth, placeholder="Actual cause for benchmarking")

    # Diagnose Button
    diagnose_col1, diagnose_col2 = st.columns([1, 4])
    with diagnose_col1:
        diagnose_clicked = st.button("🚀 Diagnose Case", type="primary", use_container_width=True)

    if diagnose_clicked:
        if not symptom_input.strip() or not evidence_input.strip():
            st.error("⚠️ Please provide both a symptom and raw evidence text before running diagnosis.")
        else:
            with st.spinner("Executing Deterministic Rule Checker & Multi-Case RAG Agent..."):
                # 1. Build Case object
                auto_case_id = f"case_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                case_obj = Case(
                    case_id=auto_case_id,
                    topology=topology_input.strip() or "topo_A",
                    fault_type=fault_type_input.strip(),
                    symptom=symptom_input.strip(),
                    evidence_text=evidence_input.strip(),
                    ground_truth=ground_truth_input.strip(),
                )
                
                # 2. Call Pratik's deterministic rule engine
                rule_res = run_rule_check(case_obj)
                
                # 3. Call Vishal's RAG retrieval and Diagnostic Agent
                retrieved_cases = retrieve_similar_cases(case_obj.symptom, k=3)
                agent_diag = run_agent_diagnosis(case_obj, retrieved_cases)
                
                # Save to session state
                st.session_state.active_case = case_obj
                st.session_state.active_rule_result = rule_res
                st.session_state.active_agent_diagnosis = agent_diag
                st.session_state.active_similar_cases = retrieved_cases
                st.session_state.review_submitted = False

    # -----------------------------------------------------------------------
    # Display Results Side-by-Side
    # -----------------------------------------------------------------------
    if st.session_state.active_case is not None:
        st.divider()
        st.markdown(f"### 2. Diagnosis Results — `{st.session_state.active_case.case_id}`")
        
        col_rule, col_agent = st.columns(2)
        
        # Left Column: Deterministic Rule Checker
        with col_rule:
            st.markdown("#### 🛡️ Deterministic Rule Engine (`rules/checker.py`)")
            rule_res: RuleResult = st.session_state.active_rule_result
            
            # Rule Verdict Card
            if "no rule violations" in rule_res.rule_verdict.lower():
                st.success(f"**Verdict:** {rule_res.rule_verdict}")
            else:
                st.error(f"**Verdict:** {rule_res.rule_verdict}")
            
            # Individual Flags Grid
            st.markdown("**Rule Verification Breakdown:**")
            flags_map = [
                ("Duplicate IP", rule_res.duplicate_ip),
                ("Subnet Mask Mismatch", rule_res.wrong_mask),
                ("Default Gateway Mismatch", rule_res.gateway_mismatch),
                ("Interface Down", rule_res.interface_down),
                ("VLAN Mismatch / Default VLAN", rule_res.missing_vlan),
                ("Missing Route Subnet", rule_res.missing_route),
                ("Misconfigured / Restrictive ACL", rule_res.bad_acl),
            ]
            
            for label, is_flagged in flags_map:
                f_col1, f_col2 = st.columns([3, 1])
                f_col1.write(label)
                if is_flagged:
                    f_col2.markdown("<span class='badge-danger'>FLAGGED</span>", unsafe_allow_html=True)
                else:
                    f_col2.markdown("<span class='badge-success'>PASSED</span>", unsafe_allow_html=True)

        # Right Column: LLM Diagnostic Agent
        with col_agent:
            st.markdown("#### 🧠 Diagnostic Agent & RAG (`agent/diagnose.py`)")
            agent_diag: AgentDiagnosis = st.session_state.active_agent_diagnosis
            
            # Root Cause & Confidence
            st.info(f"**Root Cause:** {agent_diag.root_cause}")
            
            m_col1, m_col2 = st.columns(2)
            with m_col1:
                st.metric("Agent Confidence", f"{int(agent_diag.confidence * 100)}%")
            with m_col2:
                st.metric("OSI Target Layer", agent_diag.osi_layer)
                
            st.markdown(f"**Identified Evidence:** `{agent_diag.evidence}`")
            st.markdown(f"**Recommended Diagnostic Command:**")
            st.code(agent_diag.next_command, language="bash")
            
            st.markdown("**Recommended Fix Steps:**")
            for idx, step in enumerate(agent_diag.fix_steps, 1):
                st.markdown(f"{idx}. {step}")
                
            if agent_diag.similar_cases_used:
                with st.expander(f"📚 Past Similar Cases Used ({len(agent_diag.similar_cases_used)})"):
                    for sc_id in agent_diag.similar_cases_used:
                        st.markdown(f"- `{sc_id}`")

        # -------------------------------------------------------------------
        # Human-in-the-Loop Review Section
        # -------------------------------------------------------------------
        st.divider()
        st.markdown("### 3. Human-in-the-Loop Review & Resolution Verification")
        
        with st.form("review_form"):
            rev_col1, rev_col2 = st.columns([1, 2])
            
            with rev_col1:
                review_status = st.radio(
                    "Review Decision",
                    ["accepted", "edited", "rejected"],
                    format_func=lambda x: {
                        "accepted": "✅ Accept Diagnosis & Plan",
                        "edited": "✏️ Edit / Modify Diagnosis",
                        "rejected": "❌ Reject Diagnosis",
                    }[x],
                )
            
            with rev_col2:
                reviewer_note = st.text_area(
                    "Reviewer Notes / Verification Feedback",
                    placeholder="e.g. Verified in Packet Tracer topology; fix command applied and ping succeeded.",
                    height=100,
                )
                
            submit_review = st.form_submit_button("💾 Submit Review & Log Case", type="primary")
            
            if submit_review:
                review_obj = ReviewResult(
                    case_id=st.session_state.active_case.case_id,
                    status=review_status,
                    reviewer_note=reviewer_note.strip(),
                )
                
                append_result_to_json(
                    case=st.session_state.active_case,
                    rule_result=st.session_state.active_rule_result,
                    agent_diagnosis=st.session_state.active_agent_diagnosis,
                    review_result=review_obj,
                )
                st.session_state.review_submitted = True
                st.success(f"✅ Case `{st.session_state.active_case.case_id}` reviewed ({review_status}) and appended to `results/results.json`!")


# ===========================================================================
# TAB 2: DASHBOARD & STATS
# ===========================================================================

with tab2:
    st.markdown("### 📊 NetSage AI — Diagnostics & Agreement Analytics")
    
    df = load_all_results_df()
    
    if df.empty:
        st.info("ℹ️ No diagnosed cases recorded yet. Ingest and review cases in Tab 1 to generate live statistics.")
    else:
        # Add agreement column
        df["agreement"] = df.apply(compute_agreement, axis=1)
        
        # Key Summary Metrics
        total_cases = len(df)
        accepted_count = len(df[df["review_status"] == "accepted"])
        acceptance_rate = (accepted_count / total_cases * 100) if total_cases > 0 else 0
        agreed_count = df["agreement"].sum()
        agreement_rate = (agreed_count / total_cases * 100) if total_cases > 0 else 0
        avg_confidence = df["confidence"].mean() * 100 if "confidence" in df.columns else 0
        
        met1, met2, met3, met4 = st.columns(4)
        met1.metric("Total Cases Diagnosed", total_cases)
        met2.metric("Acceptance Rate", f"{acceptance_rate:.1f}%")
        met3.metric("Rule/Agent Agreement", f"{agreement_rate:.1f}%")
        met4.metric("Avg Agent Confidence", f"{avg_confidence:.1f}%")
        
        st.divider()
        
        # Charts Row
        chart_col1, chart_col2 = st.columns(2)
        
        with chart_col1:
            st.markdown("#### 📌 Case Count per Fault Type")
            fault_counts = df["fault_type"].replace("", "Uncategorized").value_counts().reset_index()
            fault_counts.columns = ["Fault Type", "Count"]
            st.bar_chart(fault_counts.set_index("Fault Type"))
            
        with chart_col2:
            st.markdown("#### 🎯 Human Review Verdicts (Accepted vs Edited vs Rejected)")
            status_counts = df["review_status"].value_counts().reset_index()
            status_counts.columns = ["Review Status", "Count"]
            st.bar_chart(status_counts.set_index("Review Status"))

        st.divider()
        
        # Agreement & Diagnostic Comparison Table
        st.markdown("#### 🤝 Rule Checker vs. Agent Diagnosis Agreement Matrix")
        st.caption("Evaluates whether deterministic rule engine flags and agent root cause point to the same fault category.")
        
        display_df = df[[
            "case_id",
            "fault_type",
            "rule_verdict",
            "root_cause",
            "agreement",
            "review_status",
            "confidence",
        ]].copy()
        
        display_df["agreement"] = display_df["agreement"].apply(lambda x: "🤝 Agreed" if x else "⚠️ Diverged")
        display_df["confidence"] = display_df["confidence"].apply(lambda x: f"{int(x * 100)}%" if pd.notnull(x) else "N/A")
        
        st.dataframe(
            display_df,
            use_container_width=True,
            column_config={
                "case_id": "Case ID",
                "fault_type": "Fault Type",
                "rule_verdict": "Rule Engine Verdict",
                "root_cause": "Agent Root Cause",
                "agreement": "Agreement",
                "review_status": "Human Review",
                "confidence": "Confidence",
            },
            hide_index=True,
        )
        
        with st.expander("📑 Raw Results JSON Log Viewer"):
            st.json(df.to_dict(orient="records"))
