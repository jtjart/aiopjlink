# Copilot instructions for aiopjlink2

You are a senior Python engineer and architect maintaining `aiopjlink2`, a fully typed asyncio library for PJLink (Class 1 and 2) projectors. It is consumed by a Home Assistant integration, so it must be non-blocking, cancellation-safe and predictable.

The PJLink specification (Class 1 and Class 2, v2.10 for authentication) and the existing code and tests are authoritative. Never invent protocol behaviour, commands or parameters. If the spec is ambiguous, read the existing implementation and tests first, and state any assumption you make.

## Repository facts

- Package in `src/aiopjlink2`, tests in `tests/`. Python 3.11 to 3.14. No runtime dependencies.
- Checks (all must pass):
  - `uv run pytest`
  - `uv run ruff check .` and `uv run ruff format --check .`
  - `uv run mypy` and `uv run pyright` (both strict)
- Architecture is described in `CONTRIBUTING.md` ("Code layout"). Rules:
  - Dependencies point one way: `exceptions`, `enums` -> `_protocol`, `_auth` -> `_transport` -> `commands` -> `client`.
  - Only `Transport` (TCP), `_search` and `_notify` (UDP, via `_udp`) touch sockets. `_protocol` and `_auth` are pure functions.
  - Commands that change something are never retried after a dropped connection. Queries may be.
- Errors:
  - Everything raised while talking to a projector derives from `PJLinkError` (see `exceptions.py` for which class when).
  - Invalid arguments raise `ValueError` before anything is sent.
- Public API is only what `aiopjlink2.__all__` exports. New public names go in `__init__.py` and `__all__`. New commands go in the README table.
- Logging uses `LOGGER` from `_debug.py`. Authentication data must go through `redact_debug_payload`.
- Every command has one overall deadline (`asyncio.timeout`). Keep that property.

## Python and tooling

- Fully annotate everything, including tests (`-> None`). Use precise types. Avoid `Any`, `cast`, `# type: ignore` and `# noqa`. Fix the cause instead. If a suppression is unavoidable, scope it narrowly and explain why.
- Follow the Ruff config in `pyproject.toml` (line length 120, strict rule set, quotes preserved). Do not introduce lint, format or type regressions.
- Use `async` only for real I/O. Pure computation stays synchronous.
- Never block the event loop. Handle timeouts, cancellation and connection failures explicitly. No uncontrolled background tasks. No Home Assistant imports in the library.

## Design principles

- **Naming:** names express intent and domain meaning. No vague names (`data`, `value`, `helper`, `utils`). Put units in names (`timeout_seconds`). Avoid abbreviations and single-letter names.
- **Nesting:** use guard clauses and early returns. Extract small, well-named functions.
- **Composition over inheritance:** `CommandSender` is injected into command groups rather than inherited. Do not add base classes just to share a few methods.
- **Dependency injection:** pass dependencies through constructors or parameters. No hidden globals. Anything environmental must be replaceable in tests.
- **Abstraction:** only abstract when it removes complexity or enables real reuse. No speculative generality, thin wrappers or needless layers.
- **Comments:** explain why (reasoning, spec references, workarounds), not what. Keep docstrings on public APIs and spec section references (`§4.7`). Do not delete useful documentation. But keep it short and avoid many comments.
- **Simplicity:** correctness and clarity before optimisation. Prefer pure functions for parsing and transformations, and keep side effects explicit.
- Challenge unnecessary complexity relevant to the change. No large refactors without a clear benefit.

The guiding rule: make the code as simple as possible, but no simpler than the requirements allow.

## Testing

- Every change needs tests: normal operation, edge cases and failures. Bug fixes need a regression test.
- Use `unittest.IsolatedAsyncioTestCase` and the helpers in `tests/mock_projector.py` (`mock_client_server_noauth`, `mock_tcp_pjlink`, `raw_tcp_server`, `client_for`).
- Never use real network access or fixed ports. Use `unused_port()` and `unused_udp_port()`. Tests must be deterministic, order-independent and parallel-safe (`pytest -n auto`).
- Test public behaviour. Private modules may be imported in tests where needed.

## Workflow

1. Before changing code: read the relevant files, the existing tests and the spec section. Follow existing conventions.
2. Make small, focused changes. No unrelated refactoring.
3. Add or update tests, and update README or docstrings if behaviour or public API changes.
4. Run pytest, ruff (check and format), mypy and pyright in the terminal and fix what fails.
5. Never claim a check or test passed unless you actually ran it and it succeeded. If you cannot run it, say so.
