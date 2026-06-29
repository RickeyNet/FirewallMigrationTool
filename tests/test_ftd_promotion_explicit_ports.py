"""Regression tests: explicit ports for FTD promotion/expansion are honored.

Reproduces the reported bug where promoting an interface to a bridge group on
explicit ports (e.g. Ethernet1/9-10) instead gave it an auto-assigned port and
handed 9/10 to standalone interfaces. Two fixes are covered:
  1. Explicit ports are reserved before greedy standalone assignment.
  2. An explicit port LIST on a promotion defines the exact member ports.
"""
from interface_converter import InterfaceConverter  # noqa: E402


def _cfg(standalones, promoted="srv"):
    ifaces = [
        {f"p{i}": {"type": "physical", "ip": [f"10.0.{i}.1", "255.255.255.0"]}}
        for i in range(1, standalones + 1)
    ]
    ifaces.append({promoted: {"type": "physical", "ip": ["10.9.9.1", "255.255.255.0"]}})
    return {"system_interface": ifaces}


def _bridge_members(result, name):
    bg = next(b for b in result["bridge_groups"] if b["name"] == name)
    return sorted(m["hardwareName"] for m in bg["selectedInterfaces"])


def _ec_members(result, name):
    ec = next(e for e in result["etherchannels"] if e["name"] == name)
    return sorted(m["hardwareName"] for m in ec["memberInterfaces"])


def _standalone_hw(result, skip_prefix="srv"):
    return {
        p["hardwareName"] for p in result["physical_interfaces"]
        if p.get("name") and not p["name"].startswith(skip_prefix)
    }


def test_bridge_promotion_explicit_ports_not_stolen():
    # 8 standalone interfaces would otherwise consume Ethernet1/16..1/9 first.
    conv = InterfaceConverter(_cfg(8), target_model="ftd-3120", custom_ha_port="none")
    conv.set_bridgegroup_promotion({"srv": ["Ethernet1/9", "Ethernet1/10"]})
    result = conv.convert()
    # Bridge uses EXACTLY the requested ports - no extra auto-assigned member.
    assert _bridge_members(result, "srv") == ["Ethernet1/10", "Ethernet1/9"]
    # Standalone interfaces did not grab the reserved ports.
    stand = _standalone_hw(result)
    assert "Ethernet1/9" not in stand and "Ethernet1/10" not in stand


def test_etherchannel_promotion_explicit_ports_exact():
    conv = InterfaceConverter(_cfg(8), target_model="ftd-3120", custom_ha_port="none")
    conv.set_etherchannel_promotion({"srv": ["Ethernet1/9", "Ethernet1/10"]})
    result = conv.convert()
    # find the EC whose source is srv (name 'srv')
    assert _ec_members(result, "srv") == ["Ethernet1/10", "Ethernet1/9"]
    stand = _standalone_hw(result)
    assert "Ethernet1/9" not in stand and "Ethernet1/10" not in stand


def test_int_promotion_still_auto_assigns():
    """An int spec keeps the original behavior: own port + grow to total."""
    conv = InterfaceConverter(_cfg(2), target_model="ftd-3120", custom_ha_port="none")
    conv.set_bridgegroup_promotion({"srv": 3})
    result = conv.convert()
    members = _bridge_members(result, "srv")
    assert len(members) == 3  # auto base + 2 added


def test_aggregate_expansion_explicit_ports_not_stolen():
    """Explicit expansion ports on an existing aggregate are reserved too."""
    cfg = {
        "system_interface": [
            {"agg1": {"type": "aggregate", "member": ["m1"],
                      "ip": ["10.0.0.1", "255.255.255.0"]}},
            {"m1": {"type": "physical"}},
            # standalones that would otherwise grab the high ports
            {"p1": {"type": "physical", "ip": ["10.1.1.1", "255.255.255.0"]}},
            {"p2": {"type": "physical", "ip": ["10.1.2.1", "255.255.255.0"]}},
        ]
    }
    conv = InterfaceConverter(cfg, target_model="ftd-3120", custom_ha_port="none")
    conv.set_etherchannel_expansion({"agg1": ["Ethernet1/9", "Ethernet1/10"]})
    result = conv.convert()
    members = _ec_members(result, "agg1")
    assert "Ethernet1/9" in members and "Ethernet1/10" in members
    stand = _standalone_hw(result, skip_prefix="p_never")
    # p1/p2 must not have taken the reserved expansion ports
    assert "Ethernet1/9" not in stand and "Ethernet1/10" not in stand
