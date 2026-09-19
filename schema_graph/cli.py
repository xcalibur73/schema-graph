"""
SchemaGraph CLI: Cross-Page Entity & Knowledge Graph Integrity Tracer.
"""

import sys
import json
import argparse

from schema_graph.extractor import (
    fetch_page_html,
    parse_sitemap_urls,
    extract_jsonld_blocks,
    flatten_entities,
)
from schema_graph.graph_builder import (
    build_entity_graph,
    find_broken_references,
    find_orphan_nodes,
    find_circular_references,
    check_publisher_consistency,
    check_author_consistency,
    audit_disambiguation,
)
from schema_graph.scorer import calculate_composite_score
from schema_graph.report_generator import (
    print_terminal_report,
    export_markdown_report,
    export_json_report,
    export_dot_graph,
)


def run_audit(urls: list[str]) -> dict:
    """Execute full SchemaGraph audit across provided URLs."""
    all_entities = []

    for url in urls:
        try:
            html = fetch_page_html(url)
            jsonld_blocks = extract_jsonld_blocks(html)
            entities = flatten_entities(jsonld_blocks, url)
            all_entities.extend(entities)
        except Exception as e:
            print(f"[WARN] Failed to fetch {url}: {e}", file=sys.stderr)
            continue

    if not all_entities:
        return {
            "urls": urls,
            "total_entities": 0,
            "total_edges": 0,
            "score_data": {
                "overall_score": 0,
                "grade": "F",
                "component_scores": {
                    "reference_integrity": 0,
                    "entity_connectivity": 0,
                    "disambiguation_depth": 0,
                    "publisher_consistency": 100,
                    "author_consistency": 100,
                },
            },
            "broken_refs": [],
            "orphan_nodes": [],
            "cycles": [],
            "disambiguation": [],
            "publisher_result": {"consistent": True, "inconsistencies": []},
            "author_result": {"consistent": True, "inconsistencies": []},
            "nodes": {},
            "edges": [],
        }

    # Build graph
    nodes, edges = build_entity_graph(all_entities)

    # Run integrity checks
    broken_refs = find_broken_references(nodes, edges)
    orphan_nodes_list = find_orphan_nodes(nodes, edges)
    cycles = find_circular_references(nodes, edges)
    disambiguation = audit_disambiguation(nodes)
    publisher_result = check_publisher_consistency(all_entities)
    author_result = check_author_consistency(all_entities)

    # Calculate scores
    from schema_graph.scorer import (
        calculate_reference_integrity_score,
        calculate_connectivity_score,
        calculate_disambiguation_score,
        calculate_publisher_score,
        calculate_author_score,
    )

    ref_score = calculate_reference_integrity_score(len(edges), len(broken_refs))
    conn_score = calculate_connectivity_score(len(nodes), len(orphan_nodes_list))
    disamb_score = calculate_disambiguation_score(disambiguation)
    pub_score = calculate_publisher_score(publisher_result)
    auth_score = calculate_author_score(author_result)

    score_data = calculate_composite_score(
        ref_score, conn_score, disamb_score, pub_score, auth_score
    )

    return {
        "urls": urls,
        "total_entities": len(nodes),
        "total_edges": len(edges),
        "score_data": score_data,
        "broken_refs": broken_refs,
        "orphan_nodes": orphan_nodes_list,
        "cycles": cycles,
        "disambiguation": disambiguation,
        "publisher_result": publisher_result,
        "author_result": author_result,
        "nodes": nodes,
        "edges": edges,
    }


def main():
    from schema_graph import __version__
    parser = argparse.ArgumentParser(
        prog="schema-graph",
        description="SchemaGraph: Cross-Page Entity & Knowledge Graph Integrity Tracer",
        epilog="Example: python run.py https://webaudits.pro --sitemap",
    )
    parser.add_argument(
        "urls",
        nargs="*",
        help="One or more URLs to audit, or a sitemap URL with --sitemap flag.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"SchemaGraph v{__version__}",
    )
    parser.add_argument(
        "--sitemap",
        action="store_true",
        help="Treat the first URL as a sitemap.xml and crawl all discovered URLs.",
    )
    parser.add_argument(
        "--max-urls",
        type=int,
        default=50,
        help="Maximum number of URLs to crawl from sitemap (default: 50).",
    )
    parser.add_argument(
        "--output",
        choices=["terminal", "markdown", "json", "dot"],
        default="terminal",
        help="Output format (default: terminal).",
    )
    parser.add_argument(
        "--save",
        type=str,
        default=None,
        help="Save report to file path.",
    )

    args = parser.parse_args()
    if not args.urls:
        parser.print_help()
        return 0

    # Resolve URLs
    urls = args.urls
    if args.sitemap:
        sitemap_url = urls[0]
        print(f"Parsing sitemap: {sitemap_url}")
        discovered = parse_sitemap_urls(sitemap_url)
        if not discovered:
            print(f"[ERROR] No URLs found in sitemap: {sitemap_url}", file=sys.stderr)
            sys.exit(1)
        urls = discovered[: args.max_urls]
        print(f"Discovered {len(discovered)} URLs, auditing {len(urls)}")

    print(f"SchemaGraph: Auditing {len(urls)} URL(s)...")

    result = run_audit(urls)

    # Output
    if args.output == "terminal":
        print_terminal_report(
            urls=result["urls"],
            score_data=result["score_data"],
            broken_refs=result["broken_refs"],
            orphan_nodes=result["orphan_nodes"],
            cycles=result["cycles"],
            disambiguation=result["disambiguation"],
            publisher_result=result["publisher_result"],
            author_result=result["author_result"],
            total_entities=result["total_entities"],
            total_edges=result["total_edges"],
        )

    elif args.output == "markdown":
        md = export_markdown_report(
            urls=result["urls"],
            score_data=result["score_data"],
            broken_refs=result["broken_refs"],
            orphan_nodes=result["orphan_nodes"],
            cycles=result["cycles"],
            disambiguation=result["disambiguation"],
            publisher_result=result["publisher_result"],
            author_result=result["author_result"],
            total_entities=result["total_entities"],
            total_edges=result["total_edges"],
        )
        if args.save:
            with open(args.save, "w", encoding="utf-8") as f:
                f.write(md)
            print(f"Markdown report saved to: {args.save}")
        else:
            print(md)

    elif args.output == "json":
        report = export_json_report(
            urls=result["urls"],
            score_data=result["score_data"],
            broken_refs=result["broken_refs"],
            orphan_nodes=result["orphan_nodes"],
            cycles=result["cycles"],
            disambiguation=result["disambiguation"],
            publisher_result=result["publisher_result"],
            author_result=result["author_result"],
            total_entities=result["total_entities"],
            total_edges=result["total_edges"],
        )
        json_str = json.dumps(report, indent=2, ensure_ascii=False)
        if args.save:
            with open(args.save, "w", encoding="utf-8") as f:
                f.write(json_str)
            print(f"JSON report saved to: {args.save}")
        else:
            print(json_str)

    elif args.output == "dot":
        dot = export_dot_graph(
            nodes=result["nodes"],
            edges=result["edges"],
            broken_refs=result["broken_refs"],
        )
        if args.save:
            with open(args.save, "w", encoding="utf-8") as f:
                f.write(dot)
            print(f"DOT graph saved to: {args.save}")
        else:
            print(dot)


if __name__ == "__main__":
    main()
