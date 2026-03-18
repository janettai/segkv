# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Ruff and mypy configuration in pyproject.toml
- GitHub Actions CI/CD workflows for linting, type checking, testing, and publishing

## [0.1.0] - 2025-01-09

### Added
- Initial release of LSDB (Log-Structured Database)
- Core `LSDB` class with key-value storage operations
- Append-only write operations with JSON serialization
- Hash index for O(1) key lookups
- Automatic segment rotation when size threshold is reached
- Background compaction to merge segments and remove deleted entries
- Crash recovery through index rebuilding from segment files
- Thread-safe operations with proper locking mechanisms
- `IndexEntry` dataclass for index management
- Configurable segment size and compaction threshold
- Full type annotations with PEP 561 py.typed marker
- MIT license

[Unreleased]: https://github.com/nanaadjeimanu/lsdb/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/nanaadjeimanu/lsdb/releases/tag/v0.1.0
