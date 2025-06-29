import os
import json
import random
import string
import pytest
from firecracker import MicroVM
from firecracker.vmm import VMMManager
from firecracker.network import NetworkManager
from firecracker.exceptions import VMMError, NetworkError
from firecracker.utils import generate_id, validate_ip_address

KERNEL_FILE = "/var/lib/firecracker/vmlinux-6.1.0"
BASE_ROOTFS = "/var/lib/firecracker/devsecops-box.img"

@pytest.fixture(autouse=True)
def teardown():
    """Ensure all VMs are cleaned up after tests.
    This fixture is automatically applied to all tests."""
    yield
    vm = MicroVM(kernel_file=KERNEL_FILE, base_rootfs=BASE_ROOTFS, verbose=True)
    vm.delete(all=True)


def generate_random_id(length=8):
    """Generate a random alphanumeric ID of specified length."""
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))


def test_create_with_invalid_rootfs_path():
    """Test VM creation with invalid rootfs path"""
    with pytest.raises(FileNotFoundError, match=r"Base rootfs file not found:"):
        MicroVM(kernel_file=KERNEL_FILE, base_rootfs="/invalid/path/to/rootfs")


def test_create_with_invalid_kernel_file():
    """Test VM creation with missing kernel file"""
    with pytest.raises(FileNotFoundError, match=r"Kernel file not found:"):
        MicroVM(kernel_file="/nonexistent/kernel", base_rootfs=BASE_ROOTFS)


def test_create_with_invalid_docker_image():
    """Test VM creation with invalid Docker image"""
    with pytest.raises(VMMError, match=r"Failed to check if Docker image invalid-image is valid:"):
        MicroVM(image="invalid-image", base_rootfs=BASE_ROOTFS)


def test_create_with_missing_base_rootfs_for_docker():
    """Test VM creation with Docker image but missing base_rootfs"""
    with pytest.raises(ValueError, match=r"base_rootfs is required when image is provided"):
        MicroVM(image="ubuntu:latest")


def test_create_with_kernel_url_missing_kernel_file():
    """Test VM creation with kernel URL but missing kernel file"""
    with pytest.raises(ValueError, match=r"kernel_file is required when kernel_url is provided"):
        MicroVM(kernel_url="https://example.com/kernel")


def test_create_with_both_user_data_and_user_data_file():
    """Test VM creation with both user_data and user_data_file"""
    with pytest.raises(ValueError, match=r"Cannot specify both user_data and user_data_file"):
        MicroVM(user_data="test", user_data_file="/tmp/test")


def test_create_with_invalid_user_data_file():
    """Test VM creation with invalid user data file"""
    with pytest.raises(ValueError, match=r"User data file not found:"):
        MicroVM(user_data_file="/nonexistent/file")


def test_delete_all_with_no_vms():
    """Test delete all VMs when no VMs exist"""
    vm = MicroVM(kernel_file=KERNEL_FILE, base_rootfs=BASE_ROOTFS)
    result = vm.delete(all=True)
    assert "No VMMs available to delete" in result


def test_delete_non_existent_vm():
    """Test deleting a non-existent VM"""
    vm = MicroVM(kernel_file=KERNEL_FILE, base_rootfs=BASE_ROOTFS)
    result = vm.delete(id="nonexistent")
    assert "No VMMs available to delete" in result


def test_filter_vmm_by_labels():
    """Test filtering VMMs by labels."""
    labels1 = {'env': 'test', 'version': '1.0'}
    vm1 = MicroVM(kernel_file=KERNEL_FILE, base_rootfs=BASE_ROOTFS, ip_addr='172.22.0.2', labels=labels1)

    result = vm1.create()
    id = vm1.inspect()['ID']
    assert f"VMM {id} created" in result

    labels = {'env': 'prod', 'version': '2.0'}
    vm2 = MicroVM(kernel_file=KERNEL_FILE, base_rootfs=BASE_ROOTFS, ip_addr='172.22.0.3', labels=labels)

    result = vm2.create()
    id = vm2.inspect()['ID']
    assert f"VMM {id} created" in result

    filtered_vms_test = vm1.find(state='Running', labels=labels1)
    assert len(filtered_vms_test) == 1, "Expected one VMM to be filtered by test labels"

    filtered_vms_prod = vm2.find(state='Running', labels=labels)
    assert len(filtered_vms_prod) == 1, "Expected one VMM to be filtered by prod labels"


