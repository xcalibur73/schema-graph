"""
Graph Integrity Scorer for SchemaGraph.

Calculates the Graph Integrity Score (0-100) and letter grade (A-F)
based on multi-page JSON-LD knowledge graph analysis results.

Scoring Weights:
- Reference Integrity (35%): Percentage of @id references that resolve to defined nodes
- Entity Connectivity (25%): Ratio of connected vs orphan entity nodes
- Disambiguation Depth (20%): Presence of sameAs, url, and identifier on key entities
- Publisher Consistency (10%): Metadata uniformity across all publisher references
- Author Consistency (10%): Metadata uniformity across all author references

Grade Thresholds:
- A: >= 90.0 (Excellent Knowledge Graph Integrity)
- B: >= 75.0 (Good Integrity, Minor Remediation Needed)
- C: >= 60.0 (Acceptable Graph, Noticeable Disconnects)
- D: >= 40.0 (Poor Graph Integrity, Critical Missing Nodes)
- F: < 40.0  (Failing Entity Graph, High Fragmentation)

Author: @xcalibur73
"""

from typing import Any, Dict, List, Optional

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

# Scoring weights
WEIGHT_REFERENCE_INTEGRITY: float = 0.35
WEIGHT_ENTITY_CONNECTIVITY: float = 0.25
WEIGHT_DISAMBIGUATION_DEPTH: float = 0.20
WEIGHT_PUBLISHER_CONSISTENCY: float = 0.10
WEIGHT_AUTHOR_CONSISTENCY: float = 0.10

# Recognized key entity types for disambiguation depth
KEY_ENTITY_TYPES: set[str] = {
    "organization",
    "person",
    "website",
    "corporation",
    "localbusiness",
    "educationalorganization",
    "governmentorganization",
    "ngo",
}


class ComponentScores(dict):
    """Component scores dictionary with support for standard names and aliases."""

    _ALIASES: dict[str, str] = {
        "ref_score": "reference_integrity",
        "reference_score": "reference_integrity",
        "references": "reference_integrity",
        "connectivity_score": "entity_connectivity",
        "connectivity": "entity_connectivity",
        "disambiguation_score": "disambiguation_depth",
        "disambiguation": "disambiguation_depth",
        "publisher_score": "publisher_consistency",
        "publisher": "publisher_consistency",
        "author_score": "author_consistency",
        "author": "author_consistency",
    }

    def __getitem__(self, key: str) -> Any:
        mapped = self._ALIASES.get(key, key)
        return super().__getitem__(mapped)

    def get(self, key: str, default: Any = None) -> Any:
        mapped = self._ALIASES.get(key, key)
        return super().get(mapped, default)

    def __contains__(self, key: object) -> bool:
        if isinstance(key, str):
            mapped = self._ALIASES.get(key, key)
            return super().__contains__(mapped)
        return super().__contains__(key)


def calculate_reference_integrity_score(total_refs: int, broken_refs: int) -> float:
    """Score 0-100 based on percentage of valid references.

    Calculates the ratio of @id references that successfully resolve to defined
    nodes within the crawled site graph against total references.

    Args:
        total_refs: Total count of @id references discovered.
        broken_refs: Count of references pointing to non-existent entity nodes.

    Returns:
        float: Score from 0.0 to 100.0 representing reference integrity.
    """
    try:
        total = int(total_refs)
        broken = int(broken_refs)
    except (TypeError, ValueError):
        return 0.0

    if total <= 0:
        return 100.0 if broken <= 0 else 0.0

    if broken < 0:
        broken = 0
    elif broken > total:
        broken = total

    valid_refs = total - broken
    score = (valid_refs / total) * 100.0
    return round(float(score), 2)


def calculate_connectivity_score(total_nodes: int, orphan_nodes: int) -> float:
    """Score 0-100 based on ratio of connected nodes.

    Measures graph cohesion by calculating the percentage of entity nodes
    that participate in directed reference relationships (non-orphans).

    Args:
        total_nodes: Total count of entity nodes declared in the graph.
        orphan_nodes: Count of nodes declared but never referenced by any entity.

    Returns:
        float: Score from 0.0 to 100.0 representing graph connectivity.
    """
    try:
        total = int(total_nodes)
        orphans = int(orphan_nodes)
    except (TypeError, ValueError):
        return 0.0

    if total <= 0:
        return 100.0 if orphans <= 0 else 0.0

    if orphans < 0:
        orphans = 0
    elif orphans > total:
        orphans = total

    connected_nodes = total - orphans
    score = (connected_nodes / total) * 100.0
    return round(float(score), 2)


