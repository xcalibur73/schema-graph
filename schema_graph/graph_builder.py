"""
SchemaGraph - Entity Knowledge Graph Builder and Integrity Analyzer.

Author: @xcalibur73
Cross-Page Schema.org JSON-LD Knowledge Graph Builder and Diagnostic Engine.
Validates cross-page @id references, detects broken pointers, identifies orphan
entities, traces circular resolution chains, audits disambiguation depth,
and verifies publisher and author metadata consistency across crawled clusters.
"""

from __future__ import annotations

import collections
import copy
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from rich.console import Console
    from rich.table import Table
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


# Canonical Schema.org relationship properties that reference other entity @id URIs
REFERENCE_PROPERTIES: Set[str] = {
    "author",
    "publisher",
    "creator",
    "founder",
    "funder",
    "sponsor",
    "worksFor",
    "memberOf",
    "parentOrganization",
    "subOrganization",
    "mainEntityOfPage",
    "mainEntity",
    "isPartOf",
    "hasPart",
    "about",
    "mentions",
    "itemReviewed",
    "provider",
    "brand",
    "manufacturer",
    "organizer",
    "performer",
    "location",
    "knowsAbout",
    "alumniOf",
    "alumni",
    "employee",
    "affiliation",
    "breadcrumb",
    "itemListElement",
    "item",
    "hasOfferCatalog",
    "makesOffer",
    "offers",
    "reviewRating",
    "reviewedBy",
    "editor",
    "translator",
    "producer",
    "copyrightHolder",
    "accountingService",
    "parent",
    "children",
    "colleague",
    "knows",
    "follows",
    "spouse",
    "publishingEntity",
    "publishingPrinciples",
}

# Key entity types requiring explicit sameAs disambiguation
KEY_DISAMBIGUATION_TYPES: Set[str] = {
    "Organization",
    "Corporation",
    "LocalBusiness",
    "NewsMediaOrganization",
    "EducationalOrganization",
    "GovernmentOrganization",
    "MedicalOrganization",
    "NGO",
    "SportsTeam",
    "Person",
    "Author",
    "WebSite",
}

# Authoritative Knowledge Graph authority link substrings
AUTHORITY_DOMAINS: List[str] = [
    "wikidata.org",
    "wikipedia.org",
]

# Recognized social and professional profile domains for disambiguation
SOCIAL_DOMAINS: List[str] = [
    "linkedin.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "github.com",
    "crunchbase.com",
    "pinterest.com",
    "tiktok.com",
]


@dataclass
class EntityNode:
    """Represents a resolved Schema.org entity node in the directed knowledge graph."""
    id: str
    type: str
    name: str
    source_url: str
    properties: dict = field(default_factory=dict)
    same_as: list = field(default_factory=list)


@dataclass
class GraphEdge:
    """Represents a directed reference relationship between two entity nodes."""
    source_id: str
    target_id: str
    property_name: str
    source_url: str


def normalize_uri(uri: str, base_url: str = "") -> str:
    """
    Normalize an entity URI or reference ID.
    Resolves fragment-only and relative references against base_url if provided.
    Normalizes trailing slashes for non-fragment URLs.
    """
    if not uri or not isinstance(uri, str):
        return ""
    uri_clean = uri.strip()
    if not uri_clean:
        return ""

    try:
        # Resolve relative URI or fragment against base_url if available
        if base_url and (uri_clean.startswith("#") or not urllib.parse.urlparse(uri_clean).scheme):
            uri_clean = urllib.parse.urljoin(base_url, uri_clean)

        parsed = urllib.parse.urlparse(uri_clean)
        if parsed.scheme and parsed.netloc:
            # Normalize trailing slash in path if no fragment or before fragment
            path = parsed.path
            if path and path != "/" and path.endswith("/"):
                path = path.rstrip("/")
            normalized = urllib.parse.urlunparse((
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                path,
                parsed.params,
                parsed.query,
                parsed.fragment
            ))
            return normalized
        return uri_clean
    except Exception:
        return uri_clean


def _extract_name_from_dict(d: dict) -> str:
    """Extract human-readable name or title from an entity dict."""
    if not isinstance(d, dict):
        return ""
    for k in ("name", "headline", "title", "legalName", "alternateName"):
        val = d.get(k)
        if val and isinstance(val, str):
            return val.strip()
    # Try givenName + familyName
    given = d.get("givenName")
    family = d.get("familyName")
    if given or family:
        parts = [str(p).strip() for p in (given, family) if p]
        return " ".join(parts)
    return ""


