import sys
from pathlib import Path

# Ensure the tool modules are importable when running tests from repo root
ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "FortiGateToFTDTool"))

from route_converter import RouteConverter


def _minimal_interface(name: str, ip: str, netmask: str):
    return {
        "name": name,
        "ipv4": {
            "ipAddress": {
                "ipAddress": ip,
                "netmask": netmask,
            }
        },
    }


def test_network_calc_cache_initialized_and_reused():
    rc = RouteConverter(
        fortigate_config={"router_static": []},
        converted_interfaces={"physical_interfaces": []},
    )

    # First calculation populates cache
    first = rc._calculate_network_address("10.0.0.5", "255.255.255.0")
    assert first == "10.0.0.0"
    key = ("10.0.0.5", "255.255.255.0")
    assert key in rc._network_calc_cache

    # Override cached value to prove subsequent calls use cache, not recompute
    rc._network_calc_cache[key] = "10.0.0.0-CACHED"
    second = rc._calculate_network_address("10.0.0.5", "255.255.255.0")
    assert second == "10.0.0.0-CACHED"


def test_ip_to_interface_lookup_populates_and_uses_cache():
    interfaces = {"physical_interfaces": [_minimal_interface("port1", "192.0.2.10", "255.255.255.0")]}

    rc = RouteConverter(
        fortigate_config={"router_static": []},
        converted_interfaces=interfaces,
    )

    # ip_to_interface_name should include host, /32, and network entries
    assert rc.ip_to_interface_name["192.0.2.10"] == "port1"
    assert rc.ip_to_interface_name["192.0.2.10/32"] == "port1"
    assert rc.ip_to_interface_name["192.0.2.0/24"] == "port1"

    # Cache entry from network calculation exists
    assert ("192.0.2.10", "255.255.255.0") in rc._network_calc_cache