def test_vmm_labels_match():
    """Test inspecting VMMs by labels."""
    vm = MicroVM(kernel_file=KERNEL_FILE, base_rootfs=BASE_ROOTFS,ip_addr='172.22.0.2', labels={'env': 'test', 'version': '1.0'})

    result = vm.create()
    id = vm.list()[0]['id']
    assert f"VMM {id} created" in result

    vm = vm.find(state='Running', labels={'env': 'test', 'version': '1.0'})
    assert vm is not None, f"VM not found: {vm}"

def test_get_gateway_ip():
    """Test deriving gateway IP from a given IP address."""
    network_manager = NetworkManager()

    valid_ip = "192.168.1.10"
    expected_gateway_ip = "192.168.1.1"
    assert network_manager.get_gateway_ip(valid_ip) == expected_gateway_ip

    invalid_ips = [
        "256.1.2.3",        # Invalid octet
        "192.168.1",        # Incomplete
        "192.168.1.0.1",    # Too many octets
        "invalid.ip",       # Invalid format
    ]

    for ip in invalid_ips:
        with pytest.raises(NetworkError):
            network_manager.get_gateway_ip(ip)


def test_validate_ip_address():
    """Test IP address validation."""
    valid_ips = [
        "192.168.1.1",
        "10.0.0.1",
        "172.16.0.1"
    ]

    for ip in valid_ips:
        assert validate_ip_address(ip) is True

    invalid_ips = [
        "256.1.2.3",  # Invalid octet
        "192.168.1",  # Incomplete
        "192.168.1.0.1",  # Too many octets
        "invalid.ip",  # Invalid format
        "192.168.1.0"  # Reserved address
    ]

    for ip in invalid_ips:
        with pytest.raises(Exception):
            validate_ip_address(ip)


def test_vmm_config():
    """Test getting VM configuration"""
    vm = MicroVM(ip_addr="172.30.0.2", kernel_file=KERNEL_FILE, base_rootfs=BASE_ROOTFS)
    vm.create()
    
    config = vm.config()
    assert config['machine-config']['vcpu_count'] == 1
    assert config['machine-config']['mem_size_mib'] == 512


def test_vmm_create():
    """Test VM creation and deletion."""
    vm = MicroVM(kernel_file=KERNEL_FILE, base_rootfs=BASE_ROOTFS)
    result = vm.create()
    id = vm.list()[0]['id']
    assert f"VMM {id} created" in result


def test_vmm_create_multiple_vms():
    """Test creating multiple VMs and verify their creation."""
    num_vms = 3
    created_vms = []

    for i in range(num_vms):
        unique_ip = f"172.{20 + i}.0.2"

        vm = MicroVM(ip_addr=unique_ip, kernel_file=KERNEL_FILE, base_rootfs=BASE_ROOTFS)

        result = vm.create()
        id = vm.list()[0]['id']
        assert id is not None, f"VM creation failed: {result}"

        config_path = f"/var/lib/firecracker/{vm._microvm_id}/config.json"
        assert os.path.exists(config_path), f"config.json not found at {config_path}"

        created_vms.append(vm)

    assert len(created_vms) == num_vms, f"Expected {num_vms} VMs to be created, but only {len(created_vms)} were created"


def test_vmm_creation_with_valid_arguments():
    """Test VM creation with valid arguments"""
    vm = MicroVM(
        ip_addr="172.16.0.10",
        vcpu=1,
        memory=1024,
        kernel_file=KERNEL_FILE,
        base_rootfs=BASE_ROOTFS
    )
    result = vm.create()
    id = vm.list()[0]['id']
    assert id is not None, f"VM creation failed: {result}"
    assert vm._vcpu == 1
    assert vm._memory == 1024
    assert vm._ip_addr == "172.16.0.10"


def test_vmm_creation_with_invalid_resources():
    """Test VM creation with invalid VCPU count and memory"""
    with pytest.raises(ValueError, match="vcpu must be a positive integer"):
        MicroVM(vcpu=-1, kernel_file=KERNEL_FILE, base_rootfs=BASE_ROOTFS)

    with pytest.raises(ValueError, match="vcpu must be a positive integer"):
        MicroVM(vcpu=0, kernel_file=KERNEL_FILE, base_rootfs=BASE_ROOTFS)


