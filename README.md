# SchemaGraph

Cross-page entity and knowledge graph integrity tracer for Schema.org JSON-LD.

Part of the [WebAudits.pro](https://webaudits.pro) technical intelligence platform.

---

## What it does

SchemaGraph extracts, connects, and audits structured data entities across multi-page website clusters. It builds an in-memory directed knowledge graph from `<script type="application/ld+json">` blocks and detects:
- Broken `@id` references (entities pointing to target URI identifiers that are never defined anywhere on the domain).
- Orphan entity nodes (defined schema objects that have no inbound structural relationships).
- Circular `@id` dependency chains using depth-first search (DFS) cycle detection.
- Publisher and author metadata drift across template layouts (inconsistent names, logos, or URLs).
- Entity disambiguation depth (presence of canonical `sameAs` links to Wikidata, Wikipedia, or verified authority profiles).

---

## Why it exists

Modern websites often deploy structured data on a per-page basis using plugins or CMS components. This produces fragmented, isolated entities rather than a cohesive Knowledge Graph:
- A blog post references an `@id` for its publisher or author that exists on another page, but trailing slashes, protocol mismatches, or slug changes break the resolution chain.
- Search engines (Google Knowledge Graph, AI Overviews, Perplexity) rely on `@id` node connections to establish topical authority and entity relationships.

SchemaGraph audits the entire domain graph as a single connected data structure, identifying resolution defects that standard single-page validators miss.

---

## Key features

- **Multi-Page Cluster Ingestion:** Audits an array of explicit URLs or automatically crawls URLs discovered in an XML sitemap.
- **In-Memory Directed Graph Engine:** Parses nested `@graph` arrays and flattened entities into a queryable graph of nodes and directed edges.
- **Cycle Detection:** Implements Tarjan / DFS cycle detection algorithms to isolate recursive reference loops that trap crawlers.
- **Disambiguation Signal Auditor:** Checks key entity types (`Organization`, `Person`, `WebSite`) for disambiguation properties (`sameAs`, `url`, `identifier`).
- **GraphViz DOT Export:** Exports graph architecture directly into GraphViz DOT format for visual rendering and architectural review.

---

## Architecture

```text
[URL List or Sitemap]
         |
         v
[JSON-LD Extractor] ----------> Raw Blocks & Normalized @id URIs
         |
         v
[Entity Graph Builder] -------> In-Memory Directed Graph
         |
         +---> Broken @id Reference Resolver
         +---> Orphan Node Identifier
         +---> DFS Circular Dependency Detector
         +---> Publisher & Author Consistency Checker
         +---> Disambiguation Coverage Auditor
         |
         v
[Scoring Engine] -------------> 5-Component Composite Graph Integrity Score
         |
         +---> Terminal Report (Rich Table)
         +---> Markdown Document / JSON Object / GraphViz DOT Export
```

SchemaGraph operates in four modules:
1. `extractor.py`: Fetches HTML, parses XML sitemaps, extracts JSON-LD blocks, normalizes URI formats, and flattens entities into uniform data dictionaries.
2. `graph_builder.py`: Builds nodes and directed edges based on entity reference properties (`author`, `publisher`, `isPartOf`, `mainEntityOfPage`, `about`), running DFS cycle detection.
3. `scorer.py`: Evaluates graph health across five weighted dimensions: Reference Integrity (35%), Entity Connectivity (25%), Disambiguation Depth (20%), Publisher Consistency (10%), and Author Consistency (10%).
4. `report_generator.py`: Generates Rich terminal tables, Markdown documentation, JSON objects, and DOT graph files.

---

## Installation

### Prerequisites
- Python 3.10 or higher

### Install from Source
```bash
git clone https://github.com/xcalibur73/schema-graph.git
cd schema-graph
pip install -r requirements.txt
pip install -e .
```

---

## Usage

### Basic CLI Invocation
```bash
# Audit specific URLs
schema-graph https://webaudits.pro https://webaudits.pro/about

# Crawl and audit an entire domain via sitemap (up to 50 URLs)
schema-graph https://webaudits.pro/sitemap.xml --sitemap --max-urls 50

# Export as GraphViz DOT file for visual rendering
schema-graph https://webaudits.pro/sitemap.xml --sitemap --output dot --save graph.dot

# Export machine-readable JSON report
schema-graph https://webaudits.pro --output json --save audit.json

# Check installed version
schema-graph --version
```

---

## Example output

```text
+-------------------------------------------------------------------------------+
| SchemaGraph: Cross-Page Entity & Knowledge Graph Integrity Tracer             |
| Crawled URLs: 12                                                              |
| Graph Integrity Score: 94.5/100 (Grade: A)                                    |
| Entities: 48 | Edges: 52 | Broken Refs: 0 | Orphans: 2 | Cycles: 0            |
+-------------------------------------------------------------------------------+

Component Score Breakdown:
+------------------------+--------+------------+
| Component              | Weight | Score      |
+------------------------+--------+------------+
| Reference Integrity    | 35%    | 100.0/100  |
| Entity Connectivity    | 25%    | 95.8/100   |
| Disambiguation Depth   | 20%    | 88.0/100   |
| Publisher Consistency  | 10%    | 100.0/100  |
| Author Consistency     | 10%    | 100.0/100  |
+------------------------+--------+------------+

Disambiguation Depth Audit:
- Organization (webaudits.pro): 7 verified sameAs links (Wikidata, Twitter, GitHub)
- Person (@xcalibur73): Verified profile links present
```

---

## Benchmark / methodology

### Empirical 12-Site Entity Integrity Study
- **Dataset:** 12 multi-page production site clusters across publishing, e-commerce, and SaaS platforms.
- **Command Used:** `python run.py <sitemap_url> --sitemap --max-urls 25 --output json`
- **Tool Version:** SchemaGraph v1.0.0
- **Environment:** Windows 11 / Ubuntu 22.04, Python 3.12, unthrottled fiber network.
- **Raw Telemetry & Calculation:**
  - Reference Integrity: `((total_references - broken_references) / total_references) * 100`
  - Connectivity Ratio: `((total_nodes - orphan_nodes) / total_nodes) * 100`
- **Results:**
  - 58.3% of surveyed production websites contained at least one broken cross-page `@id` reference.
  - Complete study dataset: [BENCHMARKS.md](BENCHMARKS.md).

---

## Limitations

- **Diagnostic Heuristic:** The Graph Integrity Score is a project-derived structural evaluation. It does not measure Google's internal Knowledge Graph indexing state or ensure rich snippet eligibility.
- **Microdata & RDFa:** SchemaGraph specifically audits `<script type="application/ld+json">` blocks. It does not parse inline HTML5 Microdata attributes or RDFa tags.
- **External Entity Verification:** Audits the presence and syntax of `sameAs` links; it does not crawl external Wikidata or Wikipedia pages to verify that the external entity matches.

---

## Accuracy / standards

SchemaGraph aligns its analysis with official W3C standards and project heuristics:

| Metric / Check | Classification | Authority / Standard |
|:---|:---|:---|
| JSON-LD Syntactic Validity | Web Standard | W3C JSON-LD 1.1 Specification |
| Schema.org Type Vocabulary | Web Standard | Schema.org Community Group |
| Reference Resolution Integrity | Project-Derived Heuristic | Graph closure over domain crawl |
| Disambiguation Depth Score | Project-Derived Heuristic | Authority coverage model |
| Graph Integrity Composite Score | Project-Derived Heuristic | 5-factor weighted structural formula |

---

## Testing

SchemaGraph features comprehensive test coverage across extractor parsing, graph construction, cycle detection, and scoring:

```bash
# Run unit test suite
python -m unittest discover -s tests

# Test execution output
# Ran 95 tests in 0.041s
# OK
```

Automated CI executes on every push and pull request via GitHub Actions across Linux and Windows environments.

---

## Roadmap

- [x] Initial release with in-memory graph builder and DFS cycle detector.
- [x] PEP 621 packaging, CLI `--version`, and Windows cp1252 encoding hardening.
- [ ] Direct validation against Google Search Central Rich Results test API.
- [ ] Interactive SVG network graph visualization export.
- [ ] WebAudits.pro continuous entity drift alerts.

---

## License

MIT License. See [LICENSE](LICENSE) for full details.
