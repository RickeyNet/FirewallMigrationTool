"""Tests for the FortiGate -> Palo Alto interface scale-up features.

Mirrors the FortiGate -> FTD interface scale-up (EtherChannel / bridge group
expand & promote), but targets PAN-OS:
  - port-channel  <-> aggregate-ethernet
  - bridge group  <-> Layer-2 VLAN segment + vlan.N SVI
"""
import sys
from pathlib import Path
from typing import Any, Dict, List

# Path setup is also handled in tests/conftest.py; kept here as a fallback for
# running this module directly. Import below must stay after this block.
ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "FortiGateToPaloAltoTool"))

from pa_interface_converter import PAInterfaceConverter  # noqa: E402


def _iface(name: str, **props: Any) -> Dict[str, Any]:
    return {name: props}


def _by_type(interfaces: List[Dict], t: str) -> List[Dict]:
    return [i for i in interfaces if i.get("type") == t]


def _find(interfaces: List[Dict], name: str) -> Dict:
    return next(i for i in interfaces if i.get("name") == name)


# ---------------------------------------------------------------------------
# Aggregate (port-channel) expansion
# ---------------------------------------------------------------------------
def test_aggregate_expansion_to_total_count() -> None:
    cfg = {
        "system_interface": [
            _iface("agg1", type="aggregate", member=["port1"],
                   ip=["10.0.0.1", "255.255.255.0"]),
            _iface("port1", type="physical"),
        ]
    }
    conv = PAInterfaceConverter(cfg, target_model="pa-3250")
    conv.set_aggregate_expansion({"agg1": 3})
    conv.convert()

    members = _by_type(conv.get_interfaces(), "aggregate-member")
    assert len(members) == 3  # original 1 + 2 added
    ae = _find(conv.get_interfaces(), "ae1")
    assert len(ae["members"]) == 3
    assert ae["ip_address"] == "10.0.0.1/24"


def test_aggregate_expansion_explicit_ports() -> None:
    cfg = {
        "system_interface": [
            _iface("agg1", type="aggregate", member=["port1"]),
            _iface("port1", type="physical"),
        ]
    }
    conv = PAInterfaceConverter(cfg, target_model="pa-3250")
    conv.set_aggregate_expansion({"agg1": ["ethernet1/10", "ethernet1/11"]})
    conv.convert()

    # An explicit port list defines the EXACT members - the source member is
    # placed on the listed ports, not auto-assigned to a separate port. So the
    # aggregate uses exactly ethernet1/10 and ethernet1/11.
    ae = _find(conv.get_interfaces(), "ae1")
    assert sorted(ae["members"]) == ["ethernet1/10", "ethernet1/11"]


# ---------------------------------------------------------------------------
# Aggregate (port-channel) promotion
# ---------------------------------------------------------------------------
def test_promote_physical_to_aggregate_keeps_ip() -> None:
    cfg = {
        "system_interface": [
            _iface("port1", type="physical", ip=["192.0.2.1", "255.255.255.0"],
                   alias="wan"),
        ]
    }
    conv = PAInterfaceConverter(cfg, target_model="pa-3250")
    conv.set_aggregate_promotion({"wan": 2})
    conv.convert()

    aes = _by_type(conv.get_interfaces(), "aggregate-ethernet")
    assert len(aes) == 1
    ae = aes[0]
    # original port + 1 added = 2 members
    assert len(ae["members"]) == 2
    # In PAN-OS the ae is the L3 interface, so the IP stays on it.
    assert ae["ip_address"] == "192.0.2.1/24"
    # FortiGate name and alias both resolve to the ae.
    assert conv.get_interface_mapping()["port1"] == "ae1"
    assert conv.get_interface_mapping()["wan"] == "ae1"


def test_promote_skipped_when_subinterfaces_present() -> None:
    cfg = {
        "system_interface": [
            _iface("port1", type="physical"),
            _iface("vlan100", type="vlan", interface="port1", vlanid=100,
                   ip=["10.1.1.1", "255.255.255.0"]),
        ]
    }
    conv = PAInterfaceConverter(cfg, target_model="pa-3250")
    conv.set_aggregate_promotion({"port1": 2})
    conv.convert()

    # Promotion is refused because port1 carries a VLAN subinterface; it stays
    # a plain physical interface.
    assert not _by_type(conv.get_interfaces(), "aggregate-ethernet")
    assert _by_type(conv.get_interfaces(), "physical")


