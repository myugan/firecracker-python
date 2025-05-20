import os
import json
import random
import string
import pytest
from faker import Faker
from firecracker import MicroVM
from firecracker.vmm import VMMManager
from firecracker.network import NetworkManager
from firecracker.exceptions import VMMError

faker = Faker()

@pytest.fixture(autouse=True)
def teardown():
    """Ensure all VMs are cleaned up after tests.
    This fixture is automatically applied to all tests."""
    yield
    vm = MicroVM(verbose=True)
    vm.delete(all=True)


def generate_unique_name():
    """Generate a unique name for each test."""
    return faker.name()


def generate_random_id(length=8):
    """Generate a random alphanumeric ID of specified length."""
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))


def test_create_with_invalid_rootfs_path():
    """Test VM creation with invalid rootfs path"""
    vm = MicroVM(base_rootfs="/invalid/path/to/rootfs")
    with pytest.raises(VMMError, match=r"Failed to configure root drive"):
        vm.create()


def test_create_with_invalid_rootfs_url():
    """Test VM creation with invalid rootfs URL"""
    urls = ["https://invalid-url", "invalid-url"]

    for url in urls:
        with pytest.raises(Exception):
            MicroVM(rootfs_url=url)


def test_create_with_missing_kernel_file():
    """Test VM creation with missing kernel file"""
    vm = MicroVM(kernel_file="/nonexistent/kernel")
    with pytest.raises(ValueError, match=r"Kernel file not found:"):
        vm.create()


def test_delete_all_with_no_vms():
    """Test delete all VMs when no VMs exist"""
    vm = MicroVM()
    result = vm.delete(all=True)
    assert "No VMMs available to delete" in result


def test_delete_non_existent_vm():
    """Test deleting a non-existent VM"""
    vm = MicroVM()
    result = vm.delete(id="nonexistent")
    assert "No VMMs available to delete" in result


def test_filter_vmm_by_labels():
    """Test filtering VMMs by labels."""
    labels1 = {'env': 'test', 'version': '1.0'}
    labels2 = {'env': 'prod', 'version': '2.0'}
    vm1 = MicroVM(name='test-labels-1', ip_addr='172.22.0.2', labels=labels1)
    vm2 = MicroVM(name='test-labels-2', ip_addr='172.22.0.3', labels=labels2)

    result1 = vm1.create()
    assert "created successfully" in result1

    result2 = vm2.create()
    assert "created successfully" in result2

    filtered_vms_test = vm1.find(state='Running', labels=labels1)
    assert len(filtered_vms_test) == 1, "Expected one VMM to be filtered by test labels"
    assert filtered_vms_test[0]['name'] == 'test-labels-1', "Filtered VMM name should match for test labels"

    filtered_vms_prod = vm2.find(state='Running', labels=labels2)
    assert len(filtered_vms_prod) == 1, "Expected one VMM to be filtered by prod labels"
    assert filtered_vms_prod[0]['name'] == 'test-labels-2', "Filtered VMM name should match for prod labels"


def test_vmm_labels_match():
    """Test inspecting VMMs by labels."""
    vm = MicroVM(name='test-labels-1', ip_addr='172.22.0.2', labels={'env': 'test', 'version': '1.0'})

    result = vm.create()
    assert "created successfully" in result

    vm_id = vm.list()[0]['id']
    vmm_config = vm.inspect(id=vm_id)
    assert vmm_config['Labels'] == {'env': 'test', 'version': '1.0'}, "VMM labels should match the expected test labels"


def test_get_gateway_ip():
    """Test deriving gateway IP from a given IP address."""
    from firecracker.network import NetworkManager

    network_manager = NetworkManager()  # Create an instance of NetworkManager

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
        with pytest.raises(Exception):
            network_manager.get_gateway_ip(ip)


def test_validate_ip_address():
    """Test IP address validation."""
    from firecracker.utils import validate_ip_address

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
    vm = MicroVM(name="test123", ip_addr="172.30.0.2")
    vm.create()
    
    config = vm.config()
    assert config['machine-config']['vcpu_count'] == 1
    assert config['machine-config']['mem_size_mib'] == 512


