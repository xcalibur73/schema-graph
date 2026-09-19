"""
Unit tests for SchemaGraph graph_builder module.

Author: @xcalibur73
"""

import unittest
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from schema_graph.graph_builder import (
    EntityNode,
    GraphEdge,
    build_entity_graph,
    find_broken_references,
    find_orphan_nodes,
    find_circular_references,
    check_publisher_consistency,
    check_author_consistency,
    audit_disambiguation,
    normalize_uri,
)


class TestGraphBuilder(unittest.TestCase):
    """Test suite for graph construction and integrity analysis."""

    def test_normalize_uri(self):
        """Test URI normalization and resolution."""
        self.assertEqual(normalize_uri("https://example.com/path/"), "https://example.com/path")
        self.assertEqual(normalize_uri("#author", base_url="https://example.com/post"), "https://example.com/post#author")
        self.assertEqual(normalize_uri("https://example.com/page#frag"), "https://example.com/page#frag")
        self.assertEqual(normalize_uri(""), "")

    def test_build_entity_graph_basic(self):
        """Test building nodes and edges from flattened JSON-LD entities."""
        entities = [
            {
                "@context": "https://schema.org",
                "@type": "Article",
                "@id": "https://example.com/post-1#article",
                "headline": "Post 1 Headline",
                "author": {"@id": "https://example.com/#author"},
                "publisher": {"@id": "https://example.com/#org"},
                "isPartOf": {"@id": "https://example.com/#website"},
                "_source_url": "https://example.com/post-1",
            },
            {
                "@type": "Person",
                "@id": "https://example.com/#author",
                "name": "Jane Doe",
                "sameAs": ["https://www.wikidata.org/wiki/Q12345"],
                "_source_url": "https://example.com/author",
            },
            {
                "@type": "Organization",
                "@id": "https://example.com/#org",
                "name": "Acme Media",
                "url": "https://example.com",
                "sameAs": "https://en.wikipedia.org/wiki/Acme_Media",
                "_source_url": "https://example.com",
            },
            {
                "@type": "WebSite",
                "@id": "https://example.com/#website",
                "name": "Acme Website",
                "_source_url": "https://example.com",
            },
        ]

        nodes, edges = build_entity_graph(entities)

        # Check nodes count and attributes
        self.assertEqual(len(nodes), 4)
        self.assertIn("https://example.com/post-1#article", nodes)
        self.assertIn("https://example.com/#author", nodes)
        self.assertIn("https://example.com/#org", nodes)
        self.assertIn("https://example.com/#website", nodes)

        author_node = nodes["https://example.com/#author"]
        self.assertEqual(author_node.name, "Jane Doe")
        self.assertEqual(author_node.type, "Person")
        self.assertEqual(author_node.same_as, ["https://www.wikidata.org/wiki/Q12345"])

        # Check edges
        edge_targets = {(e.source_id, e.target_id, e.property_name) for e in edges}
        self.assertIn(
            ("https://example.com/post-1#article", "https://example.com/#author", "author"),
            edge_targets,
        )
        self.assertIn(
            ("https://example.com/post-1#article", "https://example.com/#org", "publisher"),
            edge_targets,
        )
        self.assertIn(
            ("https://example.com/post-1#article", "https://example.com/#website", "isPartOf"),
            edge_targets,
        )

    def test_build_entity_graph_synthetic_ids(self):
        """Test that entities without @id receive unique synthetic identifiers."""
        entities = [
            {
                "@type": "Article",
                "headline": "No ID Article",
                "_source_url": "https://example.com/page-1",
            },
            {
                "@type": "Article",
                "headline": "Second No ID Article",
                "_source_url": "https://example.com/page-2",
            },
        ]
        nodes, edges = build_entity_graph(entities)
        self.assertEqual(len(nodes), 2)
        node_ids = list(nodes.keys())
        self.assertTrue(node_ids[0].startswith("https://example.com/page-1#Article#"))
        self.assertTrue(node_ids[1].startswith("https://example.com/page-2#Article#"))
        self.assertNotEqual(node_ids[0], node_ids[1])

    def test_find_broken_references(self):
        """Test broken reference detection for non-existent @id targets."""
        nodes = {
            "https://example.com/#article": EntityNode(
                id="https://example.com/#article",
                type="Article",
                name="Article",
                source_url="https://example.com/post",
            )
        }
        edges = [
            GraphEdge(
                source_id="https://example.com/#article",
                target_id="https://example.com/#missing-author",
                property_name="author",
                source_url="https://example.com/post",
            )
        ]

        broken = find_broken_references(nodes, edges)
        self.assertEqual(len(broken), 1)
        self.assertEqual(broken[0]["source_id"], "https://example.com/#article")
        self.assertEqual(broken[0]["target_id"], "https://example.com/#missing-author")
        self.assertEqual(broken[0]["property_name"], "author")
        self.assertEqual(broken[0]["severity"], "Critical")

    def test_find_orphan_nodes(self):
        """Test orphan node detection when entities have zero incoming edges."""
        nodes = {
            "https://example.com/#article": EntityNode(
                id="https://example.com/#article",
                type="Article",
                name="Article",
                source_url="https://example.com/post",
            ),
            "https://example.com/#orphan-org": EntityNode(
                id="https://example.com/#orphan-org",
                type="Organization",
                name="Isolated Org",
                source_url="https://example.com/about",
            ),
            "https://example.com/#author": EntityNode(
                id="https://example.com/#author",
                type="Person",
                name="Author Person",
                source_url="https://example.com/author",
            ),
        }
        edges = [
            GraphEdge(
                source_id="https://example.com/#article",
                target_id="https://example.com/#author",
                property_name="author",
                source_url="https://example.com/post",
            )
        ]

        orphans = find_orphan_nodes(nodes, edges)
        orphan_ids = {o["node_id"] for o in orphans}

        # #article is not referenced as a target (it is a root source)
        self.assertIn("https://example.com/#article", orphan_ids)
        # #orphan-org is unreferenced as target
        self.assertIn("https://example.com/#orphan-org", orphan_ids)
        # #author IS referenced as a target, so must NOT be in orphans
        self.assertNotIn("https://example.com/#author", orphan_ids)

    def test_find_circular_references(self):
        """Test DFS cycle detection for circular @id chains."""
        nodes = {
            "A": EntityNode(id="A", type="Article", name="A", source_url=""),
            "B": EntityNode(id="B", type="Person", name="B", source_url=""),
            "C": EntityNode(id="C", type="Organization", name="C", source_url=""),
            "D": EntityNode(id="D", type="WebSite", name="D", source_url=""),
        }
        # Cycle: A -> B -> C -> A
        edges = [
            GraphEdge(source_id="A", target_id="B", property_name="author", source_url=""),
            GraphEdge(source_id="B", target_id="C", property_name="worksFor", source_url=""),
            GraphEdge(source_id="C", target_id="A", property_name="publishingEntity", source_url=""),
            GraphEdge(source_id="C", target_id="D", property_name="isPartOf", source_url=""),
        ]

        cycles = find_circular_references(nodes, edges)
        self.assertEqual(len(cycles), 1)
        self.assertEqual(cycles[0], ["A", "B", "C", "A"])

    def test_find_circular_references_acyclic(self):
        """Test DFS cycle detection returns empty list for DAG."""
        nodes = {
            "A": EntityNode(id="A", type="Article", name="A", source_url=""),
            "B": EntityNode(id="B", type="Person", name="B", source_url=""),
            "C": EntityNode(id="C", type="Organization", name="C", source_url=""),
        }
        edges = [
            GraphEdge(source_id="A", target_id="B", property_name="author", source_url=""),
            GraphEdge(source_id="B", target_id="C", property_name="worksFor", source_url=""),
        ]
        cycles = find_circular_references(nodes, edges)
        self.assertEqual(cycles, [])

    def test_publisher_consistency_aligned(self):
        """Test publisher consistency when all pages share uniform metadata."""
        entities = [
            {
                "@type": "Article",
                "_source_url": "https://example.com/post-1",
                "publisher": {
                    "@id": "https://example.com/#org",
                    "name": "Acme Media",
                    "url": "https://example.com",
                    "logo": "https://example.com/logo.png",
                },
            },
            {
                "@type": "Article",
                "_source_url": "https://example.com/post-2",
                "publisher": {
                    "@id": "https://example.com/#org",
                    "name": "Acme Media",
                    "url": "https://example.com",
                    "logo": "https://example.com/logo.png",
                },
            },
        ]
        res = check_publisher_consistency(entities)
        self.assertTrue(res["is_consistent"])
        self.assertEqual(len(res["inconsistencies"]), 0)

    def test_publisher_consistency_drift(self):
        """Test publisher consistency detects name, url, and logo drift across pages."""
        entities = [
            {
                "@type": "Article",
                "_source_url": "https://example.com/post-1",
                "publisher": {
                    "@id": "https://example.com/#org",
                    "name": "Acme Media Inc",
                    "url": "https://example.com",
                    "logo": "https://example.com/logo-old.png",
                },
            },
            {
                "@type": "Article",
                "_source_url": "https://example.com/post-2",
                "publisher": {
                    "@id": "https://example.com/#org",
                    "name": "Acme Corp",
                    "url": "https://example.com/en",
                    "logo": "https://example.com/logo-new.png",
                },
            },
        ]
        res = check_publisher_consistency(entities)
        self.assertFalse(res["is_consistent"])
        inconsistent_fields = {inc["field"] for inc in res["inconsistencies"]}
        self.assertIn("name", inconsistent_fields)
        self.assertIn("url", inconsistent_fields)
        self.assertIn("logo", inconsistent_fields)

    def test_author_consistency_aligned(self):
        """Test author consistency with uniform data for same author @id."""
        entities = [
            {
                "@type": "Article",
                "_source_url": "https://example.com/post-1",
                "author": {
                    "@id": "https://example.com/#author-jane",
                    "name": "Jane Doe",
                    "url": "https://example.com/team/jane",
                },
            },
            {
                "@type": "Article",
                "_source_url": "https://example.com/post-2",
                "author": {
                    "@id": "https://example.com/#author-jane",
                    "name": "Jane Doe",
                    "url": "https://example.com/team/jane",
                },
            },
        ]
        res = check_author_consistency(entities)
        self.assertTrue(res["is_consistent"])
        self.assertEqual(len(res["inconsistencies"]), 0)

    def test_author_consistency_drift(self):
        """Test author consistency detects conflicting names for same @id."""
        entities = [
            {
                "@type": "Article",
                "_source_url": "https://example.com/post-1",
                "author": {
                    "@id": "https://example.com/#author-1",
                    "name": "Dr. Jane Doe",
                    "url": "https://example.com/team/jane",
                },
            },
            {
                "@type": "Article",
                "_source_url": "https://example.com/post-2",
                "author": {
                    "@id": "https://example.com/#author-1",
                    "name": "John Smith",
                    "url": "https://example.com/team/jane",
                },
            },
        ]
        res = check_author_consistency(entities)
        self.assertFalse(res["is_consistent"])
        self.assertEqual(res["inconsistencies"][0]["field"], "name")
        self.assertEqual(res["inconsistencies"][0]["author_id"], "https://example.com/#author-1")

    def test_audit_disambiguation(self):
        """Test auditing entity disambiguation signals."""
        nodes = {
            "https://example.com/#org-missing": EntityNode(
                id="https://example.com/#org-missing",
                type="Organization",
                name="Isolated Org",
                source_url="https://example.com",
                same_as=[],
            ),
            "https://example.com/#person-social-only": EntityNode(
                id="https://example.com/#person-social-only",
                type="Person",
                name="Social Person",
                source_url="https://example.com/person",
                same_as=["https://twitter.com/person", "https://linkedin.com/in/person"],
            ),
            "https://example.com/#org-full": EntityNode(
                id="https://example.com/#org-full",
                type="Organization",
                name="Complete Org",
                source_url="https://example.com",
                same_as=["https://www.wikidata.org/wiki/Q9999", "https://twitter.com/complete"],
            ),
            "https://example.com/#article": EntityNode(
                id="https://example.com/#article",
                type="Article",
                name="Some Article",
                source_url="https://example.com/post",
                same_as=[],
            ),
        }

        findings = audit_disambiguation(nodes)
        finding_ids = {f["node_id"]: f for f in findings}

        # Article should not be audited for sameAs
        self.assertNotIn("https://example.com/#article", finding_ids)

        # Missing all same_as should be flagged Warning
        self.assertIn("https://example.com/#org-missing", finding_ids)
        self.assertEqual(finding_ids["https://example.com/#org-missing"]["severity"], "Warning")
        self.assertEqual(finding_ids["https://example.com/#org-missing"]["status"], "missing_all")

        # Social-only same_as should be flagged Info for missing KG authority
        self.assertIn("https://example.com/#person-social-only", finding_ids)
        self.assertEqual(finding_ids["https://example.com/#person-social-only"]["severity"], "Info")
        self.assertEqual(finding_ids["https://example.com/#person-social-only"]["status"], "missing_kg_authority")

        # Org with Wikidata should NOT be flagged as missing
        self.assertNotIn("https://example.com/#org-full", finding_ids)


if __name__ == "__main__":
    unittest.main()
