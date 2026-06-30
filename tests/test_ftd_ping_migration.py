"""Regression tests: FortiGate ICMP "ping" migrates to an FTD PING port group.

A FortiGate ping service (the predefined PING service, or any ICMP service with
icmptype 8) is no longer dropped. It now produces two ICMPv4 port objects -- echo
request and echo reply -- and a port object group named "PING" that holds them.
"""
from service_converter import (  # noqa: E402
    ServiceConverter,
    PING_GROUP_NAME,
    PING_ECHO_REQUEST_NAME,
    PING_ECHO_REPLY_NAME,
)
from service_group_converter import ServiceGroupConverter  # noqa: E402


def _convert(services):
    conv = ServiceConverter({"firewall_service_custom": services})
    objs = conv.convert()
    return conv, objs


def _by_name(objs, name):
    return next((o for o in objs if o["name"] == name), None)


def test_named_ping_service_creates_echo_objects():
    conv, objs = _convert([
        {"PING": {"protocol": "ICMP", "icmptype": 8}},
    ])

    req = _by_name(objs, PING_ECHO_REQUEST_NAME)
    rep = _by_name(objs, PING_ECHO_REPLY_NAME)

    assert req is not None and rep is not None
    assert req["type"] == "icmpv4portobject"
    assert req["icmpv4Type"] == "ECHO_REQUEST"
    assert rep["icmpv4Type"] == "ECHO_REPLY"
    assert conv.get_statistics()["ping_services"] == 1


def test_ping_group_built_with_both_members():
    conv, _ = _convert([
        {"PING": {"protocol": "ICMP", "icmptype": 8}},
    ])

    groups = conv.get_extra_port_groups()
    assert len(groups) == 1

    ping = groups[0]
    assert ping["name"] == PING_GROUP_NAME
    assert ping["type"] == "portobjectgroup"
    member_names = sorted(m["name"] for m in ping["objects"])
    assert member_names == sorted([PING_ECHO_REQUEST_NAME, PING_ECHO_REPLY_NAME])
    assert all(m["type"] == "icmpv4portobject" for m in ping["objects"])


def test_icmp_type8_without_ping_name_is_detected():
    """An ICMP service named other than PING but with icmptype 8 is still ping."""
    conv, objs = _convert([
        {"MyEcho": {"protocol": "ICMP", "icmptype": "8"}},
    ])
    assert _by_name(objs, PING_ECHO_REQUEST_NAME) is not None
    assert conv.get_statistics()["ping_services"] == 1


def test_non_ping_icmp_still_skipped():
    """A non-echo ICMP service (e.g. type 3) is not treated as ping."""
    conv, objs = _convert([
        {"Unreachable": {"protocol": "ICMP", "icmptype": 3}},
    ])
    assert conv.get_extra_port_groups() == []
    assert conv.get_statistics()["ping_services"] == 0
    assert conv.get_statistics()["icmp_skipped"] == 1


def test_ping_objects_created_only_once():
    """Two ping services share a single set of echo objects and one PING group."""
    conv, objs = _convert([
        {"PING": {"protocol": "ICMP", "icmptype": 8}},
        {"PING2": {"protocol": "ICMP", "icmptype": 8}},
    ])
    echo_reqs = [o for o in objs if o["name"] == PING_ECHO_REQUEST_NAME]
    assert len(echo_reqs) == 1
    assert len(conv.get_extra_port_groups()) == 1
    assert conv.get_statistics()["ping_services"] == 2


def test_service_group_with_ping_flattens_to_echo_objects():
    """A FortiGate service group containing ping expands to the echo objects,
    not a nested group (FTD forbids groups inside groups)."""
    conv, _ = _convert([
        {"PING": {"protocol": "ICMP", "icmptype": 8}},
    ])

    grp_conv = ServiceGroupConverter(
        {"firewall_service_group": [
            {"DIAG": {"member": ["PING"]}},
        ]},
        service_name_mapping=conv.get_service_name_mapping(),
        skipped_services=conv.get_skipped_services(),
    )
    groups = grp_conv.convert()
    diag = next(g for g in groups if g["name"] == "DIAG")
    member_names = sorted(m["name"] for m in diag["objects"])
    assert member_names == sorted([PING_ECHO_REQUEST_NAME, PING_ECHO_REPLY_NAME])
    assert all(m["type"] == "icmpv4portobject" for m in diag["objects"])
