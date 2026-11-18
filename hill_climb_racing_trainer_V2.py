"""
Hill Climb Racing Trainer V2 – Premium Edition
================================================
Features
--------
* Modern dark-mode UI with glassmorphism-style panels
* Smooth button animations and status-bar pulse
* Fully typed MemHelper with ReadWriteMemory + pymem fallback
* TrainerController separates business logic from UI
* Hotkey registration with live feedback
* JSON config persistence (coins, diamonds, fuel, boost, hotkeys)
* Infinite-fuel freeze thread with adjustable interval
* Boost pointer recalibration (3 offset sets)
* Proper cleanup on window close
* 🤖 NEAT AI Auto-Play — neural network evolves to drive the car automatically

Dependencies
------------
  pip install ReadWriteMemory pymem psutil keyboard Pillow
"""

from __future__ import annotations

import os
import sys
import json
import time
import struct
import threading
import ctypes
from ctypes import wintypes
from typing import Optional, List, Tuple, Dict, Any

import tkinter as tk
from tkinter import messagebox, ttk, filedialog

# ── optional dependencies ────────────────────────────────────────────────────
def resource_path(relative_path: str) -> str:
    """Get absolute path to resource, works for dev and for PyInstaller bundle."""
    try:
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


try:
    from PIL import Image, ImageTk, ImageDraw, ImageFilter
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

try:
    from ReadWriteMemory import ReadWriteMemory
    RWM_AVAILABLE = True
except Exception:
    RWM_AVAILABLE = False

try:
    import pymem
    import pymem.process
    PYMEM_AVAILABLE = True
except Exception:
    PYMEM_AVAILABLE = False

try:
    import psutil
    PSUTIL_AVAILABLE = True
except Exception:
    PSUTIL_AVAILABLE = False

try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except Exception:
    KEYBOARD_AVAILABLE = False

# ── AI modules (optional — trainer works without them) ───────────────────────
try:
    from ai_controller import AIController, GameStateReader
    AI_AVAILABLE = True
except Exception:
    AI_AVAILABLE = False

# ═══════════════════════════════════════════════════════════════════════════════
# DESIGN SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════
class Theme:
    """Centralised colour palette and style constants."""

    # Base colours
    BG_DEEP       = "#0D0F14"   # outermost background
    BG_CARD       = "#141720"   # card/panel background
    BG_CARD_HOVER = "#1C2130"   # card hover state
    BG_INPUT      = "#0F111A"   # entry fields
    BG_TOPBAR     = "#0A0C10"   # top-bar strip

    ACCENT        = "#F5A623"   # golden accent (coins theme)
    ACCENT_DARK   = "#C87D0E"
    ACCENT2       = "#6C63FF"   # purple accent (diamonds theme)
    ACCENT2_DARK  = "#4E47CC"
    FUEL_COLOR    = "#2ECC71"   # green for fuel
    FUEL_ON       = "#27AE60"
    DANGER        = "#E74C3C"
    SUCCESS       = "#1ABC9C"

    TEXT_PRIMARY   = "#F0F2F5"
    TEXT_SECONDARY = "#8891A5"
    TEXT_MUTED     = "#4A5168"
    TEXT_ACCENT    = "#F5A623"

    BORDER        = "#252A38"
    BORDER_BRIGHT = "#3A4256"

    # Typography
    FONT_FAMILY   = "Segoe UI"
    FONT_TITLE    = ("Segoe UI", 22, "bold")
    FONT_SUBTITLE = ("Segoe UI", 11)
    FONT_LABEL    = ("Segoe UI", 10, "bold")
    FONT_BODY     = ("Segoe UI", 10)
    FONT_SMALL    = ("Segoe UI", 9)
    FONT_MONO     = ("Consolas", 9)
    FONT_BTN      = ("Segoe UI", 10, "bold")
    FONT_BADGE    = ("Segoe UI", 8, "bold")

    # Sizing
    CORNER_RADIUS = 8
    PAD_XL        = 20
    PAD_LG        = 14
    PAD_MD        = 10
    PAD_SM        = 6
    PAD_XS        = 3

    BTN_HEIGHT    = 32
    ENTRY_HEIGHT  = 32
    STATUS_HEIGHT = 28

    WIN_WIDTH     = 540
    WIN_HEIGHT    = 680


# ═══════════════════════════════════════════════════════════════════════════════
# GAME CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════
game: str = "HillClimbRacing.exe"
module: str = "cocos2d-win10.dll"

COINS_OFFSET          = 0x28CAD4
DIAMONDS_OFFSET       = 0x28CAEC
FUEL_BASE_OFFSET      = 0x0028CA2C
FUEL_OFFSETS: List[int]          = [0x2A8]
BOOST_BASE_OFFSET     = 0x00396244
BOOST_OFFSETS: List[int]         = [0x4, 0x14, 0x14, 0x8, 0x30,  0xF8, 0xE4]
BOOST_SECONDARY_OFFSETS: List[int] = [0x4, 0x14, 0x14, 0x8, 0x7C, 0xF8, 0xE4]
BOOST_THIRD_OFFSETS: List[int]   = [0x4, 0x14, 0x14, 0x8, 0x8C,  0xF8, 0xE4]

if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.abspath(".")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")


# ═══════════════════════════════════════════════════════════════════════════════
# MEMORY LAYER
# ═══════════════════════════════════════════════════════════════════════════════
def get_module_base_address(process_name: str, module_name: str) -> int:
    """Return the base address of *module_name* loaded inside *process_name*."""
    try:
        pm = pymem.Pymem(process_name)
        mod = pymem.process.module_from_name(pm.process_handle, module_name)
        return int(mod.lpBaseOfDll) if mod else 0
    except Exception:
        return 0


def get_base_address(process_name: str) -> int:
    """Return the main-module base address of *process_name*."""
    try:
        pm = pymem.Pymem(process_name)
        return int(pymem.process.module_from_name(pm.process_handle, process_name).lpBaseOfDll)
    except Exception:
        return 0


class MemHelper:
    """
    Thin wrapper around ReadWriteMemory + pymem for memory I/O.

    * Uses ReadWriteMemory for writing game process memory.
    * Uses pymem for reads and pointer traversal.
    * Falls back gracefully when one library is unavailable.
    """

    def __init__(self) -> None:
        self.rwm_proc: Optional[Any] = None
        self.pm: Optional[Any] = None
        self.pid: Optional[int] = None
        self.backend: Optional[str] = None

    # ── attach / detach ──────────────────────────────────────────────────────

    def attach_by_name(self, proc_name: str) -> None:
        """Find the process by name and attach."""
        if not PSUTIL_AVAILABLE:
            raise RuntimeError("psutil is required to find a process by name.")
        pid: Optional[int] = None
        for p in psutil.process_iter(["pid", "name"]):
            if p.info["name"] and p.info["name"].lower() == proc_name.lower():
                pid = p.info["pid"]
                break
        if pid is None:
            raise ProcessLookupError(f"Process '{proc_name}' not found.")
        self.attach_by_pid(pid)

    def attach_by_pid(self, pid: int) -> None:
        """Attach to a process by its PID."""
        self.detach()
        self.pid = pid

        if RWM_AVAILABLE:
            try:
                rwm = ReadWriteMemory()
                proc = rwm.get_process_by_id(pid)
                proc.open()
                self.rwm_proc = proc
                self.backend = "rwm"
            except Exception:
                self.rwm_proc = None

        if PYMEM_AVAILABLE:
            try:
                pm = pymem.Pymem()
                pm.open_process_from_id(pid)
                self.pm = pm
            except Exception:
                self.pm = None

        if not (self.rwm_proc or self.pm):
            raise RuntimeError(
                "Could not attach to process.\n"
                "Make sure ReadWriteMemory or pymem is installed and the app is "
                "running as Administrator."
            )

    def detach(self) -> None:
        """Release all handles."""
        try:
            if self.rwm_proc:
                try:
                    self.rwm_proc.close()
                except Exception:
                    pass
            if self.pm:
                try:
                    self.pm.close_process()
                except Exception:
                    pass
        finally:
            self.rwm_proc = None
            self.pm = None
            self.pid = None
            self.backend = None

    # ── reads ────────────────────────────────────────────────────────────────

    def read_int(self, addr: int) -> int:
        if not self.pm:
            raise RuntimeError("pymem is required for reads.")
        return int(self.pm.read_int(addr))

    def read_uint(self, addr: int) -> int:
        if not self.pm:
            raise RuntimeError("pymem is required for reads.")
        return int(self.pm.read_uint(addr))

    def read_float(self, addr: int) -> float:
        if not self.pm:
            raise RuntimeError("pymem is required for reads.")
        return float(self.pm.read_float(addr))

    # ── writes ───────────────────────────────────────────────────────────────

    def write_bytes(self, addr: int, data: bytes) -> None:
        if self.rwm_proc:
            try:
                if hasattr(self.rwm_proc, "writeBytes"):
                    self.rwm_proc.writeBytes(addr, list(data))
                    return
                if hasattr(self.rwm_proc, "writeByte"):
                    for i, byte in enumerate(data):
                        self.rwm_proc.writeByte(addr + i, [byte])
                    return
            except Exception:
                pass  # fall through to pymem
        if self.pm:
            self.pm.write_bytes(addr, data, len(data))
            return
        raise RuntimeError("No write backend available.")

    def write_int(self, addr: int, value: int) -> None:
        self.write_bytes(addr, int(value).to_bytes(4, "little", signed=True))

    def write_uint(self, addr: int, value: int) -> None:
        self.write_bytes(addr, int(value).to_bytes(4, "little", signed=False))

    def write_float(self, addr: int, value: float) -> None:
        """Write a float value as raw IEEE-754 bytes."""
        self.write_bytes(addr, struct.pack("<f", float(value)))

    # ── pointer resolver ─────────────────────────────────────────────────────

    def resolve_pointer(self, base: int, offsets: List[int], ptr_size: int = 4) -> int:
        """
        Walk a pointer chain starting at *base* applying *offsets*.

        Each step: read pointer at current address, then add next offset.
        """
        if not self.pm:
            raise RuntimeError("pymem is required for pointer resolution.")
        cur = int(base)
        if not offsets:
            return cur
        try:
            for off in offsets:
                raw = (
                    self.pm.read_longlong(cur)
                    if ptr_size == 8
                    else self.pm.read_int(cur)
                )
                cur = (raw if raw != 0 else cur) + off
            return cur
        except Exception:
            # Simpler fallback: treat each step as (cur + off)
            cur = int(base)
            for off in offsets:
                cur = self.pm.read_int(cur + off)
            return cur


