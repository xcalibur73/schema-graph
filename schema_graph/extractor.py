"""
SchemaGraph: JSON-LD Extractor Module.

Author: @xcalibur73
License: MIT

This module handles:
1. Fetching HTML from URLs via requests library with browser-like User-Agent.
2. Parsing sitemap.xml files (including sitemap indexes and gzipped files) to discover URLs.
3. Extracting all <script type="application/ld+json"> blocks from HTML, including nested @graph arrays.
4. Normalizing @id URIs (trailing slash normalization, protocol normalization, fragment resolution).
5. Flattening all entities from JSON-LD blocks into individual entity dicts with synthetic @id generation.
"""

import copy
import gzip
import html as html_lib
import json
import os
import re
import sys
import urllib.parse
from typing import Any, Dict, List, Optional, Set
import xml.etree.ElementTree as ET

def _defensive_unescape_json_str(raw: str) -> str:
    """Defensively unescapes HTML entities in raw JSON strings to rescue KSES-mangled blocks."""
    if "&quot;" in raw or "&#039;" in raw or "&apos;" in raw or "&#34;" in raw or "&amp;" in raw:
        return html_lib.unescape(raw)
    return raw

def _clean_entity_strings(obj: Any) -> Any:
    """Recursively unescapes HTML entities in extracted string properties (e.g. &amp;#038; -> &)."""
    if isinstance(obj, str):
        # Unescape twice to resolve double-encoded entities like &amp;#038; -> &#038; -> &
        first = html_lib.unescape(obj)
        second = html_lib.unescape(first)
        return second
    elif isinstance(obj, list):
        return [_clean_entity_strings(item) for item in obj]
    elif isinstance(obj, dict):
        return {k: _clean_entity_strings(v) for k, v in obj.items()}
    return obj

import requests
from bs4 import BeautifulSoup

# Fallback-safe rich console logging
try:
    from rich.console import Console
    _console = Console(stderr=True)
    def _log_warning(message: str) -> None:
        _console.print(f"[yellow]Warning:[/yellow] {message}")
    def _log_error(message: str) -> None:
        _console.print(f"[red]Error:[/red] {message}")
except ImportError:
    def _log_warning(message: str) -> None:
        sys.stderr.write(f"Warning: {message}\n")
    def _log_error(message: str) -> None:
        sys.stderr.write(f"Error: {message}\n")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)


