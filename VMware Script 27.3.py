import asyncio
import traceback
import signal as _signal_module
import threading as _threading_module

# pytchat fix: signal.signal() only works on the main thread.
# Patch it to be a no-op when called from a worker thread.
_orig_signal = _signal_module.signal
def _safe_signal(sig, handler):
    if _threading_module.current_thread() is _threading_module.main_thread():
        return _orig_signal(sig, handler)
_signal_module.signal = _safe_signal

import time
import subprocess
import os
import json
import threading
import http.server
import socketserver
import sys
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from datetime import datetime
from collections import defaultdict

# ========================= OPTIONAL DEPENDENCIES =========================
# These third-party libraries are optional. If any of them are missing,
# the script will still start, but the features that depend on them
# will be disabled and a message will explain what to install.
MISSING_LIBRARIES = []  # list of (import_name, pip_name, description)

try:
    import pytchat
    HAS_PYTCHAT = True
except ImportError:
    pytchat = None
    HAS_PYTCHAT = False
    MISSING_LIBRARIES.append((
        "pytchat",
        "pytchat",
        "Reads YouTube Live Chat messages. Required for the bot to react to chat commands."
    ))

try:
    from vncdotool import api as vnc
    HAS_VNCDOTOOL = True
except ImportError:
    vnc = None
    HAS_VNCDOTOOL = False
    MISSING_LIBRARIES.append((
        "vncdotool",
        "vncdotool",
        "Connects to the VM over VNC to send keyboard and mouse input. Required for all VM control commands (typing, clicking, moving the mouse, etc)."
    ))


def print_missing_libraries_report():
    """Prints a clear report of any missing optional libraries and what they do."""
    if not MISSING_LIBRARIES:
        print("[Startup] All optional libraries are installed. All features are available.")
        return
    print("=" * 70)
    print("[Startup] Some optional libraries are missing.")
    print("The script will still run, but related features will be disabled.")
    print("=" * 70)
    for import_name, pip_name, description in MISSING_LIBRARIES:
        print(f"  - Missing: {import_name}")
        print(f"      Install with: pip install {pip_name}")
        print(f"      Used for: {description}")
    print("=" * 70)

# ========================= CUSTOM COMMANDS =========================
CUSTOM_COMMANDS_FILE = "custom_commands.json"
custom_commands: dict = {}

def load_custom_commands():
    global custom_commands
    try:
        if os.path.exists(CUSTOM_COMMANDS_FILE):
            with open(CUSTOM_COMMANDS_FILE, "r", encoding="utf-8") as f:
                custom_commands = json.load(f)
            print(f"[CustomCmd] {len(custom_commands)} custom command(s) loaded.")
    except Exception as e:
        print(f"[CustomCmd] Load error: {e}")
        custom_commands = {}

def save_custom_commands():
    try:
        with open(CUSTOM_COMMANDS_FILE, "w", encoding="utf-8") as f:
            json.dump(custom_commands, f, indent=2, ensure_ascii=False)
        print(f"[CustomCmd] Saved {len(custom_commands)} command(s).")
    except Exception as e:
        print(f"[CustomCmd] Save error: {e}")

async def execute_custom_command_async(trigger: str):
    steps = custom_commands.get(trigger, [])
    print(f"[CustomCmd] Executing '{trigger}' ({len(steps)} steps)")
    for step in steps:
        action   = step.get("action", "").lower().strip()
        args_str = step.get("args", "").strip()
        try:
            if action == "combo":
                key = "+".join(args_str.replace("+", " ").split())
                await controller.send_key(key)
            elif action in ("send", "typeenter", "sendline"):
                await controller.type_text(args_str)
                await asyncio.sleep(0.05)
                await controller.send_key("enter")
            elif action in ("type", "text", "say"):
                await controller.type_text(args_str)
            elif action in ("key", "press"):
                await controller.send_key(args_str)
            elif action in ("wait", "pause", "delay"):
                try:
                    await asyncio.sleep(min(float(args_str) / 1000.0, 5.0))
                except ValueError:
                    await asyncio.sleep(0.5)
            elif action in ("click", "lclick"):
                client = await controller.connect_fresh()
                if client:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, lambda: client.mousePress(1))
            elif action in ("rclick", "rightclick"):
                client = await controller.connect_fresh()
                if client:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, lambda: client.mousePress(3))
            elif action in ("move", "mv"):
                parts = args_str.split()
                if len(parts) >= 2:
                    client = await controller.connect_fresh()
                    if client:
                        dx = int(parts[0]); dy = int(parts[1])
                        controller.cursor_x = max(0, min(1920, controller.cursor_x + dx))
                        controller.cursor_y = max(0, min(1080, controller.cursor_y + dy))
                        loop = asyncio.get_running_loop()
                        await loop.run_in_executor(None,
                            lambda: client.mouseMove(controller.cursor_x, controller.cursor_y))
            elif action in ("abs", "moveabs"):
                parts = args_str.split()
                if len(parts) >= 2:
                    client = await controller.connect_fresh()
                    if client:
                        controller.cursor_x = max(0, min(1920, int(parts[0])))
                        controller.cursor_y = max(0, min(1080, int(parts[1])))
                        loop = asyncio.get_running_loop()
                        await loop.run_in_executor(None,
                            lambda: client.mouseMove(controller.cursor_x, controller.cursor_y))
            elif action in ("scroll", "wheel"):
                try:
                    delta  = int(args_str)
                    button = 4 if delta > 0 else 5
                    client = await controller.connect_fresh()
                    if client:
                        loop = asyncio.get_running_loop()
                        for _ in range(abs(delta)):
                            await loop.run_in_executor(None, lambda b=button: client.mousePress(b))
                            await asyncio.sleep(0.01)
                except ValueError:
                    pass
            print(f"[CustomCmd]   -> {action} {args_str}")
        except Exception as e:
            print(f"[CustomCmd] Step error ({action} {args_str}): {e}")

# ========================= CONFIG =========================
VM_DATABASE_FILE = "vms.json"
vm_list = {}
VNC_HOST = "localhost"
VNC_PORT = 5900
VNC_PASSWORD = "1234"
YOUTUBE_VIDEO_ID = None
VMX_PATH = None
PREFIX = "!"
def get_vmrun_path():
    """Looks for vmrun.exe in both the 64-bit and 32-bit Program Files
    locations, since the install path varies from system to system."""
    possible_paths = [
        r"C:\Program Files\VMware\VMware Workstation\vmrun.exe",
        r"C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe",
        r"D:\Program Files\VMware\VMware Workstation\vmrun.exe",
        r"D:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe",
    ]
    for path in possible_paths:
        if os.path.exists(path):
            return path
    # Fall back to the most common location so error messages still show
    # a sensible path even when vmrun.exe cannot be found anywhere.
    return possible_paths[0]

VMRUN_PATH = get_vmrun_path()
COOLDOWN = {"startvm": 45}

# Single source of truth for vote settings.
# FIX: Removed the dead VOTE_SETTINGS dict that was never read by any logic.
VOTE_DURATION   = 100  # Seconds the voting window stays open
REQUIRED_VOTES  = 2    # Minimum unique voters required to pass

# VM_DATABASE example entries (edit vms.json directly or use registration mode):
#   "win10": r"D:\VMSVMWARE\w8\Windows 10 x64.vmx"
#   "win8":  r"D:\VMSVMWARE\w88\Windows 8.x x64.vmx"
#   "win7":  r"D:\w777\Windows 7 x64.vmx"

active_voters   = defaultdict(lambda: 0)
votes           = {"restartvm": [], "revert": []}
last_command_time = {}

# Guard set that prevents the same vote action from being executed twice
# concurrently (race condition between start_vote and process_command).
# FIX: Added to resolve the double-execution race condition.
_executing_votes: set = set()

