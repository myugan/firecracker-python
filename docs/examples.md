# Firecracker Python SDK Examples

This document provides practical examples for using the Firecracker Python SDK.

## Basic Examples

### Creating and Starting a microVM

```python
from firecracker import MicroVM

# Create a microVM with default settings
vm = MicroVM()
vm.create()

# Check the status of the microVM
print(vm.status())
```

### Creating a microVM with Custom Resources

```python
from firecracker import MicroVM

# Create a microVM with custom resources
vm = MicroVM(
    vcpu=2,
    mem_size_mib=1024,
    ip_addr="192.168.100.2"
)
vm.create()
```

### Connecting to a microVM via SSH

```python
from firecracker import MicroVM

# Create a microVM
vm = MicroVM()
vm.create()

# Connect to the microVM via SSH
# The key_path should point to the private key that corresponds to the public key
# used when building the rootfs (see the getting-started guide)
vm.connect(key_path="/path/to/private/key")

# This will open an interactive SSH session
```

### Managing multiple microVMs

```python
from firecracker import MicroVM

# Create multiple microVMs
vm1 = MicroVM(name="web-server")
vm1.create()

vm2 = MicroVM(name="database")
vm2.create()

# List all running microVMs
vms = MicroVM.list()
print(vms)

# Pause a specific microVM
vm1.pause()

# Resume a specific microVM
vm1.resume()

# Delete a specific microVM
vm2.delete()

# Delete all microVMs
vm = MicroVM()
vm.delete(all=True)
```

## Network Examples

### Port Forwarding

```python
from firecracker import MicroVM

# Create a microVM
vm = MicroVM()
vm.create()

# Forward host port 8080 to port 80 in the microVM
vm.port_forward(host_port=8080, dest_port=80)

# Connect to the microVM
vm.connect(key_path="/path/to/private/key")

# Inside the microVM, you can install and run a web server
# Then access it from the host at http://localhost:8080

# Remove the port forwarding when no longer needed
vm.port_forward(host_port=8080, dest_port=80, remove=True)
```

### Using Bridge Networking

```python
from firecracker import MicroVM

# Create a microVM with bridge networking
vm = MicroVM(
    bridge=True,
    bridge_name="br0",  # Use an existing bridge
    ip_addr="192.168.1.100"
)
vm.create()
```

## Advanced Examples

### Using MMDS (Microvm Metadata Service)

```python
from firecracker import MicroVM

# Create a microVM with MMDS enabled
vm = MicroVM(
    mmds_enabled=True,
    mmds_ip="169.254.169.254"
)
vm.create()

# Add data to MMDS
vm._api.mmds.put(json_data={
    "instance-id": "i-abcdef123456",
    "hostname": "example-host",
    "local-ipv4": "192.168.100.2",
    "public-ipv4": "203.0.113.10"
})

# Inside the microVM, you can access this data using:
# curl http://169.254.169.254/latest/meta-data/instance-id
```

### Creating a microVM with Labels

```python
from firecracker import MicroVM

# Create a microVM with labels
vm = MicroVM(
    labels={
        "environment": "production",
        "app": "web-server",
        "team": "infrastructure"
    }
)
vm.create()

# Later, find microVMs by labels
vm_finder = MicroVM()
found_vms = vm_finder.find(state="running", labels={"environment": "production"})
print(found_vms)
```

### Using a Custom Rootfs

```python
from firecracker import MicroVM

# Create a microVM with a custom rootfs
vm = MicroVM(
    base_rootfs="/path/to/custom/rootfs.img"
)
vm.create()
```

### Downloading a Rootfs from URL

```python
from firecracker import MicroVM

# Create a microVM with a rootfs downloaded from URL
vm = MicroVM(
    rootfs_url="https://example.com/path/to/rootfs.img"
)
vm.create()
```

## Practical Use Cases

### Running a Web Server in a microVM

```python
from firecracker import MicroVM

# Create a microVM with appropriate resources
vm = MicroVM(
    vcpu=2,
    mem_size_mib=1024,
    ip_addr="192.168.100.2"
)
vm.create()

# Forward port 80 to host port 8080
vm.port_forward(host_port=8080, dest_port=80)

# Connect to the microVM
vm.connect(key_path="/path/to/private/key")

# Inside the microVM, you would run:
# apt-get update
# apt-get install -y nginx
# systemctl start nginx

# Now you can access the web server from the host at http://localhost:8080
```

### Running a Database in a microVM

```python
from firecracker import MicroVM

# Create a microVM with appropriate resources for a database
vm = MicroVM(
    name="database",
    vcpu=4,
    mem_size_mib=4096,
    ip_addr="192.168.100.3"
)
vm.create()

# Forward database port
vm.port_forward(host_port=5432, dest_port=5432)

# Connect to the microVM
vm.connect(key_path="/path/to/private/key")

# Inside the microVM, you would install and configure your database

# Now you can connect to the database from the host at localhost:5432
```

### Creating a Development Environment

```python
from firecracker import MicroVM

# Create a development environment microVM
vm = MicroVM(
    name="dev-env",
    vcpu=2,
    mem_size_mib=2048,
    ip_addr="192.168.100.4"
)
vm.create()

# Forward necessary ports
vm.port_forward(host_port=8080, dest_port=80)  # Web server
vm.port_forward(host_port=3000, dest_port=3000)  # Development server

# Connect to the microVM
vm.connect(key_path="/path/to/private/key")

# Inside the microVM, you would set up your development environment
```

## Troubleshooting Examples

### Handling IP Address Conflicts

```python
from firecracker import MicroVM
from firecracker.network import NetworkManager

# Check for IP conflicts before creating a microVM
network_manager = NetworkManager()
preferred_ip = "192.168.100.2"

if network_manager.detect_cidr_conflict(preferred_ip):
    # If there's a conflict, get a suggested non-conflicting IP
    non_conflicting_ip = network_manager.suggest_non_conflicting_ip(preferred_ip)
    print(f"IP conflict detected. Using {non_conflicting_ip} instead.")
    vm = MicroVM(ip_addr=non_conflicting_ip)
else:
    vm = MicroVM(ip_addr=preferred_ip)

vm.create()
```

### Recovering from Errors

```python
from firecracker import MicroVM
from firecracker.exceptions import APIError, VMMError, ConfigurationError, ProcessError

try:
    vm = MicroVM()
    vm.create()
except ConfigurationError as e:
    print(f"Configuration error: {e}")
    # Handle configuration error
except APIError as e:
    print(f"API error: {e}")
    # Handle API error
except VMMError as e:
    print(f"VMM error: {e}")
    # Handle VMM error
except ProcessError as e:
    print(f"Process error: {e}")
    # Handle process error
except Exception as e:
    print(f"Unexpected error: {e}")
    # Handle unexpected error
``` 