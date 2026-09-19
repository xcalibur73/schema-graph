"""
Report Generator & Formatter for SchemaGraph Entity Audits.
Outputs terminal tables, Markdown documents, JSON objects, and DOT graph definitions.
"""

from typing import Dict, Any, List

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


def _severity_color(severity: str) -> str:
    """Map severity label to rich color."""
    return {
        "CRITICAL": "bold red",
        "WARNING": "yellow",
        "INFO": "cyan",
    }.get(severity, "white")


def print_terminal_report(
    urls: List[str],
    score_data: Dict[str, Any],
    broken_refs: List[dict],
    orphan_nodes: List[dict],
    cycles: List[list],
    disambiguation: List[dict],
    publisher_result: Dict[str, Any],
    author_result: Dict[str, Any],
    total_entities: int,
    total_edges: int,
) -> None:
    """Print full audit report to terminal."""
    if not HAS_RICH:
        _print_plain_report(
            urls, score_data, broken_refs, orphan_nodes, cycles,
            disambiguation, publisher_result, author_result,
            total_entities, total_edges,
        )
        return

    console = Console()

    overall = score_data["overall_score"]
    grade = score_data["grade"]
    score_color = "green" if overall >= 75 else ("yellow" if overall >= 50 else "red")

    header = Text()
    header.append("SchemaGraph: Cross-Page Entity & Knowledge Graph Integrity Tracer\n", style="bold magenta")
    header.append(f"Crawled URLs: {len(urls)}\n", style="bold white")
    header.append(f"Graph Integrity Score: {overall}/100 (Grade: {grade})\n", style=f"bold {score_color}")
    header.append(f"Entities: {total_entities} | Edges: {total_edges} | Broken Refs: {len(broken_refs)} | Orphans: {len(orphan_nodes)} | Cycles: {len(cycles)}", style="dim")

    console.print(Panel(header, border_style="magenta"))

    # Component scores table
    comp = score_data["component_scores"]
    comp_table = Table(title="Component Score Breakdown", show_header=True, header_style="bold cyan")
    comp_table.add_column("Component", style="white")
    comp_table.add_column("Weight", style="dim", justify="center")
    comp_table.add_column("Score", justify="center")

    for name, weight, val in [
        ("Reference Integrity", "35%", comp["reference_integrity"]),
        ("Entity Connectivity", "25%", comp["entity_connectivity"]),
        ("Disambiguation Depth", "20%", comp["disambiguation_depth"]),
        ("Publisher Consistency", "10%", comp["publisher_consistency"]),
        ("Author Consistency", "10%", comp["author_consistency"]),
    ]:
        sc_color = "green" if val >= 75 else ("yellow" if val >= 50 else "red")
        comp_table.add_row(name, weight, f"[{sc_color}]{val}/100[/{sc_color}]")

    console.print(comp_table)

    # Broken references
    if broken_refs:
        br_table = Table(title="Broken @id References (CRITICAL)", show_header=True, header_style="bold red")
        br_table.add_column("Referenced @id", style="red")
        br_table.add_column("Referenced By", style="white")
        br_table.add_column("Property", style="dim")
        br_table.add_column("Source URL", style="dim")
        for ref in broken_refs[:20]:
            br_table.add_row(ref["target_id"], ref.get("source_id", ""), ref.get("property", ""), ref.get("source_url", ""))
        console.print(br_table)

    # Orphan nodes
    if orphan_nodes:
        orph_table = Table(title="Orphan Entity Nodes (WARNING)", show_header=True, header_style="bold yellow")
        orph_table.add_column("@id", style="yellow")
        orph_table.add_column("@type", style="white")
        orph_table.add_column("Name", style="dim")
        orph_table.add_column("Source URL", style="dim")
        for node in orphan_nodes[:20]:
            orph_table.add_row(node.get("id", ""), node.get("type", ""), node.get("name", ""), node.get("source_url", ""))
        console.print(orph_table)

    # Circular references
    if cycles:
        cyc_table = Table(title="Circular @id Resolution Chains (CRITICAL)", show_header=True, header_style="bold red")
        cyc_table.add_column("Cycle Path", style="red")
        for cycle in cycles[:10]:
            cyc_table.add_row(" -> ".join(cycle))
        console.print(cyc_table)

    # Disambiguation gaps
    missing_disambiguation = [d for d in disambiguation if not d.get("has_same_as")]
    if missing_disambiguation:
        dis_table = Table(title="Missing Disambiguation Signals (INFO)", show_header=True, header_style="bold cyan")
        dis_table.add_column("@id", style="cyan")
        dis_table.add_column("@type", style="white")
        dis_table.add_column("Name", style="dim")
        dis_table.add_column("Missing", style="yellow")
        for d in missing_disambiguation[:15]:
            missing_items = []
            if not d.get("has_same_as"):
                missing_items.append("sameAs")
            if not d.get("has_url"):
                missing_items.append("url")
            dis_table.add_row(d.get("id", ""), d.get("type", ""), d.get("name", ""), ", ".join(missing_items))
        console.print(dis_table)

    # Publisher consistency
    if publisher_result.get("inconsistencies"):
        pub_table = Table(title="Publisher Metadata Drift (WARNING)", show_header=True, header_style="bold yellow")
        pub_table.add_column("Field", style="white")
        pub_table.add_column("Variants Found", style="yellow")
        for inc in publisher_result["inconsistencies"]:
            pub_table.add_row(inc["field"], " vs ".join(f'"{v}"' for v in inc["values"]))
        console.print(pub_table)

    # Author consistency
    if author_result.get("inconsistencies"):
        auth_table = Table(title="Author Metadata Drift (WARNING)", show_header=True, header_style="bold yellow")
        auth_table.add_column("@id", style="white")
        auth_table.add_column("Field", style="white")
        auth_table.add_column("Variants Found", style="yellow")
        for inc in author_result["inconsistencies"]:
            auth_table.add_row(inc.get("id", ""), inc["field"], " vs ".join(f'"{v}"' for v in inc["values"]))
        console.print(auth_table)

    console.print()