# ========================= SCANCODE MAP =========================
# Direct X11 keysym codes to bypass bugs in the vncdotool library.
SCANCODE_MAP = {
    "esc": chr(0xff1b), "escape": chr(0xff1b),
    "tab": chr(0xff09),
    "enter": chr(0xff0d), "return": chr(0xff0d),
    "space": " ",
    "backspace": chr(0xff08),
    "delete": chr(0xffff), "del": chr(0xffff),
    "insert": chr(0xff63), "ins": chr(0xff63),
    "home": chr(0xff50),
    "end": chr(0xff57),
    "pageup": chr(0xff55), "pgup": chr(0xff55),
    "pagedown": chr(0xff56), "pgdn": chr(0xff56),
    "ctrl": chr(0xffe3), "control": chr(0xffe3),
    "alt": chr(0xffe9),
    "shift": chr(0xffe1),
    "capslock": chr(0xffe5),
    "win": chr(0xffeb), "super": chr(0xffeb), "windows": chr(0xffeb),
    "up": chr(0xff52),
    "down": chr(0xff54),
    "left": chr(0xff51),
    "right": chr(0xff53),
    "f1": chr(0xffbe), "f2": chr(0xffbf), "f3": chr(0xffc0), "f4": chr(0xffc1),
    "f5": chr(0xffc2), "f6": chr(0xffc3), "f7": chr(0xffc4), "f8": chr(0xffc5),
    "f9": chr(0xffc6), "f10": chr(0xffc7), "f11": chr(0xffc8), "f12": chr(0xffc9),
}

# ========================= OVERLAY SYSTEM =========================
overlay_data    = {"chat": [], "running_command": ""}
seen_message_ids = set()
last_write_time = 0
_overlay_lock   = threading.Lock()


def update_overlay(author=None, message=None, running=None, msg_id=None):
    global last_write_time
    current_time = time.time()

    with _overlay_lock:
        changed = False

        if running is not None and overlay_data.get("running_command") != running:
            overlay_data["running_command"] = running
            changed = True

        if author and message and msg_id and msg_id not in seen_message_ids:
            seen_message_ids.add(msg_id)
            overlay_data["chat"].append({
                "author":  str(author),
                "message": str(message),
                "id":      str(msg_id),
            })

            if len(overlay_data["chat"]) > 20:
                removed = overlay_data["chat"].pop(0)
                seen_message_ids.discard(removed.get("id"))

            changed = True

        if changed and (current_time - last_write_time > 0.15):
            try:
                with open("overlay.json", "w", encoding="utf-8") as f:
                    json.dump(overlay_data, f, ensure_ascii=False, separators=(",", ":"))
                last_write_time = current_time
            except Exception as e:
                print(f"[Overlay Error] {e}")


async def show_running_command(cmd_text: str):
    update_overlay(running=cmd_text)
    await asyncio.sleep(2)
    if overlay_data["running_command"] == cmd_text:
        update_overlay(running="")


def start_overlay_server():
    PORT = 8080

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # Suppress request logs

    try:
        with socketserver.TCPServer(("", PORT), QuietHandler) as httpd:
            print(f"Overlay server running at: http://localhost:{PORT}/chat.html")
            httpd.serve_forever()
    except OSError:
        print("Port 8080 is busy. Overlay server could not start.")


# ========================= SPEAKER =========================
def speak_text(text: str):
    print(f"\n[SPEAKER]: {text}\n")


# ========================= VM CONTROLLER =========================
class VMController:
    def __init__(self):
        self.client   = None
        self.cursor_x = 512
        self.cursor_y = 384
        # Prevents concurrent VNC operations (avoids stuck keys).
        self._lock        = asyncio.Lock()
        # Emergency signal that tells an active hold loop to stop early.
        self._abort_hold  = False

    async def connect_fresh(self):
        await self._disconnect()
        if not HAS_VNCDOTOOL:
            print("VNC connect failed: vncdotool is not installed.")
            self.client = None
            return None
        try:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] New VNC connection...")
            loop = asyncio.get_running_loop()
            self.client = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: vnc.connect(f"{VNC_HOST}::{VNC_PORT}", password=str(VNC_PASSWORD)),
                ),
                timeout=8,
            )
            # Always clear any stuck modifier keys on every fresh connection.
            # Root cause of the "keyboard locks up" bug: if a previous keyDown
            # (from !hold, !combo, or type_text) was never followed by a successful
            # keyUp (due to a timeout / exception / dropped connection), the VNC
            # server keeps that key marked as "pressed" at the OS level.  Because
            # VNC keyboard events are injected as real OS input, even physical
            # keystrokes on the VMware window are then interpreted with that phantom
            # modifier held — making all input appear broken.  Sending keyUp for
            # every modifier on each new connection guarantees a clean slate before
            # every operation.
            await self._clear_stuck_modifiers(self.client)
            print("Fresh VNC connected.")
            return self.client
        except Exception as e:
            print(f"VNC connect failed: {e}")
            self.client = None
            return None

    async def _clear_stuck_modifiers(self, client):
        """Send keyUp for every modifier key to clear any stuck VNC keyboard state."""
        loop = asyncio.get_running_loop()
        modifier_names = [
            "shift", "ctrl", "alt", "win", "capslock",
        ]
        released: set = set()
        for name in modifier_names:
            mapped = SCANCODE_MAP.get(name)
            if mapped and mapped not in released:
                released.add(mapped)
                try:
                    await asyncio.wait_for(
                        loop.run_in_executor(None, lambda mk=mapped: client.keyUp(mk)),
                        timeout=0.5,
                    )
                except Exception:
                    pass

    async def _disconnect(self):
        if self.client:
            try:
                self.client.disconnect()
            except Exception:
                pass
        self.client = None

    async def send_key(self, key: str):
        # Lock the entire operation so no other command can call connect_fresh()
        # mid-execution and disconnect the client (which was causing stuck keys).
        async with self._lock:
            client = await self.connect_fresh()
            if not client:
                return False
            try:
                loop      = asyncio.get_running_loop()
                clean_key = key.strip().lower()
                mapped_key = SCANCODE_MAP.get(clean_key, clean_key)

                if "+" in clean_key:
                    # Combo keys, e.g. ctrl+c, win+r
                    keys       = clean_key.split("+")
                    mapped_keys = [
                        SCANCODE_MAP.get(k.strip(), k.strip()) for k in keys
                    ]
                    try:
                        for k in mapped_keys:
                            await asyncio.wait_for(
                                loop.run_in_executor(None, lambda k2=k: client.keyDown(k2)),
                                timeout=2.0,
                            )
                            await asyncio.sleep(0.01)
                    finally:
                        # Always release all keys, even if keyDown raised an error midway.
                        for k in reversed(mapped_keys):
                            try:
                                await asyncio.wait_for(
                                    loop.run_in_executor(None, lambda k2=k: client.keyUp(k2)),
                                    timeout=2.0,
                                )
                            except Exception:
                                pass
                    print(f"Combo sent: {'+'.join(mapped_keys)}")

                else:
                    # Single key: press and release atomically in the same thread.
                    def do_safe_press():
                        try:
                            client.keyDown(mapped_key)
                            time.sleep(0.1)
                        finally:
                            client.keyUp(mapped_key)

                    await asyncio.wait_for(
                        loop.run_in_executor(None, do_safe_press), timeout=10.0
                    )
                    print(f"Key sent and released: {mapped_key}")

                return True

            except Exception as e:
                print(f"Key send error: {e}")
                traceback.print_exc()
                # FIX: Was missing 'return False' here; the function returned None on error.
                return False

    async def type_text(self, text: str):
        # Same lock as send_key — prevents connection being torn down mid-typing.
        async with self._lock:
            client = await self.connect_fresh()
            if not client:
                return False
            try:
                loop = asyncio.get_running_loop()
                for char in text:
                    if char.isupper() or char in '!@#$%^&*()_+{}|:"<>?~':
                        # Hold Shift for uppercase / special characters.
                        try:
                            await asyncio.wait_for(
                                loop.run_in_executor(
                                    None, lambda: client.keyDown(SCANCODE_MAP["shift"])
                                ),
                                timeout=2.0,
                            )
                            key_to_send = char.lower() if char.isupper() else char
                            await asyncio.wait_for(
                                loop.run_in_executor(
                                    None, lambda k=key_to_send: client.keyPress(k)
                                ),
                                timeout=2.0,
                            )
                        finally:
                            try:
                                await asyncio.wait_for(
                                    loop.run_in_executor(
                                        None, lambda: client.keyUp(SCANCODE_MAP["shift"])
                                    ),
                                    timeout=2.0,
                                )
                            except Exception:
                                pass
                    else:
                        await asyncio.wait_for(
                            loop.run_in_executor(None, lambda c=char: client.keyPress(c)),
                            timeout=2.0,
                        )
                    await asyncio.sleep(0.007)

                print(f"Text sent: {text}")
                return True

            except Exception:
                # Clear all modifier keys, not just Shift, in case another
                # modifier was involved (e.g. a future code path adds Ctrl typing).
                await self._clear_stuck_modifiers(client)
                await self._disconnect()
                return False


