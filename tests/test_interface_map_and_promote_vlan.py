"""Regression tests for the interface builder follow-ups:

  1. Straight port assignment (Map / Assign) on FTD and PA, including by alias.
  2. Promote-to-port-channel placing the IP on a subinterface (L3 VLAN tag) on
     FTD and PA, with a lossless fallback when no tag is given (FTD).
  3. The GUI builder resolves an existing aggregate/switch to Expand regardless
     of the Action dropdown, so an "expand to N" is never silently dropped
     (the reported bug where a port-channel stayed at its original member count).
"""
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "FortiGateToFTDTool"))
sys.path.append(str(ROOT / "FortiGateToPaloAltoTool"))

from interface_converter import InterfaceConverter  # noqa: E402
from pa_interface_converter import PAInterfaceConverter  # noqa: E402


# ---------------------------------------------------------------------------
# Straight port assignment (Map / Assign)
# ---------------------------------------------------------------------------
def test_ftd_map_port_by_alias_is_honored():
    cfg = {"system_interface": [
        {"port1": {"type": "physical", "alias": "wan",
                   "ip": ["192.0.2.1", "255.255.255.0"]}},
        {"port2": {"type": "physical", "ip": ["10.0.2.1", "255.255.255.0"]}},
    ]}
    conv = InterfaceConverter(cfg, target_model="ftd-3120", custom_ha_port="none")
    conv.set_port_mapping({"wan": "Ethernet1/9"})  # by alias
    res = conv.convert()
    wan = next(p for p in res["physical_interfaces"] if p.get("name") == "wan")
    assert wan["hardwareName"] == "Ethernet1/9"
    # The pinned port must not be auto-assigned to the other interface.
    others = [p["hardwareName"] for p in res["physical_interfaces"]
              if p.get("name") and p["name"] != "wan"]
    assert "Ethernet1/9" not in others


def test_pa_map_port_by_alias_is_honored():
    cfg = {"system_interface": [
        {"port1": {"type": "physical", "alias": "wan",
                   "ip": ["192.0.2.1", "255.255.255.0"]}},
        {"port2": {"type": "physical", "ip": ["10.0.2.1", "255.255.255.0"]}},
    ]}
    conv = PAInterfaceConverter(cfg, target_model="pa-3250")
    conv.set_port_mapping({"wan": "ethernet1/9"})
    conv.convert()
    assert conv.get_interface_mapping()["wan"] == "ethernet1/9"
    phys = {i["name"] for i in conv.get_interfaces() if i["type"] == "physical"}
    # port2 (auto) must not collide with the pinned ethernet1/9.
    assert conv.get_interface_mapping()["port2"] != "ethernet1/9"
    assert "ethernet1/9" in phys


# ---------------------------------------------------------------------------
# Promote to port-channel -> IP on a subinterface (option B)
# ---------------------------------------------------------------------------
def test_ftd_promote_pc_ip_moves_to_subinterface():
    cfg = {"system_interface": [
        {"port2": {"type": "physical", "ip": ["10.0.2.1", "255.255.255.0"]}},
    ]}
    conv = InterfaceConverter(cfg, target_model="ftd-3120", custom_ha_port="none")
    conv.set_etherchannel_promotion({"port2": ["Ethernet1/10", "Ethernet1/11"]})
    conv.set_promotion_subinterface_vlans({"port2": 100})
    res = conv.convert()
    ec = res["etherchannels"][0]
    assert "ipv4" not in ec  # the channel itself is IP-less
    sub = next(s for s in res["subinterfaces"] if s["vlanId"] == 100)
    assert sub["hardwareName"] == "Port-channel1.100"
    assert sub["ipv4"]["ipAddress"]["ipAddress"] == "10.0.2.1"
    # Routes/policies follow the source interface to the L3 subinterface.
    assert conv.get_interface_mapping()["port2"] == sub["name"]


