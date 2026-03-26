#!/usr/bin/env python3
"""
Firewall Migration Tool - GUI Application
=====================================================
Self-contained Tkinter GUI that wraps the converter, importer, and cleanup
tools for both Cisco FTD and Palo Alto PAN-OS targets.

All phases run **in-process** (no subprocess), so the entire application can
be frozen into a single Windows .exe with PyInstaller.

Build:  see build.bat in the project root.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import ctypes
import sys
import os
import glob
import io
import json
import queue
import traceback

# ---------------------------------------------------------------------------
# Path setup - ensure converter modules are importable regardless of CWD
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    # Running inside a PyInstaller bundle
    APP_DIR = os.path.dirname(sys.executable)
    _PKG_DIR = getattr(sys, "_MEIPASS", APP_DIR)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    _PKG_DIR = APP_DIR

# Add both tool directories to sys.path
_FTD_DIR = os.path.join(APP_DIR, "FortiGateToFTDTool")
_PA_DIR = os.path.join(APP_DIR, "FortiGateToPaloAltoTool")
_ASA_DIR = os.path.join(APP_DIR, "CiscoASAToPaloAltoTool")

for _d in (_FTD_DIR, _PA_DIR, _ASA_DIR, _PKG_DIR):
    if os.path.isdir(_d) and _d not in sys.path:
        sys.path.insert(0, _d)

# Import the three FTD entry points
from fortigate_converter import main as convert_main   # noqa: E402
from ftd_api_importer import main as import_main       # noqa: E402
from ftd_api_cleanup import main as cleanup_main       # noqa: E402

# Palo Alto modules — optional (only needed when PA platform is selected)
_PA_IMPORT_ERROR = ""
try:
    from pa_converter import main as pa_convert_main          # noqa: E402
    from panos_api_importer import main as pa_import_main     # noqa: E402
    from panos_api_cleanup import main as pa_cleanup_main     # noqa: E402
    _PA_AVAILABLE = True
except ImportError as _e:
    _PA_AVAILABLE = False
    _PA_IMPORT_ERROR = str(_e)

# Cisco ASA → Palo Alto modules — optional
_ASA_IMPORT_ERROR = ""
try:
    from asa_converter import main as asa_convert_main        # noqa: E402
    _ASA_AVAILABLE = True
except ImportError as _e:
    _ASA_AVAILABLE = False
    _ASA_IMPORT_ERROR = str(_e)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
FTD_MODEL_LIST = [
    "ftd-1010", "ftd-1120", "ftd-1140",
    "ftd-2110", "ftd-2120", "ftd-2130", "ftd-2140",
    "ftd-3105", "ftd-3110", "ftd-3120", "ftd-3130", "ftd-3140",
    "ftd-4215",
]

PA_MODEL_LIST = [
    "pa-440", "pa-450", "pa-460",
    "pa-3220", "pa-3250",
    "pa-5220",
]

SOURCE_PLATFORM_LIST = ["FortiGate", "Cisco ASA"]

PLATFORM_LIST = ["Cisco FTD", "Palo Alto PAN-OS"]

DEFAULT_DIR = APP_DIR


# ---------------------------------------------------------------------------
# Stdout / stderr redirection
# ---------------------------------------------------------------------------
class _QueueWriter(io.TextIOBase):
    """Thread-safe stdout/stderr substitute that feeds text into a Queue."""

    def __init__(self, q: queue.Queue, tag):
        super().__init__()
        self._q = q
        self._tag = tag

    def write(self, text):
        if text:
            self._q.put((self._tag, text))
        return len(text) if text else 0

    def flush(self):
        pass

    def isatty(self):
        return False


# ---------------------------------------------------------------------------
# Ocean Coral theme palette
# ---------------------------------------------------------------------------
_BG       = "#0b1e24"   # root / frame background
_INPUT    = "#112e35"   # entry / combobox / spinbox fields
_FG       = "#e0d4bc"   # primary text
_FG_DIM   = "#7a9a8a"   # secondary / disabled text
_ACCENT   = "#f08a65"   # coral — accents, active elements
_ACCENT_D = "#1a4450"   # dark teal — buttons resting, selected tab
_ACCENT_H = "#5abaa0"   # teal — hover
_BORDER   = "#3e6058"   # muted green border
_BTN_BG   = "#f08a65"   # coral button resting
_TAB_BG   = "#112e35"   # inactive tab background
_OUT_BG   = "#0b1e24"   # output console background
_OUT_FG   = "#5abaa0"   # teal output console text

APP_VERSION = "1.1.1"


class App(tk.Tk):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.title(f"Firewall Migration Tool v{APP_VERSION}")
        self.geometry("960x720")
        self.minsize(800, 600)

        # Window icon
        if getattr(sys, "frozen", False):
            self.iconbitmap(sys.executable)
        else:
            icon_path = os.path.join(APP_DIR, "app_icon.ico")
            if os.path.isfile(icon_path):
                self.iconbitmap(icon_path)

        self._running = False
        self._worker_thread: threading.Thread | None = None
        self._output_queue: queue.Queue = queue.Queue()

        # Current platform selection
        self._current_platform = "Cisco FTD"
        self._current_source = "FortiGate"

        self._apply_dark_theme()
        self._build_ui()

    # ------------------------------------------------------------------
    # Dark theme
    # ------------------------------------------------------------------
    def _apply_dark_theme(self):
        """Configure ttk.Style for the Ocean Coral theme."""
        self.configure(bg=_BG)

        # Pure-tk widget defaults (messageboxes, dialogs, etc.)
        self.option_add("*background", _BG)
        self.option_add("*foreground", _FG)
        self.option_add("*activeBackground", _ACCENT_D)
        self.option_add("*activeForeground", _FG)
        self.option_add("*selectBackground", _ACCENT_D)
        self.option_add("*selectForeground", _FG)
        self.option_add("*relief", "flat")
        # Combobox popup listbox
        self.option_add("*TCombobox*Listbox.background", _INPUT)
        self.option_add("*TCombobox*Listbox.foreground", _FG)
        self.option_add("*TCombobox*Listbox.selectBackground", _ACCENT_D)
        self.option_add("*TCombobox*Listbox.selectForeground", _FG)

        style = ttk.Style(self)
        style.theme_use("clam")

        # --- Frames ---
        style.configure("TFrame", background=_BG)

        # --- LabelFrame (panels) ---
        style.configure(
            "TLabelframe",
            background=_BG,
            bordercolor=_ACCENT_D,
            relief="groove",
        )
        style.configure(
            "TLabelframe.Label",
            background=_BG,
            foreground=_ACCENT,
            font=("Segoe UI", 9, "bold"),
        )

        # --- Labels ---
        style.configure("TLabel", background=_BG, foreground=_FG)
        style.configure(
            "Status.TLabel",
            background=_TAB_BG,
            foreground=_FG_DIM,
            relief="flat",
        )

        # --- Entry ---
        style.configure(
            "TEntry",
            fieldbackground=_INPUT,
            foreground=_FG,
            insertcolor=_FG,
            bordercolor=_BORDER,
            lightcolor=_BORDER,
            darkcolor=_BORDER,
        )
        style.map(
            "TEntry",
            bordercolor=[("focus", _ACCENT)],
            lightcolor=[("focus", _ACCENT)],
        )

        # --- Button ---
        style.configure(
            "TButton",
            background=_BTN_BG,
            foreground="#000000",
            bordercolor=_ACCENT_D,
            focuscolor=_ACCENT,
            relief="flat",
            padding=(10, 5),
        )
        style.map(
            "TButton",
            background=[
                ("active", _ACCENT_H),
                ("pressed", _ACCENT_D),
                ("disabled", _TAB_BG),
            ],
            foreground=[("disabled", _FG_DIM)],
            bordercolor=[("active", _ACCENT), ("focus", _ACCENT)],
        )

        # --- Checkbutton ---
        style.configure(
            "TCheckbutton",
            background=_BG,
            foreground=_FG,
            indicatorbackground=_INPUT,
            indicatorforeground=_ACCENT,
        )
        style.map(
            "TCheckbutton",
            background=[("active", _BG)],
            indicatorbackground=[("selected", _ACCENT_D), ("active", _INPUT)],
            indicatorforeground=[("selected", _ACCENT), ("active", _FG_DIM)],
            foreground=[("active", _FG)],
        )

        # --- Combobox ---
        style.configure(
            "TCombobox",
            fieldbackground=_INPUT,
            foreground=_FG,
            background=_TAB_BG,
            bordercolor=_BORDER,
            arrowcolor=_FG_DIM,
            insertcolor=_FG,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", _INPUT), ("disabled", _BG)],
            foreground=[("disabled", _FG_DIM)],
            bordercolor=[("focus", _ACCENT)],
            arrowcolor=[("active", _ACCENT)],
        )

        # --- Spinbox ---
        style.configure(
            "TSpinbox",
            fieldbackground=_INPUT,
            foreground=_FG,
            background=_TAB_BG,
            bordercolor=_BORDER,
            arrowcolor=_FG_DIM,
            insertcolor=_FG,
        )
        style.map(
            "TSpinbox",
            bordercolor=[("focus", _ACCENT)],
            arrowcolor=[("active", _ACCENT)],
        )

        # --- Notebook (tabs) ---
        style.configure(
            "TNotebook",
            background=_BG,
            bordercolor=_BORDER,
            tabmargins=[2, 5, 2, 0],
        )
        style.configure(
            "TNotebook.Tab",
            background=_TAB_BG,
            foreground=_FG_DIM,
            bordercolor=_BORDER,
            padding=[12, 5],
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", _ACCENT_D), ("active", _ACCENT_H)],
            foreground=[("selected", _FG), ("active", _FG)],
            expand=[("selected", [1, 1, 1, 0])],
        )

        # --- Scrollbar ---
        style.configure(
            "TScrollbar",
            background=_TAB_BG,
            troughcolor=_BG,
            bordercolor=_BORDER,
            arrowcolor=_FG_DIM,
            relief="flat",
        )
        style.map(
            "TScrollbar",
            background=[("active", _ACCENT_D), ("pressed", _ACCENT)],
            arrowcolor=[("active", _FG)],
        )

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        # Platform selector bar
        platform_frame = ttk.Frame(self)
        platform_frame.pack(fill=tk.X, padx=6, pady=(6, 0))

        ttk.Label(platform_frame, text="Source:").pack(side=tk.LEFT, padx=(4, 4))
        self.source_var = tk.StringVar(value="FortiGate")
        source_combo = ttk.Combobox(
            platform_frame, textvariable=self.source_var,
            values=SOURCE_PLATFORM_LIST, state="readonly", width=14,
        )
        source_combo.pack(side=tk.LEFT)
        source_combo.bind("<<ComboboxSelected>>", self._on_source_change)

        ttk.Label(platform_frame, text="Target:").pack(side=tk.LEFT, padx=(12, 4))
        self.platform_var = tk.StringVar(value="Cisco FTD")
        self.platform_combo = ttk.Combobox(
            platform_frame, textvariable=self.platform_var,
            values=PLATFORM_LIST, state="readonly", width=20,
        )
        self.platform_combo.pack(side=tk.LEFT)
        self.platform_combo.bind("<<ComboboxSelected>>", self._on_platform_change)

        if not _PA_AVAILABLE:
            self._pa_warning = ttk.Label(
                platform_frame, text="(PA modules not found)", foreground=_FG_DIM,
            )
            self._pa_warning.pack(side=tk.LEFT, padx=8)

        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        self._build_convert_tab(notebook)
        self._build_import_tab(notebook)
        self._build_cleanup_tab(notebook)
        self._build_viewer_tab(notebook)

        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(
            self, textvariable=self.status_var, style="Status.TLabel",
            anchor=tk.W, padding=(6, 2),
        ).pack(side=tk.BOTTOM, fill=tk.X)

    def _on_source_change(self, event=None):
        """Handle source platform change — update target list and input label."""
        source = self.source_var.get()
        self._current_source = source

        if source == "Cisco ASA":
            # When source is ASA, target must be Palo Alto PAN-OS
            self.platform_combo.configure(values=["Palo Alto PAN-OS"])
            self.platform_var.set("Palo Alto PAN-OS")
            self._on_platform_change()
            self.conv_input_label.configure(text="Input Config:")
        else:
            # FortiGate — restore both targets
            self.platform_combo.configure(values=PLATFORM_LIST)
            self.conv_input_label.configure(text="Input YAML:")

    def _on_platform_change(self, event=None):
        """Handle platform selector change — update model lists and labels."""
        platform = self.platform_var.get()
        self._current_platform = platform

        if platform == "Palo Alto PAN-OS":
            if not _PA_AVAILABLE:
                detail = f"\n\nError: {_PA_IMPORT_ERROR}" if _PA_IMPORT_ERROR else ""
                search_path = _PA_DIR or "(not found)"
                messagebox.showwarning(
                    "PA Modules Missing",
                    "Palo Alto converter modules not found.\n\n"
                    f"Searched: {search_path}\n"
                    "Make sure the FortiGateToPaloAltoTool directory exists "
                    f"with all required .py files.{detail}",
                )
                self.platform_var.set("Cisco FTD")
                self._current_platform = "Cisco FTD"
                return

            # Update Convert tab
            self.conv_model_combo.configure(values=PA_MODEL_LIST)
            self.conv_model_var.set("pa-440")
            self.conv_output_var.set("pa_config")
            self.conv_ha_var.set("")
            self.conv_ha_entry.configure(state=tk.DISABLED)
            self.conv_ha_label.configure(foreground=_FG_DIM)
            self.conv_ha_hint.configure(text="(not applicable for PAN-OS)")

            # Update Import tab labels
            self.imp_host_label.configure(text="PAN-OS Host / IP:")
            self.imp_base_var.set("pa_config")
            self.imp_workers_label.configure(foreground=_FG_DIM)
            self.imp_workers_spin.configure(state=tk.DISABLED)
            self.imp_deploy_cb.configure(text="Commit after import")

            # Update Cleanup tab labels
            self.cln_host_label.configure(text="PAN-OS Host / IP:")
            self.cln_model_combo.configure(values=PA_MODEL_LIST)
            self.cln_model_var.set("pa-440")
            self.cln_deploy_cb.configure(text="Commit after cleanup")

            source = self._current_source
            if source == "Cisco ASA":
                self.title(f"Cisco ASA to Palo Alto PAN-OS Migration Tool v{APP_VERSION}")
            else:
                self.title(f"FortiGate to Palo Alto PAN-OS Migration Tool v{APP_VERSION}")
        else:
            # Restore FTD defaults
            self.conv_model_combo.configure(values=FTD_MODEL_LIST)
            self.conv_model_var.set("ftd-3120")
            self.conv_output_var.set("ftd_config")
            self.conv_ha_entry.configure(state=tk.NORMAL)
            self.conv_ha_label.configure(foreground=_FG)
            self.conv_ha_hint.configure(text="e.g. Ethernet1/5  (leave blank = no HA port)")

            self.imp_host_label.configure(text="FTD Host / IP:")
            self.imp_base_var.set("ftd_config")
            self.imp_workers_label.configure(foreground=_FG)
            self.imp_workers_spin.configure(state=tk.NORMAL)
            self.imp_deploy_cb.configure(text="Deploy after import")

            self.cln_host_label.configure(text="FTD Host / IP:")
            self.cln_model_combo.configure(values=FTD_MODEL_LIST)
            self.cln_model_var.set("ftd-3120")
            self.cln_deploy_cb.configure(text="Deploy after cleanup")

            self.title(f"FortiGate to Cisco FTD Converter v{APP_VERSION}")

    # ==================== CONVERT TAB ====================
    def _build_convert_tab(self, notebook):
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="  Convert  ")

        opts = ttk.LabelFrame(tab, text="Conversion Options", padding=10)
        opts.pack(fill=tk.X, padx=8, pady=(8, 4))

        # Row 0: Input file
        self.conv_input_label = ttk.Label(opts, text="Input YAML:")
        self.conv_input_label.grid(row=0, column=0, sticky=tk.W, pady=3)
        self.conv_input_var = tk.StringVar()
        ttk.Entry(opts, textvariable=self.conv_input_var, width=60).grid(
            row=0, column=1, sticky=tk.EW, padx=4,
        )
        ttk.Button(opts, text="Browse...", command=self._browse_yaml).grid(
            row=0, column=2, padx=4,
        )

        # Row 1: Output directory
        ttk.Label(opts, text="Output Directory:").grid(row=1, column=0, sticky=tk.W, pady=3)
        self.conv_outdir_var = tk.StringVar(value=DEFAULT_DIR)
        ttk.Entry(opts, textvariable=self.conv_outdir_var, width=60).grid(
            row=1, column=1, sticky=tk.EW, padx=4,
        )
        ttk.Button(opts, text="Browse...", command=self._browse_outdir).grid(
            row=1, column=2, padx=4,
        )

        # Row 2: Output base name
        ttk.Label(opts, text="Output Base Name:").grid(row=2, column=0, sticky=tk.W, pady=3)
        self.conv_output_var = tk.StringVar(value="ftd_config")
        ttk.Entry(opts, textvariable=self.conv_output_var, width=30).grid(
            row=2, column=1, sticky=tk.W, padx=4,
        )

        # Row 3: Target model
        ttk.Label(opts, text="Target Model:").grid(row=3, column=0, sticky=tk.W, pady=3)
        self.conv_model_var = tk.StringVar(value="ftd-3120")
        self.conv_model_combo = ttk.Combobox(
            opts, textvariable=self.conv_model_var,
            values=FTD_MODEL_LIST, state="readonly", width=18,
        )
        self.conv_model_combo.grid(row=3, column=1, sticky=tk.W, padx=4)

        # Row 4: HA port (optional)
        self.conv_ha_label = ttk.Label(opts, text="HA Port (optional):")
        self.conv_ha_label.grid(row=4, column=0, sticky=tk.W, pady=3)
        self.conv_ha_var = tk.StringVar()
        self.conv_ha_entry = ttk.Entry(opts, textvariable=self.conv_ha_var, width=20)
        self.conv_ha_entry.grid(row=4, column=1, sticky=tk.W, padx=4)
        self.conv_ha_hint = ttk.Label(opts, text="e.g. Ethernet1/5  (leave blank = no HA port)")
        self.conv_ha_hint.grid(row=5, column=1, sticky=tk.W)

        # Row 5: Pretty-print
        self.conv_pretty_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            opts, text="Pretty-print JSON output", variable=self.conv_pretty_var,
        ).grid(row=6, column=1, sticky=tk.W, padx=4, pady=3)

        opts.columnconfigure(1, weight=1)

        # Buttons
        btn_frame = ttk.Frame(tab)
        btn_frame.pack(fill=tk.X, padx=8, pady=4)
        self.conv_run_btn = ttk.Button(
            btn_frame, text="Run Conversion", command=self._run_convert,
        )
        self.conv_run_btn.pack(side=tk.LEFT)
        self.conv_cancel_btn = ttk.Button(
            btn_frame, text="Cancel", command=self._cancel_operation,
            state=tk.DISABLED,
        )
        self.conv_cancel_btn.pack(side=tk.LEFT, padx=8)
        ttk.Button(
            btn_frame, text="Clear Output",
            command=lambda: self._clear_output(self.conv_output),
        ).pack(side=tk.LEFT, padx=8)

        self.conv_output = self._make_output_area(tab)

    # ==================== IMPORT TAB ====================
    def _build_import_tab(self, notebook):
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="  Import to FTD  ")

        opts = ttk.LabelFrame(tab, text="FTD Connection & Import Options", padding=10)
        opts.pack(fill=tk.X, padx=8, pady=(8, 4))

        # Connection settings
        self.imp_host_label = ttk.Label(opts, text="FTD Host / IP:")
        self.imp_host_label.grid(row=0, column=0, sticky=tk.W, pady=3)
        self.imp_host_var = tk.StringVar()
        ttk.Entry(opts, textvariable=self.imp_host_var, width=30).grid(
            row=0, column=1, sticky=tk.W, padx=4,
        )

        ttk.Label(opts, text="Username:").grid(row=1, column=0, sticky=tk.W, pady=3)
        self.imp_user_var = tk.StringVar(value="admin")
        ttk.Entry(opts, textvariable=self.imp_user_var, width=30).grid(
            row=1, column=1, sticky=tk.W, padx=4,
        )

        ttk.Label(opts, text="Password:").grid(row=2, column=0, sticky=tk.W, pady=3)
        self.imp_pass_var = tk.StringVar()
        ttk.Entry(opts, textvariable=self.imp_pass_var, show="*", width=30).grid(
            row=2, column=1, sticky=tk.W, padx=4,
        )

        # Config directory
        ttk.Label(opts, text="Config Directory:").grid(row=3, column=0, sticky=tk.W, pady=3)
        self.imp_dir_var = tk.StringVar(value=DEFAULT_DIR)
        ttk.Entry(opts, textvariable=self.imp_dir_var, width=50).grid(
            row=3, column=1, sticky=tk.EW, padx=4,
        )
        ttk.Button(opts, text="Browse...", command=self._browse_impdir).grid(
            row=3, column=2, padx=4,
        )

        ttk.Label(opts, text="JSON Base Name:").grid(row=4, column=0, sticky=tk.W, pady=3)
        self.imp_base_var = tk.StringVar(value="ftd_config")
        ttk.Entry(opts, textvariable=self.imp_base_var, width=30).grid(
            row=4, column=1, sticky=tk.W, padx=4,
        )

        self.imp_workers_label = ttk.Label(opts, text="Workers:")
        self.imp_workers_label.grid(row=5, column=0, sticky=tk.W, pady=3)
        self.imp_workers_var = tk.StringVar(value="6")
        self.imp_workers_spin = ttk.Spinbox(
            opts, from_=1, to=32, textvariable=self.imp_workers_var, width=6,
        )
        self.imp_workers_spin.grid(row=5, column=1, sticky=tk.W, padx=4)

        self.imp_deploy_var = tk.BooleanVar()
        self.imp_deploy_cb = ttk.Checkbutton(
            opts, text="Deploy after import", variable=self.imp_deploy_var,
        )
        self.imp_deploy_cb.grid(row=6, column=1, sticky=tk.W, padx=4, pady=3)

        self.imp_debug_var = tk.BooleanVar()
        ttk.Checkbutton(
            opts, text="Debug mode (show API payloads)", variable=self.imp_debug_var,
        ).grid(row=7, column=1, sticky=tk.W, padx=4, pady=3)

        opts.columnconfigure(1, weight=1)

        # Selective import
        sel = ttk.LabelFrame(
            tab, text="Selective Import (leave unchecked to import all)", padding=8,
        )
        sel.pack(fill=tk.X, padx=8, pady=4)

        self.imp_only_vars = {}
        only_types = [
            ("Physical Interfaces", "physical-interfaces"),
            ("EtherChannels", "etherchannels"),
            ("Subinterfaces", "subinterfaces"),
            ("Bridge Groups", "bridge-groups"),
            ("Security Zones", "security-zones"),
            ("Address Objects", "address-objects"),
            ("Address Groups", "address-groups"),
            ("Service Objects", "service-objects"),
            ("Service Groups", "service-groups"),
            ("Static Routes", "routes"),
            ("Access Rules", "rules"),
        ]
        for i, (label, key) in enumerate(only_types):
            var = tk.BooleanVar()
            self.imp_only_vars[key] = var
            row, col = divmod(i, 3)
            ttk.Checkbutton(sel, text=label, variable=var).grid(
                row=row, column=col, sticky=tk.W, padx=6, pady=2,
            )

        # Buttons
        btn_frame = ttk.Frame(tab)
        btn_frame.pack(fill=tk.X, padx=8, pady=4)
        self.imp_run_btn = ttk.Button(
            btn_frame, text="Start Import", command=self._run_import,
        )
        self.imp_run_btn.pack(side=tk.LEFT)
        self.imp_cancel_btn = ttk.Button(
            btn_frame, text="Cancel", command=self._cancel_operation,
            state=tk.DISABLED,
        )
        self.imp_cancel_btn.pack(side=tk.LEFT, padx=8)
        ttk.Button(
            btn_frame, text="Clear Output",
            command=lambda: self._clear_output(self.imp_output),
        ).pack(side=tk.LEFT, padx=8)

        self.imp_output = self._make_output_area(tab)

    # ==================== CLEANUP TAB ====================
    def _build_cleanup_tab(self, notebook):
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="  Cleanup FTD  ")

        opts = ttk.LabelFrame(tab, text="FTD Connection", padding=10)
        opts.pack(fill=tk.X, padx=8, pady=(8, 4))

        self.cln_host_label = ttk.Label(opts, text="FTD Host / IP:")
        self.cln_host_label.grid(row=0, column=0, sticky=tk.W, pady=3)
        self.cln_host_var = tk.StringVar()
        ttk.Entry(opts, textvariable=self.cln_host_var, width=30).grid(
            row=0, column=1, sticky=tk.W, padx=4,
        )

        ttk.Label(opts, text="Username:").grid(row=1, column=0, sticky=tk.W, pady=3)
        self.cln_user_var = tk.StringVar(value="admin")
        ttk.Entry(opts, textvariable=self.cln_user_var, width=30).grid(
            row=1, column=1, sticky=tk.W, padx=4,
        )

        ttk.Label(opts, text="Password:").grid(row=2, column=0, sticky=tk.W, pady=3)
        self.cln_pass_var = tk.StringVar()
        ttk.Entry(opts, textvariable=self.cln_pass_var, show="*", width=30).grid(
            row=2, column=1, sticky=tk.W, padx=4,
        )

        ttk.Label(opts, text="Target Model:").grid(row=3, column=0, sticky=tk.W, pady=3)
        self.cln_model_var = tk.StringVar(value="ftd-3120")
        self.cln_model_combo = ttk.Combobox(
            opts, textvariable=self.cln_model_var,
            values=FTD_MODEL_LIST, state="readonly", width=18,
        )
        self.cln_model_combo.grid(row=3, column=1, sticky=tk.W, padx=4)

        ttk.Label(opts, text="Workers:").grid(row=4, column=0, sticky=tk.W, pady=3)
        self.cln_workers_var = tk.StringVar(value="6")
        ttk.Spinbox(
            opts, from_=1, to=32, textvariable=self.cln_workers_var, width=6,
        ).grid(row=4, column=1, sticky=tk.W, padx=4)

        opts.columnconfigure(1, weight=1)

        # Delete options
        del_frame = ttk.LabelFrame(tab, text="What to Delete", padding=8)
        del_frame.pack(fill=tk.X, padx=8, pady=4)

        self.cln_all_var = tk.BooleanVar()
        ttk.Checkbutton(
            del_frame, text="Delete ALL custom objects", variable=self.cln_all_var,
        ).grid(row=0, column=0, columnspan=3, sticky=tk.W, padx=6, pady=4)

        self.cln_del_vars = {}
        del_types = [
            ("Access Rules", "rules"),
            ("Static Routes", "routes"),
            ("Subinterfaces", "subinterfaces"),
            ("EtherChannels", "etherchannels"),
            ("Security Zones", "security-zones"),
            ("Bridge Groups", "bridge-groups"),
            ("Service Groups", "service-groups"),
            ("Service Objects", "service-objects"),
            ("Address Groups", "address-groups"),
            ("Address Objects", "address-objects"),
            ("Physical Interfaces (reset)", "reset-physical-interfaces"),
        ]
        for i, (label, key) in enumerate(del_types):
            var = tk.BooleanVar()
            self.cln_del_vars[key] = var
            row, col = divmod(i, 3)
            ttk.Checkbutton(del_frame, text=label, variable=var).grid(
                row=row + 1, column=col, sticky=tk.W, padx=6, pady=2,
            )

        # Flags
        flag_frame = ttk.Frame(tab)
        flag_frame.pack(fill=tk.X, padx=8, pady=4)
        self.cln_dry_var = tk.BooleanVar()
        ttk.Checkbutton(
            flag_frame, text="Dry run (preview only)", variable=self.cln_dry_var,
        ).pack(side=tk.LEFT, padx=6)
        self.cln_deploy_var = tk.BooleanVar()
        self.cln_deploy_cb = ttk.Checkbutton(
            flag_frame, text="Deploy after cleanup", variable=self.cln_deploy_var,
        )
        self.cln_deploy_cb.pack(side=tk.LEFT, padx=6)

        # Buttons
        btn_frame = ttk.Frame(tab)
        btn_frame.pack(fill=tk.X, padx=8, pady=4)
        self.cln_run_btn = ttk.Button(
            btn_frame, text="Start Cleanup", command=self._run_cleanup,
        )
        self.cln_run_btn.pack(side=tk.LEFT)
        self.cln_cancel_btn = ttk.Button(
            btn_frame, text="Cancel", command=self._cancel_operation,
            state=tk.DISABLED,
        )
        self.cln_cancel_btn.pack(side=tk.LEFT, padx=8)
        ttk.Button(
            btn_frame, text="Clear Output",
            command=lambda: self._clear_output(self.cln_output),
        ).pack(side=tk.LEFT, padx=8)

        self.cln_output = self._make_output_area(tab)

    # ==================== CONFIG VIEWER TAB ====================
    def _build_viewer_tab(self, notebook):
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="  Config Viewer  ")

        # Top bar: directory selector
        top = ttk.LabelFrame(tab, text="Config Files", padding=10)
        top.pack(fill=tk.X, padx=8, pady=(8, 4))

        ttk.Label(top, text="Config Directory:").grid(row=0, column=0, sticky=tk.W, pady=3)
        self.viewer_dir_var = tk.StringVar(value=DEFAULT_DIR)
        ttk.Entry(top, textvariable=self.viewer_dir_var, width=50).grid(
            row=0, column=1, sticky=tk.EW, padx=4,
        )
        ttk.Button(top, text="Browse...", command=self._browse_viewer_dir).grid(
            row=0, column=2, padx=4,
        )

        ttk.Label(top, text="JSON Base Name:").grid(row=1, column=0, sticky=tk.W, pady=3)
        self.viewer_base_var = tk.StringVar(value="ftd_config")
        ttk.Entry(top, textvariable=self.viewer_base_var, width=30).grid(
            row=1, column=1, sticky=tk.W, padx=4,
        )

        ttk.Button(top, text="Load Files", command=self._load_viewer_files).grid(
            row=1, column=2, padx=4,
        )

        top.columnconfigure(1, weight=1)

        # Middle: file selector listbox + JSON viewer (side by side)
        body = ttk.Frame(tab)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        # Left pane: file list
        list_frame = ttk.Frame(body)
        list_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 4))

        ttk.Label(list_frame, text="Config Files:").pack(anchor=tk.W)
        self.viewer_listbox = tk.Listbox(
            list_frame, width=30, font=("Consolas", 10),
            bg=_OUT_BG, fg=_OUT_FG,
            selectbackground=_ACCENT_D, selectforeground=_OUT_FG,
            highlightthickness=1, highlightbackground=_BORDER, highlightcolor=_ACCENT,
            relief=tk.FLAT, bd=1,
        )
        list_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.viewer_listbox.yview)
        self.viewer_listbox.configure(yscrollcommand=list_scroll.set)
        list_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.viewer_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.viewer_listbox.bind("<<ListboxSelect>>", self._on_viewer_select)

        # Right pane: JSON content
        content_frame = ttk.Frame(body)
        content_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        ttk.Label(content_frame, text="File Contents:").pack(anchor=tk.W)

        # Search bar
        search_bar = ttk.Frame(content_frame)
        search_bar.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(search_bar, text="Search:").pack(side=tk.LEFT)
        self._viewer_search_var = tk.StringVar()
        search_entry = ttk.Entry(search_bar, textvariable=self._viewer_search_var, width=30)
        search_entry.pack(side=tk.LEFT, padx=4)
        search_entry.bind("<Return>", lambda e: self._viewer_find_next())
        ttk.Button(search_bar, text="Find Next", command=self._viewer_find_next).pack(side=tk.LEFT, padx=2)
        ttk.Button(search_bar, text="Find Prev", command=self._viewer_find_prev).pack(side=tk.LEFT, padx=2)
        self._viewer_match_label = ttk.Label(search_bar, text="")
        self._viewer_match_label.pack(side=tk.LEFT, padx=6)
        self._viewer_search_idx = "1.0"

        self.viewer_text = tk.Text(
            content_frame, wrap=tk.NONE, font=("Consolas", 10),
            bg=_OUT_BG, fg=_OUT_FG,
            insertbackground=_OUT_FG,
            selectbackground=_ACCENT_D, selectforeground=_OUT_FG,
            state=tk.DISABLED, relief=tk.FLAT, bd=1,
            highlightthickness=1, highlightbackground=_BORDER, highlightcolor=_ACCENT,
        )
        yscroll = ttk.Scrollbar(content_frame, orient=tk.VERTICAL, command=self.viewer_text.yview)
        xscroll = ttk.Scrollbar(content_frame, orient=tk.HORIZONTAL, command=self.viewer_text.xview)
        self.viewer_text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        xscroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.viewer_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Storage for discovered file paths
        self._viewer_files: list[str] = []

    def _browse_viewer_dir(self):
        d = filedialog.askdirectory(title="Select Config Files Directory")
        if d:
            self.viewer_dir_var.set(d)

    def _load_viewer_files(self):
        """Scan the config directory for JSON files matching the base name."""
        config_dir = self.viewer_dir_var.get().strip()
        base = self.viewer_base_var.get().strip() or "ftd_config"

        if not config_dir or not os.path.isdir(config_dir):
            messagebox.showerror("Invalid Directory", "Please select a valid config directory.")
            return

        pattern = os.path.join(config_dir, f"{base}_*.json")
        files = sorted(glob.glob(pattern))

        self.viewer_listbox.delete(0, tk.END)
        self._viewer_files = files

        if not files:
            messagebox.showinfo("No Files", f"No files matching '{base}_*.json' found in:\n{config_dir}")
            return

        for f in files:
            self.viewer_listbox.insert(tk.END, os.path.basename(f))

    def _on_viewer_select(self, event):
        """Display the selected JSON file in the viewer."""
        sel = self.viewer_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self._viewer_files):
            return

        filepath = self._viewer_files[idx]
        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                raw = fh.read()
            # Pretty-print if valid JSON
            try:
                data = json.loads(raw)
                display = json.dumps(data, indent=2)
            except (json.JSONDecodeError, ValueError):
                display = raw
        except OSError as exc:
            display = f"Error reading file: {exc}"

        self.viewer_text.configure(state=tk.NORMAL)
        self.viewer_text.delete("1.0", tk.END)
        self.viewer_text.insert("1.0", display)
        self.viewer_text.configure(state=tk.DISABLED)
        # Reset search position when a new file is loaded
        self._viewer_search_idx = "1.0"
        self._viewer_clear_highlights()
        self._viewer_match_label.configure(text="")

    def _viewer_clear_highlights(self):
        self.viewer_text.tag_remove("search_hit", "1.0", tk.END)
        self.viewer_text.tag_remove("search_current", "1.0", tk.END)

    def _viewer_find(self, forwards: bool = True):
        query = self._viewer_search_var.get()
        if not query:
            self._viewer_clear_highlights()
            self._viewer_match_label.configure(text="")
            return

        self._viewer_clear_highlights()

        # Highlight all matches
        self.viewer_text.tag_configure("search_hit", background="#3a3a00", foreground=_OUT_FG)
        self.viewer_text.tag_configure("search_current", background="#48ea33", foreground="#000000")

        count_var = tk.IntVar()
        total = 0
        pos = "1.0"
        while True:
            pos = self.viewer_text.search(query, pos, stopindex=tk.END, nocase=True, count=count_var)
            if not pos:
                break
            end = f"{pos}+{count_var.get()}c"
            self.viewer_text.tag_add("search_hit", pos, end)
            total += 1
            pos = end

        if total == 0:
            self._viewer_match_label.configure(text="No matches")
            return

        # Find next/prev from current position
        if forwards:
            hit = self.viewer_text.search(query, self._viewer_search_idx, stopindex=tk.END, nocase=True, count=count_var)
            if not hit:
                # Wrap to beginning
                hit = self.viewer_text.search(query, "1.0", stopindex=tk.END, nocase=True, count=count_var)
        else:
            hit = self.viewer_text.search(query, self._viewer_search_idx, stopindex="1.0", backwards=True, nocase=True, count=count_var)
            if not hit:
                # Wrap to end
                hit = self.viewer_text.search(query, tk.END, stopindex="1.0", backwards=True, nocase=True, count=count_var)

        if hit:
            end = f"{hit}+{count_var.get()}c"
            self.viewer_text.tag_add("search_current", hit, end)
            self.viewer_text.see(hit)
            # Advance past this match for the next search
            self._viewer_search_idx = end if forwards else hit

        # Count which match we're on
        match_num = 0
        pos = "1.0"
        while hit and pos:
            pos = self.viewer_text.search(query, pos, stopindex=tk.END, nocase=True, count=count_var)
            if not pos:
                break
            match_num += 1
            if self.viewer_text.compare(pos, "==", hit):
                break
            pos = f"{pos}+{count_var.get()}c"

        self._viewer_match_label.configure(text=f"{match_num} of {total}")

    def _viewer_find_next(self):
        self._viewer_find(forwards=True)

    def _viewer_find_prev(self):
        self._viewer_find(forwards=False)

    # ------------------------------------------------------------------
    # Shared widgets / helpers
    # ------------------------------------------------------------------
    def _make_output_area(self, parent):
        """Create a scrollable text widget for command output."""
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        text = tk.Text(
            frame, wrap=tk.WORD, font=("Consolas", 10),
            bg=_OUT_BG, fg=_OUT_FG,
            insertbackground=_OUT_FG,
            selectbackground=_ACCENT_D, selectforeground=_OUT_FG,
            state=tk.DISABLED, relief=tk.FLAT, bd=1,
            highlightthickness=1, highlightbackground=_BORDER, highlightcolor=_ACCENT,
        )
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        return text

    def _append_output(self, text_widget, content):
        """Append text to a read-only text widget and auto-scroll."""
        text_widget.configure(state=tk.NORMAL)
        text_widget.insert(tk.END, content)
        text_widget.see(tk.END)
        text_widget.configure(state=tk.DISABLED)

    def _clear_output(self, text_widget):
        text_widget.configure(state=tk.NORMAL)
        text_widget.delete("1.0", tk.END)
        text_widget.configure(state=tk.DISABLED)

    def _browse_yaml(self):
        if self._current_source == "Cisco ASA":
            path = filedialog.askopenfilename(
                title="Select Cisco ASA Configuration File",
                filetypes=[
                    ("Config files", "*.txt *.cfg *.conf"),
                    ("All files", "*.*"),
                ],
            )
        else:
            path = filedialog.askopenfilename(
                title="Select FortiGate YAML Configuration",
                filetypes=[("YAML files", "*.yaml *.yml"), ("All files", "*.*")],
            )
        if path:
            self.conv_input_var.set(path)
            # Auto-set output directory to same folder as the input file
            self.conv_outdir_var.set(os.path.dirname(path))

    def _browse_outdir(self):
        d = filedialog.askdirectory(title="Select Output Directory")
        if d:
            self.conv_outdir_var.set(d)

    def _browse_impdir(self):
        d = filedialog.askdirectory(title="Select Config Files Directory")
        if d:
            self.imp_dir_var.set(d)

    def _set_buttons_state(self, state):
        """Enable or disable all run buttons (and toggle cancel buttons inversely)."""
        cancel_state = tk.DISABLED if state == tk.NORMAL else tk.NORMAL
        for btn in (self.conv_run_btn, self.imp_run_btn, self.cln_run_btn):
            btn.configure(state=state)
        for btn in (self.conv_cancel_btn, self.imp_cancel_btn, self.cln_cancel_btn):
            btn.configure(state=cancel_state)

    # ------------------------------------------------------------------
    # In-process execution engine
    # ------------------------------------------------------------------
    def _run_in_thread(self, func, argv, text_widget, label="Operation"):
        """
        Run a module's main(argv) in a background thread while capturing
        all stdout/stderr output and streaming it to the given text widget.
        """
        if self._running:
            messagebox.showwarning(
                "Busy", "An operation is already running. Please wait.",
            )
            return

        self._clear_output(text_widget)
        self._append_output(text_widget, f"> {label} {' '.join(argv)}\n\n")
        self._set_buttons_state(tk.DISABLED)
        self._running = True
        self.status_var.set(f"Running: {label}...")

        def _worker():
            old_stdout, old_stderr = sys.stdout, sys.stderr
            writer = _QueueWriter(self._output_queue, text_widget)
            sys.stdout = writer
            sys.stderr = writer
            try:
                exit_code = func(argv)
                if exit_code is None:
                    exit_code = 0
                self._output_queue.put(
                    (text_widget, f"\n--- Finished (exit code {exit_code}) ---\n"),
                )
            except SystemExit as exc:
                code = exc.code if exc.code is not None else 0
                self._output_queue.put(
                    (text_widget, f"\n--- Finished (exit code {code}) ---\n"),
                )
            except Exception as exc:
                self._output_queue.put(
                    (text_widget, f"\n--- ERROR: {exc} ---\n"),
                )
                self._output_queue.put((text_widget, traceback.format_exc()))
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr
                self._output_queue.put((text_widget, None))  # sentinel

        self._worker_thread = threading.Thread(target=_worker, daemon=True)
        self._worker_thread.start()
        self._poll_output()

    def _poll_output(self):
        """Drain the output queue and schedule the next poll."""
        try:
            while True:
                widget, text = self._output_queue.get_nowait()
                if text is None:
                    # Worker thread finished
                    self._running = False
                    self._set_buttons_state(tk.NORMAL)
                    self.status_var.set("Ready")
                    return
                self._append_output(widget, text)
        except queue.Empty:
            pass
        self.after(50, self._poll_output)

    def _cancel_operation(self):
        """Cancel the currently running operation by raising SystemExit in the worker thread."""
        if not self._running or self._worker_thread is None:
            return
        tid = self._worker_thread.ident
        if tid is None:
            return
        # Raise SystemExit asynchronously in the worker thread
        res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_ulong(tid), ctypes.py_object(SystemExit),
        )
        if res == 0:
            return  # thread already finished
        self.status_var.set("Cancelling...")

    # ------------------------------------------------------------------
    # Run commands
    # ------------------------------------------------------------------
    def _run_convert(self):
        input_file = self.conv_input_var.get().strip()
        is_asa = self._current_source == "Cisco ASA"

        if not input_file:
            file_type = "Cisco ASA config" if is_asa else "FortiGate YAML"
            messagebox.showerror("Missing Input", f"Please select a {file_type} file.")
            return

        is_pa = self._current_platform == "Palo Alto PAN-OS"

        outdir = self.conv_outdir_var.get().strip()
        base = self.conv_output_var.get().strip() or ("pa_config" if is_pa else "ftd_config")
        full_base = os.path.join(outdir, base) if outdir else base

        argv = [input_file, "-o", full_base]

        model = self.conv_model_var.get()
        if model:
            argv.extend(["-m", model])

        if not is_pa:
            ha_port = self.conv_ha_var.get().strip()
            # Always pass --ha-port: user value or "none" to skip model default
            argv.extend(["--ha-port", ha_port if ha_port else "none"])

        if self.conv_pretty_var.get():
            argv.append("--pretty")

        if is_asa:
            if not _ASA_AVAILABLE:
                messagebox.showerror(
                    "ASA Modules Missing",
                    f"Cisco ASA converter modules not found.\n\n"
                    f"Error: {_ASA_IMPORT_ERROR}",
                )
                return
            main_fn = asa_convert_main
        elif is_pa:
            main_fn = pa_convert_main
        else:
            main_fn = convert_main
        self._run_in_thread(main_fn, argv, self.conv_output, "Convert")

    def _run_import(self):
        host = self.imp_host_var.get().strip()
        password = self.imp_pass_var.get()
        is_pa = self._current_platform == "Palo Alto PAN-OS"

        platform_label = "PAN-OS" if is_pa else "FTD"
        if not host:
            messagebox.showerror("Missing Field", f"Please enter the {platform_label} host/IP address.")
            return
        if not password:
            messagebox.showerror("Missing Field", f"Please enter the {platform_label} password.")
            return

        impdir = self.imp_dir_var.get().strip()
        base = self.imp_base_var.get().strip() or ("pa_config" if is_pa else "ftd_config")
        full_base = os.path.join(impdir, base) if impdir else base

        if is_pa:
            argv = [
                "--host", host,
                "--username", self.imp_user_var.get().strip() or "admin",
                "--password", password,
                "--input", full_base,
            ]
            if self.imp_deploy_var.get():
                argv.append("--commit")
            if self.imp_debug_var.get():
                argv.append("--debug")

            self._run_in_thread(pa_import_main, argv, self.imp_output, "Import (PAN-OS)")
        else:
            argv = [
                "--host", host,
                "-u", self.imp_user_var.get().strip() or "admin",
                "-p", password,
                "--base", full_base,
                "--workers", self.imp_workers_var.get(),
            ]

            if self.imp_deploy_var.get():
                argv.append("--deploy")
            if self.imp_debug_var.get():
                argv.append("--debug")

            # Selective import flags
            selected = [k for k, v in self.imp_only_vars.items() if v.get()]
            for key in selected:
                argv.append(f"--only-{key}")

            self._run_in_thread(import_main, argv, self.imp_output, "Import")

    def _run_cleanup(self):
        host = self.cln_host_var.get().strip()
        password = self.cln_pass_var.get()
        is_pa = self._current_platform == "Palo Alto PAN-OS"

        platform_label = "PAN-OS" if is_pa else "FTD"
        if not host:
            messagebox.showerror("Missing Field", f"Please enter the {platform_label} host/IP address.")
            return
        if not password:
            messagebox.showerror("Missing Field", f"Please enter the {platform_label} password.")
            return

        if is_pa:
            argv = [
                "--host", host,
                "--username", self.cln_user_var.get().strip() or "admin",
                "--password", password,
            ]

            if self.cln_dry_var.get():
                argv.append("--dry-run")
            if self.cln_deploy_var.get():
                argv.append("--commit")

            if self.cln_all_var.get():
                argv.append("--delete-all")
            else:
                selected = [k for k, v in self.cln_del_vars.items() if v.get()]
                if not selected:
                    messagebox.showerror(
                        "Nothing Selected",
                        "Please check 'Delete ALL' or select specific object types.",
                    )
                    return
                for key in selected:
                    # Map FTD-style keys to PA cleanup flags
                    pa_key_map = {
                        "rules": "security-rules",
                        "routes": "static-routes",
                    }
                    mapped = pa_key_map.get(key, key)
                    argv.append(f"--delete-{mapped}")

            # Confirm before destructive cleanup
            if not self.cln_dry_var.get():
                if not messagebox.askyesno(
                    "Confirm Cleanup",
                    "This will DELETE objects from the PAN-OS device.\n\n"
                    "Are you sure you want to proceed?\n\n"
                    "(Use 'Dry run' to preview first)",
                ):
                    return

            self._run_in_thread(pa_cleanup_main, argv, self.cln_output, "Cleanup (PAN-OS)")
        else:
            argv = [
                "--host", host,
                "-u", self.cln_user_var.get().strip() or "admin",
                "-p", password,
                "--appliance-model", self.cln_model_var.get(),
                "--workers", self.cln_workers_var.get(),
                "--yes",  # skip CLI interactive prompt (GUI has its own dialog)
            ]

            if self.cln_dry_var.get():
                argv.append("--dry-run")
            if self.cln_deploy_var.get():
                argv.append("--deploy")

            if self.cln_all_var.get():
                argv.append("--delete-all")
            else:
                selected = [k for k, v in self.cln_del_vars.items() if v.get()]
                if not selected:
                    messagebox.showerror(
                        "Nothing Selected",
                        "Please check 'Delete ALL' or select specific object types.",
                    )
                    return
                for key in selected:
                    if key == "reset-physical-interfaces":
                        argv.append("--reset-physical-interfaces")
                    else:
                        argv.append(f"--delete-{key}")

            # Confirm before destructive cleanup
            if not self.cln_dry_var.get():
                if not messagebox.askyesno(
                    "Confirm Cleanup",
                    "This will DELETE objects from the FTD device.\n\n"
                    "Are you sure you want to proceed?\n\n"
                    "(Use 'Dry run' to preview first)",
                ):
                    return

            self._run_in_thread(cleanup_main, argv, self.cln_output, "Cleanup")


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