# ---------------------------------------------------------------------------
# Bridge group (switch) -> Layer-2 VLAN segment
# ---------------------------------------------------------------------------
def test_switch_converts_to_layer2_vlan_and_svi() -> None:
    cfg = {
        "system_interface": [
            _iface("lan_sw", type="switch", ip=["10.5.5.1", "255.255.255.0"]),
            _iface("port3", type="physical"),
            _iface("port4", type="physical"),
        ],
        "system_switch-interface": [
            _iface("lan_sw", member=["port3", "port4"]),
        ],
    }
    conv = PAInterfaceConverter(cfg, target_model="pa-3250")
    conv.convert()

    l2 = _by_type(conv.get_interfaces(), "layer2-member")
    assert len(l2) == 2
    vlan_obj = _by_type(conv.get_interfaces(), "vlan-object")
    assert len(vlan_obj) == 1
    svi = _by_type(conv.get_interfaces(), "vlan-interface")
    assert len(svi) == 1
    # IP moves onto the SVI; switch name resolves to the SVI for routes/policies.
    assert svi[0]["ip_address"] == "10.5.5.1/24"
    assert conv.get_interface_mapping()["lan_sw"] == svi[0]["name"]
    # The vlan object references the SVI as its virtual interface.
    assert vlan_obj[0]["vlan_interface"] == svi[0]["name"]


def test_switch_expansion_adds_members() -> None:
    cfg = {
        "system_interface": [
            _iface("lan_sw", type="switch", ip=["10.5.5.1", "255.255.255.0"]),
            _iface("port3", type="physical"),
        ],
        "system_switch-interface": [
            _iface("lan_sw", member=["port3"]),
        ],
    }
    conv = PAInterfaceConverter(cfg, target_model="pa-3250")
    conv.set_bridgegroup_expansion({"lan_sw": 3})
    conv.convert()

    l2 = _by_type(conv.get_interfaces(), "layer2-member")
    assert len(l2) == 3  # 1 original + 2 added


def test_promote_physical_to_bridgegroup() -> None:
    cfg = {
        "system_interface": [
            _iface("port5", type="physical", ip=["10.9.9.1", "255.255.255.0"]),
        ]
    }
    conv = PAInterfaceConverter(cfg, target_model="pa-3250")
    conv.set_bridgegroup_promotion({"port5": ["ethernet1/6"]})
    conv.convert()

    # An explicit port list defines the EXACT member ports - so the segment
    # uses ethernet1/6 only, not an extra auto-assigned port.
    l2 = _by_type(conv.get_interfaces(), "layer2-member")
    assert len(l2) == 1
    assert l2[0]["name"] == "ethernet1/6"
    svi = _by_type(conv.get_interfaces(), "vlan-interface")
    assert svi and svi[0]["ip_address"] == "10.9.9.1/24"


def test_promote_physical_to_bridgegroup_int_uses_own_port() -> None:
    """An int spec keeps the original behavior: own port + grow to total."""
    cfg = {
        "system_interface": [
            _iface("port5", type="physical", ip=["10.9.9.1", "255.255.255.0"]),
        ]
    }
    conv = PAInterfaceConverter(cfg, target_model="pa-3250")
    conv.set_bridgegroup_promotion({"port5": 2})
    conv.convert()
    l2 = _by_type(conv.get_interfaces(), "layer2-member")
    assert len(l2) == 2  # auto-assigned own port + 1 grown member


def test_zones_carry_mode() -> None:
    cfg = {
        "system_interface": [
            _iface("lan_sw", type="switch", ip=["10.5.5.1", "255.255.255.0"]),
            _iface("port3", type="physical"),
        ],
        "system_switch-interface": [
            _iface("lan_sw", member=["port3"]),
        ],
    }
    conv = PAInterfaceConverter(cfg, target_model="pa-3250")
    zones = conv.convert()
    modes = {z["mode"] for z in zones}
    assert "layer2" in modes
    assert "layer3" in modes


def test_default_behavior_unchanged_without_specs() -> None:
    cfg = {
        "system_interface": [
            _iface("port1", type="physical", ip=["10.0.0.1", "255.255.255.0"]),
        ]
    }
    conv = PAInterfaceConverter(cfg, target_model="pa-440")
    conv.convert()
    # No scale-up flags: a plain physical interface stays physical.
    assert _by_type(conv.get_interfaces(), "physical")
    assert not _by_type(conv.get_interfaces(), "aggregate-ethernet")
    assert not _by_type(conv.get_interfaces(), "vlan-interface")


# ---------------------------------------------------------------------------
# Explicit ports are reserved and honored (regression for the FTD/PA bug where
# standalone interfaces stole user-requested promotion/expansion ports)
# ---------------------------------------------------------------------------
def test_pa_promotion_explicit_ports_not_stolen() -> None:
    # 11 standalone interfaces would otherwise consume ethernet1/1..1/11 first.
    ifaces = [
        _iface(f"p{i}", type="physical", ip=[f"10.0.{i}.1", "255.255.255.0"])
        for i in range(1, 12)
    ]
    ifaces.append(_iface("srv", type="physical", ip=["10.9.9.1", "255.255.255.0"]))
    conv = PAInterfaceConverter({"system_interface": ifaces}, target_model="pa-3250")
    conv.set_bridgegroup_promotion({"srv": ["ethernet1/10", "ethernet1/11"]})
    conv.convert()

    vobj = _by_type(conv.get_interfaces(), "vlan-object")[0]
    assert sorted(vobj["members"]) == ["ethernet1/10", "ethernet1/11"]
    phys = {i["name"] for i in _by_type(conv.get_interfaces(), "physical")}
    assert "ethernet1/10" not in phys and "ethernet1/11" not in phys