def _is_key_entity(item: dict) -> bool:
    """Determine whether a dict corresponds to a key entity type."""
    raw_type = item.get("@type") or item.get("type") or item.get("entity_type")
    if not raw_type:
        return False
    if isinstance(raw_type, list):
        types = [str(t).strip().lower().split("/")[-1].split("#")[-1] for t in raw_type]
    else:
        types = [str(raw_type).strip().lower().split("/")[-1].split("#")[-1]]

    return any(
        t in KEY_ENTITY_TYPES or t.endswith("organization") or t.endswith("person")
        for t in types
    )


def calculate_disambiguation_score(disambiguation_results: list[dict]) -> float:
    """Score 0-100 based on sameAs coverage on key entity types.

    Evaluates disambiguation depth across key entities (Organization, Person, WebSite),
    checking for sameAs external authority links (Wikidata, Wikipedia, social profiles),
    official canonical url, and unique identifier attributes.

    Args:
        disambiguation_results: List of entity dictionaries or audit result records.

    Returns:
        float: Score from 0.0 to 100.0 representing disambiguation coverage.
    """
    if not disambiguation_results or not isinstance(disambiguation_results, list):
        return 100.0

    # Filter to key entities if type information is present
    target_items = [
        item for item in disambiguation_results
        if isinstance(item, dict) and _is_key_entity(item)
    ]

    # If no items explicitly matched key entity types, evaluate all dictionaries
    if not target_items:
        target_items = [item for item in disambiguation_results if isinstance(item, dict)]

    if not target_items:
        return 100.0

    item_scores: list[float] = []

    for item in target_items:
        # Precomputed score takes precedence
        if "score" in item:
            try:
                sc = float(item["score"])
                item_scores.append(round(max(0.0, min(100.0, sc)), 2))
                continue
            except (TypeError, ValueError):
                pass

        # Handle findings from audit_disambiguation
        status_str = str(item.get("status", "")).strip().lower()
        if status_str == "missing_all":
            item_scores.append(0.0)
            continue
        elif status_str == "missing_kg_authority":
            # Entity has sameAs social profiles but lacks Wikidata/Wikipedia authority reconciliation
            item_scores.append(50.0)
            continue

        # Check sameAs signals
        has_same_as = False
        if "has_same_as" in item:
            has_same_as = bool(item["has_same_as"])
        elif "has_sameAs" in item:
            has_same_as = bool(item["has_sameAs"])
        elif "sameAs" in item:
            val = item["sameAs"]
            has_same_as = bool(val) and (len(val) > 0 if isinstance(val, (list, dict, str)) else True)
        elif "same_as" in item:
            val = item["same_as"]
            has_same_as = bool(val) and (len(val) > 0 if isinstance(val, (list, dict, str)) else True)
        elif "same_as_links" in item:
            has_same_as = bool(item["same_as_links"])
        elif "same_as_count" in item:
            has_same_as = int(item.get("same_as_count", 0)) > 0
        elif item.get("has_wikidata") or item.get("has_wikipedia"):
            has_same_as = True
        elif item.get("is_disambiguated") or item.get("disambiguated"):
            has_same_as = True
        elif status_str in ("pass", "valid", "disambiguated", "ok"):
            has_same_as = True

        # Check url presence
        checked_url = False
        has_url = False
        if "has_url" in item:
            checked_url = True
            has_url = bool(item["has_url"])
        elif "url" in item:
            checked_url = True
            val = item["url"]
            has_url = bool(val) and len(str(val).strip()) > 0

        # Check identifier presence
        checked_id = False
        has_identifier = False
        if "has_identifier" in item:
            checked_id = True
            has_identifier = bool(item["has_identifier"])
        elif "has_id" in item:
            checked_id = True
            has_identifier = bool(item["has_id"])
        elif "identifier" in item:
            checked_id = True
            val = item["identifier"]
            has_identifier = bool(val) and len(str(val).strip()) > 0

        if not checked_url and not checked_id:
            # Baseline sameAs coverage
            item_score = 100.0 if has_same_as else 0.0
        else:
            # Multi-attribute depth: sameAs (50%), url (25%), identifier (25%)
            weight_same_as = 0.50
            weight_url = 0.25 if checked_url else 0.0
            weight_id = 0.25 if checked_id else 0.0
            total_weight = weight_same_as + weight_url + weight_id

            achieved = 0.0
            if has_same_as:
                achieved += weight_same_as
            if has_url:
                achieved += weight_url
            if has_identifier:
                achieved += weight_id

            item_score = (achieved / total_weight) * 100.0 if total_weight > 0 else 0.0

        item_scores.append(item_score)

    if not item_scores:
        return 0.0

    avg_score = sum(item_scores) / len(item_scores)
    return round(float(avg_score), 2)


