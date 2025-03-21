# firecracker-python

<p align="center">
<a href="https://opensource.org/license/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg"></a>
<a href="https://github.com/myugan/firecracker-python"><img src="https://img.shields.io/github/stars/myugan/firecracker-python.svg?style=social&label=Star"></a>
<a href="https://github.com/myugan/firecracker-python"><img src="https://img.shields.io/github/forks/myugan/firecracker-python.svg?style=social&label=Fork"></a>
<a href="https://github.com/myugan/firecracker-python"><img src="https://img.shields.io/github/watchers/myugan/firecracker-python.svg?style=social&label=Watch"></a>
</p>

![Firecracker](img/firecracker.png)

**firecracker-python** is a simple Python library that makes it easy to manage Firecracker microVMs. It provides a simple way to create, configure, and manage microVMs.

Some features are still being developed and will be added in the future. You can track these in the [TODO.md](TODO.md) file.

[![asciicast](https://asciinema.org/a/nCD68S0KICqXt5206Eb3TA8FJ.svg)](https://asciinema.org/a/nCD68S0KICqXt5206Eb3TA8FJ)

## Table of Contents

- [How to Install](#how-to-install)
- [Features](#features)
- [Getting Started](#getting-started)
- [Usage](#usage)
- [License](#license)
- [Contributing](#contributing)

### How to Install

To install from PyPI, you need to have a personal access token with read access to the repository.

```bash
pip3 install firecracker-python
```

Or install from source, by cloning the repository and installing the package using pip:

```bash
git clone https://github.com/myugan/firecracker-python.git
cd firecracker-python
python3 -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt
pip3 install -e .
```

### Features

- Easily create microVMs with default or custom settings
- View a list of all running microVMs
- Access and modify microVM settings
- Remove one or all microVMs
- Connect to microVMs using SSH
- Set up port forwarding in microVMs

### Getting Started

To get started with **firecracker-python**, go to the [getting start guide](docs/getting-started.md)

### Usage

Here are some examples of how to use the library.

#### Create a microVM with custom configuration and list them all.

```python
from firecracker import MicroVM

vm = MicroVM(id="<vm_id>", vcpu=2, mem_size_mib=4096)
vm.create()

vms = MicroVM.list()
for vm in vms:
    print(f"VM with id {vm['id']} has IP {vm['ip_addr']} and is in state {vm['state']}")
```

#### Delete a microVM by id or all microVMs

```python
from firecracker import MicroVM

vm = MicroVM(id="<vm_id>")
vm.delete()         # Delete a single microVM by id
# Or
vm.delete(all=True) # Delete all microVMs
```

#### Enable port forwarding

```python
from firecracker import MicroVM

vm = MicroVM()
vm.create()

vm.port_forward(host_port=10222, dest_port=22)
# [2025-03-20T07:45:52.215] [INFO] Added nftables port forwarding rule
# 'Port forwarding active: x.x.x.x:10222 -> 172.16.0.2:22'

vm.port_forward(host_port=10222, dest_port=22, remove=True)
# [2025-03-20T07:46:11.062] [INFO] Found postrouting rule with handle 16
# [2025-03-20T07:46:11.062] [INFO] Prerouting rule: 172.16.0.2:22
# [2025-03-20T07:46:11.062] [INFO] Found prerouting rule with handle 17
# [2025-03-20T07:46:11.063] [INFO] Prerouting rule with handle 17 deleted
# [2025-03-20T07:46:11.065] [INFO] Postrouting rule with handle 16 deleted
# 'Port forwarding rule removed: x.x.x.x:10222 -> 172.16.0.2:22'
```

### License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

### Contributing

Contributions are welcome! Please open an issue or submit a Pull Request (PR).