# ═══════════════════════════════════════════════════════════════════════════════
# CONTROLLER (business logic, no UI)
# ═══════════════════════════════════════════════════════════════════════════════
class TrainerController:
    """Handles all game-memory operations; completely UI-agnostic."""

    def __init__(self) -> None:
        self.mem = MemHelper()
        self.base_address: int = 0
        self.module_base: int = 0

        # Fuel freeze state
        self._fuel_freeze_event = threading.Event()
        self._fuel_thread: Optional[threading.Thread] = None
        self.fuel_freezing: bool = False
        self.fuel_addr: int = 0

        # Registered keyboard hotkeys
        self.registered_hotkeys: List[Dict[str, Any]] = []

    # ── process attachment ───────────────────────────────────────────────────

    def attach(self) -> Tuple[int, int, int]:
        """
        Attach to the game process.

        Returns (pid, coins_value, diamonds_value).
        Raises on failure.
        """
        self.mem.attach_by_name(game)
        pid = self.mem.pid or 0

        if PYMEM_AVAILABLE:
            self.base_address = get_base_address(game)
            self.module_base = (
                get_module_base_address(game, module) if module else 0
            )

        coins_val = diamonds_val = 0
        try:
            coins_val = self.mem.read_uint(self._coins_addr())
        except Exception:
            pass
        try:
            diamonds_val = self.mem.read_uint(self._diamonds_addr())
        except Exception:
            pass

        return pid, coins_val, diamonds_val

    def detach(self) -> None:
        self.stop_fuel_freeze()
        self.mem.detach()

    # ── address helpers ──────────────────────────────────────────────────────

    def _coins_addr(self) -> int:
        if not self.base_address:
            raise RuntimeError("Base address unknown — process not attached.")
        return int(self.base_address) + COINS_OFFSET

    def _diamonds_addr(self) -> int:
        if not self.base_address:
            raise RuntimeError("Base address unknown — process not attached.")
        return int(self.base_address) + DIAMONDS_OFFSET

    def _fuel_base_addr(self) -> int:
        if not self.base_address:
            raise RuntimeError("Base address unknown — process not attached.")
        return int(self.base_address) + FUEL_BASE_OFFSET

    def _boost_base_addr(self) -> int:
        if not self.module_base:
            raise RuntimeError("Module base unknown — set the `module` variable.")
        return int(self.module_base) + BOOST_BASE_OFFSET

    # ── coins / diamonds ─────────────────────────────────────────────────────

    def _validated_uint(self, value: int) -> int:
        if not 0 <= value <= 0xFFFF_FFFF:
            raise ValueError(f"Value {value} is out of 32-bit unsigned range.")
        return value

    def set_coins(self, value: int) -> None:
        self.mem.write_uint(self._coins_addr(), self._validated_uint(value))

    def add_coins(self, amount: int) -> int:
        addr = self._coins_addr()
        try:
            current = self.mem.read_uint(addr)
        except Exception:
            current = 0
        new_val = min(current + amount, 0xFFFF_FFFF)
        self.mem.write_uint(addr, new_val)
        return new_val

    def set_diamonds(self, value: int) -> None:
        self.mem.write_uint(self._diamonds_addr(), self._validated_uint(value))

    def add_diamonds(self, amount: int) -> int:
        addr = self._diamonds_addr()
        try:
            current = self.mem.read_uint(addr)
        except Exception:
            current = 0
        new_val = min(current + amount, 0xFFFF_FFFF)
        self.mem.write_uint(addr, new_val)
        return new_val

    # ── fuel freeze ──────────────────────────────────────────────────────────

    def start_fuel_freeze(self, fuel_value: float) -> None:
        """Begin continuously writing *fuel_value* to the fuel address."""
        if self.fuel_freezing:
            return
        base = self._fuel_base_addr()
        try:
            self.fuel_addr = self.mem.resolve_pointer(base, FUEL_OFFSETS)
        except Exception:
            self.fuel_addr = base + (FUEL_OFFSETS[0] if FUEL_OFFSETS else 0)

        self._fuel_freeze_event.clear()
        self.fuel_freezing = True
        self._fuel_thread = threading.Thread(
            target=self._fuel_freeze_worker,
            args=(fuel_value,),
            daemon=True,
            name="FuelFreezeThread",
        )
        self._fuel_thread.start()

    def stop_fuel_freeze(self) -> None:
        """Stop the fuel freeze thread."""
        if not self.fuel_freezing:
            return
        self._fuel_freeze_event.set()
        self.fuel_freezing = False
        if self._fuel_thread:
            self._fuel_thread.join(timeout=0.5)
            self._fuel_thread = None

    def _fuel_freeze_worker(self, fuel_value: float) -> None:
        packed = struct.pack("<f", fuel_value)
        interval = 0.11
        while not self._fuel_freeze_event.is_set():
            try:
                self.mem.write_bytes(self.fuel_addr, packed)
            except Exception:
                pass
            time.sleep(interval)

    # ── boosts ───────────────────────────────────────────────────────────────

    def set_boosts(self, value: int) -> int:
        """Write boost count; returns the resolved pointer address."""
        if not 0 < value < 10_000:
            raise ValueError("Boost value must be between 1 and 9999.")
        base = self._boost_base_addr()
        resolved = self.mem.resolve_pointer(base, BOOST_OFFSETS)
        self.mem.write_int(resolved, value)
        return resolved

    def recalibrate_boosts(self) -> Optional[Tuple[int, int, List[int]]]:
        """
        Try alternate offset sets for the boost pointer.

        Returns (resolved_addr, current_value, used_offsets) on success,
        or raises if all sets fail.
        """
        base = self._boost_base_addr()
        for offsets in (BOOST_SECONDARY_OFFSETS, BOOST_THIRD_OFFSETS):
            try:
                resolved = self.mem.resolve_pointer(base, offsets)
                val = self.mem.read_int(resolved)
                return resolved, val, offsets
            except Exception:
                continue
        raise RuntimeError("Could not recalibrate with any alternate offset set.")

    # ── hotkeys ──────────────────────────────────────────────────────────────

    def clear_all_hotkeys(self) -> None:
        if KEYBOARD_AVAILABLE:
            try:
                keyboard.clear_all_hotkeys()
            except Exception:
                pass
        self.registered_hotkeys.clear()

    def remove_hotkey(self, hk: str) -> None:
        if KEYBOARD_AVAILABLE and hk:
            try:
                keyboard.remove_hotkey(hk)
            except Exception:
                pass
        self.registered_hotkeys = [h for h in self.registered_hotkeys if h["hotkey"] != hk]

    def add_hotkey(self, hk: str, callback: Any) -> None:
        if not KEYBOARD_AVAILABLE:
            raise RuntimeError("The 'keyboard' library is not installed.")
        keyboard.add_hotkey(hk, callback)
        self.registered_hotkeys.append({"hotkey": hk, "cb": callback})


