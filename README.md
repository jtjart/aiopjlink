<div align="center">

# aiopjlink2

A modern Python asyncio PJLink library (Class I and Class II). 
This is a fork from HEInventions/aiopjlink and Kwull/aiopjlink.

[![PyPI](https://img.shields.io/pypi/v/aiopjlink2?logo=python&logoColor=%23cccccc)](https://pypi.org/project/aiopjlink2)
![PyPI - License](https://img.shields.io/pypi/l/aiopjlink2)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/aiopjlink2)

![PyPI - Downloads](https://img.shields.io/pypi/dm/aiopjlink2)
![GitHub repo size](https://img.shields.io/github/repo-size/jtjart/aiopjlink)

</div>

## What is PJLink?

Most projectors that have RJ45 ports on the back can be controlled via [PJLink](https://pjlink.jbmia.or.jp/english/).

PJLink is a communication protocol and unified standard for operating and controlling data projectors via `TCP/IP`, regardless of manufacturer.

PJLink consists of [Class 1](https://pjlink.jbmia.or.jp/english/data/5-1_PJLink_eng_20131210.pdf) commands and queries, as well as [Class 2](https://pjlink.jbmia.or.jp/english/data_cl2/PJLink_5-1.pdf) notifications and extensions.

* Class 1 is the most common type of PJLink, and is used for basic commands such as power on/off, input selection, and adjusting volume.
* Class 2 is an extended version of the protocol that supports additional commands such as opening and closing the projector's lens cover, and is typically used by more sophisticated devices.

## What is aiopjlink?

A Python library that uses [asyncio](https://docs.python.org/3/library/asyncio.html) to talk to one or more projectors connected to a network using the PJLink protocol.

The main difference from the HEInventions/aiopjlink implementation is that in aiopjlink-kw, each PJLink command is executed over a new TCP/IP connection, including authentication if required. This approach was taken due to the specific PJLink implementation used by AWOL projectors.
The additional changes made by aiopjlink2 is the exclusion of the test folder from the package that is published to PyPI. Additionally the context manager has been removed from PJLink because it brings no benefit anymore now, that each command is executed over a new connection.

It has these advantages:

* ✅ Clean modern asyncio API
* ✅ High level API abstraction (eg. `lamp.hours`)
* ✅ Pure Python 3 implementation (no dependencies)
* ✅ Full suite of test cases
* ❌ Context managers for keeping track of connections and resources 
* ✅ High quality error handling


## Usage

Each command sent to a projector is creating a new connection. The projector can be initialized with a `PJLink` instance. Once this is created, you access the different functions through a high level API (e.g. `conn.power.turn_off()`, `conn.lamps.hours()`, `conn.errors.query()`, etc).

For example, create a `PJLink` instance of the projector and issue commands:

```python
link = PJLink(address="192.168.1.120", password="secretpassword")

# Turn on the projector.
await link.power.turn_on()

# Wait a few seconds, then print out all the error information.
await asyncio.sleep(5)
print("errors = ", await link.errors.query())

# Then wait a few seconds, then turn the projector off.
await asyncio.sleep(5)
await link.power.turn_off()
```

## Development

We use the [PDM package manager](https://pdm.fming.dev/latest/).

```bash
pdm install --dev  # install all deps required to run and test the code

pdm run lint  # check code quality
pdm run test  # check all test cases run OK

pdm publish  # Publish the project to PyPI
```

Other notes:
* There are more "pdm scripts" in the `.toml` file.
* Set the env variable `AIOPJLINK_PRINT_DEBUG_COMMS` to print debug comms to the console.

## Roadmap

Pull requests with test cases are welcome. There are still some things to finish, including:

* [ ] Search Protocol (§3.2)
* [ ] Status Notification Prototol (§3.3)
