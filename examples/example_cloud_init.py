import os
import time
from firecracker import MicroVM

# Ensure the examples directory exists for creating a dummy user-data file
if not os.path.exists("examples"):
    os.makedirs("examples")

# --- Example 1: User data as a string ---
print("--- Example 1: User data as a string ---")
user_data_string = '''#cloud-config
packages:
  - net-tools
runcmd:
  - echo "Hello from cloud-init (string)!" > /tmp/cloud_init_test_string.txt
  - ifconfig > /tmp/ifconfig_string.txt
'''

vm_string = MicroVM(
    name="cloud-init-vm-string",
    user_data=user_data_string,
    verbose=True
)
try:
    print("Creating VM with string user data...")
    vm_string.create()
    print(f"VM '{vm_string._microvm_name}' created with ID: {vm_string._microvm_id}")
    print("Waiting 30 seconds for cloud-init to run...")
    time.sleep(30)  # Give cloud-init some time to run
    
    print(f"To check inside the VM (ID: {vm_string._microvm_id}):")
    print(f"  screen -r fc_{vm_string._microvm_id}")
    print("  Then check for '/tmp/cloud_init_test_string.txt' and ")
    print("  '/tmp/ifconfig_string.txt'")
    print("  And try running 'ifconfig' (net-tools should be installed).")
    print("Pausing for review. Press Enter to continue and delete the VM...")
    input()

finally:
    print(f"Deleting VM '{vm_string._microvm_name}'...")
    vm_string.delete()
    print("VM deleted.")

print("\\n--- Example 2: User data from a file ---")
user_data_file_content = '''#cloud-config
write_files:
  - path: /tmp/cloud_init_test_file.txt
    content: |
      Hello from cloud-init (file)!
      This file was written by cloud-init.
packages:
  - curl
runcmd:
  - curl -V > /tmp/curl_version_file.txt
'''
user_data_filename = "examples/sample-user-data.yaml"
with open(user_data_filename, "w") as f:
    f.write(user_data_file_content)

vm_file = MicroVM(
    name="cloud-init-vm-file",
    user_data_file=user_data_filename,
    verbose=True
)
try:
    print("Creating VM with user data from file...")
    vm_file.create()
    print(f"VM '{vm_file._microvm_name}' created with ID: {vm_file._microvm_id}")
    print("Waiting 30 seconds for cloud-init to run...")
    time.sleep(30)  # Give cloud-init some time to run

    print(f"To check inside the VM (ID: {vm_file._microvm_id}):")
    print(f"  screen -r fc_{vm_file._microvm_id}")
    print("  Then check for '/tmp/cloud_init_test_file.txt' and ")
    print("  '/tmp/curl_version_file.txt'")
    print("  And try running 'curl --version' (curl should be installed).")
    print("Pausing for review. Press Enter to continue and delete the VM...")
    input()

finally:
    print(f"Deleting VM '{vm_file._microvm_name}'...")
    vm_file.delete()
    if os.path.exists(user_data_filename):
        os.remove(user_data_filename)
    print("VM and sample user data file deleted.")

print("\\nBoth examples complete.")
print("NOTE: You will need a compatible kernel and rootfs for cloud-init to work.")
print("Typically, cloud images (e.g., Ubuntu cloud image) have cloud-init")
print("pre-installed.") 