controller = VMController()


# ========================= VOTE HELPERS =========================
def update_vote_json(restart_time: int = 0, revert_time: int = 0):
    data = {
        "restartvm": {
            "current":        len(votes["restartvm"]),
            "required":       REQUIRED_VOTES,
            "remaining_time": restart_time,
        },
        "revert": {
            "current":        len(votes["revert"]),
            "required":       REQUIRED_VOTES,
            "remaining_time": revert_time,
        },
    }
    try:
        with open("votes.json", "w") as f:
            json.dump(data, f)
    except Exception:
        pass


async def execute_vm_action(vote_type: str):
    # FIX: Guard against double execution. If start_vote and process_command both
    # trigger this for the same vote_type at the same time, only the first one runs.
    if vote_type in _executing_votes:
        return
    _executing_votes.add(vote_type)
    try:
        votes[vote_type] = []
        update_vote_json()

        if vote_type == "restartvm":
            await run_vmrun(["-T", "ws", "reset", VMX_PATH, "hard"])
        elif vote_type == "revert":
            await run_vmrun(["-T", "ws", "revertToSnapshot", VMX_PATH, "snp"])
            await asyncio.sleep(5)
            await run_vmrun(["-T", "ws", "start", VMX_PATH, "gui"])
    finally:
        _executing_votes.discard(vote_type)


async def start_vote(vote_type: str, starter: str):
    votes[vote_type] = [starter]
    print(f"Vote started for !{vote_type} by {starter}")

    if vote_type == "restartvm":
        update_vote_json(restart_time=VOTE_DURATION)
    else:
        update_vote_json(revert_time=VOTE_DURATION)

    for remaining in range(VOTE_DURATION, 0, -1):
        await asyncio.sleep(1)
        if vote_type == "restartvm":
            update_vote_json(restart_time=remaining)
        else:
            update_vote_json(revert_time=remaining)

        if len(votes[vote_type]) >= REQUIRED_VOTES:
            print(f"Vote PASSED early for !{vote_type}")
            await execute_vm_action(vote_type)
            return

    votes[vote_type] = []
    update_vote_json()
    print(f"Vote for !{vote_type} expired without reaching required votes.")


# ========================= STDOUT REDIRECT =========================
class ConsoleRedirect:
    """Redirects stdout/stderr to a Tkinter ScrolledText widget."""
    def __init__(self, widget):
        self.widget        = widget
        self._orig_stdout  = sys.stdout
        self._orig_stderr  = sys.stderr
        self._pending      = ""   # Buffer to accumulate incomplete lines.

    def write(self, msg):
        self._orig_stdout.write(msg)
        try:
            self._pending += msg
            # Only flush complete lines so each timestamp appears once per line.
            while "\n" in self._pending:
                line, self._pending = self._pending.split("\n", 1)
                ts = time.strftime("%H:%M:%S")
                self.widget.configure(state='normal')
                self.widget.insert('end', f"[{ts}] {line}\n")
                self.widget.see('end')
                self.widget.configure(state='disabled')
        except Exception:
            pass

    def flush(self): pass

    def start(self):
        sys.stdout = self
        sys.stderr = self

    def stop(self):
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr


# ========================= BOT MAIN =========================
# Reference to the running asyncio event loop (set when bot starts).
_bot_loop: asyncio.AbstractEventLoop | None = None

async def bot_main():
    update_overlay()
    threading.Thread(target=start_overlay_server, daemon=True).start()
    print("Bot starting...\n")
    await asyncio.gather(youtube_loop())


