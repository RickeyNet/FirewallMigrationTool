"""Tests for reserving one or more FTD HA ports during FortiGate -> FTD migration.

HA links are often dual (separate active/standby control or data links), so the
converter must accept several HA ports and exclude every one of them from the
data-interface port pool.
"""
import pytest

from interface_converter import InterfaceConverter  # noqa: E402


def _conv(custom_ha_port):
    return InterfaceConverter(
        {"system_interface": []}, target_model="ftd-3120",
        custom_ha_port=custom_ha_port,
    )


def _free_port_nums(conv):
    return {int(p.split("/")[-1]) for p in conv.available_ftd_ports}


def test_two_ha_ports_comma_separated_are_reserved():
    conv = _conv("Ethernet1/2, Ethernet1/3")
    assert conv.ha_ports == ["Ethernet1/2", "Ethernet1/3"]
    assert conv.skip_ftd_ports == {"Ethernet1/2", "Ethernet1/3"}
    # Neither HA port is offered to data interfaces.
    assert 2 not in _free_port_nums(conv)
    assert 3 not in _free_port_nums(conv)
    # ha_port stays as a single-value back-compat alias (first port).
    assert conv.ha_port == "Ethernet1/2"


def test_ha_ports_accepts_a_list():
    conv = _conv(["Ethernet1/2", "Ethernet1/4"])
    assert conv.ha_ports == ["Ethernet1/2", "Ethernet1/4"]


def test_whitespace_separator_and_dedupe():
    conv = _conv("Ethernet1/2  Ethernet1/2 Ethernet1/5")
    assert conv.ha_ports == ["Ethernet1/2", "Ethernet1/5"]


def test_none_reserves_no_ha_port():
    conv = _conv("none")
    assert conv.ha_ports == []
    assert conv.ha_port is None
    # All data ports (1-16) are available.
    assert _free_port_nums(conv) == set(range(1, 17))


def test_default_uses_model_single_ha_port():
    conv = InterfaceConverter({"system_interface": []}, target_model="ftd-3120")
    assert conv.ha_ports == ["Ethernet1/2"]


def test_invalid_port_in_list_raises():
    with pytest.raises(ValueError):
        _conv("Ethernet1/2, Ethernet1/99")
    with pytest.raises(ValueError):
        _conv("Ethernet1/2, bogus")


def test_data_interfaces_skip_all_ha_ports():
    cfg = {
        "system_interface": [
            {"port1": {"type": "physical", "ip": ["10.0.0.1", "255.255.255.0"]}},
            {"port2": {"type": "physical", "ip": ["10.0.1.1", "255.255.255.0"]}},
        ]
    }
    conv = InterfaceConverter(cfg, target_model="ftd-3120",
                              custom_ha_port="Ethernet1/2, Ethernet1/3")
    result = conv.convert()
    used_hw = {i["hardwareName"] for i in result["physical_interfaces"]}
    assert "Ethernet1/2" not in used_hw
    assert "Ethernet1/3" not in used_hw
