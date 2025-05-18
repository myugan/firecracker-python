# Firecracker Python Network Documentation

This document provides detailed information about the networking capabilities of the Firecracker Python SDK.

## Overview

The Firecracker Python SDK provides networking functionality for microVMs through the `NetworkManager` class. This class allows you to create and manage tap devices, set up NAT rules, forward ports, and more.

## NetworkManager

The `NetworkManager` class manages all network-related operations for Firecracker microVMs.

### Constructor

```python
NetworkManager(verbose=False, level="INFO")
```

#### Parameters

- `verbose` (bool, optional): Enable verbose logging. Defaults to `False`.
- `level` (str, optional): Logging level. Defaults to "INFO".

### Methods

#### `get_interface_name()`

Gets the name of the network interface.

**Returns:**
- `str`: Name of the network interface.

**Raises:**
- `RuntimeError`: If unable to determine the interface name.

#### `get_gateway_ip(ip)`

Derives a gateway IP from a microVM IP by replacing the last octet with 1 for IPv4, or the last segment with 1 for IPv6.

**Parameters:**
- `ip` (str): IP address to derive gateway IP from.

**Returns:**
- `str`: Derived gateway IP.

**Raises:**
- `NetworkError`: If IP address is invalid.

#### `check_bridge_device(bridge_name)`

Checks if a bridge device exists in the system.

**Parameters:**
- `bridge_name` (str): Name of the bridge device to check.

**Returns:**
- `bool`: `True` if the device exists, `False` otherwise.

**Raises:**
- `NetworkError`: If checking the bridge device fails.

#### `check_tap_device(tap_device_name)`

Checks if a tap device exists in the system.

**Parameters:**
- `tap_device_name` (str): Name of the tap device to check.

**Returns:**
- `bool`: `True` if the device exists, `False` otherwise.

**Raises:**
- `NetworkError`: If checking the tap device fails.

#### `add_nat_rules(tap_name, iface_name)`

Creates network rules using nftables Python module.

**Parameters:**
- `tap_name` (str): Name of the tap device.
- `iface_name` (str): Name of the interface to be used.

**Raises:**
- `NetworkError`: If adding NAT forwarding rule fails.

#### `get_nat_rules()`

Gets the current NAT rules.

**Returns:**
- `list`: List of current NAT rules.

#### `ensure_masquerade(iface_name)`

Ensures that masquerade is set up for the given interface.

**Parameters:**
- `iface_name` (str): Name of the interface.

**Returns:**
- `bool`: `True` if masquerade was added, `False` if it already existed.

#### `add_port_forward(host_ip, host_port, dest_ip, dest_port, protocol="tcp")`

Adds port forwarding rules.

**Parameters:**
- `host_ip` (str): Host IP address.
- `host_port` (int): Host port.
- `dest_ip` (str): Destination IP address.
- `dest_port` (int): Destination port.
- `protocol` (str, optional): Protocol to use. Defaults to "tcp".

**Returns:**
- `bool`: `True` if port forwarding was added, `False` if it already existed.

#### `delete_port_forward(host_ip, host_port, dest_ip, dest_port)`

Deletes port forwarding rules.

**Parameters:**
- `host_ip` (str): Host IP address.
- `host_port` (int): Host port.
- `dest_ip` (str): Destination IP address.
- `dest_port` (int): Destination port.

**Returns:**
- `bool`: `True` if port forwarding was deleted, `False` if it did not exist.

#### `detect_cidr_conflict(ip_address, prefix_len=24)`

Detects if an IP CIDR range conflicts with existing interfaces.

**Parameters:**
- `ip_address` (str): IP address to check.
- `prefix_len` (int, optional): Prefix length. Defaults to 24.

**Returns:**
- `bool`: `True` if there is a conflict, `False` otherwise.

#### `suggest_non_conflicting_ip(preferred_ip, prefix_len=24)`

Suggests a non-conflicting IP address.

**Parameters:**
- `preferred_ip` (str): Preferred IP address.
- `prefix_len` (int, optional): Prefix length. Defaults to 24.

**Returns:**
- `str`: Non-conflicting IP address.

#### `create_tap(name=None, iface_name=None, gateway_ip=None, bridge=False)`

Creates a tap device.

**Parameters:**
- `name` (str, optional): Name of the tap device.
- `iface_name` (str, optional): Name of the interface.
- `gateway_ip` (str, optional): Gateway IP address.
- `bridge` (bool, optional): Whether to use a bridge. Defaults to `False`.

**Raises:**
- `NetworkError`: If creating the tap device fails.

#### `attach_tap_to_bridge(iface_name, bridge_name)`

Attaches a tap device to a bridge.

**Parameters:**
- `iface_name` (str): Name of the interface.
- `bridge_name` (str): Name of the bridge.

**Raises:**
- `NetworkError`: If attaching the tap device to the bridge fails.

#### `delete_tap(name)`

Deletes a tap device.

**Parameters:**
- `name` (str): Name of the tap device.

**Raises:**
- `NetworkError`: If deleting the tap device fails.

#### `cleanup(tap_device)`

Cleans up network resources.

**Parameters:**
- `tap_device` (str): Name of the tap device.

#### `enable_nat_internet_access(tap_name, iface_name, vm_ip)`

Enables NAT for internet access.

**Parameters:**
- `tap_name` (str): Name of the tap device.
- `iface_name` (str): Name of the interface.
- `vm_ip` (str): IP address of the microVM.

**Raises:**
- `NetworkError`: If enabling NAT fails.

## Network Configuration

When creating a microVM, you can configure various network parameters:

```python
from firecracker import MicroVM

# Create a microVM with custom network settings
vm = MicroVM(
    ip_addr="192.168.100.2",
    bridge=True,
    bridge_name="br0"
)

vm.create()
```

### Key Network Parameters

- `ip_addr`: IP address for the microVM.
- `bridge`: Whether to use a bridge for networking.
- `bridge_name`: Name of the bridge interface.

## Port Forwarding

You can set up port forwarding to expose services running in the microVM:

```python
from firecracker import MicroVM

vm = MicroVM()
vm.create()

# Forward host port 8080 to port 80 in the microVM
vm.port_forward(host_port=8080, dest_port=80)
```

### Example: Running a Web Server in a microVM

```python
from firecracker import MicroVM

# Create a microVM
vm = MicroVM()
vm.create()

# Forward host port 8080 to port 80 in the microVM
vm.port_forward(host_port=8080, dest_port=80)

# Connect to the microVM
vm.connect(key_path="/path/to/private/key")

# Inside the microVM, install and run a web server
# Now the web server is accessible from the host at http://localhost:8080
```

## Troubleshooting

### Common Issues

1. **IP Address Conflicts**

   If you encounter IP address conflicts, you can use the `suggest_non_conflicting_ip` method to find a non-conflicting IP address:

   ```python
   from firecracker import MicroVM
   from firecracker.network import NetworkManager

   network_manager = NetworkManager()
   non_conflicting_ip = network_manager.suggest_non_conflicting_ip("192.168.100.2")
   
   vm = MicroVM(ip_addr=non_conflicting_ip)
   vm.create()
   ```

2. **Unable to Access the Internet from microVM**

   Make sure IP forwarding is enabled on the host:

   ```bash
   sudo sysctl -w net.ipv4.ip_forward=1
   sudo iptables -P FORWARD ACCEPT
   ```

3. **Port Forwarding Not Working**

   Check if the port is already in use on the host:

   ```bash
   sudo netstat -tulpn | grep <port>
   ```

   Try a different host port or stop the service using the conflicting port. 