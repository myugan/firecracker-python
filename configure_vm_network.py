#!/usr/bin/env python3
"""
Configure Firecracker VM networking.

This script demonstrates how to create a Firecracker VM and configure its networking
both automatically (using the modified boot args) and manually (using execute_in_vm).
"""

import time
import sys
from firecracker.microvm import MicroVM
from firecracker.vmm import VMMManager
from firecracker.exceptions import VMMError

def create_vm_with_network():
    """Create a new VM with networking enabled and configured."""
    print("Creating new VM with networking enabled...")
    vmm = MicroVM(
        name="network-test-vm",
        enable_nat=True,  # Enable NAT for internet access
        verbose=True      # Enable verbose logging
    )
    
    # Create the VM
    result = vmm.create()
    print(f"VM creation result: {result}")
    
    # Get the VM ID
    vm_id = vmm._microvm_id
    print(f"VM ID: {vm_id}")
    
    # Wait for the VM to boot
    print("Waiting for VM to boot (10 seconds)...")
    time.sleep(10)
    
    # Try to manually configure network in case auto-config with DHCP fails
    print("Manually configuring network...")
    commands = [
        "ip addr",                                      # Show current addresses
        "ip addr add 172.16.0.2/24 dev eth0",          # Add IP to eth0
        "ip link set eth0 up",                          # Bring up eth0
        "ip route add default via 172.16.0.1 dev eth0", # Add default route
        "ip addr",                                      # Show updated addresses
        "ip route"                                      # Show updated routes
    ]
    
    try:
        vmm.execute_in_vm(commands=commands)
        print("Network commands executed in VM")
    except VMMError as e:
        print(f"Error executing commands: {e}")
    
    # Print connection information
    print("\nVM Network Information:")
    print(f"VM IP Address: 172.16.0.2")
    print(f"Host Address: 172.16.0.1")
    print("\nTo connect to the VM using screen:")
    print(f"  screen -r fc_{vm_id}")
    print("\nTo detach from the screen session (leave VM running):")
    print("  Press Ctrl+A then Ctrl+D")
    
    return vm_id

def connect_to_existing_vm(vm_id):
    """Connect to an existing VM and configure its network."""
    print(f"Connecting to existing VM {vm_id}...")
    vmm = MicroVM()
    
    # Configure network manually
    print("Manually configuring network...")
    commands = [
        "ip addr add 172.16.0.2/24 dev eth0",
        "ip link set eth0 up",
        "ip route add default via 172.16.0.1 dev eth0",
        "echo 'Network configured'"
    ]
    
    try:
        vmm.execute_in_vm(id=vm_id, commands=commands)
        print("Network commands executed in VM")
    except VMMError as e:
        print(f"Error executing commands: {e}")
    
    # Print SSH connection info
    print("\nTo connect to the VM via SSH (once networking is configured):")
    print(f"  ssh -i /path/to/your/ssh_key root@172.16.0.2")

if __name__ == "__main__":
    # Check if VM ID is provided as argument
    if len(sys.argv) > 1:
        vm_id = sys.argv[1]
        connect_to_existing_vm(vm_id)
    else:
        # Create new VM
        vm_id = create_vm_with_network() 