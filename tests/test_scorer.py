"""
Unit tests for SchemaGraph scorer module.

Author: @xcalibur73
"""

import unittest
from schema_graph.scorer import (
    ComponentScores,
    calculate_reference_integrity_score,
    calculate_connectivity_score,
    calculate_disambiguation_score,
    calculate_publisher_score,
    calculate_author_score,
    calculate_composite_score,
    determine_grade,
    score_graph,
    render_score_report,
)


class TestReferenceIntegrityScorer(unittest.TestCase):
    """Test suite for reference integrity scoring (35% weight)."""

    def test_perfect_reference_integrity(self):
        score = calculate_reference_integrity_score(10, 0)
        self.assertEqual(score, 100.0)

    def test_zero_references_baseline(self):
        score = calculate_reference_integrity_score(0, 0)
        self.assertEqual(score, 100.0)

    def test_partial_broken_references(self):
        score = calculate_reference_integrity_score(10, 2)
        self.assertEqual(score, 80.0)

        score_half = calculate_reference_integrity_score(10, 5)
        self.assertEqual(score_half, 50.0)

    def test_all_broken_references(self):
        score = calculate_reference_integrity_score(10, 10)
        self.assertEqual(score, 0.0)

    def test_broken_exceeds_total_clamped(self):
        score = calculate_reference_integrity_score(5, 12)
        self.assertEqual(score, 0.0)

    def test_negative_broken_treated_as_zero(self):
        score = calculate_reference_integrity_score(10, -3)
        self.assertEqual(score, 100.0)

    def test_string_inputs_parsed(self):
        score = calculate_reference_integrity_score("20", "5")
        self.assertEqual(score, 75.0)

    def test_invalid_types_fallback_to_zero(self):
        score = calculate_reference_integrity_score("invalid", 5)
        self.assertEqual(score, 0.0)


class TestConnectivityScorer(unittest.TestCase):
    """Test suite for graph entity connectivity scoring (25% weight)."""

    def test_perfect_connectivity(self):
        score = calculate_connectivity_score(10, 0)
        self.assertEqual(score, 100.0)

    def test_zero_nodes_baseline(self):
        score = calculate_connectivity_score(0, 0)
        self.assertEqual(score, 100.0)

    def test_partial_orphan_nodes(self):
        score = calculate_connectivity_score(10, 3)
        self.assertEqual(score, 70.0)

        score_quarter = calculate_connectivity_score(4, 1)
        self.assertEqual(score_quarter, 75.0)

    def test_all_orphan_nodes(self):
        score = calculate_connectivity_score(8, 8)
        self.assertEqual(score, 0.0)

    def test_orphans_exceeds_total_clamped(self):
        score = calculate_connectivity_score(4, 10)
        self.assertEqual(score, 0.0)

    def test_negative_orphans_treated_as_zero(self):
        score = calculate_connectivity_score(6, -2)
        self.assertEqual(score, 100.0)

    def test_string_inputs_parsed(self):
        score = calculate_connectivity_score("10", "4")
        self.assertEqual(score, 60.0)

    def test_invalid_types_fallback_to_zero(self):
        score = calculate_connectivity_score(None, 0)
        self.assertEqual(score, 0.0)


