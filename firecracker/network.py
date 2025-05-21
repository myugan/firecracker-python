import sys
import ipaddress
from pyroute2 import IPRoute
from firecracker.logger import Logger
from firecracker.utils import run
from firecracker.config import MicroVMConfig
from firecracker.exceptions import NetworkError, ConfigurationError
from ipaddress import IPv4Address, IPv4Network, AddressValueError

sys.path.append("/usr/lib/python3/dist-packages")
try:
    from nftables import Nftables
except ImportError:
    print(
        "Nftables module is not available. Using mock implementation for non-Linux systems."
    )

    # Create a mock Nftables class for development/testing on non-Linux systems
    class Nftables:
        def __init__(self):
            pass

        def set_json_output(self, value):
            pass

        def json_cmd(self, cmd):
            print(f"MOCK: Would execute nftables command: {cmd}")
            return (0, {"nftables": []}, "")

        def cmd(self, cmd):
            print(f"MOCK: Would execute nftables command: {cmd}")
            return (0, "", "")


class NetworkManager:
    """Manages network-related operations for Firecracker VMs."""

    def __init__(self, verbose: bool = False, level: str = "INFO"):
        self.logger = Logger(level=level, verbose=verbose)
        self._config = MicroVMConfig()
        self._config.verbose = verbose
        self._nft = Nftables()
        self._nft.set_json_output(True)

    def get_host_ip(self) -> str:
        """Get the host machine's IP address.

        Returns:
            str: The host's IP address

        Raises:
            NetworkError: If unable to determine the host IP address
        """
        try:
            # First try to get the IP address of the default interface
            try:
                interface = self.get_interface_name()

                cmd = f"ip -4 addr show {interface} | grep -oP '(?<=inet\\s)\\d+(\\.\\d+){{3}}'"
                process = run(cmd)
                if process.returncode == 0 and process.stdout.strip():
                    ip = process.stdout.strip()
                    if self._config.verbose:
                        self.logger.info(f"Host IP address: {ip}")
                    return ip
            except Exception as e:
                if self._config.verbose:
                    self.logger.warn(
                        f"Failed to get IP using interface {interface}: {str(e)}"
                    )

            # Fallback method 1 - use hostname command
            try:
                process = run("hostname -I | awk '{print $1}'")
                if process.returncode == 0 and process.stdout.strip():
                    ip = process.stdout.strip()
                    if self._config.verbose:
                        self.logger.info(f"Host IP address (hostname method): {ip}")
                    return ip
            except Exception:
                if self._config.verbose:
                    self.logger.warn("Failed to get IP using hostname method")

            # Fallback method 2 - get local IP by creating a dummy socket
            try:
                import socket

                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    # Doesn't need to be reachable, just to determine interface
                    s.connect(("8.8.8.8", 80))
                    ip = s.getsockname()[0]
                    if self._config.verbose:
                        self.logger.info(f"Host IP address (socket method): {ip}")
                    return ip
                finally:
                    s.close()
            except Exception:
                if self._config.verbose:
                    self.logger.warn("Failed to get IP using socket method")

            # Last resort method - use localhost IP for testing purposes
            if self._config.verbose:
                self.logger.warn(
                    "Using localhost (127.0.0.1) as host IP - port forwarding may not work correctly"
                )
            return "127.0.0.1"

        except Exception as e:
            if self._config.verbose:
                self.logger.error(f"Failed to determine host IP: {str(e)}")
            raise NetworkError(f"Failed to determine host IP address: {str(e)}")

    def get_interface_name(self) -> str:
        """Get the name of the network interface.

        Returns:
            str: Name of the network interface

        Raises:
            RuntimeError: If unable to determine the interface name
        """
        process = run("ip route | grep default | awk '{print $5}'")
        if process.returncode == 0:
            if self._config.verbose:
                self.logger.info(f"Default interface name: {process.stdout.strip()}")

            return process.stdout.strip()
        else:
            raise RuntimeError("Unable to determine the interface name")

    def get_gateway_ip(self, ip: str) -> str:
        """Derive gateway IP from VMM IP by replacing the last octet with 1 for IPv4,
        or the last segment with 1 for IPv6.

        Args:
            ip (str): IP address to derive gateway IP from

        Returns:
            str: Derived gateway IP

        Raises:
            NetworkError: If IP address is invalid
        """
        try:
            ip_obj = ipaddress.ip_address(ip)
            if isinstance(ip_obj, IPv4Address):
                gateway_ip = IPv4Address((int(ip_obj) & 0xFFFFFF00) | 1)
            elif isinstance(ip_obj, ipaddress.IPv6Address):
                segments = ip_obj.exploded.split(":")
                segments[-1] = "1"
                gateway_ip = ipaddress.IPv6Address(":".join(segments))
            else:
                raise NetworkError(f"Unsupported IP address type: {ip}")

            return str(gateway_ip)

        except AddressValueError:
            raise NetworkError(f"Invalid IP address format: {ip}")

        except Exception as e:
            raise NetworkError(f"Failed to derive gateway IP: {str(e)}")

    def find_tap_interface_rules(self, rules, tap_name):
        """Find rules that match the specified tap interface.

        Args:
            rules (list): List of rules to search through.
            tap_name (str): Name of the tap device to find.

        Returns:
            list: List of matching rules for the specified tap interface.
        """
        tap_rules = []
        for item in rules:
            if "rule" in item:
                rule = item["rule"]
                if "expr" in rule:
                    for expr in rule["expr"]:
                        if (
                            "match" in expr
                            and "right" in expr["match"]
                            and isinstance(expr["match"]["right"], str)
                            and tap_name in expr["match"]["right"]
                        ):
                            if self._config.verbose:
                                self.logger.info(f"Found matching rule for {tap_name}")
                            tap_rules.append(
                                {
                                    "handle": rule["handle"],
                                    "chain": rule["chain"],
                                    "interface": expr["match"]["right"],
                                }
                            )

        return tap_rules

    def check_bridge_device(self, bridge_name: str) -> bool:
        """Check if the bridge device exists in the system.

        Args:
            bridge_name (str): Name of the bridge device to check.

        Returns:
            bool: True if the device exists, False otherwise.

        Raises:
            NetworkError: If checking the bridge device fails.
        """
        try:
            with IPRoute() as ipr:
                links = ipr.link_lookup(ifname=bridge_name)
                if not links:
                    if self._config.verbose:
                        self.logger.info(f"Bridge device {bridge_name} not found")
                    return False

                link_info = ipr.get_links(links[0])[0]
                for attr_name, attr_value in link_info.get("attrs", []):
                    if attr_name == "IFLA_LINKINFO":
                        for info_attr_name, info_attr_value in attr_value.get(
                            "attrs", []
                        ):
                            if (
                                info_attr_name == "IFLA_INFO_KIND"
                                and info_attr_value == "bridge"
                            ):
                                if self._config.verbose:
                                    self.logger.info(
                                        f"Bridge device {bridge_name} exists"
                                    )
                                return True

                return False

        except Exception as e:
            raise NetworkError(f"Failed to check bridge device {bridge_name}: {str(e)}")

    def check_tap_device(self, tap_device_name: str) -> bool:
        """Check if the tap device exists in the system using pyroute2.

        Args:
            tap_device_name (str): Name of the tap device to check.

        Returns:
            bool: True if the device exists, False otherwise.

        Raises:
            NetworkError: If checking the tap device fails.
        """
        try:
            with IPRoute() as ipr:
                links = ipr.link_lookup(ifname=tap_device_name)
                if not bool(links):
                    if self._config.verbose:
                        self.logger.info(f"Tap device {tap_device_name} not found")
                    return False
                else:
                    if self._config.verbose:
                        self.logger.info(f"Tap device {tap_device_name} found")
                    return True

        except Exception as e:
            raise NetworkError(
                f"Failed to check tap device {tap_device_name}: {str(e)}"
            )

    def add_nat_rules(self, tap_name: str, iface_name: str):
        """Create network rules using nftables Python module.

        Args:
            tap_name (str): Name of the tap device.
            iface_name (str): Name of the interface to be used.

        Raises:
            NetworkError: If adding NAT forwarding rule fails.
        """
        rules = [
            {
                "nftables": [
                    {"add": {"table": {"family": "ip", "name": "nat"}}},
                    {
                        "add": {
                            "chain": {
                                "family": "ip",
                                "table": "nat",
                                "name": "POSTROUTING",
                                "type": "nat",
                                "hook": "postrouting",
                                "priority": 100,
                                "policy": "accept",
                            }
                        }
                    },
                    {"add": {"table": {"family": "ip", "name": "filter"}}},
                    {
                        "add": {
                            "chain": {
                                "family": "ip",
                                "table": "filter",
                                "name": "FORWARD",
                                "type": "filter",
                                "hook": "forward",
                                "priority": 0,
                                "policy": "accept",
                            }
                        }
                    },
                    {
                        "add": {
                            "rule": {
                                "family": "ip",
                                "table": "filter",
                                "chain": "FORWARD",
                                "expr": [
                                    {
                                        "match": {
                                            "left": {"meta": {"key": "iifname"}},
                                            "op": "==",
                                            "right": tap_name,
                                        }
                                    },
                                    {
                                        "match": {
                                            "left": {"meta": {"key": "oifname"}},
                                            "op": "==",
                                            "right": iface_name,
                                        }
                                    },
                                    {"counter": {"packets": 0, "bytes": 0}},
                                    {"accept": None},
                                ],
                            }
                        }
                    },
                ]
            }
        ]

        for rule in rules:
            rc, output, error = self._nft.json_cmd(rule)
            if self._config.verbose:
                self.logger.info("Added NAT forwarding rule")

            if rc != 0 and "File exists" not in str(error):
                raise NetworkError(f"Failed to add NAT forwarding rule: {error}")

    def get_nat_rules(self):
        """Get all rules from the filter table.

        Returns:
            list: List of rules.

        Raises:
            NetworkError: If retrieving NAT forwarding rules fails.
        """
        list_cmd = {
            "nftables": [{"list": {"table": {"family": "ip", "name": "filter"}}}]
        }
        output = self._nft.json_cmd(list_cmd)

        try:
            result = output[1]["nftables"]
            if self._config.verbose:
                self.logger.debug(f"Found {len(result)} rules in the filter table")
            return result

        except Exception as e:
            raise NetworkError(f"Failed to get NAT forwarding rules: {str(e)}")

    def get_masquerade_handle(self, iface_name: str):
        """
        Get the handle value of a masquerade rule for the specified interface.

        Args:
            iface_name (str): The interface name to look for.

        Returns:
            int: The handle value if found, None otherwise.
        """
        list_cmd = {"nftables": [{"list": {"table": {"family": "ip", "name": "nat"}}}]}
        output = self._nft.json_cmd(list_cmd)

        if not output[0]:
            result = output[1]["nftables"]

            for item in result:
                if "rule" not in item:
                    continue

                rule = item["rule"]
                if rule.get("chain") != "POSTROUTING":
                    continue

                has_interface_match = False
                has_masquerade = False

                for expr in rule.get("expr", []):
                    if (
                        "match" in expr
                        and expr["match"].get("op") == "=="
                        and expr["match"].get("left", {}).get("meta", {}).get("key")
                        == "oifname"
                        and expr["match"].get("right") == iface_name
                    ):
                        has_interface_match = True

                    if "masquerade" in expr:
                        has_masquerade = True

                if has_interface_match and has_masquerade:
                    if self._config.verbose:
                        self.logger.info(
                            f"Found masquerade rule for {iface_name} with handle {rule.get('handle')}"
                        )
                    return rule.get("handle")

        return None

    def ensure_masquerade(self, iface_name: str):
        """
        Ensure a masquerade rule exists for the specified interface.
        Creates it if it doesn't exist, returns the handle if it does.

        Args:
            iface_name (str): The interface name.

        Returns:
            int: The handle value of the rule.
        """
        handle = self.get_masquerade_handle(iface_name)
        if handle is not None:
            if self._config.verbose:
                self.logger.info(
                    f"Masquerade rule for {iface_name} already exists with handle {handle}"
                )
            return handle

        add_cmd = {
            "nftables": [
                {
                    "add": {
                        "rule": {
                            "family": "ip",
                            "table": "nat",
                            "chain": "POSTROUTING",
                            "expr": [
                                {
                                    "match": {
                                        "op": "==",
                                        "left": {"meta": {"key": "oifname"}},
                                        "right": iface_name,
                                    }
                                },
                                {"counter": {"packets": 0, "bytes": 0}},
                                {"masquerade": None},
                            ],
                        }
                    }
                }
            ]
        }

        result = self._nft.json_cmd(add_cmd)
        if not result[0]:
            if self._config.verbose:
                self.logger.info(f"Created masquerade rule for {iface_name}")
            return self.get_masquerade_handle(iface_name)
        else:
            if self._config.verbose:
                self.logger.warn(f"Failed to create masquerade rule: {result[1]}")
            return None

    def get_port_forward_handles(
        self, host_ip: str, host_port: int, dest_ip: str, dest_port: int
    ):
        """Get port forwarding rules from the nat table.

        Checks for both:
        - PREROUTING rules that forward traffic from host_ip:host_port to dest_ip:dest_port
        - POSTROUTING rules that handle return traffic from dest_ip (masquerade)

        Args:
            host_ip (str): IP address to forward from.
            host_port (int): Port to forward.
            dest_ip (str): IP address to forward to.
            dest_port (int): Port to forward to.

        Returns:
            dict: Dictionary containing handles for prerouting and postrouting rules.

        Raises:
            NetworkError: If retrieving nftables rules fails.
        """
        list_cmd = {"nftables": [{"list": {"table": {"family": "ip", "name": "nat"}}}]}

        try:
            output = self._nft.json_cmd(list_cmd)
            result = output[1]["nftables"]
            rules = {}

            for item in result:
                if "rule" not in item:
                    continue

                rule = item["rule"]
                chain = rule.get(
                    "chain", ""
                ).upper()  # Normalize chain name to uppercase

                # Check for PREROUTING rules (for incoming traffic)
                if (
                    rule.get("family") == "ip"
                    and rule.get("table") == "nat"
                    and chain == "PREROUTING"
                ):
                    expr = rule.get("expr", [])

                    has_daddr_match = False
                    has_dport_match = False
                    has_correct_dnat = False

                    for e in expr:
                        if (
                            "match" in e
                            and e["match"]["op"] == "=="
                            and "payload" in e["match"]["left"]
                            and e["match"]["left"]["payload"]["field"] == "daddr"
                            and e["match"]["right"] == host_ip
                        ):
                            has_daddr_match = True

                        if (
                            "match" in e
                            and e["match"]["op"] == "=="
                            and "payload" in e["match"]["left"]
                            and e["match"]["left"]["payload"]["field"] == "dport"
                            and e["match"]["right"] == host_port
                        ):
                            has_dport_match = True

                        if (
                            "dnat" in e
                            and e["dnat"]["addr"] == dest_ip
                            and e["dnat"]["port"] == dest_port
                        ):
                            has_correct_dnat = True
                            if self._config.verbose:
                                self.logger.info(
                                    f"Prerouting rule: {dest_ip}:{dest_port}"
                                )

                    if has_daddr_match and has_dport_match and has_correct_dnat:
                        if self._config.verbose:
                            self.logger.debug(
                                f"Found matching prerouting port forward rule {rule}"
                            )
                            self.logger.info(
                                f"Found prerouting rule with handle {rule['handle']}"
                            )
                        rules["prerouting"] = rule["handle"]

                # Check for POSTROUTING rules (for outgoing traffic)
                elif (
                    rule.get("family") == "ip"
                    and rule.get("table") == "nat"
                    and chain == "POSTROUTING"
                ):
                    expr = rule.get("expr", [])
                    has_saddr_match = False
                    has_masquerade = False

                    for e in expr:
                        # Check for source address match (VM's IP)
                        if (
                            "match" in e
                            and e["match"]["op"] == "=="
                            and "payload" in e["match"]["left"]
                            and e["match"]["left"]["payload"]["field"] == "saddr"
                        ):
                            if e["match"]["right"] == dest_ip or (
                                isinstance(e["match"]["right"], dict)
                                and "prefix" in e["match"]["right"]
                                and e["match"]["right"]["prefix"]["addr"] == dest_ip
                            ):
                                has_saddr_match = True

                        if "masquerade" in e:
                            has_masquerade = True

                    if has_saddr_match and has_masquerade:
                        if self._config.verbose:
                            self.logger.debug(
                                f"Found matching postrouting masquerade rule {rule}"
                            )
                            self.logger.info(
                                f"Found postrouting rule with handle {rule['handle']}"
                            )
                        rules["postrouting"] = rule["handle"]

            if not rules and self._config.verbose:
                self.logger.info("No port forwarding rules found")

            return rules

        except Exception as e:
            raise NetworkError(f"Failed to get nftables rules: {str(e)}")

    def add_port_forward(
        self,
        host_ip: str,
        host_port: int,
        dest_ip: str,
        dest_port: int,
        protocol: str = "tcp",
    ):
        """Port forward a port to a new IP and port.

        Args:
            host_ip (str): IP address to forward from.
            host_port (int): Port to forward.
            dest_ip (str): IP address to forward to.
            dest_port (int): Port to forward to.
            protocol (str): Protocol to forward (default: "tcp").

        Raises:
            NetworkError: If adding nftables port forwarding rule fails.
        """
        try:
            # Validate IP addresses first
            import ipaddress
            try:
                ipaddress.ip_address(host_ip)
                ipaddress.ip_address(dest_ip)
            except ValueError as e:
                raise NetworkError(f"Invalid IP address: {str(e)}")

            # First check if the rules already exist
            existing_rules = self.get_port_forward_handles(
                host_ip, host_port, dest_ip, dest_port
            )
            if existing_rules:
                if self._config.verbose:
                    self.logger.info("Port forwarding rules already exist")
                return

            # Use direct command execution instead of nftables JSON
            from subprocess import run as subprocess_run
            
            # Create a batch of commands (more reliable than JSON API)
            commands = [
                "nft add table ip nat 2>/dev/null || true",
                "nft add chain ip nat PREROUTING { type nat hook prerouting priority -100\; policy accept\; } 2>/dev/null || true",
                "nft add chain ip nat POSTROUTING { type nat hook postrouting priority 100\; policy accept\; } 2>/dev/null || true",
                f"nft add rule ip nat PREROUTING ip daddr {host_ip} {protocol} dport {host_port} counter dnat to {dest_ip}:{dest_port}",
                f"nft add rule ip nat POSTROUTING ip saddr {dest_ip} counter masquerade"
            ]
            
            # Execute each command separately
            for cmd in commands:
                if self._config.verbose:
                    self.logger.debug(f"Running nftables command: {cmd}")
                    
                result = subprocess_run(cmd, shell=True, capture_output=True, text=True)
                
                if result.returncode != 0 and "File exists" not in result.stderr:
                    if self._config.verbose:
                        self.logger.error(
                            f"Command failed: {cmd}\nError: {result.stderr}"
                        )
                    raise NetworkError(
                        f"Failed to add port forwarding rule: {result.stderr}"
                    )

            if self._config.verbose:
                self.logger.info(
                    f"Added port forwarding rule: {host_ip}:{host_port} -> {dest_ip}:{dest_port}"
                )

        except Exception as e:
            if self._config.verbose:
                self.logger.error(f"Port forwarding error: {str(e)}")
            raise NetworkError(f"Failed to add port forwarding rules: {str(e)}")

    def delete_rule(self, rule):
        """Delete a single nftables rule.

        Args:
            rule (dict): Rule to delete.

        Returns:
            bool: True if the rule was successfully deleted, False otherwise.

        Raises:
            NetworkError: If deleting the rule fails.
        """
        cmd = f'delete rule filter {rule["chain"]} handle {rule["handle"]}'
        rc, output, error = self._nft.cmd(cmd)

        try:
            if self._config.verbose:
                if rc == 0:
                    self.logger.info(f"Rule with handle {rule['handle']} deleted")
                else:
                    self.logger.error(
                        f"Error deleting rule with handle {rule['handle']}: {error}"
                    )

            return rc == 0

        except Exception as e:
            raise NetworkError(f"Failed to delete rule: {str(e)}")

    def delete_nat_rules(self, tap_name):
        """Delete all nftables rules associated with the specified tap interface.

        Args:
            tap_name (str): Name of the tap device to delete rules for.
        """
        rules = self.get_nat_rules()
        tap_rules = self.find_tap_interface_rules(rules, tap_name)
        if self._config.verbose:
            self.logger.info(
                f"Found {len(rules)} total rules and {len(tap_rules)} rules for {tap_name}"
            )

        for rule in tap_rules:
            if self._config.verbose:
                self.logger.debug(f"Deleting rule: {rule}")
            self.delete_rule(rule)

    def delete_port_forward(
        self, host_ip: str, host_port: int, dest_ip: str, dest_port: int
    ):
        """Delete port forwarding rules.

        Args:
            host_ip (str): IP address being forwarded from.
            host_port (int): Port being forwarded.
            dest_ip (str): IP address being forwarded to.
            dest_port (int): Port being forwarded to.

        Raises:
            NetworkError: If deleting port forwarding rules fails.
        """
        try:
            # Find existing rules first to get the handles
            rules = self.get_port_forward_handles(
                host_ip, host_port, dest_ip, dest_port
            )
            if not rules:
                if self._config.verbose:
                    self.logger.info("No port forwarding rules found to delete")
                return

            # Use direct command execution instead of file-based operations
            from subprocess import run as subprocess_run
            
            # Delete rules by handle if found
            for rule_type, handle in rules.items():
                chain = "PREROUTING" if rule_type == "prerouting" else "POSTROUTING"
                cmd = f"nft delete rule ip nat {chain} handle {handle}"
                
                if self._config.verbose:
                    self.logger.debug(f"Running nftables command: {cmd}")
                
                result = subprocess_run(cmd, shell=True, capture_output=True, text=True)
                
                if result.returncode != 0:
                    if self._config.verbose:
                        self.logger.error(
                            f"Command failed: {cmd}\nError: {result.stderr}"
                        )
                    # If the rule doesn't exist, that's ok
                    if "No such file or directory" not in str(result.stderr):
                        raise NetworkError(
                            f"Failed to delete port forwarding rule: {result.stderr}"
                        )

            if self._config.verbose:
                self.logger.info(
                    f"Deleted port forwarding: {host_ip}:{host_port} -> {dest_ip}:{dest_port}"
                )

        except Exception as e:
            if self._config.verbose:
                self.logger.error(f"Error deleting port forwarding: {str(e)}")
            raise NetworkError(f"Failed to delete port forward rules: {str(e)}")

    def detect_cidr_conflict(self, ip_address: str, prefix_len: int = 24) -> bool:
        """Check if the given IP address and prefix length conflict with existing interfaces.

        Args:
            ip_address (str): IP address to check for conflicts
            prefix_len (int): Network prefix length (default 24 for /24 networks)

        Returns:
            bool: True if a conflict exists, False otherwise

        Raises:
            NetworkError: If the IP address format is invalid
        """
        try:
            # Create network object from the given IP and prefix
            new_network = IPv4Network(f"{ip_address}/{prefix_len}", strict=False)

            with IPRoute() as ipr:
                # Get all interfaces
                interfaces = ipr.get_links()

                for interface in interfaces:
                    idx = interface["index"]
                    # Get addresses for each interface
                    addresses = ipr.get_addr(index=idx)

                    for addr in addresses:
                        for attr_name, attr_value in addr.get("attrs", []):
                            if attr_name == "IFA_ADDRESS":
                                # Skip IPv6 addresses
                                if ":" in attr_value:
                                    continue

                                existing_prefix = addr.get("prefixlen", 24)
                                existing_network = IPv4Network(
                                    f"{attr_value}/{existing_prefix}", strict=False
                                )

                                # Check for network overlap
                                if new_network.overlaps(existing_network):
                                    if self._config.verbose:
                                        self.logger.warn(
                                            f"CIDR conflict detected: {new_network} "
                                            f"overlaps with existing {existing_network}"
                                        )
                                    return True

            return False

        except (AddressValueError, ValueError) as e:
            raise NetworkError(f"Invalid IP address format: {str(e)}")
        except Exception as e:
            raise NetworkError(f"Failed to check CIDR conflicts: {str(e)}")

    def suggest_non_conflicting_ip(
        self, preferred_ip: str, prefix_len: int = 24
    ) -> str:
        """Suggest a non-conflicting IP address based on the preferred IP.

        Args:
            preferred_ip (str): Preferred IP address
            prefix_len (int): Network prefix length

        Returns:
            str: A non-conflicting IP address

        Raises:
            NetworkError: If unable to find non-conflicting IP
        """
        try:
            # Start with the preferred network
            ip_obj = ipaddress.ip_address(preferred_ip)

            # Try up to 10 alternative networks by incrementing the third octet
            for i in range(10):
                # Calculate a new network address with incremented third octet
                if isinstance(ip_obj, IPv4Address):
                    # Extract octets
                    octets = str(ip_obj).split(".")
                    # Increment third octet and wrap around if needed
                    new_third_octet = (int(octets[2]) + i + 1) % 256
                    new_ip = f"{octets[0]}.{octets[1]}.{new_third_octet}.{octets[3]}"

                    if not self.detect_cidr_conflict(new_ip, prefix_len):
                        if self._config.verbose:
                            self.logger.info(f"Suggested non-conflicting IP: {new_ip}")
                        return new_ip

            raise NetworkError("Unable to find a non-conflicting IP address")

        except Exception as e:
            raise NetworkError(f"Failed to suggest non-conflicting IP: {str(e)}")

    def create_tap(
        self,
        name: str = None,
        iface_name: str = None,
        gateway_ip: str = None,
        bridge: bool = False,
    ) -> None:
        """Create and configure a new tap device using pyroute2.

        Args:
            iface_name (str, optional): Name of the interface for firewall rules.
            name (str, optional): Name for the new tap device.
            gateway_ip (str, optional): IP address to be assigned to the tap device.
            bridge (bool): Whether to use bridge mode.

        Raises:
            NetworkError: If tap device creation or configuration fails.
            ConfigurationError: If required parameters are missing.
        """
        if not name or (iface_name and len(iface_name) > 16):
            if not name:
                raise ConfigurationError("Tap device name is required")
            else:
                raise ValueError("iface_name must not exceed 16 characters")

        try:
            if not self.check_tap_device(name):
                if self._config.verbose:
                    self.logger.info(f"Creating tap device {name}")
                with IPRoute() as ipr:
                    ipr.link("add", ifname=name, kind="tuntap", mode="tap")
                    if self._config.verbose:
                        self.logger.info(f"Created tap device {name}")

                    if bridge:
                        self.attach_tap_to_bridge(iface_name, self._config.bridge_name)

                    idx = ipr.link_lookup(ifname=name)[0]
                    ipr.link("set", index=idx, state="up")
                    if self._config.verbose:
                        self.logger.info(f"Set tap device {name} up")

                    if not bridge:
                        self.add_nat_rules(name, iface_name)
                        self.ensure_masquerade(iface_name)

                    if gateway_ip:
                        try:
                            # Check for CIDR conflicts
                            if self.detect_cidr_conflict(gateway_ip, 24):
                                # Attempt to find a non-conflicting IP
                                alternative_ip = self.suggest_non_conflicting_ip(
                                    gateway_ip, 24
                                )
                                if self._config.verbose:
                                    self.logger.warn(
                                        f"IP conflict detected with {gateway_ip}. "
                                        f"Using alternative: {alternative_ip}"
                                    )
                                gateway_ip = alternative_ip

                            ipr.addr("add", index=idx, address=gateway_ip, prefixlen=24)
                            if self._config.verbose:
                                self.logger.info(
                                    f"Set {gateway_ip} as gateway on tap device {name}"
                                )
                        except Exception as e:
                            raise NetworkError(f"Failed to set gateway IP: {str(e)}")

        except Exception as e:
            self.cleanup(name)
            raise NetworkError(f"Failed to create tap device {name}: {str(e)}")

    def attach_tap_to_bridge(self, iface_name: str, bridge_name: str):
        """Attach a tap device to a bridge.

        Args:
            iface_name (str): Name of the tap device to attach.
            bridge_name (str): Name of the bridge to attach the tap device to.
        """
        try:
            self.check_bridge_device(bridge_name)
            with IPRoute() as ipr:
                bridge_idx = ipr.link_lookup(ifname=bridge_name)[0]
                idx = ipr.link_lookup(ifname=iface_name)[0]
                ipr.link("set", index=idx, master=bridge_idx)
                if self._config.verbose:
                    self.logger.info(
                        f"Attached tap device {iface_name} to bridge {bridge_name}"
                    )
            return True

        except Exception as e:
            raise NetworkError(
                f"Failed to attach tap device {iface_name} to bridge {bridge_name}: {str(e)}"
            )

    def delete_tap(self, name: str) -> None:
        """Delete a tap device using pyroute2.

        Args:
            name (str): Name of the tap device to clean up.
        """
        with IPRoute() as ipr:
            if self.check_tap_device(name):
                idx = ipr.link_lookup(ifname=name)[0]
                ipr.link("del", index=idx)
                if self._config.verbose:
                    self.logger.info(f"Removed tap device {name}")

    def cleanup(self, tap_device: str):
        """Clean up network resources including tap device and firewall rules using nftables.

        Args:
            tap_device (str): Name of the tap device to clean up.
        """
        try:
            if self._config.verbose:
                self.logger.info(f"Beginning thorough cleanup for {tap_device}")

            # Get the IP address associated with this tap device
            tap_ip = None
            with IPRoute() as ipr:
                if self.check_tap_device(tap_device):
                    idx = ipr.link_lookup(ifname=tap_device)[0]
                    # Get addresses for the interface
                    addresses = ipr.get_addr(index=idx)
                    for addr in addresses:
                        for attr_name, attr_value in addr.get("attrs", []):
                            if attr_name == "IFA_ADDRESS":
                                tap_ip = attr_value
                                break

            # Delete all NAT rules related to this tap device
            if not self._config.bridge:
                if self._config.verbose:
                    self.logger.info(f"Deleting firewall rules for {tap_device}")
                self.delete_nat_rules(tap_device)

            # Delete the tap device itself
            self.delete_tap(tap_device)

            # Clear the ARP cache if we know the IP
            if tap_ip:
                if self._config.verbose:
                    self.logger.info(f"Clearing ARP cache entry for {tap_ip}")
                run(
                    f"ip neigh del {tap_ip} dev {self.get_interface_name()} 2>/dev/null || true"
                )

            # Check for stale routes and remove them
            if tap_ip:
                network_prefix = ".".join(tap_ip.split(".")[:3]) + ".0/24"
                if self._config.verbose:
                    self.logger.info(
                        f"Checking for stale routes to network {network_prefix}"
                    )
                # Delete any routes to this network through the tap device
                run(f"ip route del {network_prefix} 2>/dev/null || true")

            # Flush the IP rule cache
            if self._config.verbose:
                self.logger.info("Flushing routing cache")
            run("ip route flush cache 2>/dev/null || true")

            if self._config.verbose:
                self.logger.info(f"Cleanup for {tap_device} completed successfully")

        except Exception as e:
            self.logger.error(f"Error during cleanup of {tap_device}: {str(e)}")
            # Continue with cleanup despite errors

    def enable_nat_internet_access(self, tap_name: str, iface_name: str, vm_ip: str):
        """Enable NAT-based internet access for a MicroVM.

        This method sets up the necessary NAT rules to allow the VM to access the internet
        through the host's network interface.

        Args:
            tap_name (str): Name of the tap device.
            iface_name (str): Name of the host network interface.
            vm_ip (str): IP address of the VM.

        Raises:
            NetworkError: If enabling NAT internet access fails.
        """
        try:
            if self._config.verbose:
                self.logger.info(f"Enabling NAT internet access for VM {vm_ip}")

            # Add basic NAT rules
            self.add_nat_rules(tap_name, iface_name)

            # Ensure masquerade rule exists for outgoing traffic
            self.ensure_masquerade(iface_name)

            # Add forwarding rules for the VM's subnet
            rules = {
                "nftables": [
                    {
                        "add": {
                            "rule": {
                                "family": "ip",
                                "table": "filter",
                                "chain": "FORWARD",
                                "expr": [
                                    {
                                        "match": {
                                            "left": {"meta": {"key": "iifname"}},
                                            "op": "==",
                                            "right": iface_name,
                                        }
                                    },
                                    {
                                        "match": {
                                            "left": {"meta": {"key": "oifname"}},
                                            "op": "==",
                                            "right": tap_name,
                                        }
                                    },
                                    {"counter": {"packets": 0, "bytes": 0}},
                                    {"accept": None},
                                ],
                            }
                        }
                    },
                    {
                        "add": {
                            "rule": {
                                "family": "ip",
                                "table": "filter",
                                "chain": "FORWARD",
                                "expr": [
                                    {
                                        "match": {
                                            "left": {"meta": {"key": "iifname"}},
                                            "op": "==",
                                            "right": tap_name,
                                        }
                                    },
                                    {
                                        "match": {
                                            "left": {"meta": {"key": "oifname"}},
                                            "op": "==",
                                            "right": iface_name,
                                        }
                                    },
                                    {"counter": {"packets": 0, "bytes": 0}},
                                    {"accept": None},
                                ],
                            }
                        }
                    },
                ]
            }

            for rule in rules["nftables"]:
                rc, output, error = self._nft.json_cmd({"nftables": [rule]})
                if rc != 0 and "File exists" not in str(error):
                    raise NetworkError(f"Failed to add NAT rule: {error}")

            if self._config.verbose:
                self.logger.info("NAT internet access enabled successfully")

        except Exception as e:
            raise NetworkError(f"Failed to enable NAT internet access: {str(e)}")
