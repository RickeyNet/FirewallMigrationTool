"""Tests for speed-aware EtherChannel member allocation on the FortiGate -> FTD tool.

On mixed-speed models (e.g. the Secure Firewall 3120: Ethernet1/1-1/8 are 1G
RJ45, 1/9-1/16 are 10G SFP+), an EtherChannel grown via expansion or promotion
must keep every member at the same link speed - LACP cannot bond a 1G port with
a 10G port. These tests pin that behavior.
"""
from typing import Any, Dict, List

from interface_converter import InterfaceConverter  # noqa: E402


def _iface(name: str, **props: Any) -> Dict[str, Any]:
    return {name: props}


def _ec_members(result: Dict[str, List[Dict]], ec_name: str) -> List[str]:
    """Return the FTD hardware names of an EtherChannel's members."""
    for ec in result["etherchannels"]:
        if ec["name"] == ec_name:
            return [m["hardwareName"] for m in ec["memberInterfaces"]]
    raise AssertionError(f"EtherChannel {ec_name} not found")


def _port_nums(hardware_names: List[str]) -> List[int]:
    return [int(h.split("/")[-1]) for h in hardware_names]


def _all_same_speed(port_nums: List[int]) -> bool:
    """True if every port is in the same 3120 speed band (1-8 or 9-16)."""
    return (all(1 <= p <= 8 for p in port_nums)
            or all(9 <= p <= 16 for p in port_nums))


def test_promotion_does_not_mix_speeds_when_10g_scarce() -> None:
    """The reported bug: promote a port to a 4-member channel when only a few
    10G ports remain. It must NOT backfill with 1G ports."""
    # Consume most 10G ports (1/16 down to 1/11) with standalone interfaces so
    # only 1/10 and 1/9 remain in the 10G band; the rest of the pool is 1G.
    cfg = {
        "system_interface": [
            _iface("portA", type="physical", ip=["10.0.0.1", "255.255.255.0"]),
            _iface("portB", type="physical", ip=["10.0.1.1", "255.255.255.0"]),
            _iface("portC", type="physical", ip=["10.0.2.1", "255.255.255.0"]),
            _iface("portD", type="physical", ip=["10.0.3.1", "255.255.255.0"]),
            _iface("portE", type="physical", ip=["10.0.4.1", "255.255.255.0"]),
            # The interface to promote to a 4-member EtherChannel.
            _iface("wan", type="physical", alias="wan",
                   ip=["192.0.2.1", "255.255.255.0"]),
        ]
    }
    conv = InterfaceConverter(cfg, target_model="ftd-3120")
    conv.set_etherchannel_promotion({"wan": 4})
    result = conv.convert()

    members = _ec_members(result, "wan")
    nums = _port_nums(members)
    # Same-speed guarantee: never a mix of 1G (1-8) and 10G (9-16).
    assert _all_same_speed(nums), f"channel mixed speeds: {members}"


def test_expansion_does_not_mix_speeds() -> None:
    """Expanding a 10G aggregate beyond the free 10G ports stops short rather
    than mixing in 1G ports."""
    cfg = {
        "system_interface": [
            _iface("agg1", type="aggregate", member=["p1", "p2"],
                   ip=["10.0.0.1", "255.255.255.0"]),
            _iface("p1", type="physical"),
            _iface("p2", type="physical"),
        ]
    }
    conv = InterfaceConverter(cfg, target_model="ftd-3120")
    # Ask for 10 members - far more than the 8 ports in the 10G band.
    conv.set_etherchannel_expansion({"agg1": 10})
    result = conv.convert()

    members = _ec_members(result, "agg1")
    nums = _port_nums(members)
    assert _all_same_speed(nums), f"channel mixed speeds: {members}"


def test_explicit_member_of_wrong_speed_is_rejected() -> None:
    """An explicitly listed member of the wrong speed is skipped, not bonded."""
    cfg = {
        "system_interface": [
            # Base member lands on a 10G port (highest free port = 1/16).
            _iface("agg1", type="aggregate", member=["p1"],
                   ip=["10.0.0.1", "255.255.255.0"]),
            _iface("p1", type="physical"),
        ]
    }
    conv = InterfaceConverter(cfg, target_model="ftd-3120")
    # Ethernet1/3 is a 1G port - must be rejected against a 10G channel.
    conv.set_etherchannel_expansion({"agg1": ["Ethernet1/10", "Ethernet1/3"]})
    result = conv.convert()

    members = _ec_members(result, "agg1")
    nums = _port_nums(members)
    assert 3 not in nums, f"1G port 1/3 was wrongly added: {members}"
    assert _all_same_speed(nums), f"channel mixed speeds: {members}"


def test_uniform_model_unconstrained() -> None:
    """A model without port_speed_groups (e.g. ftd-1010) keeps the old
    behavior: expansion fills from the whole pool."""
    cfg = {
        "system_interface": [
            _iface("agg1", type="aggregate", member=["p1"]),
            _iface("p1", type="physical"),
        ]
    }
    conv = InterfaceConverter(cfg, target_model="ftd-1010")
    conv.set_etherchannel_expansion({"agg1": 4})
    result = conv.convert()
    members = _ec_members(result, "agg1")
    assert len(members) == 4  # 1 source + 3 added, no speed constraint