def _extract_type_str(raw_type: Any) -> str:
    """Extract normalized string representation of @type."""
    if not raw_type:
        return "Thing"
    if isinstance(raw_type, list):
        filtered = [str(t).strip() for t in raw_type if t]
        return ", ".join(filtered) if filtered else "Thing"
    return str(raw_type).strip()


def _extract_same_as_list(raw_same_as: Any) -> list[str]:
    """Extract normalized list of string URLs from sameAs field."""
    links: list[str] = []
    if not raw_same_as:
        return links
    if isinstance(raw_same_as, str):
        s = raw_same_as.strip()
        if s:
            links.append(s)
    elif isinstance(raw_same_as, list):
        for item in raw_same_as:
            if isinstance(item, str):
                s = item.strip()
                if s and s not in links:
                    links.append(s)
            elif isinstance(item, dict):
                sub_url = item.get("@id") or item.get("url")
                if sub_url and isinstance(sub_url, str):
                    s = sub_url.strip()
                    if s and s not in links:
                        links.append(s)
    return links


def _is_probable_uri_or_id(val: str, known_ids: Set[str]) -> bool:
    """Check if a string value represents a URI reference or known entity @id."""
    if not val or not isinstance(val, str):
        return False
    val_clean = val.strip()
    if val_clean in known_ids:
        return True
    if val_clean.startswith(("http://", "https://", "urn:", "#")):
        return True
    return False