def fetch_page_html(url: str, timeout: int = 15) -> str:
    """Fetch HTML content from a URL with browser-like User-Agent.

    Args:
        url: The web page URL to fetch.
        timeout: Request timeout in seconds (default: 15).

    Returns:
        The fetched HTML response body as a string.

    Raises:
        requests.RequestException: If the HTTP request fails or returns an error status.
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
    }
    try:
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
        if response.encoding is None or response.encoding.lower() == "iso-8859-1":
            response.encoding = response.apparent_encoding or "utf-8"
        return response.text
    except requests.RequestException as exc:
        _log_error(f"Failed to fetch HTML from {url}: {exc}")
        raise


def normalize_id(uri: str, base_url: str = "") -> str:
    """Normalize an @id URI: strip trailing slashes, force https, resolve relative URIs.

    Args:
        uri: The URI to normalize (can be relative, fragment, or absolute).
        base_url: Optional document base URL for resolving relative URIs.

    Returns:
        The normalized canonical URI string.
    """
    if not uri:
        return ""
    uri = uri.strip()
    if not uri:
        return ""

    # Resolve relative URI against base_url
    if base_url:
        base_url = base_url.strip()
        if base_url.startswith("http://"):
            base_url = "https://" + base_url[7:]
        uri = urllib.parse.urljoin(base_url, uri)

    # Protocol-relative URI
    if uri.startswith("//"):
        uri = "https:" + uri

    parsed = urllib.parse.urlsplit(uri)
    original_scheme = parsed.scheme.lower() if parsed.scheme else ""
    scheme = "https" if original_scheme == "http" else original_scheme

    # Non-HTTP schemes (e.g. urn:uuid, mailto) retain their scheme and stripped slash
    if scheme not in ("http", "https"):
        return uri.rstrip("/")

    netloc = parsed.netloc.lower()
    # Strip standard default ports
    if netloc.endswith(":80"):
        netloc = netloc[:-3]
    elif netloc.endswith(":443"):
        netloc = netloc[:-4]

    # Normalize multiple contiguous path slashes
    path = re.sub(r"/{2,}", "/", parsed.path)
    fragment = parsed.fragment.rstrip("/")
    query = parsed.query

    # Trailing slash normalization
    if path.endswith("/") and len(path) > 1:
        path = path.rstrip("/")
    elif path == "/" and not fragment:
        path = ""
    elif not path and fragment:
        path = "/"

    reconstructed = urllib.parse.urlunsplit((scheme, netloc, path, query, fragment))
    if reconstructed.endswith("/") and not fragment:
        return reconstructed.rstrip("/")
    return reconstructed


def parse_sitemap_urls(
    sitemap_url: str,
    timeout: int = 15,
    max_urls: int = 50000,
    recurse: bool = True,
    _visited: Optional[set[str]] = None,
) -> list[str]:
    """Parse a sitemap.xml and return all <loc> URLs.

    Handles standard <urlset> sitemaps, nested <sitemapindex> hierarchies,
    gzipped .xml.gz archives, and unescaped ampersands in URLs.

    Args:
        sitemap_url: Web URL (http/https) or local file path to sitemap.
        timeout: Network timeout in seconds.
        max_urls: Maximum number of URLs to discover.
        recurse: Whether to recurse into child sitemaps if a sitemapindex is detected.
        _visited: Internal set to guard against circular sitemap references.

    Returns:
        List of discovered URL strings.
    """
    if _visited is None:
        _visited = set()

    normalized_url = sitemap_url.strip()
    if normalized_url in _visited:
        return []
    _visited.add(normalized_url)

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/xml,text/xml,*/*;q=0.8",
    }
    content: Optional[bytes] = None

    if normalized_url.startswith(("http://", "https://")):
        try:
            resp = requests.get(normalized_url, headers=headers, timeout=timeout, allow_redirects=True)
            resp.raise_for_status()
            content = resp.content
        except requests.RequestException as exc:
            _log_error(f"Failed to fetch sitemap from {normalized_url}: {exc}")
            return []
    elif normalized_url.startswith("file://"):
        file_path = normalized_url[7:]
        if sys.platform == "win32" and file_path.startswith("/"):
            file_path = file_path.lstrip("/")
        try:
            with open(file_path, "rb") as f:
                content = f.read()
        except OSError as exc:
            _log_error(f"Failed to read local sitemap {normalized_url}: {exc}")
            return []
    elif os.path.exists(normalized_url):
        try:
            with open(normalized_url, "rb") as f:
                content = f.read()
        except OSError as exc:
            _log_error(f"Failed to read local sitemap {normalized_url}: {exc}")
            return []
    else:
        _log_error(f"Invalid sitemap URL or file path: {normalized_url}")
        return []

    if not content:
        return []

    # Handle gzip compressed sitemaps
    if content.startswith(b"\x1f\x8b") or normalized_url.endswith(".gz"):
        try:
            content = gzip.decompress(content)
        except Exception as exc:
            _log_error(f"Failed to decompress gzipped sitemap {normalized_url}: {exc}")
            return []

    # Parse XML with fallback for unescaped ampersands
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        try:
            cleaned = re.sub(rb"&(?!amp;|lt;|gt;|apos;|quot;|#\d+;|#x[0-9a-fA-F]+;)", b"&amp;", content)
            root = ET.fromstring(cleaned)
        except ET.ParseError as exc:
            _log_error(f"XML parse error in sitemap {normalized_url}: {exc}")
            return []

    root_tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag

    discovered_urls: list[str] = []
    seen: set[str] = set()

    if root_tag == "sitemapindex":
        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag == "loc" and elem.text:
                child_loc = elem.text.strip()
                if not child_loc:
                    continue
                if recurse:
                    child_urls = parse_sitemap_urls(
                        child_loc,
                        timeout=timeout,
                        max_urls=max_urls,
                        recurse=True,
                        _visited=_visited,
                    )
                    for u in child_urls:
                        if u not in seen:
                            seen.add(u)
                            discovered_urls.append(u)
                            if len(discovered_urls) >= max_urls:
                                return discovered_urls
                else:
                    if child_loc not in seen:
                        seen.add(child_loc)
                        discovered_urls.append(child_loc)
                        if len(discovered_urls) >= max_urls:
                            return discovered_urls
    else:
        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag == "loc" and elem.text:
                loc = elem.text.strip()
                if loc and loc not in seen:
                    seen.add(loc)
                    discovered_urls.append(loc)
                    if len(discovered_urls) >= max_urls:
                        return discovered_urls

    return discovered_urls


def _unpack_graph(data: Any, default_context: Any = None) -> list[dict]:
    """Unpack @graph arrays and extract all dictionary entities."""
    results: list[dict] = []
    if isinstance(data, list):
        for item in data:
            results.extend(_unpack_graph(item, default_context))
    elif isinstance(data, dict):
        context = data.get("@context", default_context)
        if "@graph" in data:
            graph_data = data["@graph"]
            parent_props = {k: v for k, v in data.items() if k not in ("@graph", "@context")}
            if parent_props.get("@type"):
                parent_entity = dict(data)
                del parent_entity["@graph"]
                if context and "@context" not in parent_entity:
                    parent_entity["@context"] = context
                results.append(parent_entity)
            if isinstance(graph_data, list):
                for item in graph_data:
                    results.extend(_unpack_graph(item, context))
            elif isinstance(graph_data, dict):
                results.extend(_unpack_graph(graph_data, context))
        else:
            entity = dict(data)
            if context and "@context" not in entity:
                entity["@context"] = context
            results.append(entity)
    return results


def extract_jsonld_blocks(html: str) -> list[dict]:
    """Extract all JSON-LD blocks from HTML string. Handles @graph arrays.

    Args:
        html: Raw HTML string of the target page.

    Returns:
        List of JSON-LD entity dictionaries.
    """
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    blocks: list[dict] = []

    for tag in soup.find_all("script"):
        t = tag.get("type", "")
        if not t or "application/ld+json" not in t.lower():
            continue

        raw = tag.string or tag.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue

        # Strip HTML comments if present
        if raw.startswith("<!--") and raw.endswith("-->"):
            raw = raw[4:-3].strip()

        # Strip CDATA tags
        raw = re.sub(r"^//\s*<!\[CDATA\[", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"^//\s*\]\]>", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"/\*\s*<!\[CDATA\[\s*\*/", "", raw)
        raw = re.sub(r"/\*\s*\]\]>\s*\*/", "", raw)
        raw = raw.strip()

        parsed = None
        # 1. Attempt direct JSON parsing
        try:
            parsed = json.loads(raw, strict=False)
        except json.JSONDecodeError:
            pass

        # 2. Defensive HTML entity unescaping (extruct-inspired KSES rescue)
        if parsed is None:
            unescaped_raw = _defensive_unescape_json_str(raw)
            try:
                parsed = json.loads(unescaped_raw, strict=False)
            except json.JSONDecodeError:
                try:
                    # Strip block comments and single-line comments not part of URLs
                    cleaned = re.sub(r"/\*.*?\*/", "", unescaped_raw, flags=re.DOTALL)
                    cleaned = re.sub(r"(?<!:)//[^\r\n]*", "", cleaned)
                    cleaned = re.sub(r",\s*([\]}])", r"\1", cleaned)
                    parsed = json.loads(cleaned, strict=False)
                except json.JSONDecodeError as exc:
                    _log_warning(f"Failed to parse JSON-LD script content: {exc}")
                    continue

        # Clean entity strings to normalize any internal double-escaped entities
        parsed = _clean_entity_strings(parsed)

        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    blocks.append(item)
        elif isinstance(parsed, dict):
            blocks.append(parsed)

    return blocks


def _is_entity_def(obj: dict) -> bool:
    """Check if a dictionary represents an entity definition rather than a pure reference."""
    if "@type" in obj:
        return True
    if "@id" in obj:
        non_id_keys = {k for k in obj.keys() if k not in ("@id", "@context", "_source_url")}
        if non_id_keys:
            return True
    return False


def flatten_entities(jsonld_blocks: list[dict], source_url: str) -> list[dict]:
    """Flatten all entities from JSON-LD blocks into individual entity dicts.
    Each entity gets '_source_url' metadata and a synthetic @id if missing.

    Handles nested entities, multi-type definitions, and circular reference chains.
    Entities without an explicit @id receive a deterministic synthetic @id in the form:
    {source_url}#{@type}#{index}

    Args:
        jsonld_blocks: List of JSON-LD dictionaries extracted from HTML.
        source_url: The source URL where the entities were located.

    Returns:
        List of flattened entity dictionaries.
    """
    if not jsonld_blocks:
        return []

    norm_source_url = normalize_id(source_url)
    type_counters: dict[str, int] = {}
    entity_id_map: dict[int, str] = {}
    discovered_order: list[tuple[dict, Any]] = []
    visited_discovery: set[int] = set()

    def _get_type_str(entity: dict) -> str:
        raw_type = entity.get("@type", "Thing")
        if isinstance(raw_type, list):
            parts = [str(t).strip() for t in raw_type if str(t).strip()]
            return "_".join(parts) if parts else "Thing"
        elif isinstance(raw_type, str) and raw_type.strip():
            return raw_type.strip()
        return "Thing"

    def _assign_id(entity: dict) -> str:
        if id(entity) in entity_id_map:
            return entity_id_map[id(entity)]
        raw_id = entity.get("@id")
        if raw_id and isinstance(raw_id, str) and raw_id.strip():
            resolved = normalize_id(raw_id, source_url)
        else:
            t_str = _get_type_str(entity)
            type_counters[t_str] = type_counters.get(t_str, 0) + 1
            idx = type_counters[t_str]
            resolved = f"{norm_source_url}#{t_str}#{idx}"
        entity_id_map[id(entity)] = resolved
        return resolved

    def _discover(obj: Any, is_root: bool = False, default_context: Any = None) -> None:
        if not isinstance(obj, dict):
            if isinstance(obj, list):
                for item in obj:
                    _discover(item, is_root=False, default_context=default_context)
            return

        obj_id = id(obj)
        if obj_id in visited_discovery:
            return

        context = obj.get("@context", default_context)
        if "@graph" in obj:
            visited_discovery.add(obj_id)
            graph_data = obj["@graph"]
            parent_props = {k: v for k, v in obj.items() if k not in ("@graph", "@context")}
            if parent_props.get("@type"):
                _assign_id(obj)
                discovered_order.append((obj, context))

            if isinstance(graph_data, list):
                for item in graph_data:
                    _discover(item, is_root=True, default_context=context)
            elif isinstance(graph_data, dict):
                _discover(graph_data, is_root=True, default_context=context)
            return

        is_entity = is_root or _is_entity_def(obj)
        if is_entity:
            visited_discovery.add(obj_id)
            _assign_id(obj)
            discovered_order.append((obj, context))

        for k, v in obj.items():
            if k in ("@context", "_source_url"):
                continue
            _discover(v, is_root=False, default_context=context)

    for block in jsonld_blocks:
        _discover(block, is_root=True)

    flattened: list[dict] = []
    for entity, context in discovered_order:
        ent_copy: dict[str, Any] = {
            "_source_url": source_url,
            "@id": entity_id_map[id(entity)],
        }
        if context:
            ent_copy["@context"] = context

        for k, v in entity.items():
            if k in ("@id", "_source_url", "@graph"):
                continue
            if k == "@context":
                ent_copy["@context"] = v
                continue

            def _transform_val(val: Any) -> Any:
                if isinstance(val, dict):
                    if id(val) in entity_id_map:
                        return {"@id": entity_id_map[id(val)]}
                    elif "@id" in val:
                        ref_copy = dict(val)
                        ref_copy["@id"] = normalize_id(str(ref_copy["@id"]), source_url)
                        return ref_copy
                    else:
                        return {pk: _transform_val(pv) for pk, pv in val.items()}
                elif isinstance(val, list):
                    return [_transform_val(item) for item in val]
                else:
                    return val

            ent_copy[k] = _transform_val(v)

        flattened.append(ent_copy)

    return flattened
