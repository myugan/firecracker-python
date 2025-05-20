#!/usr/bin/env python3

from firecracker import MicroVM
import time
import requests

def create_test_vm():
    """Create a test MicroVM with DNS configuration."""
    # User data with DNS configuration
    user_data = """
#cloud-config
runcmd:
  - |
    bash -c 'cat > /etc/systemd/resolved.conf <<EOF
    [Resolve]
    DNS=8.8.8.8 8.8.4.4
    FallbackDNS=1.1.1.1 1.0.0.1
    EOF'
  - systemctl restart systemd-resolved
"""

    # Create VM configuration
    vm = MicroVM(
        id='test-vm',
        enable_nat=True,
        ip_addr='172.16.0.2',
        mmds_enabled=True,
        user_data=user_data,
        verbose=True  # Enable verbose logging
    )

    try:
        # Create and start the VM
        print("Creating VM...")
        vm.create()
        
        # Wait for VM to boot
        print("Waiting for VM to boot...")
        time.sleep(10)  # Adjust this time based on your VM's boot time

        # Verify MMDS data
        print("\nVerifying MMDS data...")
        try:
            # First get a token
            token_response = requests.put(
                'http://169.254.169.254/latest/api/token',
                headers={'X-metadata-token-ttl-seconds': '21600'}
            )
            token = token_response.text

            # Then use the token to access user data
            response = requests.get(
                'http://169.254.169.254/latest/user-data',
                headers={'X-metadata-token': token}
            )
            print(f"MMDS user-data response: {response.text}")
        except requests.exceptions.RequestException as e:
            print(f"Could not access MMDS: {e}")
            print("This might be normal as MMDS access depends on network setup")
        
        # Connect to VM and verify DNS configuration
        print("\nConnecting to VM...")
        vm.connect(
            key_path='/root/ubuntu-24.04',  # Update this path to your SSH key
            id='test-vm'
        )
        
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        # Clean up
        print("\nCleaning up...")
        vm.delete()

if __name__ == "__main__":
    create_test_vm() 