def build_entity_graph(entities: list[dict]) -> tuple[dict[str, EntityNode], list[GraphEdge]]:
    """
    Build graph nodes and edges from flattened entity list.
    Returns (nodes_by_id, edges).

    Handles:
    - Direct flattened entities
    - Embedded @graph arrays
    - Nested inline entities with @type or @id
    - Synthetic node IDs for entities lacking explicit @id
    - Property edge extraction for Schema.org relationships
    """
    nodes_by_id: dict[str, EntityNode] = {}
    edges: list[GraphEdge] = []

    if not entities:
        return nodes_by_id, edges

    # Pass 1: Flatten and unpack any nested @graph blocks
    flattened_entities: list[dict] = []
    for item in entities:
        if not isinstance(item, dict):
            continue
        try:
            if "@graph" in item and isinstance(item["@graph"], list):
                base_source = item.get("_source_url") or item.get("source_url") or ""
                for sub_item in item["@graph"]:
                    if isinstance(sub_item, dict):
                        sub_copy = copy.deepcopy(sub_item)
                        if base_source and "_source_url" not in sub_copy:
                            sub_copy["_source_url"] = base_source
                        flattened_entities.append(sub_copy)
            else:
                flattened_entities.append(copy.deepcopy(item))
        except Exception:
            flattened_entities.append(copy.deepcopy(item))

    synthetic_counter = 1

    # Helper function to register an entity node
    def register_node(ent_dict: dict, default_source_url: str) -> str:
        nonlocal synthetic_counter
        source_url = str(ent_dict.get("_source_url") or ent_dict.get("source_url") or default_source_url or "").strip()
        raw_id = ent_dict.get("@id") or ent_dict.get("id") or ""
        raw_type = ent_dict.get("@type") or ent_dict.get("type") or ""
        type_str = _extract_type_str(raw_type)

        if raw_id and isinstance(raw_id, str):
            node_id = normalize_uri(raw_id, base_url=source_url)
        else:
            primary_type = type_str.split(",")[0].strip() or "Thing"
            node_id = f"{source_url}#{primary_type}#{synthetic_counter}"
            synthetic_counter += 1

        name = _extract_name_from_dict(ent_dict)
        same_as = _extract_same_as_list(ent_dict.get("sameAs") or ent_dict.get("same_as"))

        if node_id in nodes_by_id:
            existing = nodes_by_id[node_id]
            # Merge name if previously missing
            if not existing.name and name:
                existing.name = name
            # Upgrade generic Thing type if more specific type is provided
            if (not existing.type or existing.type == "Thing") and type_str and type_str != "Thing":
                existing.type = type_str
            # Merge same_as links
            for link in same_as:
                if link not in existing.same_as:
                    existing.same_as.append(link)
            # Merge non-empty properties
            for pk, pv in ent_dict.items():
                if pk not in existing.properties or not existing.properties[pk]:
                    existing.properties[pk] = pv
        else:
            nodes_by_id[node_id] = EntityNode(
                id=node_id,
                type=type_str,
                name=name,
                source_url=source_url,
                properties=copy.deepcopy(ent_dict),
                same_as=same_as,
            )

        return node_id

    # Pass 2: Register all top-level entity nodes
    for ent in flattened_entities:
        try:
            source_url = str(ent.get("_source_url") or ent.get("source_url") or "").strip()
            register_node(ent, source_url)
        except Exception:
            continue

    # Pass 3: Inspect nested entities to register inline nodes
    # E.g. {"publisher": {"@type": "Organization", "@id": "...", "name": "..."}}
    for ent in flattened_entities:
        source_url = str(ent.get("_source_url") or ent.get("source_url") or "").strip()
        for key, val in ent.items():
            if key in ("@context", "_source_url", "source_url"):
                continue
            if isinstance(val, dict):
                has_type = bool(val.get("@type") or val.get("type"))
                has_id = bool(val.get("@id") or val.get("id"))
                has_sub_props = len([k for k in val.keys() if not k.startswith("@")]) > 0
                # If it has @type or defined properties in addition to @id, register as inline node
                if has_type or (has_id and has_sub_props):
                    try:
                        register_node(val, source_url)
                    except Exception:
                        pass
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        has_type = bool(item.get("@type") or item.get("type"))
                        has_id = bool(item.get("@id") or item.get("id"))
                        has_sub_props = len([k for k in item.keys() if not k.startswith("@")]) > 0
                        if has_type or (has_id and has_sub_props):
                            try:
                                register_node(item, source_url)
                            except Exception:
                                pass

    known_ids = set(nodes_by_id.keys())
    seen_edges: Set[Tuple[str, str, str, str]] = set()

    # Pass 4: Extract relationship edges between nodes
    def extract_edges_from_val(source_id: str, prop_name: str, val: Any, source_url: str) -> None:
        if val is None:
            return

        # Case A: Dictionary containing @id or representing an entity
        if isinstance(val, dict):
            target_id = ""
            if "@id" in val and val["@id"]:
                target_id = normalize_uri(str(val["@id"]), base_url=source_url)
            elif "id" in val and val["id"] and isinstance(val["id"], str):
                target_id = normalize_uri(str(val["id"]), base_url=source_url)

            if target_id:
                edge_key = (source_id, target_id, prop_name, source_url)
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    edges.append(GraphEdge(
                        source_id=source_id,
                        target_id=target_id,
                        property_name=prop_name,
                        source_url=source_url
                    ))

            # Recursively inspect sub-properties for nested edges if it's a blank node
            if not target_id:
                for sub_k, sub_v in val.items():
                    if sub_k in REFERENCE_PROPERTIES:
                        extract_edges_from_val(source_id, sub_k, sub_v, source_url)

        # Case B: List of items
        elif isinstance(val, list):
            for sub_item in val:
                extract_edges_from_val(source_id, prop_name, sub_item, source_url)

        # Case C: String value in a known relationship property
        elif isinstance(val, str) and (prop_name in REFERENCE_PROPERTIES):
            clean_str = val.strip()
            if _is_probable_uri_or_id(clean_str, known_ids):
                target_id = normalize_uri(clean_str, base_url=source_url)
                if target_id:
                    edge_key = (source_id, target_id, prop_name, source_url)
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)
                        edges.append(GraphEdge(
                            source_id=source_id,
                            target_id=target_id,
                            property_name=prop_name,
                            source_url=source_url
                        ))

    for node_id, node in list(nodes_by_id.items()):
        source_url = node.source_url
        for prop_name, prop_val in node.properties.items():
            if prop_name in ("@id", "id", "@context", "_source_url", "source_url", "sameAs", "same_as"):
                continue
            try:
                extract_edges_from_val(node_id, prop_name, prop_val, source_url)
            except Exception:
                continue

    return nodes_by_id, edges


