"""
Unit tests for SchemaGraph entity graph integrity modules.
"""

import unittest
import json
from schema_graph.extractor import extract_jsonld_blocks, flatten_entities, normalize_id
from schema_graph.graph_builder import (
    build_entity_graph,
    find_broken_references,
    find_orphan_nodes,
    find_circular_references,
    check_publisher_consistency,
    check_author_consistency,
    audit_disambiguation,
)
from schema_graph.scorer import (
    calculate_reference_integrity_score,
    calculate_connectivity_score,
    calculate_disambiguation_score,
    calculate_composite_score,
)


class TestExtractor(unittest.TestCase):

    def test_extract_single_entity(self):
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@context": "https://schema.org", "@type": "Organization", "@id": "https://example.com/#org", "name": "Acme Corp"}
        </script>
        </head><body></body></html>
        """
        blocks = extract_jsonld_blocks(html)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["@type"], "Organization")

    def test_extract_graph_array(self):
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@context": "https://schema.org", "@graph": [
            {"@type": "Organization", "@id": "https://example.com/#org", "name": "Acme"},
            {"@type": "Person", "@id": "https://example.com/#author", "name": "Jane"}
        ]}
        </script>
        </head><body></body></html>
        """
        blocks = extract_jsonld_blocks(html)
        self.assertEqual(len(blocks), 1)
        entities = flatten_entities(blocks, "https://example.com")
        self.assertEqual(len(entities), 2)

    def test_normalize_id_trailing_slash(self):
        self.assertEqual(
            normalize_id("https://example.com/"),
            "https://example.com"
        )

    def test_normalize_id_http_to_https(self):
        self.assertEqual(
            normalize_id("http://example.com/#org"),
            "https://example.com/#org"
        )

    def test_flatten_synthetic_id(self):
        blocks = [{"@context": "https://schema.org", "@type": "Article", "name": "Test Post"}]
        entities = flatten_entities(blocks, "https://example.com/blog/post-1")
        self.assertEqual(len(entities), 1)
        self.assertIn("@id", entities[0])
        self.assertIn("Article", entities[0]["@id"])


class TestGraphBuilder(unittest.TestCase):

    def _build_sample_graph(self):
        entities = [
            {
                "@type": "Organization",
                "@id": "https://example.com/#org",
                "name": "Acme Corp",
                "sameAs": ["https://www.wikidata.org/wiki/Q12345"],
                "_source_url": "https://example.com",
            },
            {
                "@type": "Person",
                "@id": "https://example.com/#author",
                "name": "Jane Doe",
                "worksFor": {"@id": "https://example.com/#org"},
                "_source_url": "https://example.com/about",
            },
            {
                "@type": "Article",
                "@id": "https://example.com/blog/post-1",
                "name": "Test Article",
                "author": {"@id": "https://example.com/#author"},
                "publisher": {"@id": "https://example.com/#org"},
                "_source_url": "https://example.com/blog/post-1",
            },
        ]
        return entities

    def test_build_graph_nodes_and_edges(self):
        entities = self._build_sample_graph()
        nodes, edges = build_entity_graph(entities)
        self.assertEqual(len(nodes), 3)
        self.assertGreaterEqual(len(edges), 2)

    def test_no_broken_references_in_complete_graph(self):
        entities = self._build_sample_graph()
        nodes, edges = build_entity_graph(entities)
        broken = find_broken_references(nodes, edges)
        self.assertEqual(len(broken), 0)

    def test_detect_broken_reference(self):
        entities = [
            {
                "@type": "Article",
                "@id": "https://example.com/blog/post-1",
                "name": "Test",
                "author": {"@id": "https://example.com/#ghost-author"},
                "_source_url": "https://example.com/blog/post-1",
            },
        ]
        nodes, edges = build_entity_graph(entities)
        broken = find_broken_references(nodes, edges)
        self.assertEqual(len(broken), 1)
        self.assertEqual(broken[0]["target_id"], "https://example.com/#ghost-author")

    def test_detect_orphan_node(self):
        entities = [
            {
                "@type": "Organization",
                "@id": "https://example.com/#org",
                "name": "Orphan Org",
                "_source_url": "https://example.com",
            },
            {
                "@type": "Article",
                "@id": "https://example.com/blog/post-1",
                "name": "Test",
                "_source_url": "https://example.com/blog/post-1",
            },
        ]
        nodes, edges = build_entity_graph(entities)
        orphans = find_orphan_nodes(nodes, edges)
        # Both nodes are orphans since neither references the other
        self.assertGreaterEqual(len(orphans), 1)

    def test_detect_circular_reference(self):
        entities = [
            {
                "@type": "Person",
                "@id": "https://example.com/#alice",
                "name": "Alice",
                "worksFor": {"@id": "https://example.com/#org"},
                "_source_url": "https://example.com",
            },
            {
                "@type": "Organization",
                "@id": "https://example.com/#org",
                "name": "Acme",
                "founder": {"@id": "https://example.com/#alice"},
                "_source_url": "https://example.com",
            },
        ]
        nodes, edges = build_entity_graph(entities)
        cycles = find_circular_references(nodes, edges)
        self.assertGreaterEqual(len(cycles), 1)

    def test_publisher_consistency_pass(self):
        entities = [
            {"@type": "Article", "publisher": {"@type": "Organization", "name": "Acme Corp", "url": "https://acme.com"}, "_source_url": "https://acme.com/post-1"},
            {"@type": "Article", "publisher": {"@type": "Organization", "name": "Acme Corp", "url": "https://acme.com"}, "_source_url": "https://acme.com/post-2"},
        ]
        result = check_publisher_consistency(entities)
        self.assertTrue(result["consistent"])

    def test_publisher_consistency_drift(self):
        entities = [
            {"@type": "Article", "publisher": {"@type": "Organization", "name": "Acme Corp"}, "_source_url": "https://acme.com/post-1"},
            {"@type": "Article", "publisher": {"@type": "Organization", "name": "ACME Corporation"}, "_source_url": "https://acme.com/post-2"},
        ]
        result = check_publisher_consistency(entities)
        self.assertFalse(result["consistent"])
        self.assertGreaterEqual(len(result["inconsistencies"]), 1)

    def test_disambiguation_flags_missing_sameas(self):
        entities = [
            {
                "@type": "Organization",
                "@id": "https://example.com/#org",
                "name": "Acme",
                "_source_url": "https://example.com",
            },
        ]
        nodes, _ = build_entity_graph(entities)
        results = audit_disambiguation(nodes)
        org_result = [r for r in results if r["type"] == "Organization"]
        self.assertGreaterEqual(len(org_result), 1)
        self.assertFalse(org_result[0]["has_same_as"])


class TestScorer(unittest.TestCase):

    def test_perfect_reference_integrity(self):
        score = calculate_reference_integrity_score(10, 0)
        self.assertEqual(score, 100.0)

    def test_zero_references(self):
        score = calculate_reference_integrity_score(0, 0)
        self.assertEqual(score, 100.0)

    def test_half_broken_references(self):
        score = calculate_reference_integrity_score(10, 5)
        self.assertEqual(score, 50.0)

    def test_full_connectivity(self):
        score = calculate_connectivity_score(10, 0)
        self.assertEqual(score, 100.0)

    def test_composite_grade_a(self):
        result = calculate_composite_score(100, 100, 100, 100, 100)
        self.assertEqual(result["grade"], "A")
        self.assertEqual(result["overall_score"], 100.0)

    def test_composite_grade_f(self):
        result = calculate_composite_score(0, 0, 0, 0, 0)
        self.assertEqual(result["grade"], "F")


if __name__ == "__main__":
    unittest.main()