def test_vmm_create():
    """Test VM creation and deletion."""
    name = "test123"
    vm = MicroVM(name=name, ip_addr="172.18.0.12")
    vm.create()
    vms = vm.list()
    assert any(v['name'] == name for v in vms), "VM not found in list after creation"
    
    # Check if config.json exists
    config_path = f"/var/lib/firecracker/{vm._microvm_id}/config.json"
    assert os.path.exists(config_path), f"config.json not found at {config_path}"


def test_vmm_create_multiple_vms():
    """Test creating multiple VMs and verify their creation."""
    num_vms = 3
    created_vms = []

    for i in range(num_vms):
        name = generate_unique_name()
        unique_ip = f"172.{20 + i}.0.2"

        vm = MicroVM(name=name, ip_addr=unique_ip, verbose=True)

        result = vm.create()
        assert f"VMM {vm._microvm_id} is created successfully" in result

        # Check if config.json exists for each VM
        config_path = f"/var/lib/firecracker/{vm._microvm_id}/config.json"
        assert os.path.exists(config_path), f"config.json not found at {config_path}"

        created_vms.append(vm)

    assert len(created_vms) == num_vms, f"Expected {num_vms} VMs to be created, but only {len(created_vms)} were created"


def test_vmm_creation_with_duplicate_name():
    """Test VM creation with duplicate name"""
    name = "test123"
    vm = MicroVM(name=name, ip_addr="172.15.0.2")
    result = vm.create()
    assert "is created successfully" in result, f"VM creation failed: {result}"

    vm = MicroVM(name=name, ip_addr="172.16.0.2")
    result = vm.create()
    assert "already exists" in result, f"VM creation failed: {result}"


def test_vmm_creation_with_valid_arguments():
    """Test VM creation with valid arguments"""
    vm = MicroVM(
        name="test789",
        ip_addr="172.16.0.10",
        vcpu=1,
        mem=1024
    )
    result = vm.create()
    assert "created successfully" in result
    assert vm._vcpu == 1
    assert vm._mem == 1024
    assert vm._ip_addr == "172.16.0.10"


def test_vmm_creation_with_invalid_resources():
    """Test VM creation with invalid VCPU count"""
    with pytest.raises(ValueError, match="vcpu must be a positive integer"):
        MicroVM(vcpu=-1)

    with pytest.raises(ValueError, match="vcpu must be a positive integer"):
        MicroVM(vcpu=0)

    with pytest.raises(ValueError, match="mem must be valid"):
        MicroVM(mem=100)


def test_vmm_creation_with_valid_ip_ranges():
    """Test VM creation with various valid IP ranges"""
    valid_ips = [
        "172.16.0.14",      # Private Class B
        "192.168.1.15",    # Private Class C
        "10.0.0.16",        # Private Class A
        "169.254.1.17",     # Link-local address
    ]

    for ip in valid_ips:
        vm = MicroVM(ip_addr=ip)
        assert vm._ip_addr == ip

        # Verify gateway IP derivation
        gateway_parts = ip.split('.')
        gateway_parts[-1] = '1'
        expected_gateway = '.'.join(gateway_parts)
        assert vm._gateway_ip == expected_gateway, f"Expected gateway IP {expected_gateway}, got {vm._gateway_ip}"


def test_vmm_creation_without_arguments():
    """Test VM creation without any arguments"""
    vm = MicroVM()
    vm.create()
    
    vms = vm.list()
    assert len(vms) == 1
    assert vms[0]['id'] is not None
    assert vms[0]['name'] is not None
    assert vms[0]['ip_addr'] == "172.16.0.2"
    assert vms[0]['state'] == "Running"


def test_vmm_name_generation():
    """Test automatic VM name generation"""
    name = generate_unique_name()
    vm = MicroVM(name=name)
    vm.create()
    list_result = vm.list()
    assert len(list_result) == 1
    assert list_result[0]['name'] == name


def test_vmm_list():
    name = "test123"
    vm = MicroVM(name=name, ip_addr="172.16.0.2")
    result = vm.create()
    assert "is created successfully" in result, f"VM creation failed: {result}"

    vms = vm.list()
    assert len(vms) == 1, "VM list should contain exactly one VM"
    assert vms[0]['name'] == name, "VM name should match the created name"
    assert vms[0]['ip_addr'] == '172.16.0.2', "VM IP address should match the created IP address"