# ═══════════════════════════════════════════════════════════════════════════════
# UI HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
class ToolTip:
    """Modern dark tooltip that follows the widget."""

    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self._tip: Optional[tk.Toplevel] = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _event: tk.Event | None = None) -> None:
        try:
            x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
            y = self.widget.winfo_rooty() - 30
        except Exception:
            return
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        self._tip.attributes("-topmost", True)
        tk.Label(
            self._tip,
            text=self.text,
            font=Theme.FONT_SMALL,
            bg="#1E2235",
            fg=Theme.TEXT_PRIMARY,
            relief="flat",
            bd=0,
            padx=8,
            pady=4,
        ).pack()

    def _hide(self, _event: tk.Event | None = None) -> None:
        if self._tip:
            self._tip.destroy()
            self._tip = None


def make_separator(parent: tk.Widget, color: str = Theme.BORDER) -> tk.Frame:
    """Return a 1-px horizontal separator."""
    sep = tk.Frame(parent, height=1, bg=color)
    sep.pack(fill="x", padx=Theme.PAD_MD, pady=Theme.PAD_SM)
    return sep


def apply_dark_titlebar(hwnd: int) -> None:
    """Enable Windows dark title-bar via undocumented DWM API (Win 10+)."""
    try:
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# STYLED WIDGET FACTORIES
# ═══════════════════════════════════════════════════════════════════════════════
def DarkButton(
    parent: tk.Widget,
    text: str,
    command: Any = None,
    color: str = Theme.ACCENT,
    width: int = 0,
    small: bool = False,
) -> tk.Button:
    """Return a styled flat button with hover animation."""
    font = Theme.FONT_SMALL if small else Theme.FONT_BTN
    btn = tk.Button(
        parent,
        text=text,
        command=command,
        font=font,
        bg=color,
        fg=Theme.BG_DEEP,
        activebackground=Theme.ACCENT_DARK if color == Theme.ACCENT else color,
        activeforeground=Theme.BG_DEEP,
        relief="flat",
        bd=0,
        cursor="hand2",
        padx=Theme.PAD_MD,
        pady=4 if small else 6,
    )
    if width:
        btn.config(width=width)

    hover_color = _darken(color, 0.85)
    btn.bind("<Enter>", lambda _: btn.config(bg=hover_color))
    btn.bind("<Leave>", lambda _: btn.config(bg=color))
    return btn


def _darken(hex_color: str, factor: float) -> str:
    """Return a slightly darkened version of a hex colour."""
    try:
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return "#{:02x}{:02x}{:02x}".format(
            int(r * factor), int(g * factor), int(b * factor)
        )
    except Exception:
        return hex_color


def DarkEntry(
    parent: tk.Widget,
    textvariable: tk.Variable,
    width: int = 14,
    center: bool = False,
) -> tk.Entry:
    """Return a styled dark entry widget."""
    e = tk.Entry(
        parent,
        textvariable=textvariable,
        font=Theme.FONT_BODY,
        bg=Theme.BG_INPUT,
        fg=Theme.TEXT_PRIMARY,
        insertbackground=Theme.ACCENT,
        relief="flat",
        bd=0,
        width=width,
        justify="center" if center else "left",
        highlightthickness=1,
        highlightbackground=Theme.BORDER,
        highlightcolor=Theme.ACCENT,
    )
    return e