def _print_plain_report(
    urls, score_data, broken_refs, orphan_nodes, cycles,
    disambiguation, publisher_result, author_result,
    total_entities, total_edges,
) -> None:
    """Fallback plain text output when rich is not installed."""
    print(f"\n=== SchemaGraph: Entity & Knowledge Graph Integrity Tracer ===")
    print(f"Crawled URLs: {len(urls)}")
    print(f"Graph Integrity Score: {score_data['overall_score']}/100 (Grade: {score_data['grade']})")
    print(f"Entities: {total_entities} | Edges: {total_edges}")
    print(f"Broken References: {len(broken_refs)} | Orphan Nodes: {len(orphan_nodes)} | Cycles: {len(cycles)}")

    if broken_refs:
        print(f"\n--- Broken @id References (CRITICAL) ---")
        for ref in broken_refs[:20]:
            print(f"  {ref['target_id']} <- referenced by {ref.get('source_id', '?')} via {ref.get('property', '?')}")

    if orphan_nodes:
        print(f"\n--- Orphan Entity Nodes (WARNING) ---")
        for node in orphan_nodes[:20]:
            print(f"  {node.get('id', '?')} [{node.get('type', '?')}] from {node.get('source_url', '?')}")

    if cycles:
        print(f"\n--- Circular @id Chains (CRITICAL) ---")
        for cycle in cycles[:10]:
            print(f"  {' -> '.join(cycle)}")

    print()


