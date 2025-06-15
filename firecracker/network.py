import sys
import ipaddress
from pyroute2 import IPRoute
from firecracker.logger import Logger
from firecracker.utils import run
from firecracker.config import MicroVMConfig
from firecracker.exceptions import NetworkError, ConfigurationError
from ipaddress import IPv4Address, IPv4Network, AddressValueError
sys.path.append('/usr/lib/python3/dist-packages')
try:
    from nftables import Nftables
except ImportError:
    print("Nftables module is not available. Please install it.")


class NetworkManager:
    """Manages network-related operations for Firecracker VMs."""
    def __init__(self, verbose: bool = False, level: str = "INFO"):
        self._config = MicroVMConfig()
        self._config.verbose = verbose
        self._nft = Nftables()
        self._nft.set_json_output(True)
        self._logger = Logger(level=level, verbose=verbose)

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
                self._logger.debug(f"Default interface name: {process.stdout.strip()}")

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
                segments = ip_obj.exploded.split(':')
                segments[-1] = '1'
                gateway_ip = ipaddress.IPv6Address(':'.join(segments))
                if self._config.verbose:
                    self._logger.debug(f"Derived gateway IP: {gateway_ip}")
            else:
                raise NetworkError(f"Unsupported IP address type: {ip}")

            return str(gateway_ip)

        except AddressValueError:
            raise NetworkError(f"Invalid IP address format: {ip}")

        except Exception as e:
            raise NetworkError(f"Failed to derive gateway IP: {str(e)}")

    def setup(self, tap_name: str, iface_name: str, bridge: bool, bridge_name: str, gateway_ip: str):
        """Setup the network for the Firecracker VM."""
        if not self.check_tap_device(tap_name):
            self.create_tap(tap_name, iface_name, gateway_ip)

        if bridge:
            self.check_bridge_device(bridge_name)
            self.attach_tap_to_bridge(iface_name, bridge_name)

        self.add_nat_rules(tap_name, iface_name)
        self.create_masquerade(iface_name)

    def find_tap_interface_rules(self, rules, tap_name):
        """Find rules that match the specified tap interface.

        Args:
            rules (list): List of rules to search through.
            tap_name (str): Name of the tap device to find.

        Returns:
            list: List of matching rules for the specified tap interface.
        """
        tap_rules = []
        logged_tap_names = set()

        for item in rules:
            if 'rule' in item:
                rule = item['rule']
                if 'expr' in rule:
                    for expr in rule['expr']:
                        if 'match' in expr and 'right' in expr['match'] and isinstance(expr['match']['right'], str) and tap_name in expr['match']['right']:
                            if self._config.verbose:
                                if tap_name not in logged_tap_names:
                                    self._logger.debug(f"Found matching rule for {tap_name} with handle {rule['handle']}")
                                    logged_tap_names.add(tap_name)
                            tap_rules.append({
                                'handle': rule['handle'],
                                'chain': rule['chain'],
                                'interface': expr['match']['right']
                            })

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
                        self._logger.info(f"Bridge device {bridge_name} not found")
                    return False

                link_info = ipr.get_links(links[0])[0]
                for attr_name, attr_value in link_info.get('attrs', []):
                    if attr_name == 'IFLA_LINKINFO':
                        for info_attr_name, info_attr_value in attr_value.get('attrs', []):
                            if info_attr_name == 'IFLA_INFO_KIND' and info_attr_value == 'bridge':
                                if self._config.verbose:
                                    self._logger.info(f"Bridge device {bridge_name} exists")
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
                    return False
                else:
                    return True

        except Exception as e:
            raise NetworkError(f"Failed to check tap device {tap_device_name}: {str(e)}")

    def add_nat_rules(self, tap_name: str, iface_name: str):
        """Create network rules using nftables Python module.

        Args:
            tap_name (str): Name of the tap device.
            iface_name (str): Name of the interface to be used.

        Raises:
            NetworkError: If adding NAT forwarding rule fails.
        """
        try:
            rules = [
                {
                    "nftables": [
                        {
                            "add": {
                                "table": {
                                    "family": "ip",
                                    "name": "nat"
                                }
                            }
                        },
                        {
                            "add": {
                                "chain": {
                                    "family": "ip",
                                    "table": "nat",
                                    "name": "POSTROUTING",
                                    "type": "nat",
                                    "hook": "postrouting",
                                    "priority": 100,
                                    "policy": "accept"
                                }
                            }
                        },
                        {
                            "add": {
                                "table": {
                                    "family": "ip",
                                    "name": "filter"
                                }
                            }
                        },
                        {
                            "add": {
                                "chain": {
                                    "family": "ip",
                                    "table": "filter",
                                    "name": "FORWARD",
                                    "type": "filter",
                                    "hook": "forward",
                                    "priority": 0,
                                    "policy": "accept"
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
                                        {"match": {"left": {"meta": {"key": "iifname"}}, "op": "==", "right": tap_name}},
                                        {"match": {"left": {"meta": {"key": "oifname"}}, "op": "==", "right": iface_name}},
                                        {"counter": {"packets": 0, "bytes": 0}},
                                        {"accept": None}
                                    ]
                                }
                            }
                        }
                    ]
                }
            ]

            for rule in rules:
                rc, output, error = self._nft.json_cmd(rule)
                if self._config.verbose:
                    self._logger.info("Added NAT forwarding rule")
                    self._logger.debug(f"NAT forwarding rule: {output}")

                if rc != 0 and "File exists" not in str(error):
                    raise NetworkError(f"Failed to add NAT forwarding rule: {error}")

        except Exception as e:
            raise NetworkError(f"Failed to add NAT forwarding rule: {str(e)}")

    def get_nat_rules(self):
        """Get all rules from the filter table.

        Returns:
            list: List of rules.

        Raises:
            NetworkError: If retrieving NAT forwarding rules fails.
        """
        list_cmd = {"nftables": [{"list": {"table": {"family": "ip", "name": "filter"}}}]}
        output = self._nft.json_cmd(list_cmd)

        try:
            result = output[1]['nftables']
            if self._config.verbose:
                self._logger.debug(f"Found {len(result)} rules in the filter table")
            return result

        except Exception as e:
            raise NetworkError(f"Failed to get NAT forwarding rules: {str(e)}")

    def get_masquerade_handle(self):
        """
        Get the handle value of a masquerade rule for the specified machine ID.

        Args:
            id (str): Machine ID to match in the rule comment.

        Returns:
            int: The handle value if found, None otherwise.
        """
        list_cmd = {"nftables": [{"list": {"table": {"family": "ip", "name": "nat"}}}]}
        output = self._nft.json_cmd(list_cmd)

        if not output[0]:
            result = output[1]['nftables']
            expected_comment = f"microVM outbound NAT"

            for item in result:
                if 'rule' not in item:
                    continue

                rule = item['rule']
                if rule.get('chain') != 'POSTROUTING':
                    continue

                comment = rule.get('comment', '')
                has_masquerade = False

                # Check for masquerade action
                for expr in rule.get('expr', []):
                    if 'masquerade' in expr:
                        has_masquerade = True
                        break

                if comment == expected_comment and has_masquerade:
                    if self._config.verbose:
                        self._logger.debug(f"Found masquerade rule with handle {rule.get('handle')}")
                    return rule.get('handle')

        return None

    def create_masquerade(self, iface_name: str):
        """
        Ensure a masquerade rule exists for the specified interface.
        Creates it if it doesn't exist, returns the handle if it does.

        Args:
            id (str): Machine ID for the rule comment.
            iface_name (str): The interface name.

        Returns:
            int: The handle value of the rule.
        """
        try:
            handle = self.get_masquerade_handle()
            if handle is not None:
                if self._config.verbose:
                    self._logger.info("Masquerade rule already exists")
                return True

            add_cmd = {
                "nftables": [
                    {
                        "add": {
                            "rule": {
                                "family": "ip",
                                "table": "nat",
                                "chain": "POSTROUTING",
                                "comment": f"microVM outbound NAT",
                                "expr": [
                                    {
                                        "match": {
                                            "op": "==",
                                            "left": {"meta": {"key": "oifname"}},
                                            "right": iface_name
                                        }
                                    },
                                    {"counter": {"packets": 0, "bytes": 0}},
                                    {"masquerade": None}
                                ]
                            }
                        }
                    }
                ]
            }

            result = self._nft.json_cmd(add_cmd)
            if not result[0]:
                if self._config.verbose:
                    self._logger.info("Created masquerade rule")
                return True
            else:
                return False

        except Exception as e:
            raise NetworkError(f"Failed to create masquerade rule: {str(e)}")

    def get_port_forward_handles(self, host_ip: str, host_port: int, dest_ip: str, dest_port: int):
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
        list_cmd = {
            "nftables": [{"list": {"table": {"family": "ip", "name": "nat"}}}]
        }

        try:
            output = self._nft.json_cmd(list_cmd)
            result = output[1]['nftables']
            rules = {}

            for item in result:
                if 'rule' not in item:
                    continue

                rule = item['rule']
                chain = rule.get('chain', '').upper()  # Normalize chain name to uppercase

                if rule.get('family') == 'ip' and rule.get('table') == 'nat' and chain == 'PREROUTING':
                    expr = rule.get('expr', [])

                    has_daddr_match = False
                    has_dport_match = False
                    has_correct_dnat = False

                    for e in expr:
                        if 'match' in e and e['match']['op'] == '==' and \
                            'payload' in e['match']['left'] and e['match']['left']['payload']['field'] == 'daddr' and \
                            e['match']['right'] == host_ip:
                            has_daddr_match = True

                        if 'match' in e and e['match']['op'] == '==' and \
                            'payload' in e['match']['left'] and e['match']['left']['payload']['field'] == 'dport' and \
                            e['match']['right'] == host_port:
                            has_dport_match = True

                        if 'dnat' in e and e['dnat']['addr'] == dest_ip and e['dnat']['port'] == dest_port:
                            has_correct_dnat = True
                            if self._config.verbose:
                                self._logger.info(f"Prerouting rule: {dest_ip}:{dest_port}")

                    if has_daddr_match and has_dport_match and has_correct_dnat:
                        if self._config.verbose:
                            self._logger.debug(f"Found matching prerouting port forward rule {rule}")
                            self._logger.info(f"Found prerouting rule with handle {rule['handle']}")
                        rules['prerouting'] = rule['handle']

                # Check for POSTROUTING rules (for outgoing traffic)
                elif rule.get('family') == 'ip' and rule.get('table') == 'nat' and chain == 'POSTROUTING':
                    expr = rule.get('expr', [])
                    has_saddr_match = False
                    has_masquerade = False

                    for e in expr:
                        if 'match' in e and e['match']['op'] == '==' and \
                            'payload' in e['match']['left'] and e['match']['left']['payload']['field'] == 'saddr':
                            if e['match']['right'] == dest_ip or \
                               (isinstance(e['match']['right'], dict) and
                                'prefix' in e['match']['right'] and
                                e['match']['right']['prefix']['addr'] == dest_ip):
                                has_saddr_match = True

                        if 'masquerade' in e:
                            has_masquerade = True

                    if has_saddr_match and has_masquerade:
                        if self._config.verbose:
                            self._logger.debug(f"Found matching postrouting masquerade rule {rule}")
                            self._logger.info(f"Found postrouting rule with handle {rule['handle']}")
                        rules['postrouting'] = rule['handle']

            if not rules and self._config.verbose:
                self._logger.info("No port forwarding rules found")

            return rules

        except Exception as e:
            raise NetworkError(f"Failed to get nftables rules: {str(e)}")

    def get_port_forward_by_comment(self, id: str, host_port: int):
        """Get port forwarding rules by matching the comment pattern.

        Args:
            id (str): Machine ID to search for
            host_port (int): Host port to search for

        Returns:
            dict: Dictionary containing handles for prerouting and postrouting rules.

        Raises:
            NetworkError: If retrieving nftables rules fails.
        """
        list_cmd = {
            "nftables": [{"list": {"table": {"family": "ip", "name": "nat"}}}]
        }

        try:
            output = self._nft.json_cmd(list_cmd)
            result = output[1]['nftables']
            rules = {}
            expected_comment = f"machine_id={id} host_port={host_port}"

            for item in result:
                if 'rule' not in item:
                    continue

                rule = item['rule']
                chain = rule.get('chain', '').upper()  # Normalize chain name to uppercase
                comment = rule.get('comment', '')

                # Check for PREROUTING rules with matching comment
                if rule.get('family') == 'ip' and rule.get('table') == 'nat' and chain == 'PREROUTING':
                    if comment == expected_comment:
                        if self._config.verbose:
                            self._logger.info(f"Found prerouting rule with matching comment: {comment}")
                            self._logger.debug(f"Rule details: {rule}")
                        rules['prerouting'] = rule['handle']

                # Check for POSTROUTING rules (for the same machine)
                elif rule.get('family') == 'ip' and rule.get('table') == 'nat' and chain == 'POSTROUTING':
                    expr = rule.get('expr', [])
                    has_saddr_match = False
                    has_masquerade = False

                    for e in expr:
                        if 'match' in e and e['match']['op'] == '==' and \
                            'payload' in e['match']['left'] and e['match']['left']['payload']['field'] == 'saddr':
                            if isinstance(e['match']['right'], dict) and 'prefix' in e['match']['right']:
                                has_saddr_match = True

                        if 'masquerade' in e:
                            has_masquerade = True

                    if has_saddr_match and has_masquerade:
                        if self._config.verbose:
                            self._logger.debug(f"Found matching postrouting masquerade rule {rule}")
                            self._logger.info(f"Found postrouting rule with handle {rule['handle']}")
                        rules['postrouting'] = rule['handle']

            if not rules and self._config.verbose:
                self._logger.info(f"No port forwarding rules found for machine_id={id} host_port={host_port}")

            return rules

        except Exception as e:
            raise NetworkError(f"Failed to get nftables rules: {str(e)}")

    def add_port_forward(self, id: str, host_ip: str, host_port: int, dest_ip: str, dest_port: int, protocol: str = "tcp"):
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
        # First check if the rules already exist
        # existing_rules = self.get_port_forward_handles(host_ip, host_port, dest_ip, dest_port)

        existing_rules = self.get_port_forward_by_comment(id, host_port)
        if existing_rules:
            if self._config.verbose:
                self._logger.info("Port forwarding rules already exist")
            return

        # Create the rules
        rules = {
            "nftables": [
                {
                    "add": {
                        "table": {
                            "family": "ip",
                            "name": "nat"
                        }
                    }
                },
                {
                    "add": {
                        "chain": {
                            "family": "ip",
                            "table": "nat",
                            "name": "PREROUTING",
                            "type": "nat",
                            "hook": "prerouting",
                            "prio": -100,
                            "policy": "accept"
                        }
                    }
                },
                {
                    "add": {
                        "chain": {
                            "family": "ip",
                            "table": "nat",
                            "name": "POSTROUTING",
                            "type": "nat",
                            "hook": "postrouting",
                            "prio": 100,
                            "policy": "accept"
                        }
                    }
                },
                {
                    "add": {
                        "rule": {
                            "family": "ip",
                            "table": "nat",
                            "chain": "PREROUTING",
                            "comment": f"machine_id={id} host_port={host_port}",
                            "expr": [
                                {
                                    "match": {
                                        "op": "==",
                                        "left": {
                                            "payload": {
                                                "protocol": "ip",
                                                "field": "daddr"
                                            }
                                        },
                                        "right": host_ip
                                    }
                                },
                                {
                                    "match": {
                                        "op": "==",
                                        "left": {
                                            "payload": {
                                                "protocol": protocol,
                                                "field": "dport"
                                            }
                                        },
                                        "right": host_port
                                    }
                                },
                                {
                                    "dnat": {
                                        "addr": dest_ip,
                                        "port": dest_port
                                    }
                                }
                            ]
                        }
                    }
                },
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
                                        "left": {
                                            "payload": {
                                                "protocol": "ip",
                                                "field": "saddr"
                                            }
                                        },
                                        "right": {
                                            "prefix": {
                                                "addr": dest_ip,
                                                "len": 32
                                            }
                                        }
                                    }
                                },
                                {
                                    "masquerade": None
                                }
                            ]
                        }
                    }
                }
            ]
        }

        try:
            for rule in rules["nftables"]:
                rc, output, error = self._nft.json_cmd({"nftables": [rule]})
                if rc != 0 and "File exists" not in str(error):
                    raise NetworkError(f"Failed to add port forwarding rule: {error}")

            if self._config.verbose:
                self._logger.info(f"Added port forwarding rule: {host_ip}:{host_port} -> {dest_ip}:{dest_port}")

        except Exception as e:
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
                    self._logger.debug(f"Rule with handle {rule['handle']} deleted")
                else:
                    self._logger.error(f"Error deleting rule with handle {rule['handle']}: {error}")

            return rc == 0

        except Exception as e:
            raise NetworkError(f"Failed to delete rule: {str(e)}")

    def delete_nat_rules(self, tap_name):
        """Delete all nftables rules associated with the specified tap interface.

        Args:
            tap_name (str): Name of the tap device to delete rules for.
        """
        try:
            rules = self.get_nat_rules()
            tap_rules = self.find_tap_interface_rules(rules, tap_name)
            if self._config.verbose:
                self._logger.debug(f"Found {len(tap_rules)} rules for {tap_name}")

            for rule in tap_rules:
                self.delete_rule(rule)
                if self._config.verbose:
                    self._logger.debug(f"Deleted rule with handle {rule['handle']}")
                    self._logger.info("Deleted NAT rules")

        except Exception as e:
            raise NetworkError(f"Failed to delete NAT rules: {str(e)}")

    def delete_masquerade(self):
        """Delete masquerade rules for the specified interface.

        Raises:
            NetworkError: If deleting masquerade rules fails.
        """
        try:
            handle = self.get_masquerade_handle()
            if handle is not None:
                cmd = f'delete rule nat POSTROUTING handle {handle}'
                rc, output, error = self._nft.cmd(cmd)

                if self._config.verbose:
                    if rc == 0:
                        self._logger.debug(f"Deleted masquerade rule with handle {handle}")
                        self._logger.info("Deleted masquerade rules")
                    else:
                        self._logger.warn(f"Error deleting masquerade rule with handle {handle}: {error}")

        except Exception as e:
            raise NetworkError(f"Failed to delete masquerade rule: {str(e)}")

    def delete_port_forward(self, id: str, host_port: int):
        """Delete port forwarding rules.

        Args:
            host_port (int): Port being forwarded.
            machine_id (str): ID of the machine for which port forwarding is being deleted.

        Raises:
            NetworkError: If deleting port forwarding rules fails.
        """
        if not isinstance(host_port, int) or host_port < 1 or host_port > 65535:
            raise ValueError(f"Invalid host port number: {host_port}. Must be between 1 and 65535.")

        if not id:
            raise ValueError("id cannot be empty")

        try:
            output = self._nft.json_cmd({"nftables": [{"list": {"table": {"family": "ip", "name": "nat"}}}]})
            rules = output[1]['nftables']

            for item in rules:
                if 'rule' not in item:
                    continue

                rule = item['rule']
                comment = rule.get('comment', '')
                
                if f"machine_id={id} host_port={host_port}" in comment:
                    chain = rule.get('chain', '').upper()
                    handle = rule['handle']
                    
                    cmd = f'delete rule nat {chain} handle {handle}'
                    rc, _, error = self._nft.cmd(cmd)

                    if self._config.verbose:
                        if rc == 0:
                            self._logger.info(f"{chain} rule with handle {handle} deleted")
                        else:
                            self._logger.warn(f"Error deleting {chain} rule with handle {handle}: {error}")

            if self._config.verbose:
                self._logger.info(f"Deleted port forwarding rule for {id} with host port {host_port}")

        except Exception as e:
            raise NetworkError(f"Failed to delete port forward rules: {str(e)}")

    def delete_all_port_forward(self, id: str):
        """Delete all port forwarding rules for a given machine ID.

        Args:
            id (str): Machine ID to search for and delete all associated port forwarding rules.

        Raises:
            NetworkError: If deleting port forwarding rules fails.
        """
        list_cmd = {
            "nftables": [{"list": {"table": {"family": "ip", "name": "nat"}}}]
        }

        try:
            output = self._nft.json_cmd(list_cmd)
            result = output[1]['nftables']
            rules_to_delete = {}

            for item in result:
                if 'rule' not in item:
                    continue

                rule = item['rule']
                chain = rule.get('chain', '').upper()
                comment = rule.get('comment', '')

                if comment and f"machine_id={id}" in comment:
                    if chain == 'PREROUTING':
                        if 'prerouting' not in rules_to_delete:
                            rules_to_delete['prerouting'] = []
                        rules_to_delete['prerouting'].append(rule['handle'])
                    elif chain == 'POSTROUTING':
                        if 'postrouting' not in rules_to_delete:
                            rules_to_delete['postrouting'] = []
                        rules_to_delete['postrouting'].append(rule['handle'])

            if not rules_to_delete:
                if self._config.verbose:
                    self._logger.info("No port forwarding rules found")
                return

            for chain, handles in rules_to_delete.items():
                for handle in handles:
                    cmd = f'delete rule nat {chain.upper()} handle {handle}'
                    rc, output, error = self._nft.cmd(cmd)

                    if self._config.verbose:
                        if rc == 0:
                            self._logger.debug(f"{chain} rule with handle {handle} deleted")
                            self._logger.info("Deleted port forwarding rules")
                        else:
                            self._logger.warn(f"Error deleting {chain} rule with handle {handle}: {error}")

            if self._config.verbose:
                self._logger.info(f"Deleted all port forwarding rules for {id}")

        except Exception as e:
            raise NetworkError(f"Failed to delete port forward rules: {str(e)}")

    def detect_cidr_conflict(self, ip_addr: str, prefix_len: int = 24) -> bool:
        """Check if the given IP address and prefix length conflict with existing interfaces.
        
        Args:
            ip_addr (str): IP address to check for conflicts
            prefix_len (int): Network prefix length (default 24 for /24 networks)
            
        Returns:
            bool: True if a conflict exists, False otherwise
            
        Raises:
            NetworkError: If the IP address format is invalid
        """
        try:
            new_network = IPv4Network(f"{ip_addr}/{prefix_len}", strict=False)

            with IPRoute() as ipr:
                interfaces = ipr.get_links()
                
                for interface in interfaces:
                    idx = interface['index']
                    addresses = ipr.get_addr(index=idx)
                    
                    for addr in addresses:
                        for attr_name, attr_value in addr.get('attrs', []):
                            if attr_name == 'IFA_ADDRESS':
                                if ':' in attr_value:
                                    continue
                                
                                existing_prefix = addr.get('prefixlen', 24)
                                existing_network = IPv4Network(
                                    f"{attr_value}/{existing_prefix}", 
                                    strict=False
                                )

                                if new_network.overlaps(existing_network):
                                    if self._config.verbose:
                                        self._logger.warn(
                                            f"CIDR conflict detected: {new_network} "
                                            f"overlaps with existing {existing_network}"
                                        )
                                    return True
            return False
            
        except (AddressValueError, ValueError) as e:
            raise NetworkError(f"Invalid IP address format: {str(e)}")

        except Exception as e:
            raise NetworkError(f"Failed to check CIDR conflicts: {str(e)}")

    def suggest_non_conflicting_ip(self, preferred_ip: str, prefix_len: int = 24) -> str:
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
            ip_obj = ipaddress.ip_address(preferred_ip)
            
            for i in range(10):
                if isinstance(ip_obj, IPv4Address):
                    octets = str(ip_obj).split('.')
                    new_third_octet = (int(octets[2]) + i + 1) % 256
                    new_ip = f"{octets[0]}.{octets[1]}.{new_third_octet}.{octets[3]}"
                    
                    if not self.detect_cidr_conflict(new_ip, prefix_len):
                        self._logger.debug(f"Suggested non-conflicting IP: {new_ip}")
                        return new_ip
            
            raise NetworkError("Unable to find a non-conflicting IP address")
            
        except Exception as e:
            raise NetworkError(f"Failed to suggest non-conflicting IP: {str(e)}")

    def create_tap(self, tap_name: str = None, iface_name: str = None, gateway_ip: str = None) -> None:
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
        if not tap_name or (iface_name and len(iface_name) > 16):
            if not tap_name:
                raise ConfigurationError("TAP device name is required")
            else:
                # pyroute2 issue: https://github.com/svinota/pyroute2/issues/452#issuecomment-363702389
                raise ValueError("Interface name must not exceed 16 characters")

        try:
            with IPRoute() as ipr:
                ipr.link('add', ifname=tap_name, kind='tuntap', mode='tap')
                idx = ipr.link_lookup(ifname=tap_name)[0]
                if gateway_ip:
                    ipr.addr('add', index=idx, address=gateway_ip, prefixlen=24)

                ipr.link('set', index=idx, state='up')
                
                if self._config.verbose:
                    self._logger.debug(f"Created TAP device {tap_name}")

        except Exception as e:
            self.cleanup(tap_name)
            raise NetworkError(f"Failed to create TAP device {tap_name}: {str(e)}")

    def attach_tap_to_bridge(self, iface_name: str, bridge_name: str):
        """Attach a tap device to a bridge.

        Args:
            iface_name (str): Name of the tap device to attach.
            bridge_name (str): Name of the bridge to attach the tap device to.
        """
        try:
            with IPRoute() as ipr:
                bridge_idx = ipr.link_lookup(ifname=bridge_name)[0]
                idx = ipr.link_lookup(ifname=iface_name)[0]
                ipr.link('set', index=idx, master=bridge_idx)
                if self._config.verbose:
                    self._logger.info(f"Attached tap device {iface_name} to bridge {bridge_name}")

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
        try:
            with IPRoute() as ipr:
                if self.check_tap_device(name):
                    idx = ipr.link_lookup(ifname=name)[0]
                    ipr.link('del', index=idx)
                    if self._config.verbose:
                        self._logger.info(f"Removed tap device {name}")
            return True

        except Exception as e:
            raise NetworkError(f"Failed to delete tap device {name}: {str(e)}")

    def cleanup(self, tap_device: str):
        """Clean up network resources including TAP device and firewall rules.

        Args:
            tap_device (str): Name of the tap device to clean up.
        """
        try:
            self.delete_nat_rules(tap_device)
            machine_id = tap_device[4:]

            self.delete_masquerade()
            self.delete_all_port_forward(machine_id)
            self.delete_tap(tap_device)

        except Exception as e:
            raise NetworkError(f"Failed to cleanup network resources: {str(e)}")
