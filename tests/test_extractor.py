"""
Unit tests for SchemaGraph JSON-LD extractor module.

Author: @xcalibur73
License: MIT
"""

import gzip
import os
import tempfile
import unittest
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from unittest.mock import MagicMock, patch
import requests

from schema_graph.extractor import (
    extract_jsonld_blocks,
    fetch_page_html,
    flatten_entities,
    normalize_id,
    parse_sitemap_urls,
)


class TestExtractorComprehensive(unittest.TestCase):

    def test_normalize_id_trailing_slash(self):
        self.assertEqual(normalize_id("https://example.com/"), "https://example.com")
        self.assertEqual(normalize_id("https://example.com/about/"), "https://example.com/about")
        self.assertEqual(normalize_id("https://example.com/post/#author/"), "https://example.com/post#author")

    def test_normalize_id_http_to_https(self):
        self.assertEqual(normalize_id("http://example.com/"), "https://example.com")
        self.assertEqual(normalize_id("http://example.com/#org"), "https://example.com/#org")
        self.assertEqual(normalize_id("//example.com/assets"), "https://example.com/assets")

    def test_normalize_id_relative_resolution(self):
        self.assertEqual(normalize_id("/contact/", "https://example.com"), "https://example.com/contact")
        self.assertEqual(normalize_id("#author", "https://example.com/"), "https://example.com/#author")
        self.assertEqual(normalize_id("#author", "https://example.com"), "https://example.com/#author")
        self.assertEqual(normalize_id("#author", "https://example.com/post/"), "https://example.com/post#author")

    def test_normalize_id_port_and_urn(self):
        self.assertEqual(normalize_id("http://example.com:80/home"), "https://example.com/home")
        self.assertEqual(normalize_id("https://example.com:443/home"), "https://example.com/home")
        self.assertEqual(normalize_id("urn:uuid:12345/"), "urn:uuid:12345")
        self.assertEqual(normalize_id(""), "")

    def test_extract_jsonld_blocks_standard(self):
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@context": "https://schema.org", "@type": "Organization", "name": "Acme Corp"}
        </script>
        </head><body></body></html>
        """
        blocks = extract_jsonld_blocks(html)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["@type"], "Organization")

    def test_extract_jsonld_blocks_cdata_and_comments(self):
        html = """
        <html><head>
        <script type="application/ld+json">
        <!--
        {"@type": "Article", "name": "Commented"}
        -->
        </script>
        <script type="application/ld+json">
        /* <![CDATA[ */
        {"@type": "Person", "name": "CDATA Person"}
        /* ]]> */
        </script>
        </head><body></body></html>
        """
        blocks = extract_jsonld_blocks(html)
        self.assertEqual(len(blocks), 2)
        types = [b["@type"] for b in blocks]
        self.assertIn("Article", types)
        self.assertIn("Person", types)

    def test_extract_jsonld_blocks_trailing_comma(self):
        html = """
        <script type="application/ld+json">
        {"@type": "Thing", "name": "Fixed",}
        </script>
        """
        blocks = extract_jsonld_blocks(html)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["name"], "Fixed")

    def test_flatten_entities_synthetic_id(self):
        blocks = [{"@context": "https://schema.org", "@type": "Article", "name": "Guide"}]
        entities = flatten_entities(blocks, "https://example.com/guide")
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0]["@id"], "https://example.com/guide#Article#1")
        self.assertEqual(entities[0]["_source_url"], "https://example.com/guide")

    def test_flatten_entities_nested_inline(self):
        blocks = [
            {
                "@type": "Article",
                "@id": "https://example.com/post-1",
                "headline": "Post One",
                "author": {
                    "@type": "Person",
                    "name": "Jane",
                    "worksFor": {
                        "@type": "Organization",
                        "@id": "http://example.com/#org",
                        "name": "Acme"
                    }
                },
                "publisher": {
                    "@id": "http://example.com/#org"
                }
            }
        ]
        entities = flatten_entities(blocks, "https://example.com/post-1")
        self.assertEqual(len(entities), 3)

        by_id = {e["@id"]: e for e in entities}
        self.assertIn("https://example.com/post-1", by_id)
        self.assertIn("https://example.com/post-1#Person#1", by_id)
        self.assertIn("https://example.com/#org", by_id)

        article = by_id["https://example.com/post-1"]
        self.assertEqual(article["author"], {"@id": "https://example.com/post-1#Person#1"})
        self.assertEqual(article["publisher"], {"@id": "https://example.com/#org"})

    def test_flatten_entities_multi_type(self):
        blocks = [
            {
                "@context": "https://schema.org",
                "@type": ["LocalBusiness", "MedicalClinic"],
                "name": "Clinic"
            }
        ]
        entities = flatten_entities(blocks, "https://example.com/clinic")
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0]["@id"], "https://example.com/clinic#LocalBusiness_MedicalClinic#1")

    def test_flatten_entities_circular_loop(self):
        obj1 = {"@type": "Person", "name": "Alice"}
        obj2 = {"@type": "Organization", "name": "Company"}
        obj1["worksFor"] = obj2
        obj2["founder"] = obj1

        entities = flatten_entities([obj1], "https://example.com")
        self.assertEqual(len(entities), 2)
        ids = {e["@id"] for e in entities}
        self.assertIn("https://example.com#Person#1", ids)
        self.assertIn("https://example.com#Organization#1", ids)

    def test_parse_sitemap_urls_local_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sitemap_path = os.path.join(tmpdir, "sitemap.xml")
            with open(sitemap_path, "w", encoding="utf-8") as f:
                f.write("""<?xml version="1.0" encoding="UTF-8"?>
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                    <url><loc>https://example.com/page1</loc></url>
                    <url><loc>https://example.com/page2?test=1&amp;param=2</loc></url>
                </urlset>""")

            urls = parse_sitemap_urls(sitemap_path)
            self.assertEqual(len(urls), 2)
            self.assertIn("https://example.com/page1", urls)
            self.assertIn("https://example.com/page2?test=1&param=2", urls)

    def test_parse_sitemap_urls_unescaped_ampersand(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sitemap_path = os.path.join(tmpdir, "sitemap_bad.xml")
            with open(sitemap_path, "w", encoding="utf-8") as f:
                f.write("""<?xml version="1.0" encoding="UTF-8"?>
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                    <url><loc>https://example.com/bad?a=1&b=2</loc></url>
                </urlset>""")

            urls = parse_sitemap_urls(sitemap_path)
            self.assertEqual(len(urls), 1)
            self.assertEqual(urls[0], "https://example.com/bad?a=1&b=2")

    def test_parse_sitemap_urls_gzipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gz_path = os.path.join(tmpdir, "sitemap.xml.gz")
            content = b"""<?xml version="1.0" encoding="UTF-8"?>
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                <url><loc>https://example.com/gz-page</loc></url>
            </urlset>"""
            with gzip.open(gz_path, "wb") as f:
                f.write(content)
            urls = parse_sitemap_urls(gz_path)
            self.assertEqual(urls, ["https://example.com/gz-page"])

    def test_parse_sitemap_urls_index_recursion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            child_path = os.path.join(tmpdir, "child.xml")
            with open(child_path, "w", encoding="utf-8") as f:
                f.write("""<?xml version="1.0" encoding="UTF-8"?>
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                    <url><loc>https://example.com/child-page</loc></url>
                </urlset>""")

            index_path = os.path.join(tmpdir, "index.xml")
            with open(index_path, "w", encoding="utf-8") as f:
                f.write(f"""<?xml version="1.0" encoding="UTF-8"?>
                <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                    <sitemap><loc>{child_path}</loc></sitemap>
                </sitemapindex>""")

            urls = parse_sitemap_urls(index_path, recurse=True)
            self.assertEqual(urls, ["https://example.com/child-page"])

    @patch("schema_graph.extractor.requests.get")
    def test_fetch_page_html(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>Test</body></html>"
        mock_response.encoding = "utf-8"
        mock_get.return_value = mock_response

        html = fetch_page_html("https://example.com")
        self.assertEqual(html, "<html><body>Test</body></html>")
        mock_response.raise_for_status.assert_called_once()

    @patch("schema_graph.extractor.requests.get")
    def test_fetch_page_html_error(self, mock_get):
        mock_get.side_effect = requests.RequestException("Network Error")
        with self.assertRaises(requests.RequestException):
            fetch_page_html("https://invalid.domain.test")

    def test_defensive_unescape_kses_jsonld(self):
        # Mangled KSES script tag with HTML entity encoded quotes and ampersands
        html = """
        <html><head>
        <script type="application/ld+json">
        {&quot;@context&quot;: &quot;https://schema.org&quot;, &quot;@type&quot;: &quot;Organization&quot;, &quot;name&quot;: &quot;Acme &amp;#038; Sons&quot;}
        </script>
        </head><body></body></html>
        """
        blocks = extract_jsonld_blocks(html)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["@type"], "Organization")
        self.assertEqual(blocks[0]["name"], "Acme & Sons")

    def test_clean_entity_strings_double_encoded(self):
        html = """
        <html><head>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": "Design &amp;amp; Architecture",
            "description": "Guides &amp;#038; Tutorials"
        }
        </script>
        </head><body></body></html>
        """
        blocks = extract_jsonld_blocks(html)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["name"], "Design & Architecture")
        self.assertEqual(blocks[0]["description"], "Guides & Tutorials")

    def test_commented_jsonld_with_trailing_commas(self):
        html = """
        <html><head>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org", // main schema context
            "@type": "Organization",
            /* developer notes: official name */
            "name": "Acme Global",
            "url": "https://example.com/org", // official url
        }
        </script>
        </head><body></body></html>
        """
        blocks = extract_jsonld_blocks(html)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["name"], "Acme Global")
        self.assertEqual(blocks[0]["url"], "https://example.com/org")


    def test_cdata_wrapped_jsonld_extraction(self):
        html = """
        <html><head>
        <script type="application/ld+json">
        /* <![CDATA[ */
        {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": "WordPress Enterprise",
            "url": "https://example.com"
        }
        /* ]]> */
        </script>
        </head><body></body></html>
        """
        blocks = extract_jsonld_blocks(html)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["name"], "WordPress Enterprise")

    def test_bare_cdata_wrapped_jsonld_extraction(self):
        html = """
        <html><head>
        <script type="application/ld+json">
        <![CDATA[
        {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": "CDATA Site"
        }
        ]]>
        </script>
        </head><body></body></html>
        """
        blocks = extract_jsonld_blocks(html)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["name"], "CDATA Site")


if __name__ == "__main__":
    unittest.main()

