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
* ✅ Cross-platform CI for Python 3.11–3.14
* ✅ Development container and `uv`-based tooling
* ✅ One connection reused for follow-up commands, opened lazily and replaced transparently when the projector drops it
* ✅ One overall deadline per command, whatever stage it is in
* ✅ A per-command connection mode for projectors that cannot handle anything else

## Installation

```bash
pip install aiopjlink2
```

## Usage

You create one `PJLink` instance and call the high-level API on it. The first command connects, the ones after it reuse the connection, and `close()` (or leaving the `async with` block) lets go of it.

```python
import asyncio

from aiopjlink import PJLink


async def main() -> None:
    async with PJLink(address="192.168.1.120", password="secret") as link:
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
├── _transport.py     Transport: connection, lock, deadline, transmit()
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

## Connection handling

```python
PJLink(address)  # default: reuse the connection, release it after 25 s idle
PJLink(address, idle_timeout=2)  # one connection per burst of commands (e.g. per poll)
PJLink(address, persistent=False)  # one connection per command
```

Pick the mildest mode that works with your projector. For a poll of three commands every ten seconds:

| Mode | Connections and authentication | Use it for |
|---|---|---|
| Default (`persistent=True`, `idle_timeout=25`) | One connection is reused across polls; authentication is sent once per connection. | Long-running programs, such as an integration polling every few seconds. |
| `idle_timeout=2` | One connection per poll; it closes two seconds after the last command. Authentication is sent once per poll. | Releasing the projector between polls while reusing the connection within each poll. |
| `persistent=False` | Three connections per poll, one per command; authentication is sent for every command. | Projectors that do not handle multiple commands on one connection, or that must stay free for other controllers. |

With `persistent=True`, `close()` releases the kept connection. With `persistent=False`, each connection is closed before its command completes, so `close()` has nothing to release.

The spec allows both. It lets a controller send any number of commands on one connection as long as each follows the previous answer within 30 seconds (§5.3), and it tells the controller to disconnect once it is done (§5.4). A connection can therefore never be "permanent": the projector drops one that stays silent for 30 seconds (§5.4, §6), and the number of controllers a projector accepts at once depends on the model (§6). So with `persistent=True`:

* **Reconnecting is automatic.** A connection that is gone is replaced by the next command. A projector that hangs up after every answer works too, it just gains nothing from reuse.
* **A failed command never poisons the next one.** After a timeout, a cancelled command or anything unexpected, the connection is dropped, so a late answer can not be mistaken for the answer to the next command.
* **Queries are repeated once** if the kept connection turns out to be dead. Commands that change something (power, input, volume, ...) are not: the projector may have carried them out before it hung up, so you get `PJLinkConnectionClosed` and decide.
* **Idle connections are released** after 25 seconds, so a projector that accepts a single controller is free for others (its own web interface, a remote) when you are not talking to it.

Every command has one deadline, `timeout` (default 4 s), that covers connecting, the greeting, sending and waiting for the answer. A command on an unreachable or silent projector therefore fails after `timeout`, not a multiple of it. Commands share one `PJLink` object in turn, so a command that has to wait behind others waits for each of them, and each is bound by `timeout`. With `persistent=False`, closing the socket after a successful command may take up to one more second.

## Error handling

Everything the library raises while talking to a projector derives from `PJLinkException`:

```
PJLinkException
├── PJLinkConnectionError               projector unreachable or not talking
│   ├── PJLinkNoConnection              refused / no greeting / no response in time
│   └── PJLinkConnectionClosed          closed or reset by the projector
├── PJLinkPassword                      password missing or wrong
├── PJLinkProtocolError                 what the projector sent is not valid PJLink
├── PJLinkUnexpectedResponseParameter   valid PJLink, but a value the library does not know
└── PJLinkProjectorError                the projector answered with an error
    ├── PJLinkNotSupported      ERR1    not supported (see `err.command` and the message: "no lamp", "no speaker installed", ...)
    ├── PJLinkInvalidParameter  ERR2    parameter out of range
    ├── PJLinkNotReady          ERR3    unavailable right now (standby, warming up, or an `OK` answer to a status query)
    └── PJLinkDeviceFailure     ERR4    projector or display failure
```

A typical caller only needs a few clauses:

```python
try:
    state = await link.power.get()
except PJLinkNotReady:
    state = Power.State.OFF  # standby or not ready
except PJLinkConnectionError:
    ...  # unavailable, try again later
except PJLinkPassword:
    ...  # ask for a (new) password
except PJLinkException:
    ...  # anything else the projector or library reported
```

`ValueError` is raised for invalid arguments (a programming error). See `aiopjlink/exceptions.py` for the full table of which situation raises what.

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

The repository also includes a [dev container](.devcontainer/devcontainer.json) configured for Python 3.14 and the `uv` toolchain, along with recommended VS Code extensions for Python, Pylance, Ruff, and TOML support.

Enable PJLink traffic logging via Python's standard `logging` config. The library emits debug messages through the `aiopjlink` logger, so you can route them to the console or a file as needed.

```python
import logging

logging.basicConfig(level=logging.DEBUG)
```

## Project automation

This repository includes GitHub Actions workflows for:

* linting and static analysis
* tests on Linux, macOS, and Windows
* Python 3.11, 3.12, 3.13 and 3.14 coverage
* build verification and PyPI release publishing

The package is published from the `src` layout and is versioned via git metadata.

## Roadmap

Pull requests with test cases are welcome. There are still some things to finish, including:

* [ ] Search Protocol (§3.2)
* [ ] Status Notification Protocol (§3.3)