def _load_vm_list() -> dict:
    """Load VM aliases from vms.json. Returns {} if file missing."""
    if os.path.exists(VM_DATABASE_FILE):
        try:
            with open(VM_DATABASE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_vm_list(data: dict):
    with open(VM_DATABASE_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ========================= GUI =========================
class NexovativeControlCenterGUI:
    BG      = "#0f0f1a"
    BG2     = "#16162a"
    BG3     = "#1e1e35"
    ACCENT  = "#7c5cbf"
    ACCENT2 = "#a07cdf"
    GREEN   = "#3ddc97"
    RED     = "#e05c7a"
    YELLOW  = "#f0c060"
    TEXT    = "#e8e8f0"
    TEXTDIM = "#8888aa"
    CONSOLE = "#0a0a14"
    CONTEXT = "#00e676"
    BORDER  = "#2d2d50"

    def __init__(self, root):
        self.root = root
        self.root.title("Nexovative Control Center")
        self.root.geometry("900x700")
        self.root.minsize(760, 580)
        self.root.configure(bg=self.BG)
        self.root.resizable(True, True)

        self._bot_thread     = None
        self._bot_running    = False
        self._console_redir  = None
        self._editing_cmd    = None
        self._step_items     = []

        self._build_styles()
        self._build_ui()
        load_custom_commands()
        self._refresh_cmd_list()
        self._report_missing_libraries()

    def _report_missing_libraries(self):
        if not MISSING_LIBRARIES:
            self._log("[Startup] All optional libraries are installed. All features are available.")
            return
        self._log(f"[Startup] {len(MISSING_LIBRARIES)} optional library(ies) missing. Related features are disabled:")
        for import_name, pip_name, description in MISSING_LIBRARIES:
            self._log(f"  - {import_name} (pip install {pip_name}) → {description}")

    # ── Styles ──
    def _build_styles(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure(".",
            background=self.BG, foreground=self.TEXT,
            fieldbackground=self.BG2, bordercolor=self.BORDER,
            troughcolor=self.BG2, selectbackground=self.ACCENT,
            selectforeground=self.TEXT, font=("Segoe UI", 10))
        s.configure("TNotebook", background=self.BG, tabmargins=[2,4,0,0])
        s.configure("TNotebook.Tab",
            background=self.BG2, foreground=self.TEXTDIM,
            padding=[16,6], font=("Segoe UI",10,"bold"))
        s.map("TNotebook.Tab",
            background=[("selected", self.BG3)],
            foreground=[("selected", self.TEXT)])
        s.configure("TFrame", background=self.BG)
        s.configure("Card.TFrame", background=self.BG2)
        s.configure("TLabel",  background=self.BG,  foreground=self.TEXT)
        s.configure("TEntry",
            fieldbackground=self.BG3, foreground=self.TEXT,
            insertcolor=self.TEXT, bordercolor=self.BORDER, relief="flat")
        s.configure("TCombobox",
            fieldbackground=self.BG3, foreground=self.TEXT,
            selectbackground=self.ACCENT, arrowcolor=self.ACCENT2)
        s.map("TCombobox", fieldbackground=[("readonly", self.BG3)])
        for name, bg, fg in [
            ("Green.TButton",  self.GREEN,  "#000"),
            ("Red.TButton",    self.RED,    "#fff"),
            ("Accent.TButton", self.ACCENT, "#fff"),
            ("Dim.TButton",    self.BG3,    self.TEXT),
        ]:
            s.configure(name, background=bg, foreground=fg,
                        font=("Segoe UI",10,"bold"), relief="flat", padding=[10,5])
            s.map(name, background=[("active", self.ACCENT2)])
        s.configure("TScrollbar",
            background=self.BG3, troughcolor=self.BG,
            arrowcolor=self.ACCENT2, bordercolor=self.BG)

    # ── Root UI ──
    def _build_ui(self):
        bar = tk.Frame(self.root, bg=self.BG2, height=48)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        tk.Label(bar, text="Nexovative Control Center",
                 bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI",13,"bold")).pack(side="left", padx=16, pady=8)
        self._status_dot = tk.Label(bar, text="  Stopped",
                                    bg=self.BG2, fg=self.RED,
                                    font=("Segoe UI",10,"bold"))
        self._status_dot.pack(side="right", padx=16)

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        t1 = ttk.Frame(nb); t2 = ttk.Frame(nb); t3 = ttk.Frame(nb)
        nb.add(t1, text="  Main  ")
        nb.add(t2, text="  Command Builder  ")
        nb.add(t3, text="  VM Controls  ")

        self._build_main_tab(t1)
        self._build_cmd_builder_tab(t2)
        self._build_vm_controls_tab(t3)

    # ──────────────── TAB 1: MAIN ────────────────
    def _build_main_tab(self, parent):
        card = ttk.Frame(parent, style="Card.TFrame", padding=16)
        card.pack(fill="x", padx=12, pady=(12,6))

        # YouTube ID
        tk.Label(card, text="YouTube Video ID", bg=self.BG2,
                 fg=self.TEXTDIM, font=("Segoe UI",9,"bold")).grid(
                 row=0, column=0, sticky="w", padx=(0,8))
        self._yt_var = tk.StringVar()
        ttk.Entry(card, textvariable=self._yt_var, width=34,
                  font=("Segoe UI Mono",10)).grid(
                  row=0, column=1, sticky="ew", padx=(0,12), ipady=4)

        # VM selection
        tk.Label(card, text="VMware VM", bg=self.BG2,
                 fg=self.TEXTDIM, font=("Segoe UI",9,"bold")).grid(
                 row=1, column=0, sticky="w", padx=(0,8), pady=(10,0))
        self._vm_var = tk.StringVar()
        self._vm_combo = ttk.Combobox(card, textvariable=self._vm_var,
                                      state="readonly", width=32,
                                      font=("Segoe UI",10))
        self._vm_combo.grid(row=1, column=1, sticky="ew",
                            padx=(0,12), pady=(10,0), ipady=3)
        ttk.Button(card, text="Refresh", style="Dim.TButton",
                   command=self._refresh_vm_list).grid(
                   row=1, column=2, pady=(10,0))

        # Add VM row
        tk.Label(card, text="Add VM", bg=self.BG2,
                 fg=self.TEXTDIM, font=("Segoe UI",9,"bold")).grid(
                 row=2, column=0, sticky="w", padx=(0,8), pady=(10,0))
        add_inner = tk.Frame(card, bg=self.BG2)
        add_inner.grid(row=2, column=1, columnspan=2, sticky="ew", pady=(10,0))
        self._alias_var = tk.StringVar()
        self._vmx_var   = tk.StringVar()
        ttk.Entry(add_inner, textvariable=self._alias_var,
                  width=10, font=("Segoe UI Mono",10)).pack(side="left", padx=(0,6), ipady=3)
        tk.Label(add_inner, text="alias", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI",8)).pack(side="left", padx=(0,10))
        ttk.Entry(add_inner, textvariable=self._vmx_var,
                  width=26, font=("Segoe UI Mono",10)).pack(side="left", padx=(0,6), ipady=3)
        tk.Label(add_inner, text=".vmx path", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI",8)).pack(side="left", padx=(0,10))
        ttk.Button(add_inner, text="+ Add", style="Dim.TButton",
                   command=self._add_vm).pack(side="left")

        card.columnconfigure(1, weight=1)

        # Buttons
        btn_f = tk.Frame(parent, bg=self.BG)
        btn_f.pack(fill="x", padx=12, pady=6)
        ttk.Button(btn_f, text="Start Bot", style="Green.TButton",
                   command=self._start_bot).pack(side="left", padx=(0,8))
        ttk.Button(btn_f, text="Stop Bot", style="Red.TButton",
                   command=self._stop_bot).pack(side="left")

        tk.Label(parent, text="Console Output", bg=self.BG, fg=self.TEXTDIM,
                 font=("Segoe UI",9,"bold")).pack(anchor="w", padx=16, pady=(4,0))

        cf = tk.Frame(parent, bg=self.BORDER, bd=1)
        cf.pack(fill="both", expand=True, padx=12, pady=(2,6))
        self._console = scrolledtext.ScrolledText(
            cf, bg=self.CONSOLE, fg=self.CONTEXT,
            font=("Consolas",9), insertbackground=self.CONTEXT,
            selectbackground=self.ACCENT, relief="flat", bd=0,
            state='disabled', wrap='word')
        self._console.pack(fill="both", expand=True, padx=1, pady=1)

        # Admin CMD
        af = tk.Frame(parent, bg=self.BG2, pady=6)
        af.pack(fill="x", padx=12, pady=(0,8))
        tk.Label(af, text="Admin CMD:", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI",9,"bold")).pack(side="left", padx=(8,6))
        self._admin_var = tk.StringVar()
        ae = ttk.Entry(af, textvariable=self._admin_var,
                       width=36, font=("Segoe UI Mono",10))
        ae.pack(side="left", padx=(0,8), ipady=4)
        ae.bind("<Return>", lambda e: self._send_admin_cmd())
        ttk.Button(af, text="Send", style="Accent.TButton",
                   command=self._send_admin_cmd).pack(side="left")

        self._refresh_vm_list()

    # ──────────────── TAB 2: COMMAND BUILDER ────────────────
    def _build_cmd_builder_tab(self, parent):
        pane = tk.PanedWindow(parent, orient="horizontal",
                              bg=self.BG, sashwidth=6, bd=0)
        pane.pack(fill="both", expand=True, padx=8, pady=8)

        # Left: list
        left = ttk.Frame(pane, style="Card.TFrame", padding=8)
        pane.add(left, minsize=180, width=220)
        tk.Label(left, text="Custom Commands", bg=self.BG2, fg=self.ACCENT2,
                 font=("Segoe UI",10,"bold")).pack(anchor="w", pady=(0,6))
        lf = tk.Frame(left, bg=self.BG3, highlightbackground=self.BORDER,
                      highlightthickness=1)
        lf.pack(fill="both", expand=True)
        self._cmd_listbox = tk.Listbox(lf, bg=self.BG3, fg=self.TEXT,
            selectbackground=self.ACCENT, selectforeground="#fff",
            activestyle="none", font=("Segoe UI Mono",10),
            relief="flat", bd=0, exportselection=False)
        self._cmd_listbox.pack(fill="both", expand=True)
        self._cmd_listbox.bind("<<ListboxSelect>>", self._on_cmd_select)
        br = tk.Frame(left, bg=self.BG2)
        br.pack(fill="x", pady=(6,0))
        ttk.Button(br, text="+ New", style="Green.TButton",
                   command=self._new_cmd).pack(side="left", expand=True, fill="x", padx=(0,4))
        ttk.Button(br, text="Del", style="Red.TButton",
                   command=self._delete_cmd).pack(side="left", expand=True, fill="x")

        # Right: editor
        right = ttk.Frame(pane, style="Card.TFrame", padding=10)
        pane.add(right, minsize=300)

        tr = tk.Frame(right, bg=self.BG2)
        tr.pack(fill="x", pady=(0,10))
        tk.Label(tr, text="Trigger:", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI",9,"bold")).pack(side="left", padx=(0,8))
        self._trig_var = tk.StringVar()
        ttk.Entry(tr, textvariable=self._trig_var,
                  font=("Segoe UI Mono",11), width=18).pack(side="left", ipady=4)
        tk.Label(tr, text="(e.g. !bubbles)", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI",9)).pack(side="left", padx=8)

        # Chain input
        cc = tk.Frame(right, bg=self.BG3, pady=8, padx=10)
        cc.pack(fill="x", pady=(0,10))
        hr = tk.Frame(cc, bg=self.BG3)
        hr.pack(fill="x", pady=(0,4))
        tk.Label(hr, text="Quick Chain Input", bg=self.BG3, fg=self.ACCENT2,
                 font=("Segoe UI",9,"bold")).pack(side="left")
        tk.Label(hr, text="  Write in chat syntax -> parse into steps",
                 bg=self.BG3, fg=self.TEXTDIM, font=("Segoe UI",8)).pack(side="left")
        cer = tk.Frame(cc, bg=self.BG3)
        cer.pack(fill="x")
        self._chain_var = tk.StringVar()
        ce = ttk.Entry(cer, textvariable=self._chain_var, font=("Segoe UI Mono",10))
        ce.pack(side="left", fill="x", expand=True, ipady=5, padx=(0,8))
        ce.bind("<Return>", lambda e: self._parse_chain_input())
        ttk.Button(cer, text="Parse Steps", style="Accent.TButton",
                   command=self._parse_chain_input).pack(side="left")
        tk.Label(cc,
                 text="Example:  !combo win+r  !wait 800  !typeenter notepad.exe  !wait 500  !type Hello World",
                 bg=self.BG3, fg=self.TEXTDIM, font=("Segoe UI",8),
                 wraplength=440, justify="left").pack(anchor="w", pady=(4,0))

        # Steps treeview
        sh = tk.Frame(right, bg=self.BG2)
        sh.pack(fill="x", pady=(0,4))
        tk.Label(sh, text="Steps", bg=self.BG2, fg=self.ACCENT2,
                 font=("Segoe UI",10,"bold")).pack(side="left")
        tk.Label(sh, text="  (Fill via Parse or add manually below)",
                 bg=self.BG2, fg=self.TEXTDIM, font=("Segoe UI",8)).pack(side="left")

        tf = tk.Frame(right, bg=self.BORDER, bd=1)
        tf.pack(fill="both", expand=True, pady=(0,6))
        self._step_tree = ttk.Treeview(tf, columns=("action","args"),
                                       show="headings", height=8, selectmode="browse")
        self._step_tree.heading("action", text="Action")
        self._step_tree.heading("args",   text="Arguments")
        self._step_tree.column("action", width=120, minwidth=90)
        self._step_tree.column("args",   width=240, minwidth=120)
        self._step_tree.pack(fill="both", expand=True, side="left")
        ts = ttk.Scrollbar(tf, orient="vertical", command=self._step_tree.yview)
        ts.pack(side="right", fill="y")
        self._step_tree.configure(yscrollcommand=ts.set)

        sbr = tk.Frame(right, bg=self.BG2)
        sbr.pack(fill="x", pady=(0,8))
        for lbl, fn in [("Up","_step_up"),("Down","_step_down"),("Remove","_step_remove")]:
            ttk.Button(sbr, text=lbl, style="Dim.TButton",
                       command=lambda f=fn: getattr(self,f)()).pack(side="left", padx=(0,4))

        ACTIONS = ["combo","type","typeenter","key","wait",
                   "click","rclick","move","abs","scroll"]
        addf = tk.Frame(right, bg=self.BG3, pady=8, padx=8)
        addf.pack(fill="x", pady=(0,8))
        tk.Label(addf, text="Add Step:", bg=self.BG3, fg=self.TEXTDIM,
                 font=("Segoe UI",9,"bold")).pack(side="left", padx=(0,8))
        self._action_var = tk.StringVar(value="combo")
        ttk.Combobox(addf, textvariable=self._action_var, values=ACTIONS,
                     state="readonly", width=12).pack(side="left", padx=(0,8), ipady=3)
        tk.Label(addf, text="Args:", bg=self.BG3, fg=self.TEXTDIM,
                 font=("Segoe UI",9)).pack(side="left", padx=(0,4))
        self._args_var = tk.StringVar()
        ttk.Entry(addf, textvariable=self._args_var, width=20,
                  font=("Segoe UI Mono",10)).pack(side="left", padx=(0,8), ipady=3)
        ttk.Button(addf, text="+ Add Step", style="Accent.TButton",
                   command=self._add_step).pack(side="left")

        tk.Label(right,
                 text="combo: win+r  |  type: notepad  |  typeenter: run.exe  |  wait: 500 (ms)  |  key: enter",
                 bg=self.BG2, fg=self.TEXTDIM, font=("Segoe UI",8),
                 wraplength=420, justify="left").pack(anchor="w", pady=(0,6))

        savr = tk.Frame(right, bg=self.BG2)
        savr.pack(fill="x")
        ttk.Button(savr, text="Save Command", style="Green.TButton",
                   command=self._save_cmd).pack(side="left", padx=(0,8))
        ttk.Button(savr, text="Test Now", style="Accent.TButton",
                   command=self._test_cmd).pack(side="left")

    # ──────────────── TAB 3: VM CONTROLS ────────────────
    def _build_vm_controls_tab(self, parent):
        tk.Label(parent, text="Virtual Machine Controls",
                 bg=self.BG, fg=self.ACCENT2,
                 font=("Segoe UI",13,"bold")).pack(pady=(24,4))
        tk.Label(parent, text="Direct admin actions — no vote required.",
                 bg=self.BG, fg=self.TEXTDIM,
                 font=("Segoe UI",9)).pack(pady=(0,28))

        grid = ttk.Frame(parent, style="Card.TFrame", padding=28)
        grid.pack(padx=60, fill="x")

        btn_cfg = [
            ("Start VM",    "green",  "Power on the virtual machine.",            self._vm_start),
            ("Restart VM",  "accent", "Send a hard reset to the VM.",             self._vm_restart),
            ("Revert VM",   "accent", "Revert to snapshot and reboot.",           self._vm_revert),
            ("Shutdown VM", "red",    "Force stop the virtual machine.",          self._vm_shutdown),
        ]
        style_map = {"green":"Green.TButton","accent":"Accent.TButton","red":"Red.TButton"}

        for i, (label, color, desc, cmd) in enumerate(btn_cfg):
            row = i // 2; col = i % 2
            cell = tk.Frame(grid, bg=self.BG2, padx=16, pady=16)
            cell.grid(row=row, column=col, padx=12, pady=12, sticky="nsew")
            grid.columnconfigure(col, weight=1)
            ttk.Button(cell, text=label, style=style_map[color],
                       command=cmd, width=18).pack()
            tk.Label(cell, text=desc, bg=self.BG2, fg=self.TEXTDIM,
                     font=("Segoe UI",8), wraplength=180, justify="center").pack(pady=(6,0))

        sf = tk.Frame(parent, bg=self.BG)
        sf.pack(pady=24)
        tk.Label(sf, text="Last action:", bg=self.BG, fg=self.TEXTDIM,
                 font=("Segoe UI",9)).pack(side="left", padx=(0,8))
        self._vm_action_label = tk.Label(sf, text="—", bg=self.BG,
                                          fg=self.TEXT, font=("Segoe UI",9,"bold"))
        self._vm_action_label.pack(side="left")

    def _vm_set_last(self, text, color=None):
        self._vm_action_label.configure(text=text, fg=color or self.TEXT)

    def _run_vm_action(self, coro, label_start, label_ok, label_err_prefix):
        self._vm_set_last(label_start, self.YELLOW)
        def run():
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(coro)
                loop.close()
                self.root.after(0, lambda: self._vm_set_last(label_ok, self.GREEN))
            except Exception as e:
                self.root.after(0, lambda: self._vm_set_last(f"{label_err_prefix}: {e}", self.RED))
                print(f"[VM] Error: {e}")
        threading.Thread(target=run, daemon=True).start()

    def _check_vmx(self) -> bool:
        if not VMX_PATH:
            messagebox.showerror("No VM", "Start the bot first to select a VM.")
            return False
        return True

    def _vm_start(self):
        if not self._check_vmx(): return
        self._log("[VM] Start requested.")
        async def _start():
            await run_vmrun(["-T","ws","start",VMX_PATH,"gui"])
        self._run_vm_action(_start(), "Starting...", "Started", "Start error")

    def _vm_restart(self):
        if not self._check_vmx(): return
        if not messagebox.askyesno("Restart VM", f"Hard reset the VM now?"): return
        self._log("[VM] Restart requested.")
        async def _restart():
            await run_vmrun(["-T","ws","reset",VMX_PATH,"hard"])
        self._run_vm_action(_restart(), "Restarting...", "Restarted", "Restart error")

    def _vm_revert(self):
        if not self._check_vmx(): return
        if not messagebox.askyesno("Revert VM",
                "Revert to snapshot 'snp' and reboot?\nAll unsaved VM state will be lost."): return
        self._log("[VM] Revert requested.")
        async def _revert():
            await run_vmrun(["-T","ws","revertToSnapshot",VMX_PATH,"snp"])
            await asyncio.sleep(5)
            await run_vmrun(["-T","ws","start",VMX_PATH,"gui"])
        self._run_vm_action(_revert(), "Reverting...", "Reverted", "Revert error")

    def _vm_shutdown(self):
        if not self._check_vmx(): return
        if not messagebox.askyesno("Shutdown VM",
                "Force stop the VM?\nUnsaved VM state will be lost."): return
        self._log("[VM] Shutdown requested.")
        async def _shutdown():
            await run_vmrun(["-T","ws","stop",VMX_PATH,"hard"])
        self._run_vm_action(_shutdown(), "Shutting down...", "Powered off", "Shutdown error")

    # ──────────────── VM List ────────────────
    def _refresh_vm_list(self):
        vms = _load_vm_list()
        aliases = list(vms.keys())
        self._vm_combo['values'] = aliases
        if aliases:
            self._vm_combo.current(0)
            self._log(f"VM list loaded: {', '.join(aliases)}")
        else:
            self._log("No VMs registered. Add one with alias + .vmx path above.")

    def _add_vm(self):
        alias = self._alias_var.get().strip().lower()
        vmx   = self._vmx_var.get().strip().replace('"','')
        if not alias or not vmx:
            messagebox.showwarning("Missing", "Enter both an alias and a .vmx path.")
            return
        vms = _load_vm_list()
        vms[alias] = vmx
        _save_vm_list(vms)
        self._alias_var.set(""); self._vmx_var.set("")
        self._refresh_vm_list()
        self._log(f"[VM] Added: {alias} -> {vmx}")

    # ──────────────── Bot Start / Stop ────────────────
    def _start_bot(self):
        global YOUTUBE_VIDEO_ID, VMX_PATH, vm_list, _bot_loop
        yt  = self._yt_var.get().strip()
        alias = self._vm_var.get().strip()
        if not yt:
            messagebox.showerror("Missing", "Enter a YouTube Video ID.")
            return
        if not alias:
            messagebox.showerror("Missing", "Select a VM.")
            return
        if self._bot_running:
            self._log("Bot is already running."); return

        vm_list = _load_vm_list()
        if alias not in vm_list:
            messagebox.showerror("Unknown VM", f"'{alias}' not found in vms.json.")
            return

        YOUTUBE_VIDEO_ID = yt
        VMX_PATH         = vm_list[alias]
        self._bot_running = True
        self._set_status("Running", self.GREEN)
        self._console_redir = ConsoleRedirect(self._console)
        self._console_redir.start()
        self._log(f"Starting bot -> YT: {YOUTUBE_VIDEO_ID}  |  VM: {alias} ({VMX_PATH})")

        def run():
            global _bot_loop
            try:
                _bot_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(_bot_loop)
                _bot_loop.run_until_complete(bot_main())
            except Exception as e:
                print(f"[Bot] Fatal error: {e}")
            finally:
                _bot_loop = None
                self._bot_running = False
                self.root.after(0, lambda: self._set_status("Stopped", self.RED))

        self._bot_thread = threading.Thread(target=run, daemon=True)
        self._bot_thread.start()

    def _stop_bot(self):
        self._bot_running = False
        loop = _bot_loop
        if loop and loop.is_running():
            # Cancel all running tasks in the bot event loop so youtube_loop exits.
            loop.call_soon_threadsafe(
                lambda: [t.cancel() for t in asyncio.all_tasks(loop)]
            )
        if self._console_redir:
            self._console_redir.stop()
            self._console_redir = None
        self._set_status("Stopped", self.RED)
        self._log("Bot stopped by user.")

    # ──────────────── Admin CMD ────────────────
    def _send_admin_cmd(self):
        cmd = self._admin_var.get().strip()
        if not cmd: return
        self._admin_var.set("")
        self._log(f"[AdminCMD] {cmd}")

        async def _run():
            c = cmd.lower()
            if c == "!startvm":
                await run_vmrun(["-T","ws","start",VMX_PATH,"gui"])
            elif c == "!restart":
                await run_vmrun(["-T","ws","reset",VMX_PATH,"hard"])
            elif c == "!revert":
                await run_vmrun(["-T","ws","revertToSnapshot",VMX_PATH,"snp"])
                await asyncio.sleep(5)
                await run_vmrun(["-T","ws","start",VMX_PATH,"gui"])
            elif c == "!shutdown":
                await run_vmrun(["-T","ws","stop",VMX_PATH,"hard"])
            elif c == "!clearvotes":
                votes["restartvm"] = []
                votes["revert"]    = []
                update_vote_json()
                print("[Admin] Votes cleared.")
            elif cmd.lower().startswith("!speak "):
                speak_text(cmd[7:].strip())
            else:
                print(f"[Admin] Unknown command: {cmd}")

        if _bot_loop and _bot_loop.is_running():
            asyncio.run_coroutine_threadsafe(_run(), _bot_loop)
        else:
            threading.Thread(
                target=lambda: asyncio.run(_run()), daemon=True
            ).start()

    # ──────────────── Helpers ────────────────
    def _log(self, msg):
        self._console.configure(state='normal')
        ts = time.strftime("%H:%M:%S")
        self._console.insert('end', f"[{ts}] {msg}\n")
        self._console.see('end')
        self._console.configure(state='disabled')

    def _set_status(self, text, color):
        self._status_dot.configure(text=f"  {text}", fg=color)

    # ──────────────── Chain Parser ────────────────
    def _parse_chain_input(self):
        raw = self._chain_var.get().strip()
        if not raw:
            messagebox.showinfo("Empty", "Chain input is empty.")
            return
        parts = [p.strip() for p in raw.split('!') if p.strip()]
        if not parts:
            messagebox.showwarning("Parse Error", "No valid commands found.\nCommands must start with !.")
            return
        steps = []
        for part in parts:
            tokens = part.split(maxsplit=1)
            steps.append({"action": tokens[0].lower(),
                           "args":   tokens[1] if len(tokens) > 1 else ""})
        self._step_items = steps
        self._refresh_step_tree()
        self._chain_var.set("")
        self._log(f"[ChainParse] {len(steps)} step(s): "
                  + "  ->  ".join(f"{s['action']}({s['args']})" for s in steps))

    # ──────────────── Command Builder ────────────────
    def _refresh_cmd_list(self):
        self._cmd_listbox.delete(0,'end')
        for t in sorted(custom_commands.keys()):
            self._cmd_listbox.insert('end', t)

    def _on_cmd_select(self, event=None):
        sel = self._cmd_listbox.curselection()
        if not sel: return
        trigger = self._cmd_listbox.get(sel[0])
        self._editing_cmd = trigger
        self._trig_var.set(trigger)
        self._step_items = list(custom_commands.get(trigger, []))
        self._refresh_step_tree()

    def _refresh_step_tree(self):
        for r in self._step_tree.get_children():
            self._step_tree.delete(r)
        for i, s in enumerate(self._step_items):
            tag = "even" if i%2==0 else "odd"
            self._step_tree.insert("","end", values=(s["action"],s["args"]), tags=(tag,))
        self._step_tree.tag_configure("even", background=self.BG3)
        self._step_tree.tag_configure("odd",  background=self.BG2)

    def _add_step(self):
        action = self._action_var.get().strip()
        args   = self._args_var.get().strip()
        if not action: return
        self._step_items.append({"action":action,"args":args})
        self._refresh_step_tree()
        self._args_var.set("")

    def _selected_idx(self):
        sel = self._step_tree.selection()
        if not sel: return None
        return list(self._step_tree.get_children()).index(sel[0])

    def _step_up(self):
        idx = self._selected_idx()
        if idx is None or idx==0: return
        self._step_items[idx-1],self._step_items[idx]=self._step_items[idx],self._step_items[idx-1]
        self._refresh_step_tree()
        self._step_tree.selection_set(self._step_tree.get_children()[idx-1])

    def _step_down(self):
        idx = self._selected_idx()
        if idx is None or idx>=len(self._step_items)-1: return
        self._step_items[idx],self._step_items[idx+1]=self._step_items[idx+1],self._step_items[idx]
        self._refresh_step_tree()
        self._step_tree.selection_set(self._step_tree.get_children()[idx+1])

    def _step_remove(self):
        idx = self._selected_idx()
        if idx is None: return
        self._step_items.pop(idx)
        self._refresh_step_tree()

    def _new_cmd(self):
        self._editing_cmd=None; self._trig_var.set("!"); self._step_items=[]
        self._refresh_step_tree(); self._cmd_listbox.selection_clear(0,'end')

    def _save_cmd(self):
        trigger = self._trig_var.get().strip()
        if not trigger.startswith("!") or len(trigger)<2:
            messagebox.showerror("Invalid Trigger", "Trigger must start with ! e.g. !bubbles")
            return
        custom_commands[trigger] = list(self._step_items)
        save_custom_commands()
        self._refresh_cmd_list()
        self._log(f"[CustomCmd] Saved '{trigger}' with {len(self._step_items)} step(s).")

    def _delete_cmd(self):
        sel = self._cmd_listbox.curselection()
        if not sel:
            messagebox.showinfo("Select", "Select a command to delete."); return
        trigger = self._cmd_listbox.get(sel[0])
        if messagebox.askyesno("Delete", f"Delete '{trigger}'?"):
            del custom_commands[trigger]
            save_custom_commands()
            self._refresh_cmd_list()
            self._new_cmd()
            self._log(f"[CustomCmd] Deleted '{trigger}'.")

    def _test_cmd(self):
        trigger = self._trig_var.get().strip()
        if trigger not in custom_commands:
            messagebox.showinfo("Not Saved", "Save the command first, then test."); return
        if _bot_loop:
            asyncio.run_coroutine_threadsafe(
                execute_custom_command_async(trigger), _bot_loop)
        else:
            threading.Thread(
                target=lambda: asyncio.run(execute_custom_command_async(trigger)),
                daemon=True).start()
        self._log(f"[CustomCmd] Testing '{trigger}'...")



def is_on_cooldown(cmd: str) -> bool:
    now = time.time()
    if cmd in last_command_time and now - last_command_time[cmd] < COOLDOWN.get(cmd, 5):
        return True
    last_command_time[cmd] = now
    return False


async def run_vmrun(args: list) -> bool:
    try:
        if not os.path.exists(VMRUN_PATH):
            print(f"vmrun not found. Checked Program Files and Program Files (x86): {VMRUN_PATH}")
            return False
        # run_in_executor prevents subprocess.run from blocking the async loop.
        loop   = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                [VMRUN_PATH] + args,
                capture_output=True,
                text=True,
                timeout=60,
            ),
        )
        return result.returncode == 0
    except Exception as e:
        print(f"VMRun error: {e}")
        return False


# ========================= COMMAND PROCESSOR =========================
async def process_command(message: str, author: str):
    if not message.startswith(PREFIX):
        return

    # FIX: Old code used message.split(PREFIX) which split on every "!" including
    # those inside arguments (e.g. "!type Hello! World" broke into two commands).
    # New approach: strip the leading prefix once, then split only on " !" (space +
    # prefix) so that "!" inside argument text is never treated as a command boundary.
    content      = message[len(PREFIX):]
    raw_commands = [cmd.strip() for cmd in content.split(f" {PREFIX}") if cmd.strip()]

    active_voters[author] = time.time()

    for raw_cmd in raw_commands:
        parts = raw_cmd.split()
        if not parts:
            continue

        command = parts[0].lower()
        args    = parts[1:]

        full_cmd_string = f"Running: {PREFIX}{command} {' '.join(args)}".strip()
        asyncio.create_task(show_running_command(full_cmd_string))

        # ---------- Custom commands (checked first) ----------
        trigger = PREFIX + command
        if trigger in custom_commands:
            asyncio.create_task(execute_custom_command_async(trigger))
            continue

        # ---------- VM control commands ----------
        if command == "startvm":
            if is_on_cooldown("startvm"):
                continue
            # FIX: Was missing the required -T ws hosttype flags.
            await run_vmrun(["-T", "ws", "start", VMX_PATH, "gui"])

        elif command == "restartvm":
            if votes["restartvm"]:
                if author not in votes["restartvm"]:
                    votes["restartvm"].append(author)
                    update_vote_json(restart_time=VOTE_DURATION)
                    # FIX: Guard against double execution via _executing_votes in
                    # execute_vm_action — start_vote may also trigger it independently.
                    if len(votes["restartvm"]) >= REQUIRED_VOTES:
                        asyncio.create_task(execute_vm_action("restartvm"))
            else:
                asyncio.create_task(start_vote("restartvm", author))

        elif command == "revert":
            if votes["revert"]:
                if author not in votes["revert"]:
                    votes["revert"].append(author)
                    update_vote_json(revert_time=VOTE_DURATION)
                    if len(votes["revert"]) >= REQUIRED_VOTES:
                        asyncio.create_task(execute_vm_action("revert"))
            else:
                asyncio.create_task(start_vote("revert", author))

        # ---------- Keyboard commands ----------
        elif command in ("key", "press") and args:
            await controller.send_key(" ".join(args).lower())

        elif command == "combo" and args:
            full_input = "+".join(args).lower().replace(" ", "+")
            while "++" in full_input:
                full_input = full_input.replace("++", "+")
            await controller.send_key(full_input)
            await asyncio.sleep(1.0)

        elif command == "hold" and args:
            key_name = args[0].lower()
            key      = SCANCODE_MAP.get(key_name, key_name)

            # FIX: float() was called without error handling; non-numeric input crashed.
            try:
                hold_duration = float(args[1]) if len(args) > 1 else 1.0
            except ValueError:
                hold_duration = 1.0
            hold_duration = min(hold_duration, 3.0)

            controller._abort_hold = False
            async with controller._lock:
                client = await controller.connect_fresh()
                if client:
                    loop        = asyncio.get_running_loop()
                    key_released = False
                    try:
                        await asyncio.wait_for(
                            loop.run_in_executor(None, lambda: client.keyDown(key)),
                            timeout=3.0,
                        )
                        elapsed = 0.0
                        while elapsed < hold_duration and not controller._abort_hold:
                            await asyncio.sleep(0.05)
                            elapsed += 0.05
                    finally:
                        try:
                            await asyncio.wait_for(
                                loop.run_in_executor(None, lambda: client.keyUp(key)),
                                timeout=3.0,
                            )
                            key_released = True
                        except Exception:
                            pass
                        if not key_released:
                            # Recovery: open a fresh connection and force-send keyUp.
                            # FIX: retry up to 3 times in case the VNC server is briefly busy.
                            for attempt in range(3):
                                try:
                                    rc = await asyncio.wait_for(
                                        loop.run_in_executor(
                                            None,
                                            lambda: vnc.connect(
                                                f"{VNC_HOST}::{VNC_PORT}",
                                                password=str(VNC_PASSWORD),
                                            ),
                                        ),
                                        timeout=5,
                                    )
                                    await asyncio.wait_for(
                                        loop.run_in_executor(None, lambda: rc.keyUp(key)),
                                        timeout=3.0,
                                    )
                                    rc.disconnect()
                                    print(f"Key force-released via recovery connection (attempt {attempt+1}): {key}")
                                    key_released = True
                                    break
                                except Exception:
                                    await asyncio.sleep(0.5)
                            if not key_released:
                                print(f"WARN: Recovery keyUp failed after 3 attempts for: {key}")

        elif command == "release" and args:
            # FIX: Must acquire the lock before connect_fresh() so we don't
            # disconnect a client that a concurrent hold/send_key is using.
            async with controller._lock:
                client = await controller.connect_fresh()
                if client:
                    key  = SCANCODE_MAP.get(args[0].lower(), args[0].lower())
                    loop = asyncio.get_running_loop()
                    try:
                        await asyncio.wait_for(
                            loop.run_in_executor(None, lambda: client.keyUp(key)),
                            timeout=3.0,
                        )
                    except Exception:
                        pass

        elif command == "releaseall":
            # Signal any active hold to abort immediately, THEN wait for the
            # lock.  Because hold's while-loop has await asyncio.sleep() points,
            # the event loop will let it see _abort_hold=True, exit the loop,
            # run its finally (keyUp), and release the lock before we proceed.
            # This eliminates the race condition where we used to just sleep 0.15 s
            # and then call connect_fresh() while hold was still inside its lock.
            controller._abort_hold = True
            async with controller._lock:
                client = await controller.connect_fresh()
                if client:
                    loop = asyncio.get_running_loop()
                    # FIX: expanded list — any holdable key can get stuck, not just
                    # classic modifiers.
                    release_keys = [
                        "shift", "ctrl", "control", "alt", "win", "super", "windows",
                        "capslock", "tab", "enter", "space", "backspace",
                        "up", "down", "left", "right",
                        "f1","f2","f3","f4","f5","f6","f7","f8","f9","f10","f11","f12",
                    ]
                    released_values = set()
                    for k in release_keys:
                        mapped = SCANCODE_MAP.get(k)
                        if mapped and mapped not in released_values:
                            released_values.add(mapped)
                            try:
                                await asyncio.wait_for(
                                    loop.run_in_executor(
                                        None, lambda mk=mapped: client.keyUp(mk)
                                    ),
                                    timeout=2.0,
                                )
                            except Exception:
                                pass
                    print("All modifier keys released.")

        # ---------- Text commands ----------
        elif command in ("send", "typeenter") and args:
            await controller.type_text(" ".join(args))
            await asyncio.sleep(0.05)
            await controller.send_key("enter")

        elif command == "type" and args:
            await controller.type_text(" ".join(args))

        # ---------- Mouse commands ----------
        elif command in ("move", "mouse", "mv") and args:
            client = await controller.connect_fresh()
            if client:
                try:
                    if args[0].isalpha():
                        direction = args[0].lower()
                        step      = int(args[1]) if len(args) > 1 and args[1].isdigit() else 40
                        if direction == "up":    controller.cursor_y -= step
                        elif direction == "down":  controller.cursor_y += step
                        elif direction == "left":  controller.cursor_x -= step
                        elif direction == "right": controller.cursor_x += step
                        controller.cursor_x = max(0, min(1920, controller.cursor_x))
                        controller.cursor_y = max(0, min(1080, controller.cursor_y))
                        loop = asyncio.get_running_loop()
                        await loop.run_in_executor(
                            None,
                            lambda: client.mouseMove(controller.cursor_x, controller.cursor_y),
                        )
                    elif len(args) >= 2:
                        dx, dy = int(args[0]), int(args[1])
                        controller.cursor_x = max(0, min(1920, controller.cursor_x + dx))
                        controller.cursor_y = max(0, min(1080, controller.cursor_y + dy))
                        loop = asyncio.get_running_loop()
                        await loop.run_in_executor(
                            None,
                            lambda: client.mouseMove(controller.cursor_x, controller.cursor_y),
                        )
                except Exception:
                    pass

        elif command in ("abs", "cursor", "moveabs") and len(args) >= 2:
            client = await controller.connect_fresh()
            if client:
                try:
                    controller.cursor_x = max(0, min(1920, int(args[0])))
                    controller.cursor_y = max(0, min(1080, int(args[1])))
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(
                        None,
                        lambda: client.mouseMove(controller.cursor_x, controller.cursor_y),
                    )
                except Exception:
                    pass

        elif command in ("drag", "dragrel") and len(args) >= 2:
            client = await controller.connect_fresh()
            if client:
                try:
                    dx, dy = int(args[0]), int(args[1])
                    controller.cursor_x = max(0, min(1920, controller.cursor_x + dx))
                    controller.cursor_y = max(0, min(1080, controller.cursor_y + dy))
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(
                        None,
                        lambda: client.mouseDrag(controller.cursor_x, controller.cursor_y),
                    )
                except Exception:
                    pass

        elif command in ("click", "lclick"):
            client = await controller.connect_fresh()
            if client:
                count = int(args[0]) if args and args[0].isdigit() else 1
                loop  = asyncio.get_running_loop()
                for _ in range(count):
                    await loop.run_in_executor(None, lambda: client.mousePress(1))
                    await asyncio.sleep(0.01)

        elif command in ("rclick", "rightclick"):
            client = await controller.connect_fresh()
            if client:
                count = int(args[0]) if args and args[0].isdigit() else 1
                loop  = asyncio.get_running_loop()
                for _ in range(count):
                    # FIX: Was mousePress(2) which is MIDDLE click in VNC protocol.
                    # Right click is button 3.
                    await loop.run_in_executor(None, lambda: client.mousePress(3))
                    await asyncio.sleep(0.01)

        elif command in ("scroll", "wheel") and args:
            client = await controller.connect_fresh()
            if client:
                try:
                    delta  = int(args[0])
                    button = 4 if delta > 0 else 5  # 4 = scroll up, 5 = scroll down
                    loop   = asyncio.get_running_loop()
                    # FIX: Was "abs(delta) // 120" which treated deltas like Windows
                    # WM_MOUSEWHEEL units; chat-sourced deltas are plain step counts
                    # (1, 2, 3 …) so dividing by 120 always produced 0, making scroll
                    # completely non-functional.
                    for _ in range(abs(delta)):
                        await loop.run_in_executor(None, lambda b=button: client.mousePress(b))
                        await asyncio.sleep(0.01)
                except Exception:
                    pass

        elif command == "wait" and args and args[0].replace(".", "", 1).isdigit():
            await asyncio.sleep(min(float(args[0]), 5.0))


# ========================= MAIN LOOPS =========================
async def youtube_loop():
    if not HAS_PYTCHAT:
        print("[Chat] pytchat is not installed - YouTube chat features are disabled.")
        return
    while True:
        chat       = None
        chat_start = time.time()
        try:
            chat = pytchat.create(video_id=YOUTUBE_VIDEO_ID)
            print("Chat connected.")

            while chat.is_alive():
                # Refresh the chat connection every 200 seconds.
                if time.time() - chat_start > 200:
                    print("Chat connection reset.")
                    break

                for c in chat.get().sync_items():
                    msg = c.message.strip()
                    if not msg:
                        continue
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] {c.author.name}: {msg}")
                    update_overlay(author=c.author.name, message=msg, msg_id=c.id)
                    if msg.startswith(PREFIX):
                        await process_command(msg, c.author.name)

                # Purge voters who have been inactive for more than 10 minutes
                # to prevent active_voters from growing indefinitely.
                cutoff = time.time() - 600
                stale = [k for k, v in active_voters.items() if v < cutoff]
                for k in stale:
                    del active_voters[k]

                await asyncio.sleep(0.4)

        except Exception as e:
            print(f"Chat loop error: {e}")
            await asyncio.sleep(3)
        finally:
            if chat:
                try:
                    chat.terminate()
                except Exception:
                    pass

        await asyncio.sleep(0.4)


# ========================= MAIN =========================
if __name__ == "__main__":
    print_missing_libraries_report()
    load_custom_commands()
    root = tk.Tk()
    app  = NexovativeControlCenterGUI(root)
    root.mainloop()