def test_ftd_promote_pc_without_vlan_keeps_ip_on_channel():
    """No L3 VLAN tag -> IP applied directly to the routed port-channel
    (lossless fallback; never silently dropped)."""
    cfg = {"system_interface": [
        {"port2": {"type": "physical", "ip": ["10.0.2.1", "255.255.255.0"]}},
    ]}
    conv = InterfaceConverter(cfg, target_model="ftd-3120", custom_ha_port="none")
    conv.set_etherchannel_promotion({"port2": ["Ethernet1/10", "Ethernet1/11"]})
    res = conv.convert()
    ec = res["etherchannels"][0]
    assert ec["ipv4"]["ipAddress"]["ipAddress"] == "10.0.2.1"
    assert not res["subinterfaces"]


def test_pa_promote_ae_ip_moves_to_subinterface():
    cfg = {"system_interface": [
        {"port2": {"type": "physical", "ip": ["10.0.2.1", "255.255.255.0"]}},
    ]}
    conv = PAInterfaceConverter(cfg, target_model="pa-3250")
    conv.set_aggregate_promotion({"port2": ["ethernet1/10", "ethernet1/11"]})
    conv.set_promotion_subinterface_vlans({"port2": 100})
    conv.convert()
    ifaces = {i["name"]: i for i in conv.get_interfaces()}
    ae = ifaces["ae1"]
    assert "ip_address" not in ae  # ae is IP-less
    sub = ifaces["ae1.100"]
    assert sub["type"] == "subinterface" and sub["parent"] == "ae1"
    assert sub["ip_address"] == "10.0.2.1/24"
    assert conv.get_interface_mapping()["port2"] == "ae1.100"


# ---------------------------------------------------------------------------
# GUI builder: aggregate/switch always resolves to Expand (misroute fix)
# ---------------------------------------------------------------------------
class _Var:
    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v


def _make_row(iface, action, target="Port-Channel", members="", vlan=""):
    import gui_app
    return {
        "iface_var": _Var(iface),
        "action_var": _Var(action),
        "target_var": _Var(target),
        "members_var": _Var(members),
        "vlan_var": _Var(vlan),
    }


def _argv_for(index, row):
    import gui_app
    fake = SimpleNamespace(_agg_iface_index=index)
    return gui_app.App._agg_row_to_argv(fake, row)


def test_gui_aggregate_forced_to_expand_even_if_action_is_promote():
    import gui_app
    # An aggregate accidentally left on the default "Promote" action must still
    # produce --expand-portchannel (the converter ignores promote on aggregates).
    row = _make_row("wan_lag", gui_app.AGG_ACTION_PROMOTE, members="4")
    argv = _argv_for({"wan_lag": "aggregate"}, row)
    assert argv == ["--expand-portchannel", "wan_lag=4"]


def test_gui_switch_forced_to_expand():
    import gui_app
    row = _make_row("lan_sw", gui_app.AGG_ACTION_PROMOTE,
                    target="Bridge Group", members="3")
    argv = _argv_for({"lan_sw": "switch"}, row)
    assert argv == ["--expand-bridgegroup", "lan_sw=3"]


def test_gui_map_action_emits_single_map_port():
    import gui_app
    row = _make_row("wan", gui_app.AGG_ACTION_MAP,
                    members="Ethernet1/9,Ethernet1/10")
    argv = _argv_for({"wan": "physical"}, row)
    assert argv == ["--map-port", "wan=Ethernet1/9"]  # only the first port


def test_gui_promote_pc_with_vlan_emits_vlan_flag():
    import gui_app
    row = _make_row("wan", gui_app.AGG_ACTION_PROMOTE,
                    target="Port-Channel", members="2", vlan="100")
    argv = _argv_for({"wan": "physical"}, row)
    assert argv == [
        "--promote-portchannel", "wan=2",
        "--promote-portchannel-vlan", "wan=100",
    ]
