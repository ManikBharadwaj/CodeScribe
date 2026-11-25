# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

B.Tech CSE students, especially students learning programming and data structures, and developers organizing or reviewing their own Python and C++ source files.

## Product Purpose

CodeScribe provides account-owned workspaces for storing source files and a static analysis coach that helps users understand code structure, complexity, and possible improvements without running submitted code.

## Positioning

CodeScribe combines a code vault with Python AST analysis and C++ structural analysis, presenting findings as line-specific, hint-first learning feedback rather than a code-execution service.

## Operating Context

Users sign in, choose a workspace, create or upload a source file, edit it, and request static analysis. They can revisit or delete files and workspaces they own.

## Capabilities and Constraints

- The existing Flask application provides account registration, login/logout sessions, account-owned workspaces and files, and JSON API routes.
- Python analysis uses the built-in `ast` module; C++ analysis is structural and token-based rather than a full compiler AST.
- User code is not compiled or executed. Analysis must remain static and return structured diagnostics for invalid input.
- The primary editor languages are Python (`.py`) and C++ (`.cpp`). Existing `.h` and `.hpp` file compatibility and API contracts must be preserved.
- Workspace/file ownership checks and the existing authentication/session behavior must remain intact.
- The current file upload limit is 2 MB.
- The UI voice is direct, playful Gen-Z Hinglish for a student developer audience; technical findings, line numbers, and complexity notation remain unambiguous.

## Brand Commitments

The product name is CodeScribe. The existing identity uses the tagline “Tera Code, Meri Zimmedari” and a friendly, coder-buddy Hinglish voice.

## Evidence on Hand

- Flask routes and SQLAlchemy models: `app.py`, `models.py`.
- Python AST and C++ structural analyzer: `analyzer.py`.
- Existing API and auth/workspace regression contract: `smoke_test.py`.
- Existing UI copy and app interface: `templates/index.html`, `static/script.js`, `static/style.css`.
- No code-execution service or third-party OAuth capability is present.

## Product Principles

- Keep submitted code in account-owned workspaces.
- Teach through accurate static findings and hints, not full replacement solutions.
- Clearly distinguish measured metrics from estimates.
- Preserve safe, predictable behavior for invalid code and failed requests.
