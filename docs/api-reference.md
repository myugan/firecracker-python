# Firecracker Python API Reference

This document provides detailed information about the Firecracker Python SDK API, including classes, methods, and usage examples.

## MicroVM

The primary class for managing Firecracker microVMs.

### Constructor

```python
MicroVM(name=None, kernel_file=None, base_rootfs=None, rootfs_url=None, 
        vcpu=None, mem_size_mib=None, ip_addr=None, bridge=None, 
        bridge_name=None, mmds_enabled=None, mmds_ip=None, labels=None, 
        working_dir='/root', expose_ports=None, host_port=None, 
        dest_port=None, user_data=None, user_data_file=None, verbose=False)
```

#### Parameters

- `name` (str, optional): Custom name for the microVM. If not provided, a random name will be generated.
- `kernel_file` (str, optional): Path to the kernel file to use. Defaults to configuration setting.
- `base_rootfs` (str, optional): Path to the base rootfs file. Defaults to configuration setting.
- `rootfs_url` (str, optional): URL to download a rootfs image from.
- `vcpu` (int, optional): Number of virtual CPUs to allocate. Defaults to configuration setting.
- `mem_size_mib` (int, optional): Memory size in MiB. Defaults to configuration setting.
- `ip_addr` (str, optional): IP address for the microVM. Defaults to configuration setting.
- `bridge` (bool, optional): Whether to use a bridge for networking. Defaults to configuration setting.
- `bridge_name` (str, optional): Name of the bridge interface. Defaults to configuration setting.
- `mmds_enabled` (bool, optional): Whether to enable MMDS (Microvm Metadata Service). Defaults to configuration setting.
- `mmds_ip` (str, optional): IP address for MMDS. Defaults to configuration setting.
- `labels` (dict, optional): Labels for the microVM.
- `working_dir` (str, optional): Working directory for the microVM. Defaults to `/root`.
- `expose_ports` (bool, optional): Whether to expose ports. Defaults to configuration setting.
- `host_port` (int, optional): Host port for port forwarding.
- `dest_port` (int, optional): Destination port for port forwarding.
- `user_data` (str, optional): Cloud-init user data as a string. This will enable MMDS.
- `user_data_file` (str, optional): Path to a file containing cloud-init user data. This will enable MMDS.
- `verbose` (bool, optional): Enable verbose logging. Defaults to `False`.

### Static Methods

#### `list()`

Lists all running Firecracker VMs.

**Returns:**
- `List[Dict]`: A list of dictionaries containing microVM details.

**Example:**
```python
from firecracker import MicroVM

# List all running microVMs
vms = MicroVM.list()
print(vms)
```

### Instance Methods

#### `create()`

Creates a new microVM and configures it.

**Returns:**
- `dict`: Status of the creation operation.

**Example:**
```python
from firecracker import MicroVM

# Create a new microVM with default settings
vm = MicroVM()
vm.create()
```

#### `find(state=None, labels=None)`

Finds a microVM by state or labels.

**Parameters:**
- `state` (str, optional): State of the microVM to find.
- `labels` (dict, optional): Labels to filter microVMs by.

**Returns:**
- `str`: ID of the found microVM or error message.

**Example:**
```python
from firecracker import MicroVM

vm = MicroVM()
# Find all running microVMs with label "env=prod"
vm.find(state="running", labels={"env": "prod"})
```

#### `config(id=None)`

Gets the configuration for the current microVM or a specific microVM.

**Parameters:**
- `id` (str, optional): ID of the microVM to query. If not provided, uses the current microVM's ID.

**Returns:**
- `dict`: Response from the microVM configuration endpoint or error message.

**Example:**
```python
from firecracker import MicroVM

vm = MicroVM()
# Get configuration for the current microVM
config = vm.config()
print(config)
```

#### `inspect(id=None)`

Inspects a microVM by ID.

**Parameters:**
- `id` (str, optional): ID of the microVM to inspect. If not provided, uses the current microVM's ID.

**Returns:**
- `dict`: Detailed information about the microVM.

