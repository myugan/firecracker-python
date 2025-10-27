#!/usr/bin/env python3
"""
Example: Load MicroVM from Snapshot

This example demonstrates how to load a microVM from a snapshot with the
rootfs path override to handle cases where the snapshot was created with
a different microVM ID or on a different system.
"""

from firecracker import MicroVM

def load_snapshot_example():
    """
    Example of loading a microVM from snapshot with explicit rootfs path.
    """
    
    # Initialize MicroVM with required parameters
    microvm = MicroVM(
        name="devsecops-box",
        kernel_file="/path/to/vmlinux",
        base_rootfs="/var/lib/firecracker/devsecops-box.img",
        vcpu=2,
        memory=2048,
        ip_addr="172.16.0.10",
        verbose=True
    )
    
    # Option 1: Load snapshot with automatic rootfs path detection
    # The library will automatically use the correct rootfs path
    result = microvm.create(
        snapshot=True,
        memory_path="/var/lib/firecracker/snapshots/restuhaqza/devsecops-box-ous03sz1/memory",
        snapshot_path="/var/lib/firecracker/snapshots/restuhaqza/devsecops-box-ous03sz1/snapshot"
    )
    
    print(f"Result: {result}")


def load_snapshot_with_explicit_rootfs():
    """
    Example of loading a microVM from snapshot with explicit rootfs path override.
    This is useful when you want to use a different rootfs than what was used
    when the snapshot was created.
    """
    
    microvm = MicroVM(
        name="devsecops-box",
        kernel_file="/path/to/vmlinux",
        base_rootfs="/var/lib/firecracker/devsecops-box-v2.img",  # Different from snapshot
        vcpu=2,
        memory=2048,
        ip_addr="172.16.0.10",
        verbose=True
    )
    
    # Option 2: Explicitly specify the rootfs path to use
    result = microvm.create(
        snapshot=True,
        memory_path="/var/lib/firecracker/snapshots/restuhaqza/devsecops-box-ous03sz1/memory",
        snapshot_path="/var/lib/firecracker/snapshots/restuhaqza/devsecops-box-ous03sz1/snapshot",
        rootfs_path="/var/lib/firecracker/devsecops-box-v2.img"  # Override the path
    )
    
    print(f"Result: {result}")


def load_snapshot_with_overlayfs():
    """
    Example of loading a microVM from snapshot with overlayfs configuration.
    The library will automatically use base_rootfs when overlayfs is enabled.
    """
    
    microvm = MicroVM(
        name="devsecops-box",
        kernel_file="/path/to/vmlinux",
        base_rootfs="/var/lib/firecracker/base-rootfs.img",
        overlayfs=True,
        overlayfs_file="/var/lib/firecracker/overlay.ext4",
        vcpu=2,
        memory=2048,
        ip_addr="172.16.0.10",
        verbose=True
    )
    
    # With overlayfs, the library automatically uses base_rootfs as the rootfs path
    result = microvm.create(
        snapshot=True,
        memory_path="/var/lib/firecracker/snapshots/restuhaqza/devsecops-box-ous03sz1/memory",
        snapshot_path="/var/lib/firecracker/snapshots/restuhaqza/devsecops-box-ous03sz1/snapshot"
    )
    
    print(f"Result: {result}")


def agent_integration_example():
    """
    Example of how to integrate this in the udaan-agent code.
    This shows the typical flow used in the agent.
    """
    
    # Agent configuration
    microvm_id = "devsecops-box-ous03sz1"
    machine_name = "devsecops-box"
    rootfs_path = "/var/lib/firecracker/devsecops-box.img"
    snapshot_dir = f"/var/lib/firecracker/snapshots/restuhaqza/{microvm_id}"
    
    try:
        # Initialize MicroVM
        microvm = MicroVM(
            name=machine_name,
            kernel_file="/var/lib/firecracker/vmlinux",
            base_rootfs=rootfs_path,
            vcpu=2,
            memory=2048,
            ip_addr="172.16.0.10",
            verbose=True
        )
        
        # Load from snapshot
        # The rootfs_path parameter ensures the correct file is used
        # even if the snapshot was created with a different VMM ID
        result = microvm.create(
            snapshot=True,
            memory_path=f"{snapshot_dir}/memory",
            snapshot_path=f"{snapshot_dir}/snapshot",
            rootfs_path=rootfs_path  # Explicitly provide the rootfs path
        )
        
        print(f"✓ Snapshot loaded successfully: {result}")
        return True
        
    except FileNotFoundError as e:
        print(f"✗ File not found: {e}")
        return False
    except Exception as e:
        print(f"✗ Failed to load snapshot: {e}")
        return False


if __name__ == "__main__":
    print("Example 1: Load snapshot with automatic rootfs detection")
    print("=" * 60)
    # load_snapshot_example()
    
    print("\n\nExample 2: Load snapshot with explicit rootfs override")
    print("=" * 60)
    # load_snapshot_with_explicit_rootfs()
    
    print("\n\nExample 3: Load snapshot with overlayfs")
    print("=" * 60)
    # load_snapshot_with_overlayfs()
    
    print("\n\nExample 4: Agent integration pattern")
    print("=" * 60)
    print("This is the recommended pattern for udaan-agent:")
    print("""
    microvm = MicroVM(
        name=machine_name,
        kernel_file=kernel_path,
        base_rootfs=rootfs_path,  # Current/correct rootfs path
        vcpu=vcpu_count,
        memory=memory_size,
        ip_addr=ip_address,
        verbose=True
    )
    
    result = microvm.create(
        snapshot=True,
        memory_path=memory_file,
        snapshot_path=snapshot_file,
        rootfs_path=rootfs_path  # Override the snapshot's saved path
    )
    """)

