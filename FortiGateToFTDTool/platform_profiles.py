#!/usr/bin/env python3
"""Shared appliance model family helpers for importer and cleanup scripts."""

from typing import Optional


FTD_1000_SERIES = {
    "ftd-1010", "1010", "ftd1010",
    "ftd-1120", "1120", "ftd1120",
    "ftd-1140", "1140", "ftd1140",
}

FTD_2000_SERIES = {
    "ftd-2110", "2110", "ftd2110",
    "ftd-2120", "2120", "ftd2120",
    "ftd-2130", "2130", "ftd2130",
    "ftd-2140", "2140", "ftd2140",
}

FTD_3100_SERIES = {
    "ftd-3105", "3105", "ftd3105",
    "ftd-3110", "3110", "ftd3110",
    "ftd-3120", "3120", "ftd3120",
    "ftd-3130", "3130", "ftd3130",
    "ftd-3140", "3140", "ftd3140",
    "ftd-4215", "4215", "ftd4215",
}


def normalize_model(model: Optional[str]) -> str:
    """Normalize model string for family membership checks."""
    return str(model or "generic").lower().strip()


def is_ftd_1000(model: Optional[str]) -> bool:
    return normalize_model(model) in FTD_1000_SERIES


def is_ftd_2000(model: Optional[str]) -> bool:
    return normalize_model(model) in FTD_2000_SERIES


def is_ftd_3100(model: Optional[str]) -> bool:
    return normalize_model(model) in FTD_3100_SERIES