**Example:**
```python
from firecracker import MicroVM

vm = MicroVM()
vm.create()
# Inspect the current microVM
details = vm.inspect()
print(details)
```

#### `status(id=None)`

Gets the status of the current microVM or a specific microVM.

**Parameters:**
- `id` (str, optional): ID of the microVM to check. If not provided, uses the current microVM's ID.

**Returns:**
- `str`: Status message indicating whether the microVM is running or paused.

**Example:**
```python
from firecracker import MicroVM

vm = MicroVM()
vm.create()
# Check status of the current microVM
status = vm.status()
print(status)
```

#### `pause(id=None)`

Pauses the current microVM or a specific microVM.

**Parameters:**
- `id` (str, optional): ID of the microVM to pause. If not provided, uses the current microVM's ID.

**Returns:**
- `str`: Status message indicating the result of the pause operation.

**Example:**
```python
from firecracker import MicroVM

vm = MicroVM()
vm.create()
# Pause the current microVM
vm.pause()
```

#### `resume(id=None)`

Resumes the current microVM or a specific microVM.

**Parameters:**
- `id` (str, optional): ID of the microVM to resume. If not provided, uses the current microVM's ID.

**Returns:**
- `str`: Status message indicating the result of the resume operation.

**Example:**
```python
from firecracker import MicroVM

vm = MicroVM()
vm.create()
vm.pause()
# Resume the current microVM
vm.resume()
```

#### `delete(id=None, all=False)`

Deletes the current microVM or a specific microVM, or all microVMs if `all` is `True`.

**Parameters:**
- `id` (str, optional): ID of the microVM to delete. If not provided, uses the current microVM's ID.
- `all` (bool, optional): If `True`, deletes all microVMs. Defaults to `False`.

**Returns:**
- `str`: Status message indicating the result of the delete operation.

**Example:**
```python
from firecracker import MicroVM

# Delete a specific microVM
vm = MicroVM()
vm.create()
vm.delete()

# Delete all microVMs
vm = MicroVM()
vm.delete(all=True)
```

#### `connect(id=None, username=None, key_path=None)`

Connects to the microVM via SSH.

**Parameters:**
- `id` (str, optional): ID of the microVM to connect to. If not provided, uses the current microVM's ID.
- `username` (str, optional): Username to use for SSH connection. Defaults to `root`.
- `key_path` (str, optional): Path to the SSH private key.

**Example:**
```python
from firecracker import MicroVM

vm = MicroVM()
vm.create()
# Connect to the microVM via SSH
vm.connect(key_path="/path/to/private/key")
```

#### `port_forward(id=None, host_port=None, dest_port=None, remove=False)`

Sets up or removes port forwarding for the microVM.

**Parameters:**
- `id` (str, optional): ID of the microVM. If not provided, uses the current microVM's ID.
- `host_port` (int, optional): Host port for port forwarding.
- `dest_port` (int, optional): Destination port inside the microVM.
- `remove` (bool, optional): If `True`, removes the port forwarding rule. Defaults to `False`.

**Example:**
```python
from firecracker import MicroVM

vm = MicroVM()
vm.create()
# Forward host port 8080 to port 80 in the microVM
vm.port_forward(host_port=8080, dest_port=80)

# Remove the port forwarding rule
vm.port_forward(host_port=8080, dest_port=80, remove=True)
```

## Api

The API client for interacting with the Firecracker HTTP API.

### Constructor

```python
Api(socket_path)
```

#### Parameters

- `socket_path` (str): Path to the Firecracker API socket.

## Logger

A logger for the Firecracker module.

### Constructor

```python
Logger(level="INFO", verbose=False)
```

#### Parameters

- `level` (str, optional): Logging level. Defaults to "INFO".
- `verbose` (bool, optional): Enable verbose logging. Defaults to `False`.

## NetworkManager

Manages network interfaces for microVMs.

## ProcessManager

Manages processes for microVMs.

## VMMManager

Manages Virtual Machine Monitors (VMMs).

## Scripts

Helper scripts for common tasks. 