#!/usr/bin/env python3
"""PAN-OS Service Object Converter — FortiGate Target
======================================================
Converts PAN-OS service objects to FortiGate ``firewall service custom``
CLI config.

PAN-OS has one protocol (tcp OR udp) per service object.  FortiGate can
combine both protocols in a single service object with separate
``tcp-portrange`` and ``udp-portrange`` directives.  This converter
attempts to merge companion objects that share a base name and differ only
by a ``_TCP`` / ``_UDP`` suffix (the pattern produced by the reverse
FG→PA converter).  Objects that do not match the merge pattern are output
as individual FortiGate service objects.

FortiGate CLI output format:
    config firewall service custom
        edit "HTTP"
            set tcp-portrange 80
        next
        edit "DNS"
            set tcp-portrange 53
            set udp-portrange 53
            set comment "DNS service"
        next
    end

PAN-OS port formats supported:
    "80"          -> single port
    "8000-8999"   -> range
    "80,8080"     -> multi-port (written as FG space-separated range list)
"""

from typing import Any, Dict, List, Optional, Tuple

from fg_common import sanitize_fg_name


# PAN-OS suffixes applied by the reverse converter when splitting TCP+UDP
_SPLIT_SUFFIXES = ("_TCP", "_UDP", "_tcp", "_udp")


def _strip_split_suffix(name: str) -> Tuple[Optional[str], Optional[str]]:
    """If *name* ends in a TCP/UDP split suffix, return (base, proto).

    Returns (None, None) if the name does not end in a known suffix.
    """
    for suffix in _SPLIT_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)], suffix.lstrip("_").lower()
    return None, None


def _convert_pa_ports(port_str: str) -> str:
    """Convert a PAN-OS port string to FortiGate portrange format.

    PAN-OS uses comma-separated and hyphenated notation.
    FortiGate uses space-separated entries (each entry is a single port or range).

    Examples:
        "80"         -> "80"
        "8000-8999"  -> "8000-8999"
        "80,8080"    -> "80 8080"
    """
    if not port_str:
        return ""
    # Replace commas with spaces — FG uses space-separated port/range entries
    return port_str.replace(",", " ").strip()


class FGServiceConverter:
    """Convert PAN-OS service objects to FortiGate service custom format."""

    def __init__(self, pa_config: Dict[str, Any]):
        self.pa_config = pa_config
        self.failed_items: List[Dict] = []

        # Maps the original PA service name -> FG merged service name
        # Used by the policy and group converters to resolve references
        self._name_map: Dict[str, str] = {}

        self._stats = {
            "total": 0,
            "tcp_only": 0,
            "udp_only": 0,
            "merged_tcp_udp": 0,
            "skipped": 0,
        }

    def convert(self) -> str:
        """Convert all service objects and return FortiGate CLI block.

        Returns:
            A string containing the ``config firewall service custom`` block,
            or an empty string if there are no service objects.
        """
        services = self.pa_config.get("services", [])
        if not services:
            return ""

        # ------------------------------------------------------------------
        # Pass 1: Group by base name to detect TCP+UDP companion pairs
        # ------------------------------------------------------------------
        # base_name -> {proto: (pa_name, port_str, description)}
        merged: Dict[str, Dict[str, Tuple[str, str, str]]] = {}
        standalone: List[Dict[str, Any]] = []

        for svc in services:
            pa_name = sanitize_fg_name(svc.get("name", ""))
            if not pa_name:
                continue
            proto = svc.get("protocol", "").lower()
            port = _convert_pa_ports(svc.get("port", ""))
            desc = svc.get("description", "")

            base, split_proto = _strip_split_suffix(pa_name)
            if base is not None and split_proto is not None:
                # Candidate for merging
                if base not in merged:
                    merged[base] = {}
                merged[base][split_proto] = (pa_name, port, desc)
            else:
                standalone.append(svc)

        # ------------------------------------------------------------------
        # Pass 2: Decide what becomes merged vs standalone
        # ------------------------------------------------------------------
        # Groups that have BOTH tcp and udp entries → merge
        # Groups missing one side → treat remaining as standalone
        fg_services: List[Dict[str, Any]] = []
        for base, protos in merged.items():
            if "tcp" in protos and "udp" in protos:
                tcp_name, tcp_port, tcp_desc = protos["tcp"]
                _, udp_port, _ = protos["udp"]
                fg_services.append({
                    "fg_name": base,
                    "tcp_port": tcp_port,
                    "udp_port": udp_port,
                    "description": tcp_desc,
                    "merged": True,
                    "pa_names": [tcp_name, protos["udp"][0]],
                })
            else:
                # Only one protocol — treat as standalone
                for proto, (pa_name, port, desc) in protos.items():
                    standalone.append({
                        "name": pa_name,
                        "protocol": proto,
                        "port": port,
                        "description": desc,
                    })

        # Append standalone objects (original pa_name preserved)
        for svc in standalone:
            pa_name = sanitize_fg_name(svc.get("name", ""))
            proto = svc.get("protocol", "").lower()
            port = _convert_pa_ports(svc.get("port", ""))
            desc = svc.get("description", "")
            fg_services.append({
                "fg_name": pa_name,
                "tcp_port": port if proto == "tcp" else "",
                "udp_port": port if proto == "udp" else "",
                "description": desc,
                "merged": False,
                "pa_names": [pa_name],
            })

        # ------------------------------------------------------------------
        # Pass 3: Build name mapping and CLI entries
        # ------------------------------------------------------------------
        entries: List[str] = []
        used_names: Dict[str, int] = {}

        for fg_svc in fg_services:
            fg_name = fg_svc["fg_name"]
            if not fg_name:
                continue

            if fg_name in used_names:
                used_names[fg_name] += 1
                fg_name = f"{fg_name}_{used_names[fg_name]}"
            else:
                used_names[fg_name] = 1

            # Register name mapping for all original PA names
            for pa_name in fg_svc["pa_names"]:
                self._name_map[pa_name] = fg_name

            tcp_port = fg_svc["tcp_port"]
            udp_port = fg_svc["udp_port"]
            description = fg_svc.get("description", "")

            if not tcp_port and not udp_port:
                print(f"  Skipped service: {fg_name} (no ports)")
                self._stats["skipped"] += 1
                continue

            lines = [f'    edit "{fg_name}"']
            if tcp_port:
                lines.append(f"        set tcp-portrange {tcp_port}")
            if udp_port:
                lines.append(f"        set udp-portrange {udp_port}")
            if description:
                safe_desc = description.replace('"', "'")
                lines.append(f'        set comment "{safe_desc}"')
            lines.append("    next")

            entries.append("\n".join(lines))
            self._stats["total"] += 1

            if fg_svc["merged"]:
                self._stats["merged_tcp_udp"] += 1
                print(f"  Converted service: {fg_name} (tcp+udp merged)")
            elif tcp_port:
                self._stats["tcp_only"] += 1
                print(f"  Converted service: {fg_name} (tcp)")
            else:
                self._stats["udp_only"] += 1
                print(f"  Converted service: {fg_name} (udp)")

        if not entries:
            return ""

        block = "config firewall service custom\n"
        block += "\n".join(entries)
        block += "\nend\n"
        return block

    def get_name_map(self) -> Dict[str, str]:
        """Return mapping: original PA service name -> FG service name."""
        return dict(self._name_map)

    def get_statistics(self) -> Dict[str, int]:
        return dict(self._stats)
