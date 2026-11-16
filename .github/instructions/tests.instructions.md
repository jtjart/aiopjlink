---
applyTo: "tests/**/*.py"
---
- Use `unittest.IsolatedAsyncioTestCase` and the helpers in `mock_projector.py`.
- Never use real network access or fixed ports; use `unused_port()` / `unused_udp_port()`.
- Fully annotate tests (mypy and pyright strict).
