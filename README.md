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
- [Key Features](#key-features)
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

### Key Features

- Easily create microVMs with default or custom settings
- View a list of all running microVMs
- Access and modify microVM settings
- Remove one or all microVMs
- Connect to microVMs using SSH
- Set up port forwarding in microVMs

### Getting Started

To get started with **firecracker-python**, check out the [getting started guide](docs/getting-started.md)

### Usage

Here are some examples of how to use the library.

#### Create a microVM with custom configuration and list them all

```python
from firecracker import MicroVM

# Create a new microVM with custom configuration
vm = MicroVM(vcpu=2, memory="4096")
# Or
vm = MicroVM(vcpu=2, memory="4G")

vm.create()

# List all running microVMs
vms = MicroVM.list()  # Static method to list all VMs
for vm in vms:
    print(f"VM with id {vm['id']} has IP {vm['ip_addr']} and is in state {vm['state']}")
```

#### Delete a microVM by id or all microVMs

```python
from firecracker import MicroVM

# Create a new microVM
vm = MicroVM()
vm.create()

# Delete the microVM just created
vm.delete()

# Delete a specific microVM by ID
vm.delete(id="<specific_id>")

# Delete all microVMs
vm.delete(all=True)
```

#### Enable port forwarding

During initialization:

```python
from firecracker import MicroVM

# Single port
vm = MicroVM(expose_ports=True, host_port=10222, dest_port=22)
# Multiple ports
# vm = MicroVM(expose_ports=True, host_port=[10222, 10280], dest_port=[22, 80])

vm.create()
```

After creation you can also expose ports using the `port_forward` function:

```python
from firecracker import MicroVM

vm = MicroVM()
vm.create()

# Forward a single port
vm.port_forward(host_port=10222, dest_port=22)
# 'Port forwarding added successfully'

# Forward multiple ports
vm.port_forward(host_port=[10222, 10280], dest_port=[22, 80])
# 'Port forwarding added successfully'

# Remove port forwarding
vm.port_forward(host_port=10222, dest_port=22, remove=True)
# 'Port forwarding removed successfully'
```

> **Note:** When using port forwarding, you need to specify both `host_port` and `dest_port`. The number of host ports must match the number of destination ports.

### License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

### Contributing

Contributions are welcome! Please open an issue or submit a Pull Request (PR).