class TestDisambiguationScorer(unittest.TestCase):
    """Test suite for disambiguation depth scoring (20% weight)."""

    def test_empty_results_clean_graph(self):
        score = calculate_disambiguation_score([])
        self.assertEqual(score, 100.0)

    def test_all_key_entities_with_sameas(self):
        entities = [
            {"@type": "Organization", "has_same_as": True},
            {"@type": "Person", "has_same_as": True},
            {"@type": "WebSite", "has_same_as": True},
        ]
        score = calculate_disambiguation_score(entities)
        self.assertEqual(score, 100.0)

    def test_all_key_entities_missing_sameas(self):
        entities = [
            {"@type": "Organization", "has_same_as": False},
            {"@type": "Person", "has_same_as": False},
        ]
        score = calculate_disambiguation_score(entities)
        self.assertEqual(score, 0.0)

    def test_mixed_sameas_coverage(self):
        entities = [
            {"@type": "Organization", "has_same_as": True},
            {"@type": "Person", "has_same_as": False},
        ]
        score = calculate_disambiguation_score(entities)
        self.assertEqual(score, 50.0)

    def test_audit_findings_missing_all_status(self):
        findings = [
            {"type": "Organization", "status": "missing_all"},
            {"type": "Person", "status": "missing_all"},
        ]
        score = calculate_disambiguation_score(findings)
        self.assertEqual(score, 0.0)

    def test_audit_findings_missing_kg_authority_partial(self):
        findings = [
            {"type": "Organization", "status": "missing_kg_authority"},
        ]
        score = calculate_disambiguation_score(findings)
        self.assertEqual(score, 50.0)

    def test_multi_attribute_depth_full(self):
        entities = [
            {
                "@type": "Organization",
                "sameAs": ["https://www.wikidata.org/wiki/Q12345"],
                "url": "https://example.com",
                "identifier": "US-ORG-12345",
            },
        ]
        score = calculate_disambiguation_score(entities)
        self.assertEqual(score, 100.0)

    def test_multi_attribute_depth_partial(self):
        # sameAs (50%) + url (25%), missing identifier (0%)
        entities = [
            {
                "@type": "Organization",
                "has_same_as": True,
                "has_url": True,
                "has_identifier": False,
            },
        ]
        score = calculate_disambiguation_score(entities)
        self.assertEqual(score, 75.0)

    def test_precomputed_scores(self):
        entities = [
            {"score": 90.0},
            {"score": 70.0},
        ]
        score = calculate_disambiguation_score(entities)
        self.assertEqual(score, 80.0)

    def test_filters_to_key_entities_when_mixed(self):
        entities = [
            {"@type": "Article", "has_same_as": False},  # Should be ignored (not key entity)
            {"@type": "Organization", "has_same_as": True},  # Key entity: evaluated
        ]
        score = calculate_disambiguation_score(entities)
        self.assertEqual(score, 100.0)


class TestPublisherScorer(unittest.TestCase):
    """Test suite for publisher metadata consistency scoring (10% weight)."""

    def test_empty_result_defaults_to_perfect(self):
        score = calculate_publisher_score({})
        self.assertEqual(score, 100.0)

    def test_boolean_consistency_flag(self):
        self.assertEqual(calculate_publisher_score({"consistent": True}), 100.0)
        self.assertEqual(calculate_publisher_score({"consistent": False}), 0.0)
        self.assertEqual(calculate_publisher_score({"is_consistent": True}), 100.0)
        self.assertEqual(calculate_publisher_score({"is_consistent": False}), 0.0)

    def test_reference_counts_ratio(self):
        res = {"total_refs": 10, "inconsistent_refs": 2}
        self.assertEqual(calculate_publisher_score(res), 80.0)

        res_drift = {"total_references": 5, "drift_count": 1}
        self.assertEqual(calculate_publisher_score(res_drift), 80.0)

    def test_direct_score_override(self):
        self.assertEqual(calculate_publisher_score({"score": 93.4}), 93.4)
        self.assertEqual(calculate_publisher_score({"uniformity_score": 85.0}), 85.0)

    def test_field_level_consistency(self):
        res = {"fields": {"name": True, "url": True, "logo": False}}
        self.assertEqual(calculate_publisher_score(res), 66.67)

    def test_drift_and_conflict_flags(self):
        self.assertEqual(calculate_publisher_score({"has_drift": True}), 0.0)
        self.assertEqual(calculate_publisher_score({"has_drift": False}), 100.0)
        self.assertEqual(calculate_publisher_score({"conflicts": ["mismatch"]}), 0.0)
        self.assertEqual(calculate_publisher_score({"conflicts": []}), 100.0)

    def test_status_string(self):
        self.assertEqual(calculate_publisher_score({"status": "PASS"}), 100.0)
        self.assertEqual(calculate_publisher_score({"status": "FAIL"}), 0.0)


class TestAuthorScorer(unittest.TestCase):
    """Test suite for author metadata consistency scoring (10% weight)."""

    def test_empty_result_defaults_to_perfect(self):
        score = calculate_author_score({})
        self.assertEqual(score, 100.0)

    def test_boolean_consistency_flag(self):
        self.assertEqual(calculate_author_score({"consistent": True}), 100.0)
        self.assertEqual(calculate_author_score({"consistent": False}), 0.0)
        self.assertEqual(calculate_author_score({"is_consistent": True}), 100.0)
        self.assertEqual(calculate_author_score({"is_consistent": False}), 0.0)

    def test_reference_counts_ratio(self):
        res = {"total_refs": 10, "inconsistent_refs": 1}
        self.assertEqual(calculate_author_score(res), 90.0)

        res_authors = {"total_authors": 4, "conflicts_count": 1}
        self.assertEqual(calculate_author_score(res_authors), 75.0)

    def test_direct_score_override(self):
        self.assertEqual(calculate_author_score({"score": 88.0}), 88.0)
        self.assertEqual(calculate_author_score({"consistency_score": 95.5}), 95.5)

    def test_field_level_consistency(self):
        res = {"fields": {"name": True, "same_as": True}}
        self.assertEqual(calculate_author_score(res), 100.0)

    def test_drift_and_conflict_flags(self):
        self.assertEqual(calculate_author_score({"has_drift": True}), 0.0)
        self.assertEqual(calculate_author_score({"has_inconsistency": True}), 0.0)
        self.assertEqual(calculate_author_score({"has_conflicts": False}), 100.0)

    def test_status_string(self):
        self.assertEqual(calculate_author_score({"status": "PASS"}), 100.0)
        self.assertEqual(calculate_author_score({"status": "FAIL"}), 0.0)


