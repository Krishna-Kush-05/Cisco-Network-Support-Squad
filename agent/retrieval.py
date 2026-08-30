"""
agent/retrieval.py — NetSage AI Case Retrieval Module (RAG).

Owner: Vishal
Used by: Manmath (Dashboard & Orchestration)

Retrieves top-k similar historical networking incident cases from data/cases
given a symptom description.

Public API:
    retrieve_similar_cases(symptom: str, k: int = 3) -> List[Case]
"""

import os
import re
from pathlib import Path
from typing import List

try:
    from shared.schema import Case
except ImportError:
    from schema import Case

_CASE_FILE_RE = re.compile(
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


def _load_all_known_cases() -> List[Case]:
    """Scan data/cases directory and parse all case_XX.txt files into Case models."""
    cases: List[Case] = []
    
    # Try multiple standard directory locations
    search_dirs = [
        Path(__file__).resolve().parent.parent / "data" / "cases",
        Path(__file__).resolve().parent.parent / "data",
        Path.cwd() / "data" / "cases",
        Path.cwd(),
    ]
    
    seen_ids = set()
    for directory in search_dirs:
        if not directory.exists():
            continue
        for file_path in directory.glob("case_*.txt"):
            try:
                content = file_path.read_text(encoding="utf-8")
                m = _CASE_FILE_RE.search(content)
                if m:
                    case_id = m.group("case_id").strip()
                    if case_id not in seen_ids:
                        seen_ids.add(case_id)
                        cases.append(
                            Case(
                                case_id=case_id,
                                topology=m.group("topology").strip(),
                                fault_type=m.group("fault_type").strip(),
                                symptom=m.group("symptom").strip(),
                                ground_truth=m.group("ground_truth").strip(),
                                evidence_text=m.group("evidence_text").strip(),
                            )
                        )
            except Exception:
                continue
                
    return cases


def _compute_similarity(text1: str, text2: str) -> float:
    """Compute word overlap Jaccard similarity between two strings."""
    words1 = set(re.findall(r"\w+", text1.lower()))
    words2 = set(re.findall(r"\w+", text2.lower()))
    if not words1 or not words2:
        return 0.0
    intersection = words1.intersection(words2)
    union = words1.union(words2)
    return len(intersection) / len(union)


def retrieve_similar_cases(symptom: str, k: int = 3) -> List[Case]:
    """
    Retrieve top-k similar historical cases matching the input symptom.
    
    Args:
        symptom: The reported symptom string.
        k: Maximum number of similar cases to return.
        
    Returns:
        List of Case objects ordered by relevance.
    """
    all_cases = _load_all_known_cases()
    if not all_cases:
        return []
        
    # Rank cases by symptom + fault_type similarity
    scored = []
    for c in all_cases:
        score = _compute_similarity(symptom, f"{c.symptom} {c.fault_type} {c.ground_truth}")
        scored.append((score, c))
        
    # Sort descending by score
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for score, c in scored if score > 0.0][:k]