def test_vmm_creation_with_valid_ip_ranges():
    """Test VM creation with various valid IP ranges"""
    valid_ips = [
        "172.16.0.14",      # Private Class B
        "192.168.1.15",    # Private Class C
        "10.0.0.16",        # Private Class A
        "169.254.1.17",     # Link-local address
    ]

    for ip in valid_ips:
        vm = MicroVM(ip_addr=ip, kernel_file=KERNEL_FILE, base_rootfs=BASE_ROOTFS)
        assert vm._ip_addr == ip

        # Verify gateway IP derivation
        gateway_parts = ip.split('.')
        gateway_parts[-1] = '1'
        expected_gateway = '.'.join(gateway_parts)
        assert vm._gateway_ip == expected_gateway, f"Expected gateway IP {expected_gateway}, got {vm._gateway_ip}"


def test_vmm_list():
    vm = MicroVM(ip_addr="172.16.0.2", kernel_file=KERNEL_FILE, base_rootfs=BASE_ROOTFS)
    result = vm.create()
    id = vm.list()[0]['id']
    assert id is not None, f"VM creation failed: {result}"

    vms = vm.list()
    assert len(vms) == 1, "VM list should contain exactly one VM"
    assert vms[0]['ip_addr'] == '172.16.0.2', "VM IP address should match the created IP address"


def test_vmm_pause_resume():
    """Test VM pause and resume functionality"""
    vm = MicroVM(ip_addr="172.16.0.2", kernel_file=KERNEL_FILE, base_rootfs=BASE_ROOTFS)
    result = vm.create()
    id = vm.list()[0]['id']
    assert id is not None, f"VM creation failed: {result}"

    id = vm.list()[0]['id']
    result = vm.pause()
    assert f"VMM {id} paused successfully" in result

    result = vm.resume()
    assert f"VMM {id} resumed successfully" in result


def test_vmm_json_file_exists():
    """Test if VMM JSON configuration file exists and has correct content"""
    ip_addr = "192.168.1.100"
    vm = MicroVM(ip_addr=ip_addr, kernel_file=KERNEL_FILE, base_rootfs=BASE_ROOTFS)
    vm.create()
    
    id = vm.list()[0]['id']
    json_path = f"{vm._config.data_path}/{id}/config.json"

    # Verify the JSON file exists
    assert os.path.exists(json_path), "JSON configuration file was not created"

    # Load and verify the JSON content
    with open(json_path, 'r') as json_file:
        config_data = json.load(json_file)
        assert config_data['ID'] == id, "VMM ID does not match"
        assert config_data['Network'][f"tap_{id}"]['IPAddress'] == ip_addr, "VMM IP address does not match"


def test_pause_resume_vm():
    """Test pausing and resuming a VM"""
    vm = MicroVM(ip_addr="172.16.0.2", kernel_file=KERNEL_FILE, base_rootfs=BASE_ROOTFS)
    vm.create()
    vm_id = vm.list()[0]['id']

    # Pause the VM
    result = vm.pause(id=vm_id)
    assert f"VMM {vm_id} paused successfully" in result

    # Resume the VM
    result = vm.resume(id=vm_id)
    assert f"VMM {vm_id} resumed successfully" in result


def test_ip_address_overlap():
    """Test IP address overlap"""
    vm = MicroVM(kernel_file=KERNEL_FILE, base_rootfs=BASE_ROOTFS)
    result = vm.create()
    id = vm.list()[0]['id']

    assert f"VMM {id} created" in result

    vm = MicroVM(kernel_file=KERNEL_FILE, base_rootfs=BASE_ROOTFS)
    result = vm.create()

    assert f"IP address 172.16.0.2 is already in use" in result


def test_network_conflict_detection():
    """Test network conflict detection"""
    network_manager = NetworkManager()
    
    # Test CIDR conflict detection
    ip_addr = "172.16.0.2"
    has_conflict = network_manager.detect_cidr_conflict(ip_addr, 24)
    assert isinstance(has_conflict, bool)
    
    # Test non-conflicting IP suggestion
    suggested_ip = network_manager.suggest_non_conflicting_ip(ip_addr, 24)
    assert isinstance(suggested_ip, str)
    assert suggested_ip != ip_addr


