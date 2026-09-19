# SchemaGraph

Cross-Page Entity & Knowledge Graph Integrity Tracer

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Status: Production](https://img.shields.io/badge/status-production-success.svg)](#)
[![Cloud Engine: WebAudits.pro](https://img.shields.io/badge/cloud-webaudits.pro-orange.svg)](https://webaudits.pro/tools/schema-graph)

SchemaGraph is a command-line utility and Python diagnostic engine that validates Schema.org JSON-LD entity graphs across multi-page websites. Standard schema validation tools inspect syntax on a single page in isolation. SchemaGraph constructs a directed knowledge graph from all discovered JSON-LD blocks across an entire site cluster and traces cross-page entity integrity.

Key capabilities:
- Multi-URL crawling with automatic JSON-LD extraction from `<script type="application/ld+json">` blocks.
- In-memory directed knowledge graph construction with `@id` node resolution across pages.
- Broken reference detection: identifies `@id` URIs that point to nodes never defined on any crawled page.
- Orphan entity detection: finds `Person`, `Organization`, `WebSite`, and custom nodes declared but never referenced by any other entity.
- Circular reference tracing: detects `@id` loops (e.g., `Article -> author -> Person -> worksFor -> Organization -> publishesOn -> Article`).
- `sameAs` disambiguation audit: flags missing Wikidata, Wikipedia, or social profile links on entity nodes.
- Publisher and author consistency checks: verifies that `publisher` and `author` references resolve to consistent entity metadata across all pages.
- Multi-format output: high-contrast terminal tables, Markdown audit reports, JSON pipelines, and DOT/Graphviz graph export.

---

## The Engineering Problem

Google's Knowledge Graph, AI Overviews, and rich result features rely on connected entity graphs, not isolated page-level JSON-LD snippets. Common cross-page schema failures include:

1. Broken `@id` references: An `Article` node references `"author": {"@id": "https://example.com/#author"}`, but no page on the site defines a `Person` node with that `@id`. Google cannot resolve the entity and drops the author rich result.
2. Orphan entity nodes: A `WebSite` or `Organization` node is declared on the homepage but never referenced by any `Article`, `Product`, or `FAQPage` node. The entity exists in isolation with zero graph connectivity.
3. Circular dependency loops: Entity chains form infinite resolution cycles (Person -> worksFor -> Organization -> founder -> Person), causing crawler parsers to bail out.
4. Publisher metadata drift: The `publisher.name` on `/blog/post-1` says "Acme Corp" while `/blog/post-2` says "ACME Corporation". Google treats these as separate entities, fragmenting authority.
5. Missing disambiguation signals: Entity nodes lack `sameAs` links to Wikidata, Wikipedia, or LinkedIn, preventing Knowledge Graph reconciliation.

---

## Installation

```bash
git clone https://github.com/xcalibur73/schema-graph.git
cd schema-graph
pip install -r requirements.txt
```

### System Requirements
- Python 3.10 or higher.
- No external browser dependencies required (pure HTTP crawling with `requests` and `beautifulsoup4`).

---

## Usage

### Audit a Live Website
```bash
python run.py https://webaudits.pro
```

### Audit Multiple URLs
```bash
python run.py https://example.com https://example.com/about https://example.com/blog/post-1
```

### Crawl and Audit Entire Sitemap
```bash
python run.py https://example.com/sitemap.xml --sitemap
```

### Export Markdown Report
```bash
python run.py https://example.com --output markdown --save SCHEMA-AUDIT.md
```

### Export DOT Graph for Graphviz Visualization
```bash
python run.py https://example.com --output dot --save entity-graph.dot
```

### Export JSON for CI/CD Pipelines
```bash
python run.py https://example.com --output json --save audit.json
```

---

## Web Platform Integration (WebAudits.pro)

To run hosted audits without installing local Python dependencies:
- Interactive web tool: [WebAudits.pro/tools/schema-graph](https://webaudits.pro/tools/schema-graph)
- Automated multi-page crawling and entity graph visualization.

---

## Graph Construction Architecture

SchemaGraph operates in four sequential passes:

### Pass 1: Extraction
Crawls target URLs (or parses a sitemap XML) and extracts all `<script type="application/ld+json">` blocks. Handles nested `@graph` arrays, flattened single-entity documents, and mixed multi-type blocks.

### Pass 2: Graph Assembly
Builds a directed graph where:
- Each unique `@id` URI becomes a node.
- Each property referencing another `@id` (e.g., `"author": {"@id": "..."}`) becomes a directed edge.
- Inline entities without explicit `@id` are assigned synthetic identifiers based on their source URL and `@type`.

### Pass 3: Integrity Analysis
Runs six diagnostic checks against the assembled graph:

| Check | What It Detects | Severity |
|:---|:---|:---|
| Broken References | `@id` URIs referenced but never defined | Critical |
| Orphan Nodes | Entities defined but never referenced | Warning |
| Circular Dependencies | `@id` resolution chains that loop back | Critical |
| Publisher Drift | Inconsistent `name`, `url`, or `logo` across publisher references | Warning |
| Author Inconsistency | Same `@id` author with conflicting `name` or `sameAs` values | Warning |
| Missing Disambiguation | Entity nodes lacking `sameAs` links to Wikidata/Wikipedia | Info |

### Pass 4: Report Generation
Outputs results in the requested format: terminal table, Markdown document, JSON object, or DOT graph definition.

---

## Entity Resolution Rules

SchemaGraph follows these resolution precedence rules:

1. **Exact `@id` match**: Direct URI string comparison (case-sensitive, trailing slash normalized).
2. **Fragment identifier resolution**: `https://example.com/#author` resolves to the entity block on `https://example.com/` containing `"@id": "https://example.com/#author"`.
3. **Canonical URL normalization**: Strips query parameters, normalizes protocol (https preferred), and resolves relative URIs against the document base.
4. **Type-qualified fallback**: When no explicit `@id` exists, entities are keyed by `{source_url}#{@type}#{index}` to prevent false duplicate detection.

---

## Scoring Model

SchemaGraph produces an overall Graph Integrity Score (0-100):

| Component | Weight | Scoring Criteria |
|:---|:---:|:---|
| Reference Integrity | 35% | Percentage of `@id` references that resolve to defined nodes |
| Entity Connectivity | 25% | Ratio of connected vs orphan entity nodes |
| Disambiguation Depth | 20% | Presence of `sameAs`, `url`, and `identifier` on key entities |
| Publisher Consistency | 10% | Metadata uniformity across all `publisher` references |
| Author Consistency | 10% | Metadata uniformity across all `author` references |

---

## Running Unit Tests

```bash
python -m unittest discover tests/
```

---

## Author

Maintained by [@xcalibur73](https://github.com/xcalibur73), creator of [WebAudits.pro](https://webaudits.pro).

Part of a technical SEO engineering tooling suite:
1. [schema-graph](https://github.com/xcalibur73/schema-graph): Cross-page entity and knowledge graph integrity tracer.
2. [dom-hydrate](https://github.com/xcalibur73/dom-hydrate): Headless Chromium SSR vs CSR DOM diff engine.
3. [citation-pulse](https://github.com/xcalibur73/citation-pulse): GEO and AI search citability benchmark engine.
4. [index-trace](https://github.com/xcalibur73/index-trace): Search Console emergency triage and crawler collision tracer.
5. [overflow-trace](https://github.com/xcalibur73/overflow-trace): Mobile viewport horizontal overflow tracer.

---

## License

Licensed under the [MIT License](LICENSE).
