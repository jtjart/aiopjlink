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
* Searching the network for projectors by UDP broadcast (§3.2), by IPv4 or IPv6
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

Finding projectors on the network (`SRCH`/`ACKN`, §3.2) is done by `search()` and `search_iter()`, see [below](#searching-for-projectors).

**Not supported yet:** status notifications (`LKUP`, `POWR`/`ERST` notifications, §3.3).
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

## Searching for projectors

`search()` finds the projectors on the network (§3.2). It broadcasts one UDP datagram, listens for answers, and returns what it found:

```python
import asyncio
from aiopjlink import PJLink, search


async def main() -> None:
    for found in await search(duration=12):
        print(found.address, found.mac_address)  # 192.168.1.120 00:11:22:33:44:55
    ...


asyncio.run(main())
```

A `SearchResult` has the `address` the answer came from, which goes straight into `PJLink(address=...)`, and the projector's `mac_address` (lower case, `aa:bb:cc:dd:ee:ff`), which stays the same when the address changes. No password is needed to search (§6).

**To stop as soon as the one you want has answered,** use `search_iter()`, which yields each projector when it answers. Close it when you leave the loop, so the socket is released at once:

```python
from contextlib import aclosing
from aiopjlink import search_iter


async def find_address(mac_address: str) -> str | None:
    async with aclosing(search_iter()) as results:
        async for result in results:
            if result.mac_address == mac_address:
                return result.address
    return None
```

**Time.** The spec has the controller listen for 30 seconds, and that is the default `duration`. Projectors wait a random time of up to 10 seconds before they answer, so about 12 seconds is enough for a person who is waiting, and shorter risks missing some.

**Networks.** The default target, `255.255.255.255`, only reaches the one network the operating system chooses. On a machine with several (Home Assistant often has), give the broadcast address of each, or `ff02::1` for IPv6, with the interface (`ff02::1%eth0`) when there are several:

```python
await search(broadcast_address=["192.168.1.255", "10.0.0.255"])
```

The address of a single projector works as well. Host names do not: they are not broadcast addresses. A broadcast does not cross a router, and does not leave a container that is not on the host network.

**Reliability.** The search is UDP, so a datagram can get lost (§6), and a projector that has just been switched on may not answer yet. Nothing found is not proof that nothing is there: search again. Device search is defined by PJLink Class 2, so a projector that only speaks Class 1 is not expected to answer.

**Local port.** Both ends use UDP port 4352 (Fig. 1 of the spec leaves open whether a projector answers the port the request came from, or port 4352), so the search sends from, and listens on, port 4352. That means one search at a time per local address: a second one, or another program using the port, raises `PJLinkNoConnection`. Pass `local_port=0` to let the operating system choose a port; that only works with projectors that answer the port the request came from. `local_address` picks the local interface.

Anything else that arrives on the port is ignored. Problems on this machine (the port is in use, there is no network) raise `PJLinkNoConnection`, and a wrong argument raises `ValueError`.

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

Keep `timeout` above 2 s: a projector answers a wrong password only after two seconds (§5.1), so a shorter deadline reports it as `PJLinkNoConnection` instead of `PJLinkPassword`.

## Error handling

Everything the library raises derives from `PJLinkException`:

```
PJLinkException
├── PJLinkConnectionError               projector unreachable or not talking
│   ├── PJLinkNoConnection              refused / no greeting / no response in time / no search socket
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

* [x] Search protocol (§3.2)
* [ ] Status notification protocol (§3.3)

## Honorable mentions

Based on [HEInventions/aiopjlink](https://github.com/HEInventions/aiopjlink) and [Kwull/aiopjlink](https://github.com/Kwull/aiopjlink), and maintained as an independent project.