def find_broken_references(nodes: dict[str, EntityNode], edges: list[GraphEdge]) -> list[dict]:
    """
    Find edges pointing to @id URIs with no corresponding node definition.
    Returns a list of diagnostic issue dictionaries.
    """
    broken_list: list[dict] = []
    seen: Set[Tuple[str, str, str]] = set()

    for edge in edges:
        target = edge.target_id
        if not target:
            continue

        # Check direct resolution
        is_resolved = False
        if target in nodes:
            is_resolved = True
        elif target.rstrip("/") in nodes:
            is_resolved = True
        elif (target + "/") in nodes:
            is_resolved = True
        elif edge.source_url:
            # Try resolving relative fragment or URL against source_url
            resolved_uri = normalize_uri(target, base_url=edge.source_url)
            if resolved_uri in nodes or resolved_uri.rstrip("/") in nodes:
                is_resolved = True

        if not is_resolved:
            dedup_key = (edge.source_id, target, edge.property_name)
            if dedup_key not in seen:
                seen.add(dedup_key)
                src_node = nodes.get(edge.source_id)
                src_type = src_node.type if src_node else "Unknown"
                broken_list.append({
                    "source_id": edge.source_id,
                    "source_type": src_type,
                    "source_url": edge.source_url,
                    "property_name": edge.property_name,
                    "property": edge.property_name,
                    "target_id": target,
                    "severity": "Critical",
                    "message": (
                        f"Node '{edge.source_id}' ({src_type}) references @id '{target}' "
                        f"via property '{edge.property_name}', but no entity with that @id is defined."
                    ),
                })

    return broken_list


def find_orphan_nodes(nodes: dict[str, EntityNode], edges: list[GraphEdge]) -> list[dict]:
    """
    Find nodes that are never referenced as a target by any edge.
    Returns a list of orphan node diagnostic dictionaries.
    """
    referenced_target_ids: Set[str] = set()

    for edge in edges:
        # Exclude self-referencing loops
        if edge.source_id != edge.target_id and edge.target_id:
            referenced_target_ids.add(edge.target_id)
            clean_target = edge.target_id.rstrip("/")
            referenced_target_ids.add(clean_target)
            referenced_target_ids.add(clean_target + "/")

    outgoing_counts: collections.Counter[str] = collections.Counter()
    for edge in edges:
        outgoing_counts[edge.source_id] += 1

    orphans: list[dict] = []
    for node_id, node in nodes.items():
        clean_id = node_id.rstrip("/")
        is_referenced = (
            node_id in referenced_target_ids
            or clean_id in referenced_target_ids
            or (clean_id + "/") in referenced_target_ids
        )

        if not is_referenced:
            out_degree = outgoing_counts.get(node_id, 0)
            orphans.append({
                "id": node.id,
                "node_id": node.id,
                "type": node.type,
                "name": node.name,
                "source_url": node.source_url,
                "out_degree": out_degree,
                "is_isolated": (out_degree == 0),
                "severity": "Warning",
                "message": (
                    f"Entity node '{node.id}' ({node.type}) is declared on '{node.source_url}' "
                    f"but is never referenced as a target by any entity edge in the graph."
                ),
            })

    return orphans


def find_circular_references(nodes: dict[str, EntityNode], edges: list[GraphEdge]) -> list[list[str]]:
    """
    Detect circular @id resolution chains using DFS cycle detection.
    Returns a list of cycle chains, where each chain is a list of node IDs:
    e.g. ['https://example.com/#a', 'https://example.com/#b', 'https://example.com/#a']
    """
    # Build adjacency list with mapped canonical node IDs
    adj: dict[str, list[str]] = {nid: [] for nid in nodes}

    for edge in edges:
        src = edge.source_id
        tgt = edge.target_id

        if src not in adj:
            adj[src] = []

        # Map target to canonical node_id if present with slash variance
        resolved_tgt = tgt
        if tgt not in nodes:
            if tgt.rstrip("/") in nodes:
                resolved_tgt = tgt.rstrip("/")
            elif (tgt + "/") in nodes:
                resolved_tgt = tgt + "/"

        # Only connect edges to defined nodes
        if resolved_tgt in nodes:
            if resolved_tgt not in adj[src]:
                adj[src].append(resolved_tgt)

    cycles: list[list[str]] = []
    seen_canonical: Set[Tuple[str, ...]] = set()

    # 3-color DFS state: 0 = unvisited (white), 1 = visiting (gray), 2 = visited (black)
    state: dict[str, int] = {nid: 0 for nid in nodes}
    stack: list[str] = []
    stack_pos: dict[str, int] = {}

    def dfs(u: str) -> None:
        state[u] = 1
        stack_pos[u] = len(stack)
        stack.append(u)

        for v in adj.get(u, []):
            if state.get(v, 0) == 1:
                # Back-edge found: cycle detected!
                cycle_start = stack_pos[v]
                cycle_path = stack[cycle_start:] + [v]

                # Canonicalize representation to prevent duplicate rotations
                base = cycle_path[:-1]
                min_elem = min(base)
                min_idx = base.index(min_elem)
                canonical = tuple(base[min_idx:] + base[:min_idx])

                if canonical not in seen_canonical:
                    seen_canonical.add(canonical)
                    cycles.append(list(canonical) + [canonical[0]])

            elif state.get(v, 0) == 0:
                dfs(v)

        stack.pop()
        stack_pos.pop(u, None)
        state[u] = 2

    for node_id in sorted(nodes.keys()):
        if state[node_id] == 0:
            dfs(node_id)

    # Sort cycles by length then first node ID for deterministic output
    cycles.sort(key=lambda c: (len(c), c[0]))
    return cycles