def test_port_forwarding():
    """Test port forwarding for a VM"""
    vm = MicroVM(kernel_file=KERNEL_FILE, base_rootfs=BASE_ROOTFS)
    vm.create()
    id = vm.list()[0]['id']

    host_port = 8080
    dest_port = 80

    # Add port forwarding
    result = vm.port_forward(host_port=host_port, dest_port=dest_port)
    assert f"Port forwarding added successfully for VMM {id}" in result

    # Remove port forwarding
    result = vm.port_forward(host_port=host_port, dest_port=dest_port, remove=True)
    assert f"Port forwarding removed successfully for VMM {id}" in result


def test_port_forwarding_existing_vmm():
    """Test port forwarding for an existing VMM"""
    vm = MicroVM(kernel_file=KERNEL_FILE, base_rootfs=BASE_ROOTFS)
    vm.create()
    id = vm.list()[0]['id']
    config = f"{vm._config.data_path}/{id}/config.json"
    
    vm.port_forward(host_port=10222, dest_port=22)
    with open(config, 'r') as file:
        config = json.load(file)
        expected_ports = {
            "22/tcp": [
                {
                    "HostPort": 10222,
                    "DestPort": 22
                }
            ]
        }
        assert config['Ports'] == expected_ports


def test_port_forwarding_remove_existing_port():
    """Test port forwarding removal for an existing VMM"""
    vm = MicroVM(kernel_file=KERNEL_FILE, base_rootfs=BASE_ROOTFS, ip_addr="172.16.0.2", expose_ports=True, host_port=10222, dest_port=22)
    vm.create()
    id = vm.list()[0]['id']
    config = f"{vm._config.data_path}/{id}/config.json"
    
    vm.port_forward(id=id, host_port=10222, dest_port=22, remove=True)
    with open(config, 'r') as file:
        config = json.load(file)
        assert '22/tcp' not in config['Ports']


def test_list_vmm():
    """Test listing VMMs from config files"""
    vmm_manager = VMMManager()
    vmm_list = vmm_manager.list_vmm()
    assert isinstance(vmm_list, list)


def test_find_vmm_by_id():
    """Test finding a VMM by ID"""
    vmm_manager = VMMManager()
    vmm_id = "some_id"
    result = vmm_manager.find_vmm_by_id(vmm_id)
    assert isinstance(result, str)


def test_vmm_expose_single_port():
    """Test exposing a single port to the host"""
    vm = MicroVM(ip_addr="172.20.0.2", expose_ports=True, host_port=10024, dest_port=22, kernel_file=KERNEL_FILE, base_rootfs=BASE_ROOTFS)
    vm.create()
    id = vm.list()[0]['id']
    json_path = f"{vm._config.data_path}/{id}/config.json"
    with open(json_path, 'r') as json_file:
        config_data = json.load(json_file)
        expected_ports = {
            '22/tcp': [
                {
                    'HostPort': 10024,
                    'DestPort': 22
                }
            ]
        }
        assert config_data['Ports'] == expected_ports


def test_vmm_expose_multiple_ports():
    """Test exposing multiple ports to the host"""
    vm = MicroVM(ip_addr="172.21.0.2", expose_ports=True, host_port=[10024, 10025], dest_port=[22, 80], kernel_file=KERNEL_FILE, base_rootfs=BASE_ROOTFS)
    vm.create()
    id = vm.list()[0]['id']
    json_path = f"{vm._config.data_path}/{id}/config.json"
    with open(json_path, 'r') as json_file:
        config_data = json.load(json_file)
        expected_ports = {
            '22/tcp': [
                {
                    'HostPort': 10024,
                    'DestPort': 22
                }
            ],
            '80/tcp': [
                {
                    'HostPort': 10025,
                    'DestPort': 80
                }
            ]
        }
        assert config_data['Ports'] == expected_ports