def calculate_publisher_score(publisher_result: dict) -> float:
    """Score 0-100 based on publisher metadata consistency.

    Verifies that all publisher references across the crawled pages resolve
    to uniform metadata (name, url, logo) without conflicting variations.

    Args:
        publisher_result: Audit result dictionary containing publisher consistency metrics.

    Returns:
        float: Score from 0.0 to 100.0 representing publisher metadata uniformity.
    """
    if not isinstance(publisher_result, dict) or not publisher_result:
        return 100.0

    # 1. Direct precomputed score
    for key in ("score", "uniformity_score", "consistency_score"):
        if key in publisher_result:
            try:
                val = float(publisher_result[key])
                return round(max(0.0, min(100.0, val)), 2)
            except (TypeError, ValueError):
                pass

    # 2. Ratio of consistent references vs total
    total_key = None
    for k in ("total_refs", "total_references", "total_publishers", "total", "count"):
        if k in publisher_result:
            total_key = k
            break

    if total_key:
        try:
            total = int(publisher_result[total_key])
            if total > 0:
                inconsistent_val = None
                for ik in (
                    "inconsistent_refs",
                    "inconsistent_references",
                    "drift_count",
                    "conflicts_count",
                    "mismatches",
                ):
                    if ik in publisher_result:
                        inconsistent_val = int(publisher_result[ik])
                        break
                if inconsistent_val is not None:
                    inconsistent = max(0, min(total, inconsistent_val))
                    return round(((total - inconsistent) / total) * 100.0, 2)

                if "consistent_refs" in publisher_result or "consistent_references" in publisher_result:
                    ck = "consistent_refs" if "consistent_refs" in publisher_result else "consistent_references"
                    consistent = max(0, min(total, int(publisher_result[ck])))
                    return round((consistent / total) * 100.0, 2)
        except (TypeError, ValueError):
            pass

    # 3. Field-level uniformity dictionary
    fields = publisher_result.get("fields") or publisher_result.get("field_consistency")
    if isinstance(fields, dict) and fields:
        consistent_count = sum(1 for v in fields.values() if bool(v))
        return round((consistent_count / len(fields)) * 100.0, 2)

    field_keys = [k for k in publisher_result if k.endswith("_consistent")]
    if field_keys:
        consistent_count = sum(1 for k in field_keys if bool(publisher_result[k]))
        return round((consistent_count / len(field_keys)) * 100.0, 2)

    # 4. Drift and conflict flags
    if "has_drift" in publisher_result:
        return 0.0 if bool(publisher_result["has_drift"]) else 100.0
    if "drift_detected" in publisher_result:
        return 0.0 if bool(publisher_result["drift_detected"]) else 100.0
    if "has_conflicts" in publisher_result:
        return 0.0 if bool(publisher_result["has_conflicts"]) else 100.0
    if "is_consistent" in publisher_result:
        return 100.0 if bool(publisher_result["is_consistent"]) else 0.0
    if "consistent" in publisher_result:
        return 100.0 if bool(publisher_result["consistent"]) else 0.0

    # 5. Status strings
    if "status" in publisher_result:
        status_str = str(publisher_result["status"]).strip().upper()
        if status_str in ("PASS", "CONSISTENT", "VALID", "OK", "SUCCESS"):
            return 100.0
        elif status_str in ("FAIL", "DRIFT", "INCONSISTENT", "ERROR"):
            return 0.0

    # 6. Conflict list inspection
    for lk in ("conflicts", "issues", "drift_items"):
        if lk in publisher_result and isinstance(publisher_result[lk], list):
            return 100.0 if len(publisher_result[lk]) == 0 else 0.0

    return 100.0