def _extract_logo_str(logo_val: Any) -> str:
    """Extract clean string URL from a logo field."""
    if not logo_val:
        return ""
    if isinstance(logo_val, str):
        return logo_val.strip()
    if isinstance(logo_val, dict):
        for k in ("url", "contentUrl", "@id", "id"):
            sub = logo_val.get(k)
            if sub and isinstance(sub, str):
                return sub.strip()
    if isinstance(logo_val, list) and logo_val:
        return _extract_logo_str(logo_val[0])
    return ""


def check_publisher_consistency(entities: list[dict]) -> dict:
    """
    Check that all publisher references use consistent name, url, and logo values.
    Verifies cross-page alignment and reports any metadata drift.
    """
    publishers_by_id: dict[str, list[dict]] = collections.defaultdict(list)
    total_refs = 0

    for ent in entities:
        if not isinstance(ent, dict):
            continue
        source_url = str(ent.get("_source_url") or ent.get("source_url") or "").strip()

        # Check publisher field on the entity
        pub = ent.get("publisher")
        if pub:
            pub_items = pub if isinstance(pub, list) else [pub]
            for p in pub_items:
                if isinstance(p, dict):
                    pub_id = str(p.get("@id") or p.get("id") or "").strip()
                    name = _extract_name_from_dict(p)
                    url = str(p.get("url") or "").strip()
                    logo = _extract_logo_str(p.get("logo"))
                    key = pub_id or url or "unidentified_publisher"
                    publishers_by_id[key].append({
                        "name": name,
                        "url": url,
                        "logo": logo,
                        "source_url": source_url,
                        "declared_id": pub_id,
                        "is_org_definition": False,
                    })
                    total_refs += 1
                elif isinstance(p, str) and p.strip():
                    pub_id = p.strip()
                    publishers_by_id[pub_id].append({
                        "name": "",
                        "url": "",
                        "logo": "",
                        "source_url": source_url,
                        "declared_id": pub_id,
                        "is_org_definition": False,
                    })
                    total_refs += 1

        # Check if the entity itself is an Organization node
        ent_type = str(ent.get("@type") or ent.get("type") or "")
        if any(ot in ent_type for ot in ("Organization", "Corporation", "NewsMediaOrganization", "LocalBusiness")):
            pub_id = str(ent.get("@id") or ent.get("id") or "").strip()
            name = _extract_name_from_dict(ent)
            url = str(ent.get("url") or "").strip()
            logo = _extract_logo_str(ent.get("logo"))
            if pub_id or name or url:
                key = pub_id or (url or name or "unidentified_publisher")
                publishers_by_id[key].append({
                    "name": name,
                    "url": url,
                    "logo": logo,
                    "source_url": source_url,
                    "declared_id": pub_id,
                    "is_org_definition": True,
                })

    inconsistencies: list[dict] = []
    summary_by_pub: dict[str, dict] = {}

    for pub_key, records in publishers_by_id.items():
        # Collect non-empty unique values
        names = list(dict.fromkeys(r["name"] for r in records if r["name"]))
        urls = list(dict.fromkeys(r["url"] for r in records if r["url"]))
        logos = list(dict.fromkeys(r["logo"] for r in records if r["logo"]))
        sources = list(dict.fromkeys(r["source_url"] for r in records if r["source_url"]))

        drift_items: list[str] = []

        if len(names) > 1:
            drift_items.append("name")
            inconsistencies.append({
                "publisher_id": pub_key,
                "field": "name",
                "values": names,
                "conflicting_values": names,
                "sources": sources,
                "severity": "Warning",
                "message": f"Publisher '{pub_key}' has conflicting name values across pages: {names}",
            })

        if len(urls) > 1:
            # Check for substantial URL drift (ignoring trailing slash)
            norm_urls = list(dict.fromkeys(u.rstrip("/") for u in urls))
            if len(norm_urls) > 1:
                drift_items.append("url")
                inconsistencies.append({
                    "publisher_id": pub_key,
                    "field": "url",
                    "values": urls,
                    "conflicting_values": urls,
                    "sources": sources,
                    "severity": "Warning",
                    "message": f"Publisher '{pub_key}' has conflicting url values across pages: {urls}",
                })

        if len(logos) > 1:
            drift_items.append("logo")
            inconsistencies.append({
                "publisher_id": pub_key,
                "field": "logo",
                "values": logos,
                "conflicting_values": logos,
                "sources": sources,
                "severity": "Warning",
                "message": f"Publisher '{pub_key}' has conflicting logo values across pages: {logos}",
            })

        summary_by_pub[pub_key] = {
            "names": names,
            "urls": urls,
            "logos": logos,
            "occurrences": len(records),
            "sources": sources,
            "drift_fields": drift_items,
            "is_consistent": (len(drift_items) == 0),
            "consistent": (len(drift_items) == 0),
        }

    is_all_consistent = (len(inconsistencies) == 0)

    return {
        "consistent": is_all_consistent,
        "is_consistent": is_all_consistent,
        "total_publishers": len(publishers_by_id),
        "total_publisher_entities": len(publishers_by_id),
        "total_references_analyzed": total_refs,
        "publishers": summary_by_pub,
        "inconsistencies": inconsistencies,
        "warnings": [inc["message"] for inc in inconsistencies],
    }


