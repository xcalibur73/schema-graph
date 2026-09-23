# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.1] - 2026-09-24
 
### Fixed
- Fixed false positive in sitemap page discovery: excluded `.xml` and `.xml.gz` URLs during XML parsing to prevent child sitemaps from being crawled as orphan page nodes.
- Hardened JSON-LD extractor against CDATA wrappers: enhanced regex sanitization to strip `<![CDATA[` and `/* <![CDATA[ */` comments without discarding valid enclosed JSON.

## [1.2.0] - 2026-09-20
 
### Added
- Real-world CMS JSON-LD comment and syntax resilience in `extractor.py`:
  - Strips JavaScript block comments (`/* ... */`) and line comments (`// ...`) without corrupting `http://` or `https://` URLs.
  - Automatically cleans trailing commas in arrays and objects across defensive extraction fallbacks.
  - Added unit test `test_commented_jsonld_with_trailing_commas`.

## [1.1.0] - 2026-09-20

### Added
- Defensive entity unescaping engine in `extractor.py` inspired by `extruct`:
  - Automatic unescaping of KSES-encoded JSON-LD script blocks containing `&quot;`, `&#039;`, or `&amp;`.
  - Recursive property string cleaning to resolve double-escaped entities like `&amp;#038;` into clean unescaped text.
  - Comprehensive unit tests covering WordPress KSES entity mangling and double-escaped ampersand resolution.

## [1.0.0] - 2026-09-19

### Added
- Initial release of schema-graph: Cross-page entity and knowledge graph integrity tracer for Schema.org JSON-LD.
- CLI entry point with `--output` (terminal, markdown, json) and `--version` flags.
- Standard PEP 621 packaging via `pyproject.toml`.
- GitHub Actions CI matrix workflow for Python 3.10, 3.11, and 3.12.
- Comprehensive automated unit test suite.
- Integration endpoints for the WebAudits.pro technical audit platform.

### Hardened
- Cross-platform Windows terminal encoding safety (`_safe_str` Unicode sanitization).
- Universal test discovery path resilience.