def calculate_author_score(author_result: dict) -> float:
    """Score 0-100 based on author metadata consistency.

    Verifies that all author references resolve to consistent metadata
    (name, @id, sameAs profiles) without conflicting variations across pages.

    Args:
        author_result: Audit result dictionary containing author consistency metrics.

    Returns:
        float: Score from 0.0 to 100.0 representing author metadata uniformity.
    """
    if not isinstance(author_result, dict) or not author_result:
        return 100.0

    # 1. Direct precomputed score
    for key in ("score", "uniformity_score", "consistency_score"):
        if key in author_result:
            try:
                val = float(author_result[key])
                return round(max(0.0, min(100.0, val)), 2)
            except (TypeError, ValueError):
                pass

    # 2. Ratio of consistent author references vs total
    total_key = None
    for k in ("total_refs", "total_references", "total_authors", "total", "count"):
        if k in author_result:
            total_key = k
            break

    if total_key:
        try:
            total = int(author_result[total_key])
            if total > 0:
                inconsistent_val = None
                for ik in (
                    "inconsistent_refs",
                    "inconsistent_references",
                    "inconsistent_authors",
                    "drift_count",
                    "conflicts_count",
                    "mismatches",
                ):
                    if ik in author_result:
                        inconsistent_val = int(author_result[ik])
                        break
                if inconsistent_val is not None:
                    inconsistent = max(0, min(total, inconsistent_val))
                    return round(((total - inconsistent) / total) * 100.0, 2)

                if (
                    "consistent_refs" in author_result
                    or "consistent_authors" in author_result
                    or "consistent_references" in author_result
                ):
                    ck = (
                        "consistent_refs"
                        if "consistent_refs" in author_result
                        else ("consistent_authors" if "consistent_authors" in author_result else "consistent_references")
                    )
                    consistent = max(0, min(total, int(author_result[ck])))
                    return round((consistent / total) * 100.0, 2)
        except (TypeError, ValueError):
            pass

    # 3. Field-level uniformity dictionary
    fields = author_result.get("fields") or author_result.get("field_consistency")
    if isinstance(fields, dict) and fields:
        consistent_count = sum(1 for v in fields.values() if bool(v))
        return round((consistent_count / len(fields)) * 100.0, 2)

    field_keys = [k for k in author_result if k.endswith("_consistent")]
    if field_keys:
        consistent_count = sum(1 for k in field_keys if bool(author_result[k]))
        return round((consistent_count / len(field_keys)) * 100.0, 2)

    # 4. Drift and conflict flags
    if "has_drift" in author_result:
        return 0.0 if bool(author_result["has_drift"]) else 100.0
    if "has_inconsistency" in author_result:
        return 0.0 if bool(author_result["has_inconsistency"]) else 100.0
    if "drift_detected" in author_result:
        return 0.0 if bool(author_result["drift_detected"]) else 100.0
    if "has_conflicts" in author_result:
        return 0.0 if bool(author_result["has_conflicts"]) else 100.0
    if "is_consistent" in author_result:
        return 100.0 if bool(author_result["is_consistent"]) else 0.0
    if "consistent" in author_result:
        return 100.0 if bool(author_result["consistent"]) else 0.0

    # 5. Status strings
    if "status" in author_result:
        status_str = str(author_result["status"]).strip().upper()
        if status_str in ("PASS", "CONSISTENT", "VALID", "OK", "SUCCESS"):
            return 100.0
        elif status_str in ("FAIL", "INCONSISTENT", "DRIFT", "ERROR"):
            return 0.0

    # 6. Conflict list inspection
    for lk in ("conflicts", "issues", "conflicting_authors", "drift_items"):
        if lk in author_result and isinstance(author_result[lk], list):
            return 100.0 if len(author_result[lk]) == 0 else 0.0

    return 100.0


