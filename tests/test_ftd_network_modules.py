"""Tests for optional FTD network-module support (FortiGate -> FTD).

Models with a network-module slot (3110/3120/3130/3140, 4215) can carry an
add-on interface module. Its ports (Ethernet2/1..N) join the available pool at
the module's link speed, and can be assigned, bundled into EtherChannels (same
speed only), or reserved for HA.
"""
import pytest

from interface_converter import (  # noqa: E402
    InterfaceConverter, FTD_NETWORK_MODULES, get_network_modules,
)


def _conv(model, module="none", ha=None):
    return InterfaceConverter(
        {"system_interface": []}, target_model=model,
        custom_ha_port=ha, network_module=module,
    )


def test_module_ports_added_to_pool():
    conv = _conv("ftd-3120", module="8x10g")
    pool = conv.available_ftd_ports
    assert "Ethernet2/1" in pool and "Ethernet2/8" in pool
    assert "Ethernet2/9" not in pool          # only 8 module ports
    assert "Ethernet1/16" in pool             # fixed ports still present
    # Module ports take the module's link speed.
    assert conv._speed_group_of_port("Ethernet2/1") == "10G"


def test_module_ports_consumed_after_fixed_ports():
    """Auto-assignment uses built-in ports before module ports."""
    conv = _conv("ftd-3120", module="8x10g")
    # First assignment should be a fixed port (highest-numbered), not a module port.
    first = conv._get_ftd_hardware_name("port1")
    assert first.startswith("Ethernet1/")


def test_model_without_slot_ignores_module():
    conv = _conv("ftd-3105", module="8x10g")  # 3105 has no NM slot
    assert not any(p.startswith("Ethernet2/") for p in conv.available_ftd_ports)


def test_module_port_speeds():
    assert _conv("ftd-3130", module="4x40g")._speed_group_of_port("Ethernet2/1") == "40G"
    assert _conv("ftd-3140", module="8x25g")._speed_group_of_port("Ethernet2/3") == "25G"


def test_ha_can_use_a_module_port():
    conv = _conv("ftd-3120", module="8x10g", ha="Ethernet2/1")
    assert conv.ha_ports == ["Ethernet2/1"]
    assert "Ethernet2/1" not in conv.available_ftd_ports


def test_invalid_ha_module_port_rejected():
    # Module only has 8 ports; Ethernet2/9 does not exist.
    with pytest.raises(ValueError):
        _conv("ftd-3120", module="8x10g", ha="Ethernet2/9")


def test_etherchannel_can_bundle_module_ports_same_speed():
    """An explicit member list of module ports is accepted (all 10G)."""
    cfg = {
        "system_interface": [
            {"agg1": {"type": "aggregate", "member": ["p1"],
                      "ip": ["10.0.0.1", "255.255.255.0"]}},
            {"p1": {"type": "physical"}},
        ]
    }
    conv = InterfaceConverter(cfg, target_model="ftd-3120", network_module="8x10g")
    # Base member p1 lands on a fixed 10G SFP+ port (Ethernet1/16); add two
    # module 10G ports - same speed, so all are accepted.
    conv.set_etherchannel_expansion({"agg1": ["Ethernet2/1", "Ethernet2/2"]})
    result = conv.convert()
    members = [m["hardwareName"]
               for ec in result["etherchannels"] if ec["name"] == "agg1"
               for m in ec["memberInterfaces"]]
    assert "Ethernet2/1" in members and "Ethernet2/2" in members


def test_catalog_consistency():
    assert "none" in get_network_modules()
    assert FTD_NETWORK_MODULES["none"]["ports"] == 0
    assert FTD_NETWORK_MODULES["4x40g"]["ports"] == 4