@pytest.mark.integration
def test_vmm_pause_resume():
    """Test VM pause and resume functionality"""
    vm = MicroVM(name="test123", ip_addr="172.16.0.2")
    result = vm.create()
    assert "created successfully" in result

    id = vm.list()[0]['id']
    result = vm.pause()
    assert f"VMM {id} paused successfully" in result

    result = vm.resume()
    assert f"VMM {id} resumed successfully" in result


def test_vmm_json_file_exists():
    """Test if VMM JSON configuration file exists and has correct content"""
    name = "test_vmm"
    ip_addr = "192.168.1.100"
    vm = MicroVM(name=name, ip_addr=ip_addr)
    vm.create()
    
    id = vm.list()[0]['id']
    json_path = f"{vm._config.data_path}/{id}/config.json"

    # Verify the JSON file exists
    assert os.path.exists(json_path), "JSON configuration file was not created"

    # Load and verify the JSON content
    with open(json_path, 'r') as json_file:
        config_data = json.load(json_file)
        assert config_data['ID'] == id, "VMM ID does not match"
        assert config_data['Name'] == name, "VMM Name does not match"
        assert config_data['Network'][f"tap_{id}"]['IPAddress'] == ip_addr, "VMM IP address does not match"


def test_pause_resume_vm():
    """Test pausing and resuming a VM"""
    vm = MicroVM(name="test123", ip_addr="172.16.0.2")
    vm.create()
    vm_id = vm.list()[0]['id']

    # Pause the VM
    result = vm.pause(id=vm_id)
    assert f"VMM {vm_id} paused successfully" in result

    # Resume the VM
    result = vm.resume(id=vm_id)
    assert f"VMM {vm_id} resumed successfully" in result


# def test_connect_to_vm(mock_vm):
#     """Test connecting to a VM via SSH"""
#     vm = mock_vm
#     vm.create()
#     vm_id = vm.list()[0]['id']

#     # Assuming SSH key path and username are set correctly
#     ssh_key_path = "/root/ubuntu-24.04"
#     username = "root"

#     result = vm.connect(id=vm_id, username=username, key_path=ssh_key_path)
#     assert "SSH session to VMM" in result

#     vm._ssh_client.exec_command('exit')


def test_ip_address_overlap():
    """Test IP address overlap"""
    ip = "172.16.0.2"
    vm = MicroVM(name="test123", ip_addr=ip)
    vm.create()

    vm = MicroVM(name="test456", ip_addr=ip)
    result = vm.create()
    
    assert f"IP address {ip} is already in use" in result


def test_port_forwarding():
    """Test port forwarding for a VM"""
    vm = MicroVM(name="test123", ip_addr="172.16.0.2")
    vm.create()
    vm_id = vm.list()[0]['id']

    host_port = 8080
    dest_port = 80

    # Add port forwarding
    result = vm.port_forward(id=vm_id, host_port=host_port, dest_port=dest_port)
    assert f"Port forwarding active" in result

    # Remove port forwarding
    result = vm.port_forward(id=vm_id, host_port=host_port, dest_port=dest_port, remove=True)
    assert f"Port forwarding rule removed" in result


def test_port_forwarding_existing_vmm():
    """Test port forwarding for an existing VMM"""
    vm = MicroVM(name="test123", ip_addr="172.16.0.2", expose_ports=True, host_port=10222, dest_port=22)
    vm.create()
    id = vm.list()[0]['id']
    config = f"{vm._config.data_path}/{id}/config.json"
    
    vm.port_forward(id=id, host_port=10223, dest_port=23)
    with open(config, 'r') as file:
        config = json.load(file)
        expected_ports = {
            '22/tcp': [
                {
                    'HostPort': 10222,
                    'DestPort': 22
                }
            ],
            '23/tcp': [
                {
                    'HostPort': 10223,
                    'DestPort': 23
                }
            ]
        }
        assert config['Ports'] == expected_ports
    

def test_port_forwarding_remove_existing_port():
    """Test port forwarding removal for an existing VMM"""
    vm = MicroVM(name="test123", ip_addr="172.16.0.2", expose_ports=True, host_port=10222, dest_port=22)
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