def determine_grade(score: float) -> str:
    """Determine letter grade based on composite score thresholds.

    Grade Scale:
    - A: >= 90.0
    - B: >= 75.0
    - C: >= 60.0
    - D: >= 40.0
    - F: < 40.0

    Args:
        score: Graph Integrity Score (0.0 to 100.0).

    Returns:
        str: Letter grade ('A', 'B', 'C', 'D', or 'F').
    """
    if score >= 90.0:
        return "A"
    elif score >= 75.0:
        return "B"
    elif score >= 60.0:
        return "C"
    elif score >= 40.0:
        return "D"
    else:
        return "F"


def calculate_composite_score(
    ref_score: float,
    connectivity_score: float,
    disambiguation_score: float,
    publisher_score: float,
    author_score: float,
) -> dict:
    """Calculate weighted composite score and return full breakdown.

    Weights:
    - Reference Integrity: 35%
    - Entity Connectivity: 25%
    - Disambiguation Depth: 20%
    - Publisher Consistency: 10%
    - Author Consistency: 10%

    Args:
        ref_score: Score for reference integrity (0-100).
        connectivity_score: Score for entity connectivity (0-100).
        disambiguation_score: Score for disambiguation depth (0-100).
        publisher_score: Score for publisher consistency (0-100).
        author_score: Score for author consistency (0-100).

    Returns:
        dict: Breakdown containing overall_score, component_scores, and grade.
    """
    try:
        r_score = max(0.0, min(100.0, float(ref_score)))
    except (TypeError, ValueError):
        r_score = 0.0

    try:
        c_score = max(0.0, min(100.0, float(connectivity_score)))
    except (TypeError, ValueError):
        c_score = 0.0

    try:
        d_score = max(0.0, min(100.0, float(disambiguation_score)))
    except (TypeError, ValueError):
        d_score = 0.0

    try:
        p_score = max(0.0, min(100.0, float(publisher_score)))
    except (TypeError, ValueError):
        p_score = 0.0

    try:
        a_score = max(0.0, min(100.0, float(author_score)))
    except (TypeError, ValueError):
        a_score = 0.0

    weighted_total = (
        (r_score * WEIGHT_REFERENCE_INTEGRITY)
        + (c_score * WEIGHT_ENTITY_CONNECTIVITY)
        + (d_score * WEIGHT_DISAMBIGUATION_DEPTH)
        + (p_score * WEIGHT_PUBLISHER_CONSISTENCY)
        + (a_score * WEIGHT_AUTHOR_CONSISTENCY)
    )

    overall_score = round(max(0.0, min(100.0, weighted_total)), 2)
    grade = determine_grade(overall_score)

    component_scores = ComponentScores({
        "reference_integrity": round(r_score, 2),
        "entity_connectivity": round(c_score, 2),
        "disambiguation_depth": round(d_score, 2),
        "publisher_consistency": round(p_score, 2),
        "author_consistency": round(a_score, 2),
    })

    verdicts: dict[str, str] = {
        "A": "Excellent Knowledge Graph Integrity",
        "B": "Good Knowledge Graph Integrity with Minor Remediation Needed",
        "C": "Acceptable Graph with Structural Disconnects",
        "D": "Poor Graph Integrity with Critical Broken Nodes",
        "F": "Failing Entity Graph: High Knowledge Graph Fragmentation",
    }

    return {
        "overall_score": overall_score,
        "component_scores": component_scores,
        "grade": grade,
        "weights": {
            "reference_integrity": WEIGHT_REFERENCE_INTEGRITY,
            "entity_connectivity": WEIGHT_ENTITY_CONNECTIVITY,
            "disambiguation_depth": WEIGHT_DISAMBIGUATION_DEPTH,
            "publisher_consistency": WEIGHT_PUBLISHER_CONSISTENCY,
            "author_consistency": WEIGHT_AUTHOR_CONSISTENCY,
        },
        "verdict": verdicts.get(grade, "Unknown"),
        "passed": overall_score >= 60.0,
    }


