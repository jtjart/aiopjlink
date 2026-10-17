# aiopjlink2

A typed asyncio library for controlling [PJLink](https://pjlink.jbmia.or.jp/english/) projectors over TCP.


[![PyPI](https://img.shields.io/pypi/v/aiopjlink2?logo=python&logoColor=%23cccccc)](https://pypi.org/project/aiopjlink2)
![PyPI - License](https://img.shields.io/pypi/l/aiopjlink2)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/aiopjlink2)
![PyPI - Downloads](https://img.shields.io/pypi/dm/aiopjlink2)

## What is PJLink?

PJLink is a manufacturer-independent protocol for operating data projectors over `TCP/IP`. It is defined in two parts:
- [Class 1](https://pjlink.jbmia.or.jp/english/data/5-1_PJLink_eng_20131210.pdf) (basic control and status) and
- [Class 2](https://pjlink.jbmia.or.jp/english/data_cl2/PJLink_5-1.pdf) (extensions for higher resolutions, more inputs, and extra queries and notifications).

## Features

* High-level, fully typed asyncio API (`py.typed`) with one command group per feature
* One connection reused for follow-up commands, opened lazily and replaced when the projector drops it
* One overall deadline per command, whatever stage it is in
* A per-command connection mode for projectors that cannot handle more
* Python 3.11–3.14; tested on Linux, macOS and Windows

## Supported commands

| Group | Class 1 | Class 2 |
|---|---|---|
| `power` | `POWR` | |
| `sources` | `INPT`, `INST` | `INNM`, `IRES`, `RRES`, `INPT`/`INST` with extended indexes (`A`–`Z`) |
| `mute` | `AVMT` | |
| `errors` | `ERST` | |
| `lamps` | `LAMP` | `RLMP` |
| `filter` | | `FILT`, `RFIL` |
| `speaker`, `microphone` | | `SVOL`, `MVOL` |
| `freeze` | | `FREZ` |
| `info` | `NAME`, `INF1`, `INF2`, `INFO`, `CLSS` | `SNUM`, `SVER` |

**Not supported yet:** UDP search (`SRCH`/`ACKN`, §3.2) and status notifications (`LKUP`, `POWR`/`ERST` notifications, §3.3).
`PJLink.wait_for_notification()` exists but raises `NotImplementedError`.

## Installation

```bash
pip install aiopjlink2
```

## Usage

Create one `PJLink` object and call its command groups. The first command connects, later ones reuse the connection, and leaving the `async with` block (or calling `close()`) releases it.

```python
import asyncio

from aiopjlink import PJLink


async def main() -> None:
    async with PJLink(address="192.168.1.120", password="secret") as link:
        await link.power.turn_on()
        await asyncio.sleep(5)
        print("errors =", await link.errors.query())
        await link.power.turn_off()


asyncio.run(main())
```

One object may be shared between tasks: commands are sent one after the other.

## Connection handling

```python
PJLink(address)  # reuse the connection, release it after 25 s idle
PJLink(address, idle_timeout=2)  # one connection per burst of commands (e.g. per poll)
PJLink(address, persistent=False)  # one connection per command
```

| Mode | Behaviour | Use it for |
|---|---|---|
| Default (`idle_timeout=25`) | One connection reused across polls; authentication sent once per connection. | Long-running programs polling every few seconds. |
| `idle_timeout=2` | One connection per poll, closed 2 s after the last command. | Freeing the projector between polls. |
| `persistent=False` | One connection and one authentication per command; nothing to close. | Projectors that cannot handle several commands per connection. |

The spec allows both styles (§5.3, §5.4). With `persistent=True`:

* **Reconnecting is automatic.** A connection the projector dropped (it does so after 30 s of silence) is replaced by the next command.
* **A failed command never poisons the next one.** After a timeout, cancellation or any unexpected error the connection is dropped, so a late answer is never mistaken for the next answer.
* **Queries are repeated once** on a new connection if the kept one turns out to be dead. Commands that change something (power, input, volume, ...) are not: the projector may already have carried them out, so you get `PJLinkConnectionClosed` and decide.

Every command has a single deadline, `timeout` (default 4 s), covering connect, greeting, send and answer. A command waiting behind others in the queue is bound by `timeout` for each of them.

## Error handling

Everything the library raises derives from `PJLinkException`:

```
PJLinkException
├── PJLinkConnectionError               projector unreachable or not talking
│   ├── PJLinkNoConnection              refused / no greeting / no response in time
│   └── PJLinkConnectionClosed          closed or reset by the projector
├── PJLinkPassword                      password missing or wrong
├── PJLinkProtocolError                 what the projector sent is not valid PJLink
├── PJLinkUnexpectedResponseParameter   valid PJLink, but a value the library does not know
└── PJLinkProjectorError                the projector answered with an error
    ├── PJLinkNotSupported      ERR1    not supported ("no lamp", "no speaker installed", ...)
    ├── PJLinkInvalidParameter  ERR2    parameter out of range
    ├── PJLinkNotReady          ERR3    unavailable now (standby, warming up, `OK` to a status query)
    └── PJLinkDeviceFailure     ERR4    projector or display failure
```

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
    ...  # anything else
```

`ValueError` is raised for invalid arguments (a programming error). The full table of situations is in `aiopjlink/exceptions.py`.

## Debug logging

Traffic is logged at `DEBUG` level on the `aiopjlink` logger (authentication tokens are redacted):

```python
import logging

logging.basicConfig(level=logging.DEBUG)
```

## Development

The easiest way to start is the [dev container](.devcontainer/devcontainer.json): open the repository in VS Code and choose "Reopen in Container". Python 3.14, [uv](https://docs.astral.sh/uv/), the dependencies and the pre-commit hooks are set up automatically.
Working without the container is possible too. See [CONTRIBUTING.md](CONTRIBUTING.md) for the setup, the checks and the code layout.

Only names exported from `aiopjlink` are public API.

## Roadmap

Pull requests with tests are welcome:

* [ ] Search protocol (§3.2)
* [ ] Status notification protocol (§3.3)

## Honorable mentions

Based on [HEInventions/aiopjlink](https://github.com/HEInventions/aiopjlink) and [Kwull/aiopjlink](https://github.com/Kwull/aiopjlink), and maintained as an independent project.