def test_create_tap_device():
    """Test creating a tap device"""
    network_manager = NetworkManager()
    tap_name = "tap_test"
    iface_name = "eth0"
    gateway_ip = "192.168.1.1"

    network_manager.create_tap(name=tap_name, iface_name=iface_name, gateway_ip=gateway_ip)
    assert network_manager.check_tap_device(tap_name)
    network_manager.delete_tap(tap_name)


def test_add_nat_rules():
    """Test adding NAT rules"""
    network_manager = NetworkManager()
    tap_name = "tap_test"
    iface_name = "eth0"

    network_manager.add_nat_rules(tap_name, iface_name)
    rules = network_manager.get_nat_rules()
    assert any(tap_name in str(rule) for rule in rules)
    network_manager.delete_nat_rules(tap_name)


def test_delete_nat_rules():
    """Test deleting NAT rules"""
    network_manager = NetworkManager()
    tap_name = "tap_test"

    network_manager.delete_nat_rules(tap_name)
    rules = network_manager.get_nat_rules()
    assert not any(tap_name in str(rule) for rule in rules)


def test_vmm_expose_single_port():
    """Test exposing a single port to the host"""
    vm = MicroVM(name="test123", ip_addr="172.20.0.2", expose_ports=True, host_port=10024, dest_port=22)
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
    vm = MicroVM(name="test123", ip_addr="172.21.0.2", expose_ports=True, host_port=[10024, 10025], dest_port=[22, 80])
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
    vm_name = "test_vm_name"
    vm = MicroVM(name=vm_name, ip_addr="172.16.0.32")
    vm.create()

    # Extract the dynamic ID from the creation result
    list_result = vm.list()
    id = list_result[0]['id']  # Assuming the format 'VMM <dynamic_id> is created successfully'

    # Verify the VM is listed with the dynamic ID and name
    assert len(list_result) == 1, "There should be exactly one VM listed"
    assert list_result[0]['id'] == id, f"Expected VM ID {id}, but got {list_result[0]['id']}"
    assert list_result[0]['name'] == vm_name, f"Expected VM name {vm_name}, but got {list_result[0]['name']}"

    # Check if config.json exists before deletion
    config_path = f"/var/lib/firecracker/{id}/config.json"
    assert os.path.exists(config_path), f"config.json not found at {config_path}, cannot proceed with deletion"

    # Delete the VM using the name
    delete_result = vm.delete()
    assert f"VMM {id} deleted successfully" in delete_result, f"Unexpected delete result: {delete_result}"

    # Verify the VM is no longer listed
    list_result = vm.list()
    assert len(list_result) == 0, "VM should be deleted and not listed"


def test_vmm_delete_all():
    """Test deletion of all VMs using real VMMs"""
    name1 = generate_unique_name()
    vm1 = MicroVM(name=name1, ip_addr="172.17.0.2")
    result = vm1.create()
    assert "is created successfully" in result, f"VM creation failed: {result}"

    name2 = generate_unique_name()
    vm2 = MicroVM(name=name2, ip_addr="172.18.0.2")
    result = vm2.create()
    assert "is created successfully" in result, f"VM creation failed: {result}"

    vm = MicroVM()
    vms = vm.list()
    assert len(vms) >= 2
    assert name1 in [v['name'] for v in vms]
    assert name2 in [v['name'] for v in vms]

    # Check if config.json exists for each VM before deletion
    for v in vms:
        config_path = f"/var/lib/firecracker/{v['id']}/config.json"
        assert os.path.exists(config_path), f"config.json not found at {config_path}, cannot proceed with deletion"

    result = vm.delete(all=True)
    assert "All VMMs deleted successfully" in result

    vms = vm.list()
    assert len(vms) == 0


def test_vmm_delete_with_tap_device_cleanup():
    """Test VMM deletion when tap network is deleted manually."""
    name = generate_unique_name()
    vm = MicroVM(name=name, ip_addr="172.21.0.2")
    vm.create()

    list_result = vm.list()
    id = list_result[0]['id']  # Assuming the format 'VMM <dynamic_id> is created successfully'

    tap_device_name = f"tap_{id}"
    vm._network.delete_tap(tap_device_name)

    result = vm.delete()
    assert f"VMM {id} deleted successfully" in result, f"VM deletion failed: {result}"