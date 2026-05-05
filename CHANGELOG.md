# Changelog

All notable changes to this project are documented in this file.

## [0.2.0] - 2026-05-05

### Added
- Municipal holiday selector integrated in the main filters.
- Approved compensations are now injected as holidays and count as non-business days.
- Bidirectional sync between calendar selection and request form date fields.
- Premium dashboard shell with sidebar navigation and focused calendar hero.
- Packaging support with pyproject-based editable install.
- CI workflow for automated install and test execution on Python 3.11.

### Changed
- Streamlit deprecated width usage replaced with current APIs.
- Login and management UI refined for clearer actions and visual hierarchy.
- Package scope restricted to vacation_app to avoid unintended package discovery.

### Fixed
- Data mutation paths now handle DataStoreError and show user-safe feedback.
- Storage schema cache now keys on backend/data source to avoid stale schema state.
- Relational storage round-trip consistency for approval metadata validated by tests.