def export_markdown_report(
    urls: List[str],
    score_data: Dict[str, Any],
    broken_refs: List[dict],
    orphan_nodes: List[dict],
    cycles: List[list],
    disambiguation: List[dict],
    publisher_result: Dict[str, Any],
    author_result: Dict[str, Any],
    total_entities: int,
    total_edges: int,
) -> str:
    """Generate Markdown audit report string."""
    lines = []
    lines.append("# SchemaGraph: Entity & Knowledge Graph Integrity Audit\n")
    lines.append(f"**Crawled URLs**: {len(urls)}\n")
    lines.append(f"**Graph Integrity Score**: {score_data['overall_score']}/100 (Grade: {score_data['grade']})\n")
    lines.append(f"**Entities**: {total_entities} | **Edges**: {total_edges} | **Broken Refs**: {len(broken_refs)} | **Orphans**: {len(orphan_nodes)} | **Cycles**: {len(cycles)}\n")

    # Component scores
    lines.append("---\n")
    lines.append("## Component Score Breakdown\n")
    lines.append("| Component | Weight | Score |")
    lines.append("|:---|:---:|:---:|")
    comp = score_data["component_scores"]
    for name, weight, val in [
        ("Reference Integrity", "35%", comp["reference_integrity"]),
        ("Entity Connectivity", "25%", comp["entity_connectivity"]),
        ("Disambiguation Depth", "20%", comp["disambiguation_depth"]),
        ("Publisher Consistency", "10%", comp["publisher_consistency"]),
        ("Author Consistency", "10%", comp["author_consistency"]),
    ]:
        lines.append(f"| {name} | {weight} | {val}/100 |")

    # Broken references
    if broken_refs:
        lines.append("\n---\n")
        lines.append("## Broken @id References (CRITICAL)\n")
        lines.append("| Referenced @id | Referenced By | Property | Source URL |")
        lines.append("|:---|:---|:---|:---|")
        for ref in broken_refs[:30]:
            lines.append(f"| `{ref['target_id']}` | `{ref.get('source_id', '')}` | {ref.get('property', '')} | {ref.get('source_url', '')} |")

    # Orphan nodes
    if orphan_nodes:
        lines.append("\n---\n")
        lines.append("## Orphan Entity Nodes (WARNING)\n")
        lines.append("| @id | @type | Name | Source URL |")
        lines.append("|:---|:---|:---|:---|")
        for node in orphan_nodes[:30]:
            lines.append(f"| `{node.get('id', '')}` | {node.get('type', '')} | {node.get('name', '')} | {node.get('source_url', '')} |")

    # Cycles
    if cycles:
        lines.append("\n---\n")
        lines.append("## Circular @id Resolution Chains (CRITICAL)\n")
        for i, cycle in enumerate(cycles[:10], 1):
            lines.append(f"{i}. `{' -> '.join(cycle)}`")

    # URLs crawled
    lines.append("\n---\n")
    lines.append("## Crawled URLs\n")
    for url in urls:
        lines.append(f"- {url}")

    lines.append("\n---\n")
    lines.append("*Generated by [SchemaGraph](https://github.com/xcalibur73/schema-graph) | [WebAudits.pro](https://webaudits.pro/tools/schema-graph)*\n")

    return "\n".join(lines)


def export_json_report(
    urls: List[str],
    score_data: Dict[str, Any],
    broken_refs: List[dict],
    orphan_nodes: List[dict],
    cycles: List[list],
    disambiguation: List[dict],
    publisher_result: Dict[str, Any],
    author_result: Dict[str, Any],
    total_entities: int,
    total_edges: int,
) -> dict:
    """Build JSON-serializable audit report dict."""
    return {
        "tool": "SchemaGraph",
        "version": "1.0.0",
        "urls_crawled": urls,
        "total_entities": total_entities,
        "total_edges": total_edges,
        "score": score_data,
        "broken_references": broken_refs,
        "orphan_nodes": orphan_nodes,
        "circular_chains": cycles,
        "disambiguation_audit": disambiguation,
        "publisher_consistency": publisher_result,
        "author_consistency": author_result,
    }


def export_dot_graph(
    nodes: dict,
    edges: list,
    broken_refs: List[dict],
) -> str:
    """Generate DOT graph definition for Graphviz visualization."""
    lines = []
    lines.append("digraph SchemaGraph {")
    lines.append('  rankdir=LR;')
    lines.append('  node [shape=box, style="rounded,filled", fontname="Arial", fontsize=10];')
    lines.append('  edge [fontname="Arial", fontsize=8];')
    lines.append("")

    # Broken reference target IDs for red coloring
    broken_ids = {ref["target_id"] for ref in broken_refs}

    # Emit nodes
    for node_id, node in nodes.items():
        label = f"{node.type}\\n{node.name or node_id}"
        safe_id = node_id.replace('"', '\\"').replace(":", "_").replace("/", "_").replace("#", "_").replace(".", "_")
        if node_id in broken_ids:
            lines.append(f'  "{safe_id}" [label="{label}", fillcolor="#FFCCCC", color="#CC0000"];')
        else:
            type_colors = {
                "Organization": "#CCE5FF",
                "Person": "#D4EDDA",
                "WebSite": "#FFF3CD",
                "Article": "#E2E3E5",
                "WebPage": "#E2E3E5",
                "Product": "#F8D7DA",
            }
            fill = type_colors.get(node.type, "#F0F0F0")
            lines.append(f'  "{safe_id}" [label="{label}", fillcolor="{fill}"];')

    lines.append("")

    # Emit edges
    for edge in edges:
        src = edge.source_id.replace('"', '\\"').replace(":", "_").replace("/", "_").replace("#", "_").replace(".", "_")
        tgt = edge.target_id.replace('"', '\\"').replace(":", "_").replace("/", "_").replace("#", "_").replace(".", "_")
        prop = edge.property_name
        if edge.target_id in broken_ids:
            lines.append(f'  "{src}" -> "{tgt}" [label="{prop}", color="#CC0000", style=dashed];')
        else:
            lines.append(f'  "{src}" -> "{tgt}" [label="{prop}"];')

    lines.append("}")
    return "\n".join(lines)
