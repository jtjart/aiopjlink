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
* Password authentication with SHA256 (specification 2.10) and automatic fallback to MD5
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
* **Data the projector sends unasked is discarded.** Some projectors volunteer a status line of their own (one was seen to send `%1powr=0` after a power-on command). Nothing can be the answer to a command that has not been sent yet, so whatever has arrived by then is thrown away before the next command goes out, and shows up in the debug log as `discarded unsolicited data`.
* **Queries are repeated once** on a new connection if the kept one turns out to be dead. Commands that change something (power, input, volume, ...) are not: the projector may already have carried them out, so you get `PJLinkConnectionClosed` and decide.

Every command has a single deadline, `timeout` (default 4 s), covering connect, greeting, send and answer. A command waiting behind others in the queue is bound by `timeout` for each of them.

`timeout` is how long a projector may take to answer. The exception is a command that carries a password: a projector answers a wrong password only after two seconds (§5.1), so such a command is given at least 3 s to be answered, whatever `timeout` is, and a wrong password is reported as `PJLinkPassword` rather than as a dead connection. There is therefore no minimum for `timeout`.

## Authentication

A projector with a password uses MD5 (PJLink up to 2.00) or SHA256 (PJLink 2.10, §5.1). By default the library does what the spec describes for a controller that knows both: after the projector's greeting it asks `PJLINK 2`. A projector that supports SHA256 answers with a random number and is authenticated with it. For any other reaction (`ERR1`, `ERR2`, `ERRA`, an echo, hanging up, silence) the library drops the connection and reconnects with MD5, as the spec and the JBMIA application guideline (§6) prescribe.

```python
PJLink(address, password="secret")  # SHA256 if the projector can, otherwise MD5
PJLink(address, password="secret", authentication=PJAuth.SHA256)  # never MD5: PJLinkNotSupported if it cannot
PJLink(address, password="secret", authentication=PJAuth.MD5)  # never asks for SHA256
```

* **The answer is remembered.** Once a projector has not said yes to the question (it answered with an error, hung up, or stayed silent), MD5 is assumed from then on and new connections go straight to MD5, so only the first one pays for the question. That also protects a projector that cannot cope with the question (it may lock up for 30 s, guideline behaviour 6) from being put out of action again by every new connection.
* **A rejected MD5 digest is retried at once.** If MD5 is rejected by a projector that never said it lacks SHA256 (the question was skipped because MD5 was assumed or worked before, or went unanswered), it may have been switched to SHA256 or just missed the question. The same command then asks again on a new connection, for SHA256 only, with a deadline of its own (a command can thus make two attempts, each bounded by `timeout`). A projector that did answer the question with an error is not asked again, and a wrong password is never tried twice. A rejected command was not carried out, so this is safe for commands that change something.
* **A silent projector costs time once.** The question is bound by 2 s, and by half of `timeout`, so that the command can still reconnect. For a projector that cannot cope with the question at all, use `PJAuth.MD5`.
* **`ERRA` in answer to the question is not a wrong password.** Some MD5-only projectors answer it that way. A wrong password is reported as `PJLinkPassword` once the digest has been sent.
* **With `persistent=False`** every command does the whole handshake (question included) on its own connection.
* **Security note.** The fallback can be provoked by anyone who can tamper with the traffic. If all your projectors support SHA256, use `PJAuth.SHA256`.

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
    ├── PJLinkNotSupported      ERR1    not supported ("no lamp", "no speaker installed", SHA256 when required, ...)
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
