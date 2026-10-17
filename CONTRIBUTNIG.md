# Contributing

Pull requests with tests are welcome.

## Development setup

### Dev container (recommended)

The repository ships a [dev container](.devcontainer/devcontainer.json) that sets up everything for you:

* Python 3.14 and [uv](https://docs.astral.sh/uv/)
* all dependencies (`uv sync --group dev`)
* the pre-commit hooks
* VS Code with Python, Pylance, Ruff, mypy and TOML/YAML support, format-on-save with Ruff, and pytest wired into the test explorer

You need [Docker](https://docs.docker.com/get-docker/) (or a compatible runtime) and VS Code with the
[Dev Containers](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers) extension.
Open the repository and choose **Reopen in Container**. GitHub Codespaces works the same way.

### Without the dev container

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```bash
uv sync --group dev          # creates .venv; uv downloads a matching Python if needed (3.11+)
uv run pre-commit install    # optional: run the checks on every commit
```

## Checks

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pyright
```

The pre-commit hooks run the same tools, including the full test suite, so a commit takes a moment.
CI runs them too, with the tests on Linux, macOS and Windows with Python 3.11–3.14.

The mock projector in the tests listens on `127.0.0.1:4352`: do not run the tests in parallel or while a real PJLink service uses that port.

## Code layout

Modules are grouped by feature, not by spec chapter. Each module docstring lists the spec sections it implements.
Modules starting with `_` are internal; only the names in `aiopjlink.__all__` are public API.

```
src/aiopjlink/
├── __init__.py       public API (everything in __all__)
├── client.py         PJLink: the entry point, wires the command groups onto a Transport
├── _transport.py     Transport: connection, lock, deadline, transmit()
├── _protocol.py      command / response line format (§2)
├── _auth.py          opening handshake and password hashing (§5)
├── _debug.py         logger and redaction of authentication data
├── exceptions.py     PJLinkException and its subclasses
├── enums.py          PJClass
├── projector.py      backwards-compatible re-exports of the old module
└── commands/         one module per feature (spec chapter 4)
    ├── base.py       CommandGroup
    ├── power.py      §4.1, §4.2
    ├── sources.py    §4.3, §4.4, §4.9, §4.17 - §4.19
    ├── mute.py       §4.5, §4.6
    ├── errors.py     §4.7
    ├── lamp.py       §4.8, §4.21
    ├── filter.py     §4.20, §4.22
    ├── freeze.py     §4.25, §4.26
    ├── volume.py     §4.23, §4.24
    └── information.py  §4.10 - §4.16
```

Rules the code follows:

* Dependencies point one way: `exceptions`, `enums` → `_protocol`, `_auth` → `_transport` → `commands` → `client`.
* Only `Transport` touches sockets. `_protocol` and `_auth` are pure functions.
* Everything raised while talking to a projector is a `PJLinkException` (see `exceptions.py` for which one when). Invalid arguments are a `ValueError`, raised before anything is sent.
* Commands that change something are never repeated after a dropped connection; queries may be.
* New public names must be exported in `__init__.py` and `projector.py` (`tests/test_compat.py` checks this), and new commands added to the README table.

## Releases

The version comes from git tags (hatch-vcs). Publishing a GitHub release tagged `vX.Y.Z` builds the package and publishes it to PyPI; the workflow fails if the tag and the built version differ.