def check_author_consistency(entities: list[dict]) -> dict:
    """
    Check that all author references with the same @id have consistent metadata.
    Compares author names, profile URLs, job titles, and disambiguation links.
    """
    authors_by_id: dict[str, list[dict]] = collections.defaultdict(list)
    total_author_refs = 0

    for ent in entities:
        if not isinstance(ent, dict):
            continue
        source_url = str(ent.get("_source_url") or ent.get("source_url") or "").strip()

        # Check author/creator fields on the entity
        for prop in ("author", "creator"):
            auth_val = ent.get(prop)
            if not auth_val:
                continue
            auth_items = auth_val if isinstance(auth_val, list) else [auth_val]
            for a in auth_items:
                if isinstance(a, dict):
                    auth_id = str(a.get("@id") or a.get("id") or "").strip()
                    if auth_id:
                        name = _extract_name_from_dict(a)
                        url = str(a.get("url") or "").strip()
                        job = str(a.get("jobTitle") or "").strip()
                        same_as = _extract_same_as_list(a.get("sameAs") or a.get("same_as"))
                        authors_by_id[auth_id].append({
                            "name": name,
                            "url": url,
                            "job_title": job,
                            "same_as": same_as,
                            "source_url": source_url,
                            "is_person_definition": False,
                        })
                        total_author_refs += 1
                elif isinstance(a, str) and a.strip():
                    auth_id = a.strip()
                    if _is_probable_uri_or_id(auth_id, set()):
                        authors_by_id[auth_id].append({
                            "name": "",
                            "url": "",
                            "job_title": "",
                            "same_as": [],
                            "source_url": source_url,
                            "is_person_definition": False,
                        })
                        total_author_refs += 1

        # Check if the entity itself is a Person node
        ent_type = str(ent.get("@type") or ent.get("type") or "")
        if "Person" in ent_type or "Author" in ent_type:
            auth_id = str(ent.get("@id") or ent.get("id") or "").strip()
            if auth_id:
                name = _extract_name_from_dict(ent)
                url = str(ent.get("url") or "").strip()
                job = str(ent.get("jobTitle") or "").strip()
                same_as = _extract_same_as_list(ent.get("sameAs") or ent.get("same_as"))
                authors_by_id[auth_id].append({
                    "name": name,
                    "url": url,
                    "job_title": job,
                    "same_as": same_as,
                    "source_url": source_url,
                    "is_person_definition": True,
                })

    inconsistencies: list[dict] = []
    summary_by_author: dict[str, dict] = {}

    for auth_id, records in authors_by_id.items():
        names = list(dict.fromkeys(r["name"] for r in records if r["name"]))
        urls = list(dict.fromkeys(r["url"] for r in records if r["url"]))
        jobs = list(dict.fromkeys(r["job_title"] for r in records if r["job_title"]))
        sources = list(dict.fromkeys(r["source_url"] for r in records if r["source_url"]))

        # Check sameAs links across references
        all_same_as: list[str] = []
        for r in records:
            for link in r["same_as"]:
                if link not in all_same_as:
                    all_same_as.append(link)

        drift_fields: list[str] = []

        if len(names) > 1:
            drift_fields.append("name")
            inconsistencies.append({
                "id": auth_id,
                "author_id": auth_id,
                "field": "name",
                "values": names,
                "conflicting_values": names,
                "sources": sources,
                "severity": "Warning",
                "message": f"Author @id '{auth_id}' has conflicting name values across pages: {names}",
            })

        if len(urls) > 1:
            norm_urls = list(dict.fromkeys(u.rstrip("/") for u in urls))
            if len(norm_urls) > 1:
                drift_fields.append("url")
                inconsistencies.append({
                    "id": auth_id,
                    "author_id": auth_id,
                    "field": "url",
                    "values": urls,
                    "conflicting_values": urls,
                    "sources": sources,
                    "severity": "Warning",
                    "message": f"Author @id '{auth_id}' has conflicting url values across pages: {urls}",
                })

        # Check for conflicting Wikidata / Wikipedia sameAs entries
        wikidata_links = [s for s in all_same_as if "wikidata.org" in s]
        if len(wikidata_links) > 1:
            drift_fields.append("sameAs:wikidata")
            inconsistencies.append({
                "id": auth_id,
                "author_id": auth_id,
                "field": "sameAs:wikidata",
                "values": wikidata_links,
                "conflicting_values": wikidata_links,
                "sources": sources,
                "severity": "Warning",
                "message": f"Author @id '{auth_id}' references multiple conflicting Wikidata entities: {wikidata_links}",
            })

        summary_by_author[auth_id] = {
            "names": names,
            "urls": urls,
            "job_titles": jobs,
            "same_as": all_same_as,
            "occurrences": len(records),
            "sources": sources,
            "drift_fields": drift_fields,
            "is_consistent": (len(drift_fields) == 0),
            "consistent": (len(drift_fields) == 0),
        }

    is_all_consistent = (len(inconsistencies) == 0)

    return {
        "consistent": is_all_consistent,
        "is_consistent": is_all_consistent,
        "total_unique_authors": len(authors_by_id),
        "total_references_analyzed": total_author_refs,
        "authors": summary_by_author,
        "inconsistencies": inconsistencies,
        "warnings": [inc["message"] for inc in inconsistencies],
    }


