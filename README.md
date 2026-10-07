<div align="center">

# aiopjlink2

A modern Python asyncio PJLink library (Class 1 and Class 2).
This is a fork from HEInventions/aiopjlink and Kwull/aiopjlink.

[![PyPI](https://img.shields.io/pypi/v/aiopjlink2?logo=python&logoColor=%23cccccc)](https://pypi.org/project/aiopjlink2)
![PyPI - License](https://img.shields.io/pypi/l/aiopjlink2)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/aiopjlink2)

![PyPI - Downloads](https://img.shields.io/pypi/dm/aiopjlink2)
![GitHub repo size](https://img.shields.io/github/repo-size/jtjart/aiopjlink)

</div>

## What is PJLink?

Many projectors with an RJ45 connection can be controlled using [PJLink](https://pjlink.jbmia.or.jp/english/).

PJLink is a communication protocol and unified standard for operating and controlling data projectors over `TCP/IP`, regardless of manufacturer.

It supports both [Class 1](https://pjlink.jbmia.or.jp/english/data/5-1_PJLink_eng_20131210.pdf) commands and [Class 2](https://pjlink.jbmia.or.jp/english/data_cl2/PJLink_5-1.pdf) notifications and extensions.

* Class 1 covers basic commands such as power on/off, input selection, and volume control.
* Class 2 adds extended functionality such as lens control and projector-specific notifications.

## What is aiopjlink2?

`aiopjlink2` is a typed, asyncio-based Python library for controlling PJLink-compatible projectors.

The library keeps the ergonomic API of the earlier forks while modernizing the project around the current Python tooling ecosystem:

* ✅ Modern asyncio API with high-level command groups
* ✅ Fully typed public API (`py.typed` package)
* ✅ Cross-platform CI for Python 3.11–3.13
* ✅ Development container and `uv`-based tooling
* ✅ One connection per command, with no connection manager to keep around

## Installation

```bash
pip install aiopjlink2
```

## Usage

Each PJLink command opens a short-lived TCP connection, sends the request, and closes the socket again. You create one `PJLink` instance and then call the high-level API on it.

```python
import asyncio

from aiopjlink import PJLink


async def main() -> None:
    link = PJLink(address="192.168.1.120", password="secret")

    await link.power.turn_on()
    await asyncio.sleep(5)
    print("errors =", await link.errors.query())
    await asyncio.sleep(5)
    await link.power.turn_off()


asyncio.run(main())
```

The library exposes command groups such as `power`, `sources`, `mute`, `lamps`, `errors`, and `info` on the `PJLink` object.

## Project layout

```
src/aiopjlink/
├── __init__.py       public API (everything in __all__)
├── client.py         PJLink: the entry point, wires the command groups onto a Transport
├── _transport.py     Transport: connection, lock, transmit()
├── exceptions.py     PJLinkException and its subclasses
├── enums.py          PJClass
├── _protocol.py      command / response line format (spec §2)
├── _auth.py          opening handshake and password hashing (spec §5)
├── _debug.py         shared logging helpers for debug output
├── projector.py      backwards-compatible re-exports of the old module
└── commands/         one module per feature, spec chapter 4
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

Modules are grouped by feature, not by spec chapter, so related commands (for example `LAMP` and `RLMP`) live together. Each module docstring lists the spec sections it implements. Modules starting with an underscore are internal; only the names exported from `aiopjlink` are public API.

## Development

The project uses [uv](https://docs.astral.sh/uv/) for dependency management and development tasks, with Hatchling for packaging and Ruff, Mypy, and Pyright for quality checks.

```bash
uv sync --group dev

uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pyright
```

The repository also includes a [dev container](.devcontainer/devcontainer.json) configured for Python 3.13 and the `uv` toolchain, along with recommended VS Code extensions for Python, Pylance, Ruff, and TOML support.

Enable PJLink traffic logging via Python's standard `logging` config. The library emits debug messages through the `aiopjlink` logger, so you can route them to the console or a file as needed.

```python
import logging

logging.basicConfig(level=logging.DEBUG)
```

## Project automation

This repository includes GitHub Actions workflows for:

* linting and static analysis
* tests on Linux, macOS, and Windows
* Python 3.11, 3.12, and 3.13 coverage
* build verification and PyPI release publishing

The package is published from the `src` layout and is versioned via git metadata.

## Roadmap

Pull requests with test cases are welcome. There are still some things to finish, including:

* [ ] Search Protocol (§3.2)
* [ ] Status Notification Protocol (§3.3)