def Card(parent: tk.Widget, **pack_kwargs: Any) -> tk.Frame:
    """Return a rounded-corner-ish card frame."""
    frm = tk.Frame(parent, bg=Theme.BG_CARD, bd=0)
    defaults = dict(fill="x", padx=Theme.PAD_MD, pady=Theme.PAD_XS)
    defaults.update(pack_kwargs)
    frm.pack(**defaults)

    # Subtle top highlight
    highlight = tk.Frame(frm, height=2, bg=Theme.BORDER_BRIGHT)
    highlight.pack(fill="x")
    return frm


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN UI
# ═══════════════════════════════════════════════════════════════════════════════
class TrainerApp:
    """
    Main application window.

    Owns all Tk widgets; delegates game-memory operations to TrainerController.
    """

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.ctrl = TrainerController()
        self._status_after_id: Optional[str] = None

        # AI controller (created if ai_controller.py is present)
        self._ai_ctrl: Optional[Any] = AIController() if AI_AVAILABLE else None
        self._ai_ui_poll_id: Optional[str] = None   # for after() polling

        self._setup_root()
        self._load_icons()

        # Tk variables
        self.coin_var    = tk.StringVar(value="0")
        self.diamond_var = tk.StringVar(value="0")
        self.fuel_var    = tk.StringVar(value="100.00")
        self.boost_var   = tk.StringVar(value="0")

        self._load_config()
        self._build_ui()

        # Apply dark title-bar after window is mapped
        self.root.after(50, self._apply_dark_titlebar)
        self.root.after(200, self._startup_attach)

    # ── window setup ─────────────────────────────────────────────────────────

    def _setup_root(self) -> None:
        self.root.title("Hill Climb Racing Trainer")
        self.root.configure(bg=Theme.BG_DEEP)
        self.root.geometry(f"{Theme.WIN_WIDTH}x{Theme.WIN_HEIGHT}")
        self.root.resizable(False, False)
        try:
            icon_path = resource_path("Icon/icon.ico")
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
        except Exception:
            pass

    def _apply_dark_titlebar(self) -> None:
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            if not hwnd:
                hwnd = self.root.winfo_id()
            apply_dark_titlebar(hwnd)
        except Exception:
            pass

    # ── icons ─────────────────────────────────────────────────────────────────

    def _load_icons(self) -> None:
        self._icon_info  = self._load_pil_icon(resource_path("Icon/info.ico"),  (18, 18))
        self._icon_boost = self._load_pil_icon(resource_path("Icon/boost.ico"), (48, 48))
        self._icon_app   = self._load_pil_icon(resource_path("Icon/icon2.ico"), (32, 32))

    @staticmethod
    def _load_pil_icon(path: str, size: Tuple[int, int]) -> Optional[Any]:
        if PIL_AVAILABLE and os.path.exists(path):
            try:
                im = Image.open(path).convert("RGBA").resize(size, Image.LANCZOS)
                return ImageTk.PhotoImage(im)
            except Exception:
                pass
        return None

    # ── config ───────────────────────────────────────────────────────────────

    def _load_config(self) -> None:
        try:
            cfg_to_read = CONFIG_PATH if os.path.exists(CONFIG_PATH) else resource_path("config.json")
            if os.path.exists(cfg_to_read):
                with open(cfg_to_read, "r") as fh:
                    data: Dict[str, Any] = json.load(fh)
                self.coin_var.set(data.get("coin", "0"))
                self.diamond_var.set(data.get("diamond", "0"))
                self.fuel_var.set(data.get("fuel", "100.00"))
                self.boost_var.set(data.get("boost", "0"))
                global game, module
                if data.get("game") and game is None:
                    game = data["game"]
                if data.get("module") and module is None:
                    module = data["module"]
        except Exception:
            pass

    def _save_config(
        self,
        hotkeys: Optional[Dict[str, Any]] = None,
        silent: bool = False,
    ) -> None:
        data: Dict[str, Any] = {
            "game": game,
            "module": module,
            "coin": self.coin_var.get(),
            "diamond": self.diamond_var.get(),
            "fuel": self.fuel_var.get(),
            "boost": self.boost_var.get(),
        }
        if hotkeys is not None:
            data["hotkeys"] = hotkeys
        try:
            with open(CONFIG_PATH, "w") as fh:
                json.dump(data, fh, indent=2)
            if not silent:
                self._set_status("✓  Profile saved.", color=Theme.SUCCESS)
        except Exception as e:
            messagebox.showerror("Save Error", str(e))

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # ── Top bar ──────────────────────────────────────────────────────────
        topbar = tk.Frame(self.root, bg=Theme.BG_TOPBAR, height=56)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        inner_top = tk.Frame(topbar, bg=Theme.BG_TOPBAR)
        inner_top.pack(fill="both", expand=True, padx=Theme.PAD_LG, pady=8)

        if self._icon_app:
            tk.Label(inner_top, image=self._icon_app, bg=Theme.BG_TOPBAR).pack(
                side="left", padx=(0, 10)
            )

        title_col = tk.Frame(inner_top, bg=Theme.BG_TOPBAR)
        title_col.pack(side="left", fill="y")
        tk.Label(
            title_col,
            text="Hill Climb Racing Trainer",
            font=Theme.FONT_TITLE,
            bg=Theme.BG_TOPBAR,
            fg=Theme.TEXT_PRIMARY,
        ).pack(anchor="w")
        tk.Label(
            title_col,
            text="Premium Edition  •  v2.0",
            font=Theme.FONT_SUBTITLE,
            bg=Theme.BG_TOPBAR,
            fg=Theme.TEXT_SECONDARY,
        ).pack(anchor="w")

        # ── Status bar ───────────────────────────────────────────────────────
        status_bar = tk.Frame(self.root, bg=Theme.BG_CARD, height=Theme.STATUS_HEIGHT)
        status_bar.pack(fill="x")
        status_bar.pack_propagate(False)

        self._status_dot = tk.Label(
            status_bar, text="●", font=("Segoe UI", 9), bg=Theme.BG_CARD, fg=Theme.DANGER
        )
        self._status_dot.pack(side="left", padx=(Theme.PAD_LG, 4), pady=5)

        self._status_label = tk.Label(
            status_bar,
            text="Initialising…",
            font=Theme.FONT_SMALL,
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_SECONDARY,
            anchor="w",
        )
        self._status_label.pack(side="left", fill="x", expand=True, pady=5)

        self._pid_label = tk.Label(
            status_bar,
            text="",
            font=Theme.FONT_MONO,
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_MUTED,
        )
        self._pid_label.pack(side="right", padx=Theme.PAD_LG)

        make_separator(self.root, color=Theme.BORDER)

        # ── Scrollable content area ──────────────────────────────────────────
        canvas = tk.Canvas(
            self.root, bg=Theme.BG_DEEP, highlightthickness=0, bd=0
        )
        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=canvas.yview)
        self._content = tk.Frame(canvas, bg=Theme.BG_DEEP)
        self._content.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self._content, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Mousewheel scroll
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        content = self._content

        # ── Section: Currency ────────────────────────────────────────────────
        self._section_header(content, "💰  Currency")

        self._coin_row    = self._currency_row(content, "Coins",    self.coin_var,    Theme.ACCENT,  "🪙")
        self._diamond_row = self._currency_row(content, "Diamonds", self.diamond_var, Theme.ACCENT2, "💎")

        # ── Section: Fuel ────────────────────────────────────────────────────
        self._section_header(content, "⛽  Fuel")
        self._build_fuel_card(content)

        # ── Section: Boosts ──────────────────────────────────────────────────
        self._section_header(content, "🚀  Boosts")
        self._build_boost_card(content)

        # ── Section: AI Auto-Pilot ───────────────────────────────────────────
        self._section_header(content, "🤖  AI Auto-Pilot (NEAT)")
        self._build_ai_card(content)

        # ── Bottom action bar ────────────────────────────────────────────────
        make_separator(content, color=Theme.BORDER)
        btn_bar = tk.Frame(content, bg=Theme.BG_DEEP)
        btn_bar.pack(fill="x", padx=Theme.PAD_MD, pady=(Theme.PAD_MD, Theme.PAD_LG))

        DarkButton(btn_bar, "⌨  Hotkeys & Save", command=self.open_hotkeys_window,
                   color=Theme.ACCENT2).pack(side="left", padx=(0, Theme.PAD_SM))
        DarkButton(btn_bar, "💾  Quick Save", command=self._save_config,
                   color="#2C3E50").pack(side="left", padx=Theme.PAD_SM)
        DarkButton(btn_bar, "🔄  Re-attach", command=self._startup_attach,
                   color="#2C3E50").pack(side="right")

    # ── section helpers ───────────────────────────────────────────────────────

    def _section_header(self, parent: tk.Widget, text: str) -> None:
        hdr = tk.Frame(parent, bg=Theme.BG_DEEP)
        hdr.pack(fill="x", padx=Theme.PAD_MD, pady=(Theme.PAD_MD, 2))
        tk.Label(
            hdr,
            text=text,
            font=Theme.FONT_LABEL,
            bg=Theme.BG_DEEP,
            fg=Theme.TEXT_SECONDARY,
        ).pack(side="left")

    def _currency_row(
        self,
        parent: tk.Widget,
        label: str,
        var: tk.StringVar,
        accent: str,
        emoji: str,
    ) -> tk.Frame:
        card = tk.Frame(parent, bg=Theme.BG_CARD, bd=0)
        card.pack(fill="x", padx=Theme.PAD_MD, pady=4)

        # left icon strip
        strip = tk.Frame(card, bg=accent, width=4)
        strip.pack(side="left", fill="y")

        inner = tk.Frame(card, bg=Theme.BG_CARD)
        inner.pack(side="left", fill="both", expand=True, padx=Theme.PAD_MD, pady=10)

        # row: label
        lbl_row = tk.Frame(inner, bg=Theme.BG_CARD)
        lbl_row.pack(fill="x")
        tk.Label(lbl_row, text=f"{emoji}  {label}", font=Theme.FONT_LABEL,
                 bg=Theme.BG_CARD, fg=accent).pack(side="left")

        # row: entry + buttons
        ctrl_row = tk.Frame(inner, bg=Theme.BG_CARD)
        ctrl_row.pack(fill="x", pady=(6, 0))

        entry = DarkEntry(ctrl_row, var, width=16)
        entry.pack(side="left")

        DarkButton(
            ctrl_row, "  Set  ",
            command=lambda lbl=label: self._set_currency(lbl),
            color=accent, small=True,
        ).pack(side="left", padx=(8, 4))
        DarkButton(
            ctrl_row, "+100 M",
            command=lambda lbl=label: self._add_100m(lbl),
            color="#2C3E50", small=True,
        ).pack(side="left", padx=4)
        DarkButton(
            ctrl_row, "Max",
            command=lambda lbl=label: self._set_max(lbl),
            color="#2C3E50", small=True,
        ).pack(side="left", padx=4)

        return card

    def _build_fuel_card(self, parent: tk.Widget) -> None:
        card = tk.Frame(parent, bg=Theme.BG_CARD, bd=0)
        card.pack(fill="x", padx=Theme.PAD_MD, pady=4)

        strip = tk.Frame(card, bg=Theme.FUEL_COLOR, width=4)
        strip.pack(side="left", fill="y")

        inner = tk.Frame(card, bg=Theme.BG_CARD)
        inner.pack(side="left", fill="both", expand=True, padx=Theme.PAD_MD, pady=10)

        lbl_row = tk.Frame(inner, bg=Theme.BG_CARD)
        lbl_row.pack(fill="x")
        tk.Label(lbl_row, text="⛽  Infinite Fuel", font=Theme.FONT_LABEL,
                 bg=Theme.BG_CARD, fg=Theme.FUEL_COLOR).pack(side="left")

        ctrl_row = tk.Frame(inner, bg=Theme.BG_CARD)
        ctrl_row.pack(fill="x", pady=(6, 0))

        tk.Label(ctrl_row, text="Value:", font=Theme.FONT_BODY,
                 bg=Theme.BG_CARD, fg=Theme.TEXT_SECONDARY).pack(side="left")
        DarkEntry(ctrl_row, self.fuel_var, width=10, center=True).pack(side="left", padx=8)

        self._fuel_btn = DarkButton(
            ctrl_row, "▶  Activate",
            command=self._toggle_fuel,
            color=Theme.FUEL_COLOR,
            small=True,
        )
        self._fuel_btn.pack(side="left", padx=4)

        note = tk.Label(
            inner,
            text="Writes the float value to memory every ~110 ms.",
            font=Theme.FONT_SMALL,
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_MUTED,
        )
        note.pack(anchor="w", pady=(4, 0))

    def _build_boost_card(self, parent: tk.Widget) -> None:
        card = tk.Frame(parent, bg=Theme.BG_CARD, bd=0)
        card.pack(fill="x", padx=Theme.PAD_MD, pady=4)

        strip = tk.Frame(card, bg=Theme.ACCENT, width=4)
        strip.pack(side="left", fill="y")

        inner = tk.Frame(card, bg=Theme.BG_CARD)
        inner.pack(side="left", fill="both", expand=True, padx=Theme.PAD_MD, pady=10)

        # Header row
        hdr_row = tk.Frame(inner, bg=Theme.BG_CARD)
        hdr_row.pack(fill="x")
        tk.Label(hdr_row, text="🚀  Boost Count", font=Theme.FONT_LABEL,
                 bg=Theme.BG_CARD, fg=Theme.ACCENT).pack(side="left")

        if self._icon_info:
            info_btn = tk.Label(
                hdr_row, image=self._icon_info,
                bg=Theme.BG_CARD, cursor="hand2",
            )
            info_btn.pack(side="right")
            info_btn.bind("<Button-1>", lambda _: self._show_boost_instructions())
            ToolTip(info_btn, "How to use Boosts — click for instructions")

        # Controls
        ctrl_row = tk.Frame(inner, bg=Theme.BG_CARD)
        ctrl_row.pack(fill="x", pady=(6, 0))

        DarkEntry(ctrl_row, self.boost_var, width=10, center=True).pack(side="left")

        DarkButton(ctrl_row, "  Set  ", command=self._set_boosts,
                   color=Theme.ACCENT, small=True).pack(side="left", padx=(8, 4))
        DarkButton(ctrl_row, "Recalibrate Pointer", command=self._recalibrate_boosts,
                   color="#2C3E50", small=True).pack(side="left", padx=4)

        note = tk.Label(
            inner,
            text="⚠  Open the boost buy popup in-game before clicking Set.",
            font=Theme.FONT_SMALL,
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_MUTED,
        )
        note.pack(anchor="w", pady=(4, 0))

    def _build_ai_card(self, parent: tk.Widget) -> None:
        card = tk.Frame(parent, bg=Theme.BG_CARD, bd=0)
        card.pack(fill="x", padx=Theme.PAD_MD, pady=4)

        strip = tk.Frame(card, bg=Theme.ACCENT2, width=4)
        strip.pack(side="left", fill="y")

        inner = tk.Frame(card, bg=Theme.BG_CARD)
        inner.pack(side="left", fill="both", expand=True, padx=Theme.PAD_MD, pady=10)

        # Header row
        hdr_row = tk.Frame(inner, bg=Theme.BG_CARD)
        hdr_row.pack(fill="x")
        tk.Label(hdr_row, text="🤖  AI Auto-Pilot (NEAT)", font=Theme.FONT_LABEL,
                 bg=Theme.BG_CARD, fg=Theme.ACCENT2).pack(side="left")

        self._ai_status_badge = tk.Label(
            hdr_row, text="OFFLINE", font=Theme.FONT_BADGE,
            bg="#252A38", fg=Theme.TEXT_SECONDARY, padx=6, pady=1
        )
        self._ai_status_badge.pack(side="right")

        # Stats bar
        stats_frame = tk.Frame(inner, bg=Theme.BG_INPUT, padx=8, pady=6)
        stats_frame.pack(fill="x", pady=(8, 6))

        self._ai_gen_lbl = tk.Label(stats_frame, text="Gen: 0", font=Theme.FONT_SMALL,
                                     bg=Theme.BG_INPUT, fg=Theme.TEXT_SECONDARY)
        self._ai_gen_lbl.pack(side="left", padx=(0, 10))

        self._ai_score_lbl = tk.Label(stats_frame, text="Score: 0", font=Theme.FONT_SMALL,
                                       bg=Theme.BG_INPUT, fg=Theme.ACCENT)
        self._ai_score_lbl.pack(side="left", padx=(0, 10))

        self._ai_best_lbl = tk.Label(stats_frame, text="Best: 0", font=Theme.FONT_SMALL,
                                      bg=Theme.BG_INPUT, fg=Theme.SUCCESS)
        self._ai_best_lbl.pack(side="left", padx=(0, 10))

        self._ai_gas_indicator = tk.Label(stats_frame, text="Gas ▶", font=Theme.FONT_BADGE,
                                          bg="#1C2130", fg=Theme.TEXT_MUTED, padx=4)
        self._ai_gas_indicator.pack(side="right", padx=2)

        self._ai_brake_indicator = tk.Label(stats_frame, text="◀ Brake", font=Theme.FONT_BADGE,
                                            bg="#1C2130", fg=Theme.TEXT_MUTED, padx=4)
        self._ai_brake_indicator.pack(side="right", padx=2)

        # Controls row
        ctrl_row = tk.Frame(inner, bg=Theme.BG_CARD)
        ctrl_row.pack(fill="x", pady=(2, 0))

        self._ai_run_btn = DarkButton(
            ctrl_row, "▶  Auto-Play",
            command=self._toggle_ai_autoplay,
            color=Theme.ACCENT2,
            small=True,
        )
        self._ai_run_btn.pack(side="left", padx=(0, 4))

        self._ai_train_btn = DarkButton(
            ctrl_row, "🧬  Train (50 Pop)",
            command=self._toggle_ai_training,
            color="#2C3E50",
            small=True,
        )
        self._ai_train_btn.pack(side="left", padx=4)

        DarkButton(
            ctrl_row, "💾  Save",
            command=self._save_ai_brain,
            color="#1C2130",
            small=True,
        ).pack(side="left", padx=4)

        DarkButton(
            ctrl_row, "📂  Load",
            command=self._load_ai_brain,
            color="#1C2130",
            small=True,
        ).pack(side="left", padx=4)

        note = tk.Label(
            inner,
            text="Autonomous neural driver using NEAT. Auto-controls Right/Left keys in real-time.",
            font=Theme.FONT_SMALL,
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_MUTED,
        )
        note.pack(anchor="w", pady=(6, 0))

    # ── AI Auto-Pilot actions ─────────────────────────────────────────────────

    def _toggle_ai_autoplay(self) -> None:
        if not AI_AVAILABLE or not self._ai_ctrl:
            messagebox.showinfo("AI Not Available", "ai_controller module could not be loaded.")
            return

        if self._ai_ctrl.running:
            self._ai_ctrl.stop()
            self._ai_run_btn.config(text="▶  Auto-Play", bg=Theme.ACCENT2)
            self._ai_train_btn.config(text="🧬  Train (50 Pop)", bg="#2C3E50")
            self._ai_status_badge.config(text="OFFLINE", fg=Theme.TEXT_SECONDARY, bg="#252A38")
            self._reset_ai_indicators()
            self._set_status("AI Auto-Play stopped.", color=Theme.TEXT_SECONDARY)
        else:
            if self.ctrl.mem.pm:
                self._ai_ctrl.state_reader = GameStateReader(
                    self.ctrl.mem.pm,
                    self.ctrl.base_address,
                    self.ctrl.module_base,
                )
            brain = None
            if os.path.exists("best_brain.json"):
                self._ai_ctrl.load_brain("best_brain.json")
                brain = self._ai_ctrl.brain

            self._ai_ctrl.start_manual(brain=brain)
            self._ai_run_btn.config(text="⏹  Stop AI", bg=Theme.DANGER)
            self._ai_status_badge.config(text="AUTO-PLAY", fg=Theme.SUCCESS, bg="#113322")
            self._set_status("AI Auto-Play active (driving car)...", color=Theme.SUCCESS)
            self._poll_ai_stats()

    def _toggle_ai_training(self) -> None:
        if not AI_AVAILABLE or not self._ai_ctrl:
            messagebox.showinfo("AI Not Available", "ai_controller module could not be loaded.")
            return

        if self._ai_ctrl.running:
            self._ai_ctrl.stop()
            self._ai_run_btn.config(text="▶  Auto-Play", bg=Theme.ACCENT2)
            self._ai_train_btn.config(text="🧬  Train (50 Pop)", bg="#2C3E50")
            self._ai_status_badge.config(text="OFFLINE", fg=Theme.TEXT_SECONDARY, bg="#252A38")
            self._reset_ai_indicators()
            self._set_status("AI Training stopped.", color=Theme.TEXT_SECONDARY)
        else:
            if self.ctrl.mem.pm:
                self._ai_ctrl.state_reader = GameStateReader(
                    self.ctrl.mem.pm,
                    self.ctrl.base_address,
                    self.ctrl.module_base,
                )
            self._ai_ctrl.start_training(pop_size=50)
            self._ai_train_btn.config(text="⏹  Stop Training", bg=Theme.DANGER)
            self._ai_status_badge.config(text="TRAINING", fg=Theme.ACCENT, bg="#332211")
            self._set_status("NEAT Evolution Training started...", color=Theme.ACCENT)
            self._poll_ai_stats()

    def _poll_ai_stats(self) -> None:
        if not self._ai_ctrl or not self._ai_ctrl.running:
            self._reset_ai_indicators()
            return

        try:
            gen = self._ai_ctrl.generation
            score = self._ai_ctrl.current_score
            best = self._ai_ctrl.best_score
            decision = self._ai_ctrl.last_decision

            self._ai_gen_lbl.config(text=f"Gen: {gen}")
            self._ai_score_lbl.config(text=f"Score: {int(score)}")
            self._ai_best_lbl.config(text=f"Best: {int(best)}")

            if len(decision) >= 2:
                gas_active = decision[0] > 0.5
                brake_active = decision[1] > 0.5
                self._ai_gas_indicator.config(
                    bg=Theme.FUEL_ON if gas_active else "#1C2130",
                    fg=Theme.TEXT_PRIMARY if gas_active else Theme.TEXT_MUTED,
                )
                self._ai_brake_indicator.config(
                    bg=Theme.DANGER if brake_active else "#1C2130",
                    fg=Theme.TEXT_PRIMARY if brake_active else Theme.TEXT_MUTED,
                )
        except Exception:
            pass

        self._ai_ui_poll_id = self.root.after(100, self._poll_ai_stats)

    def _reset_ai_indicators(self) -> None:
        if self._ai_ui_poll_id:
            try:
                self.root.after_cancel(self._ai_ui_poll_id)
            except Exception:
                pass
            self._ai_ui_poll_id = None
        if hasattr(self, "_ai_gas_indicator"):
            self._ai_gas_indicator.config(bg="#1C2130", fg=Theme.TEXT_MUTED)
            self._ai_brake_indicator.config(bg="#1C2130", fg=Theme.TEXT_MUTED)

    def _save_ai_brain(self) -> None:
        if not self._ai_ctrl:
            return
        path = "best_brain.json"
        try:
            self._ai_ctrl.save_brain(path)
            self._set_status(f"✓ AI Brain saved to {path}", color=Theme.SUCCESS)
        except Exception as e:
            messagebox.showerror("Save Brain", f"Error saving brain: {e}")

    def _load_ai_brain(self) -> None:
        if not self._ai_ctrl:
            return
        path = "best_brain.json"
        if not os.path.exists(path):
            messagebox.showinfo("Load Brain", f"No saved brain found at {path}")
            return
        try:
            success = self._ai_ctrl.load_brain(path)
            if success:
                self._set_status(f"✓ AI Brain loaded from {path}", color=Theme.SUCCESS)
            else:
                messagebox.showwarning("Load Brain", "Could not load brain file format.")
        except Exception as e:
            messagebox.showerror("Load Brain", f"Error loading brain: {e}")

    # ── status helpers ────────────────────────────────────────────────────────

    def _set_status(
        self,
        text: str,
        color: str = Theme.TEXT_SECONDARY,
        dot_color: Optional[str] = None,
    ) -> None:
        self._status_label.config(text=text, fg=color)
        if dot_color:
            self._status_dot.config(fg=dot_color)
        # Clear auto-dismiss timer
        if self._status_after_id:
            self.root.after_cancel(self._status_after_id)
        # Auto-revert to secondary after 4 s (unless it's a persistent status)
        if color not in (Theme.TEXT_SECONDARY, Theme.DANGER):
            self._status_after_id = self.root.after(
                4000,
                lambda: self._status_label.config(fg=Theme.TEXT_SECONDARY),
            )

    # ── startup attach ────────────────────────────────────────────────────────

    def _startup_attach(self) -> None:
        if not game:
            messagebox.showerror(
                "Game Not Set",
                "Please set the `game` variable inside the script before running.",
            )
            self.root.destroy()
            return

        self._set_status(f"Attaching to {game}…", color=Theme.TEXT_SECONDARY, dot_color=Theme.ACCENT)
        self.root.update_idletasks()

        try:
            pid, coins, diamonds = self.ctrl.attach()
            self.coin_var.set(str(coins))
            self.diamond_var.set(str(diamonds))
            self._status_dot.config(fg=Theme.SUCCESS)
            self._pid_label.config(text=f"PID {pid}")
            self._set_status(
                f"Attached  •  Coins: {coins:,}  •  Diamonds: {diamonds:,}",
                color=Theme.SUCCESS,
            )
            if self._ai_ctrl and AI_AVAILABLE and self.ctrl.mem.pm:
                self._ai_ctrl.state_reader = GameStateReader(
                    self.ctrl.mem.pm,
                    self.ctrl.base_address,
                    self.ctrl.module_base,
                )
        except Exception as exc:
            self._status_dot.config(fg=Theme.DANGER)
            self._pid_label.config(text="")
            self._set_status(str(exc), color=Theme.DANGER)
            messagebox.showerror(
                "Attach Failed",
                f"Could not attach to '{game}':\n{exc}\n\nTry running as Administrator.",
            )

    # ── currency actions ──────────────────────────────────────────────────────

    def _get_int_var(self, var: tk.StringVar, label: str) -> Optional[int]:
        try:
            return int(var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid Value", f"Enter a valid integer for {label}.")
            return None

    def _set_currency(self, label: str) -> None:
        if label == "Coins":
            val = self._get_int_var(self.coin_var, "Coins")
            if val is None:
                return
            try:
                self.ctrl.set_coins(val)
                self._set_status(f"🪙  Coins set to {val:,}", color=Theme.ACCENT)
            except Exception as e:
                messagebox.showerror("Error", str(e))
        else:
            val = self._get_int_var(self.diamond_var, "Diamonds")
            if val is None:
                return
            try:
                self.ctrl.set_diamonds(val)
                self._set_status(f"💎  Diamonds set to {val:,}", color=Theme.ACCENT2)
            except Exception as e:
                messagebox.showerror("Error", str(e))

    def _add_100m(self, label: str) -> None:
        try:
            if label == "Coins":
                new = self.ctrl.add_coins(100_000_000)
                self.coin_var.set(str(new))
                self._set_status(f"🪙  +100 M Coins  →  {new:,}", color=Theme.ACCENT)
            else:
                new = self.ctrl.add_diamonds(100_000_000)
                self.diamond_var.set(str(new))
                self._set_status(f"💎  +100 M Diamonds  →  {new:,}", color=Theme.ACCENT2)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _set_max(self, label: str) -> None:
        max_val = 0xFFFF_FFFF
        try:
            if label == "Coins":
                self.coin_var.set(str(max_val))
                self.ctrl.set_coins(max_val)
                self._set_status(f"🪙  Coins set to MAX ({max_val:,})", color=Theme.ACCENT)
            else:
                self.diamond_var.set(str(max_val))
                self.ctrl.set_diamonds(max_val)
                self._set_status(f"💎  Diamonds set to MAX ({max_val:,})", color=Theme.ACCENT2)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # ── fuel actions ──────────────────────────────────────────────────────────

    def _toggle_fuel(self) -> None:
        if not self.ctrl.fuel_freezing:
            try:
                val = float(self.fuel_var.get() or "100.0")
            except ValueError:
                messagebox.showerror("Invalid Value", "Enter a valid float for fuel.")
                return
            try:
                self.ctrl.start_fuel_freeze(val)
                self._fuel_btn.config(
                    text="⏹  Deactivate", bg=Theme.DANGER,
                    activebackground=_darken(Theme.DANGER, 0.85),
                )
                self._fuel_btn.bind("<Enter>", lambda _: self._fuel_btn.config(bg=_darken(Theme.DANGER, 0.85)))
                self._fuel_btn.bind("<Leave>", lambda _: self._fuel_btn.config(bg=Theme.DANGER))
                self._status_dot.config(fg=Theme.FUEL_COLOR)
                self._set_status("⛽  Infinite fuel ON", color=Theme.FUEL_COLOR)
            except Exception as e:
                messagebox.showerror("Fuel Error", str(e))
        else:
            self.ctrl.stop_fuel_freeze()
            self._fuel_btn.config(
                text="▶  Activate", bg=Theme.FUEL_COLOR,
                activebackground=_darken(Theme.FUEL_COLOR, 0.85),
            )
            self._fuel_btn.bind("<Enter>", lambda _: self._fuel_btn.config(bg=_darken(Theme.FUEL_COLOR, 0.85)))
            self._fuel_btn.bind("<Leave>", lambda _: self._fuel_btn.config(bg=Theme.FUEL_COLOR))
            self._status_dot.config(fg=Theme.SUCCESS)
            self._set_status("⛽  Infinite fuel OFF", color=Theme.TEXT_SECONDARY)

    # ── boost actions ─────────────────────────────────────────────────────────

    def _set_boosts(self) -> None:
        val = self._get_int_var(self.boost_var, "Boosts")
        if val is None:
            return
        ok = messagebox.askyesno(
            "Confirm",
            "Make sure you've opened the Boost buy popup in-game.\n\nProceed?",
        )
        if not ok:
            return
        try:
            addr = self.ctrl.set_boosts(val)
            self._set_status(f"🚀  Boosts set to {val}  @ {hex(addr)}", color=Theme.ACCENT)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _recalibrate_boosts(self) -> None:
        ok = messagebox.askyesno(
            "Recalibrate",
            "Is the boost pointer already working correctly?\n\n"
            "Yes = keep as-is    No = attempt recalibration",
        )
        if ok:
            self._set_status("Boost pointer left unchanged.", color=Theme.TEXT_SECONDARY)
            return
        try:
            addr, val, offsets = self.ctrl.recalibrate_boosts()
            self._set_status(
                f"✓  Recalibrated  @ {hex(addr)}  value={val}", color=Theme.SUCCESS
            )
            messagebox.showinfo(
                "Recalibration OK",
                f"Used offsets: {offsets}\nAddress: {hex(addr)}\nValue: {val}",
            )
        except Exception as e:
            messagebox.showerror("Recalibration Failed", str(e))

    # ── boost instructions popup ──────────────────────────────────────────────

    def _show_boost_instructions(self) -> None:
        top = tk.Toplevel(self.root)
        top.title("Boost Instructions")
        top.configure(bg=Theme.BG_CARD)
        top.resizable(False, False)
        top.transient(self.root)
        top.grab_set()

        # Icon
        if self._icon_boost:
            tk.Label(top, image=self._icon_boost, bg=Theme.BG_CARD).pack(pady=Theme.PAD_LG)

        tk.Label(
            top,
            text="How to Set Boosts",
            font=Theme.FONT_LABEL,
            bg=Theme.BG_CARD,
            fg=Theme.ACCENT,
        ).pack()

        msg = (
            "1. In-game, tap the boost icon to open the boost buy popup.\n\n"
            "2. Return to this trainer and type your desired boost count in the entry.\n\n"
            "3. Click  Set .\n\n"
            "4. Go back to the game and click the  –  icon to lower the displayed\n"
            "   count — this triggers the pointer to be written.\n\n"
            "5. Buy your boosts and enjoy!"
        )

        txt = tk.Text(
            top,
            wrap="word",
            height=10,
            width=48,
            font=Theme.FONT_BODY,
            bg=Theme.BG_INPUT,
            fg=Theme.TEXT_PRIMARY,
            relief="flat",
            bd=0,
            padx=12,
            pady=10,
            highlightthickness=0,
        )
        txt.insert("1.0", msg)
        txt.config(state="disabled")
        txt.pack(padx=Theme.PAD_LG, pady=Theme.PAD_MD)

        DarkButton(top, "  Got it!  ", command=top.destroy, color=Theme.ACCENT).pack(
            pady=Theme.PAD_LG
        )

    # ── hotkeys window ────────────────────────────────────────────────────────

    def hotkey_keypress(self, event: tk.Event, var: tk.StringVar) -> str:
        """Capture a keypress into *var* as a keyboard-library hotkey string."""
        if event.keysym in ("Control_L", "Control_R", "Shift_L", "Shift_R", "Alt_L", "Alt_R"):
            return "break"
        mods: List[str] = []
        if event.state & 4:
            mods.append("ctrl")
        if event.state & 1:
            mods.append("shift")
        if event.state & 8:
            mods.append("alt")
        key = event.keysym.lower()
        var.set("+".join(mods + [key]) if key else "+".join(mods))
        return "break"

    def open_hotkeys_window(self) -> None:
        wh = tk.Toplevel(self.root)
        wh.title("Hotkeys & Save Profile")
        wh.configure(bg=Theme.BG_DEEP)
        wh.resizable(False, False)
        wh.transient(self.root)
        wh.grab_set()

        tk.Label(
            wh,
            text="⌨  Hotkeys & Save Profile",
            font=Theme.FONT_TITLE,
            bg=Theme.BG_DEEP,
            fg=Theme.TEXT_PRIMARY,
        ).pack(pady=(Theme.PAD_LG, Theme.PAD_SM))
        tk.Label(
            wh,
            text="Click inside the hotkey field, then press your desired key combination.",
            font=Theme.FONT_SMALL,
            bg=Theme.BG_DEEP,
            fg=Theme.TEXT_SECONDARY,
        ).pack(pady=(0, Theme.PAD_MD))

        make_separator(wh)

        self.ctrl.registered_hotkeys.clear()

        def make_hotkey_row(
            parent: tk.Widget, label: str, emoji: str, accent: str
        ) -> Tuple[tk.StringVar, tk.StringVar, tk.StringVar, tk.BooleanVar]:
            card = tk.Frame(parent, bg=Theme.BG_CARD)
            card.pack(fill="x", padx=Theme.PAD_MD, pady=4)

            strip = tk.Frame(card, bg=accent, width=4)
            strip.pack(side="left", fill="y")

            inner = tk.Frame(card, bg=Theme.BG_CARD)
            inner.pack(side="left", fill="both", expand=True, padx=Theme.PAD_MD, pady=10)

            tk.Label(inner, text=f"{emoji}  {label}", font=Theme.FONT_LABEL,
                     bg=Theme.BG_CARD, fg=accent).pack(anchor="w")

            ctrl = tk.Frame(inner, bg=Theme.BG_CARD)
            ctrl.pack(fill="x", pady=(6, 0))

            # Mode
            mode_var = tk.StringVar(value="Set")
            mode_opt = ttk.Combobox(
                ctrl, textvariable=mode_var, values=["Set", "Increase"],
                state="readonly", width=9, font=Theme.FONT_BODY,
            )
            mode_opt.pack(side="left")

            # Amount
            val_var = tk.StringVar(value="100000")
            DarkEntry(ctrl, val_var, width=10, center=True).pack(side="left", padx=8)

            # Hotkey
            hk_var = tk.StringVar(value="")
            hk_entry = DarkEntry(ctrl, hk_var, width=14, center=True)
            hk_entry.pack(side="left", padx=4)
            hk_entry.bind("<KeyPress>", lambda e: self.hotkey_keypress(e, hk_var))
            ToolTip(hk_entry, "Click here, then press your desired key combo")

            act_var = tk.BooleanVar(value=False)
            prev_hk: List[str] = [hk_var.get()]

            def on_hk_change(*_: Any) -> None:
                if act_var.get() and hk_var.get() != prev_hk[0]:
                    self.ctrl.remove_hotkey(prev_hk[0])
                    act_var.set(False)

            hk_var.trace("w", on_hk_change)

            def toggle_active() -> None:
                new_hk = self._register_currency_hotkey(label, mode_var, val_var, hk_var, act_var, prev_hk[0])
                prev_hk[0] = new_hk

            act_check = tk.Checkbutton(
                ctrl, text="Active", variable=act_var, command=toggle_active,
                bg=Theme.BG_CARD, fg=Theme.TEXT_PRIMARY,
                selectcolor=Theme.BG_INPUT, activebackground=Theme.BG_CARD,
                font=Theme.FONT_BODY, cursor="hand2",
            )
            act_check.pack(side="left", padx=4)

            DarkButton(ctrl, "✕", command=lambda: [hk_var.set(""), act_var.set(False)],
                       color=Theme.BG_INPUT, small=True).pack(side="left", padx=2)

            return mode_var, val_var, hk_var, act_var

        coin_tuple  = make_hotkey_row(wh, "Coins",    "🪙", Theme.ACCENT)
        diam_tuple  = make_hotkey_row(wh, "Diamonds", "💎", Theme.ACCENT2)

        # Fuel toggle row
        fuel_card = tk.Frame(wh, bg=Theme.BG_CARD)
        fuel_card.pack(fill="x", padx=Theme.PAD_MD, pady=4)
        tk.Frame(fuel_card, bg=Theme.FUEL_COLOR, width=4).pack(side="left", fill="y")
        fuel_inner = tk.Frame(fuel_card, bg=Theme.BG_CARD)
        fuel_inner.pack(side="left", fill="both", expand=True, padx=Theme.PAD_MD, pady=10)
        tk.Label(fuel_inner, text="⛽  Fuel Toggle", font=Theme.FONT_LABEL,
                 bg=Theme.BG_CARD, fg=Theme.FUEL_COLOR).pack(anchor="w")
        fuel_ctrl = tk.Frame(fuel_inner, bg=Theme.BG_CARD)
        fuel_ctrl.pack(fill="x", pady=(6, 0))
        fhk_var  = tk.StringVar(value="")
        fhk_entry = DarkEntry(fuel_ctrl, fhk_var, width=14, center=True)
        fhk_entry.pack(side="left")
        fhk_entry.bind("<KeyPress>", lambda e: self.hotkey_keypress(e, fhk_var))
        ToolTip(fhk_entry, "Click here, then press your desired key combo")
        factive  = tk.BooleanVar(value=False)
        f_prev   = [fhk_var.get()]

        def f_on_hk_change(*_: Any) -> None:
            if factive.get() and fhk_var.get() != f_prev[0]:
                self.ctrl.remove_hotkey(f_prev[0])
                factive.set(False)

        fhk_var.trace("w", f_on_hk_change)

        def fuel_toggle_active() -> None:
            new_hk = self._register_fuel_hotkey(fhk_var, factive, f_prev[0])
            f_prev[0] = new_hk

        tk.Checkbutton(
            fuel_ctrl, text="Active", variable=factive, command=fuel_toggle_active,
            bg=Theme.BG_CARD, fg=Theme.TEXT_PRIMARY,
            selectcolor=Theme.BG_INPUT, activebackground=Theme.BG_CARD,
            font=Theme.FONT_BODY, cursor="hand2",
        ).pack(side="left", padx=4)
        DarkButton(fuel_ctrl, "✕", command=lambda: [fhk_var.set(""), factive.set(False)],
                   color=Theme.BG_INPUT, small=True).pack(side="left", padx=2)

        # Load existing config
        self._load_hotkey_config(coin_tuple, diam_tuple, fhk_var, factive)

        make_separator(wh)

        # Save button
        def save_all() -> None:
            mode_c, val_c, hk_c, act_c = coin_tuple
            mode_d, val_d, hk_d, act_d = diam_tuple
            hotkeys = {
                "coins": {
                    "mode": mode_c.get(), "value": val_c.get(),
                    "hotkey": hk_c.get(), "active": act_c.get(),
                },
                "diamonds": {
                    "mode": mode_d.get(), "value": val_d.get(),
                    "hotkey": hk_d.get(), "active": act_d.get(),
                },
                "fuel": {
                    "hotkey": fhk_var.get(), "active": factive.get(),
                },
            }
            self._save_config(hotkeys=hotkeys)

        btn_bar = tk.Frame(wh, bg=Theme.BG_DEEP)
        btn_bar.pack(fill="x", padx=Theme.PAD_MD, pady=Theme.PAD_LG)
        DarkButton(btn_bar, "💾  Save Profile", command=save_all, color=Theme.ACCENT).pack(side="left")
        DarkButton(btn_bar, "✕  Close", command=wh.destroy, color="#2C3E50").pack(side="right")

    def _load_hotkey_config(
        self,
        coin_tuple: tuple,
        diam_tuple: tuple,
        fhk_var: tk.StringVar,
        factive: tk.BooleanVar,
    ) -> None:
        try:
            if not os.path.exists(CONFIG_PATH):
                return
            with open(CONFIG_PATH, "r") as fh:
                data: Dict[str, Any] = json.load(fh)
            h = data.get("hotkeys", {})

            def apply(section_name: str, row_tuple: tuple) -> None:
                s = h.get(section_name, {})
                mode_v, val_v, hk_v, act_v = row_tuple
                mode_v.set(s.get("mode", "Set"))
                val_v.set(s.get("value", "100000"))
                hk_v.set(s.get("hotkey", ""))
                active = s.get("active", False)
                act_v.set(active)
                if active:
                    self._register_currency_hotkey(
                        section_name.title(), mode_v, val_v, hk_v, act_v, hk_v.get()
                    )

            apply("coins", coin_tuple)
            apply("diamonds", diam_tuple)

            fs = h.get("fuel", {})
            fhk_var.set(fs.get("hotkey", ""))
            factive.set(fs.get("active", False))
            if fs.get("active"):
                self._register_fuel_hotkey(fhk_var, factive, fhk_var.get())
        except Exception:
            pass

    def _register_currency_hotkey(
        self,
        label: str,
        mode_var: tk.StringVar,
        val_var: tk.StringVar,
        hk_var: tk.StringVar,
        act_var: tk.BooleanVar,
        previous_hk: str,
    ) -> str:
        if not act_var.get():
            self.ctrl.remove_hotkey(previous_hk)
            return previous_hk

        hk = hk_var.get().strip()
        if not hk:
            messagebox.showerror("Hotkey", "Please enter a hotkey first.")
            act_var.set(False)
            return previous_hk
        try:
            intval = int(val_var.get())
        except ValueError:
            messagebox.showerror("Value", "Hotkey value must be an integer.")
            act_var.set(False)
            return previous_hk

        def cb() -> None:
            is_coins = label.lower().startswith("coin")
            addr_fn = self.ctrl._coins_addr if is_coins else self.ctrl._diamonds_addr
            try:
                addr = addr_fn()
            except Exception:
                return
            if mode_var.get() == "Set":
                self.root.after(10, lambda: self._safe_write_uint(addr, intval))
            else:
                def inc() -> None:
                    try:
                        cur = self.ctrl.mem.read_uint(addr)
                    except Exception:
                        cur = 0
                    self._safe_write_uint(addr, min(cur + intval, 0xFFFF_FFFF))
                self.root.after(10, inc)

        try:
            self.ctrl.add_hotkey(hk, cb)
            self._set_status(f"Hotkey  {hk}  registered for {label}", color=Theme.SUCCESS)
            return hk
        except Exception as e:
            messagebox.showerror("Hotkey Error", str(e))
            act_var.set(False)
            return previous_hk

    def _register_fuel_hotkey(
        self,
        hk_var: tk.StringVar,
        act_var: tk.BooleanVar,
        previous_hk: str,
    ) -> str:
        if not act_var.get():
            self.ctrl.remove_hotkey(previous_hk)
            return previous_hk

        hk = hk_var.get().strip()
        if not hk:
            messagebox.showerror("Hotkey", "Please enter a hotkey for fuel toggle.")
            act_var.set(False)
            return previous_hk

        def fuel_cb() -> None:
            self.root.after(10, self._toggle_fuel)

        try:
            self.ctrl.add_hotkey(hk, fuel_cb)
            self._set_status(f"Fuel toggle hotkey  {hk}  registered", color=Theme.SUCCESS)
            return hk
        except Exception as e:
            messagebox.showerror("Hotkey Error", str(e))
            act_var.set(False)
            return previous_hk

    def _safe_write_uint(self, addr: int, value: int) -> None:
        try:
            self.ctrl.mem.write_uint(addr, value)
        except Exception as e:
            self._set_status(f"Write error: {e}", color=Theme.DANGER)

    # ── cleanup ───────────────────────────────────────────────────────────────

    def cleanup_and_exit(self) -> None:
        self._save_config(silent=True)
        if self._ai_ctrl:
            try:
                self._ai_ctrl.stop()
            except Exception:
                pass
        try:
            self.ctrl.detach()
        except Exception:
            pass
        try:
            self.ctrl.clear_all_hotkeys()
        except Exception:
            pass
        self.root.destroy()


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════
def main() -> None:
    root = tk.Tk()
    app = TrainerApp(root)
    root.protocol("WM_DELETE_WINDOW", app.cleanup_and_exit)

    # Style ttk widgets globally
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure(
        "TCombobox",
        fieldbackground=Theme.BG_INPUT,
        background=Theme.BG_CARD,
        foreground=Theme.TEXT_PRIMARY,
        selectbackground=Theme.ACCENT,
        selectforeground=Theme.BG_DEEP,
        arrowcolor=Theme.TEXT_SECONDARY,
        bordercolor=Theme.BORDER,
        lightcolor=Theme.BORDER,
        darkcolor=Theme.BORDER,
    )
    style.map("TCombobox", fieldbackground=[("readonly", Theme.BG_INPUT)])
    style.configure("Vertical.TScrollbar",
                    background=Theme.BG_CARD,
                    troughcolor=Theme.BG_DEEP,
                    arrowcolor=Theme.TEXT_MUTED,
                    bordercolor=Theme.BG_DEEP)

    root.mainloop()


if __name__ == "__main__":
    main()