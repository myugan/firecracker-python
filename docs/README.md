# Firecracker Python SDK Documentation

Welcome to the Firecracker Python SDK documentation! This documentation will help you use the Python SDK to create and manage Firecracker microVMs.

## Table of Contents

- [Getting Started](getting-started.md) - A step-by-step guide to get started with the SDK
- [API Reference](api-reference.md) - Detailed information about the SDK's API
- [Configuration](configuration.md) - Configuration options for microVMs
- [Network](network.md) - Networking capabilities and examples
- [Examples](examples.md) - Practical examples for using the SDK

## What is Firecracker?

Firecracker is a virtual machine monitor (VMM) that uses the Linux Kernel-based Virtual Machine (KVM) to create and manage secure, multi-tenant container and function-based services. Firecracker was developed at Amazon Web Services to improve the security and resource efficiency of container and function-based services.

This Python SDK provides a simple and intuitive interface for creating and managing Firecracker microVMs.

## Key Features

- **Lightweight**: Firecracker microVMs start quickly and use minimal resources
- **Secure**: Strong isolation boundaries between microVMs
- **Flexible**: Configure microVMs with different CPU, memory, and network settings
- **Programmable**: Full control via Python API

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

## Documentation Structure

- **Getting Started Guide**: Follow this guide to set up your environment and create your first microVM.
- **API Reference**: Complete documentation of all classes, methods, and parameters.
- **Configuration**: Learn about all the configuration options available for microVMs.
- **Network**: Understand how networking works with Firecracker microVMs and how to configure it.
- **Examples**: See practical examples of how to use the SDK for various use cases.

## System Requirements

- Linux kernel 4.14 or later
- KVM enabled
- Python 3.8 or later
- The `python3-nftables` module

## Installation

You can install the Firecracker Python SDK using pip:

```bash
pip install firecracker-python
```

Or install from source:

```bash
git clone https://github.com/myugan/firecracker-python.git
cd firecracker-python
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -e .
``` 