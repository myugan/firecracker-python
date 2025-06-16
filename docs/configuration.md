# Firecracker Python Configuration Documentation

This document provides detailed information about the configuration options available in the Firecracker Python SDK.

## Overview

The Firecracker Python SDK provides various configuration options for microVMs through the `MicroVMConfig` class. This class defines default values for microVM parameters, which can be overridden when creating a microVM instance.

## MicroVMConfig

The `MicroVMConfig` class is a dataclass that defines default configuration values for Firecracker microVMs.

### Configuration Parameters

| Parameter | Type | Default Value | Description |
|-----------|------|---------------|-------------|
| `data_path` | str | "/var/lib/firecracker" | Base directory for storing Firecracker data |
| `binary_path` | str | "/usr/local/bin/firecracker" | Path to the Firecracker binary |
| `kernel_file` | str | "{data_path}/vmlinux-5.10.225" | Path to the Linux kernel file |
| `initrd_file` | str | None | Path to the initrd file (optional) |
| `init_file` | str | "/sbin/init" | Path to the init file |
| `base_rootfs` | str | "{data_path}/rootfs.img" | Path to the base root filesystem image |
| `overlayfs` | bool | False | Whether to use overlay filesystem |
| `overlayfs_file` | str | None | Path to the overlay filesystem file |
| `ip_addr` | str | "172.16.0.2" | Default IP address for microVMs |
| `bridge` | bool | False | Whether to use bridge networking by default |
| `bridge_name` | str | "docker0" | Default bridge interface name |
| `mmds_enabled` | bool | False | Whether MMDS (Microvm Metadata Service) is enabled by default |
| `mmds_ip` | str | "169.254.169.254" | Default IP address for MMDS |
| `vcpu` | int | 1 | Default number of virtual CPUs |
| `memory` | str | 512 | Default memory size in MiB (can be specified as a number or with units like '1G') |
| `hostname` | str | "fc-vm" | Default hostname for microVMs |
| `verbose` | bool | False | Whether verbose logging is enabled by default |
| `level` | str | "INFO" | Default logging level |
| `ssh_user` | str | "root" | Default SSH user for connecting to microVMs |
| `expose_ports` | bool | False | Whether to expose ports by default |
| `host_port` | int | None | Default host port for port forwarding |
| `dest_port` | int | None | Default destination port for port forwarding |
| `user_data` | str | None | Cloud-init user data |

## Using Custom Configuration

> Floating point numbers cannot be used for vcpu configuration as it will result in a `SerdeJson(Error("invalid type: floating point `0.2`, expected u8", line: 1, column: 18))` error

When creating a microVM, you can override the default configuration by passing parameters to the MicroVM constructor:

```python
from firecracker import MicroVM

# Create a microVM with custom configuration
vm = MicroVM(
    vcpu=2,
    memory=1024,
    ip_addr="192.168.100.2"
)

vm.create()
```

## Configuration Examples

### Basic microVM with Minimal Resources

```python
from firecracker import MicroVM

vm = MicroVM(
    vcpu=1,
    memory=256
)

vm.create()
```

### High-Performance microVM

```python
from firecracker import MicroVM

vm = MicroVM(
    vcpu=4,
    memory=4096
)

vm.create()
```

### microVM with Custom Network Settings

```python
from firecracker import MicroVM

vm = MicroVM(
    ip_addr="192.168.100.2",
    bridge=True,
    bridge_name="br0",
    expose_ports=True
)

vm.create()
```

### microVM with MMDS (Microvm Metadata Service)

```python
from firecracker import MicroVM

vm = MicroVM(
    mmds_enabled=True,
    mmds_ip="169.254.169.254"
)

vm.create()

# Add data to MMDS
vm._api.mmds.put(json_data={"instance-id": "i-abcdef123456"})
```

## Advanced Configuration

### Custom Kernel and Rootfs

You can specify custom kernel and rootfs images:

```python
from firecracker import MicroVM

vm = MicroVM(
    kernel_file="/path/to/custom/vmlinux",
    base_rootfs="/path/to/custom/rootfs.img"
)

vm.create()
```

### Download Rootfs from URL

The SDK supports downloading a rootfs image from a URL:

```python
from firecracker import MicroVM

vm = MicroVM(
    rootfs_url="https://example.com/path/to/rootfs.img"
)

vm.create()
```

### Setting Labels

You can set labels for your microVM for better organization:

```python
from firecracker import MicroVM

vm = MicroVM(
    labels={
        "environment": "production",
        "app": "web-server",
        "team": "infrastructure"
    }
)

vm.create()
```

## Recommended System Requirements

For optimal performance, ensure your host system meets these requirements:

- Linux kernel 4.14 or later
- KVM enabled
- At least 4GB of RAM
- At least 2 CPU cores