class TestCompositeScorer(unittest.TestCase):
    """Test suite for composite scoring, weight calibration, and grade thresholds."""

    def test_perfect_score_yields_grade_a(self):
        res = calculate_composite_score(100, 100, 100, 100, 100)
        self.assertEqual(res["overall_score"], 100.0)
        self.assertEqual(res["grade"], "A")
        self.assertTrue(res["passed"])

    def test_zero_score_yields_grade_f(self):
        res = calculate_composite_score(0, 0, 0, 0, 0)
        self.assertEqual(res["overall_score"], 0.0)
        self.assertEqual(res["grade"], "F")
        self.assertFalse(res["passed"])

    def test_grade_thresholds(self):
        self.assertEqual(determine_grade(100.0), "A")
        self.assertEqual(determine_grade(90.0), "A")
        self.assertEqual(determine_grade(89.9), "B")
        self.assertEqual(determine_grade(75.0), "B")
        self.assertEqual(determine_grade(74.9), "C")
        self.assertEqual(determine_grade(60.0), "C")
        self.assertEqual(determine_grade(59.9), "D")
        self.assertEqual(determine_grade(40.0), "D")
        self.assertEqual(determine_grade(39.9), "F")
        self.assertEqual(determine_grade(0.0), "F")

    def test_individual_weight_contributions(self):
        # Reference Integrity (35%)
        res_ref = calculate_composite_score(100, 0, 0, 0, 0)
        self.assertEqual(res_ref["overall_score"], 35.0)

        # Entity Connectivity (25%)
        res_conn = calculate_composite_score(0, 100, 0, 0, 0)
        self.assertEqual(res_conn["overall_score"], 25.0)

        # Disambiguation Depth (20%)
        res_dis = calculate_composite_score(0, 0, 100, 0, 0)
        self.assertEqual(res_dis["overall_score"], 20.0)

        # Publisher Consistency (10%)
        res_pub = calculate_composite_score(0, 0, 0, 100, 0)
        self.assertEqual(res_pub["overall_score"], 10.0)

        # Author Consistency (10%)
        res_auth = calculate_composite_score(0, 0, 0, 0, 100)
        self.assertEqual(res_auth["overall_score"], 10.0)

    def test_component_scores_alias_lookup(self):
        res = calculate_composite_score(90, 80, 70, 100, 95)
        comp = res["component_scores"]

        # Standard keys
        self.assertEqual(comp["reference_integrity"], 90.0)
        self.assertEqual(comp["entity_connectivity"], 80.0)
        self.assertEqual(comp["disambiguation_depth"], 70.0)
        self.assertEqual(comp["publisher_consistency"], 100.0)
        self.assertEqual(comp["author_consistency"], 95.0)

        # Convenient alias keys
        self.assertEqual(comp["ref_score"], 90.0)
        self.assertEqual(comp["connectivity_score"], 80.0)
        self.assertEqual(comp["disambiguation_score"], 70.0)
        self.assertEqual(comp["publisher_score"], 100.0)
        self.assertEqual(comp["author_score"], 95.0)
        self.assertIn("ref_score", comp)

    def test_score_graph_convenience_helper(self):
        res = score_graph(
            total_refs=10,
            broken_refs=0,
            total_nodes=5,
            orphan_nodes=0,
            disambiguation_results=[],
            publisher_result={"consistent": True},
            author_result={"consistent": True},
        )
        self.assertEqual(res["overall_score"], 100.0)
        self.assertEqual(res["grade"], "A")

    def test_render_score_report_runs_without_error(self):
        res = calculate_composite_score(85, 90, 75, 100, 100)
        # Should execute successfully without throwing exceptions
        render_score_report(res)


if __name__ == "__main__":
    unittest.main()