def audit_disambiguation(nodes: dict[str, EntityNode]) -> list[dict]:
    """
    Check entity nodes for missing sameAs links to Wikidata, Wikipedia, or social profiles.
    Key entity types that should have sameAs: Organization, Person, WebSite.
    Returns a list of entity audit findings with severity and recommendations.
    """
    findings: list[dict] = []

    for node_id, node in nodes.items():
        node_type = node.type
        # Check if node belongs to key disambiguation entity types
        is_target_entity = any(
            target_type in node_type
            for target_type in KEY_DISAMBIGUATION_TYPES
        )
        if not is_target_entity:
            continue

        same_as = node.same_as
        has_wikidata = any("wikidata.org" in s.lower() for s in same_as)
        has_wikipedia = any("wikipedia.org" in s.lower() for s in same_as)
        has_social = any(
            any(domain in s.lower() for domain in SOCIAL_DOMAINS)
            for s in same_as
        )

        missing_signals: list[str] = []
        if not has_wikidata:
            missing_signals.append("Wikidata")
        if not has_wikipedia:
            missing_signals.append("Wikipedia")
        if not has_social:
            missing_signals.append("Social Profiles")

        has_url = bool(node.properties.get("url") or (node.source_url and "http" in node.source_url))
        has_id = bool(node.id and not node.id.startswith("urn:uuid:"))

        # Flag issues if either no sameAs at all or lacking KG authority links
        if not same_as:
            findings.append({
                "id": node.id,
                "node_id": node.id,
                "type": node.type,
                "name": node.name or "Unnamed Entity",
                "source_url": node.source_url,
                "same_as_count": 0,
                "existing_same_as": [],
                "has_same_as": False,
                "has_url": has_url,
                "has_identifier": has_id,
                "has_wikidata": False,
                "has_wikipedia": False,
                "has_social": False,
                "missing_signals": missing_signals,
                "status": "missing_all",
                "severity": "Warning",
                "issue": (
                    f"Entity '{node.name or node.id}' ({node.type}) has zero sameAs disambiguation links."
                ),
                "recommendation": (
                    "Add sameAs links to Wikidata, Wikipedia, and official social profiles "
                    "to anchor entity authority in search knowledge graphs."
                ),
            })
        elif not (has_wikidata or has_wikipedia):
            findings.append({
                "id": node.id,
                "node_id": node.id,
                "type": node.type,
                "name": node.name or "Unnamed Entity",
                "source_url": node.source_url,
                "same_as_count": len(same_as),
                "existing_same_as": same_as,
                "has_same_as": True,
                "has_url": has_url,
                "has_identifier": has_id,
                "has_wikidata": False,
                "has_wikipedia": False,
                "has_social": has_social,
                "missing_signals": ["Wikidata", "Wikipedia"],
                "status": "missing_kg_authority",
                "severity": "Info",
                "issue": (
                    f"Entity '{node.name or node.id}' ({node.type}) has social profile links "
                    f"but lacks Wikidata or Wikipedia Knowledge Graph authority reconciliation."
                ),
                "recommendation": (
                    "Add a sameAs link pointing to the Wikidata entity URI (https://www.wikidata.org/wiki/Q...) "
                    "or Wikipedia article for authoritative entity reconciliation."
                ),
            })

    return findings


