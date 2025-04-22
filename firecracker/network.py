import sys
import ipaddress
from pyroute2 import IPRoute
from firecracker.logger import Logger
from firecracker.utils import run
from firecracker.config import MicroVMConfig
from firecracker.exceptions import NetworkError, ConfigurationError
from ipaddress import IPv4Address, AddressValueError
sys.path.append('/usr/lib/python3/dist-packages')
try:
    from nftables import Nftables
except ImportError:
    print("Nftables module is not available. Please install it to use this feature.")
    Nftables = None


class NetworkManager:
    """Manages network-related operations for Firecracker VMs."""
    def __init__(self, verbose: bool = False, level: str = "INFO"):
        self.logger = Logger(level=level, verbose=verbose)
        self._config = MicroVMConfig()
        self._config.verbose = verbose
        self._nft = Nftables()
        self._nft.set_json_output(True)

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
                segments = ip_obj.exploded.split(':')
                segments[-1] = '1'
                gateway_ip = ipaddress.IPv6Address(':'.join(segments))
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
            if 'rule' in item:
                rule = item['rule']
                if 'expr' in rule:
                    for expr in rule['expr']:
                        if 'match' in expr and 'right' in expr['match'] and isinstance(expr['match']['right'], str) and tap_name in expr['match']['right']:
                            if self._config.verbose:
                                self.logger.info(f"Found matching rule for {tap_name}")
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
                        self.logger.info(f"Bridge device {bridge_name} not found")
                    return False

                link_info = ipr.get_links(links[0])[0]
                for attr_name, attr_value in link_info.get('attrs', []):
                    if attr_name == 'IFLA_LINKINFO':
                        for info_attr_name, info_attr_value in attr_value.get('attrs', []):
                            if info_attr_name == 'IFLA_INFO_KIND' and info_attr_value == 'bridge':
                                if self._config.verbose:
                                    self.logger.info(f"Bridge device {bridge_name} exists")
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
            raise NetworkError(f"Failed to check tap device {tap_device_name}: {str(e)}")

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
        list_cmd = {"nftables": [{"list": {"table": {"family": "ip", "name": "filter"}}}]}
        output = self._nft.json_cmd(list_cmd)

        try:
            result = output[1]['nftables']
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
            result = output[1]['nftables']

            for item in result:
                if 'rule' not in item:
                    continue

                rule = item['rule']
                if rule.get('chain') != 'POSTROUTING':
                    continue

                has_interface_match = False
                has_masquerade = False

                for expr in rule.get('expr', []):
                    if 'match' in expr and expr['match'].get('op') == '==' and \
                    expr['match'].get('left', {}).get('meta', {}).get('key') == 'oifname' and \
                    expr['match'].get('right') == iface_name:
                        has_interface_match = True

                    if 'masquerade' in expr:
                        has_masquerade = True

                if has_interface_match and has_masquerade:
                    if self._config.verbose:
                        self.logger.info(f"Found masquerade rule for {iface_name} with handle {rule.get('handle')}")
                    return rule.get('handle')

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
                self.logger.info(f"Masquerade rule for {iface_name} already exists with handle {handle}")
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
                self.logger.info(f"Created masquerade rule for {iface_name}")
            return self.get_masquerade_handle(iface_name)
        else:
            if self._config.verbose:
                self.logger.warn(f"Failed to create masquerade rule: {result[1]}")
            return None

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
            # The output is a list of dictionaries, each containing a table, chain, or rule.
            # We need to extract the rules from the list.
            #
            # Example output structure:
            # rules = [
            #     {'metainfo': {...}},                  # Metadata information
            #     {'table': {...}},                     # Table definitions
            #     {'chain': {...}},                     # Chain definitions
            #     {'rule': {                            # Rule definitions
            #         'family': 'ip',                   # IP family
            #         'table': 'nat',                   # Table name
            #         'chain': 'prerouting',            # Chain name
            #         'handle': 16,                     # Rule handle (ID)
            #         'expr': [                         # Rule expressions
            #             {'match': {...}},             # Match conditions
            #             {'dnat': {...}}               # Action to perform
            #         ]
            #     }},
            #     ...
            # ]

            rules = {}

            for item in result:
                if 'rule' not in item:
                    continue

                rule = item['rule']

                # Check for PREROUTING rules (for incoming traffic)
                if rule.get('family') == 'ip' and rule.get('table') == 'nat' and rule.get('chain') == 'prerouting':
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
                                self.logger.info(f"Prerouting rule: {dest_ip}:{dest_port}")

                    if has_daddr_match and has_dport_match and has_correct_dnat:
                        if self._config.verbose:
                            self.logger.debug(f"Found matching prerouting port forward rule {rule}")
                            self.logger.info(f"Found prerouting rule with handle {rule['handle']}")
                        rules['prerouting'] = rule['handle']

                # Check for POSTROUTING rules (for outgoing traffic)
                elif rule.get('family') == 'ip' and rule.get('table') == 'nat' and rule.get('chain') in ['postrouting', 'POSTROUTING']:
                    expr = rule.get('expr', [])
                    has_saddr_match = False
                    has_masquerade = False

                    for e in expr:
                        # Check for source address match (VM's IP)
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
                            self.logger.debug(f"Found matching postrouting masquerade rule {rule}")
                            self.logger.info(f"Found postrouting rule with handle {rule['handle']}")
                        rules['postrouting'] = rule['handle']

            if not rules and self._config.verbose:
                self.logger.info("No port forwarding rules found")

            return rules

        except Exception as e:
            raise NetworkError(f"Failed to get nftables rules: {str(e)}")

    def add_port_forward(self, host_ip: str, host_port: int, dest_ip: str, dest_port: int, protocol: str = "tcp"):
        """Port forward a port to a new IP and port.

        Args:
            host_ip (str): IP address to forward from.
            host_port (int): Port to forward.
            dest_ip (str): IP address to forward to.
            dest_port (int): Port to forward to.
            id (str): ID of the microVM.

        Raises:
            NetworkError: If adding nftables port forwarding rule fails.
        """
        rules = {
            "nftables": [
                {
                    "table": {
                        "family": "ip",
                        "name": "nat",
                        "handle": 91
                    }
                    },
                {
                    "chain": {
                        "family": "ip",
                        "table": "nat",
                        "name": "PREROUTING",
                        "handle": 2,
                        "type": "nat",
                        "hook": "prerouting",
                        "prio": -100,
                        "policy": "accept"
                    }
                    },
                {
                    "chain": {
                        "family": "ip",
                        "table": "nat",
                        "name": "OUTPUT",
                        "handle": 4,
                        "type": "nat",
                        "hook": "output",
                        "prio": -100,
                        "policy": "accept"
                    }
                    },
                {
                    "chain": {
                        "family": "ip",
                        "table": "nat",
                        "name": "POSTROUTING",
                        "handle": 6,
                        "type": "nat",
                        "hook": "postrouting",
                        "prio": 100,
                        "policy": "accept"
                    }
                    },
                {
                    "chain": {
                        "family": "ip",
                        "table": "nat",
                        "name": "postrouting",
                        "handle": 11,
                        "type": "nat",
                        "hook": "postrouting",
                        "prio": 100,
                        "policy": "accept"
                    }
                    },
                {
                    "chain": {
                        "family": "ip",
                        "table": "nat",
                        "name": "prerouting",
                        "handle": 12,
                        "type": "nat",
                        "hook": "prerouting",
                        "prio": -100,
                        "policy": "accept"
                    }
                    },
                {
                    "rule": {
                        "family": "ip",
                        "table": "nat",
                        "chain": "postrouting",
                        "handle": 14,
                        "expr": [
                            {
                                "match": {
                                    "op": "==",
                                    "left": {
                                        "meta": {
                                            "key": "oif"
                                        }
                                    },
                                    "right": "eth0"
                                    }
                                },
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
                    },
                {
                    "rule": {
                        "family": "ip",
                        "table": "nat",
                        "chain": "prerouting",
                        "handle": 13,
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
            ]
        }

        self._nft.json_cmd(rules)
        if self._config.verbose:
            self.logger.info("Added nftables port forwarding rule")

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
                    self.logger.error(f"Error deleting rule with handle {rule['handle']}: {error}")

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
            self.logger.info(f"Found {len(rules)} total rules and {len(tap_rules)} rules for {tap_name}")

        for rule in tap_rules:
            if self._config.verbose:
                self.logger.debug(f"Deleting rule: {rule}")
            self.delete_rule(rule)

    def delete_port_forward(self, host_ip: str, host_port: int, dest_ip: str, dest_port: int):
        """Delete port forwarding rules.

        Args:
            host_ip (str): IP address being forwarded from.
            host_port (int): Port being forwarded.
            dest_ip (str): IP address being forwarded to.
            dest_port (int): Port being forwarded to.

        Raises:
            NetworkError: If deleting port forwarding rules fails.
        """
        rules = self.get_port_forward_handles(host_ip, host_port, dest_ip, dest_port)
        if not rules:
            if self._config.verbose:
                self.logger.info("No port forwarding rules found to delete")
            return

        try:
            if 'prerouting' in rules:
                handle = rules['prerouting']
                cmd = f'delete rule nat prerouting handle {handle}'
                rc, output, error = self._nft.cmd(cmd)

                if self._config.verbose:
                    if rc == 0:
                        self.logger.info(f"Prerouting rule with handle {handle} deleted")
                    else:
                        self.logger.warn(f"Error deleting prerouting rule with handle {handle}: {error}")

            if 'postrouting' in rules:
                handle = rules['postrouting']
                chain = 'POSTROUTING' if rules.get('postrouting_chain') == 'POSTROUTING' else 'postrouting'
                cmd = f'delete rule nat {chain} handle {handle}'
                rc, output, error = self._nft.cmd(cmd)

                if self._config.verbose:
                    if rc == 0:
                        self.logger.info(f"Postrouting rule with handle {handle} deleted")
                    else:
                        self.logger.warn(f"Error deleting postrouting rule with handle {handle}: {error}")

        except Exception as e:
            raise NetworkError(f"Failed to delete port forward rules: {str(e)}")

    def create_tap(self, name: str = None, iface_name: str = None,
                   gateway_ip: str = None, bridge: bool = False) -> None:
        """Create and configure a new tap device using pyroute2.

        Args:
            iface_name (str, optional): Name of the interface for firewall rules.
            name (str, optional): Name for the new tap device.
            gateway_ip (str, optional): IP address to be assigned to the tap device.
            bridge_name (str, optional): Name of the bridge to attach the tap device to.

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
                    ipr.link('add', ifname=name, kind='tuntap', mode='tap')
                    if self._config.verbose:
                        self.logger.info(f"Created tap device {name}")

                    if bridge:
                        self.attach_tap_to_bridge(iface_name, self._config.bridge_name)

                    idx = ipr.link_lookup(ifname=name)[0]
                    ipr.link('set', index=idx, state='up')
                    if self._config.verbose:
                        self.logger.info(f"Set tap device {name} up")

                    if not bridge:
                        self.add_nat_rules(name, iface_name)
                        self.ensure_masquerade(iface_name)

                    if gateway_ip:
                        try:
                            ipr.addr('add', index=idx, address=gateway_ip, prefixlen=24)
                            if self._config.verbose:
                                self.logger.info(f"Set {gateway_ip} as gateway on tap device {name}")
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
                ipr.link('set', index=idx, master=bridge_idx)
                if self._config.verbose:
                    self.logger.info(f"Attached tap device {iface_name} to bridge {bridge_name}")
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
                ipr.link('del', index=idx)
                if self._config.verbose:
                    self.logger.info(f"Removed tap device {name}")

    def cleanup(self, tap_device: str):
        """Clean up network resources including tap device and firewall rules using nftables.

        Args:
            tap_device (str): Name of the tap device to clean up.
        """
        if not self._config.bridge:
            if self._config.verbose:
                self.logger.info(f"Deleting firewall rules for {tap_device}")

            self.delete_nat_rules(tap_device)

        self.delete_tap(tap_device)