def score_graph(
    total_refs: int = 0,
    broken_refs: int = 0,
    total_nodes: int = 0,
    orphan_nodes: int = 0,
    disambiguation_results: Optional[list[dict]] = None,
    publisher_result: Optional[dict] = None,
    author_result: Optional[dict] = None,
) -> dict:
    """Convenience helper to compute all sub-scores and composite score in a single call.

    Args:
        total_refs: Total @id references discovered.
        broken_refs: Broken @id references discovered.
        total_nodes: Total entity nodes discovered.
        orphan_nodes: Orphan entity nodes discovered.
        disambiguation_results: Disambiguation audit records for key entities.
        publisher_result: Publisher consistency audit record.
        author_result: Author consistency audit record.

    Returns:
        dict: Full score breakdown including overall_score, component_scores, and grade.
    """
    ref_score = calculate_reference_integrity_score(total_refs, broken_refs)
    connectivity_score = calculate_connectivity_score(total_nodes, orphan_nodes)
    disambiguation_score = calculate_disambiguation_score(disambiguation_results or [])
    publisher_score = calculate_publisher_score(publisher_result or {})
    author_score = calculate_author_score(author_result or {})

    return calculate_composite_score(
        ref_score=ref_score,
        connectivity_score=connectivity_score,
        disambiguation_score=disambiguation_score,
        publisher_score=publisher_score,
        author_score=author_score,
    )


def render_score_report(score_breakdown: dict) -> None:
    """Render score breakdown table using rich if available, plain text otherwise.

    Args:
        score_breakdown: Dictionary returned by calculate_composite_score or score_graph.
    """
    overall = score_breakdown.get("overall_score", 0.0)
    grade = score_breakdown.get("grade", "F")
    verdict = score_breakdown.get("verdict", "")
    comp = score_breakdown.get("component_scores", {})
    weights = score_breakdown.get("weights", {
        "reference_integrity": WEIGHT_REFERENCE_INTEGRITY,
        "entity_connectivity": WEIGHT_ENTITY_CONNECTIVITY,
        "disambiguation_depth": WEIGHT_DISAMBIGUATION_DEPTH,
        "publisher_consistency": WEIGHT_PUBLISHER_CONSISTENCY,
        "author_consistency": WEIGHT_AUTHOR_CONSISTENCY,
    })

    rows = [
        ("Reference Integrity", weights.get("reference_integrity", 0.35), comp.get("reference_integrity", 0.0)),
        ("Entity Connectivity", weights.get("entity_connectivity", 0.25), comp.get("entity_connectivity", 0.0)),
        ("Disambiguation Depth", weights.get("disambiguation_depth", 0.20), comp.get("disambiguation_depth", 0.0)),
        ("Publisher Consistency", weights.get("publisher_consistency", 0.10), comp.get("publisher_consistency", 0.0)),
        ("Author Consistency", weights.get("author_consistency", 0.10), comp.get("author_consistency", 0.0)),
    ]

    if HAS_RICH:
        console = Console()
        grade_colors = {
            "A": "green",
            "B": "cyan",
            "C": "yellow",
            "D": "magenta",
            "F": "red",
        }
        color = grade_colors.get(grade, "white")

        table = Table(title="SchemaGraph: Graph Integrity Breakdown", show_header=True, header_style="bold blue")
        table.add_column("Component", style="cyan", width=26)
        table.add_column("Weight", justify="right", width=10)
        table.add_column("Raw Score", justify="right", width=12)
        table.add_column("Weighted", justify="right", width=12)

        for name, weight, raw in rows:
            weighted = raw * weight
            table.add_row(
                name,
                f"{int(weight * 100)}%",
                f"{raw:.1f}/100",
                f"{weighted:.1f}",
            )

        console.print(table)
        summary_text = (
            f"Overall Score: [bold {color}]{overall:.1f}/100[/bold {color}] | "
            f"Grade: [bold {color}]{grade}[/bold {color}] | "
            f"Verdict: {verdict}"
        )
        console.print(Panel(summary_text, title="Integrity Verdict", border_style=color))
    else:
        print("=" * 66)
        print("SchemaGraph: Graph Integrity Breakdown")
        print("=" * 66)
        print(f"{'Component':<26} {'Weight':>8} {'Raw Score':>12} {'Weighted':>12}")
        print("-" * 66)
        for name, weight, raw in rows:
            weighted = raw * weight
            print(f"{name:<26} {int(weight * 100):>7}% {raw:>11.1f} {weighted:>12.1f}")
        print("-" * 66)
        print(f"Overall Score: {overall:.1f}/100 | Grade: {grade} | Verdict: {verdict}")
        print("=" * 66)