def render_graph_summary(
    nodes: dict[str, EntityNode],
    edges: list[GraphEdge],
    broken: Optional[list[dict]] = None,
    orphans: Optional[list[dict]] = None,
    cycles: Optional[list[list[str]]] = None
) -> None:
    """
    Render a high-contrast terminal summary of the knowledge graph and diagnostic integrity.
    Uses rich library when available, with fallback to standard plain text output.
    """
    broken = broken if broken is not None else find_broken_references(nodes, edges)
    orphans = orphans if orphans is not None else find_orphan_nodes(nodes, edges)
    cycles = cycles if cycles is not None else find_circular_references(nodes, edges)

    if RICH_AVAILABLE:
        console = Console()
        console.print("\n[bold cyan]=== SchemaGraph Integrity Summary ===[/bold cyan]\n")

        table = Table(title="Graph Topology Statistics", show_header=True, header_style="bold magenta")
        table.add_column("Metric", style="cyan", width=30)
        table.add_column("Count", justify="right", style="green", width=12)
        table.add_column("Status", style="bold", width=18)

        table.add_row("Total Resolved Nodes", str(len(nodes)), "[green]OK[/green]")
        table.add_row("Total Directed Edges", str(len(edges)), "[green]OK[/green]")

        broken_status = f"[red]{len(broken)} CRITICAL[/red]" if broken else "[green]0 (Passed)[/green]"
        table.add_row("Broken @id References", str(len(broken)), broken_status)

        orphan_status = f"[yellow]{len(orphans)} WARNING[/yellow]" if orphans else "[green]0 (Passed)[/green]"
        table.add_row("Orphan Entity Nodes", str(len(orphans)), orphan_status)

        cycle_status = f"[red]{len(cycles)} CRITICAL[/red]" if cycles else "[green]0 (Passed)[/green]"
        table.add_row("Circular Reference Loops", str(len(cycles)), cycle_status)

        console.print(table)

        if broken:
            console.print("\n[bold red]Broken @id References Detected:[/bold red]")
            for b in broken[:5]:
                console.print(f"  - [red]{b.get('property', b.get('property_name'))}[/red]: {b['source_id']} -> [bold]{b['target_id']}[/bold]")
            if len(broken) > 5:
                console.print(f"  ... and {len(broken) - 5} more")

        if cycles:
            console.print("\n[bold red]Circular Reference Loops Detected:[/bold red]")
            for c in cycles[:5]:
                console.print(f"  - Loop: {' -> '.join(c)}")
            if len(cycles) > 5:
                console.print(f"  ... and {len(cycles) - 5} more")

        console.print("")
    else:
        print("\n=== SchemaGraph Integrity Summary ===")
        print(f"Total Resolved Nodes:     {len(nodes)}")
        print(f"Total Directed Edges:     {len(edges)}")
        print(f"Broken @id References:    {len(broken)}")
        print(f"Orphan Entity Nodes:      {len(orphans)}")
        print(f"Circular Reference Loops: {len(cycles)}")
        if broken:
            print("\nBroken @id References:")
            for b in broken[:5]:
                print(f"  - {b.get('property', b.get('property_name'))}: {b['source_id']} -> {b['target_id']}")
        if cycles:
            print("\nCircular Reference Loops:")
            for c in cycles[:5]:
                print(f"  - Loop: {' -> '.join(c)}")
        print("=====================================\n")
