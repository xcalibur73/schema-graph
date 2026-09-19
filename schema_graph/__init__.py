"""
SchemaGraph package initialization.

Author: @xcalibur73
"""

from schema_graph.scorer import (
    ComponentScores,
    calculate_author_score,
    calculate_composite_score,
    calculate_connectivity_score,
    calculate_disambiguation_score,
    calculate_publisher_score,
    calculate_reference_integrity_score,
    determine_grade,
    render_score_report,
    score_graph,
)

__version__ = "1.2.0"

__all__ = [
    "ComponentScores",
    "calculate_author_score",
    "calculate_composite_score",
    "calculate_connectivity_score",
    "calculate_disambiguation_score",
    "calculate_publisher_score",
    "calculate_reference_integrity_score",
    "determine_grade",
    "render_score_report",
    "score_graph",
]
