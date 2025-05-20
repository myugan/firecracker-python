# Firecracker Python SDK Documentation

Welcome to the Firecracker Python SDK documentation! This documentation will help you use the Python SDK to create and manage Firecracker microVMs.

## Table of Contents

- [Getting Started](getting-started.md)
- [API Reference](api-reference.md)
- [Configuration](configuration.md)
- [Network](network.md)
- [Examples](examples.md)

## What is Firecracker?

Firecracker is a virtual machine monitor (VMM) that uses the Linux Kernel-based Virtual Machine (KVM) to create and manage secure, multi-tenant container and function-based services. Firecracker was developed at Amazon Web Services to improve the security and resource efficiency of container and function-based services.

This Python SDK provides a simple and intuitive interface for creating and managing Firecracker microVMs.

## Key Features

- **Lightweight**: Firecracker microVMs start quickly and use minimal resources
- **Secure**: Strong isolation boundaries between microVMs
- **Flexible**: Configure microVMs with different CPU, memory, and network settings
- **Programmable**: Full control via Python API

## Installation

You can install the Firecracker Python SDK using pip:

```bash
pip install firecracker-python
```

## Quick Start

Here's a simple example to get started:

```python
from firecracker import MicroVM

# Create a microVM with default settings
vm = MicroVM()
vm.create()

# Connect to the microVM via SSH
vm.connect(key_path="/path/to/private/key")
```

## System Requirements

- Linux kernel 4.14 or later
- KVM enabled
- Python 3.8 or later
- The `python3-nftables` module

## License

This project is licensed under the MIT License - see the LICENSE file for details. 