def test_vmm_delete():
    """Test VM deletion using the VM name"""
    vm = MicroVM(ip_addr="172.16.0.32", kernel_file=KERNEL_FILE, base_rootfs=BASE_ROOTFS)
    vm.create()

    # Extract the dynamic ID from the creation result
    list_result = vm.list()
    id = list_result[0]['id']

    # Verify the VM is listed with the dynamic ID and name
    assert len(list_result) == 1, "There should be exactly one VM listed"
    assert list_result[0]['id'] == id, f"Expected VM ID {id}, but got {list_result[0]['id']}"

    # Check if config.json exists before deletion
    config_path = f"/var/lib/firecracker/{id}/config.json"
    assert os.path.exists(config_path), f"config.json not found at {config_path}, cannot proceed with deletion"

    # Delete the VM using the name
    delete_result = vm.delete()
    assert f"VMM {id} is deleted" in delete_result, f"Unexpected delete result: {delete_result}"

    # Verify the VM is no longer listed
    list_result = vm.list()
    assert len(list_result) == 0, "VM should be deleted and not listed"


def test_vmm_delete_all():
    """Test deletion of all VMs using real VMMs"""
    vm = MicroVM(kernel_file=KERNEL_FILE, base_rootfs=BASE_ROOTFS, ip_addr="172.19.0.2")
    vm.create()
    vm = MicroVM(kernel_file=KERNEL_FILE, base_rootfs=BASE_ROOTFS, ip_addr="172.20.0.2")
    vm.create()

    vms = vm.list()
    assert len(vms) >= 2

    result = vm.delete(all=True)
    assert "All VMMs are deleted" in result

    vms = vm.list()
    assert len(vms) == 0


def test_vmm_delete_with_tap_device_cleanup():
    """Test VMM deletion when tap network is deleted manually."""
    vm = MicroVM(ip_addr="172.21.0.2", kernel_file=KERNEL_FILE, base_rootfs=BASE_ROOTFS)
    vm.create()

    list_result = vm.list()
    id = list_result[0]['id']

    tap_device_name = f"tap_{id}"
    vm._network.delete_tap(tap_device_name)

    result = vm.delete()
    assert f"VMM {id} is deleted" in result, f"VM deletion failed: {result}"


def test_vmm_with_mmds():
    """Test VM creation with MMDS enabled"""
    vm = MicroVM(
        kernel_file=KERNEL_FILE,
        base_rootfs=BASE_ROOTFS,
        ip_addr="172.16.0.2",
        mmds_enabled=True,
        mmds_ip="169.254.169.254"
    )
    result = vm.create()
    id = vm.list()[0]['id']
    assert f"VMM {id} created" in result

    config = vm.config()
    assert config['mmds-config']['version'] == "V2"
    assert config['mmds-config']['ipv4_address'] == "169.254.169.254"
    assert config['mmds-config']['network_interfaces'] == ["eth0"]


def test_memory_size_conversion():
    """Test memory size conversion functionality"""
    vm = MicroVM(kernel_file=KERNEL_FILE, base_rootfs=BASE_ROOTFS)
    
    # Test various memory size formats
    test_cases = [
        ("512", 512),
        ("512M", 512),
        ("1G", 1024),
        ("2G", 2048),
    ]
    
    for input_size, expected_mb in test_cases:
        vm._memory = int(vm._convert_memory_size(input_size))
        assert vm._memory == expected_mb


def test_network_manager_interface_detection():
    """Test network interface detection"""
    network_manager = NetworkManager()
    
    # Test interface name detection (may fail in test environment)
    try:
        iface_name = network_manager.get_interface_name()
        assert isinstance(iface_name, str)
        assert len(iface_name) > 0
    except RuntimeError:
        # This is expected in some test environments
        pass


def test_nftables_availability():
    """Test nftables availability detection"""
    network_manager = NetworkManager()
    
    # Test nftables availability check
    is_available = network_manager.is_nftables_available()
    assert isinstance(is_available, bool)


def test_vmm_manager_config_file_creation():
    """Test VMM manager config file creation"""
    vmm_manager = VMMManager()
    test_id = generate_id()
    test_ip = "172.16.0.2"
    
    config_path = vmm_manager.create_vmm_json_file(
        test_id,
        IPAddress=test_ip
    )
    
    assert os.path.exists(config_path)
    
    # Clean up
    os.remove(config_path)
    os.rmdir(os.path.dirname(config_path))


def test_network_overlap_check():
    """Test network overlap checking"""
    vmm_manager = VMMManager()
    
    # Test overlap detection
    has_overlap = vmm_manager.check_network_overlap("172.16.0.2")
    assert isinstance(has_overlap, bool)
