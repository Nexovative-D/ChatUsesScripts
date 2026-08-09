import subprocess
import time
import signal as _signal_module
import threading as _threading_module
import tkinter as tk
import os
import sys
import importlib.util as _importlib_util
import json

# Which backend the user wants YouTubeChatSource to use:
#   "auto"            — try official (if key set) -> chat_downloader -> pytchat, in order (default)
#   "official"        — official API only, no fallback
#   "chat_downloader" — chat-downloader only, no fallback
#   "pytchat"         — pytchat only, no fallback
# Asked once at startup via _ask_chat_backend_choice(), changeable any
# time after that by re-running the picker or editing the config file.
# Defined here (near the top) because _ask_chat_backend_choice() /
# _show_chat_backend_dialog() are called during splash startup, before
# the rest of the module body has executed.
CHAT_BACKEND_PREFERENCE      = "auto"
CHAT_BACKEND_PREFERENCE_FILE = "chat_backend_preference.json"


def load_chat_backend_preference():
    global CHAT_BACKEND_PREFERENCE
    try:
        if os.path.exists(CHAT_BACKEND_PREFERENCE_FILE):
            with open(CHAT_BACKEND_PREFERENCE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            pref = data.get("backend", "auto")
            if pref in ("auto", "official", "chat_downloader", "pytchat"):
                CHAT_BACKEND_PREFERENCE = pref
    except Exception as e:
        print(f"[ChatBackendPref] Load error: {e}")
        CHAT_BACKEND_PREFERENCE = "auto"


def save_chat_backend_preference():
    try:
        with open(CHAT_BACKEND_PREFERENCE_FILE, "w", encoding="utf-8") as f:
            json.dump({"backend": CHAT_BACKEND_PREFERENCE}, f, indent=2)
        print(f"[ChatBackendPref] Saved: {CHAT_BACKEND_PREFERENCE}")
    except Exception as e:
        print(f"[ChatBackendPref] Save error: {e}")


# ========================= UAC ELEVATION =========================
# If not already running as administrator, re-launch with ShellExecuteW
# so Windows shows the UAC prompt. The original process exits immediately.
def _is_admin():
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

if not _is_admin():
    import ctypes
    # Show an explanation dialog before the UAC prompt so users are not alarmed.
    # Use the Windows MessageBox API directly — tkinter is not yet initialised.
    MB_YESNO        = 0x04
    MB_ICONQUESTION = 0x20
    IDYES           = 6
    msg = (
        "VirtualBox Chat Bot requires Administrator privileges.\n\n"
        "Reason: Without admin rights, the bot cannot write the\n"
        "overlay HTML files (vote status, OS vote, etc.).\n\n"
        "Click Yes to continue, No to exit."
    )
    answer = ctypes.windll.user32.MessageBoxW(
        0, msg, "Administrator Access Required", MB_YESNO | MB_ICONQUESTION
    )
    if answer != IDYES:
        sys.exit(0)
    # Re-launch with elevated privileges.
    script = os.path.abspath(sys.argv[0])
    params = " ".join(f'"{a}"' for a in sys.argv[1:])
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, f'"{script}" {params}', None, 1
    )
    sys.exit(0)

# ========================= VERSION & UPDATE CHECK =========================
VERSION = "31.3.0"   # increment this with every release

# Raw URL of version.json in your repo, and the page to send users to
# when a newer version is available.
GITHUB_VERSION_URL = "https://raw.githubusercontent.com/Nexovative-D/ChatUsesScripts/refs/heads/main/version.json"
GITHUB_REPO_PAGE_URL = "https://github.com/Nexovative-D/ChatUsesScripts"


def _check_for_update():
    """
    Downloads version.json from GitHub and compares its "version" field to
    the version running locally. If a newer version is available, asks the
    user whether to open the GitHub repo page so they can download and
    install the update themselves. Called once during splash, before the
    main GUI is built.
    """
    import urllib.request
    import json as _json
    import ctypes
    import webbrowser

    MB_YESNO        = 0x04
    MB_ICONQUESTION = 0x20
    IDYES           = 6

    try:
        _update_splash(8, "Checking for updates...")
        req = urllib.request.Request(
            GITHUB_VERSION_URL,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data       = _json.loads(resp.read().decode("utf-8"))
            latest_ver = data.get("version", "0.0.0").strip()
    except Exception as e:
        # Network unavailable or repo not configured — silently skip.
        print(f"[Updater] Could not check for updates: {e}")
        return

    def _ver_tuple(v):
        try:
            return tuple(int(x) for x in v.strip().split("."))
        except Exception:
            return (0, 0, 0)

    if _ver_tuple(latest_ver) <= _ver_tuple(VERSION):
        print(f"[Updater] Up to date ({VERSION}).")
        return

    # New version found — ask the user whether to open the GitHub page.
    msg = (
        f"A new version is available!\n\n"
        f"  Current version : {VERSION}\n"
        f"  New version     : {latest_ver}\n\n"
        f"Open the GitHub page to download the update?"
    )
    answer = ctypes.windll.user32.MessageBoxW(
        0, msg, "Update Available", MB_YESNO | MB_ICONQUESTION
    )
    if answer == IDYES:
        print(f"[Updater] Opening GitHub page for version {latest_ver}. Exiting.")
        webbrowser.open(GITHUB_REPO_PAGE_URL)
        try:
            if _host_root is not None:
                _host_root.destroy()
        except Exception:
            pass
        sys.exit(0)
    else:
        print(f"[Updater] User declined to open the GitHub page for {latest_ver}.")


# Show the splash immediately — before any heavy imports — so the user
# sees something within milliseconds of launching the script.

_splash_root   = None
_splash_bar    = None
_splash_label  = None
_splash_pct    = None
_splash_inner  = None   # inner frame, needed by the outro animation
_splash_brand_label = None
_splash_title_label = None
_splash_by_label = None
_splash_bar_bg = None
_splash_spinner_canvas = None   # Canvas holding the rotating dot spinner
_splash_spinner_angle  = 0      # current rotation angle of the spinner, in degrees
_host_root     = None   # the one-and-only tk.Tk() instance (kept hidden during splash)
APP_LITE_MODE  = False  # True = Lite Mode (fewer widgets, slower polling, for weaker PCs)
APP_EXTENDED_INTRO = False   # True = play the ~8s full-screen intro animation instead of the short one
SELECTED_MONITOR = None   # dict {"left","top","width","height"} of the monitor the user picked, or None if only one monitor exists

STARTUP_PREFS_FILE = "startup_prefs.json"


def _load_startup_prefs():
    """Reads small startup-screen preferences (currently just the extended-intro checkbox)."""
    try:
        if os.path.exists(STARTUP_PREFS_FILE):
            import json as _json
            with open(STARTUP_PREFS_FILE, "r", encoding="utf-8") as f:
                return _json.load(f)
    except Exception as e:
        print(f"[Startup] Could not read {STARTUP_PREFS_FILE}: {e}")
    return {}


def _save_startup_prefs(prefs: dict):
    try:
        import json as _json
        with open(STARTUP_PREFS_FILE, "w", encoding="utf-8") as f:
            _json.dump(prefs, f, indent=2)
    except Exception as e:
        print(f"[Startup] Could not save {STARTUP_PREFS_FILE}: {e}")


def _detect_monitors():
    """
    Returns a list of dicts describing every connected monitor:
    {"left": int, "top": int, "width": int, "height": int, "is_primary": bool}
    Uses ctypes + the Windows EnumDisplayMonitors API, so no extra
    dependency is required. Returns a single-item list on failure or on
    non-Windows systems, so callers can always treat the result the same way.
    """
    try:
        import ctypes
        from ctypes import wintypes

        monitors = []

        MONITORENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
            ctypes.POINTER(wintypes.RECT), ctypes.c_double
        )

        def _callback(hMonitor, hdcMonitor, lprcMonitor, dwData):
            r = lprcMonitor.contents
            monitors.append({
                "left": r.left, "top": r.top,
                "width": r.right - r.left, "height": r.bottom - r.top,
                "is_primary": (r.left == 0 and r.top == 0),
            })
            return 1

        ctypes.windll.user32.EnumDisplayMonitors(
            0, 0, MONITORENUMPROC(_callback), 0
        )

        if monitors:
            return monitors
    except Exception as e:
        print(f"[Startup] Monitor detection failed, assuming single monitor: {e}")

    return [{"left": 0, "top": 0, "width": 800, "height": 600, "is_primary": True}]


def _ask_monitor_choice(monitors):
    """
    Shown before the Lite/Full GUI mode dialog, only if more than one
    monitor was detected. Lets the user pick which monitor the app's
    windows (splash, dialogs, and the main window) should appear on.
    Sets the global SELECTED_MONITOR and returns nothing.
    """
    global SELECTED_MONITOR

    if len(monitors) <= 1:
        SELECTED_MONITOR = monitors[0] if monitors else None
        return

    dlg = tk.Toplevel(_host_root)
    dlg.title("")
    dlg.resizable(False, False)
    dlg.overrideredirect(True)
    W, H = 460, 120 + 46 * len(monitors)
    sw = dlg.winfo_screenwidth()
    sh = dlg.winfo_screenheight()
    x = (sw - W) // 2
    y = (sh - H) // 2
    dlg.geometry(f"{W}x{H}+{x}+{y}")
    dlg.configure(bg="#0f0f1a")

    border = tk.Frame(dlg, bg="#7c5cbf", padx=2, pady=2)
    border.place(relx=0, rely=0, relwidth=1, relheight=1)
    inner = tk.Frame(border, bg="#0f0f1a")
    inner.pack(fill="both", expand=True)

    tk.Label(inner, text="Choose a Monitor",
             bg="#0f0f1a", fg="#ffffff",
             font=("Segoe UI", 15, "bold")).pack(pady=(20, 4))

    tk.Label(inner,
             text=f"{len(monitors)} monitors detected. Pick where the app should open.",
             bg="#0f0f1a", fg="#aaaaaa",
             font=("Segoe UI", 9), justify="center").pack(pady=(0, 12))

    result = {"monitor": monitors[0]}

    def _choose(mon):
        result["monitor"] = mon
        dlg.destroy()

    for i, mon in enumerate(monitors):
        label = f"Monitor {i + 1}  —  {mon['width']}x{mon['height']}"
        if mon.get("is_primary"):
            label += "  (Primary)"
        tk.Button(
            inner, text=label,
            bg="#1e1e2e", fg="#3ddc97", activebackground="#2a2a3e",
            activeforeground="#3ddc97", relief="flat", bd=0,
            font=("Segoe UI", 9, "bold"), justify="center",
            width=36, height=1, cursor="hand2",
            command=lambda mon=mon: _choose(mon),
        ).pack(pady=(0, 6))

    dlg.lift()
    dlg.attributes("-topmost", True)
    dlg.focus_force()
    dlg.update()

    dlg.wait_window(dlg)

    SELECTED_MONITOR = result["monitor"]
    print(f"[Startup] Monitor selected: {SELECTED_MONITOR}")


# ========================= STARTUP DEPENDENCY CHECK =========================
# Runs once, right after the hidden host root is created and BEFORE the
# Lite/Full GUI mode picker. Detects which optional pip packages this script
# uses are missing on the current Python environment, and — if any are
# missing — offers to install them automatically via `pip install`, with a
# live per-package progress display. vboxapi is intentionally excluded from
# the auto-install offer: it isn't a normal PyPI package, it ships with the
# VirtualBox SDK, so it gets its own informational (non-installable) notice
# instead.
#
# Declining just continues the normal startup — every one of these imports
# is already wrapped in its own try/except further down, with the relevant
# feature disabled and a console message if the package is absent. This
# check only exists to make that same information visible up front, with a
# one-click fix, instead of the user discovering it feature-by-feature.
_STARTUP_OPTIONAL_DEPS = [
    # (import_name, pip_package_name, human_label)
    ("pytchat",         "pytchat",                 "pytchat — reading YouTube live chat (backend 3 of 3)"),
    ("chat_downloader", "chat-downloader",          "chat-downloader — reading YouTube live chat (backend 2 of 3)"),
    ("googleapiclient", "google-api-python-client", "google-api-python-client — official YouTube Data API chat backend (backend 1 of 3, needs an API key)"),
    ("win32com",     "pywin32",  "pywin32 — Windows COM / SAPI text-to-speech"),
    ("plyer",        "plyer",    "plyer — desktop toast notifications"),
    ("pystray",      "pystray",  "pystray — system tray icon"),
    ("PIL",          "pillow",   "Pillow — tray icon image support"),
    ("pyautogui",    "pyautogui","pyautogui — Real PC Control (mouse/keyboard)"),
    ("psutil",       "psutil",   "psutil — CPU/RAM display & Lite Mode recommendation"),
]


def _find_missing_optional_deps():
    """Returns a list of (import_name, pip_package_name, human_label) tuples
    for every optional dependency above that isn't currently importable.
    Uses find_spec so it doesn't actually import anything yet."""
    missing = []
    for import_name, pip_name, label in _STARTUP_OPTIONAL_DEPS:
        try:
            found = _importlib_util.find_spec(import_name) is not None
        except (ImportError, ValueError, ModuleNotFoundError):
            found = False
        if not found:
            missing.append((import_name, pip_name, label))
    return missing


def _vboxapi_present() -> bool:
    try:
        return _importlib_util.find_spec("vboxapi") is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def _restart_script():
    """Re-launches the current script fresh (new process replaces this one)
    so newly-installed packages are actually importable — a running Python
    process won't pick up a package that pip just installed underneath it."""
    python = sys.executable
    os.execv(python, [python] + sys.argv)


def _show_vboxapi_only_notice():
    """
    Simple info-only popup for the case where every pip-installable
    optional dependency is present and the ONLY thing missing is vboxapi.
    There's nothing to offer to install (vboxapi isn't a pip package), so
    this just informs the user and waits for a single OK — no install/skip
    choice, since there's no actual decision to make here.
    """
    dlg = tk.Toplevel(_host_root)
    dlg.title("")
    dlg.resizable(False, False)
    dlg.overrideredirect(True)
    W, H = 460, 220
    if SELECTED_MONITOR:
        sw, sh = SELECTED_MONITOR["width"], SELECTED_MONITOR["height"]
        mx, my = SELECTED_MONITOR["left"], SELECTED_MONITOR["top"]
    else:
        sw = dlg.winfo_screenwidth()
        sh = dlg.winfo_screenheight()
        mx, my = 0, 0
    x = mx + (sw - W) // 2
    y = my + (sh - H) // 2
    dlg.geometry(f"{W}x{H}+{x}+{y}")
    dlg.configure(bg="#0f0f1a")

    border = tk.Frame(dlg, bg="#7c5cbf", padx=2, pady=2)
    border.place(relx=0, rely=0, relwidth=1, relheight=1)
    inner = tk.Frame(border, bg="#0f0f1a")
    inner.pack(fill="both", expand=True)

    tk.Label(inner, text="⚠ vboxapi Not Installed",
             bg="#0f0f1a", fg="#ffffff",
             font=("Segoe UI", 13, "bold")).pack(pady=(20, 8))

    tk.Label(inner,
             text="vboxapi can't be installed via pip — it ships with the "
                  "VirtualBox SDK. VirtualBox mouse/session control will "
                  "stay disabled until you install it manually from the "
                  "VirtualBox SDK for your Python environment.\n\n"
                  "Every other library this script uses is already installed.",
             bg="#0f0f1a", fg="#e8a33d",
             font=("Segoe UI", 9), justify="left",
             wraplength=400).pack(padx=24, pady=(0, 16))

    tk.Button(
        inner, text="OK", bg="#7c5cbf", fg="#ffffff",
        activebackground="#a684e8", activeforeground="#ffffff",
        relief="flat", font=("Segoe UI", 9, "bold"),
        width=14, height=1, cursor="hand2",
        command=dlg.destroy,
    ).pack(pady=(0, 10))

    dlg.lift()
    dlg.attributes("-topmost", True)
    dlg.focus_force()
    dlg.update()
    dlg.wait_window(dlg)


def _run_dependency_check_and_offer_install():
    """
    Shown once, right after _host_root is created and before the Lite/Full
    GUI mode picker. If any optional pip packages are missing, asks the
    user whether to install them automatically. If they agree, installs
    each one via `pip install` in turn, showing live progress, then
    restarts the script so the new packages take effect. If they decline,
    or nothing is missing, startup just continues as normal.

    Special case: if every pip-installable package is present and vboxapi
    is the ONLY thing missing, there's no install/skip decision to make
    (vboxapi can't be pip-installed), so a simple info-only notice is
    shown instead of the full install dialog.
    """
    missing = _find_missing_optional_deps()
    vbox_ok = _vboxapi_present()

    if not missing and vbox_ok:
        return  # nothing to report — continue straight to normal startup

    if not missing and not vbox_ok:
        _show_vboxapi_only_notice()
        return

    dlg = tk.Toplevel(_host_root)
    dlg.title("")
    dlg.resizable(False, False)
    dlg.overrideredirect(True)
    W, H = 480, 460
    if SELECTED_MONITOR:
        sw, sh = SELECTED_MONITOR["width"], SELECTED_MONITOR["height"]
        mx, my = SELECTED_MONITOR["left"], SELECTED_MONITOR["top"]
    else:
        sw = dlg.winfo_screenwidth()
        sh = dlg.winfo_screenheight()
        mx, my = 0, 0
    x = mx + (sw - W) // 2
    y = my + (sh - H) // 2
    dlg.geometry(f"{W}x{H}+{x}+{y}")
    dlg.configure(bg="#0f0f1a")

    border = tk.Frame(dlg, bg="#7c5cbf", padx=2, pady=2)
    border.place(relx=0, rely=0, relwidth=1, relheight=1)
    inner = tk.Frame(border, bg="#0f0f1a")
    inner.pack(fill="both", expand=True)

    tk.Label(inner, text="Missing Python Libraries",
             bg="#0f0f1a", fg="#ffffff",
             font=("Segoe UI", 14, "bold")).pack(pady=(18, 4))

    # ── Bottom-anchored controls, packed FIRST so they always stay
    # visible no matter how long the missing-libraries list gets —
    # same fix as the NexoAI chat input row: an expand=True widget
    # packed first would claim all the space and push a later
    # side="bottom" widget out of view. ──
    btn_row = tk.Frame(inner, bg="#0f0f1a")
    btn_row.pack(side="bottom", pady=(6, 14))

    info_label = tk.Label(inner,
             text="Install them automatically now? Each will be installed "
                  "with pip, one at a time, with progress shown below. "
                  "You can also skip this — every feature above just stays "
                  "disabled until you install its package yourself.",
             bg="#0f0f1a", fg="#888888",
             font=("Segoe UI", 8), justify="left",
             wraplength=440)
    info_label.pack(side="bottom", padx=20, pady=(0, 6))

    progress_frame = tk.Frame(inner, bg="#0f0f1a")
    # Not packed yet — only shown once install actually starts (see
    # _do_install), packed side="bottom" at that point too.
    status_label = tk.Label(progress_frame, text="", bg="#0f0f1a", fg="#cccccc",
                             font=("Segoe UI", 9))
    status_label.pack(pady=(4, 4))
    bar_bg = tk.Frame(progress_frame, bg="#1e1e2e", height=18, width=420)
    bar_bg.pack_propagate(False)
    bar_bg.pack(pady=(0, 4))
    bar_fill = tk.Frame(bar_bg, bg="#3ddc97", height=18, width=0)
    bar_fill.place(x=0, y=0)
    pct_label = tk.Label(progress_frame, text="0%", bg="#0f0f1a", fg="#3ddc97",
                          font=("Segoe UI", 8, "bold"))
    pct_label.pack()

    if not vbox_ok:
        tk.Label(inner,
                 text="⚠ vboxapi is also missing, but it can't be installed via "
                      "pip — it ships with the VirtualBox SDK. VirtualBox "
                      "mouse/session control will stay disabled until you "
                      "install it manually from the VirtualBox SDK for your "
                      "Python environment.",
                 bg="#0f0f1a", fg="#e8a33d",
                 font=("Segoe UI", 8), justify="left",
                 wraplength=440).pack(side="bottom", padx=20, pady=(0, 6))

    if missing:
        tk.Label(inner,
                 text=f"{len(missing)} optional package(s) used by this script "
                      f"aren't installed:",
                 bg="#0f0f1a", fg="#aaaaaa",
                 font=("Segoe UI", 9), justify="center",
                 wraplength=440).pack(pady=(0, 6))

        # Scrollable list — fixed max height (doesn't matter if there are
        # 3 missing libraries or 30, the dialog itself never grows and
        # the buttons below never get pushed off-screen).
        list_outer = tk.Frame(inner, bg="#1e1e2e", highlightthickness=0)
        list_outer.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        list_canvas = tk.Canvas(list_outer, bg="#1e1e2e", highlightthickness=0,
                                 height=160)
        list_scrollbar = tk.Scrollbar(list_outer, orient="vertical",
                                       command=list_canvas.yview)
        list_frame = tk.Frame(list_canvas, bg="#1e1e2e")

        list_frame.bind(
            "<Configure>",
            lambda e: list_canvas.configure(scrollregion=list_canvas.bbox("all"))
        )
        list_canvas.create_window((0, 0), window=list_frame, anchor="nw",
                                   width=W - 76)
        list_canvas.configure(yscrollcommand=list_scrollbar.set)

        list_canvas.pack(side="left", fill="both", expand=True)
        list_scrollbar.pack(side="right", fill="y")

        # Mouse wheel support (Windows sends <MouseWheel> with .delta)
        def _on_mousewheel(event):
            list_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        list_canvas.bind("<Enter>", lambda e: list_canvas.bind_all("<MouseWheel>", _on_mousewheel))
        list_canvas.bind("<Leave>", lambda e: list_canvas.unbind_all("<MouseWheel>"))

        for _, pip_name, label in missing:
            tk.Label(list_frame, text=f"•  {label}",
                     bg="#1e1e2e", fg="#f0c060",
                     font=("Segoe UI", 9), anchor="w",
                     justify="left", wraplength=W - 96).pack(fill="x", padx=10, pady=2)

    result = {"choice": None}   # "install", "skip", or None (window closed)

    def _do_install():
        btn_row.pack_forget()
        if missing:
            info_label.pack_forget()
        progress_frame.pack(side="bottom", pady=(6, 10))
        dlg.update()

        total = len(missing)
        for i, (import_name, pip_name, label) in enumerate(missing, start=1):
            status_label.configure(text=f"Installing {pip_name}  ({i}/{total})...")
            dlg.update()
            try:
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "--upgrade", pip_name],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                status_label.configure(text=f"✓ Installed {pip_name}  ({i}/{total})")
            except subprocess.CalledProcessError as e:
                status_label.configure(text=f"✗ Failed to install {pip_name} — "
                                             f"see console for details")
                print(f"[DepInstall] Failed installing {pip_name}: {e.stderr}")
            dlg.update()

            pct = int((i / total) * 100)
            bar_fill.configure(width=int(420 * (pct / 100)))
            pct_label.configure(text=f"{pct}%")
            dlg.update()
            time.sleep(0.2)   # brief pause so each step is visible, not a flash

        status_label.configure(text="Done — restarting script...")
        dlg.update()
        time.sleep(1.0)
        result["choice"] = "install"
        dlg.destroy()

    def _skip_install():
        result["choice"] = "skip"
        dlg.destroy()

    if missing:
        tk.Button(
            btn_row, text="✅  Install Automatically",
            bg="#3ddc97", fg="#0f0f1a", activebackground="#5eeab0",
            activeforeground="#0f0f1a", relief="flat",
            font=("Segoe UI", 9, "bold"), justify="center",
            width=20, height=2, cursor="hand2",
            command=_do_install,
        ).pack(side="left", padx=(0, 8))

    tk.Button(
        btn_row, text="Skip  (keep those features disabled)",
        bg="#1e1e2e", fg="#cccccc", activebackground="#2a2a3e",
        activeforeground="#ffffff", relief="flat",
        font=("Segoe UI", 9), justify="center",
        width=24 if missing else 30, height=2, cursor="hand2",
        command=_skip_install,
    ).pack(side="left")

    dlg.lift()
    dlg.attributes("-topmost", True)
    dlg.focus_force()
    dlg.update()

    dlg.wait_window(dlg)

    if result["choice"] == "install":
        _restart_script()   # never returns — new process takes over
    # "skip" or window closed some other way -> fall through, startup continues


def _ask_chat_backend_choice():
    """
    Called at startup, right after the dependency check dialog and before
    the Lite/Full GUI mode picker. Shows the picker dialog ONLY if no
    remembered choice exists yet — if the user previously checked
    "Remember my choice", this skips straight past silently and just
    uses the saved preference. See _show_chat_backend_dialog() for the
    actual picker (also reachable later from the Main tab).
    """
    if os.path.exists(CHAT_BACKEND_PREFERENCE_FILE):
        # A previous launch already remembered a choice — honor it
        # silently instead of asking again.
        load_chat_backend_preference()
        return
    _show_chat_backend_dialog()


def _show_chat_backend_dialog():
    """
    Lets the user choose which YouTube chat backend YouTubeChatSource
    should use — see the class docstring for what each one means. Sets
    the global CHAT_BACKEND_PREFERENCE and persists it if "Remember my
    choice" is checked. Called both at startup (via
    _ask_chat_backend_choice) and on demand from the Main tab's
    "Change Chat Backend" button.
    """
    global CHAT_BACKEND_PREFERENCE

    dlg = tk.Toplevel(_host_root)
    dlg.title("")
    dlg.resizable(False, False)
    dlg.overrideredirect(True)
    W, H = 480, 500
    if SELECTED_MONITOR:
        sw, sh = SELECTED_MONITOR["width"], SELECTED_MONITOR["height"]
        mx, my = SELECTED_MONITOR["left"], SELECTED_MONITOR["top"]
    else:
        sw = dlg.winfo_screenwidth()
        sh = dlg.winfo_screenheight()
        mx, my = 0, 0
    x = mx + (sw - W) // 2
    y = my + (sh - H) // 2
    dlg.geometry(f"{W}x{H}+{x}+{y}")
    dlg.configure(bg="#0f0f1a")

    border = tk.Frame(dlg, bg="#7c5cbf", padx=2, pady=2)
    border.place(relx=0, rely=0, relwidth=1, relheight=1)
    inner = tk.Frame(border, bg="#0f0f1a")
    inner.pack(fill="both", expand=True)

    tk.Label(inner, text="YouTube Chat Backend",
             bg="#0f0f1a", fg="#ffffff",
             font=("Segoe UI", 14, "bold")).pack(pady=(18, 4))

    tk.Label(inner,
             text="How should the bot read YouTube live chat?",
             bg="#0f0f1a", fg="#aaaaaa",
             font=("Segoe UI", 9), justify="center",
             wraplength=440).pack(pady=(0, 14))

    remember_var = tk.BooleanVar(value=True)

    result = {"backend": CHAT_BACKEND_PREFERENCE}

    def _choose(backend):
        result["backend"] = backend
        dlg.destroy()

    options = [
        ("auto", "🔀  Auto (recommended)",
         "Tries the official API first (if a key is set on the Main tab), "
         "then chat-downloader, then pytchat — falls back automatically "
         "if one fails."),
        ("official", "🔑  Official YouTube API only",
         "Needs an API key (set on the Main tab). Never breaks from a "
         "YouTube update, but uses your daily API quota. Fails with no "
         "fallback if the key is missing/invalid."),
        ("chat_downloader", "📥  chat-downloader only",
         "Free, no API key needed. Unofficial — reads YouTube's internal "
         "chat format, so it can break if YouTube changes something.\n"
         "⚠ Known issue: currently prone to failing with \"Unable to parse "
         "initial video data\" — a bug in the chat-downloader library itself "
         "(YouTube page format it depends on). If you hit that error, switch "
         "to Auto or pytchat, or try 'pip install --upgrade chat-downloader'."),
        ("pytchat", "🐍  pytchat only",
         "Free, no API key needed. The original backend this script has "
         "always used. Also unofficial, same breakage risk as above."),
    ]

    for value, title, desc in options:
        row = tk.Frame(inner, bg="#1e1e2e", cursor="hand2")
        row.pack(fill="x", padx=20, pady=4)

        is_current = (value == CHAT_BACKEND_PREFERENCE)
        title_fg = "#3ddc97" if is_current else "#ffffff"
        suffix = "   (current)" if is_current else ""

        title_lbl = tk.Label(row, text=title + suffix, bg="#1e1e2e", fg=title_fg,
                              font=("Segoe UI", 10, "bold"), anchor="w",
                              justify="left")
        title_lbl.pack(fill="x", padx=10, pady=(6, 0))
        desc_fg = "#e0a72e" if value == "chat_downloader" else "#888888"
        desc_lbl = tk.Label(row, text=desc, bg="#1e1e2e", fg=desc_fg,
                             font=("Segoe UI", 8), anchor="w", justify="left",
                             wraplength=420)
        desc_lbl.pack(fill="x", padx=10, pady=(0, 6))

        for widget in (row, title_lbl, desc_lbl):
            widget.bind("<Button-1>", lambda e, v=value: _choose(v))

    remember_chk = tk.Checkbutton(
        inner, text="Remember my choice (don't ask again next launch)",
        variable=remember_var, bg="#0f0f1a", fg="#aaaaaa",
        selectcolor="#1e1e2e", activebackground="#0f0f1a",
        activeforeground="#ffffff", font=("Segoe UI", 8))
    remember_chk.pack(pady=(8, 4))

    dlg.lift()
    dlg.attributes("-topmost", True)
    dlg.focus_force()
    dlg.update()

    dlg.wait_window(dlg)

    CHAT_BACKEND_PREFERENCE = result["backend"]
    if remember_var.get():
        save_chat_backend_preference()
    else:
        # Explicitly reset the saved file to "auto" so a previous
        # "remembered" choice doesn't linger and get picked up next
        # launch after the user just said not to remember this one.
        try:
            if os.path.exists(CHAT_BACKEND_PREFERENCE_FILE):
                os.remove(CHAT_BACKEND_PREFERENCE_FILE)
        except Exception:
            pass


def _ask_startup_mode():
    """
    Shown once, right after the hidden host root is created and before the
    splash screen appears. Lets the user pick between Full GUI Mode and
    Lite Mode (fewer widgets built up front, slower background refresh
    intervals) for weaker computers, and whether to play the extended,
    full-screen ~8s intro animation instead of the short one. Returns
    nothing — sets the global APP_LITE_MODE and APP_EXTENDED_INTRO flags
    directly. The extended-intro choice is remembered across launches.
    """
    global APP_LITE_MODE, APP_EXTENDED_INTRO

    prefs = _load_startup_prefs()
    remembered_extended_intro = bool(prefs.get("extended_intro", False))

    # ── Detect system specs and decide which mode to recommend ──
    recommend_lite = False
    spec_summary = ""
    try:
        import psutil
        total_ram_gb = psutil.virtual_memory().total / (1024 ** 3)
        cpu_cores    = psutil.cpu_count(logical=True) or 1

        # Simple heuristic: recommend Lite Mode on lower-end machines.
        # Full GUI Mode builds every tab up front and polls more often, so
        # it benefits from more headroom than a bare minimum system has.
        if total_ram_gb < 6 or cpu_cores <= 2:
            recommend_lite = True

        spec_summary = f"Detected: {total_ram_gb:.1f} GB RAM, {cpu_cores} CPU cores"
        print(f"[Startup] {spec_summary} — recommending "
              f"{'Lite' if recommend_lite else 'Full GUI'} Mode")
    except Exception as e:
        print(f"[Startup] Could not detect system specs: {e}")
        spec_summary = ""

    dlg = tk.Toplevel(_host_root)
    dlg.title("")
    dlg.resizable(False, False)
    dlg.overrideredirect(True)
    W, H = 460, 360
    if SELECTED_MONITOR:
        sw, sh = SELECTED_MONITOR["width"], SELECTED_MONITOR["height"]
        mx, my = SELECTED_MONITOR["left"], SELECTED_MONITOR["top"]
    else:
        sw = dlg.winfo_screenwidth()
        sh = dlg.winfo_screenheight()
        mx, my = 0, 0
    x  = mx + (sw - W) // 2
    y  = my + (sh - H) // 2
    dlg.geometry(f"{W}x{H}+{x}+{y}")
    dlg.configure(bg="#0f0f1a")

    border = tk.Frame(dlg, bg="#7c5cbf", padx=2, pady=2)
    border.place(relx=0, rely=0, relwidth=1, relheight=1)
    inner = tk.Frame(border, bg="#0f0f1a")
    inner.pack(fill="both", expand=True)

    tk.Label(inner, text="Choose Startup Mode",
             bg="#0f0f1a", fg="#ffffff",
             font=("Segoe UI", 15, "bold")).pack(pady=(20, 4))

    tk.Label(inner,
             text="Pick Lite Mode if your computer is older or slower.\n"
                  "You can't switch modes without restarting the app.",
             bg="#0f0f1a", fg="#aaaaaa",
             font=("Segoe UI", 9), justify="center").pack(pady=(0, 6))

    if spec_summary:
        rec_text = ("Recommended: Lite Mode" if recommend_lite
                    else "Recommended: Full GUI Mode")
        rec_color = "#3ddc97" if recommend_lite else "#a684e8"
        tk.Label(inner, text=spec_summary,
                 bg="#0f0f1a", fg="#666680",
                 font=("Segoe UI", 8)).pack(pady=(0, 1))
        tk.Label(inner, text=rec_text,
                 bg="#0f0f1a", fg=rec_color,
                 font=("Segoe UI", 9, "bold")).pack(pady=(0, 10))
    else:
        tk.Label(inner, text="").pack(pady=(0, 14))   # keeps layout consistent

    result = {"lite": recommend_lite, "extended_intro": remembered_extended_intro}

    def _choose(lite: bool):
        result["lite"] = lite
        dlg.destroy()

    btn_row = tk.Frame(inner, bg="#0f0f1a")
    btn_row.pack(pady=(0, 4))

    # Recommended option gets a bright border to draw the eye, without
    # hiding or disabling the other choice — it's a suggestion, not a lock.
    full_highlight = bool(spec_summary) and not recommend_lite
    lite_highlight = bool(spec_summary) and recommend_lite

    full_btn = tk.Button(
        btn_row,
        text=("⭐ " if full_highlight else "") + "🖥  Full GUI Mode\n(all features, more RAM/CPU)",
        bg="#7c5cbf", fg="#ffffff", activebackground="#a684e8",
        activeforeground="#ffffff", relief="flat",
        bd=3 if full_highlight else 0,
        highlightthickness=2 if full_highlight else 0,
        highlightbackground="#f0c060", highlightcolor="#f0c060",
        font=("Segoe UI", 9, "bold"), justify="center",
        width=22, height=3, cursor="hand2",
        command=lambda: _choose(False),
    )
    full_btn.pack(side="left", padx=(0, 8))

    lite_btn = tk.Button(
        btn_row,
        text=("⭐ " if lite_highlight else "") + "🪶  Lite Mode\n(fewer widgets, lower usage)",
        bg="#1e1e2e", fg="#3ddc97", activebackground="#2a2a3e",
        activeforeground="#3ddc97", relief="flat",
        bd=3 if lite_highlight else 0,
        highlightthickness=2 if lite_highlight else 0,
        highlightbackground="#f0c060", highlightcolor="#f0c060",
        font=("Segoe UI", 9, "bold"), justify="center",
        width=22, height=3, cursor="hand2",
        command=lambda: _choose(True),
    )
    lite_btn.pack(side="left")

    # ── Extended intro animation checkbox ──
    extended_var = tk.BooleanVar(value=remembered_extended_intro)

    def _on_extended_toggle():
        result["extended_intro"] = extended_var.get()

    intro_check = tk.Checkbutton(
        inner, text="Play extended intro animation (~8s, full screen)",
        variable=extended_var, command=_on_extended_toggle,
        bg="#0f0f1a", fg="#cccccc", selectcolor="#1e1e2e",
        activebackground="#0f0f1a", activeforeground="#ffffff",
        font=("Segoe UI", 9), cursor="hand2",
    )
    intro_check.pack(pady=(14, 0))

    tk.Label(inner, text="Otherwise the quick ~4s animation plays instead.",
             bg="#0f0f1a", fg="#666680",
             font=("Segoe UI", 8)).pack(pady=(2, 0))

    tk.Label(inner, text="Script by Nexovative",
             bg="#0f0f1a", fg="#f0c060",
             font=("Segoe UI", 8, "bold")).pack(side="bottom", pady=(0, 10))

    dlg.lift()
    dlg.attributes("-topmost", True)
    dlg.focus_force()
    dlg.update()

    # Block here (small local event loop) until the user picks one.
    dlg.wait_window(dlg)

    APP_LITE_MODE = result["lite"]
    APP_EXTENDED_INTRO = result["extended_intro"]
    _save_startup_prefs({"extended_intro": APP_EXTENDED_INTRO})
    print(f"[Startup] Mode selected: {'LITE' if APP_LITE_MODE else 'FULL GUI'}, "
          f"extended intro: {APP_EXTENDED_INTRO}")


def _create_splash():
    global _splash_root, _splash_bar, _splash_label, _splash_pct, _host_root
    global _splash_inner, _splash_brand_label, _splash_title_label, _splash_by_label, _splash_bar_bg
    global _splash_spinner_canvas, _splash_spinner_angle

    # Create the single tk.Tk() host window and keep it hidden.
    # All ttk styles will be registered on this interpreter.
    _host_root = tk.Tk()
    _host_root.withdraw()

    monitors = _detect_monitors()
    _ask_monitor_choice(monitors)   # only actually prompts if more than one monitor was found

    _run_dependency_check_and_offer_install()   # offers to pip-install any missing optional packages; restarts the script if the user accepts

    _ask_chat_backend_choice()   # user picks which YouTube chat backend to use (official API / chat-downloader / pytchat / auto)

    _ask_startup_mode()   # user picks Full GUI vs Lite Mode before anything else loads

    W, H = 480, 240
    # Splash is a Toplevel so it shares the same Tk interpreter
    splash = tk.Toplevel(_host_root)
    splash.title("")
    splash.resizable(False, False)
    splash.overrideredirect(True)          # borderless window
    if SELECTED_MONITOR:
        sw, sh = SELECTED_MONITOR["width"], SELECTED_MONITOR["height"]
        mx, my = SELECTED_MONITOR["left"], SELECTED_MONITOR["top"]
    else:
        sw = splash.winfo_screenwidth()
        sh = splash.winfo_screenheight()
        mx, my = 0, 0
    x  = mx + (sw - W) // 2
    y  = my + (sh - H) // 2
    splash.geometry(f"{W}x{H}+{x}+{y}")
    splash.configure(bg="#0f0f1a")

    # Border frame
    border = tk.Frame(splash, bg="#7c5cbf", padx=2, pady=2)
    border.place(relx=0, rely=0, relwidth=1, relheight=1)
    inner = tk.Frame(border, bg="#0f0f1a")
    inner.pack(fill="both", expand=True)
    _splash_inner = inner

    # "Script by Nexovative"
    _splash_by_label = tk.Label(inner, text="Script by Nexovative",
             bg="#0f0f1a", fg="#f0c060",
             font=("Segoe UI", 11, "bold"))
    _splash_by_label.pack(pady=(18, 0))

    # App title
    _splash_title_label = tk.Label(inner, text="Nexovative Control Center",
             bg="#0f0f1a", fg="#ffffff",
             font=("Segoe UI", 18, "bold"))
    _splash_title_label.pack(pady=(4, 0))

    # ── Windows 11-style rotating dot spinner ──
    SPINNER_SIZE = 46
    spinner = tk.Canvas(inner, width=SPINNER_SIZE, height=SPINNER_SIZE,
                         bg="#0f0f1a", highlightthickness=0, bd=0)
    spinner.pack(pady=(16, 10))
    _splash_spinner_canvas = spinner
    _splash_spinner_angle = 0
    _draw_spinner(0)

    # Status row: current library being imported, with percentage alongside
    status_row = tk.Frame(inner, bg="#0f0f1a")
    status_row.pack(pady=(0, 8))

    _splash_label = tk.Label(status_row, text="Starting up...",
                              bg="#0f0f1a", fg="#cccccc",
                              font=("Segoe UI", 9))
    _splash_label.pack(side="left")

    _splash_pct = tk.Label(status_row, text="0%",
                            bg="#0f0f1a", fg="#3ddc97",
                            font=("Segoe UI", 9, "bold"))
    _splash_pct.pack(side="left", padx=(8, 0))

    # Kept for compatibility with code that references these — unused now
    # that the loading bar has been replaced by the spinner above.
    _splash_bar_bg = None
    _splash_bar    = None

    # Hidden until loading finishes — shows the animated "NEXOVATIVE" reveal.
    _splash_brand_label = tk.Label(inner, text="",
                                    bg="#0f0f1a", fg="#7c5cbf",
                                    font=("Segoe UI", 22, "bold"))
    # not packed yet — packed only when the intro animation starts

    _splash_root = splash
    splash.lift()
    # splash.attributes("-topmost", True)  # removed: caused splash to stay always on top
    splash.update()


def _draw_spinner(angle):
    """
    Draws a Windows 11-style rotating dot ring on the spinner canvas at the
    given rotation angle (degrees). Dots fade from bright to dim going
    backwards around the ring, giving the same "chasing dots" look as the
    Windows 11 boot/loading spinner.
    """
    import math

    canvas = _splash_spinner_canvas
    if canvas is None:
        return
    canvas.delete("spinner")

    size = 46
    cx, cy = size / 2, size / 2
    radius = size / 2 - 5
    dot_count = 8
    base_color = (166, 132, 232)   # #a684e8, matches ACCENT2

    for i in range(dot_count):
        dot_angle = math.radians(angle + i * (360 / dot_count))
        dx = cx + radius * math.cos(dot_angle)
        dy = cy + radius * math.sin(dot_angle)

        # Brightness fades around the ring so the ring reads as "spinning".
        brightness = 1.0 - (i / dot_count) * 0.85
        r = int(15 + (base_color[0] - 15) * brightness)
        g = int(15 + (base_color[1] - 15) * brightness)
        b = int(26 + (base_color[2] - 26) * brightness)
        color = f"#{r:02x}{g:02x}{b:02x}"

        dot_radius = 2.6 + 1.6 * brightness
        canvas.create_oval(dx - dot_radius, dy - dot_radius,
                            dx + dot_radius, dy + dot_radius,
                            fill=color, outline="", tags="spinner")


def _spin_splash(steps=10, step_degrees=12, delay=0.012):
    """
    Advances the spinner animation by a few frames. Called from
    _update_splash so the spinner keeps moving every time loading
    progress is reported, without needing a separate background thread.
    """
    global _splash_spinner_angle
    if _splash_root is None or _splash_spinner_canvas is None:
        return
    try:
        for _ in range(steps):
            _splash_spinner_angle = (_splash_spinner_angle + step_degrees) % 360
            _draw_spinner(_splash_spinner_angle)
            _splash_root.update_idletasks()
            _splash_root.update()
            time.sleep(delay)
    except Exception:
        pass


def _update_splash(pct, label=None):
    """
    Update the spinner-based loading screen (call from main thread).
    `label` is shown as the current step / library being imported, and
    `pct` is shown alongside it as a percentage. Also spins the dot
    ring forward a few frames so it animates continuously as loading
    progresses.
    """
    if _splash_root is None:
        return
    try:
        _splash_pct.configure(text=f"{pct}%")
        if label:
            _splash_label.configure(text=label)
        _spin_splash()
    except Exception:
        pass

def _play_chime(note_freqs, note_duration=0.12, sample_rate=44100, volume=0.25):
    """
    Synthesizes a short chime as PCM audio (a quick arpeggio of sine-wave
    notes with a soft fade-out on each note to avoid clicking) and plays it
    asynchronously via the built-in winsound module. No external files or
    audio libraries are required. Silently does nothing on non-Windows
    platforms or if anything about audio playback fails.
    """
    if sys.platform != "win32":
        return
    try:
        import winsound
        import struct
        import math as _math
        import tempfile

        samples = []
        for freq in note_freqs:
            n = int(sample_rate * note_duration)
            for i in range(n):
                t = i / sample_rate
                # Soft fade-out over the note's tail avoids an audible click.
                fade = 1.0 if i < n * 0.7 else max(0.0, 1.0 - (i - n * 0.7) / (n * 0.3))
                sample = _math.sin(2 * _math.pi * freq * t) * volume * fade
                samples.append(int(sample * 32767))

        pcm_data = struct.pack("<" + "h" * len(samples), *samples)

        num_channels = 1
        bits_per_sample = 16
        byte_rate = sample_rate * num_channels * bits_per_sample // 8
        block_align = num_channels * bits_per_sample // 8
        data_size = len(pcm_data)

        wav_header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF", 36 + data_size, b"WAVE",
            b"fmt ", 16, 1, num_channels, sample_rate,
            byte_rate, block_align, bits_per_sample,
            b"data", data_size,
        )

        tmp_path = os.path.join(
            tempfile.gettempdir(),
            f"_nexovative_chime_{int(time.time() * 1000) % 1000000}.wav"
        )
        with open(tmp_path, "wb") as f:
            f.write(wav_header + pcm_data)

        winsound.PlaySound(tmp_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
    except Exception as e:
        print(f"[Splash] Could not play chime: {e}")


def _play_splash_outro_animation():
    """
    Called once loading reaches 100%. Hides the progress bar / status text
    and plays a modern Canvas-based reveal of "NEXOVATIVE": each letter
    slides up and fades in with a staggered ease-out, an animated glow
    line sweeps in underneath, then the whole wordmark pulses through a
    gradient before a soft hold and close. Fully synchronous (uses
    time.sleep + root.update) so it fits into the existing linear startup
    sequence without needing Tk's event loop to already be running.
    """
    if _splash_root is None:
        print("[Splash] outro animation skipped — no splash root")
        return
    try:
        print("[Splash] playing NEXOVATIVE outro animation...")

        # Force the splash to the very front and keep it there for the
        # duration of the animation. Without this, if another window
        # (console, another app, the OS itself) stole focus while we were
        # loading, the animation would silently play behind it and the
        # user would never see it.
        _splash_root.deiconify()
        _splash_root.lift()
        _splash_root.attributes("-topmost", True)
        _splash_root.focus_force()
        _splash_root.update_idletasks()
        _splash_root.update()

        # Hide the loading-specific widgets — this is a reveal moment now.
        for w in (_splash_label, _splash_pct, _splash_bar_bg,
                  _splash_title_label, _splash_by_label, _splash_brand_label,
                  _splash_spinner_canvas):
            if w is not None:
                w.pack_forget()
        # The spinner's percentage/status labels live inside a small
        # container frame (status_row) that isn't tracked by any global —
        # walk the splash tree and hide any leftover children so nothing
        # from the loading screen lingers on top of the reveal.
        for child in _splash_inner.winfo_children():
            if child not in (_splash_brand_label,):
                child.pack_forget()

        BG = "#0f0f1a"
        word = "NEXOVATIVE"

        canvas_w, canvas_h = 440, 130
        canvas = tk.Canvas(_splash_inner, width=canvas_w, height=canvas_h,
                            bg=BG, highlightthickness=0, bd=0)
        canvas.pack(pady=(24, 0))
        _splash_root.update_idletasks()
        _splash_root.update()
        time.sleep(0.12)   # tiny beat so the cleared layout is visible first

        import random
        import math
        random.seed()

        font_name = ("Segoe UI", 26, "bold")
        letter_gap = 30
        total_width = letter_gap * (len(word) - 1)
        start_x = canvas_w // 2 - total_width // 2
        base_y = canvas_h // 2 + 4
        rise = 22   # pixels each letter travels upward while fading in

        def _ease_out_cubic(t):
            return 1 - (1 - t) ** 3

        def _lerp_color(c1, c2, t):
            c1 = _splash_root.winfo_rgb(c1)
            c2 = _splash_root.winfo_rgb(c2)
            r = int(c1[0] + (c2[0] - c1[0]) * t) >> 8
            g = int(c1[1] + (c2[1] - c1[1]) * t) >> 8
            b = int(c1[2] + (c2[2] - c1[2]) * t) >> 8
            return f"#{r:02x}{g:02x}{b:02x}"

        # ── Background starfield: scattered dots that twinkle throughout ──
        STAR_COUNT = 26
        star_colors = ["#3d3d5c", "#4a4a6e", "#5a5a80", "#6b5ca0"]
        stars = []
        for _ in range(STAR_COUNT):
            sx = random.randint(6, canvas_w - 6)
            sy = random.randint(4, canvas_h - 4)
            r  = random.uniform(0.8, 1.8)
            item = canvas.create_oval(sx - r, sy - r, sx + r, sy + r,
                                       fill=BG, outline="", tags="star")
            stars.append({
                "item": item, "color": random.choice(star_colors),
                "phase": random.uniform(0, 6.28), "speed": random.uniform(0.12, 0.3),
            })

        def _twinkle_frame(t_elapsed):
            """Fades each star in/out on its own sine cycle for a twinkle effect."""
            for s in stars:
                brightness = 0.5 + 0.5 * math.sin(t_elapsed * s["speed"] * 10 + s["phase"])
                brightness = max(0.0, brightness)
                color = _lerp_color(BG, s["color"], brightness)
                canvas.itemconfigure(s["item"], fill=color)

        # Fade the starfield in first, on its own, before the wordmark appears.
        _play_chime([523.25, 659.25], note_duration=0.18, volume=0.15)   # soft C5-E5 shimmer
        STAR_FADE_STEPS = 16
        for step in range(1, STAR_FADE_STEPS + 1):
            _twinkle_frame(step * 0.05)
            _splash_root.update_idletasks()
            _splash_root.update()
            time.sleep(0.02)

        elapsed = STAR_FADE_STEPS * 0.05

        # ── Phase 1: staggered slide-up + fade-in reveal, letter by letter ──
        letter_ids = []
        STEPS = 8
        for i, ch in enumerate(word):
            x = start_x + i * letter_gap
            item = canvas.create_text(x, base_y + rise, text=ch,
                                       font=font_name, fill=BG, anchor="center")
            letter_ids.append(item)

            for step in range(1, STEPS + 1):
                t = _ease_out_cubic(step / STEPS)
                y = (base_y + rise) - rise * t
                color = _lerp_color(BG, "#a684e8", t)
                canvas.coords(item, x, y)
                canvas.itemconfigure(item, fill=color)
                elapsed += 0.014
                _twinkle_frame(elapsed)
                canvas.tag_raise(item)
                _splash_root.update_idletasks()
                _splash_root.update()
                time.sleep(0.014)

            canvas.itemconfigure(item, fill="#a684e8")
            elapsed += 0.08
            _twinkle_frame(elapsed)
            _splash_root.update_idletasks()
            _splash_root.update()
            time.sleep(0.08)   # stagger before the next letter starts

        # ── Phase 2: animated glow underline sweeps in beneath the wordmark ──
        _play_chime([392.00, 523.25, 659.25], note_duration=0.1, volume=0.2)   # G4-C5-E5 rise
        line_y = base_y + 34
        glow = canvas.create_line(start_x, line_y, start_x, line_y,
                                   fill="#3ddc97", width=2, capstyle="round")
        end_x = start_x + total_width + 14
        SWEEP_STEPS = 18
        for step in range(1, SWEEP_STEPS + 1):
            t = _ease_out_cubic(step / SWEEP_STEPS)
            x2 = (start_x - 14) + (end_x - (start_x - 14)) * t
            canvas.coords(glow, start_x - 14, line_y, x2, line_y)
            elapsed += 0.02
            _twinkle_frame(elapsed)
            _splash_root.update_idletasks()
            _splash_root.update()
            time.sleep(0.02)

        for _ in range(14):
            elapsed += 0.02
            _twinkle_frame(elapsed)
            _splash_root.update_idletasks()
            _splash_root.update()
            time.sleep(0.02)

        # ── Phase 3: gradient color pulse across the full wordmark ──
        pulse_colors = ["#a684e8", "#3ddc97", "#f0c060", "#7c5cbf", "#a684e8"]
        PULSE_STEPS = 9
        for c_from, c_to in zip(pulse_colors, pulse_colors[1:]):
            for step in range(1, PULSE_STEPS + 1):
                t = step / PULSE_STEPS
                color = _lerp_color(c_from, c_to, t)
                for item in letter_ids:
                    canvas.itemconfigure(item, fill=color)
                canvas.itemconfigure(glow, fill=color)
                elapsed += 0.026
                _twinkle_frame(elapsed)
                _splash_root.update_idletasks()
                _splash_root.update()
                time.sleep(0.026)

        # ── Phase 4: sparkle burst — small stars flare bright and scatter
        # outward from the wordmark, then fade, like a shower of light ──
        _play_chime([659.25, 830.61, 987.77], note_duration=0.09, volume=0.22)   # E5-G#5-B5 sparkle
        burst_cx = start_x + total_width / 2
        burst_cy = base_y - 6
        SPARK_COUNT = 18
        sparks = []
        for _ in range(SPARK_COUNT):
            ang = random.uniform(0, 6.28318)
            dist = random.uniform(30, 95)
            tx = burst_cx + math.cos(ang) * dist
            ty = burst_cy + math.sin(ang) * dist * 0.6
            color = random.choice(["#a684e8", "#3ddc97", "#f0c060", "#ffffff"])
            item = canvas.create_oval(burst_cx - 1.5, burst_cy - 1.5,
                                       burst_cx + 1.5, burst_cy + 1.5,
                                       fill=color, outline="", tags="spark")
            sparks.append({"item": item, "tx": tx, "ty": ty, "color": color})

        BURST_STEPS = 16
        for step in range(1, BURST_STEPS + 1):
            t = _ease_out_cubic(step / BURST_STEPS)
            fade = 1.0 - (step / BURST_STEPS) ** 2   # sparks dim as they travel out
            for sp in sparks:
                sx = burst_cx + (sp["tx"] - burst_cx) * t
                sy = burst_cy + (sp["ty"] - burst_cy) * t
                sz = 1.5 * fade + 0.3
                col = _lerp_color(BG, sp["color"], max(0.0, fade))
                canvas.coords(sp["item"], sx - sz, sy - sz, sx + sz, sy + sz)
                canvas.itemconfigure(sp["item"], fill=col)
            elapsed += 0.02
            _twinkle_frame(elapsed)
            _splash_root.update_idletasks()
            _splash_root.update()
            time.sleep(0.02)

        # Settle back to the accent color and hold on the finished word.
        for item in letter_ids:
            canvas.itemconfigure(item, fill="#a684e8")
        canvas.itemconfigure(glow, fill="#a684e8")
        for _ in range(20):
            elapsed += 0.035
            _twinkle_frame(elapsed)
            _splash_root.update_idletasks()
            _splash_root.update()
            time.sleep(0.035)

        try:
            _splash_root.attributes("-topmost", False)
        except Exception:
            pass
        print("[Splash] outro animation finished")
    except Exception as e:
        print(f"[Splash] outro animation error: {e}")


def _play_extended_intro_animation():
    """
    Opt-in ~8 second, full-screen cinematic intro, shown instead of the
    short splash outro animation when the user checked "Play extended
    intro animation" on the startup mode screen. Runs in its own
    full-screen borderless Toplevel (separate from the small splash
    window) so it can fill the entire display. Fully synchronous, same
    approach as the short animation: time.sleep + root.update() in a loop.
    """
    if _host_root is None:
        print("[Intro] extended animation skipped — no host root")
        return

    try:
        import random
        import math
        random.seed()

        print("[Intro] playing extended ~8s intro animation...")

        BG = "#0a0a14"
        win = tk.Toplevel(_host_root)
        win.overrideredirect(True)
        win.configure(bg=BG)
        if SELECTED_MONITOR:
            sw, sh = SELECTED_MONITOR["width"], SELECTED_MONITOR["height"]
            mx, my = SELECTED_MONITOR["left"], SELECTED_MONITOR["top"]
        else:
            sw = win.winfo_screenwidth()
            sh = win.winfo_screenheight()
            mx, my = 0, 0
        win.geometry(f"{sw}x{sh}+{mx}+{my}")
        win.attributes("-topmost", True)
        win.lift()
        win.focus_force()

        canvas = tk.Canvas(win, width=sw, height=sh, bg=BG,
                            highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        win.update_idletasks()
        win.update()

        cx, cy = sw // 2, sh // 2

        def _ease_out_cubic(t):
            return 1 - (1 - t) ** 3

        def _ease_in_out(t):
            return 3 * t * t - 2 * t * t * t

        def _lerp_color(c1, c2, t):
            r1 = win.winfo_rgb(c1)
            r2 = win.winfo_rgb(c2)
            r = int(r1[0] + (r2[0] - r1[0]) * t) >> 8
            g = int(r1[1] + (r2[1] - r1[1]) * t) >> 8
            b = int(r1[2] + (r2[2] - r1[2]) * t) >> 8
            return f"#{r:02x}{g:02x}{b:02x}"

        def _tick(delay=0.02):
            win.update_idletasks()
            win.update()
            time.sleep(delay)

        # ── Layer 0: deep parallax starfield across the whole screen ──
        STAR_COUNT = 140
        star_colors = ["#3d3d5c", "#4a4a6e", "#5a5a80", "#6b5ca0", "#7c5cbf"]
        stars = []
        for _ in range(STAR_COUNT):
            sx = random.randint(0, sw)
            sy = random.randint(0, sh)
            depth = random.uniform(0.3, 1.0)   # closer stars (higher depth) drift faster & brighter
            r = 0.6 + depth * 1.8
            item = canvas.create_oval(sx - r, sy - r, sx + r, sy + r,
                                       fill=BG, outline="", tags="star")
            stars.append({
                "item": item, "x": sx, "y": sy, "depth": depth,
                "color": random.choice(star_colors),
                "phase": random.uniform(0, 6.28), "speed": random.uniform(0.1, 0.35),
            })

        def _twinkle_frame(t_elapsed):
            for s in stars:
                brightness = 0.5 + 0.5 * math.sin(t_elapsed * s["speed"] * 10 + s["phase"])
                brightness = max(0.0, brightness) * (0.5 + 0.5 * s["depth"])
                color = _lerp_color(BG, s["color"], brightness)
                canvas.itemconfigure(s["item"], fill=color)

        elapsed = 0.0

        # ── Phase 1: starfield fades in (~1.5s) ──
        _play_chime([392.00, 523.25], note_duration=0.25, volume=0.15)
        for step in range(1, 46):
            elapsed += 0.036
            _twinkle_frame(elapsed)
            _tick(0.036)

        # ── Phase 2: expanding concentric rings pulse outward from center
        # (~2.5s), like a shockwave announcing the logo is coming ──
        _play_chime([261.63, 329.63, 392.00], note_duration=0.14, volume=0.18)
        RING_WAVES = 3
        ring_colors = ["#7c5cbf", "#a684e8", "#3ddc97"]
        for wave in range(RING_WAVES):
            ring = canvas.create_oval(cx, cy, cx, cy, outline=ring_colors[wave % len(ring_colors)],
                                       width=3, tags="ring")
            RING_STEPS = 22
            max_r = min(sw, sh) * 0.42
            for step in range(1, RING_STEPS + 1):
                t = _ease_out_cubic(step / RING_STEPS)
                r = max_r * t
                fade = 1.0 - t
                color = _lerp_color(BG, ring_colors[wave % len(ring_colors)], fade)
                canvas.coords(ring, cx - r, cy - r, cx + r, cy + r)
                canvas.itemconfigure(ring, outline=color)
                elapsed += 0.018
                _twinkle_frame(elapsed)
                _tick(0.018)
            canvas.delete(ring)

        # ── Phase 3: orbiting particles spiral inward and settle into a
        # ring around where the wordmark will appear (~2s) ──
        ORBIT_COUNT = 24
        orbit_radius = min(sw, sh) * 0.22
        orbit_particles = []
        for i in range(ORBIT_COUNT):
            ang = (i / ORBIT_COUNT) * 2 * math.pi
            start_dist = random.uniform(max(sw, sh) * 0.5, max(sw, sh) * 0.7)
            sx = cx + math.cos(ang) * start_dist
            sy = cy + math.sin(ang) * start_dist
            color = random.choice(["#a684e8", "#3ddc97", "#f0c060"])
            item = canvas.create_oval(sx - 2.5, sy - 2.5, sx + 2.5, sy + 2.5,
                                       fill=color, outline="", tags="orbit")
            orbit_particles.append({"item": item, "angle": ang, "color": color})

        SPIRAL_STEPS = 32
        for step in range(1, SPIRAL_STEPS + 1):
            t = _ease_out_cubic(step / SPIRAL_STEPS)
            for p in orbit_particles:
                ang = p["angle"] + t * math.pi * 1.4   # spins in while closing distance
                dist = orbit_radius + (1 - t) * (min(sw, sh) * 0.35)
                px = cx + math.cos(ang) * dist
                py = cy + math.sin(ang) * dist * 0.55   # slightly flattened ellipse orbit
                canvas.coords(p["item"], px - 2.5, py - 2.5, px + 2.5, py + 2.5)
                p["last_pos"] = (px, py)
            elapsed += 0.02
            _twinkle_frame(elapsed)
            _tick(0.02)

        # ── Phase 4: big wordmark reveal, letter by letter (~2.5s) ──
        _play_chime([392.00, 523.25, 659.25], note_duration=0.1, volume=0.2)
        word = "NEXOVATIVE"
        font_size = max(28, min(64, sw // 16))
        font_name = ("Segoe UI", font_size, "bold")
        letter_gap = font_size * 1.15
        total_width = letter_gap * (len(word) - 1)
        start_x = cx - total_width / 2
        base_y = cy
        rise = 40

        letter_ids = []
        STEPS = 7
        for i, ch in enumerate(word):
            x = start_x + i * letter_gap
            item = canvas.create_text(x, base_y + rise, text=ch,
                                       font=font_name, fill=BG, anchor="center")
            letter_ids.append(item)
            for step in range(1, STEPS + 1):
                t = _ease_out_cubic(step / STEPS)
                y = (base_y + rise) - rise * t
                color = _lerp_color(BG, "#a684e8", t)
                canvas.coords(item, x, y)
                canvas.itemconfigure(item, fill=color)
                elapsed += 0.012
                _twinkle_frame(elapsed)
                # keep orbiting particles alive and spinning during the reveal
                for p in orbit_particles:
                    p["angle"] += 0.05
                    px = cx + math.cos(p["angle"]) * orbit_radius
                    py = cy + math.sin(p["angle"]) * orbit_radius * 0.55
                    canvas.coords(p["item"], px - 2.5, py - 2.5, px + 2.5, py + 2.5)
                canvas.tag_raise(item)
                _tick(0.012)
            canvas.itemconfigure(item, fill="#a684e8")
            elapsed += 0.07
            _twinkle_frame(elapsed)
            _tick(0.07)

        # ── Phase 5: glow underline sweep (~0.6s) ──
        _play_chime([440.00, 554.37, 659.25], note_duration=0.1, volume=0.2)
        line_y = base_y + font_size * 0.9
        glow = canvas.create_line(start_x, line_y, start_x, line_y,
                                   fill="#3ddc97", width=3, capstyle="round")
        end_x = start_x + total_width + 18
        SWEEP_STEPS = 24
        for step in range(1, SWEEP_STEPS + 1):
            t = _ease_out_cubic(step / SWEEP_STEPS)
            x2 = (start_x - 18) + (end_x - (start_x - 18)) * t
            canvas.coords(glow, start_x - 18, line_y, x2, line_y)
            elapsed += 0.02
            _twinkle_frame(elapsed)
            _tick(0.02)

        # ── Phase 6: orbiting particles collapse into the underline as a
        # trail of light, then the ring disperses (~1.5s) ──
        COLLAPSE_STEPS = 18
        for step in range(1, COLLAPSE_STEPS + 1):
            t = _ease_in_out(step / COLLAPSE_STEPS)
            for p in orbit_particles:
                p["angle"] += 0.06
                orbit_x = cx + math.cos(p["angle"]) * orbit_radius
                orbit_y = cy + math.sin(p["angle"]) * orbit_radius * 0.55
                target_x = start_x + random.uniform(0, total_width)
                target_y = line_y
                px = orbit_x + (target_x - orbit_x) * t
                py = orbit_y + (target_y - orbit_y) * t
                size = max(0.5, 2.5 * (1 - t))
                canvas.coords(p["item"], px - size, py - size, px + size, py + size)
            elapsed += 0.02
            _twinkle_frame(elapsed)
            _tick(0.02)
        for p in orbit_particles:
            canvas.delete(p["item"])

        # ── Phase 7: extended gradient pulse across the wordmark (~2.5s) ──
        pulse_colors = ["#a684e8", "#3ddc97", "#f0c060", "#7c5cbf", "#3ddc97", "#a684e8"]
        PULSE_STEPS = 12
        for c_from, c_to in zip(pulse_colors, pulse_colors[1:]):
            for step in range(1, PULSE_STEPS + 1):
                t = step / PULSE_STEPS
                color = _lerp_color(c_from, c_to, t)
                for item in letter_ids:
                    canvas.itemconfigure(item, fill=color)
                canvas.itemconfigure(glow, fill=color)
                elapsed += 0.02
                _twinkle_frame(elapsed)
                _tick(0.02)

        # ── Phase 8: big finale sparkle burst (~1.2s) ──
        _play_chime([659.25, 830.61, 987.77, 1174.66], note_duration=0.09, volume=0.24)
        burst_cx, burst_cy = cx, base_y - font_size * 0.3
        SPARK_COUNT = 60
        sparks = []
        for _ in range(SPARK_COUNT):
            ang = random.uniform(0, 2 * math.pi)
            dist = random.uniform(sw * 0.08, sw * 0.28)
            tx = burst_cx + math.cos(ang) * dist
            ty = burst_cy + math.sin(ang) * dist * 0.6
            color = random.choice(["#a684e8", "#3ddc97", "#f0c060", "#ffffff"])
            item = canvas.create_oval(burst_cx - 2, burst_cy - 2, burst_cx + 2, burst_cy + 2,
                                       fill=color, outline="", tags="spark")
            sparks.append({"item": item, "tx": tx, "ty": ty, "color": color})

        BURST_STEPS = 24
        for step in range(1, BURST_STEPS + 1):
            t = _ease_out_cubic(step / BURST_STEPS)
            fade = 1.0 - (step / BURST_STEPS) ** 2
            for sp in sparks:
                sx = burst_cx + (sp["tx"] - burst_cx) * t
                sy = burst_cy + (sp["ty"] - burst_cy) * t
                sz = 2.5 * fade + 0.3
                col = _lerp_color(BG, sp["color"], max(0.0, fade))
                canvas.coords(sp["item"], sx - sz, sy - sz, sx + sz, sy + sz)
                canvas.itemconfigure(sp["item"], fill=col)
            elapsed += 0.02
            _twinkle_frame(elapsed)
            _tick(0.02)

        # Settle back to the accent color and hold on the finished word.
        for item in letter_ids:
            canvas.itemconfigure(item, fill="#a684e8")
        canvas.itemconfigure(glow, fill="#3ddc97")
        for _ in range(30):
            elapsed += 0.03
            _twinkle_frame(elapsed)
            _tick(0.03)

        # ── Phase 9: fade to black, then close (~1s) ──
        # Simple fade: layer increasingly opaque black rectangles using
        # stipple patterns, each one darker than the last.
        stipple_steps = ["gray12", "gray25", "gray50", "gray75", None]
        for stipple in stipple_steps:
            canvas.create_rectangle(0, 0, sw, sh, fill="#000000",
                                     outline="", stipple=stipple if stipple else "")
            _tick(0.06)

        try:
            win.attributes("-topmost", False)
        except Exception:
            pass
        win.destroy()
        print("[Intro] extended animation finished")
    except Exception as e:
        print(f"[Intro] extended animation error: {e}")
        try:
            win.destroy()
        except Exception:
            pass   # win may not have been created yet if the failure happened early


def _close_splash():
    global _splash_root
    if _splash_root:
        try:
            _splash_root.destroy()   # destroy only the Toplevel splash
        except Exception:
            pass
        _splash_root = None
    # _host_root stays alive — it becomes the main window

# ── Show splash immediately ──
_create_splash()
_update_splash(5, "Loading GUI...")
_check_for_update()   # checks GitHub, offers to open the repo page if a newer version exists

# ========================= HEAVY IMPORTS =========================
# These run AFTER the splash is visible.

_update_splash(10, "Importing signal patcher...")

# pytchat fix: signal.signal() only works on main thread.
# When the bot runs in a worker thread, patch it to be a no-op.
_orig_signal = _signal_module.signal
def _safe_signal(sig, handler):
    if _threading_module.current_thread() is _threading_module.main_thread():
        return _orig_signal(sig, handler)
_signal_module.signal = _safe_signal

_update_splash(20, "Importing pytchat...")
try:
    import pytchat
    _PYTCHAT_OK = True
except ImportError:
    pytchat = None
    _PYTCHAT_OK = False
    print("[Startup] pytchat not installed — YouTube chat reading will be disabled. Run: pip install pytchat")

try:
    from chat_downloader import ChatDownloader as _ChatDownloaderLib
    _CHAT_DOWNLOADER_OK = True
except ImportError:
    _ChatDownloaderLib = None
    _CHAT_DOWNLOADER_OK = False
    print("[Startup] chat-downloader not installed — that chat backend will be unavailable. "
          "Run: pip install chat-downloader")

try:
    from googleapiclient.discovery import build as _google_api_build
    _GOOGLE_API_OK = True
except ImportError:
    _google_api_build = None
    _GOOGLE_API_OK = False
    print("[Startup] google-api-python-client not installed — the official YouTube Data API "
          "chat backend will be unavailable. Run: pip install google-api-python-client")


# ========================= YOUTUBE CHAT SOURCE ADAPTER =========================
# Every part of the script that reads YouTube live chat goes through this
# adapter — NOTHING outside this block ever calls pytchat directly.
#
# Why: pytchat hasn't been meaningfully updated in years, and it works by
# reverse-engineering YouTube's internal (undocumented) live-chat data
# format. If YouTube changes that format, pytchat can break instantly and
# completely, with no fix available from upstream.
#
# Because every reader in this script (Real PC's chat listener, the main
# bot, the multi-stream secondary bot) used to call pytchat.create() /
# .is_alive() / .terminate() / .get().sync_items() directly, a pytchat
# break would have meant hunting down and fixing the same broken calls in
# several different places. With this adapter, swapping pytchat for a
# replacement library (or a hand-rolled scraper) later is a change to
# ONE class — YouTubeChatSource — instead of a script-wide rewrite.
# (CHAT_BACKEND_PREFERENCE, CHAT_BACKEND_PREFERENCE_FILE,
#  load_chat_backend_preference() and save_chat_backend_preference() are
#  defined near the top of the file — splash startup needs them before
#  this point in the module.)


class ChatMessage:
    """A single chat message, normalized so callers never touch pytchat's
    own message-object shape directly."""
    __slots__ = ("id", "author_name", "is_owner", "text")

    def __init__(self, id, author_name, is_owner, text):
        self.id          = id
        self.author_name = author_name
        self.is_owner    = is_owner
        self.text        = text


class YouTubeChatSource:
    """
    Reads YouTube live chat through up to three backends, tried in order
    of reliability:

      1. Official YouTube Data API v3 — used only if an API key is
         configured. This is the only backend Google actually guarantees
         to keep working, since it's a supported, documented API rather
         than a reverse-engineered read of YouTube's internal chat
         format. Costs YouTube API quota per poll.
      2. chat-downloader — unofficial, no API key needed.
      3. pytchat — unofficial, no API key needed.

    Backends 2 and 3 both work by reverse-engineering YouTube's internal,
    undocumented chat data format, so either one can break instantly and
    completely if YouTube changes that format, with no guarantee of a
    fix from upstream. Having two of them side by side means one
    breaking doesn't necessarily take both down at once, and connect()
    automatically falls through to the next available backend.

    Every reader in the script talks only to this class — never to
    pytchat / chat_downloader / googleapiclient directly. If any backend
    breaks or a better one comes along later, only this class needs to
    change.
    """

    def __init__(self, video_id: str, api_key: str = ""):
        self.video_id   = video_id
        self.api_key    = (api_key or "").strip()
        self.backend_name = None   # "official" / "chat_downloader" / "pytchat" / None

        # Official API state
        self._official_service         = None
        self._official_live_chat_id    = None
        self._official_next_page_token = None

        # chat-downloader state — its iterator blocks waiting for each
        # message, so it runs in its own thread feeding a queue that
        # get_messages() can drain without blocking the caller.
        self._cd_chat       = None
        self._cd_queue      = None
        self._cd_thread     = None
        self._cd_stop_event = None

        # pytchat state
        self._pytchat_backend = None

    # ------------------------------------------------------------ connect

    def connect(self) -> bool:
        """
        (Re)connects using whichever backend(s) CHAT_BACKEND_PREFERENCE
        allows. "auto" (default) tries official -> chat_downloader ->
        pytchat in order, falling through on failure. Any specific
        choice ("official" / "chat_downloader" / "pytchat") tries ONLY
        that backend — no silent fallback — since the whole point of
        picking one explicitly is to control what's actually being used.
        """
        self.terminate()
        pref = CHAT_BACKEND_PREFERENCE if CHAT_BACKEND_PREFERENCE in (
            "auto", "official", "chat_downloader", "pytchat") else "auto"

        if pref == "official":
            if self.api_key and self._connect_official():
                self.backend_name = "official"
                return True
            if not self.api_key:
                print("[ChatSource] Preference is 'official' but no API key is set.")
            print(f"[ChatSource] Official API connect failed ({self.video_id}) — "
                  "not falling back, per preference.")
            self.backend_name = None
            return False

        if pref == "chat_downloader":
            if self._connect_chat_downloader():
                self.backend_name = "chat_downloader"
                return True
            print(f"[ChatSource] chat-downloader connect failed ({self.video_id}) — "
                  "not falling back, per preference.")
            self.backend_name = None
            return False

        if pref == "pytchat":
            if self._connect_pytchat():
                self.backend_name = "pytchat"
                return True
            print(f"[ChatSource] pytchat connect failed ({self.video_id}) — "
                  "not falling back, per preference.")
            self.backend_name = None
            return False

        # pref == "auto" — try each in order, falling through on failure.
        if self.api_key and self._connect_official():
            self.backend_name = "official"
            return True
        if self.api_key:
            print("[ChatSource] Official API failed — falling back to chat-downloader.")

        if self._connect_chat_downloader():
            self.backend_name = "chat_downloader"
            return True
        print("[ChatSource] chat-downloader unavailable — falling back to pytchat.")

        if self._connect_pytchat():
            self.backend_name = "pytchat"
            return True

        print(f"[ChatSource] All backends failed to connect ({self.video_id}).")
        self.backend_name = None
        return False

    def _connect_official(self) -> bool:
        if not _GOOGLE_API_OK:
            print("[ChatSource] google-api-python-client not installed — skipping official API.")
            return False
        try:
            self._official_service = _google_api_build(
                "youtube", "v3", developerKey=self.api_key, cache_discovery=False)
            video_resp = self._official_service.videos().list(
                part="liveStreamingDetails", id=self.video_id
            ).execute()
            items = video_resp.get("items", [])
            if not items:
                print(f"[ChatSource] Official API: video '{self.video_id}' not found.")
                self._official_service = None
                return False
            chat_id = items[0].get("liveStreamingDetails", {}).get("activeLiveChatId")
            if not chat_id:
                print(f"[ChatSource] Official API: video '{self.video_id}' has no active live chat.")
                self._official_service = None
                return False
            self._official_live_chat_id    = chat_id
            self._official_next_page_token = None
            return True
        except Exception as e:
            print(f"[ChatSource] Official API connect failed: {e}")
            self._official_service = None
            return False

    def _connect_chat_downloader(self) -> bool:
        if not _CHAT_DOWNLOADER_OK:
            print("[ChatSource] chat-downloader not installed — skipping.")
            return False
        try:
            url = f"https://www.youtube.com/watch?v={self.video_id}"
            self._cd_chat       = _ChatDownloaderLib().get_chat(url)
            self._cd_queue      = queue.Queue()
            self._cd_stop_event = threading.Event()
            self._cd_thread = threading.Thread(
                target=self._cd_pump, daemon=True,
                name=f"cd_pump_{self.video_id}")
            self._cd_thread.start()
            return True
        except Exception as e:
            print(f"[ChatSource] chat-downloader connect failed: {e}")
            self._cd_chat = None
            return False

    def _cd_pump(self):
        """Background thread: chat-downloader's iterator blocks waiting for
        each message to arrive, so it needs a dedicated thread feeding a
        queue that get_messages() can drain without blocking the caller."""
        try:
            for item in self._cd_chat:
                if self._cd_stop_event.is_set():
                    break
                self._cd_queue.put(item)
        except Exception as e:
            if not self._cd_stop_event.is_set():
                print(f"[ChatSource] chat-downloader stream ended: {e}")
        finally:
            self._cd_queue.put(None)   # signals end-of-stream to is_alive()/get_messages()

    def _connect_pytchat(self) -> bool:
        if not _PYTCHAT_OK:
            print("[ChatSource] pytchat not installed — skipping.")
            return False
        try:
            self._pytchat_backend = pytchat.create(video_id=self.video_id)
            return True
        except Exception as e:
            print(f"[ChatSource] pytchat connect failed: {e}")
            self._pytchat_backend = None
            return False

    # ---------------------------------------------------------- is_alive

    def is_alive(self) -> bool:
        try:
            if self.backend_name == "official":
                return self._official_service is not None
            elif self.backend_name == "chat_downloader":
                return bool(self._cd_thread and self._cd_thread.is_alive())
            elif self.backend_name == "pytchat":
                return bool(self._pytchat_backend and self._pytchat_backend.is_alive())
        except Exception:
            return False
        return False

    # ------------------------------------------------------ get_messages

    def get_messages(self):
        """Returns a list of ChatMessage for whatever arrived since the last call."""
        if self.backend_name == "official":
            return self._get_messages_official()
        elif self.backend_name == "chat_downloader":
            return self._get_messages_chat_downloader()
        elif self.backend_name == "pytchat":
            return self._get_messages_pytchat()
        return []

    def _get_messages_official(self):
        try:
            resp = self._official_service.liveChatMessages().list(
                liveChatId=self._official_live_chat_id,
                part="snippet,authorDetails",
                pageToken=self._official_next_page_token,
            ).execute()
        except Exception as e:
            print(f"[ChatSource] Official API poll error: {e}")
            return []

        self._official_next_page_token = resp.get("nextPageToken")

        # Respect YouTube's suggested polling interval (capped at 10s) so
        # this doesn't burn through the daily API quota faster than needed.
        poll_ms = resp.get("pollingIntervalMillis", 5000)
        time.sleep(min(max(poll_ms, 1000), 10000) / 1000)

        out = []
        for item in resp.get("items", []):
            snippet = item.get("snippet", {}) or {}
            author  = item.get("authorDetails", {}) or {}
            out.append(ChatMessage(
                id=item.get("id"),
                author_name=author.get("displayName", ""),
                is_owner=bool(author.get("isChatOwner", False)),
                text=snippet.get("displayMessage", "") or "",
            ))
        return out

    def _get_messages_chat_downloader(self):
        out = []
        while True:
            try:
                item = self._cd_queue.get_nowait()
            except queue.Empty:
                break
            if item is None:
                # end-of-stream sentinel from _cd_pump — put it back so
                # is_alive() logic (thread-based) still reflects reality,
                # nothing further to read this round.
                break
            try:
                author = item.get("author", {}) or {}
                # NOTE: chat-downloader doesn't expose a dedicated
                # "is channel owner" boolean for YouTube — this infers it
                # from the author's badge tooltips, which is the best
                # signal available. Verify against a live stream if exact
                # owner detection matters for your use case.
                is_owner = any(
                    "owner" in (b.get("title", "") or "").lower()
                    for b in (author.get("badges", []) or [])
                )
                out.append(ChatMessage(
                    id=item.get("message_id"),
                    author_name=author.get("name", "") or "",
                    is_owner=is_owner,
                    text=item.get("message", "") or "",
                ))
            except Exception as e:
                print(f"[ChatSource] Skipped malformed message: {e}")
        return out

    def _get_messages_pytchat(self):
        if not self._pytchat_backend:
            return []
        items = self._pytchat_backend.get().sync_items()
        out = []
        for item in items:
            try:
                out.append(ChatMessage(
                    id=getattr(item, "id", None),
                    author_name=item.author.name,
                    is_owner=getattr(item.author, "isChatOwner", False),
                    text=item.message,
                ))
            except Exception as e:
                print(f"[ChatSource] Skipped malformed message: {e}")
        return out

    # ----------------------------------------------------------- cleanup

    def terminate(self):
        self._official_service         = None
        self._official_live_chat_id    = None
        self._official_next_page_token = None

        if self._cd_stop_event:
            self._cd_stop_event.set()
        if self._cd_thread and self._cd_thread.is_alive():
            self._cd_thread.join(timeout=1)
        self._cd_chat   = None
        self._cd_queue  = None
        self._cd_thread = None
        self._cd_stop_event = None

        if self._pytchat_backend:
            try:
                self._pytchat_backend.terminate()
            except Exception:
                pass
        self._pytchat_backend = None

        self.backend_name = None

_update_splash(35, "Importing VirtualBox API...")
try:
    from vboxapi import VirtualBoxManager
    _VBOXAPI_OK = True
except ImportError:
    VirtualBoxManager = None
    _VBOXAPI_OK = False
    print("[Startup] vboxapi not installed — VirtualBox mouse/session control will be disabled. "
          "Install the VirtualBox SDK for your Python environment.")

_update_splash(50, "Importing system libraries...")
import threading
import queue
import collections
import re
try:
    import win32com.client
    _WIN32COM_OK = True
except ImportError:
    win32com = None
    _WIN32COM_OK = False
    print("[Startup] pywin32 not installed — text-to-speech (SAPI) will be disabled. Run: pip install pywin32")
import http.server
import socketserver
import urllib.request
import urllib.error
from tkinter import ttk, scrolledtext, messagebox

_update_splash(65, "Importing tray & notification libraries...")

# ── System tray & toast notifications ──
try:
    from plyer import notification as _plyer_notification
    _PLYER_OK = True
except ImportError:
    _PLYER_OK = False
    print("[Notify] plyer not installed — toast notifications disabled. Run: pip install plyer")

try:
    import pystray
    from PIL import Image, ImageDraw
    _PYSTRAY_OK = True
except ImportError:
    _PYSTRAY_OK = False
    print("[Tray] pystray/Pillow not installed — system tray disabled. Run: pip install pystray pillow")

try:
    import pyautogui
    pyautogui.FAILSAFE   = False  # off by default — moving the mouse to a screen corner (e.g. via !move) no longer aborts the script
    pyautogui.PAUSE      = 0.05   # small delay between actions for stability
    _PYAUTOGUI_OK = True
except ImportError:
    pyautogui     = None
    _PYAUTOGUI_OK = False
    print("[RealPC] pyautogui not installed — Real PC Control tab will show install prompt. "
          "Run: pip install pyautogui")

try:
    import psutil
    _PSUTIL_OK = True
except ImportError:
    psutil     = None
    _PSUTIL_OK = False
    print("[SysMonitor] psutil not installed — CPU/RAM usage display and Lite Mode "
          "recommendation will be disabled. Run: pip install psutil")

_update_splash(80, "Initializing VirtualBox manager...")


# ========================= CUSTOM COMMANDS =========================
CUSTOM_COMMANDS_FILE = "custom_commands.json"
custom_commands = {}  # {"!bubbles": [{"action": "combo", "args": "win+r"}, ...]}

# ========================= NOTIFICATIONS & TRAY =========================
_tray_icon   = None   # pystray.Icon instance
_tray_thread = None
_gui_root    = None   # set by GUI after root is created

def notify(title, message, timeout=4):
    """Send a Windows toast notification (non-blocking)."""
    def _send():
        if _PLYER_OK:
            try:
                _plyer_notification.notify(
                    title=title,
                    message=message,
                    app_name="VirtualBox Chat Bot",
                    timeout=timeout,
                )
            except Exception as e:
                print(f"[Notify] Error: {e}")
        else:
            print(f"[Notify] {title}: {message}")
    threading.Thread(target=_send, daemon=True).start()

def _make_tray_image():
    """Generate a simple purple icon for the system tray."""
    size = 64
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, size - 4, size - 4], fill=(124, 92, 191, 255))
    draw.rectangle([28, 18, 36, 42], fill="white")
    draw.rectangle([28, 46, 36, 54], fill="white")
    return img

def _show_gui_from_tray(icon, item):
    """Called from tray menu — restore the GUI window."""
    if _gui_root:
        _gui_root.after(0, _gui_root.deiconify)
        _gui_root.after(0, _gui_root.lift)

def _exit_from_tray(icon, item):
    """Called from tray menu — stop bot and kill the entire process."""
    bot_stop_event.set()
    icon.stop()
    if _gui_root:
        _gui_root.after(0, _gui_root.destroy)
    # Give destroy a moment then hard-exit so nothing lingers
    def _hard_exit():
        time.sleep(0.5)
        os._exit(0)
    threading.Thread(target=_hard_exit, daemon=True).start()

def start_tray_icon():
    """Start the system tray icon in a background thread."""
    global _tray_icon, _tray_thread
    if not _PYSTRAY_OK:
        return
    if _tray_icon is not None:
        return  # already running
    menu = pystray.Menu(
        pystray.MenuItem("Show GUI",        _show_gui_from_tray, default=True),
        pystray.MenuItem("Exit",            _exit_from_tray),
    )
    _tray_icon = pystray.Icon(
        name  = "VBoxChatBot",
        icon  = _make_tray_image(),
        title = "VirtualBox Chat Bot",
        menu  = menu,
    )
    _tray_thread = threading.Thread(target=_tray_icon.run, daemon=True)
    _tray_thread.start()
    print("[Tray] System tray icon started.")

def stop_tray_icon():
    """Remove the tray icon."""
    global _tray_icon
    if _tray_icon:
        try:
            _tray_icon.stop()
        except Exception:
            pass
        _tray_icon = None

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

def execute_custom_command(trigger):
    steps = custom_commands.get(trigger, [])
    print(f"[CustomCmd] Executing '{trigger}' ({len(steps)} steps)")
    for step in steps:
        action = step.get("action", "").lower().strip()
        args   = step.get("args",   "").strip()
        try:
            if action == "combo":
                keys = [k.strip().lower() for k in args.replace("+", " ").split()]
                send_combo(keys)
            elif action in ("type", "text", "say"):
                send_keyboard(args)
            elif action in ("send", "sendenter", "typeenter", "sendline"):
                send_keyboard(args)
                time.sleep(0.05)
                send_special_enter()
            elif action == "enter":
                send_special_enter()
            elif action in ("key", "press"):
                k = args.lower().strip()
                if k in SCANCODES:
                    send_scancode(SCANCODES[k][0])
                    time.sleep(0.02)
                    send_scancode(SCANCODES[k][1])
                else:
                    send_keyboard(k)
            elif action in ("keydown", "hold"):
                # args can be just a key name ("shift") or "key duration"
                # ("shift 2") to auto-release after N seconds. Whatever is
                # asked for is capped at 5s — this key WILL be released
                # automatically even if no separate "release"/"keyup" step
                # ever follows, so a forgotten (or malicious) custom
                # command can never leave a key stuck down in the VM
                # indefinitely.
                parts = args.lower().split()
                k = parts[0].strip() if parts else ""
                try:
                    hold_seconds = float(parts[1]) if len(parts) > 1 else 1.0
                except ValueError:
                    hold_seconds = 1.0
                hold_seconds = max(0.05, min(hold_seconds, 5.0))

                if k in SCANCODES:
                    send_scancode(SCANCODES[k][0])
                    _schedule_key_auto_release(k, hold_seconds)
            elif action in ("keyup", "release"):
                k = args.lower().strip()
                if k in SCANCODES:
                    _cancel_key_auto_release(k)
                    send_scancode(SCANCODES[k][1])
            elif action in ("wait", "pause", "delay"):
                try:
                    ms = float(args)
                    time.sleep(max(0, min(ms, 5000)) / 1000.0)
                except ValueError:
                    time.sleep(0.5)
            elif action in ("click", "lclick"):
                handle_mouse("click", args)
            elif action in ("rclick", "rightclick"):
                handle_mouse("rclick", args)
            elif action in ("mclick", "middleclick"):
                handle_mouse("mclick", args)
            elif action in ("move", "mouse", "mv"):
                handle_mouse("move", args)
            elif action in ("abs", "cursor", "moveabs"):
                handle_mouse("abs", args)
            elif action in ("drag", "dragrel"):
                handle_mouse("drag", args)
            elif action in ("dragabs", "drag_absolute"):
                handle_mouse("dragabs", args)
            elif action in ("holdclick", "holdrclick"):
                handle_mouse(action, args)
            elif action in ("scroll", "wheel"):
                handle_mouse("scroll", args)
            print(f"[CustomCmd]   → {action} {args}")
        except Exception as e:
            print(f"[CustomCmd] Step error ({action} {args}): {e}")

# ========================= OVERLAY SYSTEM =========================
overlay_data = {"chat": [], "running_command": "", "viewers": None, "likes": None, "subscribers": None,
                 "revert_cooldown_remaining": 0, "restart_cooldown_remaining": 0}
seen_message_ids = set()
last_write_time = 0

def update_overlay(author=None, message=None, running=None, msg_id=None):
    global last_write_time
    changed = False
    current_time = time.time()
    if running is not None and overlay_data.get("running_command") != running:
        overlay_data["running_command"] = running
        changed = True
    if author and message and msg_id and msg_id not in seen_message_ids:
        seen_message_ids.add(msg_id)
        overlay_data["chat"].append({"author": str(author), "message": str(message), "id": str(msg_id)})
        if len(overlay_data["chat"]) > 20:
            removed = overlay_data["chat"].pop(0)
            seen_message_ids.discard(removed.get("id"))
        changed = True
    # Cooldown countdowns — read fresh every call so the overlay writer
    # below (update_overlay_cooldowns) can push updates every second
    # without needing its own separate JSON file or its own polling
    # target in the browser; chat.html reads these straight out of the
    # same overlay.json it's already fetching for chat messages.
    revert_remaining = max(0, int(revert_cooldown_until - current_time))
    restart_remaining = max(0, int(restart_cooldown_until - current_time))
    if overlay_data.get("revert_cooldown_remaining") != revert_remaining:
        overlay_data["revert_cooldown_remaining"] = revert_remaining
        changed = True
    if overlay_data.get("restart_cooldown_remaining") != restart_remaining:
        overlay_data["restart_cooldown_remaining"] = restart_remaining
        changed = True
    if changed and (current_time - last_write_time > 0.15):
        try:
            with open("overlay.json", "w", encoding="utf-8") as f:
                json.dump(overlay_data, f, ensure_ascii=False, separators=(',', ':'))
            last_write_time = current_time
        except Exception as e:
            print(f"[Overlay Error] {e}")

def _cooldown_overlay_ticker():
    """
    Background thread: calls update_overlay() once a second purely so the
    cooldown countdown fields stay fresh on overlay.json even when chat
    is quiet (update_overlay is otherwise only called when a chat message
    or running-command change happens). Started once at bot startup.
    """
    while not bot_stop_event.is_set():
        update_overlay()
        if bot_stop_event.wait(1.0):
            break

# def fetch_youtube_stats():
  #  """Background thread: polls YouTube Data API v3 every 30s for live viewer/like/subscriber counts."""
   # import urllib.request
   # while True:
      #  try:
       #     if YOUTUBE_API_KEY and VIDEO_ID:
                # Live viewer count + like count from video resource
            #    url_video = (
                 #   f"https://www.googleapis.com/youtube/v3/videos"
                 #   f"?part=statistics,liveStreamingDetails&id={VIDEO_ID}&key={YOUTUBE_API_KEY}"
             #   )
             #   with urllib.request.urlopen(url_video, timeout=10) as r:
                #    vdata = json.loads(r.read().decode())
               # items = vdata.get("items", [])
               # if items:
               #     stats = items[0].get("statistics", {})
               #     live  = items[0].get("liveStreamingDetails", {})
               #     overlay_data["viewers"]     = int(live.get("concurrentViewers", 0)) if live.get("concurrentViewers") else None
               #     overlay_data["likes"]       = int(stats.get("likeCount", 0))        if stats.get("likeCount")       else None
                    # Subscriber count requires channel ID — fetch from video snippet first if not cached
                 #   url_snap = (
                  #      f"https://www.googleapis.com/youtube/v3/videos"
                  #      f"?part=snippet&id={VIDEO_ID}&key={YOUTUBE_API_KEY}"
                  #  )
                  #  with urllib.request.urlopen(url_snap, timeout=10) as r2:
                  #      snap = json.loads(r2.read().decode())
                  #  channel_id = snap.get("items", [{}])[0].get("snippet", {}).get("channelId", "")
                 #   if channel_id:
                  #      url_ch = (
                  #          f"https://www.googleapis.com/youtube/v3/channels"
                  #          f"?part=statistics&id={channel_id}&key={YOUTUBE_API_KEY}"
                    #    )
                   #     with urllib.request.urlopen(url_ch, timeout=10) as r3:
                   #         cdata = json.loads(r3.read().decode())
                   #     sub_count = cdata.get("items", [{}])[0].get("statistics", {}).get("subscriberCount")
                   #     overlay_data["subscribers"] = int(sub_count) if sub_count else None
                    # Write updated stats immediately
                  #  try:
                     #   with open("overlay.json", "w", encoding="utf-8") as f:
                    #        json.dump(overlay_data, f, ensure_ascii=False, separators=(',', ':'))
                #    except Exception:
                #        pass
     #   except Exception as e:
      #      print(f"[Stats] Fetch error: {e}")
      #  time.sleep(30)

def start_overlay_server():
    PORT = 8083
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format, *args): pass
    try:
        with socketserver.TCPServer(("", PORT), QuietHandler) as httpd:
            print(f"[Overlay] Server running at: http://localhost:{PORT}/chat.html")
            httpd.serve_forever()
    except OSError:
        print("[Overlay] Port 8083 is busy.")

# ========================= SCANCODES =========================
SCANCODES = {
    "esc": ("01","81"), "tab": ("0f","8f"), "enter": ("1c","9c"), "space": ("39","b9"),
    "backspace": ("0e","8e"), "delete": ("53","d3"), "del": ("53","d3"),
    "insert": ("52","d2"), "home": ("47","c7"), "end": ("4f","cf"),
    "pageup": ("49","c9"), "pagedown": ("51","d1"),
    # Generic (unspecified-side) modifiers — kept for backward compatibility,
    # all map to the LEFT-side key, same as before.
    "ctrl": ("1d","9d"), "alt": ("38","b8"), "shift": ("2a","aa"), "capslock": ("3a","ba"),
    "win": ("e05b","e0db"), "super": ("e05b","e0db"),
    # Left/right-distinguished modifiers — real physical keyboards have two
    # of each, and some shortcuts specifically need the right-hand one
    # (e.g. AltGr on non-US layouts is physically "ralt").
    "lctrl": ("1d","9d"), "rctrl": ("e01d","e09d"),
    "lalt": ("38","b8"), "ralt": ("e038","e0b8"), "altgr": ("e038","e0b8"),
    "lshift": ("2a","aa"), "rshift": ("36","b6"),
    "lwin": ("e05b","e0db"), "rwin": ("e05c","e0dc"),
    "f1": ("3b","bb"), "f2": ("3c","bc"), "f3": ("3d","bd"), "f4": ("3e","be"),
    "f5": ("3f","bf"), "f6": ("40","c0"), "f7": ("41","c1"), "f8": ("42","c2"),
    "f9": ("43","c3"), "f10": ("44","c4"), "f11": ("57","d7"), "f12": ("58","d8"),
    "up": ("48","c8"), "down": ("50","d0"), "left": ("4b","cb"), "right": ("4d","cd"),
    "a": ("1e","9e"), "b": ("30","b0"), "c": ("2e","ae"), "d": ("20","a0"),
    "e": ("12","92"), "f": ("21","a1"), "g": ("22","a2"), "h": ("23","a3"),
    "i": ("17","97"), "j": ("24","a4"), "k": ("25","a5"), "l": ("26","a6"),
    "m": ("32","b2"), "n": ("31","b1"), "o": ("18","98"), "p": ("19","99"),
    "q": ("10","90"), "r": ("13","93"), "s": ("1f","9f"), "t": ("14","94"),
    "u": ("16","96"), "v": ("2f","af"), "w": ("11","91"), "x": ("2d","ad"),
    "y": ("15","95"), "z": ("2c","ac"),
    "0": ("0b","8b"), "1": ("02","82"), "2": ("03","83"), "3": ("04","84"),
    "4": ("05","85"), "5": ("06","86"), "6": ("07","87"), "7": ("08","88"),
    "8": ("09","89"), "9": ("0a","8a"),
    # Punctuation / symbol row — main-keyboard (non-numpad) keys, US layout
    "minus": ("0c","8c"), "dash": ("0c","8c"), "hyphen": ("0c","8c"),
    "equal": ("0d","8d"), "equals": ("0d","8d"), "plus": ("0d","8d"),
    "lbracket": ("1a","9a"), "leftbracket": ("1a","9a"), "[": ("1a","9a"),
    "rbracket": ("1b","9b"), "rightbracket": ("1b","9b"), "]": ("1b","9b"),
    "backslash": ("2b","ab"), "\\": ("2b","ab"),
    "semicolon": ("27","a7"), ";": ("27","a7"),
    "quote": ("28","a8"), "apostrophe": ("28","a8"), "'": ("28","a8"),
    "grave": ("29","a9"), "backtick": ("29","a9"), "tilde": ("29","a9"), "`": ("29","a9"),
    "comma": ("33","b3"), ",": ("33","b3"),
    "period": ("34","b4"), "dot": ("34","b4"), ".": ("34","b4"),
    "slash": ("35","b5"), "forwardslash": ("35","b5"), "/": ("35","b5"),
    # Numpad
    "num0": ("52","d2"), "num1": ("4f","cf"), "num2": ("50","d0"), "num3": ("51","d1"),
    "num4": ("4b","cb"), "num5": ("4c","cc"), "num6": ("4d","cd"), "num7": ("47","c7"),
    "num8": ("48","c8"), "num9": ("49","c9"),
    "numlock": ("45","c5"),
    "numdivide": ("e035","e0b5"), "numdiv": ("e035","e0b5"),
    "nummultiply": ("37","b7"), "nummul": ("37","b7"),
    "numsubtract": ("4a","ca"), "numminus": ("4a","ca"),
    "numadd": ("4e","ce"), "numplus": ("4e","ce"),
    "numdecimal": ("53","d3"), "numdot": ("53","d3"),
    "numenter": ("e01c","e09c"),
    # Misc / navigation / system
    "printscreen": ("e02ae037","e0b7e0aa"), "prtsc": ("e02ae037","e0b7e0aa"),
    "scrolllock": ("46","c6"),
    "pause": ("e11d45e19dc5", ""),   # Pause/Break has no separate release code — the full press+release is one 6-byte make sequence, sent as "down"; "up" is an intentional no-op
    "menu": ("e05d","e0dd"), "apps": ("e05d","e0dd"), "contextmenu": ("e05d","e0dd"),
    # Media / volume — useful for muting/adjusting a stream's audio source
    "volumeup": ("e030","e0b0"), "volumedown": ("e02e","e0ae"), "volumemute": ("e020","e0a0"),
    "mediaplaypause": ("e022","e0a2"), "medianext": ("e019","e099"), "mediaprev": ("e010","e090"),
}

def send_combo(keys):
    up_codes = []
    for k in keys:
        if k in SCANCODES:
            down, up = SCANCODES[k]
            send_scancode(down)
            time.sleep(0.01)
            up_codes.insert(0, up)
    for up in up_codes:
        send_scancode(up)
        time.sleep(0.01)

def get_vboxmanage_path():
    possible_paths = [
        r"C:\Program Files\Oracle\VirtualBox\VBoxManage.exe",
        r"C:\Program Files (x86)\Oracle\VirtualBox\VBoxManage.exe",
        r"D:\Program Files\Oracle\VirtualBox\VBoxManage.exe",
        r"E:\Program Files\Oracle\VirtualBox\VBoxManage.exe",
    ]
    for path in possible_paths:
        if os.path.exists(path):
            return path
    return None

def get_vm_list():
    """Fetches the VM list from VirtualBox."""
    vbm = get_vboxmanage_path()
    if not vbm:
        return []
    try:
        result = subprocess.run([vbm, "list", "vms"], capture_output=True, text=True)
        # Each line: "VM Name" {uuid}
        vms = re.findall(r'"([^"]+)"', result.stdout)
        return vms
    except Exception as e:
        print(f"[VM List] Error: {e}")
        return []

VBOXMANAGE_PATH = get_vboxmanage_path()
COOLDOWN_START  = 120
VOTES_JSON_FILE = "votes.json"
VOTE_FILE_BAN   = "ban_vote.html"
STATUS_FILE     = "newstatus.html"

# Shared vote state written to votes.json (read by overlay.html)
_votes_state = {
    "restartvm": {"remaining_time": 0, "current": 0, "required": 2},
    "revert":    {"remaining_time": 0, "current": 0, "required": 2},
}

def update_votes_json(vote_type: str, current: int, required: int, remaining_time: float = 0):
    """Write the current vote state for one vote type to votes.json."""
    _votes_state[vote_type]["current"]        = current
    _votes_state[vote_type]["required"]       = required
    _votes_state[vote_type]["remaining_time"] = max(0, int(remaining_time))
    try:
        with open(VOTES_JSON_FILE, "w", encoding="utf-8") as f:
            json.dump(_votes_state, f, separators=(',', ':'))
    except Exception as e:
        print(f"[Votes] Write error: {e}")
BAN_DURATION      = 1800
VOTE_TIMEOUT      = 120
SUCCESS_SOUND_FILE = "success.mp3"
ADMIN_USERNAME     = "Nexora-WN"
YOUTUBE_API_KEY    = ""   # Optional: YouTube Data API v3 key — enables the
                          # official chat backend in YouTubeChatSource
                          # (see the class above). Entered once in the
                          # GUI, saved to youtube_api_key_config.json.
YOUTUBE_API_KEY_CONFIG_FILE = "youtube_api_key_config.json"

def load_youtube_api_key_config():
    global YOUTUBE_API_KEY
    try:
        if os.path.exists(YOUTUBE_API_KEY_CONFIG_FILE):
            with open(YOUTUBE_API_KEY_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            YOUTUBE_API_KEY = data.get("api_key", "").strip()
            if YOUTUBE_API_KEY:
                print("[YouTubeAPIKey] Config loaded — official API backend available.")
    except Exception as e:
        print(f"[YouTubeAPIKey] Load error: {e}")

def save_youtube_api_key_config():
    try:
        with open(YOUTUBE_API_KEY_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"api_key": YOUTUBE_API_KEY}, f, indent=2)
        print("[YouTubeAPIKey] Config saved.")
    except Exception as e:
        print(f"[YouTubeAPIKey] Save error: {e}")

# Global bot state (set at runtime from GUI)
VIDEO_ID = ""
VM_NAME  = ""

# ========================= REAL PC CONTROL =========================
REALPC_CONFIG_FILE = "realpc_config.json"
REALPC_CONFIG = {
    "video_id":          "",       # YouTube video ID to listen on
    "enabled":           False,    # master on/off switch
    "failsafe":          False,    # pyautogui failsafe (mouse to corner = abort) — off by default
    "action_delay":      0.05,     # seconds between pyautogui calls
    "cooldown":          1.0,      # per-user cooldown in seconds
    "whitelist_only":    False,    # only allow whitelisted users
    "whitelist":         [],       # list of allowed usernames
    "blocked":           [],       # list of blocked usernames
    "allowed_actions":   {         # which action categories are enabled
        "keyboard":   True,
        "mouse":      True,
        "screenshot": True,
        "combo":      True,
    },
    "text_only":         False,    # if True, only !type and !send work — everything else blocked
    "mouse_step":        50,       # pixels per !moverel step
    "scroll_step":       3,        # clicks per !scroll
    "max_type_length":   100,      # max chars per !type command
    "danger_filter_enabled": True,  # HARD block of dangerous OS-level commands/hotkeys — default ON
}

_realpc_bot_thread   = None
_realpc_stop_event   = threading.Event()
_realpc_user_cd      = {}          # {username: last_action_time}
_realpc_cd_lock      = threading.Lock()
_realpc_status_cb    = None        # GUI callback to update status label


def load_realpc_config():
    try:
        if os.path.exists(REALPC_CONFIG_FILE):
            with open(REALPC_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            REALPC_CONFIG.update(data)
            print("[RealPC] Config loaded.")
    except Exception as e:
        print(f"[RealPC] Load error: {e}")


def save_realpc_config():
    try:
        with open(REALPC_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(REALPC_CONFIG, f, indent=2)
        print("[RealPC] Config saved.")
    except Exception as e:
        print(f"[RealPC] Save error: {e}")


def _realpc_set_status(msg: str):
    if _realpc_status_cb:
        try:
            _realpc_status_cb(msg)
        except Exception:
            pass
    print(f"[RealPC] {msg}")


def _realpc_check_cooldown(username: str) -> bool:
    """Return True if the user is allowed to act (not on cooldown)."""
    cd = REALPC_CONFIG.get("cooldown", 1.0)
    now = time.time()
    with _realpc_cd_lock:
        last = _realpc_user_cd.get(username, 0)
        if now - last < cd:
            return False
        _realpc_user_cd[username] = now
    return True


# ========================= REAL PC — DANGEROUS COMMAND FILTER =========================
# HARD-CODED safety net for the Real PC Control feature. This is intentionally
# NOT fully configurable from the GUI — only the master on/off switch is exposed,
# and turning it off requires two explicit warning dialogs.
#
# IMPORTANT: this filter does NOT just look at one command in isolation.
# A single !type/!send call rarely contains a full dangerous command — chat
# users can (and will) split it across many small steps to dodge a naive
# per-command filter, e.g.:
#
#   !type shu   !type tdown          -> spells "shutdown"
#   !type rd5   !key backspace   !type m2   !key backspace   -> "rd" + "m" via edits
#   !key s !key h !key u !key t !key d !key o !key w !key n  -> one key at a time
#
# To catch this, we keep a small per-user ROLLING TEXT BUFFER that simulates
# what is actually being typed on the real screen: !type/!send/!key append
# characters, !backspace removes the last character, !space appends a space,
# !enter/!send flushes (real commands are usually submitted with Enter, but
# we still keep scanning right up to that point). Every mutation re-scans the
# buffer (with whitespace stripped, to catch spaced-out spelling like
# "s h u t d o w n") against the dangerous pattern list.
#
# This list also blocks PowerShell/.NET text-to-speech invocation
# (System.Speech.Synthesis, SAPI.SpVoice, .Speak()). This isn't a
# destructive command, but it's the same "chat types something into the
# VM" risk surface: it lets chat make the machine's own voice read out
# arbitrary (including abusive) text on stream.

# Substrings that indicate an attempt to run destructive or system-level
# commands (typed directly, or via Run/terminal opened some other way).
# Matching is case-insensitive and checked with whitespace fully stripped,
# so spacing/chunking tricks don't bypass it.
_REALPC_DANGEROUS_TEXT_PATTERNS_WITH_DESC = [
    # ============ Category: Disk & Filesystem ============
    ("formatc", "Formats (wipes) the C: drive", "Disk & Filesystem"),
    ("formatd", "Formats (wipes) the D: drive", "Disk & Filesystem"),
    ("formate", "Formats (wipes) the E: drive", "Disk & Filesystem"),
    ("del/f", "Force-deletes files, bypassing the normal delete confirmation", "Disk & Filesystem"),
    ("del/s", "Deletes files recursively through subfolders", "Disk & Filesystem"),
    ("del/q", "Deletes files silently, no confirmation prompt", "Disk & Filesystem"),
    ("rd/s", "Deletes an entire folder and everything inside it", "Disk & Filesystem"),
    ("rmdir/s", "Deletes an entire folder and everything inside it", "Disk & Filesystem"),
    ("deltree", "Deletes an entire folder tree at once", "Disk & Filesystem"),
    ("diskpart", "Windows disk partitioning tool — can wipe/repartition drives", "Disk & Filesystem"),
    ("cleanall", "Diskpart command that wipes a drive completely", "Disk & Filesystem"),
    ("format", "Formats (wipes) a drive", "Disk & Filesystem"),
    ("\\\\.\\physicaldrive", "Direct raw access to a physical disk, bypassing normal file protections", "Disk & Filesystem"),
    ("/fs:ntfs", "Filesystem-format flag used together with 'format' to wipe a drive", "Disk & Filesystem"),
    ("/fs:fat32", "Filesystem-format flag used together with 'format' to wipe a drive", "Disk & Filesystem"),
    ("vssadmin", "Manages Windows shadow copies (backups) — can delete them", "Disk & Filesystem"),
    ("vssadminresize", "Shrinks shadow-copy storage, destroying backup history", "Disk & Filesystem"),
    ("vssadmindelete", "Permanently deletes Windows shadow-copy backups", "Disk & Filesystem"),
    ("wbadmindelete", "Permanently deletes Windows Backup system data", "Disk & Filesystem"),
    ("cipher/w", "Overwrites deleted file remnants — used to make data unrecoverable", "Disk & Filesystem"),
    ("icacls", "Changes file/folder permissions — can lock out or expose files", "Disk & Filesystem"),
    ("takeown/f", "Force-takes ownership of a file/folder, bypassing normal permissions", "Disk & Filesystem"),
    ("attrib+h", "Hides a file from normal view in File Explorer", "Disk & Filesystem"),
    ("attrib-h", "Un-hides a hidden file", "Disk & Filesystem"),
    # System32 / Windows directory protection — the single most common
    # "instantly break the whole OS" target. Blocking the path itself
    # catches it regardless of which tool is used to delete/move/rename
    # it (del, PowerShell, robocopy, explorer.exe drag-and-drop via a
    # scripted rename, etc.) — the earlier del/f, del/s, rd/s patterns
    # above only catch it if the classic "del" command is used verbatim.
    ("system32", "Targets Windows' core system folder — deleting/renaming it breaks the OS immediately", "Disk & Filesystem"),
    ("windows\\system32", "Direct path to Windows' core system folder", "Disk & Filesystem"),
    ("c:\\windows", "Targets the entire Windows installation folder", "Disk & Filesystem"),
    ("%windir%", "Environment variable pointing to the Windows folder — used to target it indirectly", "Disk & Filesystem"),
    ("%systemroot%", "Environment variable pointing to the Windows folder — used to target it indirectly", "Disk & Filesystem"),
    ("remove-item", "PowerShell's delete command — can remove any file or folder, including system ones", "Disk & Filesystem"),
    ("ri-recurse", "PowerShell shorthand for a recursive forced delete", "Disk & Filesystem"),
    ("robocopy/purge", "Windows file-sync tool's delete mode — can wipe an entire folder's contents", "Disk & Filesystem"),
    ("robocopymir", "Windows file-sync tool's 'mirror' mode — deletes anything not in the source, can empty a folder", "Disk & Filesystem"),
    ("rename-item", "PowerShell's rename command — renaming System32 breaks Windows just as badly as deleting it", "Disk & Filesystem"),
    ("move-item", "PowerShell's move command — moving System32 elsewhere breaks Windows just as badly as deleting it", "Disk & Filesystem"),
    # Mount / volume-remapping tricks — these can expose or replace the C:
    # drive out from under a running Windows install, effectively causing
    # the same "everything is suddenly gone" outcome as a format, without
    # ever calling a command with "format" in it.
    ("mountvol", "Windows tool that assigns/removes drive letters — can unmount or remap C:", "Disk & Filesystem"),
    ("mountvoly", "Windows tool that assigns/removes drive letters — can unmount or remap C:", "Disk & Filesystem"),
    ("mountvol/d", "Removes a volume's drive letter, making it inaccessible", "Disk & Filesystem"),
    ("mount-diskimage", "PowerShell command that mounts a disk image — can be used to swap in a different disk", "Disk & Filesystem"),
    ("dismount-diskimage", "PowerShell command that unmounts a disk image", "Disk & Filesystem"),
    ("set-disk", "PowerShell command that changes a disk's online/offline or read-only state", "Disk & Filesystem"),
    ("set-partition", "PowerShell command that changes a partition's drive letter or state", "Disk & Filesystem"),
    ("-isoffline", "PowerShell flag that takes a disk offline, making it disappear from the system", "Disk & Filesystem"),
    ("get-diskset-disk", "PowerShell one-liner pattern used to take a disk offline/online", "Disk & Filesystem"),
    ("remove-partitionaccesspath", "Removes a drive letter/mount path from a partition", "Disk & Filesystem"),
    ("wsl--mount", "Mounts a physical disk into WSL/Linux, bypassing normal Windows file protections", "Disk & Filesystem"),
    ("wslmount", "Mounts a physical disk into WSL/Linux, bypassing normal Windows file protections", "Disk & Filesystem"),
    ("diskpartselectvolume", "Diskpart sub-command that targets a specific drive for further changes (assign/remove/format)", "Disk & Filesystem"),
    ("diskpartremoveletter", "Diskpart sub-command that strips a drive letter, making the drive vanish from Explorer", "Disk & Filesystem"),
    ("diskpartassignletter", "Diskpart sub-command that reassigns a drive letter — can redirect C: to a different disk", "Disk & Filesystem"),
    ("diskpartoffline", "Diskpart sub-command that takes a disk offline", "Disk & Filesystem"),
    ("diskpartclean", "Diskpart sub-command that wipes a disk's partition table", "Disk & Filesystem"),
    # ============ Category: Power & System State ============
    ("shutdown", "Turns the computer off", "Power & System State"),
    ("logoff", "Logs the current user out", "Power & System State"),
    ("restart-computer", "PowerShell command that reboots the machine", "Power & System State"),
    ("restart -computer", "PowerShell command that reboots the machine", "Power & System State"),
    ("restart–computer", "PowerShell command that reboots the machine (en-dash variant)", "Power & System State"),
    ("stop-computer", "PowerShell command that shuts the machine down", "Power & System State"),
    ("stop -computer", "PowerShell command that shuts the machine down", "Power & System State"),
    ("restart-service", "Restarts a Windows service, can disrupt anything running", "Power & System State"),
    ("stop-service", "Stops a Windows service, can disrupt anything running", "Power & System State"),
    ("shutdown.exe", "Turns the computer off", "Power & System State"),
    ("shutdown/r", "Reboots the computer", "Power & System State"),
    ("shutdown/s", "Shuts the computer down", "Power & System State"),
    ("shutdown-r", "Reboots the computer", "Power & System State"),
    ("shutdown-s", "Shuts the computer down", "Power & System State"),
    ("-computerlocalhost", "Targets the local machine in a WMI reboot/shutdown command", "Power & System State"),
    ("win32_operatingsystem", "WMI object used to trigger a remote-style reboot/shutdown", "Power & System State"),
    ("invoke-cimmethod", "Runs a low-level Windows management command — can reboot/shutdown", "Power & System State"),
    ("invoke-wmimethod", "Runs a low-level Windows management command — can reboot/shutdown", "Power & System State"),
    ("win32shutdown(", "Direct WMI call that shuts down or reboots the machine", "Power & System State"),
    ("bcdedit", "Edits Windows boot configuration — can break the ability to start up", "Power & System State"),
    ("bootrec", "Repairs/rewrites the Windows boot sector — can break startup if misused", "Power & System State"),
    ("regdelete", "Deletes a Windows Registry key — can break the OS", "Power & System State"),
    ("regadd", "Adds/changes a Windows Registry key — can break the OS or add malicious settings", "Power & System State"),
    ("regedit/s", "Silently imports a registry file with no confirmation prompt", "Power & System State"),
    ("netuser", "Creates/deletes/changes Windows user accounts", "Power & System State"),
    ("netlocalgroup", "Adds/removes users from admin or other local groups", "Power & System State"),
    ("netstop", "Stops a Windows service", "Power & System State"),
    ("taskkill/f", "Force-kills a running program with no warning", "Power & System State"),
    ("stop-process", "PowerShell command that force-kills a running program", "Power & System State"),
    ("kill-9", "Force-kills a running program immediately (Linux/macOS)", "Power & System State"),
    ("wmic", "Windows management command-line tool — can shut down, kill processes, etc.", "Power & System State"),
    # ============ Category: PowerShell & Scripting ============
    ("powershell.exe", "Launches PowerShell, which can run almost any system command", "PowerShell & Scripting"),
    ("powershell-", "Launches PowerShell with a flag/argument attached", "PowerShell & Scripting"),
    ("pwsh.exe", "Launches PowerShell 7+ (cross-platform edition)", "PowerShell & Scripting"),
    ("iwr(", "PowerShell shorthand for downloading a file/page from the internet", "PowerShell & Scripting"),
    ("irm(", "PowerShell shorthand for downloading and often auto-running remote content", "PowerShell & Scripting"),
    ("-encodedcommand", "Runs a PowerShell command hidden inside base64 encoding", "PowerShell & Scripting"),
    ("-enc ", "Short form of -EncodedCommand — hides a PowerShell command in base64", "PowerShell & Scripting"),
    ("-ec ", "Short form of -EncodedCommand — hides a PowerShell command in base64", "PowerShell & Scripting"),
    ("executionpolicybypass", "Disables PowerShell's safety checks before running a script", "PowerShell & Scripting"),
    ("windowstylehidden", "Runs a command with its window hidden from view", "PowerShell & Scripting"),
    ("-windowstylehidden", "Runs a command with its window hidden from view", "PowerShell & Scripting"),
    ("-noprofile", "Runs PowerShell stripped-down, often used to avoid logging/tracing", "PowerShell & Scripting"),
    ("invoke-webrequest", "PowerShell command that downloads a file/page from the internet", "PowerShell & Scripting"),
    ("invoke-expression", "Runs arbitrary text as a PowerShell command — classic malware technique", "PowerShell & Scripting"),
    ("iex(", "Shorthand for Invoke-Expression — runs arbitrary text as a command", "PowerShell & Scripting"),
    ("invoke-command", "Runs a command, optionally on a remote machine", "PowerShell & Scripting"),
    ("mshta.exe", "Runs HTML/JavaScript applications with full system access", "PowerShell & Scripting"),
    ("rundll32.exe", "Runs code from a DLL file — a very common way to launch hidden payloads", "PowerShell & Scripting"),
    ("regsvr32", "Registers a DLL — can be abused to run malicious code while looking legitimate", "PowerShell & Scripting"),
    ("regsvr32.exe", "Registers a DLL — can be abused to run malicious code while looking legitimate", "PowerShell & Scripting"),
    ("wscript", "Runs VBScript/JScript files with full system access", "PowerShell & Scripting"),
    ("wscript.exe", "Runs VBScript/JScript files with full system access", "PowerShell & Scripting"),
    ("cscript", "Runs VBScript/JScript files from the command line", "PowerShell & Scripting"),
    ("cscript.exe", "Runs VBScript/JScript files from the command line", "PowerShell & Scripting"),
    # Script interpreters — a chat-controlled Real PC/VM bot has no
    # legitimate reason to invoke a general-purpose interpreter at all;
    # blocking the interpreter itself closes off whatever that language's
    # standard library can do (file writes, base64 decode, sockets, etc.)
    # without having to separately blocklist every module/function it
    # offers, which we'd never fully enumerate anyway.
    # NOTE: the scan function strips ALL whitespace from both the typed
    # text and these patterns before comparing, so "python" alone already
    # matches "python.exe", "python3.exe", "python -c ...", etc. — no
    # need for separate entries per variant.
    ("python", "Launches the Python interpreter — can run essentially any code", "PowerShell & Scripting"),
    ("py.exe", "Windows' Python launcher — can run essentially any code", "PowerShell & Scripting"),
    ("py-c", "Runs a one-line Python command directly from the command line", "PowerShell & Scripting"),
    ("perl", "Launches the Perl interpreter — can run essentially any code", "PowerShell & Scripting"),
    ("ruby", "Launches the Ruby interpreter — can run essentially any code", "PowerShell & Scripting"),
    ("node.exe", "Launches Node.js (JavaScript) — can run essentially any code", "PowerShell & Scripting"),
    ("node-e", "Runs a one-line Node.js command directly from the command line", "PowerShell & Scripting"),
    # ============ Category: Persistence & Services ============
    ("sc.exedelete", "Deletes a Windows service", "Persistence & Services"),
    ("sc.exestop", "Stops a Windows service", "Persistence & Services"),
    ("sc.execonfig", "Reconfigures a Windows service (e.g. to auto-run something)", "Persistence & Services"),
    ("sc.execreate", "Creates a new Windows service — a common persistence technique", "Persistence & Services"),
    ("schtasks", "Schedules a task to run automatically — a common persistence technique", "Persistence & Services"),
    ("at.exe", "Old Windows task scheduler — same persistence risk as schtasks", "Persistence & Services"),
    ("disable-windowsdefender", "Turns off Windows' built-in antivirus", "Persistence & Services"),
    ("set-mppreference", "Changes Windows Defender antivirus settings", "Persistence & Services"),
    ("-disablerealtimemonitoring", "Turns off Windows Defender's real-time virus scanning", "Persistence & Services"),
    ("bitsadmin", "Windows background file-transfer tool, often abused to download malware", "Persistence & Services"),
    ("bitsadmin/transfer", "Downloads a file in the background using Windows' BITS service", "Persistence & Services"),
    ("msiexec", "Installs/runs an MSI installer package — can install unwanted software", "Persistence & Services"),
    ("msiexec/i", "Silently installs an MSI installer package", "Persistence & Services"),
    # ============ Category: Text-to-Speech Abuse ============
    # PowerShell / .NET text-to-speech — lets chat make the machine's own
    # voice say arbitrary text out loud (harassment / abuse vector, not a
    # destructive-command vector, but same "typed into the VM" risk surface)
    ("system.speech", ".NET text-to-speech library — lets chat make the PC speak arbitrary text aloud", "Text-to-Speech Abuse"),
    ("system.speech.synthesis", ".NET text-to-speech library — lets chat make the PC speak arbitrary text aloud", "Text-to-Speech Abuse"),
    ("speechsynthesizer", ".NET text-to-speech object — lets chat make the PC speak arbitrary text aloud", "Text-to-Speech Abuse"),
    ("sapi.spvoice", "Windows text-to-speech engine — lets chat make the PC speak arbitrary text aloud", "Text-to-Speech Abuse"),
    ("spvoice", "Windows text-to-speech engine — lets chat make the PC speak arbitrary text aloud", "Text-to-Speech Abuse"),
    ("createobject(\"sapi.spvoice\")", "Creates a text-to-speech object to make the PC speak arbitrary text", "Text-to-Speech Abuse"),
    (".speak(", "Text-to-speech command — makes the PC say arbitrary/abusive text out loud", "Text-to-Speech Abuse"),
    ("speak(", "Text-to-speech command — makes the PC say arbitrary/abusive text out loud", "Text-to-Speech Abuse"),
    # ============ Category: Cross-Platform (Linux/macOS) ============
    ("rm-rf", "Recursively force-deletes files/folders with no confirmation (Linux/macOS)", "Cross-Platform (Linux/macOS)"),
    ("rm-r", "Recursively deletes files/folders (Linux/macOS)", "Cross-Platform (Linux/macOS)"),
    ("sudorm", "Deletes files/folders with admin rights (Linux/macOS)", "Cross-Platform (Linux/macOS)"),
    (":(){:|:&};:", "A 'fork bomb' — rapidly clones itself until the system crashes", "Cross-Platform (Linux/macOS)"),
    ("mkfs", "Formats (wipes) a disk partition (Linux/macOS)", "Cross-Platform (Linux/macOS)"),
    ("ddif=", "Low-level disk-copy command that can overwrite an entire drive", "Cross-Platform (Linux/macOS)"),
    (">/dev/sda", "Redirects data to overwrite a raw disk device directly", "Cross-Platform (Linux/macOS)"),
    ("chmod-r777", "Makes all files fully open to read/write/execute by anyone", "Cross-Platform (Linux/macOS)"),
    ("chmod777/", "Makes files fully open to read/write/execute by anyone", "Cross-Platform (Linux/macOS)"),
    ("sudodd", "Runs the disk-overwrite 'dd' command with admin rights", "Cross-Platform (Linux/macOS)"),
    ("sudomkfs", "Formats (wipes) a disk partition with admin rights", "Cross-Platform (Linux/macOS)"),
    ("sudoshutdown", "Shuts the computer down with admin rights (Linux/macOS)", "Cross-Platform (Linux/macOS)"),
    ("sudoreboot", "Reboots the computer with admin rights (Linux/macOS)", "Cross-Platform (Linux/macOS)"),
    ("sudohalt", "Halts the computer with admin rights (Linux/macOS)", "Cross-Platform (Linux/macOS)"),
    ("sudopoweroff", "Powers off the computer with admin rights (Linux/macOS)", "Cross-Platform (Linux/macOS)"),
    ("systemctlreboot", "Reboots the computer (Linux)", "Cross-Platform (Linux/macOS)"),
    ("systemctlpoweroff", "Powers off the computer (Linux)", "Cross-Platform (Linux/macOS)"),
    ("systemctlhalt", "Halts the computer (Linux)", "Cross-Platform (Linux/macOS)"),
    ("sudoinit0", "Shuts the computer down via the old init system (Linux)", "Cross-Platform (Linux/macOS)"),
    ("sudoinit6", "Reboots the computer via the old init system (Linux)", "Cross-Platform (Linux/macOS)"),
    ("telinit0", "Shuts the computer down via the old init system (Linux)", "Cross-Platform (Linux/macOS)"),
    ("telinit6", "Reboots the computer via the old init system (Linux)", "Cross-Platform (Linux/macOS)"),
    ("mount/dev", "Mounts a raw disk device directly, bypassing normal filesystem protections (Linux/macOS)", "Cross-Platform (Linux/macOS)"),
    ("sudomount", "Mounts a filesystem with admin rights (Linux/macOS)", "Cross-Platform (Linux/macOS)"),
    ("umount-f", "Force-unmounts a filesystem, even if files on it are in use (Linux/macOS)", "Cross-Platform (Linux/macOS)"),
    ("diskutilerasedisk", "Wipes and reformats an entire disk (macOS)", "Cross-Platform (Linux/macOS)"),
    ("diskutilunmountdisk", "Unmounts an entire disk, including all its partitions (macOS)", "Cross-Platform (Linux/macOS)"),
    # ============ Category: Download & Network Exec ============
    ("curlhttp", "Downloads content from a URL", "Download & Network Exec"),
    ("wgethttp", "Downloads content from a URL", "Download & Network Exec"),
    ("curl-o", "Downloads a file from the internet and saves it to disk", "Download & Network Exec"),
    ("wget-o", "Downloads a file from the internet and saves it to disk", "Download & Network Exec"),
    ("curl-s", "Downloads content silently, hiding progress/errors", "Download & Network Exec"),
    ("|bash", "Pipes downloaded content straight into a shell to run it immediately", "Download & Network Exec"),
    ("|sh", "Pipes downloaded content straight into a shell to run it immediately", "Download & Network Exec"),
    ("downloadstring", "Downloads text/code from the internet directly into memory", "Download & Network Exec"),
    ("downloadfile", "Downloads a file from the internet to disk", "Download & Network Exec"),
    ("certutil-urlcache", "Abuses a Windows certificate tool to download files from the internet", "Download & Network Exec"),
    ("certutil", "Windows certificate tool, commonly abused to download or decode files", "Download & Network Exec"),
    # ============ Category: Base64 Payload Decode ============
    # Base64 decode-to-file primitives — the actual "no internet needed"
    # vector: the payload (e.g. an image) is embedded as base64 text
    # directly in the typed command, then decoded straight to a file and
    # opened. None of this touches the network, so it's invisible to any
    # filter that only looks for download/exec commands.
    ("frombase64string", "Decodes base64 text back into raw file data (e.g. a hidden image)", "Base64 Payload Decode"),
    ("convert::frombase64string", "Decodes base64 text back into raw file data (e.g. a hidden image)", "Base64 Payload Decode"),
    ("writeallbytes", "Writes raw decoded data straight to a file on disk", "Base64 Payload Decode"),
    ("io.file::writeallbytes", "Writes raw decoded data straight to a file on disk", "Base64 Payload Decode"),
    ("[io.file]::writeallbytes", "Writes raw decoded data straight to a file on disk", "Base64 Payload Decode"),
    ("set-contentencoding", "Writes raw byte data to a file using PowerShell", "Base64 Payload Decode"),
    ("-encodingbyte", "Flag that tells PowerShell to write raw byte data to a file", "Base64 Payload Decode"),
    ("out-fileencoding", "Writes output to a file with a specific (often binary) encoding", "Base64 Payload Decode"),
    ("certutil-decode", "Abuses a Windows certificate tool to decode base64 into a file", "Base64 Payload Decode"),
    ("certreq-decode", "Abuses a Windows certificate tool to decode base64 into a file", "Base64 Payload Decode"),
    # Python equivalents of the above — belt-and-suspenders on top of the
    # interpreter block itself being blocked, in case "python" is ever
    # unblocked via the Danger Filter's per-pattern checkboxes.
    ("base64.b64decode", "Python function that decodes base64 text back into raw file data", "Base64 Payload Decode"),
    ("base64.decodebytes", "Python function that decodes base64 text back into raw file data", "Base64 Payload Decode"),
    ("base64.decode", "Python function that decodes base64 text back into raw file data", "Base64 Payload Decode"),
    ("importbase64", "Loads Python's base64 module, needed to decode a hidden payload", "Base64 Payload Decode"),
]
_REALPC_DANGEROUS_TEXT_PATTERNS = [p for p, _, _ in _REALPC_DANGEROUS_TEXT_PATTERNS_WITH_DESC]

# Single keys that are dangerous as a standalone !key / !press regardless of
# the typing buffer (they act immediately, not via typed text).
_REALPC_DANGEROUS_KEYS = {
    "printscreen",
}

# Hotkeys that open OS-level surfaces are intentionally NOT hard-blocked here
# (per design decision: focus protection on command/text content, not on
# every possible key combo, since that list is trivially incomplete). If a
# combo like Win+R opens a Run box, anything typed into it still has to pass
# through the text buffer filter below before it can do anything.

_realpc_typing_buffers = {}          # {username: "current simulated text"}
_realpc_typing_buffer_lock = threading.Lock()
# A real image, even a tiny one, needs hundreds to thousands of base64
# characters — far more than the old 200-char cap kept around, which meant
# a long base64 payload would get truncated out of the buffer before the
# scan below ever saw the whole thing. Raised so the base64 heuristic
# actually has something to catch.
_REALPC_BUFFER_MAX_LEN = 4000

# Any unbroken run of base64-alphabet characters at least this long is
# treated as a payload blob and blocked outright, regardless of which
# tool would go on to decode it (certutil, PowerShell, python, etc.).
# There is no legitimate reason a chat-issued PC command needs a 60+
# character run of pure base64 — real commands, paths, and URLs always
# mix in spaces, slashes, or other separators well before that length.
_REALPC_BASE64_BLOB_MIN_LEN = 60
_REALPC_BASE64_BLOB_RE = re.compile(r"[A-Za-z0-9+/]{%d,}={0,2}" % _REALPC_BASE64_BLOB_MIN_LEN)

# ── User-controlled unblock overrides ──
# Patterns/keys the operator has explicitly unchecked in the "View Blocked
# List" popup (Main tab / Real PC tab). Anything in these sets is skipped
# by the scan functions below — everything else in
# _REALPC_DANGEROUS_TEXT_PATTERNS / _REALPC_DANGEROUS_KEYS stays blocked by
# default, same as before this feature existed. Persisted so choices
# survive a restart.
_REALPC_UNBLOCKED_PATTERNS_FILE = "realpc_unblocked_patterns.json"
_REALPC_UNBLOCKED_PATTERNS = set()   # subset of _REALPC_DANGEROUS_TEXT_PATTERNS
_REALPC_UNBLOCKED_KEYS     = set()   # subset of _REALPC_DANGEROUS_KEYS
_REALPC_BASE64_RULE_ENABLED = True   # separate on/off for the base64-blob heuristic specifically


def load_realpc_unblocked_patterns():
    global _REALPC_UNBLOCKED_PATTERNS, _REALPC_UNBLOCKED_KEYS, _REALPC_BASE64_RULE_ENABLED
    try:
        if os.path.exists(_REALPC_UNBLOCKED_PATTERNS_FILE):
            with open(_REALPC_UNBLOCKED_PATTERNS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Only keep entries that still exist in the current pattern/key
            # lists — if a future version removes or renames a pattern, a
            # stale saved override just quietly drops instead of doing
            # nothing forever.
            _REALPC_UNBLOCKED_PATTERNS = set(data.get("patterns", [])) & set(_REALPC_DANGEROUS_TEXT_PATTERNS)
            _REALPC_UNBLOCKED_KEYS     = set(data.get("keys", []))     & set(_REALPC_DANGEROUS_KEYS)
            _REALPC_BASE64_RULE_ENABLED = bool(data.get("base64_rule_enabled", True))
            if _REALPC_UNBLOCKED_PATTERNS or _REALPC_UNBLOCKED_KEYS or not _REALPC_BASE64_RULE_ENABLED:
                print(f"[DangerFilter] Loaded {len(_REALPC_UNBLOCKED_PATTERNS)} unblocked "
                      f"pattern(s), {len(_REALPC_UNBLOCKED_KEYS)} unblocked key(s).")
    except Exception as e:
        print(f"[DangerFilter] Load unblocked-patterns error: {e}")


def save_realpc_unblocked_patterns():
    try:
        with open(_REALPC_UNBLOCKED_PATTERNS_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "patterns": sorted(_REALPC_UNBLOCKED_PATTERNS),
                "keys": sorted(_REALPC_UNBLOCKED_KEYS),
                "base64_rule_enabled": _REALPC_BASE64_RULE_ENABLED,
            }, f, indent=2)
        print("[DangerFilter] Unblocked-patterns config saved.")
    except Exception as e:
        print(f"[DangerFilter] Save unblocked-patterns error: {e}")


def _realpc_buffer_get(username: str) -> str:
    with _realpc_typing_buffer_lock:
        return _realpc_typing_buffers.get(username, "")


def _realpc_buffer_set(username: str, value: str):
    with _realpc_typing_buffer_lock:
        _realpc_typing_buffers[username] = value[-_REALPC_BUFFER_MAX_LEN:]


def _realpc_buffer_reset(username: str):
    with _realpc_typing_buffer_lock:
        _realpc_typing_buffers[username] = ""


def _realpc_looks_like_base64(candidate: str) -> bool:
    """
    True if `candidate` has the statistical signature of base64-encoded
    binary data: a genuine mix of uppercase, lowercase, AND digits packed
    together. Concatenated natural-language text (which is what you get
    after stripping spaces from a long typed sentence) is overwhelmingly
    lowercase with very few digits and essentially never mixes case
    mid-word, so this reliably tells the two apart.
    """
    digits = sum(c.isdigit() for c in candidate)
    uppers = sum(c.isupper() for c in candidate)
    lowers = sum(c.islower() for c in candidate)
    return digits >= 5 and uppers >= 5 and lowers >= 5


def _realpc_scan_text_for_danger(text: str):
    """Check a raw text string against dangerous patterns, AND against the
    long-base64-blob heuristic (see _REALPC_BASE64_BLOB_RE above).
    Keyword matching is case-insensitive and whitespace-stripped (evasion-
    resistant). The base64 check runs on the CASE-PRESERVED text, since the
    upper/lower/digit mix is exactly the signal that tells a real base64
    payload apart from an ordinary long sentence with its spaces removed.
    Patterns the operator has manually unblocked (see the "View Blocked
    List" popup) are skipped — see _REALPC_UNBLOCKED_PATTERNS above."""
    compact_cased = "".join(text.split())
    compact_lower = compact_cased.lower()

    for pattern in _REALPC_DANGEROUS_TEXT_PATTERNS:
        if pattern in _REALPC_UNBLOCKED_PATTERNS:
            continue
        pattern_compact = "".join(pattern.lower().split())
        if pattern_compact and pattern_compact in compact_lower:
            return pattern

    if _REALPC_BASE64_RULE_ENABLED:
        for m in _REALPC_BASE64_BLOB_RE.finditer(compact_cased):
            if _realpc_looks_like_base64(m.group()):
                return "long base64 payload"

    return None



# Map of !key / !press key names to the literal character they produce when
# typed. pyautogui's press() accepts the punctuation character itself as the
# key name (e.g. press('.') types a period, press('-') types a hyphen), so
# most punctuation keys pass straight through. A few keys also have common
# word aliases that map to the same character. Anything unmapped is treated
# as a non-printing key (arrow keys, F-keys, etc.) and acts as a separator
# so it can't silently glue two typed fragments together.
_REALPC_KEY_TO_CHAR = {
    **{c: c for c in "abcdefghijklmnopqrstuvwxyz0123456789"},
    **{c: c for c in ".-/,;'[]\\=`~!@#$%^&*()_+{}|:\"<>?"},
    "space": " ", "spacebar": " ",
    "minus": "-", "subtract": "-",
    "slash": "/", "divide": "/",
    "period": ".", "decimal": ".",
    "comma": ",",
    "equal": "=", "equals": "=",
}


def _realpc_is_dangerous(action: str, args: str, username: str):
    """
    Hard-coded, STATEFUL danger check. Returns a human-readable reason string
    if the command should be blocked, or None if it's fine. Also updates the
    per-user typing buffer so multi-step spelling/backspace evasion is caught.
    Runs BEFORE anything else, independent of allowed_actions / text_only
    settings, as long as the danger filter is enabled.
    """
    text = (args or "")

    # ── Direct single-shot check on this command's own text ──
    # (covers the simple case: someone just types the whole dangerous
    # command in one go, or pastes it via !send)
    if action in ("type", "write", "text", "say", "send", "sendline", "typeenter"):
        hit = _realpc_scan_text_for_danger(text)
        if hit:
            return f"dangerous command text blocked: matched '{hit}'"

    if action in ("key", "press"):
        key = text.strip().lower()
        if key in _REALPC_DANGEROUS_KEYS and key not in _REALPC_UNBLOCKED_KEYS:
            return f"dangerous key blocked: {key}"

    # ── Rolling typing-buffer check ──
    # Simulates what actually ends up on screen across MULTIPLE separate
    # commands from the same user, catching chunked / backspace-edited /
    # key-by-key spelling of a dangerous command.
    buf = _realpc_buffer_get(username)

    if action in ("type", "write", "text", "say"):
        buf += text
    elif action in ("send", "sendline", "typeenter"):
        buf += text
        # command is being "submitted" — check, then clear on send below
    elif action in ("key", "press"):
        key = text.strip().lower()
        if key in ("enter", "return", "tab", "esc", "escape"):
            # These keys submit/dismiss whatever was being typed — same as !enter.
            buf += " "
        else:
            buf += _REALPC_KEY_TO_CHAR.get(key, " ")   # unmapped keys act as a separator
    elif action == "space":
        buf += " "
    elif action == "enter":
        buf += " "   # Enter submits — treat as a separator, then buffer clears below
    elif action == "backspace":
        buf = buf[:-1]
    else:
        # Any other action (mouse, screenshot, wait, etc.) doesn't affect typed text.
        buf = buf  # no-op, keep as is

    _realpc_buffer_set(username, buf)

    hit = _realpc_scan_text_for_danger(buf)
    if hit:
        # Wipe the buffer so the block itself doesn't leave a dangerous
        # fragment sitting there to be combined with the next attempt.
        _realpc_buffer_reset(username)
        return f"dangerous command assembled across multiple steps: matched '{hit}'"

    # Enter/Send submits the line in real life — clear buffer afterwards
    # so unrelated future typing doesn't inherit old (safe) leftover text.
    if action in ("enter", "send", "sendline", "typeenter"):
        _realpc_buffer_reset(username)
    elif action in ("key", "press") and text.strip().lower() in ("enter", "return", "tab", "esc", "escape"):
        _realpc_buffer_reset(username)

    return None


# ── Same protection, for the VirtualBox VM's keyboard input ──
# The VM's screen is exactly what OBS captures and puts on stream, so the
# "chat spells out a dangerous command / smuggles a base64 image payload"
# risk applies here too, not just to Real PC Control. Reuses the same
# keyword list and base64 heuristic (_realpc_scan_text_for_danger) since
# the danger signature is identical either way — only the typing buffer is
# kept separate, since VM and Real PC are independent typing targets and
# shouldn't be able to "help" each other spell something out.
_vm_typing_buffers = {}
_vm_typing_buffer_lock = threading.Lock()


def _vm_buffer_get(username: str) -> str:
    with _vm_typing_buffer_lock:
        return _vm_typing_buffers.get(username, "")


def _vm_buffer_set(username: str, value: str):
    with _vm_typing_buffer_lock:
        _vm_typing_buffers[username] = value[-_REALPC_BUFFER_MAX_LEN:]


def _vm_buffer_reset(username: str):
    with _vm_typing_buffer_lock:
        _vm_typing_buffers[username] = ""


def _vm_is_dangerous(action: str, args: str, username: str):
    """
    VM-side counterpart to _realpc_is_dangerous — same dangerous-keyword +
    long-base64-payload checks, same chunked/spelled-out-over-time
    detection via a rolling per-user buffer, just applied to VM keyboard
    commands (cmd names as used by the VM chat-command dispatchers:
    type/text/say/send/sendline/typeenter/key/press/enter).
    """
    text = (args or "")

    if action in ("type", "text", "say", "send", "sendline", "typeenter"):
        hit = _realpc_scan_text_for_danger(text)
        if hit:
            return f"dangerous command text blocked: matched '{hit}'"

    if action in ("key", "press"):
        key = text.strip().lower()
        if key in _REALPC_DANGEROUS_KEYS and key not in _REALPC_UNBLOCKED_KEYS:
            return f"dangerous key blocked: {key}"

    buf = _vm_buffer_get(username)

    if action in ("type", "text", "say"):
        buf += text
    elif action in ("send", "sendline", "typeenter"):
        buf += text
    elif action in ("key", "press"):
        key = text.strip().lower()
        if key in ("enter", "return", "tab", "esc", "escape"):
            buf += " "
        else:
            buf += _REALPC_KEY_TO_CHAR.get(key, " ")
    elif action == "enter":
        buf += " "
    # any other action (mouse, startvm, restore, votehelp, etc.) doesn't
    # affect typed text — buffer left as-is

    _vm_buffer_set(username, buf)

    hit = _realpc_scan_text_for_danger(buf)
    if hit:
        _vm_buffer_reset(username)
        return f"dangerous command assembled across multiple steps: matched '{hit}'"

    if action in ("enter", "send", "sendline", "typeenter"):
        _vm_buffer_reset(username)
    elif action in ("key", "press") and text.strip().lower() in ("enter", "return", "tab", "esc", "escape"):
        _vm_buffer_reset(username)

    return None


def _vm_keyboard_blocked(action: str, args: str, username: str) -> bool:
    """
    Convenience wrapper for the VM chat-command dispatchers: runs the
    danger check (if VM_DANGER_FILTER_ENABLED), logs + announces a block
    if triggered, and returns True/False so call sites can just do
    `if _vm_keyboard_blocked(...): continue`.
    """
    if not VM_DANGER_FILTER_ENABLED:
        return False
    reason = _vm_is_dangerous(action, args, username)
    if reason:
        print(f"[VM] BLOCKED ({reason}) — from {username}: !{action} {args!r}")
        _append_event("VM_BLOCKED", username, f"!{action} {args!r} — {reason}")
        # Visible on the stream overlay too — otherwise a blocked command
        # just silently does nothing from the viewer's perspective, which
        # looks like the bot ignored their message rather than actively
        # rejecting it.
        update_status(f"🛡 Blocked command from {username}", transient=True)
        return True
    return False


def _realpc_execute(username: str, action: str, args: str):
    """
    Execute a single Real-PC command.
    action : command name without !  (e.g. 'type', 'click', 'combo')
    args   : everything after the command word
    """
    if not _PYAUTOGUI_OK:
        return

    # ── HARD SAFETY FILTER — dangerous OS-level commands ──
    # Runs first, independent of every other setting. Can only be disabled
    # from the GUI, which requires two explicit warning confirmations.
    if REALPC_CONFIG.get("danger_filter_enabled", True):
        reason = _realpc_is_dangerous(action, args, username)
        if reason:
            print(f"[RealPC] BLOCKED ({reason}) — from {username}: !{action} {args!r}")
            _realpc_set_status(f"⛔ Blocked dangerous command from {username}")
            _append_event("REALPC_BLOCKED", username, f"!{action} {args!r} — {reason}")
            return

    # Text-Only mode: only !type, !send (and aliases) are permitted
    TEXT_ONLY_ACTIONS = {"type", "write", "text", "say", "send", "sendline", "typeenter"}
    if REALPC_CONFIG.get("text_only", False) and action not in TEXT_ONLY_ACTIONS:
        print(f"[RealPC] Text-only mode — blocked: !{action} from {username}")
        return

    allowed = REALPC_CONFIG.get("allowed_actions", {})

    try:
        # ── Wait / Sleep ──
        if action in ("wait", "sleep", "delay"):
            try:
                seconds = max(0.0, min(10.0, float(args.strip())))
            except (ValueError, AttributeError):
                seconds = 0.5
            time.sleep(seconds)
            _append_event("REALPC_CMD", username, f"wait {seconds}s")

        # ── Keyboard ──
        elif action in ("type", "write", "text", "say"):
            if not allowed.get("keyboard", True):
                return
            text = args[:REALPC_CONFIG.get("max_type_length", 100)]
            pyautogui.write(text, interval=0.03)
            _append_event("REALPC_CMD", username, f"type: {text!r}")

        elif action in ("key", "press"):
            if not allowed.get("keyboard", True):
                return
            key = args.strip().lower()
            if key:
                pyautogui.press(key)
                _append_event("REALPC_CMD", username, f"key: {key}")

        elif action in ("combo", "hotkey"):
            if not allowed.get("combo", True):
                return
            keys = [k.strip() for k in args.replace("+", " ").split() if k.strip()]
            if keys:
                pyautogui.hotkey(*keys)
                _append_event("REALPC_CMD", username, f"combo: {'+'.join(keys)}")

        elif action == "enter":
            if not allowed.get("keyboard", True):
                return
            pyautogui.press("enter")
            _append_event("REALPC_CMD", username, "enter")

        elif action == "space":
            if not allowed.get("keyboard", True):
                return
            pyautogui.press("space")
            _append_event("REALPC_CMD", username, "space")

        elif action == "backspace":
            if not allowed.get("keyboard", True):
                return
            pyautogui.press("backspace")
            _append_event("REALPC_CMD", username, "backspace")

        elif action in ("send", "sendline", "typeenter"):
            if not allowed.get("keyboard", True):
                return
            text = args[:REALPC_CONFIG.get("max_type_length", 100)]
            pyautogui.write(text, interval=0.03)
            pyautogui.press("enter")
            _append_event("REALPC_CMD", username, f"send: {text!r}")

        # ── Mouse ──
        elif action in ("click", "lclick"):
            if not allowed.get("mouse", True):
                return
            nums = _parse_two_ints(args)
            if nums:
                pyautogui.click(nums[0], nums[1])
            else:
                pyautogui.click()
            _append_event("REALPC_CMD", username, f"click {args.strip()}")

        elif action in ("rclick", "rightclick"):
            if not allowed.get("mouse", True):
                return
            nums = _parse_two_ints(args)
            if nums:
                pyautogui.rightClick(nums[0], nums[1])
            else:
                pyautogui.rightClick()
            _append_event("REALPC_CMD", username, f"rclick {args.strip()}")

        elif action in ("dclick", "doubleclick"):
            if not allowed.get("mouse", True):
                return
            nums = _parse_two_ints(args)
            if nums:
                pyautogui.doubleClick(nums[0], nums[1])
            else:
                pyautogui.doubleClick()
            _append_event("REALPC_CMD", username, f"dclick {args.strip()}")

        elif action == "move":
            if not allowed.get("mouse", True):
                return
            direction = args.strip().lower()
            step = REALPC_CONFIG.get("mouse_step", 50)
            dx, dy = 0, 0
            if   direction in ("up",    "u"): dy = -step
            elif direction in ("down",  "d"): dy =  step
            elif direction in ("left",  "l"): dx = -step
            elif direction in ("right", "r"): dx =  step

            if dx or dy:
                pyautogui.moveRel(dx, dy, duration=0.15)
                _append_event("REALPC_CMD", username, f"move {direction}")
            else:
                nums = _parse_two_ints(args)
                if nums:
                    pyautogui.moveTo(nums[0], nums[1], duration=0.2)
                    _append_event("REALPC_CMD", username, f"move {nums[0]} {nums[1]}")

        elif action in ("moveto", "abs", "cursor", "moveabs"):
            if not allowed.get("mouse", True):
                return
            nums = _parse_two_ints(args)
            if nums:
                pyautogui.moveTo(nums[0], nums[1], duration=0.2)
                _append_event("REALPC_CMD", username, f"move {nums[0]} {nums[1]}")

        elif action in ("moverel", "mv", "rel"):
            if not allowed.get("mouse", True):
                return
            step = REALPC_CONFIG.get("mouse_step", 50)
            direction = args.strip().lower()
            dx, dy = 0, 0
            if   direction in ("up",    "u"): dy = -step
            elif direction in ("down",  "d"): dy =  step
            elif direction in ("left",  "l"): dx = -step
            elif direction in ("right", "r"): dx =  step
            else:
                nums = _parse_two_ints(args)
                if nums: dx, dy = nums[0], nums[1]
            if dx or dy:
                pyautogui.moveRel(dx, dy, duration=0.15)
                _append_event("REALPC_CMD", username, f"moverel {dx} {dy}")

        elif action in ("scroll", "wheel"):
            if not allowed.get("mouse", True):
                return
            try:
                amount = int(args.strip()) if args.strip() else REALPC_CONFIG.get("scroll_step", 3)
            except ValueError:
                amount = REALPC_CONFIG.get("scroll_step", 3)
            pyautogui.scroll(amount)
            _append_event("REALPC_CMD", username, f"scroll {amount}")

        elif action in ("drag", "dragrel"):
            if not allowed.get("mouse", True):
                return
            nums = _parse_two_ints(args)
            if nums:
                pyautogui.dragRel(nums[0], nums[1], duration=0.3, button="left")
                _append_event("REALPC_CMD", username, f"drag {nums[0]} {nums[1]}")

        # ── Screenshot ──
        elif action in ("screenshot", "ss", "snap"):
            if not allowed.get("screenshot", True):
                return
            img   = pyautogui.screenshot()
            fname = f"realpc_screenshot_{int(time.time())}.png"
            img.save(fname)
            _realpc_set_status(f"Screenshot saved: {fname}")
            _append_event("REALPC_CMD", username, f"screenshot → {fname}")

        # ── Info ──
        elif action in ("pos", "position", "cursor"):
            x, y = pyautogui.position()
            _realpc_set_status(f"Cursor: x={x}  y={y}")
            _append_event("REALPC_CMD", username, f"pos → {x},{y}")

        elif action in ("size", "screen", "resolution"):
            w, h = pyautogui.size()
            _realpc_set_status(f"Screen: {w}×{h}")
            _append_event("REALPC_CMD", username, f"size → {w}x{h}")

        else:
            print(f"[RealPC] Unknown command '!{action}' from {username}")

    except pyautogui.FailSafeException:
        _realpc_set_status("FAILSAFE triggered — mouse moved to corner.")
        _append_event("REALPC_FAILSAFE", username, "failsafe triggered")
    except Exception as e:
        print(f"[RealPC] Execute error (!{action}): {e}")
        _append_event("REALPC_ERROR", username, f"!{action}: {e}")


def _parse_two_ints(s: str):
    """Parse 'x y' or 'x,y' from a string. Returns (x, y) tuple or None."""
    try:
        nums = [int(n) for n in re.split(r"[\s,]+", s.strip()) if n]
        if len(nums) >= 2:
            return nums[0], nums[1]
    except (ValueError, AttributeError):
        pass
    return None


def _realpc_bot_loop():
    """Background thread: connects to YouTube chat and processes !command style messages."""
    vid = REALPC_CONFIG.get("video_id", "").strip()
    if not vid:
        _realpc_set_status("No Video ID configured.")
        return
    if not _PYAUTOGUI_OK:
        _realpc_set_status("pyautogui not installed. Run: pip install pyautogui")
        return
    if not (_PYTCHAT_OK or _CHAT_DOWNLOADER_OK or (_GOOGLE_API_OK and YOUTUBE_API_KEY)):
        _realpc_set_status("No chat backend available. Run: pip install pytchat "
                            "(or chat-downloader / google-api-python-client)")
        return

    wl_only   = REALPC_CONFIG.get("whitelist_only", False)
    whitelist = {normalize_username(u) for u in REALPC_CONFIG.get("whitelist", [])}
    blocked   = {normalize_username(u) for u in REALPC_CONFIG.get("blocked",   [])}

    pyautogui.FAILSAFE = REALPC_CONFIG.get("failsafe", False)
    pyautogui.PAUSE    = REALPC_CONFIG.get("action_delay", 0.05)

    _realpc_set_status(f"Connecting to stream: {vid}")
    chat = YouTubeChatSource(vid, api_key=YOUTUBE_API_KEY)
    if not chat.connect():
        _realpc_set_status("Connection failed.")
        return

    _dedup = _MessageDedup()
    _realpc_set_status("Listening — commands: !type  !send  !combo  !click  !move  etc.")

    while not _realpc_stop_event.is_set():
        if not chat.is_alive():
            _realpc_set_status("Chat ended or disconnected.")
            break
        try:
            for msg_obj in chat.get_messages():
                if _realpc_stop_event.is_set():
                    break
                if _dedup.is_duplicate(msg_obj.id):
                    continue

                user = normalize_username(msg_obj.author_name)
                msg  = msg_obj.text.strip()

                if not msg or not msg.startswith("!"):
                    continue
                if user in blocked:
                    continue
                if wl_only and user not in whitelist:
                    continue
                if not _realpc_check_cooldown(user):
                    continue

                # Chain parse: split on "!" boundaries to support
                # "!combo win+r !wait 1 !send cmd" style messages
                # Split on every "!" that follows a space (or is at start)
                import re as _re
                raw_chain = msg.strip()
                # Split at every "!" that starts a new token
                # e.g. "!combo win+r !wait 1 !send cmd"
                # → ["combo win+r", "wait 1", "send cmd"]
                segments = [s.strip() for s in _re.split(r'\s+(?=!)', raw_chain)]
                # Each segment starts with "!" — strip it
                commands = []
                _prev_action_was_wait = False
                for seg in segments:
                    if seg.startswith("!"):
                        seg = seg[1:].strip()
                    if not seg:
                        continue
                    parts  = seg.split(maxsplit=1)
                    action = parts[0].lower()
                    args   = parts[1] if len(parts) > 1 else ""

                    # Skip chained wait/sleep/delay commands that immediately
                    # follow another wait/sleep/delay — otherwise they stack
                    # up (e.g. "!wait 5!wait 5!wait 5" sleeps 15s instead of
                    # 5s). Only the first wait in a run is honored.
                    _is_wait_action = action in ("wait", "sleep", "delay")
                    if _is_wait_action and _prev_action_was_wait:
                        _prev_action_was_wait = _is_wait_action
                        continue
                    _prev_action_was_wait = _is_wait_action

                    commands.append((action, args))

                if not commands:
                    continue

                chain_str = "  →  ".join(
                    f"!{a} {g}".strip() for a, g in commands)
                _append_event("REALPC_MSG", user, chain_str)

                def _run_chain(cmds=commands, u=user):
                    for action, args in cmds:
                        if _realpc_stop_event.is_set():
                            break
                        _realpc_execute(u, action, args)

                threading.Thread(target=_run_chain, daemon=True).start()

        except Exception as e:
            if not _realpc_stop_event.is_set():
                print(f"[RealPC] Loop error: {e}")

        if _realpc_stop_event.wait(0.05):
            break

    if chat:
        try: chat.terminate()
        except Exception: pass
    _realpc_set_status("Stopped.")


def start_realpc_bot():
    global _realpc_bot_thread
    if _realpc_bot_thread and _realpc_bot_thread.is_alive():
        return False
    _realpc_stop_event.clear()
    _realpc_bot_thread = threading.Thread(
        target=_realpc_bot_loop, daemon=True, name="realpc_bot"
    )
    _realpc_bot_thread.start()
    return True


def stop_realpc_bot():
    _realpc_stop_event.set()

# ========================= EVENT LOG =========================
EVENT_LOG_FILE = "event_log.json"
_event_log = []                # list of dicts written at runtime
_event_log_lock = threading.Lock()

def _append_event(event_type: str, username: str, detail: str = ""):
    """Append a timestamped event to the in-memory log (and persist to disk)."""
    entry = {
        "ts":      time.strftime("%Y-%m-%d %H:%M:%S"),
        "type":    event_type,
        "user":    username,
        "detail":  detail,
    }
    with _event_log_lock:
        _event_log.append(entry)
        # Keep the last 5000 events in memory; trim older ones silently
        if len(_event_log) > 5000:
            del _event_log[:-5000]
    _persist_event_log()

def _persist_event_log():
    """Write the full event log to disk (non-blocking)."""
    def _write():
        try:
            with _event_log_lock:
                snapshot = list(_event_log)
            with open(EVENT_LOG_FILE, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[EventLog] Write error: {e}")
    threading.Thread(target=_write, daemon=True).start()

def load_event_log():
    global _event_log
    try:
        if os.path.exists(EVENT_LOG_FILE):
            with open(EVENT_LOG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            with _event_log_lock:
                _event_log = data if isinstance(data, list) else []
            print(f"[EventLog] Loaded {len(_event_log)} entries.")
    except Exception as e:
        print(f"[EventLog] Load error: {e}")
        _event_log = []

# ========================= PERMISSIONS CONFIG =========================
PERMISSIONS_CONFIG_FILE = "permissions_config.json"
# Default required-votes table (overridden by GUI / config file)
PERMISSIONS_CONFIG = {
    "restart_votes":   2,
    "revert_votes":    2,
    "ban_votes":       3,
    "action_cooldown": 60,   # seconds between restart/revert actions
}

def load_permissions_config():
    try:
        if os.path.exists(PERMISSIONS_CONFIG_FILE):
            with open(PERMISSIONS_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            PERMISSIONS_CONFIG.update(data)
            print("[Permissions] Config loaded.")
    except Exception as e:
        print(f"[Permissions] Load error: {e}")

def save_permissions_config():
    try:
        with open(PERMISSIONS_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(PERMISSIONS_CONFIG, f, indent=2)
        print("[Permissions] Config saved.")
    except Exception as e:
        print(f"[Permissions] Save error: {e}")

# ========================= SOUND & TTS CONFIG =========================
SOUND_CONFIG_FILE = "sound_config.json"
SOUND_CONFIG = {
    "success_sound":    "success.mp3",
    "revert_sound":     "",
    "restart_sound":    "",
    "ban_sound":        "",
    "os_switch_sound":  "",
    "tts_enabled":      True,
    "tts_rate":         150,        # words per minute (SAPI default ~150)
    "tts_volume":       100,        # 0-100
}

def load_sound_config():
    global SUCCESS_SOUND_FILE
    try:
        if os.path.exists(SOUND_CONFIG_FILE):
            with open(SOUND_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            SOUND_CONFIG.update(data)
            SUCCESS_SOUND_FILE = SOUND_CONFIG.get("success_sound", "success.mp3")
            print("[Sound] Config loaded.")
    except Exception as e:
        print(f"[Sound] Load error: {e}")

def save_sound_config():
    try:
        with open(SOUND_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(SOUND_CONFIG, f, indent=2)
        print("[Sound] Config saved.")
    except Exception as e:
        print(f"[Sound] Save error: {e}")

def play_event_sound(event_key: str):
    """Play the sound file configured for a specific event key."""
    sound_file = SOUND_CONFIG.get(event_key, "")
    if not sound_file:
        return
    def _play():
        try:
            subprocess.Popen(['start', sound_file], shell=True)
        except Exception as err:
            print(f"[Sound] Error playing '{sound_file}': {err}")
    threading.Thread(target=_play, daemon=True).start()

# ========================= NEXOAI (GROQ CHAT) CONFIG =========================
NEXOAI_CONFIG_FILE = "nexoai_config.json"
NEXOAI_CONFIG_DEFAULT_PROMPT = (
    "You are NexoAI, the built-in AI assistant of Nexovative Control Center "
    "(a YouTube livestream chat-bot / VirtualBox control app). You run on "
    "Groq's LPU infrastructure. Introduce yourself as NexoAI if asked who "
    "you are, and don't claim to be ChatGPT, Gemini, or any other assistant. "
    "Be concise, friendly, and helpful."
)
NEXOAI_CONFIG = {
    "groq_api_key": "",                        # saved once entered, never shown again in plain sight after restart
    "model":        "llama-3.3-70b-versatile",  # default Groq model
    "system_prompt": NEXOAI_CONFIG_DEFAULT_PROMPT,
}
GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS_URL           = "https://api.groq.com/openai/v1/models"

# urllib's default "Python-urllib/x.y" User-Agent gets blocked by Cloudflare
# (which fronts api.groq.com) as an automated-request signature — that's
# Cloudflare error 1010, not an actual Groq/API-key problem. Sending a
# normal browser-style User-Agent avoids it.
GROQ_REQUEST_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json",
}

# A reasonable, hand-maintained fallback list — used if we can't reach
# Groq's /models endpoint (e.g. no key yet, or offline) so the dropdown
# is never empty.
NEXOAI_FALLBACK_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "llama3-70b-8192",
    "llama3-8b-8192",
    "mixtral-8x7b-32768",
    "gemma2-9b-it",
]


def load_nexoai_config():
    try:
        if os.path.exists(NEXOAI_CONFIG_FILE):
            with open(NEXOAI_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            NEXOAI_CONFIG.update(data)
            print("[NexoAI] Config loaded.")
    except Exception as e:
        print(f"[NexoAI] Load error: {e}")


def save_nexoai_config():
    try:
        with open(NEXOAI_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(NEXOAI_CONFIG, f, indent=2)
        print("[NexoAI] Config saved.")
    except Exception as e:
        print(f"[NexoAI] Save error: {e}")


def groq_list_models(api_key: str):
    """
    Fetches the list of available model IDs from Groq's /models endpoint.
    Returns a list of model id strings, or the fallback list on any error
    (bad key, no internet, endpoint change, etc.) so the caller never has
    to special-case failure.
    """
    if not api_key:
        return list(NEXOAI_FALLBACK_MODELS)
    try:
        req = urllib.request.Request(
            GROQ_MODELS_URL,
            headers={**GROQ_REQUEST_HEADERS, "Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        ids = [m.get("id") for m in data.get("data", []) if m.get("id")]
        return sorted(ids) if ids else list(NEXOAI_FALLBACK_MODELS)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body).get("error", {}).get("message", body)
        except Exception:
            detail = body
        print(f"[NexoAI] Could not fetch model list (HTTP {e.code}): {detail} — using fallback list.")
        return list(NEXOAI_FALLBACK_MODELS)
    except Exception as e:
        print(f"[NexoAI] Could not fetch model list, using fallback list: {e}")
        return list(NEXOAI_FALLBACK_MODELS)


def groq_chat_completion(api_key: str, model: str, messages: list):
    """
    Sends a chat completion request to Groq (OpenAI-compatible endpoint).
    messages: list of {"role": "user"/"assistant"/"system", "content": str}
    Returns the assistant's reply text.
    Raises an exception on any failure — the caller is expected to catch
    it and show the message to the user.
    """
    if not api_key:
        raise ValueError("No Groq API key set. Enter one in the NexoAI tab first.")

    payload = json.dumps({
        "model":    model,
        "messages": messages,
    }).encode("utf-8")

    req = urllib.request.Request(
        GROQ_CHAT_COMPLETIONS_URL,
        data=payload,
        method="POST",
        headers={
            **GROQ_REQUEST_HEADERS,
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            body_json = json.loads(body)
            detail = body_json.get("error", {}).get("message", body)
        except Exception:
            detail = body
        raise ValueError(f"Groq API error (HTTP {e.code}): {detail}") from None

    choices = data.get("choices", [])
    if not choices:
        raise ValueError(f"Groq returned no response: {data}")
    return choices[0]["message"]["content"]



# ========================= MULTI-STREAM CONFIG =========================
MULTI_STREAM_CONFIG_FILE = "multi_stream_config.json"
MULTI_STREAM_CONFIG = {
    "video_ids": [],       # list of YouTube video IDs to monitor simultaneously
}
_multi_stream_bots = []        # list of running YouTubeChatBotSecondary instances

def load_multi_stream_config():
    try:
        if os.path.exists(MULTI_STREAM_CONFIG_FILE):
            with open(MULTI_STREAM_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            MULTI_STREAM_CONFIG.update(data)
            print(f"[MultiStream] Config loaded. {len(MULTI_STREAM_CONFIG['video_ids'])} extra stream(s).")
    except Exception as e:
        print(f"[MultiStream] Load error: {e}")

def save_multi_stream_config():
    try:
        with open(MULTI_STREAM_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(MULTI_STREAM_CONFIG, f, indent=2)
        print("[MultiStream] Config saved.")
    except Exception as e:
        print(f"[MultiStream] Save error: {e}")

# ========================= SCHEDULER CONFIG =========================
SCHEDULER_CONFIG_FILE = "scheduler_config.json"
SCHEDULER_CONFIG = {
    "enabled": False,
    "tasks":   [],
    # Each task: {"id": str, "label": str, "action": "revert"|"restart",
    #             "days": [0-6], "hour": int, "minute": int, "last_run": "YYYY-MM-DD"}
}
_scheduler_last_tick = ""   # "HH:MM" of last scheduler check to avoid double-fire

def load_scheduler_config():
    try:
        if os.path.exists(SCHEDULER_CONFIG_FILE):
            with open(SCHEDULER_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            SCHEDULER_CONFIG.update(data)
            print(f"[Scheduler] Config loaded. {len(SCHEDULER_CONFIG['tasks'])} task(s).")
    except Exception as e:
        print(f"[Scheduler] Load error: {e}")

def save_scheduler_config():
    try:
        with open(SCHEDULER_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(SCHEDULER_CONFIG, f, indent=2)
        print("[Scheduler] Config saved.")
    except Exception as e:
        print(f"[Scheduler] Save error: {e}")

def _run_scheduled_action(action: str, label: str):
    """Execute a scheduled revert or restart in a background thread."""
    print(f"[Scheduler] Running scheduled task '{label}' → {action}")
    notify("Scheduled Task", f"{action.capitalize()} triggered by scheduler: {label}")
    _append_event("SCHEDULER", "scheduler", f"{action} / {label}")
    if action == "revert":
        def _do_revert():
            global revert_in_progress
            if revert_in_progress:
                print("[Scheduler] Revert already in progress, skipping.")
                return
            revert_in_progress = True
            update_status("Scheduled revert...")
            speak_text("Scheduled revert starting...")
            try:
                ok, _ = retry_vbox(
                    lambda: subprocess.run([VBOXMANAGE_PATH, 'controlvm', VM_NAME, 'poweroff'], check=True),
                    attempts=3, delay=3, source="Scheduler/poweroff"
                )
                time.sleep(3)
                ok2, _ = retry_vbox(
                    lambda: subprocess.run([VBOXMANAGE_PATH, 'snapshot', VM_NAME, 'restorecurrent'], check=True),
                    attempts=3, delay=3, source="Scheduler/snapshot"
                )
                time.sleep(3)
                ok3, _ = retry_vbox(
                    lambda: subprocess.run([VBOXMANAGE_PATH, 'startvm', VM_NAME], check=True),
                    attempts=3, delay=4, source="Scheduler/startvm"
                )
                if ok2 and ok3:
                    update_status("Running")
                    play_success_sound()
                    obs_trigger("revert_done")
                    _stats["reverts"] += 1
                else:
                    update_status("Scheduled revert failed")
                    log_error("Scheduler", "Scheduled revert failed")
            finally:
                revert_in_progress = False
        threading.Thread(target=_do_revert, daemon=True).start()
    elif action == "restart":
        def _do_restart():
            global restart_in_progress
            if restart_in_progress:
                print("[Scheduler] Restart already in progress, skipping.")
                return
            restart_in_progress = True
            update_status("Scheduled restart...")
            speak_text("Scheduled restart starting...")
            try:
                ok, _ = retry_vbox(
                    lambda: subprocess.run([VBOXMANAGE_PATH, 'controlvm', VM_NAME, 'reset'], check=True),
                    attempts=3, delay=3, source="Scheduler/restart"
                )
                if ok:
                    update_status("Running")
                    play_success_sound()
                    obs_trigger("restart")
                    _stats["restarts"] += 1
                else:
                    update_status("Scheduled restart failed")
                    log_error("Scheduler", "Scheduled restart failed")
            finally:
                restart_in_progress = False
        threading.Thread(target=_do_restart, daemon=True).start()

def scheduler_loop():
    """Background thread: fires scheduled tasks at the correct time."""
    global _scheduler_last_tick
    while not bot_stop_event.is_set():
        if bot_stop_event.wait(15):
            break
        if not SCHEDULER_CONFIG.get("enabled"):
            continue
        now = time.localtime()
        tick = f"{now.tm_hour:02d}:{now.tm_min:02d}"
        today_str = time.strftime("%Y-%m-%d")
        if tick == _scheduler_last_tick:
            continue
        _scheduler_last_tick = tick
        for task in SCHEDULER_CONFIG.get("tasks", []):
            try:
                days_ok = (not task.get("days")) or (now.tm_wday in task["days"])
                time_ok = (task.get("hour") == now.tm_hour and
                           task.get("minute") == now.tm_min)
                if not (days_ok and time_ok):
                    continue
                if task.get("last_run") == today_str:
                    continue
                task["last_run"] = today_str
                save_scheduler_config()
                _run_scheduled_action(task.get("action", "revert"), task.get("label", "unnamed"))
            except Exception as e:
                log_error("Scheduler", e)
    print("[Scheduler] Loop stopped.")

_update_splash(85, "Connecting to VirtualBox...")
mgr  = None
vbox = None
if _VBOXAPI_OK:
    try:
        mgr  = VirtualBoxManager(None, None)
        vbox = mgr.getVirtualBox()
    except Exception as e:
        mgr  = None
        vbox = None
        print(f"[Startup] Could not connect to VirtualBox: {e}. "
              "VirtualBox-dependent features will be disabled.")
_update_splash(92, "Loading configuration...")

active_users = set()
bot_stop_event = threading.Event()
TEST_MODE_ENABLED = False

# ========================= ERROR RECOVERY SYSTEM =========================
ERROR_LOG_FILE = "error_log.txt"

def log_error(source, error, extra=""):
    """Append a timestamped error entry to error_log.txt."""
    try:
        ts  = time.strftime("%Y-%m-%d %H:%M:%S")
        msg = f"[{ts}] [{source}] {error}"
        if extra:
            msg += f" | {extra}"
        with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
        print(f"[ErrorLog] {msg}")
    except Exception as e:
        print(f"[ErrorLog] Could not write log: {e}")

def retry_vbox(fn, attempts=3, delay=3, source="VBox"):
    """
    Calls fn() up to `attempts` times with `delay` seconds between tries.
    Returns (success: bool, last_exception).
    fn must be a zero-argument callable wrapping a VBoxManage/subprocess call.
    """
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            fn()
            return True, None
        except Exception as e:
            last_exc = e
            log_error(source, f"Attempt {attempt}/{attempts} failed: {e}")
            if attempt < attempts:
                time.sleep(delay)
    return False, last_exc

def _global_exception_handler(exc_type, exc_value, exc_tb):
    """Catch any otherwise-unhandled exception, log it and show a notification."""
    import traceback
    tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    log_error("UNCAUGHT", exc_value, tb_str.strip())
    notify("Unexpected Error", f"{exc_type.__name__}: {exc_value}", timeout=8)

sys.excepthook = _global_exception_handler


def run_test_mode():
    """
    Test mode: read commands from stdin and execute them exactly as if
    they came from a chat message, without needing a YouTube connection.
    Type  !quit  or  !exit  to stop test mode.
    Supports all bot commands: !type, !send, !click, !combo, !key, etc.
    Also supports OS-voting triggers if OS Voting is enabled.
    """
    print("[TestMode] Started. Type commands (e.g. '!type hello', '!click', '!win7'). Type '!quit' to stop.")
    print("[TestMode] All normal bot commands are supported.")
    while not bot_stop_event.is_set():
        try:
            line = input("[TestMode] > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line.lower() in ("!quit", "!exit", "!stop"):
            print("[TestMode] Stopping test mode.")
            bot_stop_event.set()
            break

        # Parse exactly like the chat loop does
        if not line.startswith("!"):
            print("[TestMode] Commands must start with '!' — e.g. !type hello")
            continue

        parts = line[1:].split(" ", 1)
        cmd   = parts[0].lower().strip()
        args  = parts[1].strip() if len(parts) > 1 else ""

        # OS voting triggers
        if OS_VOTING_ENABLED:
            os_trigger_map = get_os_trigger_map()
            if cmd in os_trigger_map:
                target_entry = os_trigger_map[cmd]
                print(f"[TestMode] Owner-bypass OS switch → {target_entry['name']}")
                threading.Thread(target=switch_os, args=(target_entry,), daemon=True).start()
                continue

        # Custom commands
        trigger = "!" + cmd
        if trigger in custom_commands:
            threading.Thread(target=execute_custom_command, args=(trigger,), daemon=True).start()
            continue

        # Built-in commands
        try:
            if cmd in ("type", "text", "say"):
                send_keyboard(args)
            elif cmd in ("send", "sendenter", "typeenter", "sendline"):
                send_keyboard(args)
                time.sleep(0.05)
                send_special_enter()
            elif cmd == "enter":
                send_special_enter()
            elif cmd in ("key", "press"):
                k = args.lower().strip()
                if k in SCANCODES:
                    send_scancode(SCANCODES[k][0])
                    time.sleep(0.01)
                    send_scancode(SCANCODES[k][1])
                else:
                    send_keyboard(k)
            elif cmd in ("combo", "chord", "multi"):
                keys = args.lower().replace("+", " ").split()
                if keys:
                    send_combo(keys)
            elif cmd in ("click", "lclick", "rclick", "rightclick",
                         "mclick", "middleclick", "move", "mouse", "mv",
                         "abs", "cursor", "moveabs", "drag", "dragrel",
                         "holdclick", "holdrclick",
                         "dragabs", "drag_absolute", "scroll", "wheel"):
                handle_mouse(cmd, args)
            elif cmd in ("startvm", "launchvm"):
                start_vm()
            elif cmd in ("restore", "focus", "front"):
                restore_window()
            elif cmd == "run":
                send_combo(["win", "r"])
            elif cmd in ("wait", "pause", "delay"):
                try:
                    delay = max(0, min(float(args), 5.0))
                    time.sleep(delay)
                except ValueError:
                    pass
            else:
                print(f"[TestMode] Unknown command: !{cmd}")
                continue
            print(f"[TestMode] OK: !{cmd} {args}")
        except Exception as e:
            print(f"[TestMode] Error executing !{cmd}: {e}")
    print("[TestMode] Stopped.")
vote_restart = {}
vote_revert  = {}
banned_users = {}
ban_votes    = {}
restart_start_time = None
revert_start_time  = None
revert_in_progress   = False
restart_in_progress  = False

# ========================= STATISTICS =========================
_stats = {
    "total_commands":   0,
    "session_commands": 0,
    "os_switches":      0,
    "reverts":          0,
    "restarts":         0,
    "bot_start_time":   None,   # set when bot starts
    "command_counts":   {},     # {cmd_name: int}
    "user_counts":      {},     # {username: int}
}

def _record_command(cmd_name: str, username: str):
    """Call this every time a chat command is successfully dispatched."""
    _stats["total_commands"]   += 1
    _stats["session_commands"] += 1
    _stats["command_counts"][cmd_name] = _stats["command_counts"].get(cmd_name, 0) + 1
    _stats["user_counts"][username]    = _stats["user_counts"].get(username, 0) + 1
    _append_event("COMMAND", username, cmd_name)

def _reset_session_stats():
    _stats["session_commands"] = 0
    _stats["os_switches"]      = 0
    _stats["reverts"]          = 0
    _stats["restarts"]         = 0
    _stats["bot_start_time"]   = time.time()

# ========================= USER MANAGEMENT LISTS =========================
USER_MGMT_FILE = "user_mgmt.json"
whitelist_users = set()   # empty = disabled; non-empty = only these users can use commands
vip_users       = {}      # {username: {"votes_needed": int}}

def normalize_username(name: str) -> str:
    """
    Normalize a YouTube display name or user-typed name to a consistent
    lowercase key used for all comparisons.
    Strips leading/trailing whitespace, removes the @ prefix if present,
    strips Unicode invisible characters, and lowercases.
    """
    import unicodedata
    # Strip invisible / zero-width unicode chars
    name = "".join(ch for ch in name if unicodedata.category(ch) not in
                   ("Cf", "Cc", "Cs"))   # format, control, surrogate
    name = name.strip().lstrip("@").strip().lower()
    return name

def load_user_mgmt():
    global whitelist_users, vip_users
    try:
        if os.path.exists(USER_MGMT_FILE):
            with open(USER_MGMT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            whitelist_users = set(normalize_username(u) for u in data.get("whitelist", []))
            vip_users       = {normalize_username(k): v for k, v in data.get("vip", {}).items()}
            print(f"[UserMgmt] Loaded. whitelist={len(whitelist_users)}, vip={len(vip_users)}")
    except Exception as e:
        print(f"[UserMgmt] Load error: {e}")

def save_user_mgmt():
    try:
        with open(USER_MGMT_FILE, "w", encoding="utf-8") as f:
            json.dump({"whitelist": sorted(whitelist_users),
                       "vip":       vip_users}, f, indent=2, ensure_ascii=False)
        print("[UserMgmt] Saved.")
    except Exception as e:
        print(f"[UserMgmt] Save error: {e}")
AUTO_START_ENABLED = True   # if False, watchdog_restart will not auto-revive a powered-off VM
AUTO_START_CONFIG_FILE = "auto_start_config.json"

APPEARANCE_CONFIG_FILE = "appearance_config.json"

# ========================= OBS WEBSOCKET =========================
OBS_CONFIG_FILE = "obs_config.json"

try:
    import obsws_python as obs
    _OBS_LIB_OK = True
except ImportError:
    _OBS_LIB_OK = False
    print("[OBS] obsws-python not installed. Run: pip install obsws-python")

# Connection state
_obs_client    = None   # obsws_python.ReqClient instance when connected
_obs_connected = False

# Default config
OBS_CONFIG = {
    "enabled":  False,
    "host":     "localhost",
    "port":     4455,
    "password": "",
    # Scene triggers — {event_key: scene_name}  fully user-defined
    "triggers": {},
    # Per-OS scenes — {trigger_key: obs_scene_name}
    "os_scenes": {}
}

def load_obs_config():
    try:
        if os.path.exists(OBS_CONFIG_FILE):
            with open(OBS_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            OBS_CONFIG.update(data)
            print("[OBS] Config loaded.")
    except Exception as e:
        print(f"[OBS] Load error: {e}")

def save_obs_config():
    try:
        with open(OBS_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(OBS_CONFIG, f, indent=2)
        print("[OBS] Config saved.")
    except Exception as e:
        print(f"[OBS] Save error: {e}")

def obs_connect():
    global _obs_client, _obs_connected
    if not _OBS_LIB_OK:
        print("[OBS] obsws-python not installed.")
        return False
    try:
        _obs_client = obs.ReqClient(
            host=OBS_CONFIG["host"],
            port=int(OBS_CONFIG["port"]),
            password=OBS_CONFIG["password"],
            timeout=5
        )
        _obs_connected = True
        print(f"[OBS] Connected to {OBS_CONFIG['host']}:{OBS_CONFIG['port']}")
        return True
    except Exception as e:
        _obs_connected = False
        _obs_client    = None
        print(f"[OBS] Connection failed: {e}")
        return False

def obs_disconnect():
    global _obs_client, _obs_connected
    if _obs_client:
        try: _obs_client.base_client.ws.close()
        except Exception: pass
        _obs_client = None
    _obs_connected = False
    print("[OBS] Disconnected.")

def obs_set_scene(scene_name: str):
    """Switch to the given OBS scene. No-op if not connected or scene is empty."""
    if not _obs_connected or not _obs_client or not scene_name:
        return
    try:
        _obs_client.set_current_program_scene(scene_name)
        print(f"[OBS] Scene → '{scene_name}'")
    except Exception as e:
        print(f"[OBS] Scene switch error: {e}")
        log_error("OBS", e)

def obs_trigger(event: str):
    """Fire a named trigger event if OBS is enabled and connected."""
    if not OBS_CONFIG.get("enabled") or not _obs_connected:
        return
    scene = OBS_CONFIG["triggers"].get(event, "")
    if scene:
        threading.Thread(target=obs_set_scene, args=(scene,), daemon=True).start()



# Built-in theme presets
THEMES = {
    "Dark Purple (Default)": {
        "BG": "#0f0f1a", "BG2": "#16162a", "BG3": "#1e1e35",
        "ACCENT": "#7c5cbf", "ACCENT2": "#a07cdf",
        "TEXT": "#e8e8f0", "TEXTDIM": "#8888aa",
        "CONSOLE": "#0a0a14", "BORDER": "#2d2d50",
    },
    "Dark Blue": {
        "BG": "#0a0f1e", "BG2": "#101828", "BG3": "#1a2440",
        "ACCENT": "#2979ff", "ACCENT2": "#5c9eff",
        "TEXT": "#e0e8ff", "TEXTDIM": "#7080aa",
        "CONSOLE": "#070b14", "BORDER": "#1e2d55",
    },
    "Dark Green": {
        "BG": "#0a120a", "BG2": "#101a10", "BG3": "#162416",
        "ACCENT": "#2ecc71", "ACCENT2": "#58d68d",
        "TEXT": "#e0f0e0", "TEXTDIM": "#709070",
        "CONSOLE": "#070e07", "BORDER": "#1a301a",
    },
    "Dark Red": {
        "BG": "#140a0a", "BG2": "#1e1010", "BG3": "#2a1414",
        "ACCENT": "#e53935", "ACCENT2": "#ff6659",
        "TEXT": "#f0e0e0", "TEXTDIM": "#aa7070",
        "CONSOLE": "#0e0707", "BORDER": "#3a1a1a",
    },
    "Dark Orange": {
        "BG": "#14100a", "BG2": "#1e1810", "BG3": "#2a2014",
        "ACCENT": "#ff6d00", "ACCENT2": "#ff9e40",
        "TEXT": "#f0ebe0", "TEXTDIM": "#aa9070",
        "CONSOLE": "#0e0c07", "BORDER": "#3a2c1a",
    },
    "Light": {
        "BG": "#f4f4f8", "BG2": "#e8e8f0", "BG3": "#dcdce8",
        "ACCENT": "#7c5cbf", "ACCENT2": "#a07cdf",
        "TEXT": "#1a1a2e", "TEXTDIM": "#555570",
        "CONSOLE": "#ffffff", "BORDER": "#c0c0d8",
    },
    "Light Blue": {
        "BG": "#f0f4ff", "BG2": "#e0e8ff", "BG3": "#ccd8ff",
        "ACCENT": "#1565c0", "ACCENT2": "#1e88e5",
        "TEXT": "#0a1030", "TEXTDIM": "#445580",
        "CONSOLE": "#ffffff", "BORDER": "#b0c4ee",
    },
    "OLED Black": {
        "BG": "#000000", "BG2": "#0a0a0a", "BG3": "#121212",
        "ACCENT": "#bb86fc", "ACCENT2": "#e0b3ff",
        "TEXT": "#ffffff", "TEXTDIM": "#888888",
        "CONSOLE": "#000000", "BORDER": "#1e1e1e",
    },
}

def load_appearance_config():
    """Load saved appearance settings and apply them to NexovativeControlCenter class attributes."""
    try:
        if os.path.exists(APPEARANCE_CONFIG_FILE):
            with open(APPEARANCE_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            colors = data.get("colors", {})
            for key, val in colors.items():
                if hasattr(NexovativeControlCenter, key) and isinstance(val, str) and val.startswith("#"):
                    setattr(NexovativeControlCenter, key, val)
            font_size = data.get("font_size")
            if font_size:
                NexovativeControlCenter._FONT_SIZE = int(font_size)
            print("[Appearance] Config loaded.")
    except Exception as e:
        print(f"[Appearance] Load error: {e}")

def save_appearance_config(colors: dict, font_size: int):
    try:
        with open(APPEARANCE_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"colors": colors, "font_size": font_size}, f, indent=2)
        print("[Appearance] Config saved.")
    except Exception as e:
        print(f"[Appearance] Save error: {e}")

def load_auto_start_config():
    global AUTO_START_ENABLED
    try:
        if os.path.exists(AUTO_START_CONFIG_FILE):
            with open(AUTO_START_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            AUTO_START_ENABLED = bool(data.get("enabled", True))
            print(f"[AutoStart] Config loaded. Enabled={AUTO_START_ENABLED}")
    except Exception as e:
        print(f"[AutoStart] Load error: {e}")
        AUTO_START_ENABLED = True

def save_auto_start_config():
    try:
        with open(AUTO_START_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"enabled": AUTO_START_ENABLED}, f, indent=2)
        print(f"[AutoStart] Config saved. Enabled={AUTO_START_ENABLED}")
    except Exception as e:
        print(f"[AutoStart] Save error: {e}")

# ── VM Dangerous-Command / Base64-Payload Filter — master switch ──
# Controls _vm_is_dangerous / _vm_keyboard_blocked (see their definitions
# above). Default ON. Shown as a toggle on the Main tab since that's where
# the primary VM bot controls live, and the VM's screen is exactly what
# gets shown on stream.
VM_DANGER_FILTER_ENABLED = True
VM_DANGER_FILTER_CONFIG_FILE = "vm_danger_filter_config.json"

def load_vm_danger_filter_config():
    global VM_DANGER_FILTER_ENABLED
    try:
        if os.path.exists(VM_DANGER_FILTER_CONFIG_FILE):
            with open(VM_DANGER_FILTER_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            VM_DANGER_FILTER_ENABLED = bool(data.get("enabled", True))
            print(f"[VMDangerFilter] Config loaded. Enabled={VM_DANGER_FILTER_ENABLED}")
    except Exception as e:
        print(f"[VMDangerFilter] Load error: {e}")
        VM_DANGER_FILTER_ENABLED = True

def save_vm_danger_filter_config():
    try:
        with open(VM_DANGER_FILTER_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"enabled": VM_DANGER_FILTER_ENABLED}, f, indent=2)
        print(f"[VMDangerFilter] Config saved. Enabled={VM_DANGER_FILTER_ENABLED}")
    except Exception as e:
        print(f"[VMDangerFilter] Save error: {e}")

VOTE_ACTION_COOLDOWN = 60          # seconds after a restart/revert before another can be voted

# ========================= RECONNECT CONFIG =========================
RECONNECT_CONFIG_FILE = "reconnect_config.json"
RECONNECT_CONFIG = {
    "max_failures":      10,    # stop bot after this many consecutive failures (0 = infinite)
    "base_delay":         5,    # seconds to wait after first failure
    "max_delay":        120,    # cap on exponential backoff delay
    "notify_threshold":   3,    # desktop notification after this many consecutive failures
}

def load_reconnect_config():
    try:
        if os.path.exists(RECONNECT_CONFIG_FILE):
            with open(RECONNECT_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            RECONNECT_CONFIG.update(data)
            print("[Reconnect] Config loaded.")
    except Exception as e:
        print(f"[Reconnect] Load error: {e}")

def save_reconnect_config():
    try:
        with open(RECONNECT_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(RECONNECT_CONFIG, f, indent=2)
        print("[Reconnect] Config saved.")
    except Exception as e:
        print(f"[Reconnect] Save error: {e}")

# Global reference to the GUI app instance — set when the app is created.
# Used by background threads (bot loop, scheduler) to call GUI methods
# like _append_chat safely via root.after().
_gui_app = None
restart_cooldown_until = 0.0       # epoch time when restart cooldown expires
revert_cooldown_until  = 0.0       # epoch time when revert cooldown expires

# ========================= OS VOTING SYSTEM =========================
OS_VOTING_CONFIG_FILE = "os_voting_config.json"
OS_VOTE_STATUS_FILE   = "os_vote_status.html"
OS_VOTE_REQUIRED      = 3
OS_VOTE_TIMEOUT       = 120
OS_VOTE_SLOTS         = 15

OS_VOTING_ENABLED = False
OS_LIST = []   # list of dicts: {"name": str, "trigger": str, "vm": str}  (max 15 entries)

os_votes            = {}   # {trigger: set(usernames)}
os_vote_start_time  = None
os_switch_in_progress = False
os_switch_lock = threading.Lock()   # prevents concurrent switch_os calls
current_os_vm = None     # currently running OS's VM name (used as active VM_NAME target)

def load_os_voting_config():
    """Load the OS voting configuration (enabled flag + up to 5 OS entries) from disk."""
    global OS_VOTING_ENABLED, OS_LIST, current_os_vm
    try:
        if os.path.exists(OS_VOTING_CONFIG_FILE):
            with open(OS_VOTING_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            OS_VOTING_ENABLED = bool(data.get("enabled", False))
            OS_LIST = data.get("os_list", [])[:OS_VOTE_SLOTS]
            saved_vm = data.get("last_active_vm", "")
            if saved_vm:
                # Verify the saved VM still exists in the OS list before restoring it
                valid_vms = [e.get("vm", "") for e in OS_LIST if e.get("vm")]
                if saved_vm in valid_vms:
                    current_os_vm = saved_vm
                    print(f"[OSVoting] Restored last active VM: {saved_vm}")
                else:
                    current_os_vm = None
                    print(f"[OSVoting] Saved VM '{saved_vm}' no longer in OS list, ignoring.")
            print(f"[OSVoting] Config loaded. Enabled={OS_VOTING_ENABLED}, entries={len(OS_LIST)}")
    except Exception as e:
        print(f"[OSVoting] Load error: {e}")
        OS_VOTING_ENABLED = False
        OS_LIST = []

def save_os_voting_config():
    """Persist the OS voting configuration to disk."""
    try:
        data = {
            "enabled":        OS_VOTING_ENABLED,
            "os_list":        OS_LIST,
            "last_active_vm": current_os_vm or "",
        }
        with open(OS_VOTING_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[OSVoting] Config saved. Enabled={OS_VOTING_ENABLED}, entries={len(OS_LIST)}, last_vm={current_os_vm}")
    except Exception as e:
        print(f"[OSVoting] Save error: {e}")

def get_os_trigger_map():
    """Returns {trigger_lower: os_entry} for all valid, fully-configured OS entries."""
    result = {}
    for entry in OS_LIST:
        trig = (entry.get("trigger") or "").strip().lower().lstrip("!")
        vm   = (entry.get("vm") or "").strip()
        name = (entry.get("name") or "").strip()
        if trig and vm and name:
            result[trig] = entry
    return result

def update_os_vote_status():
    """Writes the current OS voting tally to OS_VOTE_STATUS_FILE for the stream overlay."""
    trigger_map = get_os_trigger_map()
    active_name = "—"
    for entry in OS_LIST:
        if entry.get("vm") == current_os_vm:
            active_name = entry.get("name", "—")
            break

    rows = ""
    for trig, entry in trigger_map.items():
        count   = len(os_votes.get(trig, set()))
        pct     = min(100, int(count / OS_VOTE_REQUIRED * 100))
        is_cur  = (entry.get("vm") == current_os_vm)
        bar_col = "#3ddc97" if is_cur else "#7c5cbf"
        name_style = "color:#3ddc97;font-weight:bold;" if is_cur else ""
        rows += f"""
        <div class="row">
          <div class="label-line">
            <span class="label" style="{name_style}">{entry['name']}</span>
            <span class="count" style="color:{bar_col};">{count}<span class="sep">/</span>{OS_VOTE_REQUIRED}</span>
          </div>
          <div class="bar-line">
            <div class="bar-wrap">
              <div class="bar" style="width:{pct}%;background:{bar_col};"></div>
            </div>
          </div>
        </div>"""

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
    *{{box-sizing:border-box;margin:0;padding:0;}}
    body{{
      background:transparent;
      font-family:'Segoe UI',Arial,sans-serif;
      color:white;
      text-shadow:1px 1px 3px rgba(0,0,0,0.9);
      padding:12px;
    }}
    #panel{{
      background:rgba(10,10,20,0.82);
      border:1px solid rgba(124,92,191,0.5);
      border-radius:18px;
      padding:20px 22px 16px;
      min-width:260px;
      max-width:320px;
      backdrop-filter:blur(6px);
    }}
    #title{{
      font-size:26px;
      font-weight:700;
      color:#b39ddb;
      letter-spacing:1px;
      text-align:center;
      margin-bottom:6px;
    }}
    #current{{
      font-size:16px;
      color:#3ddc97;
      text-align:center;
      margin-bottom:16px;
      opacity:0.9;
    }}
    .row{{
      display:flex;
      flex-direction:column;
      gap:6px;
      margin-bottom:14px;
    }}
    .label-line{{
      display:flex;
      align-items:baseline;
      justify-content:space-between;
    }}
    .label{{
      font-size:19px;
      font-weight:600;
      white-space:nowrap;
      overflow:hidden;
      text-overflow:ellipsis;
    }}
    .trigger{{
      font-size:13px;
      color:#aaa;
      font-weight:400;
      margin-left:6px;
    }}
    .bar-line{{
      display:flex;
      align-items:center;
      gap:10px;
    }}
    .bar-wrap{{
      flex:1;
      background:rgba(255,255,255,0.1);
      border-radius:9px;
      height:20px;
      overflow:hidden;
    }}
    .bar{{
      height:100%;
      border-radius:9px;
      transition:width 0.4s ease;
      min-width:4px;
    }}
    .count{{
      font-size:19px;
      font-weight:700;
      min-width:46px;
      text-align:right;
    }}
    .sep{{color:rgba(255,255,255,0.3);font-weight:300;margin:0 1px;}}
    #empty{{color:#888;font-size:16px;text-align:center;padding:8px 0;}}
    </style></head><body>
    <div id="panel">
      <div id="title">&#128229; OS Vote</div>
      <div id="current">Now running: <strong>{active_name}</strong></div>
      {rows if rows else '<div id="empty">No OS options configured.</div>'}
    </div>
    <script>setInterval(()=>location.reload(),8000);</script>
    </body></html>"""
    try:
        with open(OS_VOTE_STATUS_FILE, "w", encoding="utf-8") as f:
            f.write(html)
    except Exception as e:
        print(f"[OSVoting] Status write error: {e}")

def switch_os(target_entry, announce=True):
    """
    Powers off the current OS VM (if different) and boots the target OS VM.
    Retries startvm up to 3 times. If all attempts fail, tries to revive
    the previous (loser) VM so at least something is running.
    """
    global current_os_vm, VM_NAME, os_switch_in_progress, os_vote_start_time
    if not os_switch_lock.acquire(blocking=False):
        print("[OSVoting] Switch already in progress, ignoring duplicate request.")
        return
    os_switch_in_progress = True
    previous_vm = current_os_vm   # remember loser in case winner fails to start
    try:
        target_name = target_entry.get("name", "Unknown OS")
        target_vm   = target_entry.get("vm", "")
        if not target_vm:
            print("[OSVoting] Target entry has no VM assigned, aborting switch.")
            return
        if announce:
            speak_text(f"Switching to {target_name}...")
        update_status(f"Switching to {target_name}...")

        # Step 1: power off the loser (best-effort, non-fatal)
        if current_os_vm and current_os_vm != target_vm:
            ok, err = retry_vbox(
                lambda: subprocess.run(
                    [VBOXMANAGE_PATH, 'controlvm', current_os_vm, 'poweroff'], check=True
                ),
                attempts=3, delay=3, source="OSVoting/poweroff"
            )
            if not ok:
                log_error("OSVoting", f"Could not power off loser VM '{current_os_vm}': {err}")
            time.sleep(3)

        # Step 2: start the winner
        ok, err = retry_vbox(
            lambda: subprocess.run([VBOXMANAGE_PATH, 'startvm', target_vm], check=True),
            attempts=3, delay=4, source="OSVoting/startvm"
        )

        if ok:
            current_os_vm = target_vm
            VM_NAME = target_vm
            update_status(f"Running {target_name}")
            play_success_sound()
            play_event_sound("os_switch_sound")
            _append_event("OS_SWITCH", "vote", f"switched to {target_name}")
            notify("OS Switched", f"Now running: {target_name}")
            obs_trigger("os_switch")
            _stats["os_switches"] += 1
            # Per-OS scene: look up by trigger key
            trig_key = target_entry.get("trigger", "").strip().lower().lstrip("!")
            os_scene = OBS_CONFIG.get("os_scenes", {}).get(trig_key, "")
            if os_scene:
                threading.Thread(target=obs_set_scene, args=(os_scene,), daemon=True).start()
            save_os_voting_config()
            print(f"[OSVoting] Switched to '{target_name}' ({target_vm})")
        else:
            # Winner failed — attempt to revive the previous (loser) VM
            log_error("OSVoting", f"All startvm attempts failed for '{target_name}'", str(err))
            notify("OS Switch Failed",
                   f"Could not start {target_name}. Attempting to restore previous OS...",
                   timeout=7)
            update_status("OS switch failed — restoring previous OS...")
            if previous_vm and previous_vm != target_vm:
                ok2, err2 = retry_vbox(
                    lambda: subprocess.run([VBOXMANAGE_PATH, 'startvm', previous_vm], check=True),
                    attempts=3, delay=4, source="OSVoting/fallback"
                )
                if ok2:
                    update_status("Restored previous OS")
                    notify("Previous OS Restored", "The previous OS was brought back online.")
                    print(f"[OSVoting] Fallback: restored previous VM '{previous_vm}'")
                else:
                    log_error("OSVoting", f"Fallback also failed for '{previous_vm}'", str(err2))
                    notify("Critical: No VM Running",
                           "Both the target and previous OS failed to start. Check VirtualBox.",
                           timeout=10)
                    update_status("ERROR: no VM running")
            else:
                notify("OS Switch Failed", f"Could not start {target_name}. No previous OS to restore.", timeout=8)
    finally:
        os_votes.clear()
        os_vote_start_time = None
        update_os_vote_status()
        os_switch_in_progress = False
        os_switch_lock.release()

def os_vote_timeout_checker():
    """Background thread: clears stale OS votes after OS_VOTE_TIMEOUT seconds of inactivity."""
    global os_vote_start_time
    while not bot_stop_event.is_set():
        if bot_stop_event.wait(1):
            break
        if os_vote_start_time is not None:
            if time.time() - os_vote_start_time > OS_VOTE_TIMEOUT:
                os_votes.clear()
                os_vote_start_time = None
                update_os_vote_status()
                print("[OSVoting] Votes timed out")
    print("[OSVoting] Timeout checker stopped.")

COMMANDS_HELP = """
Commands (! prefix)
!restartvm / !revert  → dynamic vote required
!ban @user            → 3 votes to ban 30 min
!startvm, !modlaunch  → start VM
!restore / !focus     → bring VM to front
!move/!abs/!drag      → mouse control
!click / !rclick / !mclick / !scroll
!type / !send / !say  → keyboard text
!typeenter / !sendline
!key / !press / !combo / !chord
!keydown / !keyup
!wait / !pause        → delay
!votehelp / !clearvotes
!win7 !win8 ... → OS voting (if enabled in GUI)
"""

def _nexo_verify_speak():
    """
    Speaks the attribution line for the hidden !nexo0091 chat command.
    Deliberately bypasses SOUND_CONFIG's tts_enabled toggle and goes
    straight to SAPI — this exists specifically so it can't be silenced
    by turning TTS off in Settings, which would defeat its purpose.
    """
    def _speak():
        if not _WIN32COM_OK:
            print("[NexoVerify] pywin32 not installed — can't speak verification line.")
            return
        try:
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            speaker.Rate   = 0
            speaker.Volume = 100
            speaker.Speak("This stream is powered by Nexovative Script")
        except Exception as e:
            print(f"[NexoVerify] Speech error: {e}")
    threading.Thread(target=_speak, daemon=True).start()


def speak_text(text):
    if not SOUND_CONFIG.get("tts_enabled", True):
        return
    def _speak():
        if not _WIN32COM_OK:
            print("[Speech] pywin32 not installed — text-to-speech is disabled. Run: pip install pywin32")
            return
        try:
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            rate   = int(SOUND_CONFIG.get("tts_rate", 150))
            volume = int(SOUND_CONFIG.get("tts_volume", 100))
            # SAPI Rate: -10 to +10 (maps from words-per-minute ~50-400)
            # We convert: rate=150 → 0; rate=300 → +5; rate=50 → -5
            sapi_rate = max(-10, min(10, int((rate - 150) / 25)))
            speaker.Rate   = sapi_rate
            speaker.Volume = max(0, min(100, volume))
            speaker.Speak(text)
        except Exception as e:
            print(f"[Speech] Error: {e}")
    threading.Thread(target=_speak, daemon=True).start()

def send_keyboard(text):
    try:
        subprocess.run([VBOXMANAGE_PATH, 'controlvm', VM_NAME, 'keyboardputstring', text], check=True)
        print(f"[KB] Typed: {text}")
    except Exception as e:
        print(f"[KB] Error: {e}")

def send_scancode(scancode_str):
    try:
        bytes_list = [scancode_str[i:i+2] for i in range(0, len(scancode_str), 2)]
        for byte in bytes_list:
            subprocess.run([VBOXMANAGE_PATH, 'controlvm', VM_NAME, 'keyboardputscancode', byte], check=True)
            time.sleep(0.008)
    except Exception as e:
        print(f"[Scancode] Error: {e}")

# ── !hold / !keydown safety net ──
# Sending a key's "down" scancode with no guaranteed "up" leaves that key
# stuck held in the VM forever if a custom command's author forgets (or
# never intends) to add a matching "release" step. This tracks one
# pending auto-release timer per key and fires it no matter what, so a
# held key is *always* released within HOLD_KEY_MAX_SECONDS — a manual
# "release"/"keyup" step just cancels the timer and releases early.
HOLD_KEY_MAX_SECONDS = 5.0
_key_hold_timers = {}
_key_hold_timers_lock = threading.Lock()

def _schedule_key_auto_release(key: str, seconds: float):
    seconds = max(0.05, min(seconds, HOLD_KEY_MAX_SECONDS))

    def _release():
        with _key_hold_timers_lock:
            _key_hold_timers.pop(key, None)
        if key in SCANCODES:
            send_scancode(SCANCODES[key][1])
            print(f"[Hold] Auto-released '{key}' after {seconds}s.")

    with _key_hold_timers_lock:
        old = _key_hold_timers.pop(key, None)
        if old:
            old.cancel()   # a fresh !hold on the same key restarts the clock
        timer = threading.Timer(seconds, _release)
        timer.daemon = True
        _key_hold_timers[key] = timer
        timer.start()

def _cancel_key_auto_release(key: str):
    with _key_hold_timers_lock:
        timer = _key_hold_timers.pop(key, None)
    if timer:
        timer.cancel()

def send_special_enter():
    send_scancode('1c')
    time.sleep(0.015)
    send_scancode('9c')

def play_success_sound():
    try:
        subprocess.Popen(['start', SUCCESS_SOUND_FILE], shell=True)
    except Exception as e:
        print(f"[Sound] Error: {e}")

def start_vm():
    try:
        update_status("Starting...")
        subprocess.run([VBOXMANAGE_PATH, 'startvm', VM_NAME], check=True)
        update_status("Running")
        print("[VM] Started!")
    except Exception as e:
        update_status("VM is already running!")
        print(f"[VM] Already running: {e}")

def restore_window():
    try:
        subprocess.run([VBOXMANAGE_PATH, 'controlvm', VM_NAME, 'gui', 'show'], check=True)
        print("[VM] Window brought to front!")
    except:
        print("[VM] Restore: Not working in headless mode!")

def get_mouse_and_session():
    session = mgr.getSessionObject(vbox)
    machine = vbox.findMachine(VM_NAME)
    machine.lockMachine(session, 1)
    console = session.console
    mouse   = console.mouse
    return mouse, session

def unlock_session(session):
    # VirtualBox session states: 0=Null, 1=Unlocked, 2=Locked, 3=Spawning, 4=Unlocking
    if session.state == 2:   # 2 = Locked — only unlock when actually locked
        session.unlockMachine()

_MOUSE_DEFAULT_STEP = 20     # px — same default !move used before named-direction distances existed
_MOUSE_MAX_STEP = 500        # px — sanity cap so a typo like "!move up 99999" can't send an absurd jump

def _both_look_like_ints(parts):
    """True if both of a 2-element parts list parse as plain integers
    (handles an optional leading '-' for negative relative deltas)."""
    if len(parts) != 2:
        return False
    return all(p.lstrip('-').isdigit() for p in parts)

def _parse_distance(raw):
    """Parses an optional distance argument (e.g. the '50' in '!move up 50').
    Falls back to _MOUSE_DEFAULT_STEP if missing/invalid, and clamps to
    _MOUSE_MAX_STEP either way."""
    if raw is None:
        return _MOUSE_DEFAULT_STEP
    try:
        distance = int(raw)
    except ValueError:
        return _MOUSE_DEFAULT_STEP
    return max(1, min(distance, _MOUSE_MAX_STEP))

def _direction_to_delta(direction, distance):
    """Converts a named direction ('left'/'right'/'up'/'down') + a pixel
    distance into a (dx, dy) relative mouse-movement pair."""
    dx = {'left': -distance, 'right': distance, 'up': 0, 'down': 0}.get(direction, 0)
    dy = {'left': 0, 'right': 0, 'up': -distance, 'down': distance}.get(direction, 0)
    return dx, dy

def handle_mouse(cmd, args):
    session = None
    try:
        mouse, session = get_mouse_and_session()
        parts   = args.split()
        buttons = 0
        if cmd in ['move', 'mouse', 'mv']:
            if len(parts) == 2 and _both_look_like_ints(parts):
                # Raw relative dx,dy form — unchanged from before:
                # "!move 500 300" nudges the cursor by (500, 300) px.
                mouse.putMouseEvent(int(parts[0]), int(parts[1]), 0, 0, buttons)
            elif parts and parts[0].lower() in ('left', 'right', 'up', 'down'):
                # Named-direction form, now with an optional distance:
                # "!move up" (defaults to 20px, same as before this change)
                # "!move up 50" moves 50px in that direction.
                direction = parts[0].lower()
                distance = _parse_distance(parts[1] if len(parts) > 1 else None)
                dx, dy = _direction_to_delta(direction, distance)
                mouse.putMouseEvent(dx, dy, 0, 0, buttons)
        elif cmd in ['abs', 'cursor', 'moveabs']:
            if len(parts) == 2:
                mouse.putMouseEventAbsolute(int(parts[0]), int(parts[1]), 0, 0, buttons)
        elif cmd in ['click', 'lclick']:
            count = int(args) if args.isdigit() else 1
            for _ in range(count):
                mouse.putMouseEvent(0,0,0,0,1)
                mouse.putMouseEvent(0,0,0,0,0)
        elif cmd in ['rclick', 'rightclick']:
            count = int(args) if args.isdigit() else 1
            for _ in range(count):
                mouse.putMouseEvent(0,0,0,0,2)
                mouse.putMouseEvent(0,0,0,0,0)   # release right button
        elif cmd in ['mclick', 'middleclick']:
            count = int(args) if args.isdigit() else 1
            for _ in range(count):
                mouse.putMouseEvent(0,0,0,0,4)
                mouse.putMouseEvent(0,0,0,0,0)   # release middle button
        elif cmd in ['drag', 'dragrel']:
            if len(parts) >= 2:
                button = 1 if len(parts)==2 else (1 if parts[0]=='left' else 2 if parts[0]=='right' else 4)
                dx, dy = int(parts[-2]), int(parts[-1])
                mouse.putMouseEvent(0,0,0,0,button)
                mouse.putMouseEvent(dx,dy,0,0,button)
                mouse.putMouseEvent(0,0,0,0,0)
        elif cmd in ['holdclick', 'holdrclick']:
            # Named-direction click-and-drag: holds a mouse button down,
            # moves the cursor by <distance> px in <direction>, then
            # releases. Syntax: !holdclick <direction> <distance>
            #   "!holdclick left 10"  -> hold LEFT button, drag 10px left, release
            #   "!holdrclick down 30" -> hold RIGHT button, drag 30px down, release
            # (functionally the same primitive as !drag/!dragrel above,
            # just with human-readable direction names instead of raw
            # dx/dy deltas)
            if parts and parts[0].lower() in ('left', 'right', 'up', 'down'):
                direction = parts[0].lower()
                distance = _parse_distance(parts[1] if len(parts) > 1 else None)
                dx, dy = _direction_to_delta(direction, distance)
                button = 2 if cmd == 'holdrclick' else 1
                mouse.putMouseEvent(0, 0, 0, 0, button)     # press
                mouse.putMouseEvent(dx, dy, 0, 0, button)   # move while held
                mouse.putMouseEvent(0, 0, 0, 0, 0)          # release
        elif cmd in ['dragabs', 'drag_absolute']:
            if len(parts) >= 2:
                button = 1 if len(parts)==2 else (1 if parts[0]=='left' else 2 if parts[0]=='right' else 4)
                x, y = int(parts[-2]), int(parts[-1])
                mouse.putMouseEventAbsolute(x,y,0,0,button)
                mouse.putMouseEventAbsolute(x,y,0,0,0)
        elif cmd in ['scroll', 'wheel']:
            dz = int(args) if args else 0
            mouse.putMouseEvent(0,0,dz,0,0)
        print(f"[Mouse] {cmd} {args}")
    except Exception as e:
        print(f"[Mouse] Error: {e}")
    finally:
        # Always release the session — even if the command raised an exception.
        # Skipping this locks the VirtualBox machine permanently until process restart.
        if session is not None:
            unlock_session(session)

def update_ban_vote_display(target, current_votes, required, remaining_time=None):
    action_text   = f"Ban @{target}" if target else "Empty"
    remaining_str = f"Remaining time: {int(remaining_time)} s" if remaining_time is not None else ""
    html = f"""<html><head><style>
    body{{background:rgba(0,0,0,0);color:white;font-family:Arial;text-align:center;font-size:28px;text-shadow:2px 2px 4px #000;}}
    #c{{margin-top:40px;padding:20px;background:rgba(0,0,0,0.5);border-radius:12px;display:inline-block;}}
    h1{{color:#ff4444;}} .progress{{width:80%;height:25px;background:rgba(255,255,255,0.2);border-radius:12px;margin:15px auto;overflow:hidden;}}
    .bar{{height:100%;width:{int((current_votes/required)*100)}%;background:#ff4444;transition:width 0.5s;}}
    </style></head><body><div id="c"><h1>Ban Vote</h1>
    <p>{action_text}</p><p>{current_votes}/{required}</p><p>{remaining_str}</p>
    <div class="progress"><div class="bar"></div></div></div>
    <script>setInterval(()=>location.reload(),10000);</script></body></html>"""
    with open(VOTE_FILE_BAN, "w", encoding="utf-8") as f: f.write(html)

_last_persistent_status = "Idle"
_status_revert_timer = None
_status_revert_lock = threading.Lock()

def update_status(message, transient: bool = False, transient_seconds: float = 6.0):
    """
    Writes the current status to STATUS_FILE (the OBS status overlay).

    transient=True is for short-lived alerts — cooldown hits, blocked
    command notices — that should flash on the overlay for a few seconds
    and then automatically revert back to whatever the real VM status
    was, instead of permanently overwriting it (e.g. a blocked-command
    notice should not get stuck showing forever in place of "Running").
    Normal (non-transient) calls, like update_status("Running"), become
    the new baseline that transient messages revert back to.
    """
    global _last_persistent_status, _status_revert_timer

    html = f"""<html><head><style>
    body{{background:rgba(0,0,0,0);color:white;font-family:Arial;font-size:32px;text-align:center;text-shadow:2px 2px 4px #000;}}
    #s{{margin-top:20px;padding:10px;background:rgba(0,0,0,0.4);border-radius:8px;display:inline-block;}}
    </style></head><body><div id="s">Status: {message}</div>
    <script>setInterval(()=>location.reload(),10000);</script></body></html>"""
    with open(STATUS_FILE, "w", encoding="utf-8") as f: f.write(html)
    print(f"[Status] {message}")

    with _status_revert_lock:
        if _status_revert_timer:
            _status_revert_timer.cancel()
            _status_revert_timer = None

        if transient:
            def _revert():
                update_status(_last_persistent_status)
            _status_revert_timer = threading.Timer(transient_seconds, _revert)
            _status_revert_timer.daemon = True
            _status_revert_timer.start()
        else:
            _last_persistent_status = message

def vote_timeout_checker():
    global restart_start_time, revert_start_time
    while not bot_stop_event.is_set():
        if bot_stop_event.wait(1):
            break
        current_time = time.time()

        # Restart: update remaining_time every second so overlay stays in sync
        if restart_start_time is not None:
            elapsed = current_time - restart_start_time
            if elapsed > VOTE_TIMEOUT:
                vote_restart.clear(); restart_start_time = None
                update_votes_json("restartvm", 0, PERMISSIONS_CONFIG.get("restart_votes", 2), 0)
                print("[Vote] Restart votes timed out")
            else:
                remaining = max(0, VOTE_TIMEOUT - elapsed)
                update_votes_json("restartvm", len(vote_restart), _votes_state["restartvm"]["required"], remaining)

        # Revert: same live update
        if revert_start_time is not None:
            elapsed = current_time - revert_start_time
            if elapsed > VOTE_TIMEOUT:
                vote_revert.clear(); revert_start_time = None
                update_votes_json("revert", 0, PERMISSIONS_CONFIG.get("revert_votes", 2), 0)
                print("[Vote] Revert votes timed out")
            else:
                remaining = max(0, VOTE_TIMEOUT - elapsed)
                update_votes_json("revert", len(vote_revert), _votes_state["revert"]["required"], remaining)

        to_remove = [t for t, d in ban_votes.items()
                     if 'start_time' in d and current_time - d['start_time'] > VOTE_TIMEOUT]
        for t in to_remove:
            del ban_votes[t]
            update_ban_vote_display(None, 0, 3)
            print(f"[Vote] Ban vote timed out: {t}")
    print("[Vote] Timeout checker stopped.")

def watchdog_restart():
    while not bot_stop_event.is_set():
        try:
            if not AUTO_START_ENABLED:
                if bot_stop_event.wait(10):
                    break
                continue
            if not VM_NAME:
                if bot_stop_event.wait(10):
                    break
                continue
            result = subprocess.run(
                [VBOXMANAGE_PATH, 'showvminfo', VM_NAME, '--machinereadable'],
                capture_output=True, text=True
            )
            lines = [l for l in result.stdout.splitlines() if l.startswith('VMState="')]
            if lines:
                vm_state = lines[0].split('=')[1].strip('"')
                if vm_state in ["poweroff", "aborted", "gurumeditation"]:
                    if revert_in_progress or os_switch_in_progress:
                        print("[Watchdog] Revert/OS-switch in progress, ignoring down state.")
                    else:
                        print(f"[Watchdog] VM down ({vm_state}). Auto-restarting...")
                        update_status("Auto-starting...")
                        speak_text("Auto starting virtual machine...")
                        notify("VM Auto-Restarted", f"VM was found {vm_state}. Auto-restart triggered.")
                        ok, err = retry_vbox(
                            lambda: subprocess.run(
                                [VBOXMANAGE_PATH, 'startvm', VM_NAME], check=True
                            ),
                            attempts=3, delay=5, source="Watchdog/startvm"
                        )
                        if ok:
                            update_status("Running")
                            speak_text("Running")
                        else:
                            log_error("Watchdog", "Failed to auto-restart VM after 3 attempts", str(err))
                            notify("Watchdog: VM Start Failed",
                                   "Could not restart the VM after 3 attempts. Check VirtualBox.",
                                   timeout=10)
                            update_status("ERROR: VM failed to start")
                elif vm_state == "running":
                    pass  # all good
        except Exception as e:
            log_error("Watchdog", e)
        if bot_stop_event.wait(10):
            break
    print("[Watchdog] Stopped.")

class _MessageDedup:
    """
    Tracks recently-seen chat message IDs so a message never triggers a
    command twice. Needed because reconnecting to a chat backend
    (periodic reconnect, or recovering from a dropped connection) often
    re-delivers the last few seconds of messages that were already
    processed right before the reconnect — this is normal behavior for
    YouTube's live chat data, not a bug in any one backend, but without
    a dedup layer it means commands can silently run twice in a row
    right after every reconnect.
    Bounded to MAX_TRACKED entries (oldest evicted first) so a
    multi-hour stream doesn't grow this without limit.
    """
    MAX_TRACKED = 1000

    def __init__(self):
        self._seen_ids = set()
        self._order = collections.deque()

    def is_duplicate(self, msg_id) -> bool:
        # Messages with no ID (some backends can occasionally omit one)
        # can't be deduped by ID — fail open and let them through rather
        # than risk silently dropping a legitimate command.
        if not msg_id:
            return False
        if msg_id in self._seen_ids:
            return True
        self._seen_ids.add(msg_id)
        self._order.append(msg_id)
        if len(self._order) > self.MAX_TRACKED:
            oldest = self._order.popleft()
            self._seen_ids.discard(oldest)
        return False


class YouTubeChatBot:
    def __init__(self):
        self.video_id = VIDEO_ID
        self.chat = None
        self._reconnect_failures = 0
        self._dedup = _MessageDedup()
        self.reconnect()
        update_overlay()
        threading.Thread(target=start_overlay_server, daemon=True).start()
        if not self.chat or not self.chat.is_alive():
            print("[Bot] Could not connect to YouTube live chat!")
            return
        print("[Bot] Connected to YouTube chat!")
        print(COMMANDS_HELP)
        self.last_start_time = 0
        # Use names to avoid duplicate threads on bot restart.
        running_names = {t.name for t in threading.enumerate()}
        if "vote_timeout_checker" not in running_names:
            threading.Thread(target=vote_timeout_checker, daemon=True,
                             name="vote_timeout_checker").start()
        if "watchdog_restart" not in running_names:
            threading.Thread(target=watchdog_restart, daemon=True,
                             name="watchdog_restart").start()
        if "os_vote_timeout_checker" not in running_names:
            threading.Thread(target=os_vote_timeout_checker, daemon=True,
                             name="os_vote_timeout_checker").start()
        if OS_VOTING_ENABLED:
            update_os_vote_status()
       # threading.Thread(target=fetch_youtube_stats, daemon=True).start()

    def reconnect(self):
        if self.chat:
            self.chat.terminate()
        else:
            self.chat = YouTubeChatSource(self.video_id, api_key=YOUTUBE_API_KEY)
        try:
            if not self.chat.connect():
                raise ConnectionError(f"Could not connect to chat for video_id={self.video_id}")
            if self._reconnect_failures > 0:
                msg = f"[Bot] Reconnect successful after {self._reconnect_failures} failure(s)."
                print(msg)
                _append_event("RECONNECT", "system", f"recovered after {self._reconnect_failures} failures")
                update_status("Running")
            self._reconnect_failures = 0
            return True
        except Exception as e:
            self._reconnect_failures += 1
            log_error("Bot/Reconnect", e, f"consecutive failures: {self._reconnect_failures}")

            # Exponential backoff delay
            base  = RECONNECT_CONFIG.get("base_delay", 5)
            cap   = RECONNECT_CONFIG.get("max_delay", 120)
            delay = min(base * (2 ** (self._reconnect_failures - 1)), cap)
            print(f"[Bot] Reconnect failed ({self._reconnect_failures}x) — retrying in {delay:.0f}s...")
            update_status(f"Reconnecting... (attempt {self._reconnect_failures})")
            _append_event("RECONNECT_FAIL", "system",
                          f"failure #{self._reconnect_failures} — retry in {delay:.0f}s")

            # Notify on threshold
            threshold = RECONNECT_CONFIG.get("notify_threshold", 3)
            if self._reconnect_failures == threshold:
                notify("Chat Connection Lost",
                       f"Failed to reconnect to YouTube chat {threshold} times.\n"
                       f"Check your Video ID and internet connection.",
                       timeout=10)

            # Stop bot if max failures reached
            max_f = RECONNECT_CONFIG.get("max_failures", 10)
            if max_f > 0 and self._reconnect_failures >= max_f:
                print(f"[Bot] Max reconnect failures ({max_f}) reached. Stopping bot.")
                notify("Bot Stopped",
                       f"Chat connection failed {max_f} times in a row.\n"
                       "The bot has been stopped automatically.",
                       timeout=12)
                _append_event("BOT_STOP", "system", f"auto-stopped after {max_f} reconnect failures")
                update_status("Stopped — too many failures")
                bot_stop_event.set()
                return False

            # Wait with interruptible sleep
            bot_stop_event.wait(delay)
            return False

    def run(self):
        global restart_start_time, revert_start_time, revert_in_progress, restart_in_progress, restart_cooldown_until, revert_cooldown_until, os_vote_start_time
        last_reconnect   = time.time()
        RECONNECT_INTERVAL = 150
        print("[Bot] Waiting for chat messages...")
        threading.Thread(target=_cooldown_overlay_ticker, daemon=True).start()
        while not bot_stop_event.is_set():
            if time.time() - last_reconnect > RECONNECT_INTERVAL:
                print("[Bot] Periodic reconnect...")
                self.reconnect()
                last_reconnect = time.time()
            if not self.chat or not self.chat.is_alive():
                self.reconnect()
                if bot_stop_event.wait(5):
                    break
                continue
            try:
                for c in self.chat.get_messages():
                    if bot_stop_event.is_set():
                        break
                    if self._dedup.is_duplicate(c.id):
                        # Reconnects (periodic or after a dropped
                        # connection) often re-deliver the last few
                        # seconds of already-processed messages — skip
                        # them so commands never fire twice in a row.
                        continue
                    msg      = c.text.strip()
                    user     = normalize_username(c.author_name)
                    is_owner = c.is_owner
                    update_overlay(author=user, message=msg, msg_id=c.id)
                    if user in banned_users:
                        if time.time() < banned_users[user]: continue
                        else: del banned_users[user]
                    # Whitelist check: if enabled and user not in list (and not owner), skip
                    if whitelist_users and not is_owner and user not in whitelist_users:
                        continue
                    active_users.add(c.author_name.strip())
                    print(f"[Chat] [{user}]: {msg}")

                    # Live Chat Viewer
                    _is_cmd     = msg.startswith("!")
                    _is_banned_ = (user in banned_users and
                                   time.time() < banned_users.get(user, 0))
                    if _gui_app is not None:
                        try:
                            _gui_app._append_chat(
                                user, msg,
                                is_owner=is_owner,
                                is_command=_is_cmd,
                                is_banned=_is_banned_,
                            )
                        except Exception:
                            pass

                    if msg.startswith('!'):
                        chain_parts = [p.strip() for p in msg.split('!') if p.strip()]
                        _prev_cmd_was_wait = False
                        for part in chain_parts:
                            sub_parts = part.split(maxsplit=1)
                            cmd  = sub_parts[0].lower()
                            args = sub_parts[1] if len(sub_parts) > 1 else ""

                            # Skip chained wait/pause/delay commands that
                            # immediately follow another wait/pause/delay —
                            # otherwise they stack up (e.g. "!wait 5!wait 5!wait 5"
                            # sleeps for 15s instead of 5s). Only the first
                            # wait in a run is honored; the rest are ignored.
                            _is_wait_cmd = cmd in ('wait', 'pause', 'delay')
                            if _is_wait_cmd and _prev_cmd_was_wait:
                                _prev_cmd_was_wait = _is_wait_cmd
                                continue
                            _prev_cmd_was_wait = _is_wait_cmd

                            _record_command(cmd, user)

                            # ── Custom command check (first priority) ──
                            trigger = "!" + cmd
                            if trigger in custom_commands:
                                threading.Thread(
                                    target=execute_custom_command,
                                    args=(trigger,), daemon=True
                                ).start()
                                continue

                            # ── OS voting commands (e.g. !win7, !win10) ──
                            if OS_VOTING_ENABLED:
                                os_trigger_map = get_os_trigger_map()
                                if cmd in os_trigger_map:
                                    if os_switch_in_progress:
                                        continue
                                    target_entry = os_trigger_map[cmd]
                                    # Owner bypass: switch immediately, no vote needed
                                    if is_owner:
                                        print(f"[OSVoting] Switch bypassed by owner: {user} → {target_entry['name']}")
                                        threading.Thread(target=switch_os, args=(target_entry,), daemon=True).start()
                                        continue
                                    if target_entry.get("vm") == current_os_vm:
                                        continue  # already running, no point voting for it
                                    if not os_votes:
                                        os_vote_start_time = time.time()
                                    voters = os_votes.setdefault(cmd, set())
                                    if user in voters:
                                        continue
                                    voters.add(user)
                                    update_os_vote_status()
                                    print(f"[OSVoting] Vote for '{target_entry['name']}': {len(voters)}/{OS_VOTE_REQUIRED}")
                                    if len(voters) >= OS_VOTE_REQUIRED:
                                        print(f"[OSVoting] Threshold reached → switching to {target_entry['name']}")
                                        threading.Thread(target=switch_os, args=(target_entry,), daemon=True).start()
                                    continue

                            # ── Hidden attribution/verification command ──
                            # Deliberately undocumented — not shown in any
                            # help text or command list. Anyone in chat can
                            # trigger it; it just proves the stream is
                            # running this script via an audible TTS line.
                            if cmd == "nexo0091":
                                _nexo_verify_speak()
                                continue

                            # ── Built-in commands ──
                            if cmd in ['wait', 'pause', 'delay']:
                                try:
                                    delay = float(args)
                                    delay = max(0, min(delay, 5.0))
                                    time.sleep(delay)
                                except: pass
                                continue

                            # ── Same dangerous-command / base64-payload filter as
                            # Real PC Control — applies here too since the VM's
                            # screen is what actually gets shown on stream. ──
                            if cmd in ('type', 'text', 'say', 'send', 'sendline',
                                       'typeenter', 'key', 'press', 'enter'):
                                if _vm_keyboard_blocked(cmd, args, user):
                                    continue

                            if cmd in ['type', 'text', 'say']:
                                send_keyboard(args)
                            elif cmd in ['typeenter', 'send', 'sendline']:
                                send_keyboard(args)
                                send_special_enter()
                            elif cmd == 'enter':
                                send_special_enter()
                            elif cmd in ['fullscreen', 'fs']:
                                print("[Bot] Fullscreen hint (manual)")
                            elif cmd in ['move','mouse','mv','abs','cursor','moveabs',
                                         'drag','dragrel','dragabs','drag_absolute',
                                         'holdclick','holdrclick',
                                         'click','lclick','rclick','rightclick',
                                         'mclick','middleclick','scroll','wheel']:
                                handle_mouse(cmd, args)
                            elif cmd in ['startvm','modlaunch','launchvm','start_mc','startmc']:
                                if time.time() - self.last_start_time > COOLDOWN_START:
                                    start_vm()
                                    self.last_start_time = time.time()
                                else:
                                    print("[Bot] !startvm cooldown active")
                            elif cmd in ['restore','refresh','restore_window','focus','front','bringtofront']:
                                restore_window()
                            elif cmd in ['key', 'press']:
                                k = args.lower().strip()
                                if k in SCANCODES:
                                    send_scancode(SCANCODES[k][0])
                                    time.sleep(0.01)
                                    send_scancode(SCANCODES[k][1])
                                else:
                                    send_keyboard(k)
                            elif cmd in ['keydown', 'hold']:
                                k = args.lower().strip()
                                if k in SCANCODES: send_scancode(SCANCODES[k][0])
                            elif cmd in ['keyup', 'release']:
                                k = args.lower().strip()
                                if k in SCANCODES: send_scancode(SCANCODES[k][1])
                            elif cmd in ['combo','chord','multi']:
                                keys = args.lower().replace('+',' ').split()
                                if keys: send_combo(keys)
                                else: send_keyboard(args)
                            elif cmd == 'run':
                                send_combo(['win','r'])
                            elif cmd == 'votehelp':
                                update_status("Commands in description!")
                            elif cmd == 'clearvotes':
                                if user == ADMIN_USERNAME.lower():
                                    vote_restart.clear(); vote_revert.clear(); ban_votes.clear()
                                    restart_start_time = None; revert_start_time = None
                                    update_votes_json("restartvm", 0, PERMISSIONS_CONFIG.get("restart_votes", 2), 0)
                                    update_votes_json("revert",    0, PERMISSIONS_CONFIG.get("revert_votes",  2), 0)
                                    update_ban_vote_display(None,0,PERMISSIONS_CONFIG.get("ban_votes",3))
                                    os_votes.clear(); os_vote_start_time = None
                                    update_os_vote_status()
                                    speak_text("Votes cleared by admin!")
                                    print("[Admin] Votes cleared")

                            # Vote logic — required votes come from the Permissions config
                            required_votes = PERMISSIONS_CONFIG.get("restart_votes", 2)
                            # VIP override: if this user is a VIP, lower the threshold
                            if user in vip_users:
                                required_votes = min(required_votes,
                                    vip_users[user].get("votes_needed", required_votes))
                            current_time   = time.time()

                            if cmd in ['restart','restartvm']:
                                if restart_in_progress: continue
                                if current_time < restart_cooldown_until:
                                    remaining_cd = int(restart_cooldown_until - current_time)
                                    print(f"[Vote] Restart on cooldown ({remaining_cd}s left)")
                                    _append_event("COOLDOWN", user, f"restart blocked — {remaining_cd}s left")
                                    update_status(f"⏳ Restart on cooldown ({remaining_cd}s)", transient=True)
                                    if _gui_app is not None:
                                        try:
                                            _gui_app._append_chat_system(f"⏳ Restart is on cooldown — {remaining_cd}s left.")
                                        except Exception:
                                            pass
                                    continue

                                def _run_restart(triggered_by, votes_used, owner_bypass=False):
                                    """Runs the actual VM reset in a background thread — see
                                    _run_revert's docstring above for why (same reasoning
                                    applies: keep reading chat while this is in progress,
                                    and the cooldown is already set before this runs)."""
                                    global restart_in_progress
                                    try:
                                        ok, err = retry_vbox(
                                            lambda: subprocess.run([VBOXMANAGE_PATH,'controlvm',VM_NAME,'reset'], check=True),
                                            attempts=3, delay=3, source=f"Vote/restart-{'owner' if owner_bypass else 'chat'}"
                                        )
                                        if ok:
                                            update_status("Running"); play_success_sound()
                                            play_event_sound("restart_sound")
                                            _append_event("RESTART", triggered_by,
                                                           "owner bypass" if owner_bypass else f"chat vote passed ({votes_used} votes)")
                                            notify("VM Restarted",
                                                   "Restart triggered by owner." if owner_bypass else "Restart vote passed by chat.")
                                            if not owner_bypass:
                                                obs_trigger("restart")
                                                _stats["restarts"] += 1
                                        else:
                                            update_status("Restart failed")
                                            log_error("Vote/restart", "Restart failed after retries", str(err))
                                            notify("Restart Failed", str(err), timeout=6)
                                    finally:
                                        update_votes_json("restartvm", 0, required_votes, 0)
                                        restart_in_progress = False

                                # Owner bypass: skip vote, execute immediately
                                if is_owner:
                                    print(f"[Vote] Restart bypassed by owner: {user}")
                                    speak_text("Restarting Virtual Machine...")
                                    vote_restart.clear(); restart_start_time=None; active_users.clear()
                                    restart_in_progress = True
                                    restart_cooldown_until = time.time() + PERMISSIONS_CONFIG.get("action_cooldown", 60)
                                    update_status("Restarting...")
                                    update_votes_json("restartvm", required_votes, required_votes, 0)
                                    threading.Thread(target=_run_restart, args=(user, required_votes, True), daemon=True).start()
                                    continue
                                if not vote_restart: restart_start_time = current_time
                                if user in vote_restart: continue
                                vote_restart[user] = current_time
                                current   = len(vote_restart)
                                remaining = max(0, VOTE_TIMEOUT-(current_time-restart_start_time)) if restart_start_time else 0
                                update_votes_json("restartvm", current, required_votes, remaining)
                                if current >= required_votes:
                                    print("[Vote] Restart threshold reached!")
                                    speak_text("Restarting Virtual Machine...")
                                    vote_restart.clear(); restart_start_time=None; active_users.clear()
                                    restart_in_progress = True
                                    restart_cooldown_until = time.time() + PERMISSIONS_CONFIG.get("action_cooldown", 60)
                                    update_status("Restarting...")
                                    threading.Thread(target=_run_restart, args=("vote", current, False), daemon=True).start()

                            elif cmd == 'revert':
                                if revert_in_progress: continue
                                if current_time < revert_cooldown_until:
                                    remaining_cd = int(revert_cooldown_until - current_time)
                                    print(f"[Vote] Revert on cooldown ({remaining_cd}s left)")
                                    _append_event("COOLDOWN", user, f"revert blocked — {remaining_cd}s left")
                                    update_status(f"⏳ Revert on cooldown ({remaining_cd}s)", transient=True)
                                    if _gui_app is not None:
                                        try:
                                            _gui_app._append_chat_system(f"⏳ Revert is on cooldown — {remaining_cd}s left.")
                                        except Exception:
                                            pass
                                    continue

                                def _run_revert(triggered_by, votes_used, owner_bypass=False):
                                    """
                                    Runs the actual poweroff -> snapshot restore -> startvm
                                    sequence in a background thread, so the bot keeps
                                    reading/processing chat while a revert (which can
                                    easily take 10s of seconds) is in progress — this is
                                    also why the cooldown is set BEFORE this function is
                                    even called, not after it finishes: a cooldown that
                                    only started once the revert itself was done used to
                                    silently stretch out by however long the revert took.
                                    """
                                    global revert_in_progress
                                    try:
                                        obs_trigger("revert_start")
                                        ok, err = retry_vbox(
                                            lambda: subprocess.run([VBOXMANAGE_PATH,'controlvm',VM_NAME,'poweroff'], check=True),
                                            attempts=3, delay=3, source=f"Vote/revert-{'owner' if owner_bypass else 'chat'}/poweroff"
                                        )
                                        time.sleep(3)
                                        ok2, err2 = retry_vbox(
                                            lambda: subprocess.run([VBOXMANAGE_PATH,'snapshot',VM_NAME,'restorecurrent'], check=True),
                                            attempts=3, delay=3, source=f"Vote/revert-{'owner' if owner_bypass else 'chat'}/snapshot"
                                        )
                                        time.sleep(3)
                                        ok3, err3 = retry_vbox(
                                            lambda: subprocess.run([VBOXMANAGE_PATH,'startvm',VM_NAME], check=True),
                                            attempts=3, delay=4, source=f"Vote/revert-{'owner' if owner_bypass else 'chat'}/startvm"
                                        )
                                        if ok2 and ok3:
                                            update_status("Running"); play_success_sound()
                                            play_event_sound("revert_sound")
                                            _append_event("REVERT", triggered_by,
                                                           "owner bypass" if owner_bypass else f"chat vote passed ({votes_used} votes)")
                                            notify("VM Reverted",
                                                   "Snapshot restored by owner." if owner_bypass else "Snapshot restored by chat vote.")
                                            obs_trigger("revert_done")
                                            if not owner_bypass:
                                                _stats["reverts"] += 1
                                        else:
                                            failed = "snapshot" if not ok2 else "startvm"
                                            update_status("Revert failed")
                                            log_error("Vote/revert", f"Revert failed at {failed}", str(err2 or err3))
                                            notify("Revert Failed", f"Failed at {failed} step.", timeout=6)
                                    finally:
                                        update_votes_json("revert", 0, required_votes, 0)
                                        revert_in_progress = False

                                # Owner bypass: skip vote, execute immediately
                                if is_owner:
                                    print(f"[Vote] Revert bypassed by owner: {user}")
                                    speak_text("Reverting Virtual Machine...")
                                    vote_revert.clear(); revert_start_time=None; active_users.clear()
                                    revert_in_progress = True
                                    revert_cooldown_until = time.time() + PERMISSIONS_CONFIG.get("action_cooldown", 60)
                                    update_status("Reverting...")
                                    update_votes_json("revert", required_votes, required_votes, 0)
                                    threading.Thread(target=_run_revert, args=(user, required_votes, True), daemon=True).start()
                                    continue
                                if not vote_revert: revert_start_time = current_time
                                if user in vote_revert: continue
                                vote_revert[user] = current_time
                                current   = len(vote_revert)
                                remaining = max(0, VOTE_TIMEOUT-(current_time-revert_start_time)) if revert_start_time else 0
                                update_votes_json("revert", current, required_votes, remaining)
                                if current >= required_votes:
                                    print("[Vote] Revert threshold reached!")
                                    speak_text("Reverting Virtual Machine...")
                                    vote_revert.clear(); revert_start_time=None; active_users.clear()
                                    revert_in_progress = True
                                    revert_cooldown_until = time.time() + PERMISSIONS_CONFIG.get("action_cooldown", 60)
                                    update_status("Reverting...")
                                    threading.Thread(target=_run_revert, args=("vote", current, False), daemon=True).start()

                            elif cmd == 'ban':
                                # Accept both "!ban @user" and "!ban user"
                                raw_arg    = args.strip().lstrip('@').split()[0] if args.strip() else ""
                                if not raw_arg: continue
                                target_raw = raw_arg
                                target     = target_raw.lower()
                                # Prevent self-ban and owner-ban
                                if target == user: continue
                                ban_required = PERMISSIONS_CONFIG.get("ban_votes", 3)
                                if target not in ban_votes:
                                    ban_votes[target] = {'voters': set(), 'start_time': current_time}
                                if user in ban_votes[target]['voters']: continue
                                ban_votes[target]['voters'].add(user)
                                cbv       = len(ban_votes[target]['voters'])
                                remaining = max(0, VOTE_TIMEOUT-(current_time-ban_votes[target]['start_time']))
                                update_ban_vote_display(target_raw, cbv, ban_required, remaining)
                                print(f"[Ban] Vote for '{target}': {cbv}/{ban_required}")
                                _append_event("BAN_VOTE", user, f"target={target_raw} {cbv}/{ban_required}")
                                if cbv >= ban_required:
                                    banned_users[target] = time.time() + BAN_DURATION
                                    update_status(f"@{target_raw} banned 30 min!")
                                    speak_text(f"Banned {target_raw} for 30 minutes.")
                                    play_success_sound()
                                    play_event_sound("ban_sound")
                                    _append_event("BAN", user, f"banned {target_raw} for 30min")
                                    notify("User Banned", f"@{target_raw} banned for 30 minutes by chat vote.")
                                    del ban_votes[target]
                                    update_ban_vote_display(None, 0, ban_required)

            except Exception as e:
                if bot_stop_event.is_set():
                    break
                err = str(e).lower()
                if "timeout" in err or "timed out" in err:
                    print("[Bot] Timeout → reconnecting...")
                else:
                    print(f"[Bot] Error: {e} → reconnecting...")
                self.reconnect()
                if bot_stop_event.wait(5):
                    break
            if bot_stop_event.wait(0.05):
                break

        # Clean shutdown
        if self.chat:
            try: self.chat.terminate()
            except: pass
        print("[Bot] Stopped.")


# ========================= SECONDARY STREAM BOT =========================
class YouTubeChatBotSecondary:
    """
    Lightweight chat listener for additional YouTube stream IDs.
    Shares the same command handlers as the primary bot.
    Only processes commands — no vote logic (votes are kept in primary stream).
    """
    def __init__(self, video_id: str):
        self.video_id = video_id
        self.chat = None
        self._dedup = _MessageDedup()
        self._reconnect()
        print(f"[MultiStream] Secondary bot initialised: {video_id}")

    def _reconnect(self):
        if self.chat:
            self.chat.terminate()
        else:
            self.chat = YouTubeChatSource(self.video_id, api_key=YOUTUBE_API_KEY)
        if self.chat.connect():
            return True
        print(f"[MultiStream] Reconnect error ({self.video_id})")
        return False

    def run(self):
        print(f"[MultiStream] Listening on: {self.video_id}")
        while not bot_stop_event.is_set():
            if not self.chat or not self.chat.is_alive():
                if not self._reconnect():
                    if bot_stop_event.wait(10):
                        break
                    continue
            try:
                for c in self.chat.get_messages():
                    if bot_stop_event.is_set():
                        break
                    if self._dedup.is_duplicate(c.id):
                        continue
                    msg  = c.text.strip()
                    user = normalize_username(c.author_name)
                    if user in banned_users and time.time() < banned_users[user]:
                        continue
                    if whitelist_users and user not in whitelist_users:
                        continue
                    print(f"[MultiStream:{self.video_id}] [{user}]: {msg}")
                    if not msg.startswith('!'):
                        continue
                    parts = [p.strip() for p in msg.split('!') if p.strip()]
                    for part in parts:
                        sub = part.split(maxsplit=1)
                        cmd  = sub[0].lower()
                        args = sub[1] if len(sub) > 1 else ""
                        _record_command(cmd, user)
                        # Custom commands
                        trigger = "!" + cmd
                        if trigger in custom_commands:
                            threading.Thread(
                                target=execute_custom_command,
                                args=(trigger,), daemon=True
                            ).start()
                            continue
                        # Keyboard / mouse passthrough
                        try:
                            # Hidden attribution/verification command — see
                            # main handler for details. Works the same way
                            # on secondary streams.
                            if cmd == "nexo0091":
                                _nexo_verify_speak()
                                continue
                            # Same dangerous-command / base64-payload filter as
                            # Real PC Control and the main VM chat handler.
                            if cmd in ('type', 'text', 'say', 'send', 'sendline',
                                       'typeenter', 'key', 'press', 'enter'):
                                if _vm_keyboard_blocked(cmd, args, user):
                                    continue
                            if cmd in ('type', 'text', 'say'):
                                send_keyboard(args)
                            elif cmd in ('send', 'sendline', 'typeenter'):
                                send_keyboard(args); send_special_enter()
                            elif cmd == 'enter':
                                send_special_enter()
                            elif cmd in ('key', 'press'):
                                k = args.lower().strip()
                                if k in SCANCODES:
                                    send_scancode(SCANCODES[k][0])
                                    time.sleep(0.01)
                                    send_scancode(SCANCODES[k][1])
                                else:
                                    send_keyboard(k)
                            elif cmd in ('combo', 'chord', 'multi'):
                                keys = args.lower().replace('+', ' ').split()
                                if keys: send_combo(keys)
                            elif cmd in ('click', 'lclick', 'rclick', 'rightclick',
                                         'mclick', 'middleclick', 'move', 'mouse', 'mv',
                                         'abs', 'cursor', 'moveabs', 'drag', 'dragrel',
                                         'holdclick', 'holdrclick',
                                         'dragabs', 'drag_absolute', 'scroll', 'wheel'):
                                handle_mouse(cmd, args)
                        except Exception as e:
                            print(f"[MultiStream] Command error: {e}")
            except Exception as e:
                if not bot_stop_event.is_set():
                    print(f"[MultiStream:{self.video_id}] Error: {e} → reconnecting...")
                    self._reconnect()
            if bot_stop_event.wait(0.05):
                break
        if self.chat:
            try: self.chat.terminate()
            except: pass
        print(f"[MultiStream] Stopped: {self.video_id}")


# ========================= STDOUT REDIRECT =========================
class ConsoleRedirect:
    """Redirects stdout/stderr to a Tkinter ScrolledText widget."""
    def __init__(self, widget):
        self.widget = widget
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr

    def write(self, msg):
        self._orig_stdout.write(msg)
        # Schedule the widget update on the main thread (Tkinter is not thread-safe).
        # Guard against the widget being destroyed after the bot stops.
        # Skip bare newline messages — they are the second call that Python's print()
        # makes after writing the actual text, and they would produce "[HH:MM:SS] \n"
        # as a spurious blank timestamped line in the console.
        if not msg or msg == "\n":
            def _update_nl(m=msg):
                try:
                    widget = self.widget
                    if widget.winfo_exists():
                        widget.configure(state='normal')
                        widget.insert('end', m)
                        widget.see('end')
                        widget.configure(state='disabled')
                except Exception:
                    pass
            try:
                self.widget.after(0, _update_nl)
            except Exception:
                pass
            return
        try:
            widget = self.widget
            if not widget.winfo_exists():
                return
            ts = time.strftime("%H:%M:%S")
            formatted = f"[{ts}] {msg}"
            def _update(m=formatted):
                try:
                    if widget.winfo_exists():
                        widget.configure(state='normal')
                        widget.insert('end', m)
                        widget.see('end')
                        widget.configure(state='disabled')
                except Exception:
                    pass
            widget.after(0, _update)
        except Exception:
            pass

    def flush(self): pass

    def start(self):
        sys.stdout = self
        sys.stderr = self

    def stop(self):
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr


# ========================= GUI =========================
class NexovativeControlCenter:
    # ── Color palette ──
    BG       = "#0f0f1a"
    BG2      = "#16162a"
    BG3      = "#1e1e35"
    ACCENT   = "#7c5cbf"
    ACCENT2  = "#a07cdf"
    GREEN    = "#3ddc97"
    RED      = "#e05c7a"
    YELLOW   = "#f0c060"
    TEXT     = "#e8e8f0"
    TEXTDIM  = "#8888aa"
    CONSOLE  = "#0a0a14"
    CONTEXT  = "#00e676"
    BORDER   = "#2d2d50"
    _FONT_SIZE = 10

    def __init__(self, root):
        self.root = root
        self.root.title("🤖 Nexovative Control Center")
        self.root.configure(bg=self.BG)
        self.root.resizable(True, True)

        # If the user picked a non-primary monitor, move the window there
        # first — "zoomed" maximizes on whichever monitor the window
        # currently overlaps, so the move has to happen before that.
        if SELECTED_MONITOR and not SELECTED_MONITOR.get("is_primary"):
            mx, my = SELECTED_MONITOR["left"], SELECTED_MONITOR["top"]
            self.root.geometry(f"900x600+{mx + 20}+{my + 20}")
            self.root.update_idletasks()

        # Open maximized (windowed fullscreen — not borderless, still has taskbar/titlebar)
        self.root.state("zoomed")
        self.root.minsize(900, 600)

        self._bot_thread   = None
        self._bot_running  = False
        self._bot_instance = None
        self._console_redir = None

        # Edit state for Command Builder
        self._editing_cmd  = None   # trigger key being edited
        self._step_items   = []     # list of {"action":..,"args":..} dicts

        # Unsaved-changes guard: set of tab indices that have unsaved changes
        self._unsaved_tabs = set()
        self._current_tab  = 0      # index of the currently visible tab

        global _gui_app
        _gui_app = self
        load_appearance_config()
        self._build_styles()
        load_os_voting_config()
        load_auto_start_config()
        load_obs_config()
        load_permissions_config()
        load_sound_config()
        load_multi_stream_config()
        load_scheduler_config()
        load_custom_commands()
        load_nexoai_config()
        load_vm_danger_filter_config()
        load_youtube_api_key_config()
        self._build_ui()
        self._setup_konami_code_listener()

    # ── TTK Styles ──
    def _make_context_menu(self, widget, is_text=False):
        """Create and attach a right-click copy/paste/cut/select-all menu to a widget."""
        MAX_PASTE_CHARS = 2000   # hard limit to prevent freeze on huge clipboard content

        menu = tk.Menu(widget, tearoff=0,
                       bg=self.BG2, fg=self.TEXT,
                       activebackground=self.ACCENT,
                       activeforeground="#fff",
                       relief="flat", bd=0,
                       font=("Segoe UI", 9))

        def safe_paste():
            try:
                text = widget.clipboard_get()
            except Exception:
                return   # clipboard empty or unavailable
            if len(text) > MAX_PASTE_CHARS:
                text = text[:MAX_PASTE_CHARS]
                messagebox.showwarning(
                    "Paste Truncated",
                    f"Clipboard content was too long and has been truncated to {MAX_PASTE_CHARS} characters."
                )
            try:
                if is_text:
                    try:
                        widget.delete("sel.first", "sel.last")
                    except Exception:
                        pass
                    widget.insert("insert", text)
                else:
                    try:
                        sel_start = widget.index("sel.first")
                        sel_end   = widget.index("sel.last")
                        widget.delete(sel_start, sel_end)
                    except Exception:
                        pass
                    widget.insert(tk.INSERT, text)
            except Exception:
                pass

        menu.add_command(label="Cut",        command=lambda: widget.event_generate("<<Cut>>"))
        menu.add_command(label="Copy",       command=lambda: widget.event_generate("<<Copy>>"))
        menu.add_command(label="Paste",      command=safe_paste)
        menu.add_separator()
        menu.add_command(label="Select All", command=lambda: (
            widget.tag_add("sel", "1.0", "end") if is_text
            else (widget.select_range(0, "end"), widget.icursor("end"))
        ))
        menu.add_separator()
        menu.add_command(label="Delete",     command=lambda: widget.event_generate("<<Clear>>"))

        def show_menu(event):
            try:
                state    = str(widget.cget("state"))
                editable = state not in ("disabled", "readonly")
                for label in ("Cut", "Paste", "Delete"):
                    menu.entryconfigure(label,
                        state="normal" if editable else "disabled")
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        widget.bind("<Button-3>", show_menu)

    def _bind_context_menus(self, parent=None):
        """Walk all widgets and attach right-click menus to Entry and Text widgets."""
        if parent is None:
            parent = self.root
        for widget in parent.winfo_children():
            wtype = widget.winfo_class()
            if wtype in ("Entry", "TEntry"):
                self._make_context_menu(widget, is_text=False)
            elif wtype == "Text":
                self._make_context_menu(widget, is_text=True)
            self._bind_context_menus(widget)

    def _build_styles(self):
        fs = self.__class__._FONT_SIZE
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".",
            background=self.BG, foreground=self.TEXT,
            fieldbackground=self.BG2, bordercolor=self.BORDER,
            troughcolor=self.BG2, selectbackground=self.ACCENT,
            selectforeground=self.TEXT, font=("Segoe UI", fs))
        style.configure("TNotebook",
            background=self.BG, tabmargins=[2, 4, 0, 0])
        style.configure("TNotebook.Tab",
            background=self.BG2, foreground=self.TEXTDIM,
            padding=[5, 4], font=("Segoe UI", fs))
        style.map("TNotebook.Tab",
            background=[("selected", self.BG3)],
            foreground=[("selected", self.TEXT)])
        style.configure("TFrame", background=self.BG)
        style.configure("Card.TFrame", background=self.BG2)
        style.configure("TLabel",  background=self.BG,  foreground=self.TEXT)
        style.configure("Dim.TLabel", background=self.BG2, foreground=self.TEXTDIM)
        style.configure("TEntry",
            fieldbackground=self.BG3, foreground=self.TEXT,
            insertcolor=self.TEXT, bordercolor=self.BORDER, relief="flat")
        style.configure("TCombobox",
            fieldbackground=self.BG3, foreground=self.TEXT,
            selectbackground=self.ACCENT, arrowcolor=self.ACCENT2)
        style.map("TCombobox", fieldbackground=[("readonly", self.BG3)])
        for name, bg, fg in [
            ("Green.TButton",  self.GREEN,  "#000"),
            ("Red.TButton",    self.RED,    "#fff"),
            ("Accent.TButton", self.ACCENT, "#fff"),
            ("Dim.TButton",    self.BG3,    self.TEXT),
        ]:
            style.configure(name, background=bg, foreground=fg,
                            font=("Segoe UI", fs, "bold"), relief="flat", padding=[10,5])
            style.map(name, background=[("active", self.ACCENT2)])
        style.configure("TScrollbar",
            background=self.BG3, troughcolor=self.BG,
            arrowcolor=self.ACCENT2, bordercolor=self.BG)
        style.configure("TScale",
            background=self.BG2, troughcolor=self.BG3,
            bordercolor=self.BG2, lightcolor=self.ACCENT,
            darkcolor=self.ACCENT)

    # ── Main UI ──
    def _build_ui(self):
        # Title bar
        title_bar = tk.Frame(self.root, bg=self.BG2, height=48)
        title_bar.pack(fill="x", side="top")
        title_bar.pack_propagate(False)
        self._title_label = tk.Label(title_bar, text="🤖  Nexovative Control Center",
                 bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI", 13, "bold"), cursor="hand2")
        self._title_label.pack(side="left", padx=16, pady=8)
        self._title_click_count = 0
        self._title_click_reset_job = None
        self._title_label.bind("<Button-1>", self._on_title_click)

        # ── System resource monitor (CPU / RAM usage) ──
        self._sysmon_label = tk.Label(
            title_bar, text="", bg=self.BG2, fg=self.TEXTDIM,
            font=("Segoe UI", 9))
        if _PSUTIL_OK:
            self._sysmon_label.pack(side="left", padx=(4, 0))
            self._start_system_monitor()

        self._status_dot = tk.Label(title_bar, text="⬤  Stopped",
                                    bg=self.BG2, fg=self.RED,
                                    font=("Segoe UI", 10, "bold"))
        self._status_dot.pack(side="right", padx=16)
        ttk.Button(title_bar, text="❓ Help",
                   style="Dim.TButton",
                   command=lambda: self.show_welcome_guide(force=True)
                   ).pack(side="right", padx=(0, 4), pady=6)

        # ── Scrollable tab bar wrapper ──
        # The ttk.Notebook tab strip doesn't scroll natively. We wrap it in a
        # Canvas so the tab bar gets a horizontal scrollbar when tabs overflow,
        # and we bind MouseWheel so users can cycle tabs with the scroll wheel.
        nb_outer = tk.Frame(self.root, bg=self.BG)
        nb_outer.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        nb = ttk.Notebook(nb_outer)
        self.nb = nb   # kept for dynamic tab insertion (e.g. the hidden Fun tab easter egg)
        nb.pack(fill="both", expand=True)

        # Horizontal scrollbar that only appears when tabs overflow
        tab_scroll = ttk.Scrollbar(nb_outer, orient="horizontal",
                                   command=lambda *a: None)  # placeholder; wired below
        tab_scroll.pack(fill="x", side="bottom")

        # Wire scrollbar to notebook tab strip position
        # Tkinter doesn't expose the internal tab canvas, so we approximate:
        # the scrollbar moves the notebook's internal tab area via tk.call.
        def _nb_xscroll(*args):
            try:
                nb.tk.call(nb._w, "xview", *args)
            except Exception:
                pass

        def _update_scrollbar(event=None):
            try:
                nb_w  = nb.winfo_width()
                # approximate: show scrollbar only when tabs overflow
                tab_count  = nb.index("end")
                # approximate: each tab ~110px
                est_total  = tab_count * 118
                if est_total > nb_w and nb_w > 10:
                    tab_scroll.pack(fill="x", side="bottom")
                else:
                    tab_scroll.pack_forget()
            except Exception:
                pass

        nb.bind("<Configure>", _update_scrollbar)

        # MouseWheel → cycle tabs
        def _nb_scroll(event):
            try:
                cur   = nb.index("current")
                total = nb.index("end")
                if event.delta > 0:
                    nb.select((cur - 1) % total)
                else:
                    nb.select((cur + 1) % total)
            except Exception:
                pass

        nb.bind("<MouseWheel>", _nb_scroll)
        # Also bind on the title bar area so wheel anywhere on top works
        title_bar.bind("<MouseWheel>", _nb_scroll)
        self.root.bind("<Control-Tab>",       lambda e: nb.select((nb.index("current") + 1) % nb.index("end")))
        self.root.bind("<Control-Shift-Tab>", lambda e: nb.select((nb.index("current") - 1) % nb.index("end")))

        tab1 = ttk.Frame(nb)
        tab2 = ttk.Frame(nb)
        tab3 = ttk.Frame(nb)
        tab4 = ttk.Frame(nb)
        tab5 = ttk.Frame(nb)
        tab6 = ttk.Frame(nb)
        tab7 = ttk.Frame(nb)
        tab8 = ttk.Frame(nb)
        tab9  = ttk.Frame(nb)
        tab10 = ttk.Frame(nb)
        tab11 = ttk.Frame(nb)
        tab12 = ttk.Frame(nb)
        tab13 = ttk.Frame(nb)
        tab14 = ttk.Frame(nb)
        tab15 = ttk.Frame(nb)
        tab16 = ttk.Frame(nb)
        nb.add(tab1,  text="▶ Main")
        nb.add(tab2,  text="⚙ Cmds")
        nb.add(tab3,  text="🖥 VM")
        nb.add(tab4,  text="🗳 OS Vote")
        nb.add(tab5,  text="🎨 Theme")
        nb.add(tab6,  text="📡 OBS")
        nb.add(tab7,  text="📊 Stats")
        nb.add(tab8,  text="🚫 Users")
        nb.add(tab9,  text="📋 Log")
        nb.add(tab10, text="🔒 Perms")
        nb.add(tab11, text="🔊 Sound")
        nb.add(tab12, text="🌐 Streams")
        nb.add(tab13, text="📅 Sched")
        nb.add(tab14, text="🖱 Real PC (BETA)")
        nb.add(tab15, text="🔄 Reconnect")
        nb.add(tab16, text="🤖 NexoAI")
        self._fun_tab_anchor = tab15   # hidden Fun tab (easter egg) is inserted right before this one

        if not APP_LITE_MODE:
            # ── Full GUI Mode: build every tab immediately, as before. ──
            self._build_main_tab(tab1)
            self._build_cmd_builder_tab(tab2)
            self._build_vm_controls_tab(tab3)
            self._build_os_voting_tab(tab4)
            self._build_appearance_tab(tab5)
            self._build_obs_tab(tab6)
            self._build_statistics_tab(tab7)
            self._build_user_mgmt_tab(tab8)
            self._build_event_log_tab(tab9)
            self._build_permissions_tab(tab10)
            self._build_sound_tts_tab(tab11)
            self._build_multi_stream_tab(tab12)
            self._build_scheduler_tab(tab13)
            self._build_realpc_tab(tab14)
            self._build_reconnect_tab(tab15)
            self._build_nexoai_tab(tab16)
        else:
            # ── Lite Mode: ULTRA — only the tab currently being viewed is
            # ever built. Main, VM controls, and Real PC stay built (they're
            # needed for the bot to actually run), but every other tab is
            # destroyed the moment you leave it and rebuilt from scratch the
            # next time you open it. This keeps memory/CPU usage down to
            # "one extra tab's worth" at any given moment, instead of
            # accumulating every tab you've ever visited.
            self._build_main_tab(tab1)
            self._build_vm_controls_tab(tab3)
            self._build_realpc_tab(tab14)

            self._lazy_tab_builders = {
                tab2:  self._build_cmd_builder_tab,
                tab4:  self._build_os_voting_tab,
                tab5:  self._build_appearance_tab,
                tab6:  self._build_obs_tab,
                tab7:  self._build_statistics_tab,
                tab8:  self._build_user_mgmt_tab,
                tab9:  self._build_event_log_tab,
                tab10: self._build_permissions_tab,
                tab11: self._build_sound_tts_tab,
                tab12: self._build_multi_stream_tab,
                tab13: self._build_scheduler_tab,
                tab15: self._build_reconnect_tab,
                tab16: self._build_nexoai_tab,
            }
            # Maps tab index -> the frame's own "unsaved changes" save
            # function, so we can offer to save before tearing a tab down.
            self._lazy_tab_save_fns = {
                1:  self._save_cmd,
                3:  self._save_os_voting_config,
                5:  self._obs_save,
                9:  self._save_permissions,
                10: self._save_sound_config,
                11: self._ms_save,
                12: self._sched_save,
                14: self._save_reconnect_config,
            }
            self._lazy_tab_currently_built = None   # the one lazy frame that's live right now

            def _show_loading_placeholder(frame):
                tk.Label(frame, text="Loading…", bg=self.BG,
                         fg=self.TEXTDIM, font=("Segoe UI", 10)).pack(pady=40)

            for frame in list(self._lazy_tab_builders.keys()):
                _show_loading_placeholder(frame)

            def _teardown_lazy_tab(frame):
                """Destroy a lazy tab's real widgets and put the placeholder back."""
                for child in frame.winfo_children():
                    child.destroy()
                _show_loading_placeholder(frame)

            def _build_tab_on_first_view(event):
                try:
                    current = nb.nametowidget(nb.select())
                except Exception:
                    return

                # Tear down whichever lazy tab was previously active (if any,
                # and if it isn't the one we're switching to).
                prev = self._lazy_tab_currently_built
                if prev is not None and prev is not current:
                    prev_idx = None
                    try:
                        prev_idx = nb.index(prev)
                    except Exception:
                        pass
                    # Offer to save unsaved changes before destroying the tab —
                    # once destroyed, any typed-but-unsaved data is gone for good.
                    if prev_idx is not None and prev_idx in self._unsaved_tabs:
                        tab_name = nb.tab(prev_idx, "text")
                        answer = messagebox.askyesno(
                            "Unsaved Changes",
                            f"The tab  \"{tab_name}\"  has unsaved changes.\n\n"
                            "Save before closing this tab? (Lite Mode unloads "
                            "tabs you're not viewing to save memory — unsaved "
                            "data will be lost otherwise.)"
                        )
                        if answer:
                            save_fn = self._lazy_tab_save_fns.get(prev_idx)
                            if save_fn:
                                try:
                                    save_fn()
                                except Exception:
                                    pass
                        self._unsaved_tabs.discard(prev_idx)
                    _teardown_lazy_tab(prev)
                    self._lazy_tab_built.discard(prev)
                    self._lazy_tab_currently_built = None

                # Build the newly-selected lazy tab, if it is one and isn't
                # already built (it never should be at this point, but the
                # check is cheap insurance).
                if current in self._lazy_tab_builders and current not in self._lazy_tab_built:
                    builder = self._lazy_tab_builders[current]
                    for child in current.winfo_children():
                        child.destroy()   # remove the "Loading…" placeholder
                    builder(current)
                    self._lazy_tab_built.add(current)
                    self._lazy_tab_currently_built = current
                elif current in self._lazy_tab_builders:
                    self._lazy_tab_currently_built = current

            self._lazy_tab_built = set()
            nb.bind("<<NotebookTabChanged>>", _build_tab_on_first_view, add="+")
        self._sync_main_vm_lock()
        self._nb = nb   # store reference for unsaved-changes guard
        self._bind_context_menus()   # attach right-click menus to all Entry/Text widgets
        self._stats_update_job = None
        self.root.after(5000 if APP_LITE_MODE else 1000, self._refresh_stats_display)

        # ── Unsaved-changes guard: intercept tab switches ──
        # Tab indices that can have unsaved state (matched by name text prefix):
        # 1=Commands, 3=OS Voting, 5=OBS, 9=Permissions, 10=Sound&TTS,
        # 11=Multi-Stream, 12=Scheduler, 13=Real PC, 14=Reconnect
        # NOTE: in Lite Mode, indices 1,3,5,9,10,11,12,14 are lazy tabs whose
        # unsaved-changes check + save-prompt is already handled by
        # _build_tab_on_first_view right before it tears the tab down. Only
        # index 13 (Real PC) is always eagerly built, so it's the only one
        # this guard still needs to handle when Lite Mode is on.
        _lazy_guarded_indices = {1, 3, 5, 9, 10, 11, 12, 14}

        def _on_tab_changed(event):
            try:
                new_idx = nb.index(nb.select())
                old_idx = self._current_tab
                if new_idx == old_idx:
                    return
                if APP_LITE_MODE and old_idx in _lazy_guarded_indices:
                    # Already handled by the lazy-tab teardown logic above.
                    self._current_tab = new_idx
                    return
                if old_idx in self._unsaved_tabs:
                    tab_name = nb.tab(old_idx, "text")
                    answer = messagebox.askyesno(
                        "Unsaved Changes",
                        f"The tab  \"{tab_name}\"  has unsaved changes.\n\n"
                        "Save before switching tabs?"
                    )
                    if answer:
                        # Route to the correct save method based on old tab index
                        save_map = {
                            1:  self._save_cmd,
                            3:  self._save_os_voting_config,
                            5:  self._obs_save,
                            9:  self._save_permissions,
                            10: self._save_sound_config,
                            11: self._ms_save,
                            12: self._sched_save,
                            13: self._rpc_save,
                            14: self._save_reconnect_config,
                        }
                        save_fn = save_map.get(old_idx)
                        if save_fn:
                            save_fn()
                    # Clear the dirty flag regardless of the user's choice
                    self._unsaved_tabs.discard(old_idx)
                self._current_tab = new_idx
            except Exception:
                pass

        nb.bind("<<NotebookTabChanged>>", _on_tab_changed, add="+")

    # ──────────────── TAB 1 : MAIN ────────────────
    def _build_main_tab(self, parent):
        parent.configure(style="TFrame")

        # Config card
        card = ttk.Frame(parent, style="Card.TFrame", padding=16)
        card.pack(fill="x", padx=12, pady=(12,6))

        # YouTube ID
        tk.Label(card, text="YouTube Video ID", bg=self.BG2,
                 fg=self.TEXTDIM, font=("Segoe UI",9,"bold")).grid(
                 row=0, column=0, sticky="w", padx=(0,8))
        self._yt_var = tk.StringVar()
        yt_entry = ttk.Entry(card, textvariable=self._yt_var, width=32,
                             font=("Segoe UI Mono", 10))
        yt_entry.grid(row=0, column=1, sticky="ew", padx=(0,12), ipady=4)
        tk.Label(card, text="🔗", bg=self.BG2, fg=self.ACCENT,
                 font=("Segoe UI",12)).grid(row=0, column=2, padx=2)

        # VM selector
        tk.Label(card, text="VirtualBox VM (optional)", bg=self.BG2,
                 fg=self.TEXTDIM, font=("Segoe UI",9,"bold")).grid(
                 row=1, column=0, sticky="w", padx=(0,8), pady=(10,0))
        self._vm_var = tk.StringVar()
        self._vm_combo = ttk.Combobox(card, textvariable=self._vm_var,
                                      state="readonly", width=30,
                                      font=("Segoe UI",10))
        self._vm_combo.grid(row=1, column=1, sticky="ew", padx=(0,12),
                            pady=(10,0), ipady=3)
        ttk.Button(card, text="🔄 Refresh", style="Dim.TButton",
                   command=self._refresh_vm_list).grid(
                   row=1, column=2, pady=(10,0))
        self._vm_select_note = tk.Label(card,
                 text="Leave blank to run chat-only (no VM control) — YouTube chat works without a VM.",
                 bg=self.BG2, fg=self.TEXTDIM, font=("Segoe UI", 8, "italic"))
        self._vm_select_note.grid(row=2, column=0, columnspan=3, sticky="w", pady=(2,0))

        # Auto-start watchdog toggle
        tk.Label(card, text="Auto-Start Watchdog", bg=self.BG2,
                 fg=self.TEXTDIM, font=("Segoe UI",9,"bold")).grid(
                 row=3, column=0, sticky="w", padx=(0,8), pady=(10,0))
        self._auto_start_var = tk.BooleanVar(value=AUTO_START_ENABLED)
        auto_chk = tk.Checkbutton(card,
            text="Auto-restart the VM if it's found powered off",
            variable=self._auto_start_var, bg=self.BG2, fg=self.TEXT,
            selectcolor=self.BG3, activebackground=self.BG2,
            activeforeground=self.TEXT, font=("Segoe UI", 9),
            command=self._on_auto_start_toggle)
        auto_chk.grid(row=3, column=1, columnspan=2, sticky="w", pady=(10,0))

        # Base64 / Dangerous Command Blocker (VM) toggle
        tk.Label(card, text="Danger Filter", bg=self.BG2,
                 fg=self.TEXTDIM, font=("Segoe UI",9,"bold")).grid(
                 row=4, column=0, sticky="w", padx=(0,8), pady=(10,0))
        danger_row = tk.Frame(card, bg=self.BG2)
        danger_row.grid(row=4, column=1, columnspan=2, sticky="w", pady=(10,0))
        self._vm_danger_filter_var = tk.BooleanVar(value=VM_DANGER_FILTER_ENABLED)
        danger_chk = tk.Checkbutton(danger_row,
            text="🛡 Block dangerous commands & base64 payloads typed into the VM",
            variable=self._vm_danger_filter_var, bg=self.BG2, fg=self.TEXT,
            selectcolor=self.BG3, activebackground=self.BG2,
            activeforeground=self.TEXT, font=("Segoe UI", 9),
            command=self._on_vm_danger_filter_toggle)
        danger_chk.pack(side="left")
        ttk.Button(danger_row, text="📋 View Blocked List", style="Dim.TButton",
                   command=self._show_blocked_commands_list).pack(side="left", padx=(10,0))
        tk.Label(card,
                 text="Blocks destructive commands and long base64-encoded payloads "
                      "(e.g. images decoded straight to disk) typed via chat into the VM.",
                 bg=self.BG2, fg=self.TEXTDIM, font=("Segoe UI", 8),
                 justify="left").grid(row=5, column=1, columnspan=2, sticky="w", pady=(0,4))

        # YouTube Data API v3 key (optional) — enables the most reliable
        # of the three chat backends. See YouTubeChatSource for details.
        tk.Label(card, text="YouTube API Key", bg=self.BG2,
                 fg=self.TEXTDIM, font=("Segoe UI",9,"bold")).grid(
                 row=6, column=0, sticky="w", padx=(0,8), pady=(10,0))
        api_key_row = tk.Frame(card, bg=self.BG2)
        api_key_row.grid(row=6, column=1, columnspan=2, sticky="ew", pady=(10,0))
        self._yt_api_key_var = tk.StringVar(value=YOUTUBE_API_KEY)
        self._yt_api_key_entry = ttk.Entry(
            api_key_row, textvariable=self._yt_api_key_var,
            width=32, font=("Segoe UI Mono", 9), show="•")
        self._yt_api_key_entry.pack(side="left", ipady=3, fill="x", expand=True)
        self._yt_api_key_visible = False
        def _toggle_yt_api_key_visibility():
            self._yt_api_key_visible = not self._yt_api_key_visible
            self._yt_api_key_entry.configure(show="" if self._yt_api_key_visible else "•")
            yt_key_show_btn.configure(text="🙈 Hide" if self._yt_api_key_visible else "👁 Show")
        yt_key_show_btn = ttk.Button(api_key_row, text="👁 Show", style="Dim.TButton",
                                      command=_toggle_yt_api_key_visibility)
        yt_key_show_btn.pack(side="left", padx=(6,0))
        ttk.Button(api_key_row, text="💾 Save Key", style="Green.TButton",
                   command=self._save_youtube_api_key).pack(side="left", padx=(6,0))
        tk.Label(card,
                 text="Optional. Enables the official YouTube Data API v3 chat backend — "
                      "the only one Google guarantees won't break, but it uses your API "
                      "quota. Leave blank to keep using the free (unofficial) backends. "
                      "Saved locally, entered once.",
                 bg=self.BG2, fg=self.TEXTDIM, font=("Segoe UI", 8),
                 justify="left").grid(row=7, column=1, columnspan=2, sticky="w", pady=(2,4))

        # Chat backend picker (auto / official / chat-downloader / pytchat)
        tk.Label(card, text="Chat Backend", bg=self.BG2,
                 fg=self.TEXTDIM, font=("Segoe UI",9,"bold")).grid(
                 row=8, column=0, sticky="w", padx=(0,8), pady=(10,0))
        backend_row = tk.Frame(card, bg=self.BG2)
        backend_row.grid(row=8, column=1, columnspan=2, sticky="w", pady=(10,0))
        self._chat_backend_status_lbl = tk.Label(
            backend_row, text=f"Currently: {CHAT_BACKEND_PREFERENCE}",
            bg=self.BG2, fg=self.ACCENT, font=("Segoe UI", 9, "bold"))
        self._chat_backend_status_lbl.pack(side="left")
        ttk.Button(backend_row, text="🔀 Change Chat Backend", style="Dim.TButton",
                   command=self._change_chat_backend).pack(side="left", padx=(10,0))

        card.columnconfigure(1, weight=1)

        # Start / Stop buttons
        btn_frame = tk.Frame(parent, bg=self.BG)
        btn_frame.pack(fill="x", padx=12, pady=6)
        ttk.Button(btn_frame, text="▶  Start Bot", style="Green.TButton",
                   command=self._start_bot).pack(side="left", padx=(0,8))
        ttk.Button(btn_frame, text="⏹  Stop Bot", style="Red.TButton",
                   command=self._stop_bot).pack(side="left")
        ttk.Button(btn_frame, text="📌  Minimize to Tray", style="Dim.TButton",
                   command=self._minimize_to_tray).pack(side="left", padx=(8, 0))

        # Test Mode
        test_frame = tk.Frame(parent, bg=self.BG2, padx=12, pady=8)
        test_frame.pack(fill="x", padx=12, pady=(0, 4))
        self._test_mode_var = tk.BooleanVar(value=False)
        self._test_mode_btn = tk.Checkbutton(
            test_frame,
            text="🧪  Test Mode  (control VM from console — no YouTube connection needed)",
            variable=self._test_mode_var,
            bg=self.BG2, fg=self.YELLOW,
            selectcolor=self.BG3,
            activebackground=self.BG2,
            activeforeground=self.YELLOW,
            font=("Segoe UI", 9, "bold"),
            command=self._on_test_mode_toggle,
        )
        self._test_mode_btn.pack(anchor="w")
        self._test_mode_note = tk.Label(
            test_frame,
            text="When enabled: select a VM, then type commands in the console window (e.g. !type hello  !click  !combo win+r)",
            bg=self.BG2, fg=self.TEXTDIM,
            font=("Segoe UI", 8),
            wraplength=740, justify="left",
        )
        self._test_mode_note.pack(anchor="w", pady=(2, 0))

        # Admin command bar packed with side='bottom' BEFORE the console,
        # so it stays visible. If packed after a widget with expand=True,
        # the console would consume all space and push the bar off-screen.
        admin_frame = tk.Frame(parent, bg=self.BG2, pady=6)
        admin_frame.pack(fill="x", padx=12, pady=(0,4), side="bottom")
        tk.Label(admin_frame, text="Admin CMD:",
                 bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI",9,"bold")).pack(side="left", padx=(8,6))
        self._admin_var = tk.StringVar()
        admin_entry = ttk.Entry(admin_frame, textvariable=self._admin_var,
                                width=36, font=("Segoe UI Mono",10))
        admin_entry.pack(side="left", padx=(0,8), ipady=4)
        admin_entry.bind("<Return>", lambda e: self._send_admin_cmd())
        ttk.Button(admin_frame, text="Send ↵", style="Accent.TButton",
                   command=self._send_admin_cmd).pack(side="left")

        # ── Bottom pane: Live Chat Viewer | Console Output ──
        bottom_pane = tk.PanedWindow(parent, orient="horizontal",
                                     bg=self.BORDER, sashwidth=5,
                                     sashrelief="flat", bd=0)
        bottom_pane.pack(fill="both", expand=True, padx=12, pady=(2, 0))

        # Left: Live Chat Viewer
        chat_outer = tk.Frame(bottom_pane, bg=self.BG)
        bottom_pane.add(chat_outer, minsize=220, width=320)

        chat_hdr = tk.Frame(chat_outer, bg=self.BG)
        chat_hdr.pack(fill="x", pady=(0, 4))
        tk.Label(chat_hdr, text="💬  Live Chat",
                 bg=self.BG, fg=self.ACCENT,
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Button(chat_hdr, text="🗑", style="Dim.TButton", width=2,
                   command=self._clear_chat_viewer).pack(side="right")

        chat_frame = tk.Frame(chat_outer, bg=self.BORDER, bd=1)
        chat_frame.pack(fill="both", expand=True)
        self._chat_viewer = tk.Text(
            chat_frame,
            bg=self.BG3, fg=self.TEXT,
            font=("Segoe UI", 9),
            insertbackground=self.TEXT,
            selectbackground=self.ACCENT,
            relief="flat", bd=0,
            state="disabled", wrap="word",
        )
        chat_scroll = ttk.Scrollbar(chat_frame, orient="vertical",
                                    command=self._chat_viewer.yview)
        chat_scroll.pack(side="right", fill="y")
        self._chat_viewer.pack(fill="both", expand=True, padx=1, pady=1)
        self._chat_viewer.configure(yscrollcommand=chat_scroll.set)

        # Color tags for chat viewer
        self._chat_viewer.tag_configure("owner",   foreground=self.YELLOW,  font=("Segoe UI", 9, "bold"))
        self._chat_viewer.tag_configure("command", foreground=self.GREEN,   font=("Segoe UI", 9, "bold"))
        self._chat_viewer.tag_configure("vip",     foreground=self.ACCENT,  font=("Segoe UI", 9, "bold"))
        self._chat_viewer.tag_configure("banned",  foreground=self.RED,     font=("Segoe UI", 9, "italic"))
        self._chat_viewer.tag_configure("normal",  foreground=self.TEXT,    font=("Segoe UI", 9))
        self._chat_viewer.tag_configure("user",    foreground=self.TEXTDIM, font=("Segoe UI", 9, "bold"))
        self._chat_viewer.tag_configure("ts",      foreground=self.TEXTDIM, font=("Segoe UI", 8))
        self._chat_viewer.tag_configure("system",  foreground=self.ACCENT2, font=("Segoe UI", 8, "italic"))

        # Auto-scroll toggle
        self._chat_autoscroll = tk.BooleanVar(value=True)
        tk.Checkbutton(chat_outer, text="Auto-scroll",
                       variable=self._chat_autoscroll,
                       bg=self.BG, fg=self.TEXTDIM,
                       selectcolor=self.BG3, activebackground=self.BG,
                       font=("Segoe UI", 8)).pack(anchor="w", pady=(2, 0))

        # Right: Console Output
        console_outer = tk.Frame(bottom_pane, bg=self.BG)
        bottom_pane.add(console_outer, minsize=200)

        tk.Label(console_outer, text="Console Output",
                 bg=self.BG, fg=self.TEXTDIM,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 4))

        console_frame = tk.Frame(console_outer, bg=self.BORDER, bd=1)
        console_frame.pack(fill="both", expand=True)
        self._console = scrolledtext.ScrolledText(
            console_frame,
            bg=self.CONSOLE, fg=self.CONTEXT,
            font=("Cascadia Code", 9) if self._font_exists("Cascadia Code")
                 else ("Consolas", 9),
            insertbackground=self.CONTEXT,
            selectbackground=self.ACCENT,
            relief="flat", bd=0, state='disabled',
            wrap='word'
        )
        self._console.pack(fill="both", expand=True, padx=1, pady=1)

        # Initial VM list load
        self._refresh_vm_list()

    def _clear_chat_viewer(self):
        try:
            self._chat_viewer.configure(state="normal")
            self._chat_viewer.delete("1.0", "end")
            self._chat_viewer.configure(state="disabled")
        except Exception:
            pass

    def _append_chat(self, user: str, msg: str, is_owner: bool = False,
                     is_command: bool = False, is_banned: bool = False):
        """Append a chat message to the Live Chat Viewer widget (thread-safe)."""
        def _do():
            try:
                ts   = time.strftime("%H:%M:%S")
                self._chat_viewer.configure(state="normal")
                self._chat_viewer.insert("end", f"[{ts}] ", "ts")
                if is_banned:
                    self._chat_viewer.insert("end", f"{user}", "banned")
                elif is_owner:
                    self._chat_viewer.insert("end", f"★{user}", "owner")
                elif user in vip_users:
                    self._chat_viewer.insert("end", f"♦{user}", "vip")
                else:
                    self._chat_viewer.insert("end", f"{user}", "user")
                self._chat_viewer.insert("end", ": ", "ts")
                tag = "command" if is_command else "normal"
                self._chat_viewer.insert("end", f"{msg}\n", tag)
                # Keep last 500 lines
                line_count = int(self._chat_viewer.index("end-1c").split(".")[0])
                if line_count > 500:
                    self._chat_viewer.delete("1.0", f"{line_count - 500}.0")
                self._chat_viewer.configure(state="disabled")
                if self._chat_autoscroll.get():
                    self._chat_viewer.see("end")
            except Exception:
                pass
        self.root.after(0, _do)

    def _append_chat_system(self, msg: str):
        """Append a system message (reconnect, bot start/stop) to the chat viewer."""
        def _do():
            try:
                ts = time.strftime("%H:%M:%S")
                self._chat_viewer.configure(state="normal")
                self._chat_viewer.insert("end", f"[{ts}] ── {msg} ──\n", "system")
                self._chat_viewer.configure(state="disabled")
                if self._chat_autoscroll.get():
                    self._chat_viewer.see("end")
            except Exception:
                pass
        self.root.after(0, _do)
    def _build_cmd_builder_tab(self, parent):
        parent.configure(style="TFrame")

        pane = tk.PanedWindow(parent, orient="horizontal",
                              bg=self.BG, sashwidth=6,
                              sashrelief="flat", bd=0)
        pane.pack(fill="both", expand=True, padx=8, pady=8)

        # ── Left panel: command list ──
        left = ttk.Frame(pane, style="Card.TFrame", padding=8)
        pane.add(left, minsize=180, width=220)

        tk.Label(left, text="Custom Commands",
                 bg=self.BG2, fg=self.ACCENT,
                 font=("Segoe UI",10,"bold")).pack(anchor="w", pady=(0,6))

        list_frame = tk.Frame(left, bg=self.BG3, highlightbackground=self.BORDER,
                              highlightthickness=1)
        list_frame.pack(fill="both", expand=True)
        self._cmd_listbox = tk.Listbox(
            list_frame,
            bg=self.BG3, fg=self.TEXT,
            selectbackground=self.ACCENT, selectforeground="#fff",
            activestyle="none", font=("Segoe UI Mono",10),
            relief="flat", bd=0, exportselection=False
        )
        self._cmd_listbox.pack(fill="both", expand=True)
        self._cmd_listbox.bind("<<ListboxSelect>>", self._on_cmd_select)

        btn_row = tk.Frame(left, bg=self.BG2)
        btn_row.pack(fill="x", pady=(6,0))
        ttk.Button(btn_row, text="＋ New", style="Green.TButton",
                   command=self._new_cmd).pack(side="left", expand=True, fill="x", padx=(0,4))
        ttk.Button(btn_row, text="🗑 Del", style="Red.TButton",
                   command=self._delete_cmd).pack(side="left", expand=True, fill="x")

        # ── Right panel: editor ──
        right = ttk.Frame(pane, style="Card.TFrame", padding=10)
        pane.add(right, minsize=300)

        # Trigger name row
        trig_row = tk.Frame(right, bg=self.BG2)
        trig_row.pack(fill="x", pady=(0,10))
        tk.Label(trig_row, text="Trigger:", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI",9,"bold")).pack(side="left", padx=(0,8))
        self._trig_var = tk.StringVar()
        ttk.Entry(trig_row, textvariable=self._trig_var,
                  font=("Segoe UI Mono",11), width=18).pack(side="left", ipady=4)
        tk.Label(trig_row, text="(e.g. !bubbles)",
                 bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI",9)).pack(side="left", padx=8)

        # ── Chain Input ──
        chain_card = tk.Frame(right, bg=self.BG3, pady=8, padx=10)
        chain_card.pack(fill="x", pady=(0,10))

        hdr_row = tk.Frame(chain_card, bg=self.BG3)
        hdr_row.pack(fill="x", pady=(0,4))
        tk.Label(hdr_row, text="⚡ Quick Chain Input",
                 bg=self.BG3, fg=self.ACCENT,
                 font=("Segoe UI",9,"bold")).pack(side="left")
        tk.Label(hdr_row,
                 text="  Write in chat syntax → parse into steps",
                 bg=self.BG3, fg=self.TEXTDIM,
                 font=("Segoe UI",8)).pack(side="left")

        chain_entry_row = tk.Frame(chain_card, bg=self.BG3)
        chain_entry_row.pack(fill="x")
        self._chain_var = tk.StringVar()
        chain_entry = ttk.Entry(chain_entry_row, textvariable=self._chain_var,
                                font=("Segoe UI Mono", 10))
        chain_entry.pack(side="left", fill="x", expand=True, ipady=5, padx=(0,8))
        chain_entry.bind("<Return>", lambda e: self._parse_chain_input())
        ttk.Button(chain_entry_row, text="⇨ Parse Steps",
                   style="Accent.TButton",
                   command=self._parse_chain_input).pack(side="left")

        tk.Label(chain_card,
                 text='Example: !combo win+r !send cmd.exe',
                 bg=self.BG3, fg=self.TEXTDIM,
                 font=("Segoe UI",8), wraplength=440, justify="left"
                 ).pack(anchor="w", pady=(4,0))

        # ── Steps header ──
        steps_hdr = tk.Frame(right, bg=self.BG2)
        steps_hdr.pack(fill="x", pady=(0,4))
        tk.Label(steps_hdr, text="Steps",
                 bg=self.BG2, fg=self.ACCENT,
                 font=("Segoe UI",10,"bold")).pack(side="left")
        tk.Label(steps_hdr,
                 text="  (Fill via Parse or add manually below)",
                 bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI",8)).pack(side="left")

        # Steps list (Treeview)
        tree_frame = tk.Frame(right, bg=self.BORDER, bd=1)
        tree_frame.pack(fill="both", expand=True, pady=(0,6))

        cols = ("action", "args")
        self._step_tree = ttk.Treeview(
            tree_frame, columns=cols, show="headings",
            height=8, selectmode="browse"
        )
        self._step_tree.heading("action", text="Action")
        self._step_tree.heading("args",   text="Arguments")
        self._step_tree.column("action",  width=120, minwidth=90)
        self._step_tree.column("args",    width=240, minwidth=120)
        self._step_tree.pack(fill="both", expand=True, side="left")

        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical",
                                    command=self._step_tree.yview)
        tree_scroll.pack(side="right", fill="y")
        self._step_tree.configure(yscrollcommand=tree_scroll.set)

        # Step reorder/delete buttons
        step_btn_row = tk.Frame(right, bg=self.BG2)
        step_btn_row.pack(fill="x", pady=(0,8))
        for txt, cmd in [("▲ Up","_step_up"), ("▼ Down","_step_down"),
                         ("✕ Remove","_step_remove")]:
            ttk.Button(step_btn_row, text=txt, style="Dim.TButton",
                       command=lambda c=cmd: getattr(self, c)()
                       ).pack(side="left", padx=(0,4))

        # Add step row
        add_frame = tk.Frame(right, bg=self.BG3, pady=8, padx=8)
        add_frame.pack(fill="x", pady=(0,8))
        tk.Label(add_frame, text="Add Step:", bg=self.BG3, fg=self.TEXTDIM,
                 font=("Segoe UI",9,"bold")).pack(side="left", padx=(0,8))

        ACTIONS = ["combo","send","sendenter","key","keydown","keyup",
                   "wait","click","rclick","move","abs","scroll"]
        self._action_var = tk.StringVar(value="combo")
        action_cb = ttk.Combobox(add_frame, textvariable=self._action_var,
                                  values=ACTIONS, state="readonly", width=12)
        action_cb.pack(side="left", padx=(0,8), ipady=3)

        tk.Label(add_frame, text="Args:", bg=self.BG3, fg=self.TEXTDIM,
                 font=("Segoe UI",9)).pack(side="left", padx=(0,4))
        self._args_var = tk.StringVar()
        ttk.Entry(add_frame, textvariable=self._args_var, width=20,
                  font=("Segoe UI Mono",10)).pack(side="left", padx=(0,8), ipady=3)
        ttk.Button(add_frame, text="＋ Add Step", style="Accent.TButton",
                   command=self._add_step).pack(side="left")

        # Hint label
        hint = ("combo: win+r  |  send: notepad.exe  |  wait: 1  |  "
                "sendenter: hello  |  key: enter  |  click / rclick")
        tk.Label(right, text=hint, bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI",8), wraplength=420, justify="left"
                 ).pack(anchor="w", pady=(0,6))

        # Save / Test buttons
        save_row = tk.Frame(right, bg=self.BG2)
        save_row.pack(fill="x")
        ttk.Button(save_row, text="💾  Save Command", style="Green.TButton",
                   command=self._save_cmd).pack(side="left", padx=(0,8))
        ttk.Button(save_row, text="▶  Test Now", style="Accent.TButton",
                   command=self._test_cmd).pack(side="left")

        # Track unsaved changes (tab index 1)
        self._trace_dirty(1, self._trig_var, self._chain_var, self._action_var, self._args_var)

        # Populate the listbox now that it exists — works for both eager
        # (Full GUI Mode) and lazy (Lite Mode, first-click) builds.
        self._refresh_cmd_list()

    # ──────────────── TAB 3 : VM CONTROLS ────────────────
    def _build_vm_controls_tab(self, parent):
        parent.configure(style="TFrame")

        # Header
        tk.Label(parent, text="Virtual Machine Controls",
                 bg=self.BG, fg=self.ACCENT,
                 font=("Segoe UI", 13, "bold")).pack(pady=(24, 4))
        tk.Label(parent,
                 text="Direct admin actions — no vote required.",
                 bg=self.BG, fg=self.TEXTDIM,
                 font=("Segoe UI", 9)).pack(pady=(0, 28))

        # Button grid card
        grid_card = ttk.Frame(parent, style="Card.TFrame", padding=28)
        grid_card.pack(padx=60, pady=0, fill="x")

        btn_cfg = [
            # (label, icon, color_style, description, method)
            ("Start VM",    "▶",  "Green.TButton",
             "Power on the virtual machine.",     self._vm_start),
            ("Restart VM",  "🔄", "Accent.TButton",
             "Send a reset signal to the VM.",    self._vm_restart),
            ("Revert VM",   "⏮",  "Accent.TButton",
             "Power off, restore snapshot, boot.", self._vm_revert),
            ("Shutdown VM", "⏹",  "Red.TButton",
             "Force power off the virtual machine.", self._vm_shutdown),
        ]

        for i, (label, icon, style, desc, cmd) in enumerate(btn_cfg):
            row = i // 2
            col = i % 2

            cell = tk.Frame(grid_card, bg=self.BG2, padx=16, pady=16)
            cell.grid(row=row, column=col, padx=12, pady=12, sticky="nsew")
            grid_card.columnconfigure(col, weight=1)

            # Icon + label
            btn_inner = tk.Frame(cell, bg=self.BG2)
            btn_inner.pack()
            tk.Label(btn_inner, text=icon,
                     bg=self.BG2, fg=self.TEXT,
                     font=("Segoe UI", 22)).pack()
            ttk.Button(btn_inner, text=label, style=style,
                       command=cmd, width=18).pack(pady=(6, 0))
            tk.Label(cell, text=desc,
                     bg=self.BG2, fg=self.TEXTDIM,
                     font=("Segoe UI", 8),
                     wraplength=180, justify="center").pack(pady=(6, 0))

        # VM status indicator
        status_frame = tk.Frame(parent, bg=self.BG)
        status_frame.pack(pady=28)
        tk.Label(status_frame, text="Last action:",
                 bg=self.BG, fg=self.TEXTDIM,
                 font=("Segoe UI", 9)).pack(side="left", padx=(0, 8))
        self._vm_action_label = tk.Label(status_frame, text="—",
                                          bg=self.BG, fg=self.TEXT,
                                          font=("Segoe UI", 9, "bold"))
        self._vm_action_label.pack(side="left")

    # ──────────────── TAB 4 : OS VOTING ────────────────
    def _build_os_voting_tab(self, parent):
        parent.configure(style="TFrame")

        header = ttk.Frame(parent, style="TFrame")
        header.pack(fill="x", padx=16, pady=(16, 4))
        tk.Label(header, text="Chat OS Voting System",
                 bg=self.BG, fg=self.ACCENT,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w")
        tk.Label(header,
                 text=(f"Viewers vote with chat commands (e.g. !win7, !win8). "
                       f"{OS_VOTE_REQUIRED} votes switch the running OS. "
                       f"The channel owner bypasses voting and switches instantly. "
                       f"Up to {OS_VOTE_SLOTS} OS entries can be configured."),
                 bg=self.BG, fg=self.TEXTDIM, font=("Segoe UI", 9),
                 wraplength=760, justify="left").pack(anchor="w", pady=(2, 0))

        # Enable toggle
        toggle_card = ttk.Frame(parent, style="Card.TFrame", padding=14)
        toggle_card.pack(fill="x", padx=16, pady=(10, 8))
        self._os_voting_var = tk.BooleanVar(value=OS_VOTING_ENABLED)
        chk = tk.Checkbutton(toggle_card,
            text="Enable OS Voting System (uncheck = single fixed OS, classic mode)",
            variable=self._os_voting_var, bg=self.BG2, fg=self.TEXT,
            selectcolor=self.BG3, activebackground=self.BG2,
            activeforeground=self.TEXT, font=("Segoe UI", 10, "bold"),
            command=self._on_os_voting_toggle)
        chk.pack(anchor="w")

        # Scrollable rows card
        self._os_rows_card = ttk.Frame(parent, style="Card.TFrame", padding=14)
        self._os_rows_card.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        # Sticky column header (outside the scroll area so it doesn't scroll away)
        col_hdr = tk.Frame(self._os_rows_card, bg=self.BG2)
        col_hdr.pack(fill="x", pady=(0, 4))
        tk.Label(col_hdr, text="#",            bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 9, "bold"), width=2).grid(row=0, column=0, padx=4)
        tk.Label(col_hdr, text="Display Name", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 9, "bold"), width=18, anchor="w").grid(row=0, column=1, padx=4)
        tk.Label(col_hdr, text="Chat Trigger", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 9, "bold"), width=14, anchor="w").grid(row=0, column=2, padx=4)
        tk.Label(col_hdr, text="VirtualBox VM", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 9, "bold"), width=24, anchor="w").grid(row=0, column=3, padx=4)

        # Canvas + scrollbar for the rows
        scroll_container = tk.Frame(self._os_rows_card, bg=self.BG2)
        scroll_container.pack(fill="both", expand=True)

        canvas = tk.Canvas(scroll_container, bg=self.BG2, highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # Inner frame that holds all the rows
        inner = tk.Frame(canvas, bg=self.BG2)
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_configure(event):
            canvas.itemconfig(inner_id, width=event.width)
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.bind("<MouseWheel>", _on_mousewheel)
        inner.bind("<MouseWheel>", _on_mousewheel)

        self._os_name_vars    = []
        self._os_trigger_vars = []
        self._os_vm_vars      = []
        self._os_vm_combos    = []

        existing = OS_LIST + [{}] * (OS_VOTE_SLOTS - len(OS_LIST))
        for i in range(OS_VOTE_SLOTS):
            entry = existing[i] if i < len(existing) else {}
            row = tk.Frame(inner, bg=self.BG2)
            row.pack(fill="x", pady=3)
            row.bind("<MouseWheel>", _on_mousewheel)

            tk.Label(row, text=str(i + 1), bg=self.BG2, fg=self.TEXTDIM,
                     font=("Segoe UI", 9), width=2).grid(row=0, column=0, padx=4)

            name_var = tk.StringVar(value=entry.get("name", ""))
            ttk.Entry(row, textvariable=name_var, width=18,
                      font=("Segoe UI", 10)).grid(row=0, column=1, padx=4, ipady=3)
            self._os_name_vars.append(name_var)

            trig_var = tk.StringVar(value=entry.get("trigger", ""))
            ttk.Entry(row, textvariable=trig_var, width=14,
                      font=("Segoe UI Mono", 10)).grid(row=0, column=2, padx=4, ipady=3)
            self._os_trigger_vars.append(trig_var)
            tk.Label(row, text="(no ! needed)", bg=self.BG2, fg=self.TEXTDIM,
                     font=("Segoe UI", 7)).grid(row=1, column=2, sticky="w", padx=4)

            vm_var = tk.StringVar(value=entry.get("vm", ""))
            vm_combo = ttk.Combobox(row, textvariable=vm_var, width=24,
                                     state="readonly", font=("Segoe UI", 9))
            vm_combo.grid(row=0, column=3, padx=4, ipady=3)
            vm_combo.bind("<MouseWheel>", _on_mousewheel)
            self._os_vm_vars.append(vm_var)
            self._os_vm_combos.append(vm_combo)

        btn_row = tk.Frame(parent, bg=self.BG)
        btn_row.pack(fill="x", padx=16, pady=(0, 14))
        ttk.Button(btn_row, text="🔄 Refresh VM List", style="Dim.TButton",
                   command=self._refresh_os_vm_lists).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="💾 Save OS Voting Config", style="Green.TButton",
                   command=self._save_os_voting_config).pack(side="left")

        self._refresh_os_vm_lists()
        self._set_os_rows_enabled(OS_VOTING_ENABLED)
        # Track unsaved changes (tab index 3)
        self._trace_dirty(3, self._os_voting_var,
                          *self._os_name_vars, *self._os_trigger_vars, *self._os_vm_vars)

    def _refresh_os_vm_lists(self):
        vms = get_vm_list()
        for combo in self._os_vm_combos:
            current = combo.get()
            combo['values'] = vms
            if current and current in vms:
                combo.set(current)
        self._log(f"[OSVoting] VM list refreshed ({len(vms)} found).")

    def _set_os_rows_enabled(self, enabled):
        state = "readonly" if enabled else "disabled"
        for combo in self._os_vm_combos:
            combo.configure(state=state)

    # ──────────────── TAB 5 : APPEARANCE ────────────────
    def _build_appearance_tab(self, parent):
        parent.configure(style="TFrame")

        COLOR_KEYS = [
            ("BG",      "Background (main)"),
            ("BG2",     "Background (cards)"),
            ("BG3",     "Background (inputs)"),
            ("ACCENT",  "Accent color"),
            ("ACCENT2", "Accent highlight"),
            ("TEXT",    "Text (primary)"),
            ("TEXTDIM", "Text (dim)"),
            ("CONSOLE", "Console background"),
            ("BORDER",  "Border color"),
        ]

        header = ttk.Frame(parent, style="TFrame")
        header.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(header, text="Appearance & Theme",
                 bg=self.BG, fg=self.ACCENT,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w")
        tk.Label(header,
                 text="Changes apply immediately. Restart is NOT required.",
                 bg=self.BG, fg=self.TEXTDIM,
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))

        # ── Preset themes ──
        preset_card = ttk.Frame(parent, style="Card.TFrame", padding=14)
        preset_card.pack(fill="x", padx=16, pady=(0, 8))
        tk.Label(preset_card, text="Theme Presets",
                 bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 8))

        preset_row = tk.Frame(preset_card, bg=self.BG2)
        preset_row.pack(fill="x")
        self._preset_var = tk.StringVar(value="Dark Purple (Default)")

        btn_frame = tk.Frame(preset_card, bg=self.BG2)
        btn_frame.pack(fill="x", pady=(8, 0))
        for name in THEMES:
            is_dark = "Light" not in name
            fg_col  = "#ddd" if is_dark else "#111"
            bg_col  = THEMES[name]["ACCENT"]
            b = tk.Button(btn_frame, text=name,
                          bg=bg_col, fg=fg_col,
                          font=("Segoe UI", 8, "bold"),
                          relief="flat", padx=8, pady=4,
                          cursor="hand2",
                          command=lambda n=name: self._apply_preset(n))
            b.pack(side="left", padx=(0, 6), pady=2)

        # ── Font size ──
        font_card = ttk.Frame(parent, style="Card.TFrame", padding=14)
        font_card.pack(fill="x", padx=16, pady=(0, 8))
        tk.Label(font_card, text="Font Size",
                 bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))
        font_row = tk.Frame(font_card, bg=self.BG2)
        font_row.pack(anchor="w")
        self._font_size_var = tk.IntVar(value=self.__class__._FONT_SIZE)
        tk.Scale(font_row, from_=8, to=14, orient="horizontal",
                 variable=self._font_size_var, length=200,
                 bg=self.BG2, fg=self.TEXT, troughcolor=self.BG3,
                 highlightthickness=0, activebackground=self.ACCENT,
                 command=lambda _: self._apply_font_size()).pack(side="left")
        self._font_size_label = tk.Label(font_row,
                 text=f"{self.__class__._FONT_SIZE}pt",
                 bg=self.BG2, fg=self.ACCENT,
                 font=("Segoe UI", 10, "bold"), width=4)
        self._font_size_label.pack(side="left", padx=(8, 0))

        # ── Custom color pickers ──
        colors_card = ttk.Frame(parent, style="Card.TFrame", padding=14)
        colors_card.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        tk.Label(colors_card, text="Custom Colors",
                 bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 8))

        self._color_vars    = {}
        self._color_swatches = {}

        grid = tk.Frame(colors_card, bg=self.BG2)
        grid.pack(fill="x")
        for i, (key, label) in enumerate(COLOR_KEYS):
            row = i // 3
            col = i %  3
            cell = tk.Frame(grid, bg=self.BG2, padx=6, pady=4)
            cell.grid(row=row, column=col, sticky="w", padx=4, pady=2)

            tk.Label(cell, text=label, bg=self.BG2, fg=self.TEXTDIM,
                     font=("Segoe UI", 8)).pack(anchor="w")

            swatch_row = tk.Frame(cell, bg=self.BG2)
            swatch_row.pack(anchor="w")

            current_val = getattr(self.__class__, key, "#000000")
            var = tk.StringVar(value=current_val)
            self._color_vars[key] = var

            swatch = tk.Label(swatch_row, bg=current_val, width=3, height=1,
                              relief="flat", cursor="hand2")
            swatch.pack(side="left", padx=(0, 4))
            self._color_swatches[key] = swatch
            swatch.bind("<Button-1>", lambda e, k=key: self._pick_color(k))

            entry = ttk.Entry(swatch_row, textvariable=var, width=9,
                              font=("Segoe UI Mono", 9))
            entry.pack(side="left")
            entry.bind("<Return>",    lambda e, k=key: self._apply_color_entry(k))
            entry.bind("<FocusOut>",  lambda e, k=key: self._apply_color_entry(k))

        # ── Buttons ──
        btn_row = tk.Frame(parent, bg=self.BG)
        btn_row.pack(fill="x", padx=16, pady=(0, 14))
        ttk.Button(btn_row, text="💾 Save Theme",   style="Green.TButton",
                   command=self._save_appearance).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="↩ Reset to Default", style="Dim.TButton",
                   command=self._reset_appearance).pack(side="left")

    def _apply_preset(self, name):
        colors = THEMES.get(name, {})
        for key, val in colors.items():
            setattr(self.__class__, key, val)
            if hasattr(self, '_color_vars') and key in self._color_vars:
                self._color_vars[key].set(val)
        self._full_ui_rebuild()
        self._log(f"[Appearance] Applied preset: {name}")

    def _pick_color(self, key):
        from tkinter import colorchooser
        current = getattr(self.__class__, key, "#000000")
        result  = colorchooser.askcolor(color=current, title=f"Pick color for {key}")
        if result and result[1]:
            setattr(self.__class__, key, result[1])
            self._full_ui_rebuild()

    def _apply_color_entry(self, key):
        val = self._color_vars[key].get().strip()
        if not (val.startswith("#") and len(val) in (4, 7)):
            return
        setattr(self.__class__, key, val)
        self._full_ui_rebuild()

    def _apply_font_size(self):
        fs = self._font_size_var.get()
        self.__class__._FONT_SIZE = fs
        self._full_ui_rebuild()

    def _find_notebook(self):
        """
        Recursively searches the root widget tree for the first ttk.Notebook.
        The Notebook is NOT a direct child of root (it lives inside nb_outer),
        so a simple winfo_children() scan on root would miss it.
        """
        def _search(widget):
            if isinstance(widget, ttk.Notebook):
                return widget
            for child in widget.winfo_children():
                result = _search(child)
                if result is not None:
                    return result
            return None
        return _search(self.root)

    def _full_ui_rebuild(self):
        """
        Destroys and rebuilds the entire UI so every widget picks up the
        new colors from class attributes. Restores the active tab afterwards.
        """
        # Disable the tab-change dirty guard during rebuild —
        # destroying the Notebook fires <<NotebookTabChanged>> which would
        # trigger the unsaved-changes messagebox on a half-destroyed UI.
        self._switching_tab = True

        # Remember which tab was open (by index).
        active_tab = 4   # default: stay on Appearance tab
        try:
            nb = self._find_notebook()
            if nb is not None:
                active_tab = nb.index(nb.select())
        except Exception:
            pass

        # Cancel any pending after() callbacks to prevent stale-widget errors
        # and duplicate timer chains after the UI is rebuilt.
        try:
            if self._stats_update_job is not None:
                self.root.after_cancel(self._stats_update_job)
                self._stats_update_job = None
        except Exception:
            pass
        try:
            if hasattr(self, '_ban_refresh_job') and self._ban_refresh_job is not None:
                self.root.after_cancel(self._ban_refresh_job)
                self._ban_refresh_job = None
        except Exception:
            pass

        # If the console redirector is active, stop it before destroying widgets.
        # We will re-point it to the new console widget after the rebuild.
        console_redir_was_active = False
        if self._console_redir is not None:
            self._console_redir.stop()
            console_redir_was_active = True

        # Destroy everything inside root
        for widget in self.root.winfo_children():
            widget.destroy()

        # Rebuild
        self._build_styles()
        self.root.configure(bg=self.BG)
        self._editing_cmd  = None
        self._step_items   = []
        self._unsaved_tabs = set()
        self._current_tab  = 0
        self._dirty_tabs   = set()   # clear dirty flags — widgets are fresh
        was_fun_tab_revealed = getattr(self, "_fun_tab_revealed", False)
        self._fun_tab_revealed = False   # tabs were just destroyed — allow re-adding it
        self._build_ui()
        if was_fun_tab_revealed:
            self._reveal_fun_tab(celebrate=False)

        # Restore tab — search recursively again after rebuild
        try:
            nb = self._find_notebook()
            if nb is not None:
                nb.select(active_tab)
        except Exception:
            pass

        # Re-attach the console redirector to the newly created console widget.
        # Without this, stdout would be lost (or pointing at the destroyed widget)
        # for the remainder of the bot session.
        if console_redir_was_active and hasattr(self, '_console'):
            self._console_redir = ConsoleRedirect(self._console)
            self._console_redir.start()

        self.root.update_idletasks()
        # Re-enable the dirty guard now that UI is fully rebuilt
        self._switching_tab = False
        # Reset previous-tab tracker so the first switch after rebuild
        # doesn't falsely trigger the unsaved-changes dialog
        self._prev_tab_index = active_tab

    def _rebuild_styles_and_refresh(self):
        self._full_ui_rebuild()

    def _save_appearance(self):
        colors = {key: getattr(self.__class__, key)
                  for key in ["BG","BG2","BG3","ACCENT","ACCENT2",
                               "TEXT","TEXTDIM","CONSOLE","BORDER"]}
        save_appearance_config(colors, self.__class__._FONT_SIZE)
        messagebox.showinfo("Saved",
            "Appearance settings saved.\nThey will be applied on next launch too.")

    def _reset_appearance(self):
        defaults = THEMES["Dark Purple (Default)"]
        for key, val in defaults.items():
            setattr(self.__class__, key, val)
        self.__class__._FONT_SIZE = 10
        self._full_ui_rebuild()
        self._log("[Appearance] Reset to default theme.")

    # ──────────────── TAB 6 : OBS ────────────────
    def _build_obs_tab(self, parent):
        parent.configure(style="TFrame")

        # ── Scrollable canvas wrapper ──
        canvas    = tk.Canvas(parent, bg=self.BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=self.BG)
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner_cfg(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_cfg(e):
            canvas.itemconfig(inner_id, width=e.width)
        def _on_wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        inner.bind("<Configure>",   _on_inner_cfg)
        canvas.bind("<Configure>",  _on_canvas_cfg)
        canvas.bind("<MouseWheel>", _on_wheel)
        inner.bind("<MouseWheel>",  _on_wheel)

        # ── Header ──
        header = tk.Frame(inner, bg=self.BG)
        header.pack(fill="x", padx=16, pady=(14, 4))
        tk.Label(header, text="OBS WebSocket Integration",
                 bg=self.BG, fg=self.ACCENT,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w")
        tk.Label(header,
                 text="Requires OBS 28+ with WebSocket server enabled (Tools → WebSocket Server Settings).\n"
                      "Install the Python library:  pip install obsws-python",
                 bg=self.BG, fg=self.TEXTDIM,
                 font=("Segoe UI", 9), justify="left").pack(anchor="w", pady=(2, 0))

        if not _OBS_LIB_OK:
            tk.Label(inner,
                     text="⚠  obsws-python is not installed.\nRun:  pip install obsws-python",
                     bg=self.BG, fg=self.RED,
                     font=("Segoe UI", 10, "bold")).pack(pady=(8, 0))

        # ── Enable toggle ──
        toggle_card = ttk.Frame(inner, style="Card.TFrame", padding=14)
        toggle_card.pack(fill="x", padx=16, pady=(10, 6))
        toggle_card.bind("<MouseWheel>", _on_wheel)
        self._obs_enabled_var = tk.BooleanVar(value=OBS_CONFIG.get("enabled", False))
        tk.Checkbutton(toggle_card,
            text="Enable OBS WebSocket Integration",
            variable=self._obs_enabled_var,
            bg=self.BG2, fg=self.TEXT,
            selectcolor=self.BG3,
            activebackground=self.BG2, activeforeground=self.TEXT,
            font=("Segoe UI", 10, "bold")).pack(anchor="w")

        # ── Connection settings ──
        conn_card = ttk.Frame(inner, style="Card.TFrame", padding=14)
        conn_card.pack(fill="x", padx=16, pady=(0, 6))
        conn_card.bind("<MouseWheel>", _on_wheel)
        tk.Label(conn_card, text="Connection",
                 bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=4,
                                                      sticky="w", pady=(0, 8))
        tk.Label(conn_card, text="Host", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", padx=(0, 6))
        self._obs_host_var = tk.StringVar(value=OBS_CONFIG.get("host", "localhost"))
        ttk.Entry(conn_card, textvariable=self._obs_host_var,
                  width=18, font=("Segoe UI", 10)).grid(row=1, column=1, padx=(0, 16), ipady=3)
        tk.Label(conn_card, text="Port", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 9)).grid(row=1, column=2, sticky="w", padx=(0, 6))
        self._obs_port_var = tk.StringVar(value=str(OBS_CONFIG.get("port", 4455)))
        ttk.Entry(conn_card, textvariable=self._obs_port_var,
                  width=7, font=("Segoe UI", 10)).grid(row=1, column=3, padx=(0, 16), ipady=3)
        tk.Label(conn_card, text="Password", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 9)).grid(row=2, column=0, sticky="w", padx=(0, 6), pady=(8, 0))
        self._obs_pass_var = tk.StringVar(value=OBS_CONFIG.get("password", ""))
        ttk.Entry(conn_card, textvariable=self._obs_pass_var, show="●",
                  width=28, font=("Segoe UI", 10)).grid(row=2, column=1, columnspan=3,
                                                         pady=(8, 0), ipady=3)
        conn_btn_row = tk.Frame(conn_card, bg=self.BG2)
        conn_btn_row.grid(row=3, column=0, columnspan=4, sticky="w", pady=(10, 0))
        conn_btn_row.bind("<MouseWheel>", _on_wheel)
        ttk.Button(conn_btn_row, text="🔗 Connect", style="Green.TButton",
                   command=self._obs_connect).pack(side="left", padx=(0, 8))
        ttk.Button(conn_btn_row, text="✖ Disconnect", style="Red.TButton",
                   command=self._obs_disconnect).pack(side="left", padx=(0, 16))
        self._obs_status_label = tk.Label(conn_btn_row,
                 text="● Disconnected", bg=self.BG2, fg=self.RED,
                 font=("Segoe UI", 9, "bold"))
        self._obs_status_label.pack(side="left", padx=(4, 0))

        # ── Scene Triggers (dynamic) ──
        trigger_card = ttk.Frame(inner, style="Card.TFrame", padding=14)
        trigger_card.pack(fill="x", padx=16, pady=(0, 6))
        trigger_card.bind("<MouseWheel>", _on_wheel)

        trig_hdr_row = tk.Frame(trigger_card, bg=self.BG2)
        trig_hdr_row.pack(fill="x", pady=(0, 6))
        trig_hdr_row.bind("<MouseWheel>", _on_wheel)
        tk.Label(trig_hdr_row, text="Scene Triggers",
                 bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        ttk.Button(trig_hdr_row, text="＋ Add Trigger", style="Green.TButton",
                   command=lambda: self._add_obs_trigger_row()).pack(side="right")

        tk.Label(trigger_card,
                 text="Map any event key to an OBS scene.  "
                      "Event key examples:  bot_start  bot_stop  restart  revert_start  "
                      "revert_done  os_switch  ban  scheduler  — or any custom key you call via obs_trigger().",
                 bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 8), justify="left", wraplength=580).pack(
                 anchor="w", pady=(0, 8))

        col_hdr = tk.Frame(trigger_card, bg=self.BG2)
        col_hdr.pack(fill="x", pady=(0, 2))
        col_hdr.bind("<MouseWheel>", _on_wheel)
        tk.Label(col_hdr, text="Event Key (select or type)",   bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 8, "bold"), width=22, anchor="w").pack(side="left", padx=(0, 8))
        tk.Label(col_hdr, text="OBS Scene Name", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 8, "bold"), width=28, anchor="w").pack(side="left")

        self._obs_trigger_rows       = []
        self._obs_trigger_rows_frame = tk.Frame(trigger_card, bg=self.BG2)
        self._obs_trigger_rows_frame.pack(fill="x")
        self._obs_trigger_rows_frame.bind("<MouseWheel>", _on_wheel)
        self._obs_wheel_fn_trigger = _on_wheel

        # Pre-fill from saved config
        saved_triggers = OBS_CONFIG.get("triggers", {})
        if saved_triggers:
            for ev_key, scene_name in saved_triggers.items():
                self._add_obs_trigger_row(ev_key, scene_name)
        else:
            # Populate sensible defaults on first use
            for ev_key in ("bot_start", "bot_stop", "restart",
                           "revert_start", "revert_done", "os_switch"):
                self._add_obs_trigger_row(ev_key, "")

        # ── Per-OS scenes ──
        os_scene_card = ttk.Frame(inner, style="Card.TFrame", padding=14)
        os_scene_card.pack(fill="x", padx=16, pady=(0, 6))
        os_scene_card.bind("<MouseWheel>", _on_wheel)
        tk.Label(os_scene_card, text="Per-OS Scene Switching",
                 bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 4))
        tk.Label(os_scene_card,
                 text="When OS voting switches to a specific OS, OBS switches to that OS's scene.\n"
                      "Chat Trigger must match the trigger set in the OS Voting tab (e.g. win7, win10).",
                 bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 8), justify="left").pack(anchor="w", pady=(0, 8))

        hdr = tk.Frame(os_scene_card, bg=self.BG2)
        hdr.pack(fill="x", pady=(0, 4))
        hdr.bind("<MouseWheel>", _on_wheel)
        tk.Label(hdr, text="OS Name",      bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 8, "bold"), width=18, anchor="w").pack(side="left", padx=(0, 8))
        tk.Label(hdr, text="Chat Trigger", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 8, "bold"), width=14, anchor="w").pack(side="left", padx=(0, 8))
        tk.Label(hdr, text="OBS Scene Name", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 8, "bold"), width=24, anchor="w").pack(side="left")

        self._obs_os_rows = []
        self._obs_os_rows_frame = tk.Frame(os_scene_card, bg=self.BG2)
        self._obs_os_rows_frame.pack(fill="x")
        self._obs_os_rows_frame.bind("<MouseWheel>", _on_wheel)
        self._obs_wheel_fn = _on_wheel   # store for _add_obs_os_row

        saved_os_scenes = OBS_CONFIG.get("os_scenes", {})
        prefill = []
        for entry in OS_LIST:
            t = (entry.get("trigger") or "").strip().lower().lstrip("!")
            n = entry.get("name", "")
            if t:
                prefill.append((n, t, saved_os_scenes.get(t, "")))
        for trig, scene in saved_os_scenes.items():
            if not any(p[1] == trig for p in prefill):
                prefill.append(("", trig, scene))
        while len(prefill) < 5:
            prefill.append(("", "", ""))
        for name, trig, scene in prefill:
            self._add_obs_os_row(name, trig, scene)

        ttk.Button(os_scene_card, text="+ Add Row", style="Dim.TButton",
                   command=lambda: self._add_obs_os_row()).pack(anchor="w", pady=(8, 0))

        # ── Save ──
        btn_row = tk.Frame(inner, bg=self.BG)
        btn_row.pack(fill="x", padx=16, pady=(0, 20))
        btn_row.bind("<MouseWheel>", _on_wheel)
        ttk.Button(btn_row, text="💾 Save OBS Settings", style="Green.TButton",
                   command=self._obs_save).pack(side="left")

        # Track unsaved changes (tab index 5)
        self._trace_dirty(5, self._obs_enabled_var, self._obs_host_var,
                          self._obs_port_var, self._obs_pass_var)

    def _add_obs_trigger_row(self, event_key="", scene=""):
        KNOWN_EVENT_KEYS = [
            "bot_start",
            "bot_stop",
            "restart",
            "revert_start",
            "revert_done",
            "os_switch",
            "ban",
            "scheduler",
        ]
        row = tk.Frame(self._obs_trigger_rows_frame, bg=self.BG2)
        row.pack(fill="x", pady=2)
        if hasattr(self, '_obs_wheel_fn_trigger'):
            row.bind("<MouseWheel>", self._obs_wheel_fn_trigger)
        key_var   = tk.StringVar(value=event_key)
        scene_var = tk.StringVar(value=scene)
        key_cb = ttk.Combobox(row, textvariable=key_var,
                              values=KNOWN_EVENT_KEYS,
                              width=20, font=("Segoe UI Mono", 9))
        key_cb.pack(side="left", padx=(0, 8), ipady=2)
        key_cb.bind("<MouseWheel>", lambda e: "break")  # prevent scroll hijack
        ttk.Entry(row, textvariable=scene_var, width=28,
                  font=("Segoe UI", 9)).pack(side="left", ipady=2)
        entry_pair = (key_var, scene_var)
        ttk.Button(row, text="✕", style="Dim.TButton", width=2,
                   command=lambda r=row, p=entry_pair: (
                       r.destroy(),
                       self._obs_trigger_rows.remove(p)
                       if p in self._obs_trigger_rows else None
                   )).pack(side="left", padx=(6, 0))
        self._obs_trigger_rows.append(entry_pair)

    def _add_obs_os_row(self, name="", trigger="", scene=""):
        row = tk.Frame(self._obs_os_rows_frame, bg=self.BG2)
        row.pack(fill="x", pady=2)
        if hasattr(self, '_obs_wheel_fn'):
            row.bind("<MouseWheel>", self._obs_wheel_fn)
        name_var  = tk.StringVar(value=name)
        trig_var  = tk.StringVar(value=trigger)
        scene_var = tk.StringVar(value=scene)
        ttk.Entry(row, textvariable=name_var,  width=18,
                  font=("Segoe UI", 9)).pack(side="left", padx=(0, 8), ipady=2)
        ttk.Entry(row, textvariable=trig_var,  width=14,
                  font=("Segoe UI Mono", 9)).pack(side="left", padx=(0, 8), ipady=2)
        ttk.Entry(row, textvariable=scene_var, width=24,
                  font=("Segoe UI", 9)).pack(side="left", ipady=2)
        ttk.Button(row, text="✕", style="Dim.TButton", width=2,
                   command=lambda r=row, t=(name_var, trig_var, scene_var): (
                       r.destroy(),
                       self._obs_os_rows.remove(t) if t in self._obs_os_rows else None
                   )).pack(side="left", padx=(6, 0))
        self._obs_os_rows.append((name_var, trig_var, scene_var))

    def _obs_connect(self):
        OBS_CONFIG["host"]     = self._obs_host_var.get().strip()
        OBS_CONFIG["port"]     = int(self._obs_port_var.get().strip() or 4455)
        OBS_CONFIG["password"] = self._obs_pass_var.get()
        ok = obs_connect()
        if ok:
            self._obs_status_label.configure(text="● Connected", fg=self.GREEN)
            notify("OBS Connected", f"Connected to OBS at {OBS_CONFIG['host']}:{OBS_CONFIG['port']}")
        else:
            self._obs_status_label.configure(text="● Connection Failed", fg=self.RED)
            messagebox.showerror("OBS Connection Failed",
                "Could not connect to OBS.\n\n"
                "Make sure:\n"
                "• OBS is running\n"
                "• WebSocket server is enabled (Tools → WebSocket Server Settings)\n"
                "• Host, port and password are correct")

    def _obs_disconnect(self):
        obs_disconnect()
        if hasattr(self, '_obs_status_label'):
            self._obs_status_label.configure(text="● Disconnected", fg=self.RED)

    def _obs_save(self):
        OBS_CONFIG["enabled"]  = self._obs_enabled_var.get()
        OBS_CONFIG["host"]     = self._obs_host_var.get().strip()
        OBS_CONFIG["port"]     = int(self._obs_port_var.get().strip() or 4455)
        OBS_CONFIG["password"] = self._obs_pass_var.get()
        # Save dynamic scene triggers
        triggers = {}
        for key_var, scene_var in self._obs_trigger_rows:
            key   = key_var.get().strip()
            scene = scene_var.get().strip()
            if key and scene:
                triggers[key] = scene
        OBS_CONFIG["triggers"] = triggers
        # Save per-OS scenes
        os_scenes = {}
        for name_var, trig_var, scene_var in self._obs_os_rows:
            trig  = trig_var.get().strip().lower().lstrip("!")
            scene = scene_var.get().strip()
            if trig and scene:
                os_scenes[trig] = scene
        OBS_CONFIG["os_scenes"] = os_scenes
        save_obs_config()
        self._clear_dirty(5)
        messagebox.showinfo("Saved", "OBS settings saved.")

    def _on_auto_start_toggle(self):
        global AUTO_START_ENABLED
        AUTO_START_ENABLED = self._auto_start_var.get()
        save_auto_start_config()
        self._log(f"[AutoStart] Watchdog {'enabled' if AUTO_START_ENABLED else 'disabled'} by user.")

    def _show_blocked_commands_list(self):
        """
        Shows the Danger Filter's full pattern list as checkboxes — one
        per text pattern, one per standalone key, plus one for the
        base64-blob heuristic. Checked = still blocked (default state).
        Unchecking a box and clicking Save adds it to
        _REALPC_UNBLOCKED_PATTERNS / _REALPC_UNBLOCKED_KEYS, which
        _realpc_scan_text_for_danger() skips from then on — for both
        Real PC Control and the VM, since they share the same lists.
        Changes apply immediately (no restart needed) and persist to
        realpc_unblocked_patterns.json.

        Includes a search box and category filter buttons so the ~180-
        entry list is actually navigable instead of one long wall of
        checkboxes.
        """
        win = tk.Toplevel(self.root)
        win.title("🛡 Danger Filter — Blocked Commands")
        win.configure(bg=self.BG)
        win.geometry("640x700")
        win.transient(self.root)

        tk.Label(win, text="🛡 Danger Filter — Blocked Patterns",
                 bg=self.BG, fg=self.TEXT, font=("Segoe UI", 12, "bold")
                 ).pack(anchor="w", padx=14, pady=(14, 2))
        tk.Label(win,
                 text="Checked = blocked (default). Uncheck anything you want to "
                      "allow through, then click Save. Applies to both Real PC "
                      "Control and the VM immediately — no restart needed. "
                      "Your checkbox choices are kept even while searching/filtering.",
                 bg=self.BG, fg=self.TEXTDIM, font=("Segoe UI", 9),
                 wraplength=600, justify="left").pack(anchor="w", padx=14, pady=(0, 8))

        # ── Bottom-anchored controls, packed BEFORE the scrollable list so
        # they always stay visible regardless of how long the list is. ──
        btn_row = tk.Frame(win, bg=self.BG)
        btn_row.pack(side="bottom", fill="x", padx=14, pady=(6, 14))

        status_lbl = tk.Label(win, text="", bg=self.BG, fg=self.GREEN,
                               font=("Segoe UI", 9))
        status_lbl.pack(side="bottom", pady=(0, 4))

        # Vars persist across re-renders (search/category changes just
        # change which rows are drawn, never recreate the underlying
        # BooleanVars) — so toggling a box, then searching for something
        # else, then coming back never loses your change.
        pattern_vars = {}   # pattern -> BooleanVar (True = blocked)
        key_vars     = {}   # key -> BooleanVar
        base64_var   = tk.BooleanVar(value=_REALPC_BASE64_RULE_ENABLED)

        _REALPC_DANGEROUS_KEYS_DESC = {
            "delete": "Sends the Delete key — can remove selected files/text",
            "del":    "Sends the Delete key — can remove selected files/text",
            "printscreen": "Takes a screenshot to the clipboard — usually harmless, blocked as a precaution",
        }
        BASE64_CATEGORY = "Base64 Detection Rule"
        KEYS_CATEGORY   = "Standalone Keys"

        # Build the master row list ONCE: (category, label, desc, var)
        all_rows = []
        for p, desc, cat in _REALPC_DANGEROUS_TEXT_PATTERNS_WITH_DESC:
            v = tk.BooleanVar(value=(p not in _REALPC_UNBLOCKED_PATTERNS))
            pattern_vars[p] = v
            all_rows.append((cat, p, desc, v))
        for k in sorted(_REALPC_DANGEROUS_KEYS):
            v = tk.BooleanVar(value=(k not in _REALPC_UNBLOCKED_KEYS))
            key_vars[k] = v
            all_rows.append((KEYS_CATEGORY, k, _REALPC_DANGEROUS_KEYS_DESC.get(k), v))
        all_rows.append((BASE64_CATEGORY, "long base64 payload",
            f"Blocks any unbroken run of {_REALPC_BASE64_BLOB_MIN_LEN}+ base64-alphabet "
            f"characters that statistically looks like encoded binary data — e.g. an "
            f"image or file smuggled in as text and decoded straight to disk.",
            base64_var))

        categories = ["All"] + sorted({row[0] for row in all_rows})
        active_category = tk.StringVar(value="All")
        search_var = tk.StringVar(value="")

        def _save_changes():
            global _REALPC_UNBLOCKED_PATTERNS, _REALPC_UNBLOCKED_KEYS, _REALPC_BASE64_RULE_ENABLED
            _REALPC_UNBLOCKED_PATTERNS = {p for p, v in pattern_vars.items() if not v.get()}
            _REALPC_UNBLOCKED_KEYS     = {k for k, v in key_vars.items() if not v.get()}
            _REALPC_BASE64_RULE_ENABLED = base64_var.get()
            save_realpc_unblocked_patterns()
            n_unblocked = len(_REALPC_UNBLOCKED_PATTERNS) + len(_REALPC_UNBLOCKED_KEYS)
            status_lbl.configure(
                text=f"✅ Saved — {n_unblocked} item(s) unblocked." if n_unblocked
                     else "✅ Saved — everything is blocked (default).")

        def _select_all(state: bool):
            # Only affects what's currently VISIBLE (respects search/category
            # filter) — "Unblock All" while filtered to one category only
            # unblocks that category, not the entire list. Use category
            # "All" with an empty search to affect everything.
            for cat, label, desc, var in all_rows:
                if _row_matches_filter(cat, label, desc):
                    var.set(state)
            _render_rows()

        ttk.Button(btn_row, text="💾 Save Changes", style="Green.TButton",
                   command=_save_changes).pack(side="left")
        ttk.Button(btn_row, text="Block Shown (reset)", style="Dim.TButton",
                   command=lambda: _select_all(True)).pack(side="left", padx=(8, 0))
        ttk.Button(btn_row, text="Unblock Shown", style="Dim.TButton",
                   command=lambda: _select_all(False)).pack(side="left", padx=(8, 0))
        ttk.Button(btn_row, text="Close", style="Dim.TButton",
                   command=win.destroy).pack(side="right")

        # ── Search bar ──
        search_row = tk.Frame(win, bg=self.BG)
        search_row.pack(fill="x", padx=14, pady=(0, 6))
        tk.Label(search_row, text="🔎", bg=self.BG, fg=self.TEXTDIM,
                 font=("Segoe UI", 10)).pack(side="left")
        search_entry = ttk.Entry(search_row, textvariable=search_var, font=("Segoe UI", 9))
        search_entry.pack(side="left", fill="x", expand=True, padx=(4, 0), ipady=3)

        # ── Category filter buttons — single-row horizontal scroll strip ──
        # (Auto-wrapping to multiple rows was tried and was unreliable —
        # Tkinter's geometry timing made the wrap width calculation
        # inconsistent. A fixed-height scrollable strip with explicit
        # ◀/▶ buttons is simple and always works regardless of window
        # size or how many categories exist.)
        cat_outer = tk.Frame(win, bg=self.BG)
        cat_outer.pack(fill="x", padx=14, pady=(0, 8))

        cat_canvas = tk.Canvas(cat_outer, bg=self.BG, highlightthickness=0, height=34)
        cat_inner = tk.Frame(cat_canvas, bg=self.BG)
        cat_canvas.create_window((0, 0), window=cat_inner, anchor="nw")
        cat_inner.bind(
            "<Configure>",
            lambda e: cat_canvas.configure(scrollregion=cat_canvas.bbox("all")))

        def _scroll_categories(direction):
            cat_canvas.xview_scroll(direction * 3, "units")

        left_btn = ttk.Button(cat_outer, text="◀", width=3, style="Dim.TButton",
                               command=lambda: _scroll_categories(-1))
        right_btn = ttk.Button(cat_outer, text="▶", width=3, style="Dim.TButton",
                                command=lambda: _scroll_categories(1))

        left_btn.pack(side="left", padx=(0, 4))
        cat_canvas.pack(side="left", fill="x", expand=True)
        right_btn.pack(side="left", padx=(4, 0))

        # Mouse wheel over the strip scrolls it sideways too, not just the arrows
        def _on_cat_mousewheel(event):
            cat_canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")
        cat_canvas.bind("<Enter>", lambda e: cat_canvas.bind_all("<Shift-MouseWheel>", _on_cat_mousewheel))
        cat_canvas.bind("<Leave>", lambda e: cat_canvas.unbind_all("<Shift-MouseWheel>"))

        cat_buttons = {}

        def _set_category(cat):
            active_category.set(cat)
            for c, btn in cat_buttons.items():
                btn.configure(style="Accent.TButton" if c == cat else "Dim.TButton")
            _render_rows()

        for cat in categories:
            b = ttk.Button(cat_inner, text=cat, style="Dim.TButton",
                            command=lambda c=cat: _set_category(c))
            b.pack(side="left", padx=(0, 4), pady=2)
            cat_buttons[cat] = b
        cat_buttons["All"].configure(style="Accent.TButton")

        # ── Scrollable checkbox list ──
        list_outer = tk.Frame(win, bg=self.BG2, highlightthickness=0)
        list_outer.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        list_canvas = tk.Canvas(list_outer, bg=self.BG2, highlightthickness=0)
        list_scrollbar = tk.Scrollbar(list_outer, orient="vertical",
                                       command=list_canvas.yview)
        list_frame = tk.Frame(list_canvas, bg=self.BG2)

        list_frame.bind(
            "<Configure>",
            lambda e: list_canvas.configure(scrollregion=list_canvas.bbox("all")))
        list_canvas.create_window((0, 0), window=list_frame, anchor="nw", width=600)
        list_canvas.configure(yscrollcommand=list_scrollbar.set)
        list_canvas.pack(side="left", fill="both", expand=True)
        list_scrollbar.pack(side="right", fill="y")

        def _on_mousewheel(event):
            list_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        list_canvas.bind("<Enter>", lambda e: list_canvas.bind_all("<MouseWheel>", _on_mousewheel))
        list_canvas.bind("<Leave>", lambda e: list_canvas.unbind_all("<MouseWheel>"))

        def _section_header(text):
            tk.Label(list_frame, text=text, bg=self.BG2, fg=self.ACCENT,
                     font=("Segoe UI", 9, "bold"), anchor="w"
                     ).pack(fill="x", padx=8, pady=(10, 2))

        def _checkbox_row(label, var, desc=None):
            row = tk.Frame(list_frame, bg=self.BG2)
            row.pack(fill="x", padx=16, pady=2)
            cb = tk.Checkbutton(
                row, text=label, variable=var,
                bg=self.BG2, fg=self.TEXT, selectcolor=self.BG3,
                activebackground=self.BG2, activeforeground=self.TEXT,
                font=("Segoe UI Mono", 9, "bold"), anchor="w", justify="left",
                wraplength=560)
            cb.pack(fill="x", anchor="w")
            if desc:
                tk.Label(row, text=desc, bg=self.BG2, fg=self.TEXTDIM,
                         font=("Segoe UI", 8), anchor="w", justify="left",
                         wraplength=550).pack(fill="x", padx=(24, 0))

        def _row_matches_filter(cat, label, desc):
            if active_category.get() != "All" and cat != active_category.get():
                return False
            q = search_var.get().strip().lower()
            if not q:
                return True
            return q in label.lower() or (desc and q in desc.lower())

        def _render_rows(*_args):
            for child in list_frame.winfo_children():
                child.destroy()

            shown = [row for row in all_rows if _row_matches_filter(*row[:3])]
            if not shown:
                tk.Label(list_frame, text="No patterns match your search.",
                         bg=self.BG2, fg=self.TEXTDIM, font=("Segoe UI", 9)
                         ).pack(padx=16, pady=20)
                list_canvas.yview_moveto(0)
                return

            last_cat = None
            for cat, label, desc, var in shown:
                if cat != last_cat:
                    _section_header(f"{cat} ({sum(1 for r in shown if r[0] == cat)}):")
                    last_cat = cat
                _checkbox_row(label, var, desc)

            # Reset scroll position to the top — otherwise switching to a
            # new category (or typing a new search) while scrolled down
            # in the previous list leaves you looking at whatever
            # happened to be at that same scroll offset in the new list,
            # which usually means it looks like the new category "starts"
            # partway down or even empty.
            list_frame.update_idletasks()
            list_canvas.configure(scrollregion=list_canvas.bbox("all"))
            list_canvas.yview_moveto(0)

        search_var.trace_add("write", _render_rows)
        _render_rows()

    def _change_chat_backend(self):
        _show_chat_backend_dialog()   # blocks until the user picks something
        self._chat_backend_status_lbl.configure(text=f"Currently: {CHAT_BACKEND_PREFERENCE}")

    def _save_youtube_api_key(self):
        global YOUTUBE_API_KEY
        YOUTUBE_API_KEY = self._yt_api_key_var.get().strip()
        save_youtube_api_key_config()
        if YOUTUBE_API_KEY:
            messagebox.showinfo(
                "YouTube API Key",
                "Saved. The bot will now try the official YouTube Data API v3 "
                "backend first on its next (re)connect, falling back to the "
                "free backends if it fails.")
        else:
            messagebox.showinfo(
                "YouTube API Key",
                "Cleared. The bot will use the free (unofficial) chat backends only.")

    def _on_vm_danger_filter_toggle(self):
        """
        Called when the Main tab's Danger Filter checkbox is clicked.
        Turning it OFF requires two explicit hard warnings — same pattern
        as the Real PC Control danger filter. Turning it back ON never
        requires confirmation.
        """
        global VM_DANGER_FILTER_ENABLED

        if self._vm_danger_filter_var.get():
            # Re-enabled — no confirmation needed, just apply.
            VM_DANGER_FILTER_ENABLED = True
            save_vm_danger_filter_config()
            self._log("[VMDangerFilter] Enabled by user.")
            return

        # Trying to turn it OFF — hard-stop with 2 warnings.
        # Warning 1
        if not messagebox.askokcancel(
            "🛑  Disable Danger Filter — Warning 1 of 2",
            "You are about to DISABLE the Base64 / Dangerous Command Filter "
            "for the VM.\n\n"
            "This filter is what stops YouTube chat viewers from typing "
            "destructive commands (shutdown, format, del /f, registry edits, "
            "PowerShell download-and-run chains, etc.) into the VM — "
            "including ones spelled out across multiple small steps to "
            "dodge detection.\n\n"
            "It's ALSO what stops viewers from smuggling inappropriate "
            "images or other files into the VM as a base64 payload typed "
            "through chat and decoded straight to disk — which is exactly "
            "the kind of thing that gets streams reported and channels "
            "banned.\n\n"
            "Click OK to continue to the final warning, or Cancel to keep "
            "the filter enabled.",
            icon="warning",
        ):
            self._vm_danger_filter_var.set(True)
            return

        # Warning 2 — final "I accept full responsibility" confirmation
        if not messagebox.askokcancel(
            "🛑  Disable Danger Filter — Warning 2 of 2  (Final)",
            "FINAL CONFIRMATION:\n\n"
            "By clicking OK you confirm that:\n\n"
            "  • You are turning OFF protection against destructive "
            "commands AND against base64-smuggled inappropriate content "
            "being typed into the VM by chat.\n\n"
            "  • YOU take FULL and SOLE responsibility for any damage, "
            "content-policy strike, channel ban, or other consequence that "
            "results from this VM being controlled by YouTube chat with "
            "this protection disabled.\n\n"
            "  • The developer (Nexovative) is NOT responsible under any "
            "circumstances for the outcome of this decision.\n\n"
            "Click OK to permanently disable the filter, or Cancel to keep "
            "it enabled.",
            icon="warning",
        ):
            self._vm_danger_filter_var.set(True)
            return

        # Both warnings accepted — actually disable it.
        VM_DANGER_FILTER_ENABLED = False
        save_vm_danger_filter_config()
        self._log("[VMDangerFilter] ⚠ DISABLED by user after double confirmation.")
        _append_event("VM_DANGER_FILTER", "SYSTEM",
                       "VM danger/base64 filter disabled by operator after double confirmation")

    def _sync_main_vm_lock(self):
        """Lock the Main tab VM selector when OS Voting is enabled, since the
        bot then uses the OS Voting tab's list instead."""
        if OS_VOTING_ENABLED:
            self._vm_combo.configure(state="disabled")
            self._vm_select_note.configure(
                text="🗳 OS Voting is enabled — this selector is ignored. "
                     "The bot uses the VMs configured in the 'OS Voting' tab.")
        else:
            self._vm_combo.configure(state="readonly")
            self._vm_select_note.configure(
                text="Leave blank to run chat-only (no VM control) — YouTube chat works without a VM.")

    def _on_os_voting_toggle(self):
        self._set_os_rows_enabled(self._os_voting_var.get())

    def _save_os_voting_config(self):
        global OS_VOTING_ENABLED, OS_LIST
        enabled = self._os_voting_var.get()
        new_list = []
        for i in range(OS_VOTE_SLOTS):
            name = self._os_name_vars[i].get().strip()
            trig = self._os_trigger_vars[i].get().strip().lower().lstrip("!")
            vm   = self._os_vm_vars[i].get().strip()
            if name or trig or vm:
                new_list.append({"name": name, "trigger": trig, "vm": vm})

        if enabled:
            valid = [e for e in new_list if e["name"] and e["trigger"] and e["vm"]]
            if len(valid) < 2:
                messagebox.showerror("Invalid Configuration",
                    "OS Voting needs at least 2 fully filled rows "
                    "(Display Name + Chat Trigger + VM) to be enabled.")
                return
            triggers = [e["trigger"] for e in valid]
            if len(triggers) != len(set(triggers)):
                messagebox.showerror("Invalid Configuration",
                    "Chat triggers must be unique across all OS entries.")
                return

        OS_VOTING_ENABLED = enabled
        OS_LIST = new_list
        save_os_voting_config()
        self._clear_dirty(3)
        self._set_os_rows_enabled(enabled)
        self._sync_main_vm_lock()
        self._log(f"[OSVoting] Saved. Enabled={enabled}, entries={len(new_list)}")
        messagebox.showinfo("Saved", "OS Voting configuration saved.")

    def _vm_set_last(self, text, color=None):
        self._vm_action_label.configure(
            text=text,
            fg=color or self.TEXT
        )

    def _vm_start(self):
        if not VM_NAME:
            messagebox.showerror("No VM", "Start the bot first to select a VM.")
            return
        self._vm_set_last("Starting…", self.YELLOW)
        self._log("[VM] Start requested by admin.")
        def run():
            try:
                speak_text("Starting Virtual Machine...")
                update_status("Starting...")
                start_vm()
                self.root.after(0, lambda: self._vm_set_last("Started ✔", self.GREEN))
            except Exception as e:
                err_msg = str(e)
                self.root.after(0, lambda err_msg=err_msg: self._vm_set_last(f"Error: {err_msg}", self.RED))
                print(f"[VM] Start error: {err_msg}")
        threading.Thread(target=run, daemon=True).start()

    def _vm_restart(self):
        if not VM_NAME:
            messagebox.showerror("No VM", "Start the bot first to select a VM.")
            return
        if not messagebox.askyesno("Restart VM", f"Reset '{VM_NAME}' now?"):
            return
        self._vm_set_last("Restarting…", self.YELLOW)
        self._log("[VM] Restart requested by admin.")
        def run():
            try:
                speak_text("Restarting Virtual Machine...")
                update_status("Restarting...")
                subprocess.run([VBOXMANAGE_PATH, 'controlvm', VM_NAME, 'reset'], check=True)
                update_status("Running")
                play_success_sound()
                self.root.after(0, lambda: self._vm_set_last("Restarted ✔", self.GREEN))
            except Exception as e:
                err_msg = str(e)
                self.root.after(0, lambda err_msg=err_msg: self._vm_set_last(f"Error: {err_msg}", self.RED))
                print(f"[VM] Restart error: {err_msg}")
        threading.Thread(target=run, daemon=True).start()

    def _vm_revert(self):
        if not VM_NAME:
            messagebox.showerror("No VM", "Start the bot first to select a VM.")
            return
        if not messagebox.askyesno("Revert VM",
                f"Power off '{VM_NAME}', restore snapshot and reboot?\n"
                "This will discard all unsaved VM state."):
            return
        self._vm_set_last("Reverting…", self.YELLOW)
        self._log("[VM] Revert requested by admin.")
        def run():
            global revert_in_progress, revert_start_time
            revert_in_progress = True
            try:
                speak_text("Reverting Virtual Machine...")
                update_status("Reverting...")
                subprocess.run([VBOXMANAGE_PATH, 'controlvm', VM_NAME, 'poweroff'], check=True)
                time.sleep(3)
                subprocess.run([VBOXMANAGE_PATH, 'snapshot', VM_NAME, 'restorecurrent'], check=True)
                time.sleep(3)
                subprocess.run([VBOXMANAGE_PATH, 'startvm', VM_NAME], check=True)
                update_status("Running")
                play_success_sound()
                vote_revert.clear()
                update_votes_json("revert", 0, 2, 0)
                self.root.after(0, lambda: self._vm_set_last("Reverted ✔", self.GREEN))
            except Exception as e:
                update_status("Revert failed")
                err_msg = str(e)
                self.root.after(0, lambda err_msg=err_msg: self._vm_set_last(f"Error: {err_msg}", self.RED))
                print(f"[VM] Revert error: {err_msg}")
            finally:
                revert_start_time = None
                revert_in_progress = False
        threading.Thread(target=run, daemon=True).start()

    def _vm_shutdown(self):
        if not VM_NAME:
            messagebox.showerror("No VM", "Start the bot first to select a VM.")
            return
        if not messagebox.askyesno("Shutdown VM",
                f"Force power off '{VM_NAME}'?\nUnsaved VM state will be lost."):
            return
        self._vm_set_last("Shutting down…", self.YELLOW)
        self._log("[VM] Shutdown requested by admin.")
        def run():
            try:
                speak_text("Shutting down Virtual Machine...")
                update_status("Shutting down...")
                subprocess.run([VBOXMANAGE_PATH, 'controlvm', VM_NAME, 'poweroff'], check=True)
                update_status("Stopped")
                self.root.after(0, lambda: self._vm_set_last("Powered off ✔", self.TEXTDIM))
            except Exception as e:
                err_msg = str(e)
                self.root.after(0, lambda err_msg=err_msg: self._vm_set_last(f"Error: {err_msg}", self.RED))
                print(f"[VM] Shutdown error: {err_msg}")
        threading.Thread(target=run, daemon=True).start()

    # ──────────────── Helpers ────────────────
    @staticmethod
    def _font_exists(name):
        import tkinter.font as tkfont
        return name in tkfont.families()

    def _log(self, msg):
        self._console.configure(state='normal')
        ts = time.strftime("%H:%M:%S")
        self._console.insert('end', f"[{ts}] {msg}\n")
        self._console.see('end')
        self._console.configure(state='disabled')

    def _mark_dirty(self, tab_idx):
        """Mark a tab as having unsaved changes."""
        self._unsaved_tabs.add(tab_idx)

    def _clear_dirty(self, tab_idx):
        """Clear the unsaved-changes flag for a tab (called after successful save)."""
        self._unsaved_tabs.discard(tab_idx)

    def _trace_dirty(self, tab_idx, *vars_):
        """Attach write-traces to tkinter variables so any change marks the tab dirty."""
        def _cb(*_args, _idx=tab_idx):
            self._mark_dirty(_idx)
        for v in vars_:
            try:
                v.trace_add("write", _cb)
            except Exception:
                pass

    def _set_status(self, text, color):
        self._status_dot.configure(text=f"⬤  {text}", fg=color)

    # ──────────────── VM List ────────────────
    def _refresh_vm_list(self):
        vms = get_vm_list()
        self._vm_combo['values'] = vms
        if vms:
            self._vm_combo.current(0)
            self._log(f"VirtualBox: {len(vms)} VM(s) found.")
        else:
            self._log("⚠️ No VMs found (VirtualBox installed?)")

    # ──────────────── Bot Start / Stop ────────────────
    def _on_test_mode_toggle(self):
        global TEST_MODE_ENABLED, VM_NAME, current_os_vm
        enabled = self._test_mode_var.get()
        TEST_MODE_ENABLED = enabled

        if enabled:
            vm = self._vm_var.get().strip()
            if not vm and not (OS_VOTING_ENABLED and OS_LIST):
                messagebox.showerror("Missing VM",
                    "Please select a VirtualBox VM before enabling Test Mode.")
                self._test_mode_var.set(False)
                TEST_MODE_ENABLED = False
                return
            if self._bot_running:
                messagebox.showwarning("Bot Running",
                    "Stop the bot first before starting Test Mode.")
                self._test_mode_var.set(False)
                TEST_MODE_ENABLED = False
                return
            # Set VM target
            if OS_VOTING_ENABLED:
                valid = [e for e in OS_LIST if e.get("vm")]
                if valid:
                    VM_NAME = valid[0]["vm"]
                    current_os_vm = VM_NAME
            else:
                VM_NAME = vm
                current_os_vm = vm
            # Start background threads needed for VM control
            bot_stop_event.clear()
            threading.Thread(target=watchdog_restart,       daemon=True).start()
            threading.Thread(target=os_vote_timeout_checker, daemon=True).start()
            # Start the console input loop in a background thread
            threading.Thread(target=run_test_mode, daemon=True).start()
            self._set_status("Test Mode", self.YELLOW)
            self._log(f"[TestMode] Started. VM: {VM_NAME}. Type commands in the console.")
            notify("Test Mode Active", f"VM: {VM_NAME}\nType commands in the console window.")
        else:
            bot_stop_event.set()
            self._set_status("Stopped", self.RED)
            self._log("[TestMode] Stopped.")
            notify("Test Mode Stopped", "Test mode has been disabled.")

    def _start_bot(self):
        global VIDEO_ID, VM_NAME, current_os_vm
        yt  = self._yt_var.get().strip()
        vm  = self._vm_var.get().strip()
        if not yt:
            messagebox.showerror("Missing Input", "Please enter a YouTube Video ID.")
            return
        if self._bot_running:
            self._log("⚠️ Bot is already running!")
            return

        if OS_VOTING_ENABLED:
            valid_entries = [e for e in OS_LIST if e.get("name") and e.get("trigger") and e.get("vm")]
            if len(valid_entries) < 2:
                messagebox.showerror("OS Voting Misconfigured",
                    "OS Voting is enabled but fewer than 2 valid OS entries are configured.\n"
                    "Go to the OS Voting tab and fix the configuration, or disable voting.")
                return
            # Use the last active VM if it is still in the list, otherwise fall back to the first entry
            valid_vms = [e["vm"] for e in valid_entries]
            if current_os_vm and current_os_vm in valid_vms:
                start_vm_name = current_os_vm
                start_name = next(e["name"] for e in valid_entries if e["vm"] == current_os_vm)
                self._log(f"[OSVoting] Resuming with last active OS: '{start_name}'.")
            else:
                start_vm_name = valid_entries[0]["vm"]
                start_name    = valid_entries[0]["name"]
                self._log(f"[OSVoting] No saved OS found — starting with first entry: '{start_name}'.")
            VM_NAME = start_vm_name
            current_os_vm = start_vm_name
        else:
            # VM selection is optional now — the bot can connect to YouTube
            # chat and run chat-only commands without any VirtualBox VM.
            # VM-dependent commands (!type, !click, !restart, !revert, etc.)
            # will simply report "no VM selected" until one is chosen here
            # or from the Main tab dropdown.
            if not vm:
                self._log("ℹ️ No VM selected — starting in chat-only mode. "
                           "VM commands (!type, !click, !restart, etc.) will be unavailable "
                           "until a VM is selected.")
            VM_NAME = vm
            current_os_vm = vm or None

        VIDEO_ID = yt
        self._bot_running = True
        bot_stop_event.clear()
        self._set_status("Running", self.GREEN)

        # Redirect stdout → console
        self._console_redir = ConsoleRedirect(self._console)
        self._console_redir.start()

        vm_display = VM_NAME or "(none — chat-only mode)"
        self._log(f"Starting bot → YT: {VIDEO_ID}  |  VM: {vm_display}")
        notify("Bot Started", f"Listening on: {VIDEO_ID}\nVM: {vm_display}")
        obs_trigger("bot_start")
        _reset_session_stats()
        _append_event("BOT_START", "system", f"video_id={VIDEO_ID} vm={VM_NAME or 'none'}")
        if _gui_app is not None:
            try:
                _gui_app._append_chat_system(f"Bot started — listening on {VIDEO_ID}")
            except Exception:
                pass

        # Start scheduler background thread (one instance, idempotent)
        running_names = {t.name for t in threading.enumerate()}
        if "scheduler_loop" not in running_names:
            threading.Thread(target=scheduler_loop, daemon=True,
                             name="scheduler_loop").start()

        self._bot_instance = None
        self._bot_thread = threading.Thread(target=self._run_bot, daemon=True)
        self._bot_thread.start()

    def _run_bot(self):
        try:
            bot = YouTubeChatBot()
            self._bot_instance = bot
            # Launch secondary bots for extra stream IDs
            extra_ids = MULTI_STREAM_CONFIG.get("video_ids", [])
            for extra_vid in extra_ids:
                if extra_vid and extra_vid != VIDEO_ID:
                    def _run_extra(vid=extra_vid):
                        try:
                            extra_bot = YouTubeChatBotSecondary(vid)
                            _multi_stream_bots.append(extra_bot)
                            extra_bot.run()
                        except Exception as e:
                            print(f"[MultiStream] Error for {vid}: {e}")
                    threading.Thread(target=_run_extra, daemon=True).start()
                    print(f"[MultiStream] Started listener for extra stream: {extra_vid}")
            if bot.chat and bot.chat.is_alive():
                bot.run()
            else:
                print("[Bot] Chat connection failed at startup.")
        except Exception as e:
            print(f"[Bot] Fatal error: {e}")
            notify("Bot Crashed", f"Fatal error: {e}", timeout=8)
        finally:
            self._bot_instance = None
            self._bot_running = False
            _multi_stream_bots.clear()
            self.root.after(0, lambda: self._set_status("Stopped", self.RED))
            if _gui_app is not None:
                try: _gui_app._append_chat_system("Bot stopped.")
                except Exception: pass

    def _minimize_to_tray(self):
        if not _PYSTRAY_OK:
            messagebox.showinfo("Tray Unavailable",
                "pystray or Pillow is not installed.\nRun: pip install pystray pillow")
            return
        self.root.withdraw()
        notify("Running in Tray",
               "Bot is still running. Right-click the tray icon to restore or exit.")

    def _stop_bot(self):
        global TEST_MODE_ENABLED   # must be at the top of the function
        if not self._bot_running and not TEST_MODE_ENABLED:
            self._log("Bot is already stopped.")
            return
        self._log("Stopping bot... (may take a few seconds to finish current loop)")
        bot_stop_event.set()
        # Reset test mode checkbox and global if it was active.
        # set(False) only updates the BooleanVar; it does NOT call _on_test_mode_toggle,
        # so the global must be cleared here manually.
        if TEST_MODE_ENABLED:
            TEST_MODE_ENABLED = False
            self._test_mode_var.set(False)
        # Force the underlying chat connection closed immediately so the
        # blocking chat.get() call in run() doesn't keep us waiting.
        if self._bot_instance and self._bot_instance.chat:
            try:
                self._bot_instance.chat.terminate()
            except Exception as e:
                print(f"[Bot] Error terminating chat connection: {e}")
        self._bot_running = False
        if self._console_redir:
            self._console_redir.stop()
            self._console_redir = None
        self._set_status("Stopped", self.RED)
        self._log("Bot stopped by user.")
        notify("Bot Stopped", "The bot has been stopped.")
        obs_trigger("bot_stop")

    # ──────────────── Admin CMD ────────────────
    def _send_admin_cmd(self):
        cmd = self._admin_var.get().strip()
        if not cmd: return
        self._admin_var.set("")
        self._log(f"[AdminCMD] {cmd}")

        def run():
            c = cmd.lower()
            if c == '!startvm':
                speak_text("Starting Virtual Machine...")
                update_status("Starting...")
                start_vm()
            elif c == '!restart':
                speak_text("Restarting Virtual Machine...")
                update_status("Restarting...")
                try:
                    subprocess.run([VBOXMANAGE_PATH, 'controlvm', VM_NAME, 'reset'], check=True)
                    update_status("Running")
                    play_success_sound()
                except Exception as e:
                    update_status("Restart failed")
                    print(f"[Admin] Restart error: {e}")
            elif c.startswith('!speak '):
                speak_text(cmd[7:].strip())
            elif c == '!revert':
                global revert_in_progress, revert_start_time
                speak_text("Reverting Virtual Machine...")
                revert_in_progress = True
                update_status("Reverting...")
                try:
                    subprocess.run([VBOXMANAGE_PATH, 'controlvm', VM_NAME, 'poweroff'], check=True)
                    time.sleep(3)
                    subprocess.run([VBOXMANAGE_PATH, 'snapshot', VM_NAME, 'restorecurrent'], check=True)
                    time.sleep(3)
                    subprocess.run([VBOXMANAGE_PATH, 'startvm', VM_NAME], check=True)
                    update_status("Running")
                    play_success_sound()
                    vote_revert.clear()
                    update_votes_json("revert", 0, 2, 0)
                except Exception as e:
                    update_status("Revert failed")
                    print(f"[Admin] Revert error: {e}")
                finally:
                    revert_start_time = None
                    revert_in_progress = False
            elif c == '!clearvotes':
                vote_restart.clear(); vote_revert.clear(); ban_votes.clear()
                update_votes_json("restartvm", 0, 2, 0)
                update_votes_json("revert",    0, 2, 0)
                update_ban_vote_display(None, 0, 3)
                os_votes.clear()
                update_os_vote_status()
                speak_text("Votes cleared by admin!")
                print("[Admin] Votes cleared")
            else:
                print(f"[Admin] Unknown command: {cmd}")

        threading.Thread(target=run, daemon=True).start()

    # ──────────────── Command Builder ────────────────
    # ──────────────── TAB 7 : STATISTICS ────────────────
    def _build_statistics_tab(self, parent):
        parent.configure(style="TFrame")

        hdr = tk.Frame(parent, bg=self.BG)
        hdr.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(hdr, text="📊  Session Statistics",
                 bg=self.BG, fg=self.ACCENT,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w")
        tk.Label(hdr, text="Live counters — updated every second while the bot is running.",
                 bg=self.BG, fg=self.TEXTDIM,
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))

        # ── Top counter cards ──
        cards_frame = tk.Frame(parent, bg=self.BG)
        cards_frame.pack(fill="x", padx=16, pady=(4, 8))

        self._stat_labels = {}

        def _counter_card(parent_frame, key, title, color):
            card = tk.Frame(parent_frame, bg=self.BG2, padx=14, pady=10,
                            relief="flat", bd=0)
            card.pack(side="left", expand=True, fill="both", padx=(0, 8))
            tk.Label(card, text=title, bg=self.BG2, fg=self.TEXTDIM,
                     font=("Segoe UI", 8, "bold")).pack(anchor="w")
            lbl = tk.Label(card, text="0", bg=self.BG2, fg=color,
                           font=("Segoe UI", 22, "bold"))
            lbl.pack(anchor="w")
            self._stat_labels[key] = lbl

        _counter_card(cards_frame, "session_commands", "Commands (session)", self.GREEN)
        _counter_card(cards_frame, "total_commands",   "Commands (total)",   self.ACCENT2)
        _counter_card(cards_frame, "os_switches",      "OS Switches",        self.YELLOW)
        _counter_card(cards_frame, "restarts",         "Restarts",           self.RED)
        _counter_card(cards_frame, "reverts",          "Reverts",            "#f08060")

        # uptime card on its own row
        uptime_card = tk.Frame(parent, bg=self.BG2, padx=14, pady=8)
        uptime_card.pack(fill="x", padx=16, pady=(0, 10))
        tk.Label(uptime_card, text="Bot Uptime", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 8, "bold")).pack(side="left", padx=(0, 12))
        self._stat_labels["uptime"] = tk.Label(uptime_card, text="—",
                 bg=self.BG2, fg=self.TEXT, font=("Segoe UI", 11, "bold"))
        self._stat_labels["uptime"].pack(side="left")

        # ── Bottom half: two list frames side by side ──
        lists_frame = tk.Frame(parent, bg=self.BG)
        lists_frame.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        # Top commands
        cmd_card = ttk.Frame(lists_frame, style="Card.TFrame", padding=10)
        cmd_card.pack(side="left", fill="both", expand=True, padx=(0, 8))
        tk.Label(cmd_card, text="Most Used Commands",
                 bg=self.BG2, fg=self.ACCENT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))

        cmd_tree_frame = tk.Frame(cmd_card, bg=self.BORDER, bd=1)
        cmd_tree_frame.pack(fill="both", expand=True)
        self._stat_cmd_tree = ttk.Treeview(cmd_tree_frame,
            columns=("cmd", "count"), show="headings", height=10)
        self._stat_cmd_tree.heading("cmd",   text="Command")
        self._stat_cmd_tree.heading("count", text="Uses")
        self._stat_cmd_tree.column("cmd",   width=140, minwidth=80)
        self._stat_cmd_tree.column("count", width=60,  minwidth=40, anchor="center")
        self._stat_cmd_tree.pack(fill="both", expand=True, side="left")
        ttk.Scrollbar(cmd_tree_frame, orient="vertical",
                      command=self._stat_cmd_tree.yview).pack(side="right", fill="y")
        self._stat_cmd_tree.configure(yscrollcommand=lambda *a: None)

        # Top users
        usr_card = ttk.Frame(lists_frame, style="Card.TFrame", padding=10)
        usr_card.pack(side="left", fill="both", expand=True)
        tk.Label(usr_card, text="Most Active Users",
                 bg=self.BG2, fg=self.ACCENT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))

        usr_tree_frame = tk.Frame(usr_card, bg=self.BORDER, bd=1)
        usr_tree_frame.pack(fill="both", expand=True)
        self._stat_usr_tree = ttk.Treeview(usr_tree_frame,
            columns=("user", "count"), show="headings", height=10)
        self._stat_usr_tree.heading("user",  text="User")
        self._stat_usr_tree.heading("count", text="Commands")
        self._stat_usr_tree.column("user",  width=160, minwidth=80)
        self._stat_usr_tree.column("count", width=60,  minwidth=40, anchor="center")
        self._stat_usr_tree.pack(fill="both", expand=True, side="left")
        ttk.Scrollbar(usr_tree_frame, orient="vertical",
                      command=self._stat_usr_tree.yview).pack(side="right", fill="y")

        btn_row = tk.Frame(parent, bg=self.BG)
        btn_row.pack(fill="x", padx=16, pady=(0, 8))
        ttk.Button(btn_row, text="🔄 Refresh Now", style="Dim.TButton",
                   command=self._refresh_stats_display).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="🗑 Reset Session Stats", style="Red.TButton",
                   command=self._reset_stats).pack(side="left")

    def _refresh_stats_display(self):
        # In Lite Mode the Stats tab may not be built yet (lazy-loaded on
        # first click). Skip all the widget updates until it exists, and
        # check back less often so this loop doesn't burn CPU for nothing.
        if not hasattr(self, "_stat_labels"):
            try:
                self._stats_update_job = self.root.after(10000, self._refresh_stats_display)
            except Exception:
                pass
            return
        try:
            # Counter cards
            for key in ("session_commands", "total_commands", "os_switches", "restarts", "reverts"):
                lbl = self._stat_labels.get(key)
                if lbl:
                    try:
                        lbl.configure(text=str(_stats.get(key, 0)))
                    except Exception:
                        pass

            # Uptime
            uptime_lbl = self._stat_labels.get("uptime")
            if uptime_lbl:
                t0 = _stats.get("bot_start_time")
                if t0 and self._bot_running:
                    elapsed = int(time.time() - t0)
                    h, rem  = divmod(elapsed, 3600)
                    m, s    = divmod(rem, 60)
                    uptime_lbl.configure(text=f"{h:02d}h {m:02d}m {s:02d}s")
                else:
                    uptime_lbl.configure(text="—  (bot not running)")

            # Top 15 commands
            top_cmds = sorted(_stats["command_counts"].items(),
                              key=lambda x: x[1], reverse=True)[:15]
            self._stat_cmd_tree.delete(*self._stat_cmd_tree.get_children())
            for i, (cmd, cnt) in enumerate(top_cmds):
                tag = "even" if i % 2 == 0 else "odd"
                self._stat_cmd_tree.insert("", "end", values=(cmd, cnt), tags=(tag,))
            self._stat_cmd_tree.tag_configure("even", background=self.BG3)
            self._stat_cmd_tree.tag_configure("odd",  background=self.BG2)

            # Top 15 users
            top_users = sorted(_stats["user_counts"].items(),
                               key=lambda x: x[1], reverse=True)[:15]
            self._stat_usr_tree.delete(*self._stat_usr_tree.get_children())
            for i, (usr, cnt) in enumerate(top_users):
                tag = "even" if i % 2 == 0 else "odd"
                self._stat_usr_tree.insert("", "end", values=(usr, cnt), tags=(tag,))
            self._stat_usr_tree.tag_configure("even", background=self.BG3)
            self._stat_usr_tree.tag_configure("odd",  background=self.BG2)
        except Exception:
            pass
        # Schedule next refresh
        try:
            interval = 5000 if APP_LITE_MODE else 2000
            self._stats_update_job = self.root.after(interval, self._refresh_stats_display)
        except Exception:
            pass

    def _reset_stats(self):
        if not messagebox.askyesno("Reset Stats", "Reset session statistics?"):
            return
        _stats["session_commands"] = 0
        _stats["os_switches"]      = 0
        _stats["reverts"]          = 0
        _stats["restarts"]         = 0
        _stats["command_counts"].clear()
        _stats["user_counts"].clear()
        _stats["bot_start_time"]   = time.time() if self._bot_running else None
        self._refresh_stats_display()
        self._log("[Stats] Session statistics reset.")

    # ──────────────── TAB 8 : USER MANAGEMENT ────────────────
    def _build_user_mgmt_tab(self, parent):
        parent.configure(style="TFrame")

        hdr = tk.Frame(parent, bg=self.BG)
        hdr.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(hdr, text="🚫  User Management",
                 bg=self.BG, fg=self.ACCENT,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w")
        tk.Label(hdr, text="Ban / Unban, Whitelist, and VIP lists — all without typing in chat.",
                 bg=self.BG, fg=self.TEXTDIM,
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))

        pane = tk.PanedWindow(parent, orient="horizontal",
                              bg=self.BORDER, sashwidth=4, sashrelief="flat")
        pane.pack(fill="both", expand=True, padx=12, pady=(4, 12))

        # ───── LEFT: Banned users ─────
        left = ttk.Frame(pane, style="Card.TFrame", padding=10)
        pane.add(left, minsize=280)

        tk.Label(left, text="🚫  Banned Users",
                 bg=self.BG2, fg=self.RED,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))

        ban_tree_frame = tk.Frame(left, bg=self.BORDER, bd=1)
        ban_tree_frame.pack(fill="both", expand=True)

        self._ban_tree = ttk.Treeview(ban_tree_frame,
            columns=("user", "expires"), show="headings", height=10)
        self._ban_tree.heading("user",    text="Username")
        self._ban_tree.heading("expires", text="Expires")
        self._ban_tree.column("user",    width=130, minwidth=80)
        self._ban_tree.column("expires", width=110, minwidth=80)
        self._ban_tree.pack(fill="both", expand=True, side="left")
        ttk.Scrollbar(ban_tree_frame, orient="vertical",
                      command=self._ban_tree.yview).pack(side="right", fill="y")

        # Manual ban row
        ban_input = tk.Frame(left, bg=self.BG2)
        ban_input.pack(fill="x", pady=(8, 4))
        tk.Label(ban_input, text="Username (@ optional):", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))
        self._ban_user_var = tk.StringVar()
        ttk.Entry(ban_input, textvariable=self._ban_user_var,
                  width=16, font=("Segoe UI", 10)).pack(side="left", ipady=3, padx=(0, 6))
        tk.Label(ban_input, text="Min:", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 9)).pack(side="left", padx=(0, 4))
        self._ban_dur_var = tk.StringVar(value="30")
        ttk.Entry(ban_input, textvariable=self._ban_dur_var,
                  width=5, font=("Segoe UI", 10)).pack(side="left", ipady=3, padx=(0, 6))

        ban_btn_row = tk.Frame(left, bg=self.BG2)
        ban_btn_row.pack(fill="x", pady=(0, 4))
        ttk.Button(ban_btn_row, text="🚫 Ban", style="Red.TButton",
                   command=self._gui_ban_user).pack(side="left", expand=True, fill="x", padx=(0, 4))
        ttk.Button(ban_btn_row, text="✅ Unban", style="Green.TButton",
                   command=self._gui_unban_user).pack(side="left", expand=True, fill="x")

        ttk.Button(left, text="🔄 Refresh Ban List", style="Dim.TButton",
                   command=self._refresh_ban_list).pack(fill="x", pady=(4, 0))

        # ───── RIGHT: Whitelist + VIP ─────
        right = tk.Frame(pane, bg=self.BG)
        pane.add(right, minsize=320)

        # Whitelist card
        wl_card = ttk.Frame(right, style="Card.TFrame", padding=10)
        wl_card.pack(fill="both", expand=True, pady=(0, 6))

        wl_hdr = tk.Frame(wl_card, bg=self.BG2)
        wl_hdr.pack(fill="x", pady=(0, 6))
        tk.Label(wl_hdr, text="✅  Whitelist",
                 bg=self.BG2, fg=self.GREEN,
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        self._wl_enabled_var = tk.BooleanVar(value=bool(whitelist_users))
        tk.Checkbutton(wl_hdr, text="Enabled (only listed users can use commands)",
                       variable=self._wl_enabled_var, bg=self.BG2, fg=self.TEXTDIM,
                       selectcolor=self.BG3, activebackground=self.BG2,
                       activeforeground=self.TEXT, font=("Segoe UI", 8),
                       command=self._on_whitelist_toggle).pack(side="left", padx=(10, 0))

        wl_list_frame = tk.Frame(wl_card, bg=self.BORDER, bd=1)
        wl_list_frame.pack(fill="both", expand=True)
        self._wl_listbox = tk.Listbox(wl_list_frame,
            bg=self.BG3, fg=self.TEXT,
            selectbackground=self.ACCENT, selectforeground="#fff",
            activestyle="none", font=("Segoe UI Mono", 10),
            relief="flat", bd=0, height=7)
        self._wl_listbox.pack(fill="both", expand=True, side="left")
        ttk.Scrollbar(wl_list_frame, orient="vertical",
                      command=self._wl_listbox.yview).pack(side="right", fill="y")

        wl_input = tk.Frame(wl_card, bg=self.BG2)
        wl_input.pack(fill="x", pady=(6, 0))
        tk.Label(wl_input, text="@ optional:", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 8)).pack(side="left", padx=(0, 4))
        self._wl_user_var = tk.StringVar()
        ttk.Entry(wl_input, textvariable=self._wl_user_var,
                  width=18, font=("Segoe UI", 10)).pack(side="left", ipady=3, padx=(0, 6))
        ttk.Button(wl_input, text="＋ Add", style="Green.TButton",
                   command=self._wl_add).pack(side="left", padx=(0, 4))
        ttk.Button(wl_input, text="✕ Remove", style="Red.TButton",
                   command=self._wl_remove).pack(side="left")

        # VIP card
        vip_card = ttk.Frame(right, style="Card.TFrame", padding=10)
        vip_card.pack(fill="both", expand=True)

        tk.Label(vip_card, text="⭐  VIP Users",
                 bg=self.BG2, fg=self.YELLOW,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))
        tk.Label(vip_card,
                 text="VIPs need fewer votes for restart/revert (1 = solo bypass).",
                 bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 6))

        vip_list_frame = tk.Frame(vip_card, bg=self.BORDER, bd=1)
        vip_list_frame.pack(fill="both", expand=True)
        self._vip_tree = ttk.Treeview(vip_list_frame,
            columns=("user", "votes"), show="headings", height=6)
        self._vip_tree.heading("user",  text="Username")
        self._vip_tree.heading("votes", text="Votes needed")
        self._vip_tree.column("user",  width=160, minwidth=80)
        self._vip_tree.column("votes", width=90,  minwidth=60, anchor="center")
        self._vip_tree.pack(fill="both", expand=True, side="left")
        ttk.Scrollbar(vip_list_frame, orient="vertical",
                      command=self._vip_tree.yview).pack(side="right", fill="y")

        vip_input = tk.Frame(vip_card, bg=self.BG2)
        vip_input.pack(fill="x", pady=(6, 0))
        tk.Label(vip_input, text="@ optional:", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 8)).pack(side="left", padx=(0, 4))
        self._vip_user_var  = tk.StringVar()
        self._vip_votes_var = tk.StringVar(value="1")
        ttk.Entry(vip_input, textvariable=self._vip_user_var,
                  width=14, font=("Segoe UI", 10)).pack(side="left", ipady=3, padx=(0, 4))
        tk.Label(vip_input, text="Votes:", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 9)).pack(side="left", padx=(0, 4))
        ttk.Entry(vip_input, textvariable=self._vip_votes_var,
                  width=4, font=("Segoe UI", 10)).pack(side="left", ipady=3, padx=(0, 6))
        ttk.Button(vip_input, text="＋ Add VIP", style="Accent.TButton",
                   command=self._vip_add).pack(side="left", padx=(0, 4))
        ttk.Button(vip_input, text="✕ Remove", style="Red.TButton",
                   command=self._vip_remove).pack(side="left")

        self._refresh_ban_list()
        self._refresh_wl_list()
        self._refresh_vip_list()

    # ── Ban/Unban helpers ──
    def _refresh_ban_list(self):
        self._ban_tree.delete(*self._ban_tree.get_children())
        now = time.time()
        expired = [u for u, exp in list(banned_users.items()) if now >= exp]
        for u in expired:
            del banned_users[u]
        for i, (user, exp) in enumerate(sorted(banned_users.items(), key=lambda x: x[1])):
            remaining = max(0, int(exp - now))
            m, s = divmod(remaining, 60)
            tag = "even" if i % 2 == 0 else "odd"
            self._ban_tree.insert("", "end", values=(user, f"{m}m {s}s"), tags=(tag,))
        self._ban_tree.tag_configure("even", background=self.BG3)
        self._ban_tree.tag_configure("odd",  background=self.BG2)
        self._ban_refresh_job = self.root.after(12000 if APP_LITE_MODE else 5000, self._refresh_ban_list)

    def _gui_ban_user(self):
        username = normalize_username(self._ban_user_var.get())
        if not username:
            messagebox.showwarning("Missing", "Enter a username to ban.")
            return
        try:
            minutes = max(1, int(self._ban_dur_var.get().strip()))
        except ValueError:
            minutes = 30
        banned_users[username] = time.time() + minutes * 60
        self._ban_user_var.set("")
        self._log(f"[UserMgmt] Banned '{username}' for {minutes} min.")
        notify("User Banned", f"@{username} banned for {minutes} minutes.")
        self._refresh_ban_list()

    def _gui_unban_user(self):
        sel = self._ban_tree.selection()
        if not sel:
            username = normalize_username(self._ban_user_var.get())
            if username and username in banned_users:
                del banned_users[username]
                self._log(f"[UserMgmt] Unbanned '{username}'.")
                self._ban_user_var.set("")
                self._refresh_ban_list()
            else:
                messagebox.showinfo("Select", "Select a user in the list or type a username.")
            return
        username = self._ban_tree.item(sel[0], "values")[0]
        if username in banned_users:
            del banned_users[username]
            self._log(f"[UserMgmt] Unbanned '{username}'.")
            self._refresh_ban_list()

    # ── Whitelist helpers ──
    def _on_whitelist_toggle(self):
        if not self._wl_enabled_var.get():
            whitelist_users.clear()
            save_user_mgmt()
            self._log("[UserMgmt] Whitelist disabled — all users can use commands.")

    def _refresh_wl_list(self):
        self._wl_listbox.delete(0, "end")
        for u in sorted(whitelist_users):
            self._wl_listbox.insert("end", u)

    def _wl_add(self):
        username = normalize_username(self._wl_user_var.get())
        if not username:
            return
        whitelist_users.add(username)
        self._wl_user_var.set("")
        self._wl_enabled_var.set(True)
        save_user_mgmt()
        self._refresh_wl_list()
        self._log(f"[UserMgmt] Added '{username}' to whitelist.")

    def _wl_remove(self):
        sel = self._wl_listbox.curselection()
        if not sel:
            return
        username = self._wl_listbox.get(sel[0])
        whitelist_users.discard(username)
        save_user_mgmt()
        self._refresh_wl_list()
        self._log(f"[UserMgmt] Removed '{username}' from whitelist.")
        if not whitelist_users:
            self._wl_enabled_var.set(False)

    # ── VIP helpers ──
    def _refresh_vip_list(self):
        self._vip_tree.delete(*self._vip_tree.get_children())
        for i, (usr, info) in enumerate(sorted(vip_users.items())):
            tag = "even" if i % 2 == 0 else "odd"
            self._vip_tree.insert("", "end",
                values=(usr, info.get("votes_needed", 1)), tags=(tag,))
        self._vip_tree.tag_configure("even", background=self.BG3)
        self._vip_tree.tag_configure("odd",  background=self.BG2)

    def _vip_add(self):
        username = normalize_username(self._vip_user_var.get())
        if not username:
            return
        try:
            votes = max(1, int(self._vip_votes_var.get().strip()))
        except ValueError:
            votes = 1
        vip_users[username] = {"votes_needed": votes}
        self._vip_user_var.set("")
        save_user_mgmt()
        self._refresh_vip_list()
        self._log(f"[UserMgmt] Added VIP '{username}' (votes needed: {votes}).")

    def _vip_remove(self):
        sel = self._vip_tree.selection()
        if not sel:
            return
        username = self._vip_tree.item(sel[0], "values")[0]
        vip_users.pop(username, None)
        save_user_mgmt()
        self._refresh_vip_list()
        self._log(f"[UserMgmt] Removed VIP '{username}'.")

    # ──────────────── Chain Parser ────────────────
    def _parse_chain_input(self):
        """
        Parses a chat-style chain like '!combo win+r !wait 800 !send notepad.exe'
        into individual steps. Replaces the current step list (does not append).
        """
        raw = self._chain_var.get().strip()
        if not raw:
            messagebox.showinfo("Empty", "Chain input field is empty.")
            return

        # Split on '!', discard empty parts
        parts = [p.strip() for p in raw.split('!') if p.strip()]
        if not parts:
            messagebox.showwarning("Parse Error", "No valid command found.\nCommands must start with !.")
            return

        steps = []
        for part in parts:
            tokens = part.split(maxsplit=1)
            action = tokens[0].lower()
            args   = tokens[1] if len(tokens) > 1 else ""
            steps.append({"action": action, "args": args})

        self._step_items = steps
        self._refresh_step_tree()
        self._chain_var.set("")   # clear
        self._mark_dirty(1)
        self._log(f"[ChainParse] {len(steps)} step(s) created: "
                  + "  →  ".join(f"{s['action']}({s['args']})" for s in steps))

    def _refresh_cmd_list(self):
        self._cmd_listbox.delete(0, 'end')
        for trigger in sorted(custom_commands.keys()):
            self._cmd_listbox.insert('end', trigger)

    def _on_cmd_select(self, event=None):
        sel = self._cmd_listbox.curselection()
        if not sel: return
        trigger = self._cmd_listbox.get(sel[0])
        self._editing_cmd = trigger
        self._trig_var.set(trigger)
        self._step_items  = list(custom_commands.get(trigger, []))
        self._refresh_step_tree()
        self._clear_dirty(1)

    def _refresh_step_tree(self):
        for row in self._step_tree.get_children():
            self._step_tree.delete(row)
        for i, step in enumerate(self._step_items):
            tag = "even" if i % 2 == 0 else "odd"
            self._step_tree.insert("", "end",
                values=(step["action"], step["args"]), tags=(tag,))
        self._step_tree.tag_configure("even", background=self.BG3)
        self._step_tree.tag_configure("odd",  background=self.BG2)

    def _add_step(self):
        action = self._action_var.get().strip()
        args   = self._args_var.get().strip()
        if not action:
            messagebox.showwarning("Missing", "Please select an action.")
            return
        self._step_items.append({"action": action, "args": args})
        self._refresh_step_tree()
        self._args_var.set("")
        self._mark_dirty(1)

    def _selected_step_idx(self):
        sel = self._step_tree.selection()
        if not sel: return None
        children = self._step_tree.get_children()
        return list(children).index(sel[0])

    def _step_up(self):
        idx = self._selected_step_idx()
        if idx is None or idx == 0: return
        self._step_items[idx-1], self._step_items[idx] = \
            self._step_items[idx], self._step_items[idx-1]
        self._refresh_step_tree()
        self._step_tree.selection_set(self._step_tree.get_children()[idx-1])
        self._mark_dirty(1)

    def _step_down(self):
        idx = self._selected_step_idx()
        if idx is None or idx >= len(self._step_items)-1: return
        self._step_items[idx], self._step_items[idx+1] = \
            self._step_items[idx+1], self._step_items[idx]
        self._refresh_step_tree()
        self._step_tree.selection_set(self._step_tree.get_children()[idx+1])
        self._mark_dirty(1)

    def _step_remove(self):
        idx = self._selected_step_idx()
        if idx is None: return
        self._step_items.pop(idx)
        self._refresh_step_tree()
        self._mark_dirty(1)

    def _new_cmd(self):
        self._editing_cmd = None
        self._trig_var.set("!")
        self._step_items  = []
        self._refresh_step_tree()
        self._cmd_listbox.selection_clear(0, 'end')
        self._clear_dirty(1)

    def _save_cmd(self):
        trigger = self._trig_var.get().strip()
        if not trigger.startswith("!") or len(trigger) < 2:
            messagebox.showerror("Invalid Trigger",
                "Trigger must start with ! and have a name.\nExample: !bubbles")
            return
        custom_commands[trigger] = list(self._step_items)
        save_custom_commands()
        self._clear_dirty(1)
        self._refresh_cmd_list()
        self._log(f"[CustomCmd] Saved '{trigger}' with {len(self._step_items)} step(s).")

    def _delete_cmd(self):
        sel = self._cmd_listbox.curselection()
        if not sel:
            messagebox.showinfo("Select", "Select a command to delete.")
            return
        trigger = self._cmd_listbox.get(sel[0])
        if messagebox.askyesno("Delete", f"Delete '{trigger}'?"):
            del custom_commands[trigger]
            save_custom_commands()
            self._clear_dirty(1)
            self._refresh_cmd_list()
            self._new_cmd()
            self._log(f"[CustomCmd] Deleted '{trigger}'.")

    def _test_cmd(self):
        trigger = self._trig_var.get().strip()
        if trigger not in custom_commands:
            messagebox.showinfo("Not Saved", "Save the command first, then test.")
            return
        threading.Thread(target=execute_custom_command,
                         args=(trigger,), daemon=True).start()
        self._log(f"[CustomCmd] Testing '{trigger}'...")

    # ──────────────── TAB 9 : EVENT LOG ────────────────
    def _build_event_log_tab(self, parent):
        parent.configure(style="TFrame")

        hdr = tk.Frame(parent, bg=self.BG)
        hdr.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(hdr, text="📋  Event Log / History",
                 bg=self.BG, fg=self.ACCENT,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w")
        tk.Label(hdr, text="All commands, votes, bans, restarts, and scheduled actions — filterable and exportable.",
                 bg=self.BG, fg=self.TEXTDIM, font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))

        # Filter bar
        filter_frame = ttk.Frame(parent, style="Card.TFrame", padding=8)
        filter_frame.pack(fill="x", padx=12, pady=(0, 6))

        tk.Label(filter_frame, text="Filter type:", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))
        self._elog_type_var = tk.StringVar(value="ALL")
        type_cb = ttk.Combobox(filter_frame, textvariable=self._elog_type_var,
                               state="readonly", width=14,
                               values=["ALL", "COMMAND", "RESTART", "REVERT",
                                       "OS_SWITCH", "BAN_VOTE", "BAN",
                                       "SCHEDULER", "COOLDOWN", "REALPC_CMD"])
        type_cb.pack(side="left", padx=(0, 12))

        tk.Label(filter_frame, text="User:", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 9)).pack(side="left", padx=(0, 4))
        self._elog_user_var = tk.StringVar()
        ttk.Entry(filter_frame, textvariable=self._elog_user_var,
                  width=16, font=("Segoe UI", 9)).pack(side="left", padx=(0, 12))

        ttk.Button(filter_frame, text="🔍 Apply Filter", style="Accent.TButton",
                   command=self._apply_elog_filter).pack(side="left", padx=(0, 6))
        ttk.Button(filter_frame, text="🔄 Refresh", style="Dim.TButton",
                   command=self._apply_elog_filter).pack(side="left", padx=(0, 12))
        ttk.Button(filter_frame, text="💾 Export CSV", style="Green.TButton",
                   command=self._export_elog_csv).pack(side="left")

        # Treeview
        tree_frame = tk.Frame(parent, bg=self.BORDER, bd=1)
        tree_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self._elog_tree = ttk.Treeview(tree_frame,
            columns=("ts", "type", "user", "detail"), show="headings")
        self._elog_tree.heading("ts",     text="Timestamp")
        self._elog_tree.heading("type",   text="Type")
        self._elog_tree.heading("user",   text="User")
        self._elog_tree.heading("detail", text="Detail")
        self._elog_tree.column("ts",     width=150, minwidth=120)
        self._elog_tree.column("type",   width=110, minwidth=80)
        self._elog_tree.column("user",   width=140, minwidth=80)
        self._elog_tree.column("detail", width=300, minwidth=100)
        elog_scroll = ttk.Scrollbar(tree_frame, orient="vertical",
                      command=self._elog_tree.yview)
        elog_scroll.pack(side="right", fill="y")
        self._elog_tree.pack(fill="both", expand=True, side="left")
        self._elog_tree.configure(yscrollcommand=elog_scroll.set)

        self._apply_elog_filter()
        # Auto-refresh every 3 seconds while the tab is visible
        self._elog_auto_refresh()

    def _elog_auto_refresh(self):
        """Called every 3s to keep the Event Log tab live."""
        try:
            self._apply_elog_filter()
        except Exception:
            pass
        self.root.after(8000 if APP_LITE_MODE else 3000, self._elog_auto_refresh)

    def _apply_elog_filter(self):
        type_f = self._elog_type_var.get()
        user_f = self._elog_user_var.get().strip().lower()
        self._elog_tree.delete(*self._elog_tree.get_children())
        with _event_log_lock:
            entries = list(_event_log)
        shown = 0
        for i, entry in enumerate(reversed(entries)):
            if type_f != "ALL" and entry.get("type") != type_f:
                continue
            if user_f and user_f not in entry.get("user", "").lower():
                continue
            tag = "even" if shown % 2 == 0 else "odd"
            self._elog_tree.insert("", "end",
                values=(entry.get("ts", ""),
                        entry.get("type", ""),
                        entry.get("user", ""),
                        entry.get("detail", "")),
                tags=(tag,))
            shown += 1
            if shown >= 1000:
                break
        self._elog_tree.tag_configure("even", background=self.BG3)
        self._elog_tree.tag_configure("odd",  background=self.BG2)

    def _export_elog_csv(self):
        import csv
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            title="Export Event Log")
        if not path:
            return
        try:
            with _event_log_lock:
                entries = list(_event_log)
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["ts", "type", "user", "detail"])
                writer.writeheader()
                writer.writerows(entries)
            messagebox.showinfo("Export Done", f"Exported {len(entries)} entries to:\n{path}")
        except Exception as e:
            messagebox.showerror("Export Failed", str(e))

    # ──────────────── TAB 10 : PERMISSIONS ────────────────
    def _build_permissions_tab(self, parent):
        parent.configure(style="TFrame")

        hdr = tk.Frame(parent, bg=self.BG)
        hdr.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(hdr, text="🔒  Permissions",
                 bg=self.BG, fg=self.ACCENT,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w")
        tk.Label(hdr, text="Set how many votes are required for each action — no code editing needed.",
                 bg=self.BG, fg=self.TEXTDIM, font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))

        card = ttk.Frame(parent, style="Card.TFrame", padding=20)
        card.pack(fill="x", padx=12, pady=(8, 0))

        PERM_ROWS = [
            ("restart_votes",   "🔁  Restart votes required",
             "Number of !restart votes needed to reset the VM."),
            ("revert_votes",    "⏮  Revert votes required",
             "Number of !revert votes needed to restore the snapshot."),
            ("ban_votes",       "🚫  Ban votes required",
             "Number of !ban votes needed to ban a user."),
            ("action_cooldown", "⏱  Action cooldown (seconds)",
             "Seconds to wait after a restart/revert before another can be triggered."),
        ]

        self._perm_vars = {}
        for row_i, (key, label, hint) in enumerate(PERM_ROWS):
            tk.Label(card, text=label, bg=self.BG2, fg=self.TEXT,
                     font=("Segoe UI", 10, "bold")).grid(
                     row=row_i * 2, column=0, sticky="w", pady=(12 if row_i else 0, 0))
            tk.Label(card, text=hint, bg=self.BG2, fg=self.TEXTDIM,
                     font=("Segoe UI", 8)).grid(
                     row=row_i * 2 + 1, column=0, sticky="w", padx=(16, 0))

            var = tk.IntVar(value=PERMISSIONS_CONFIG.get(key, 2 if key != "action_cooldown" else 60))
            self._perm_vars[key] = var

            spin_to = 3600 if key == "action_cooldown" else 99
            spin_from = 0  if key == "action_cooldown" else 1
            spin = tk.Spinbox(card, textvariable=var,
                              from_=spin_from, to=spin_to, width=6,
                              bg=self.BG3, fg=self.TEXT,
                              insertbackground=self.TEXT,
                              buttonbackground=self.BG3,
                              font=("Segoe UI", 12, "bold"),
                              relief="flat", bd=1)
            spin.grid(row=row_i * 2, column=1, rowspan=2, padx=(24, 0),
                      pady=(12 if row_i else 0, 0), sticky="n")

        card.columnconfigure(0, weight=1)

        btn_row = tk.Frame(parent, bg=self.BG)
        btn_row.pack(fill="x", padx=12, pady=(16, 0))
        ttk.Button(btn_row, text="💾 Save Permissions", style="Green.TButton",
                   command=self._save_permissions).pack(side="left")

        # Live preview
        self._perm_status = tk.Label(parent, text="",
                                     bg=self.BG, fg=self.GREEN,
                                     font=("Segoe UI", 9))
        self._perm_status.pack(anchor="w", padx=16, pady=(6, 0))

        # Track unsaved changes (tab index 9)
        self._trace_dirty(9, *self._perm_vars.values())

    def _save_permissions(self):
        for key, var in self._perm_vars.items():
            try:
                val = int(var.get())
                PERMISSIONS_CONFIG[key] = max(0, val) if key == "action_cooldown" else max(1, val)
            except ValueError:
                pass
        save_permissions_config()
        self._clear_dirty(9)
        self._perm_status.configure(
            text=f"Saved — restart:{PERMISSIONS_CONFIG['restart_votes']}  "
                 f"revert:{PERMISSIONS_CONFIG['revert_votes']}  "
                 f"ban:{PERMISSIONS_CONFIG['ban_votes']}  "
                 f"cooldown:{PERMISSIONS_CONFIG['action_cooldown']}s")
        self._log("[Permissions] Config saved.")

    # ──────────────── TAB 11 : SOUND & TTS ────────────────
    def _build_sound_tts_tab(self, parent):
        parent.configure(style="TFrame")

        hdr = tk.Frame(parent, bg=self.BG)
        hdr.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(hdr, text="🔊  Sound & TTS",
                 bg=self.BG, fg=self.ACCENT,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w")
        tk.Label(hdr, text="Configure per-event sounds and Text-to-Speech settings.",
                 bg=self.BG, fg=self.TEXTDIM, font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))

        # Sound files card
        snd_card = ttk.Frame(parent, style="Card.TFrame", padding=14)
        snd_card.pack(fill="x", padx=12, pady=(8, 6))
        tk.Label(snd_card, text="Event Sound Files  (.mp3 / .wav)",
                 bg=self.BG2, fg=self.ACCENT,
                 font=("Segoe UI", 10, "bold")).grid(
                 row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        SOUND_ROWS = [
            ("success_sound",   "Success (default)"),
            ("restart_sound",   "VM Restart"),
            ("revert_sound",    "VM Revert"),
            ("ban_sound",       "User Banned"),
            ("os_switch_sound", "OS Switch"),
        ]
        self._sound_vars = {}
        for r, (key, label) in enumerate(SOUND_ROWS, start=1):
            tk.Label(snd_card, text=label, bg=self.BG2, fg=self.TEXT,
                     font=("Segoe UI", 9)).grid(row=r, column=0, sticky="w", pady=3, padx=(0, 10))
            var = tk.StringVar(value=SOUND_CONFIG.get(key, ""))
            self._sound_vars[key] = var
            ttk.Entry(snd_card, textvariable=var,
                      width=26, font=("Segoe UI", 9)).grid(
                      row=r, column=1, sticky="ew", padx=(0, 6), ipady=3)

            def _browse(v=var):
                from tkinter import filedialog
                p = filedialog.askopenfilename(
                    filetypes=[("Audio files", "*.mp3 *.wav"), ("All files", "*.*")],
                    title="Select sound file")
                if p:
                    v.set(p)

            ttk.Button(snd_card, text="📂", style="Dim.TButton",
                       command=_browse).grid(row=r, column=2, padx=(0, 4))

            def _test_sound(v=var):
                f = v.get().strip()
                if f:
                    try: subprocess.Popen(['start', f], shell=True)
                    except Exception as e: messagebox.showerror("Error", str(e))
                else:
                    messagebox.showinfo("No File", "No sound file configured for this event.")

            ttk.Button(snd_card, text="▶ Test", style="Accent.TButton",
                       command=_test_sound).grid(row=r, column=3, padx=(0, 4))

        snd_card.columnconfigure(1, weight=1)

        # TTS card
        tts_card = ttk.Frame(parent, style="Card.TFrame", padding=14)
        tts_card.pack(fill="x", padx=12, pady=(0, 6))
        tk.Label(tts_card, text="Text-to-Speech (SAPI)",
                 bg=self.BG2, fg=self.ACCENT,
                 font=("Segoe UI", 10, "bold")).grid(
                 row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        self._tts_enabled_var = tk.BooleanVar(value=SOUND_CONFIG.get("tts_enabled", True))
        tk.Checkbutton(tts_card, text="TTS Enabled",
                       variable=self._tts_enabled_var,
                       bg=self.BG2, fg=self.TEXT,
                       selectcolor=self.BG3,
                       activebackground=self.BG2,
                       font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", pady=4)

        tk.Label(tts_card, text="Speed (words/min):", bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI", 9)).grid(row=2, column=0, sticky="w", pady=3, padx=(0, 10))
        self._tts_rate_var = tk.IntVar(value=SOUND_CONFIG.get("tts_rate", 150))
        tk.Spinbox(tts_card, textvariable=self._tts_rate_var,
                   from_=50, to=400, width=6,
                   bg=self.BG3, fg=self.TEXT,
                   insertbackground=self.TEXT,
                   buttonbackground=self.BG3,
                   font=("Segoe UI", 11), relief="flat").grid(
                   row=2, column=1, sticky="w", padx=(0, 12))
        tk.Label(tts_card, text="(50–400, default 150)", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 8)).grid(row=2, column=2, sticky="w")

        tk.Label(tts_card, text="Volume (0–100):", bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI", 9)).grid(row=3, column=0, sticky="w", pady=3, padx=(0, 10))
        self._tts_vol_var = tk.IntVar(value=SOUND_CONFIG.get("tts_volume", 100))
        tk.Spinbox(tts_card, textvariable=self._tts_vol_var,
                   from_=0, to=100, width=6,
                   bg=self.BG3, fg=self.TEXT,
                   insertbackground=self.TEXT,
                   buttonbackground=self.BG3,
                   font=("Segoe UI", 11), relief="flat").grid(
                   row=3, column=1, sticky="w", padx=(0, 12))

        # Test TTS
        self._tts_test_var = tk.StringVar(value="VirtualBox Chat Bot is ready!")
        tk.Label(tts_card, text="Test phrase:", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 9)).grid(row=4, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(tts_card, textvariable=self._tts_test_var,
                  width=30, font=("Segoe UI", 9)).grid(
                  row=4, column=1, columnspan=2, sticky="ew", pady=(8, 0), ipady=3)
        ttk.Button(tts_card, text="🗣 Test TTS", style="Accent.TButton",
                   command=self._test_tts).grid(row=5, column=0, columnspan=3,
                                                sticky="w", pady=(8, 0))

        tts_card.columnconfigure(1, weight=1)

        # Save button
        btn_row = tk.Frame(parent, bg=self.BG)
        btn_row.pack(fill="x", padx=12, pady=(8, 0))
        ttk.Button(btn_row, text="💾 Save Sound & TTS Config", style="Green.TButton",
                   command=self._save_sound_config).pack(side="left")

        # Track unsaved changes (tab index 10)
        self._trace_dirty(10, self._tts_enabled_var, self._tts_rate_var, self._tts_vol_var,
                          *self._sound_vars.values())

    def _test_tts(self):
        # Apply preview settings first
        SOUND_CONFIG["tts_enabled"] = True  # always test
        SOUND_CONFIG["tts_rate"]    = int(self._tts_rate_var.get())
        SOUND_CONFIG["tts_volume"]  = int(self._tts_vol_var.get())
        speak_text(self._tts_test_var.get() or "Test")

    def _save_sound_config(self):
        for key, var in self._sound_vars.items():
            SOUND_CONFIG[key] = var.get().strip()
        SOUND_CONFIG["tts_enabled"] = self._tts_enabled_var.get()
        try: SOUND_CONFIG["tts_rate"]   = max(50,  min(400, int(self._tts_rate_var.get())))
        except ValueError: pass
        try: SOUND_CONFIG["tts_volume"] = max(0, min(100, int(self._tts_vol_var.get())))
        except ValueError: pass
        global SUCCESS_SOUND_FILE
        SUCCESS_SOUND_FILE = SOUND_CONFIG.get("success_sound", "success.mp3")
        save_sound_config()
        self._clear_dirty(10)
        self._log("[Sound] Config saved.")

    # ──────────────── TAB 12 : MULTI-STREAM ────────────────
    def _build_multi_stream_tab(self, parent):
        parent.configure(style="TFrame")

        hdr = tk.Frame(parent, bg=self.BG)
        hdr.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(hdr, text="🌐  Multi-Stream",
                 bg=self.BG, fg=self.ACCENT,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w")
        tk.Label(hdr,
                 text="Listen to multiple YouTube streams at once — "
                      "all video IDs share the same command handling.",
                 bg=self.BG, fg=self.TEXTDIM, font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))

        card = ttk.Frame(parent, style="Card.TFrame", padding=14)
        card.pack(fill="x", padx=12, pady=(8, 0))

        tk.Label(card,
                 text="Extra YouTube Video IDs  (in addition to the Main tab ID):",
                 bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 6))

        list_frame = tk.Frame(card, bg=self.BORDER, bd=1)
        list_frame.pack(fill="both", expand=True, pady=(0, 6))
        self._ms_listbox = tk.Listbox(list_frame,
            bg=self.BG3, fg=self.TEXT,
            selectbackground=self.ACCENT, selectforeground="#fff",
            activestyle="none", font=("Segoe UI Mono", 11),
            relief="flat", bd=0, height=8)
        self._ms_listbox.pack(fill="both", expand=True, side="left")
        ttk.Scrollbar(list_frame, orient="vertical",
                      command=self._ms_listbox.yview).pack(side="right", fill="y")

        add_row = tk.Frame(card, bg=self.BG2)
        add_row.pack(fill="x", pady=(0, 4))
        self._ms_entry_var = tk.StringVar()
        ttk.Entry(add_row, textvariable=self._ms_entry_var,
                  width=28, font=("Segoe UI Mono", 10)).pack(
                  side="left", ipady=4, padx=(0, 8))
        ttk.Button(add_row, text="＋ Add", style="Green.TButton",
                   command=self._ms_add).pack(side="left", padx=(0, 6))
        ttk.Button(add_row, text="✕ Remove Selected", style="Red.TButton",
                   command=self._ms_remove).pack(side="left")

        btn_row = tk.Frame(parent, bg=self.BG)
        btn_row.pack(fill="x", padx=12, pady=(10, 0))
        ttk.Button(btn_row, text="💾 Save", style="Green.TButton",
                   command=self._ms_save).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="▶ Apply (restart bot to take effect)", style="Dim.TButton",
                   command=lambda: self._log("[MultiStream] Restart the bot to apply changes.")).pack(side="left")

        self._ms_status = tk.Label(parent, text="", bg=self.BG, fg=self.TEXTDIM,
                                   font=("Segoe UI", 8, "italic"))
        self._ms_status.pack(anchor="w", padx=16, pady=(6, 0))

        self._ms_refresh_list()
        # Track unsaved changes (tab index 11)
        self._trace_dirty(11, self._ms_entry_var)

    def _ms_refresh_list(self):
        self._ms_listbox.delete(0, "end")
        for vid in MULTI_STREAM_CONFIG.get("video_ids", []):
            self._ms_listbox.insert("end", vid)
        self._ms_status.configure(
            text=f"{len(MULTI_STREAM_CONFIG.get('video_ids', []))} extra stream(s) configured.")

    def _ms_add(self):
        vid = self._ms_entry_var.get().strip()
        if not vid:
            return
        ids = MULTI_STREAM_CONFIG.setdefault("video_ids", [])
        if vid not in ids:
            ids.append(vid)
        self._ms_entry_var.set("")
        self._ms_refresh_list()
        self._mark_dirty(11)

    def _ms_remove(self):
        sel = self._ms_listbox.curselection()
        if not sel:
            return
        vid = self._ms_listbox.get(sel[0])
        try:
            MULTI_STREAM_CONFIG["video_ids"].remove(vid)
        except ValueError:
            pass
        self._ms_refresh_list()
        self._mark_dirty(11)

    def _ms_save(self):
        save_multi_stream_config()
        self._clear_dirty(11)
        self._ms_status.configure(
            text=f"Saved. {len(MULTI_STREAM_CONFIG.get('video_ids', []))} extra stream(s). "
                 f"Restart the bot to apply.")
        self._log("[MultiStream] Config saved.")

    # ──────────────── TAB 13 : SCHEDULER ────────────────
    def _build_scheduler_tab(self, parent):
        parent.configure(style="TFrame")

        hdr = tk.Frame(parent, bg=self.BG)
        hdr.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(hdr, text="📅  Scheduler",
                 bg=self.BG, fg=self.ACCENT,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w")
        tk.Label(hdr,
                 text="Run automatic revert or restart at specific times — e.g. every night at 03:00.",
                 bg=self.BG, fg=self.TEXTDIM, font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))

        # Enable toggle
        top_bar = ttk.Frame(parent, style="Card.TFrame", padding=10)
        top_bar.pack(fill="x", padx=12, pady=(4, 6))
        self._sched_enabled_var = tk.BooleanVar(value=SCHEDULER_CONFIG.get("enabled", False))
        tk.Checkbutton(top_bar, text="Enable Scheduler",
                       variable=self._sched_enabled_var,
                       bg=self.BG2, fg=self.YELLOW,
                       selectcolor=self.BG3, activebackground=self.BG2,
                       activeforeground=self.YELLOW,
                       font=("Segoe UI", 10, "bold"),
                       command=self._sched_toggle).pack(side="left")
        self._sched_status_lbl = tk.Label(top_bar, text="", bg=self.BG2,
                                          fg=self.TEXTDIM, font=("Segoe UI", 8))
        self._sched_status_lbl.pack(side="left", padx=16)
        self._sched_update_status()

        pane = tk.PanedWindow(parent, orient="horizontal",
                              bg=self.BORDER, sashwidth=4, sashrelief="flat")
        pane.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # Left: task list
        left = ttk.Frame(pane, style="Card.TFrame", padding=10)
        pane.add(left, minsize=220, width=260)

        tk.Label(left, text="Scheduled Tasks",
                 bg=self.BG2, fg=self.ACCENT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))

        task_tree_frame = tk.Frame(left, bg=self.BORDER, bd=1)
        task_tree_frame.pack(fill="both", expand=True)
        self._sched_tree = ttk.Treeview(task_tree_frame,
            columns=("label", "action", "time", "days"), show="headings", height=12)
        self._sched_tree.heading("label",  text="Label")
        self._sched_tree.heading("action", text="Action")
        self._sched_tree.heading("time",   text="Time")
        self._sched_tree.heading("days",   text="Days")
        self._sched_tree.column("label",  width=100, minwidth=60)
        self._sched_tree.column("action", width=70,  minwidth=55)
        self._sched_tree.column("time",   width=55,  minwidth=45)
        self._sched_tree.column("days",   width=80,  minwidth=60)
        self._sched_tree.pack(fill="both", expand=True, side="left")
        ttk.Scrollbar(task_tree_frame, orient="vertical",
                      command=self._sched_tree.yview).pack(side="right", fill="y")
        self._sched_tree.bind("<<TreeviewSelect>>", self._sched_on_select)

        btn_row = tk.Frame(left, bg=self.BG2)
        btn_row.pack(fill="x", pady=(6, 0))
        ttk.Button(btn_row, text="🗑 Delete", style="Red.TButton",
                   command=self._sched_delete).pack(fill="x")

        # Right: editor
        right = ttk.Frame(pane, style="Card.TFrame", padding=12)
        pane.add(right, minsize=280)

        tk.Label(right, text="Task Editor",
                 bg=self.BG2, fg=self.ACCENT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 10))

        row_f = tk.Frame(right, bg=self.BG2)
        row_f.pack(fill="x", pady=3)
        tk.Label(row_f, text="Label:", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 9), width=10, anchor="w").pack(side="left")
        self._sched_label_var = tk.StringVar()
        ttk.Entry(row_f, textvariable=self._sched_label_var,
                  width=24, font=("Segoe UI", 10)).pack(side="left", ipady=3)

        row_f2 = tk.Frame(right, bg=self.BG2)
        row_f2.pack(fill="x", pady=3)
        tk.Label(row_f2, text="Action:", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 9), width=10, anchor="w").pack(side="left")
        self._sched_action_var = tk.StringVar(value="revert")
        ttk.Combobox(row_f2, textvariable=self._sched_action_var,
                     state="readonly", width=12,
                     values=["revert", "restart"]).pack(side="left")

        row_f3 = tk.Frame(right, bg=self.BG2)
        row_f3.pack(fill="x", pady=3)
        tk.Label(row_f3, text="Time (HH:MM):", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 9), width=14, anchor="w").pack(side="left")
        self._sched_hour_var   = tk.IntVar(value=3)
        self._sched_minute_var = tk.IntVar(value=0)
        tk.Spinbox(row_f3, textvariable=self._sched_hour_var,
                   from_=0, to=23, width=4,
                   bg=self.BG3, fg=self.TEXT, insertbackground=self.TEXT,
                   buttonbackground=self.BG3,
                   font=("Segoe UI", 10), relief="flat").pack(side="left")
        tk.Label(row_f3, text=":", bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI", 12, "bold")).pack(side="left", padx=2)
        tk.Spinbox(row_f3, textvariable=self._sched_minute_var,
                   from_=0, to=59, width=4,
                   bg=self.BG3, fg=self.TEXT, insertbackground=self.TEXT,
                   buttonbackground=self.BG3,
                   font=("Segoe UI", 10), relief="flat").pack(side="left")

        tk.Label(right, text="Days of week (leave all unchecked = every day):",
                 bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(10, 4))
        DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        self._sched_day_vars = []
        days_row = tk.Frame(right, bg=self.BG2)
        days_row.pack(anchor="w")
        for i, dlbl in enumerate(DAY_LABELS):
            v = tk.BooleanVar(value=False)
            self._sched_day_vars.append(v)
            tk.Checkbutton(days_row, text=dlbl, variable=v,
                           bg=self.BG2, fg=self.TEXT,
                           selectcolor=self.BG3,
                           activebackground=self.BG2,
                           font=("Segoe UI", 9)).pack(side="left", padx=2)

        ttk.Button(right, text="＋ Add / Update Task", style="Green.TButton",
                   command=self._sched_add).pack(fill="x", pady=(14, 0))
        ttk.Button(right, text="💾 Save All Scheduler Tasks", style="Accent.TButton",
                   command=self._sched_save).pack(fill="x", pady=(6, 0))

        self._sched_refresh_tree()
        # Track unsaved changes (tab index 12)
        self._trace_dirty(12, self._sched_label_var, self._sched_action_var,
                          self._sched_hour_var, self._sched_minute_var,
                          self._sched_enabled_var, *self._sched_day_vars)

    def _sched_update_status(self):
        if SCHEDULER_CONFIG.get("enabled"):
            self._sched_status_lbl.configure(text="Active — tasks will fire automatically.", fg=self.GREEN)
        else:
            self._sched_status_lbl.configure(text="Disabled — tasks will not fire.", fg=self.TEXTDIM)

    def _sched_toggle(self):
        SCHEDULER_CONFIG["enabled"] = self._sched_enabled_var.get()
        save_scheduler_config()
        self._clear_dirty(12)
        self._sched_update_status()
        self._log(f"[Scheduler] {'Enabled' if SCHEDULER_CONFIG['enabled'] else 'Disabled'}.")

    def _sched_refresh_tree(self):
        self._sched_tree.delete(*self._sched_tree.get_children())
        DAY_SHORT = ["Mo","Tu","We","Th","Fr","Sa","Su"]
        for i, task in enumerate(SCHEDULER_CONFIG.get("tasks", [])):
            days = task.get("days", [])
            days_str = "".join(DAY_SHORT[d] for d in sorted(days)) if days else "Every"
            time_str = f"{task.get('hour', 0):02d}:{task.get('minute', 0):02d}"
            tag = "even" if i % 2 == 0 else "odd"
            self._sched_tree.insert("", "end",
                iid=str(i),
                values=(task.get("label", ""), task.get("action", ""), time_str, days_str),
                tags=(tag,))
        self._sched_tree.tag_configure("even", background=self.BG3)
        self._sched_tree.tag_configure("odd",  background=self.BG2)

    def _sched_on_select(self, event=None):
        sel = self._sched_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        tasks = SCHEDULER_CONFIG.get("tasks", [])
        if idx >= len(tasks):
            return
        task = tasks[idx]
        self._sched_label_var.set(task.get("label", ""))
        self._sched_action_var.set(task.get("action", "revert"))
        self._sched_hour_var.set(task.get("hour", 3))
        self._sched_minute_var.set(task.get("minute", 0))
        days = task.get("days", [])
        for i, v in enumerate(self._sched_day_vars):
            v.set(i in days)

    def _sched_add(self):
        label = self._sched_label_var.get().strip()
        if not label:
            messagebox.showwarning("Missing", "Enter a label for the task.")
            return
        try:
            hour   = max(0, min(23, int(self._sched_hour_var.get())))
            minute = max(0, min(59, int(self._sched_minute_var.get())))
        except ValueError:
            messagebox.showwarning("Invalid", "Hour and minute must be numbers.")
            return
        days = [i for i, v in enumerate(self._sched_day_vars) if v.get()]
        action = self._sched_action_var.get()
        tasks = SCHEDULER_CONFIG.setdefault("tasks", [])
        # Check for existing task with same label to update
        for t in tasks:
            if t.get("label") == label:
                t.update({"action": action, "hour": hour, "minute": minute, "days": days})
                self._sched_refresh_tree()
                self._mark_dirty(12)
                self._log(f"[Scheduler] Updated task '{label}'.")
                return
        import uuid
        tasks.append({
            "id":       str(uuid.uuid4())[:8],
            "label":    label,
            "action":   action,
            "hour":     hour,
            "minute":   minute,
            "days":     days,
            "last_run": "",
        })
        self._sched_refresh_tree()
        self._log(f"[Scheduler] Added task '{label}' → {action} at {hour:02d}:{minute:02d}.")
        self._mark_dirty(12)

    def _sched_delete(self):
        sel = self._sched_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        tasks = SCHEDULER_CONFIG.get("tasks", [])
        if idx < len(tasks):
            removed = tasks.pop(idx)
            self._log(f"[Scheduler] Deleted task '{removed.get('label', '')}'.")
            self._sched_refresh_tree()
            self._mark_dirty(12)

    def _sched_save(self):
        save_scheduler_config()
        self._clear_dirty(12)
        self._log("[Scheduler] Tasks saved.")

    # ──────────────── TAB 14 : REAL PC CONTROL ────────────────
    def _build_realpc_tab(self, parent):
        parent.configure(style="TFrame")

        # ── Header ──
        hdr = tk.Frame(parent, bg=self.BG)
        hdr.pack(fill="x", padx=16, pady=(14, 4))
        tk.Label(hdr, text="🖱  Real PC Control",
                 bg=self.BG, fg=self.ACCENT,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w")
        tk.Label(hdr,
                 text="Let YouTube chat control THIS computer with pyautogui — "
                      "keyboard, mouse, hotkeys and more.",
                 bg=self.BG, fg=self.TEXTDIM,
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))

        # ── pyautogui missing warning ──
        if not _PYAUTOGUI_OK:
            warn_card = ttk.Frame(parent, style="Card.TFrame", padding=20)
            warn_card.pack(fill="x", padx=12, pady=12)
            tk.Label(warn_card,
                     text="⚠  pyautogui is not installed.",
                     bg=self.BG2, fg=self.YELLOW,
                     font=("Segoe UI", 11, "bold")).pack(anchor="w")
            tk.Label(warn_card,
                     text="Run the following command in a terminal, then restart the bot:",
                     bg=self.BG2, fg=self.TEXT,
                     font=("Segoe UI", 9)).pack(anchor="w", pady=(6, 4))
            tk.Label(warn_card,
                     text="    pip install pyautogui",
                     bg=self.BG3, fg=self.ACCENT,
                     font=("Courier New", 11, "bold")).pack(
                     anchor="w", padx=8, pady=4)
            return   # nothing else to build

        # ── Scrollable body ──
        canvas  = tk.Canvas(parent, bg=self.BG, highlightthickness=0)
        vscroll = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vscroll.set)
        vscroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=self.BG)
        _inner_win = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner_cfg(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_cfg(e):
            canvas.itemconfig(_inner_win, width=e.width)
        def _on_wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        inner.bind("<Configure>",  _on_inner_cfg)
        canvas.bind("<Configure>", _on_canvas_cfg)
        canvas.bind("<MouseWheel>", _on_wheel)
        inner.bind("<MouseWheel>",  _on_wheel)

        # ── Connection card ──
        conn_card = ttk.Frame(inner, style="Card.TFrame", padding=14)
        conn_card.pack(fill="x", padx=12, pady=(10, 6))
        conn_card.bind("<MouseWheel>", _on_wheel)

        tk.Label(conn_card, text="Stream Connection",
                 bg=self.BG2, fg=self.ACCENT,
                 font=("Segoe UI", 10, "bold")).grid(
                 row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        tk.Label(conn_card, text="YouTube Video ID:",
                 bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", padx=(0, 10))
        self._rpc_vid_var = tk.StringVar(value=REALPC_CONFIG.get("video_id", ""))
        ttk.Entry(conn_card, textvariable=self._rpc_vid_var,
                  width=30, font=("Segoe UI Mono", 10)).grid(
                  row=1, column=1, sticky="ew", ipady=4, padx=(0, 10))
        tk.Label(conn_card,
                 text="Can be the same as the main bot or a different stream.",
                 bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 8)).grid(row=2, column=1, sticky="w", pady=(2, 0))

        tk.Label(conn_card,
                 text="Commands: !type  !send  !combo  !click  !move  !scroll  etc.\n"
                      "Every message starting with ! is parsed as a command — no prefix needed.",
                 bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 8)).grid(
                 row=3, column=0, columnspan=3, sticky="w", pady=(10, 0))

        conn_card.columnconfigure(1, weight=1)

        # ── Start / Stop buttons ──
        ctrl_row = tk.Frame(inner, bg=self.BG)
        ctrl_row.pack(fill="x", padx=12, pady=(4, 4))

        self._rpc_start_btn = ttk.Button(ctrl_row, text="▶ Start Real PC Bot",
                                          style="Green.TButton",
                                          command=self._rpc_start)
        self._rpc_start_btn.pack(side="left", padx=(0, 8))

        self._rpc_stop_btn = ttk.Button(ctrl_row, text="⏹ Stop",
                                         style="Red.TButton",
                                         command=self._rpc_stop)
        self._rpc_stop_btn.pack(side="left")

        self._rpc_status_lbl = tk.Label(ctrl_row, text="⬤  Stopped",
                                         bg=self.BG, fg=self.RED,
                                         font=("Segoe UI", 9, "bold"))
        self._rpc_status_lbl.pack(side="left", padx=(14, 0))

        # Wire status callback
        def _set_rpc_status(msg: str):
            color = self.GREEN if "Listen" in msg or "Connect" in msg else (
                    self.YELLOW if "FAILSAFE" in msg or "fail" in msg.lower() else
                    self.TEXTDIM)
            try:
                self.root.after(0, lambda m=msg, c=color:
                    self._rpc_status_lbl.configure(text=f"⬤  {m}", fg=c))
            except Exception:
                pass

        global _realpc_status_cb
        _realpc_status_cb = _set_rpc_status

        # ── Settings card ──
        settings_card = ttk.Frame(inner, style="Card.TFrame", padding=14)
        settings_card.pack(fill="x", padx=12, pady=(0, 6))
        settings_card.bind("<MouseWheel>", _on_wheel)

        tk.Label(settings_card, text="Behavior Settings",
                 bg=self.BG2, fg=self.ACCENT,
                 font=("Segoe UI", 10, "bold")).grid(
                 row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))

        # Cooldown
        tk.Label(settings_card, text="Per-user cooldown (sec):",
                 bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", padx=(0, 8))
        self._rpc_cd_var = tk.DoubleVar(value=REALPC_CONFIG.get("cooldown", 1.0))
        tk.Spinbox(settings_card, textvariable=self._rpc_cd_var,
                   from_=0.0, to=60.0, increment=0.5, width=6,
                   bg=self.BG3, fg=self.TEXT,
                   insertbackground=self.TEXT, buttonbackground=self.BG3,
                   font=("Segoe UI", 10), relief="flat").grid(
                   row=1, column=1, sticky="w", padx=(0, 20))

        # Mouse step
        tk.Label(settings_card, text="Mouse step (px):",
                 bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI", 9)).grid(row=1, column=2, sticky="w", padx=(0, 8))
        self._rpc_step_var = tk.IntVar(value=REALPC_CONFIG.get("mouse_step", 50))
        tk.Spinbox(settings_card, textvariable=self._rpc_step_var,
                   from_=1, to=500, width=6,
                   bg=self.BG3, fg=self.TEXT,
                   insertbackground=self.TEXT, buttonbackground=self.BG3,
                   font=("Segoe UI", 10), relief="flat").grid(
                   row=1, column=3, sticky="w")

        # Max type length
        tk.Label(settings_card, text="Max type length (chars):",
                 bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI", 9)).grid(row=2, column=0, sticky="w",
                                            padx=(0, 8), pady=(8, 0))
        self._rpc_maxtype_var = tk.IntVar(value=REALPC_CONFIG.get("max_type_length", 100))
        tk.Spinbox(settings_card, textvariable=self._rpc_maxtype_var,
                   from_=1, to=500, width=6,
                   bg=self.BG3, fg=self.TEXT,
                   insertbackground=self.TEXT, buttonbackground=self.BG3,
                   font=("Segoe UI", 10), relief="flat").grid(
                   row=2, column=1, sticky="w", pady=(8, 0))

        # Scroll step
        tk.Label(settings_card, text="Scroll step (clicks):",
                 bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI", 9)).grid(row=2, column=2, sticky="w",
                                            padx=(0, 8), pady=(8, 0))
        self._rpc_scroll_var = tk.IntVar(value=REALPC_CONFIG.get("scroll_step", 3))
        tk.Spinbox(settings_card, textvariable=self._rpc_scroll_var,
                   from_=1, to=50, width=6,
                   bg=self.BG3, fg=self.TEXT,
                   insertbackground=self.TEXT, buttonbackground=self.BG3,
                   font=("Segoe UI", 10), relief="flat").grid(
                   row=2, column=3, sticky="w", pady=(8, 0))

        # Failsafe
        self._rpc_failsafe_var = tk.BooleanVar(
            value=REALPC_CONFIG.get("failsafe", False))
        tk.Checkbutton(settings_card,
                       text="Enable pyautogui failsafe  "
                            "(move mouse to top-left corner to instantly stop all actions)",
                       variable=self._rpc_failsafe_var,
                       bg=self.BG2, fg=self.YELLOW,
                       selectcolor=self.BG3, activebackground=self.BG2,
                       font=("Segoe UI", 9)).grid(
                       row=3, column=0, columnspan=4, sticky="w", pady=(10, 0))

        settings_card.columnconfigure(1, weight=1)
        settings_card.columnconfigure(3, weight=1)

        # ── Allowed Actions card ──
        allow_card = ttk.Frame(inner, style="Card.TFrame", padding=14)
        allow_card.pack(fill="x", padx=12, pady=(0, 6))
        allow_card.bind("<MouseWheel>", _on_wheel)

        tk.Label(allow_card, text="Allowed Action Categories",
                 bg=self.BG2, fg=self.ACCENT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 4))

        # ── Dangerous Command Filter toggle (HARD default ON) ──
        self._rpc_danger_filter_var = tk.BooleanVar(
            value=REALPC_CONFIG.get("danger_filter_enabled", True))

        danger_row = tk.Frame(allow_card, bg=self.BG2)
        danger_row.pack(fill="x", pady=(0, 8))
        danger_row.bind("<MouseWheel>", _on_wheel)

        danger_cb = tk.Checkbutton(
            danger_row,
            text="🛡  Dangerous Command Filter  —  hard-blocks destructive commands "
                 "(format, shutdown, rm -rf, etc.), even if typed across multiple steps",
            variable=self._rpc_danger_filter_var,
            bg=self.BG2, fg=self.GREEN,
            selectcolor=self.BG3, activebackground=self.BG2,
            activeforeground=self.RED,
            font=("Segoe UI", 9, "bold"),
            command=self._rpc_on_danger_filter_toggle,
        )
        danger_cb.pack(side="left")
        self._rpc_danger_filter_cb = danger_cb

        ttk.Button(danger_row, text="📋 View Blocked List", style="Dim.TButton",
                   command=self._show_blocked_commands_list).pack(side="left", padx=(10, 0))

        tk.Label(allow_card,
                 text="This protection is ON by default and is strongly recommended to keep on.",
                 bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 8))

        ttk.Separator(allow_card, orient="horizontal").pack(fill="x", pady=(0, 8))

        # Text-Only mode toggle
        self._rpc_text_only_var = tk.BooleanVar(
            value=REALPC_CONFIG.get("text_only", False))

        text_only_row = tk.Frame(allow_card, bg=self.BG2)
        text_only_row.pack(fill="x", pady=(0, 8))
        text_only_row.bind("<MouseWheel>", _on_wheel)

        text_only_cb = tk.Checkbutton(
            text_only_row,
            text="✏  Text Only Mode  —  only  !type  and  !send  are allowed, everything else is blocked",
            variable=self._rpc_text_only_var,
            bg=self.BG2, fg=self.YELLOW,
            selectcolor=self.BG3, activebackground=self.BG2,
            activeforeground=self.YELLOW,
            font=("Segoe UI", 9, "bold"),
            command=self._rpc_on_text_only_toggle,
        )
        text_only_cb.pack(side="left")

        ttk.Separator(allow_card, orient="horizontal").pack(fill="x", pady=(0, 8))

        self._rpc_allow_vars = {}
        action_rows = [
            ("keyboard",   "⌨  Keyboard  (!type, !send, !key, !enter, !backspace, !space)"),
            ("combo",      "🔗  Combo     (!combo win+d, !combo ctrl+c, !combo alt+f4)"),
            ("mouse",      "🖱  Mouse     (!click, !rclick, !dclick, !move, !moverel, !scroll, !drag)"),
            ("screenshot", "📸  Screenshot  (!screenshot / !ss — saves PNG to bot folder)"),
        ]
        self._rpc_allow_checkbuttons = []
        for key, label in action_rows:
            var = tk.BooleanVar(
                value=REALPC_CONFIG.get("allowed_actions", {}).get(key, True))
            self._rpc_allow_vars[key] = var
            cb = tk.Checkbutton(allow_card, text=label,
                           variable=var,
                           bg=self.BG2, fg=self.TEXT,
                           selectcolor=self.BG3, activebackground=self.BG2,
                           font=("Segoe UI", 9))
            cb.pack(anchor="w", pady=2)
            cb.bind("<MouseWheel>", _on_wheel)
            self._rpc_allow_checkbuttons.append(cb)

        # Sync checkbox states on build
        self._rpc_sync_text_only_ui()

        # ── Access Control card ──
        access_card = ttk.Frame(inner, style="Card.TFrame", padding=14)
        access_card.pack(fill="x", padx=12, pady=(0, 6))
        access_card.bind("<MouseWheel>", _on_wheel)

        tk.Label(access_card, text="Access Control",
                 bg=self.BG2, fg=self.ACCENT,
                 font=("Segoe UI", 10, "bold")).grid(
                 row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

        self._rpc_wl_only_var = tk.BooleanVar(
            value=REALPC_CONFIG.get("whitelist_only", False))
        tk.Checkbutton(access_card,
                       text="Whitelist only — only listed users can send commands",
                       variable=self._rpc_wl_only_var,
                       bg=self.BG2, fg=self.TEXT,
                       selectcolor=self.BG3, activebackground=self.BG2,
                       font=("Segoe UI", 9)).grid(
                       row=1, column=0, columnspan=3, sticky="w", pady=(0, 8))

        # Whitelist
        tk.Label(access_card, text="Whitelist:",
                 bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 9, "bold")).grid(
                 row=2, column=0, sticky="nw", padx=(0, 8))

        wl_frame = tk.Frame(access_card, bg=self.BORDER, bd=1)
        wl_frame.grid(row=2, column=1, sticky="ew", padx=(0, 8))
        self._rpc_wl_listbox = tk.Listbox(wl_frame, height=5,
            bg=self.BG3, fg=self.TEXT,
            selectbackground=self.ACCENT, selectforeground="#fff",
            font=("Segoe UI", 9), relief="flat", bd=0)
        self._rpc_wl_listbox.pack(fill="both", expand=True)
        for u in REALPC_CONFIG.get("whitelist", []):
            self._rpc_wl_listbox.insert("end", u)

        wl_btn_col = tk.Frame(access_card, bg=self.BG2)
        wl_btn_col.grid(row=2, column=2, sticky="n")
        self._rpc_wl_entry = tk.StringVar()
        ttk.Entry(wl_btn_col, textvariable=self._rpc_wl_entry,
                  width=16, font=("Segoe UI", 9)).pack(pady=(0, 4), ipady=3)
        ttk.Button(wl_btn_col, text="＋ Add", style="Green.TButton",
                   command=self._rpc_wl_add).pack(fill="x", pady=(0, 3))
        ttk.Button(wl_btn_col, text="✕ Remove", style="Red.TButton",
                   command=self._rpc_wl_remove).pack(fill="x")

        # Blocked list
        tk.Label(access_card, text="Blocked:",
                 bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 9, "bold")).grid(
                 row=3, column=0, sticky="nw", padx=(0, 8), pady=(12, 0))

        bl_frame = tk.Frame(access_card, bg=self.BORDER, bd=1)
        bl_frame.grid(row=3, column=1, sticky="ew", padx=(0, 8), pady=(12, 0))
        self._rpc_bl_listbox = tk.Listbox(bl_frame, height=4,
            bg=self.BG3, fg=self.TEXT,
            selectbackground=self.RED, selectforeground="#fff",
            font=("Segoe UI", 9), relief="flat", bd=0)
        self._rpc_bl_listbox.pack(fill="both", expand=True)
        for u in REALPC_CONFIG.get("blocked", []):
            self._rpc_bl_listbox.insert("end", u)

        bl_btn_col = tk.Frame(access_card, bg=self.BG2)
        bl_btn_col.grid(row=3, column=2, sticky="n", pady=(12, 0))
        self._rpc_bl_entry = tk.StringVar()
        ttk.Entry(bl_btn_col, textvariable=self._rpc_bl_entry,
                  width=16, font=("Segoe UI", 9)).pack(pady=(0, 4), ipady=3)
        ttk.Button(bl_btn_col, text="🚫 Block", style="Red.TButton",
                   command=self._rpc_bl_add).pack(fill="x", pady=(0, 3))
        ttk.Button(bl_btn_col, text="✕ Remove", style="Dim.TButton",
                   command=self._rpc_bl_remove).pack(fill="x")

        access_card.columnconfigure(1, weight=1)

        # ── Command Reference card ──
        ref_card = ttk.Frame(inner, style="Card.TFrame", padding=14)
        ref_card.pack(fill="x", padx=12, pady=(0, 6))
        ref_card.bind("<MouseWheel>", _on_wheel)

        tk.Label(ref_card, text="Command Reference",
                 bg=self.BG2, fg=self.ACCENT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))

        CMD_HELP = (
            "Commands work exactly like the main bot — just type !command in chat.\n"
            "No prefix needed. Every message starting with ! is parsed as a command.\n\n"
            "CHAIN COMMANDS  (multiple commands in one message)\n"
            "  !combo win+r !wait 1 !send cmd !wait 0.5 !key enter\n"
            "  !click 960 540 !wait 0.3 !type hello !enter\n"
            "  Commands execute left-to-right in order.\n\n"
            "WAIT / DELAY\n"
            "  !wait 1              — wait 1 second before next command  (max 10s)\n"
            "  !wait 0.5            — wait 500ms\n"
            "  !sleep 2             — same as !wait\n\n"
            "KEYBOARD\n"
            "  !type hello world    — types text into the focused window\n"
            "  !send hello          — types text then presses Enter\n"
            "  !key enter           — presses a single key  (enter, esc, tab, f1…f12, etc.)\n"
            "  !enter               — shortcut for pressing Enter\n"
            "  !space               — shortcut for pressing Space\n"
            "  !backspace           — deletes last character\n\n"
            "COMBO  (key combinations)\n"
            "  !combo win+r         — opens Run dialog\n"
            "  !combo win+d         — shows desktop\n"
            "  !combo ctrl+c        — copy\n"
            "  !combo ctrl+v        — paste\n"
            "  !combo alt+f4        — closes focused window\n"
            "  !combo ctrl+shift+esc — opens Task Manager\n\n"
            "MOUSE\n"
            "  !click               — left-click at current cursor position\n"
            "  !click 960 540       — left-click at x=960 y=540\n"
            "  !rclick              — right-click\n"
            "  !dclick              — double-click\n"
            "  !move 960 540        — move cursor to exact coordinates\n"
            "  !moverel up          — move cursor up by step pixels  (step set in Settings)\n"
            "  !moverel down / left / right\n"
            "  !moverel 100 -50     — move cursor by +100x -50y\n"
            "  !scroll 3            — scroll up 3 clicks\n"
            "  !scroll -3           — scroll down 3 clicks\n"
            "  !drag 200 0          — drag mouse 200px right\n\n"
            "SCREENSHOT & INFO\n"
            "  !screenshot          — saves a PNG to the bot folder\n"
            "  !ss                  — same as !screenshot\n"
            "  !pos                 — prints current cursor position to status bar\n"
            "  !size                — prints screen resolution to status bar\n"
        )

        ref_txt = tk.Text(ref_card, height=22, bg=self.BG3, fg=self.TEXTDIM,
                          font=("Courier New", 9), relief="flat", bd=0,
                          wrap="none", state="normal")
        ref_txt.insert("1.0", CMD_HELP)
        ref_txt.configure(state="disabled")
        ref_txt.pack(fill="x")
        ref_txt.bind("<MouseWheel>", _on_wheel)

        # ── Live log card ──
        log_card = ttk.Frame(inner, style="Card.TFrame", padding=14)
        log_card.pack(fill="x", padx=12, pady=(0, 12))
        log_card.bind("<MouseWheel>", _on_wheel)

        tk.Label(log_card, text="Live Action Log",
                 bg=self.BG2, fg=self.ACCENT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))

        self._rpc_log = tk.Text(log_card, height=8,
                                bg=self.BG3, fg=self.TEXT,
                                font=("Courier New", 9), relief="flat", bd=0,
                                state="disabled", wrap="word")
        self._rpc_log.pack(fill="x")
        self._rpc_log.bind("<MouseWheel>", _on_wheel)

        ttk.Button(log_card, text="🗑 Clear Log", style="Dim.TButton",
                   command=lambda: (
                       self._rpc_log.configure(state="normal"),
                       self._rpc_log.delete("1.0", "end"),
                       self._rpc_log.configure(state="disabled")
                   )).pack(anchor="e", pady=(6, 0))

        # ── Save button ──
        save_row = tk.Frame(inner, bg=self.BG)
        save_row.pack(fill="x", padx=12, pady=(0, 14))
        ttk.Button(save_row, text="💾 Save Real PC Config",
                   style="Green.TButton",
                   command=self._rpc_save).pack(side="left")

        # ── Dirty-tracking: mark tab 13 (Real PC) as unsaved on any change ──
        self._trace_dirty(13,
            self._rpc_vid_var, self._rpc_cd_var, self._rpc_step_var,
            self._rpc_maxtype_var, self._rpc_scroll_var,
            self._rpc_failsafe_var, self._rpc_text_only_var,
            self._rpc_wl_only_var, *self._rpc_allow_vars.values())

        # Wire live log to event log entries tagged REALPC_*
        self._rpc_log_callback_active = True
        self._start_rpc_log_poller()

    def _start_rpc_log_poller(self):
        """Poll event log every 500ms and append new REALPC_* entries to the live log."""
        self._rpc_last_log_len = 0

        def _poll():
            if not getattr(self, "_rpc_log_callback_active", False):
                return
            try:
                with _event_log_lock:
                    entries = list(_event_log)
                new_entries = entries[self._rpc_last_log_len:]
                self._rpc_last_log_len = len(entries)
                for e in new_entries:
                    if e.get("type", "").startswith("REALPC"):
                        line = (f"[{e['ts']}]  {e['user']:<20}  "
                                f"{e['type']:<18}  {e['detail']}\n")
                        self._rpc_log.configure(state="normal")
                        self._rpc_log.insert("end", line)
                        self._rpc_log.see("end")
                        self._rpc_log.configure(state="disabled")
            except Exception:
                pass
            self.root.after(500, _poll)

        self.root.after(500, _poll)

    def _rpc_on_text_only_toggle(self):
        """Called when the Text Only checkbox is clicked."""
        self._rpc_sync_text_only_ui()

    def _rpc_on_danger_filter_toggle(self):
        """
        Called when the Dangerous Command Filter checkbox is clicked.
        Turning the filter OFF requires two explicit hard warnings.
        Turning it back ON never requires confirmation.
        """
        if self._rpc_danger_filter_var.get():
            # User (re)enabled it — no confirmation needed, just apply.
            REALPC_CONFIG["danger_filter_enabled"] = True
            return

        # User is trying to turn the filter OFF — hard-stop with 2 warnings.
        # Warning 1
        if not messagebox.askokcancel(
            "🛑  Disable Dangerous Command Filter — Warning 1 of 2",
            "You are about to DISABLE the Dangerous Command Filter.\n\n"
            "This filter is the ONLY thing hard-blocking destructive commands "
            "(format, shutdown, del /f, rm -rf, registry edits, PowerShell "
            "download-and-run chains, etc.) sent by YouTube chat viewers — "
            "including ones spelled out across multiple small steps to dodge "
            "detection (e.g. typed in chunks, key-by-key, or edited with "
            "backspace).\n\n"
            "Without it, ANY viewer could potentially damage this computer, "
            "delete files, or take actions with NO SAFETY NET.\n\n"
            "Click OK to continue to the final warning, or Cancel to keep "
            "the filter enabled.",
            icon="warning",
        ):
            self._rpc_danger_filter_var.set(True)
            return

        # Warning 2 — final "I accept full responsibility" confirmation
        if not messagebox.askokcancel(
            "🛑  Disable Dangerous Command Filter — Warning 2 of 2  (Final)",
            "FINAL CONFIRMATION:\n\n"
            "By clicking OK you confirm that:\n\n"
            "  • You are turning OFF the hard-coded protection against "
            "destructive and dangerous commands.\n\n"
            "  • YOU take FULL and SOLE responsibility for any damage, "
            "data loss, security breach, or other consequence that results "
            "from this computer being controlled by YouTube chat with this "
            "protection disabled.\n\n"
            "  • The developer (Nexovative) is NOT responsible under any "
            "circumstances for the outcome of this decision.\n\n"
            "Click OK to permanently disable the filter for this session, "
            "or Cancel to keep it enabled.",
            icon="warning",
        ):
            self._rpc_danger_filter_var.set(True)
            return

        # Both warnings accepted — actually disable it.
        REALPC_CONFIG["danger_filter_enabled"] = False
        _realpc_set_status("⚠ Dangerous Command Filter DISABLED by user")
        _append_event("REALPC_DANGER_FILTER", "SYSTEM",
                       "Dangerous command filter disabled by operator after double confirmation")

    def _rpc_sync_text_only_ui(self):
        """Grey out / restore category checkboxes based on Text Only state."""
        text_only = self._rpc_text_only_var.get()
        state = "disabled" if text_only else "normal"
        fg    = self.TEXTDIM if text_only else self.TEXT
        for cb in getattr(self, "_rpc_allow_checkbuttons", []):
            cb.configure(state=state, fg=fg)

    def _rpc_start(self):
        # ── 3-step safety confirmation ──
        # Warning 1
        if not messagebox.askokcancel(
            "⚠  Real PC Control — Warning 1 of 3",
            "You are about to give YouTube CHAT viewers direct control\n"
            "over THIS computer's keyboard and mouse.\n\n"
            "Anyone watching your stream will be able to:\n"
            "  • Type text into any open window\n"
            "  • Click and move your mouse\n"
            "  • Open programs, close windows, press key combos\n\n"
            "Make sure you understand the risks before continuing.\n\n"
            "Click OK to proceed to the next warning, or Cancel to abort.",
            icon="warning"
        ):
            return

        # Warning 2
        if not messagebox.askokcancel(
            "⚠  Real PC Control — Warning 2 of 3",
            "SECURITY RISK — READ CAREFULLY:\n\n"
            "• Viewers can type into password fields, browsers, terminals\n"
            "• Viewers can close or crash applications on your PC\n"
            "• Viewers can attempt to open Run dialogs, CMD, PowerShell\n"
            "• There is NO undo — actions execute instantly on your machine\n\n"
            "Recommended precautions:\n"
            "  ✔  Use the Whitelist to restrict who can send commands\n"
            "  ✔  Enable Failsafe (move mouse to top-left corner to stop)\n"
            "  ✔  Close sensitive apps (browser, email, file manager) first\n"
            "  ✔  Disable the Combo category if you don't want hotkeys used\n\n"
            "Click OK to proceed to the final confirmation, or Cancel to abort.",
            icon="warning"
        ):
            return

        # Warning 3 — final "I accept responsibility" confirmation
        if not messagebox.askokcancel(
            "⚠  Real PC Control — Warning 3 of 3  (Final)",
            "FINAL CONFIRMATION:\n\n"
            "By clicking OK you confirm that:\n\n"
            "  • You take FULL responsibility for any actions\n"
            "    performed on this computer through chat commands.\n\n"
            "  • The developer (Nexovative) is NOT responsible\n"
            "    for any damage, data loss, privacy breach, or\n"
            "    unintended consequences caused by this feature.\n\n"
            "  • You are aware this is an ADVANCED feature and you\n"
            "    have taken the necessary precautions.\n\n"
            "Click OK to START Real PC Control, or Cancel to abort.",
            icon="warning"
        ):
            return

        # All 3 warnings accepted — proceed
        self._rpc_collect_to_config()
        save_realpc_config()
        if not REALPC_CONFIG.get("video_id", "").strip():
            messagebox.showwarning("Missing", "Enter a YouTube Video ID first.")
            return
        if start_realpc_bot():
            self._rpc_status_lbl.configure(
                text="⬤  Starting...", fg=self.YELLOW)
        else:
            messagebox.showinfo("Already Running",
                                "Real PC bot is already running.")

    def _rpc_stop(self):
        stop_realpc_bot()
        self._rpc_status_lbl.configure(text="⬤  Stopped", fg=self.RED)

    def _rpc_save(self):
        self._rpc_collect_to_config()
        save_realpc_config()
        self._clear_dirty(13)
        messagebox.showinfo("Saved", "Real PC Control config saved.")

    def _rpc_collect_to_config(self):
        """Read all GUI widgets and push values into REALPC_CONFIG."""
        REALPC_CONFIG["video_id"]       = self._rpc_vid_var.get().strip()
        REALPC_CONFIG["failsafe"]       = self._rpc_failsafe_var.get()
        REALPC_CONFIG["whitelist_only"] = self._rpc_wl_only_var.get()
        REALPC_CONFIG["text_only"]      = self._rpc_text_only_var.get()
        REALPC_CONFIG["danger_filter_enabled"] = self._rpc_danger_filter_var.get()
        try:
            REALPC_CONFIG["cooldown"] = max(0.0, float(self._rpc_cd_var.get()))
        except (ValueError, tk.TclError):
            pass
        try:
            REALPC_CONFIG["mouse_step"] = max(1, int(self._rpc_step_var.get()))
        except (ValueError, tk.TclError):
            pass
        try:
            REALPC_CONFIG["scroll_step"] = max(1, int(self._rpc_scroll_var.get()))
        except (ValueError, tk.TclError):
            pass
        try:
            REALPC_CONFIG["max_type_length"] = max(1, int(self._rpc_maxtype_var.get()))
        except (ValueError, tk.TclError):
            pass
        REALPC_CONFIG["allowed_actions"] = {
            k: v.get() for k, v in self._rpc_allow_vars.items()
        }
        REALPC_CONFIG["whitelist"] = list(self._rpc_wl_listbox.get(0, "end"))
        REALPC_CONFIG["blocked"]   = list(self._rpc_bl_listbox.get(0, "end"))

    def _rpc_wl_add(self):
        user = normalize_username(self._rpc_wl_entry.get())
        if user and user not in self._rpc_wl_listbox.get(0, "end"):
            self._rpc_wl_listbox.insert("end", user)
        self._rpc_wl_entry.set("")
        self._mark_dirty(13)

    def _rpc_wl_remove(self):
        sel = self._rpc_wl_listbox.curselection()
        if sel:
            self._rpc_wl_listbox.delete(sel[0])
            self._mark_dirty(13)

    def _rpc_bl_add(self):
        user = normalize_username(self._rpc_bl_entry.get())
        if user and user not in self._rpc_bl_listbox.get(0, "end"):
            self._rpc_bl_listbox.insert("end", user)
        self._rpc_bl_entry.set("")
        self._mark_dirty(13)

    def _rpc_bl_remove(self):
        sel = self._rpc_bl_listbox.curselection()
        if sel:
            self._rpc_bl_listbox.delete(sel[0])
            self._mark_dirty(13)

    # ──────────────── TAB 15 : RECONNECT ────────────────
    def _build_reconnect_tab(self, parent):
        parent.configure(style="TFrame")

        hdr = tk.Frame(parent, bg=self.BG)
        hdr.pack(fill="x", padx=16, pady=(14, 4))
        tk.Label(hdr, text="🔄  Auto-Reconnect Settings",
                 bg=self.BG, fg=self.ACCENT,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w")
        tk.Label(hdr,
                 text="Configure how the bot behaves when the YouTube chat connection drops.",
                 bg=self.BG, fg=self.TEXTDIM,
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))

        card = ttk.Frame(parent, style="Card.TFrame", padding=20)
        card.pack(fill="x", padx=12, pady=(10, 6))

        ROWS = [
            ("max_failures",      "Max consecutive failures",
             "Stop the bot automatically after this many failures in a row.\n"
             "Set to 0 to retry forever."),
            ("base_delay",        "Base retry delay (seconds)",
             "How long to wait after the first failure before retrying.\n"
             "Subsequent failures wait longer (exponential backoff)."),
            ("max_delay",         "Maximum retry delay (seconds)",
             "The upper limit on how long to wait between retries.\n"
             "Prevents very long waits after many failures."),
            ("notify_threshold",  "Notify after N failures",
             "Show a desktop notification after this many consecutive failures.\n"
             "Set to 0 to disable notifications."),
        ]

        self._reconn_vars = {}
        for row_i, (key, label, hint) in enumerate(ROWS):
            tk.Label(card, text=label,
                     bg=self.BG2, fg=self.TEXT,
                     font=("Segoe UI", 10, "bold")).grid(
                     row=row_i * 2, column=0, sticky="w",
                     pady=(16 if row_i else 0, 0))
            tk.Label(card, text=hint,
                     bg=self.BG2, fg=self.TEXTDIM,
                     font=("Segoe UI", 8),
                     wraplength=480, justify="left").grid(
                     row=row_i * 2 + 1, column=0, sticky="w", padx=(16, 0))
            var = tk.IntVar(value=RECONNECT_CONFIG.get(key, 0))
            self._reconn_vars[key] = var
            tk.Spinbox(card, textvariable=var,
                       from_=0, to=3600, width=7,
                       bg=self.BG3, fg=self.TEXT,
                       insertbackground=self.TEXT,
                       buttonbackground=self.BG3,
                       font=("Segoe UI", 12, "bold"),
                       relief="flat", bd=1).grid(
                       row=row_i * 2, column=1, rowspan=2,
                       padx=(24, 0), pady=(16 if row_i else 0, 0), sticky="n")

        card.columnconfigure(0, weight=1)

        # ── Dirty-tracking: mark tab 14 (Reconnect) as unsaved on any change ──
        self._trace_dirty(14, *self._reconn_vars.values())

        # Status card
        status_card = ttk.Frame(parent, style="Card.TFrame", padding=14)
        status_card.pack(fill="x", padx=12, pady=(0, 6))
        tk.Label(status_card, text="Current Status",
                 bg=self.BG2, fg=self.ACCENT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))
        self._reconn_status_lbl = tk.Label(
            status_card, text="No connection failures.",
            bg=self.BG2, fg=self.GREEN,
            font=("Segoe UI", 9))
        self._reconn_status_lbl.pack(anchor="w")
        self._root_after_reconnect_poll()

        # Save button
        btn_row = tk.Frame(parent, bg=self.BG)
        btn_row.pack(fill="x", padx=12, pady=(10, 0))
        ttk.Button(btn_row, text="💾 Save Reconnect Config",
                   style="Green.TButton",
                   command=self._save_reconnect_config).pack(side="left")

        self._reconn_saved_lbl = tk.Label(parent, text="",
                                          bg=self.BG, fg=self.GREEN,
                                          font=("Segoe UI", 9))
        self._reconn_saved_lbl.pack(anchor="w", padx=16, pady=(4, 0))

    def _build_nexoai_tab(self, parent):
        """
        NexoAI tab — chat with Groq-hosted LLMs directly from the app.
        The Groq API key is entered once, saved to nexoai_config.json, and
        reused automatically on every future launch.
        """
        outer = tk.Frame(parent, bg=self.BG)
        outer.pack(fill="both", expand=True)

        # ── API key + model card ──
        setup_card = ttk.Frame(outer, style="Card.TFrame", padding=14)
        setup_card.pack(fill="x", padx=12, pady=(12, 6))

        tk.Label(setup_card, text="Groq API Key",
                 bg=self.BG2, fg=self.ACCENT,
                 font=("Segoe UI", 10, "bold")).grid(
                 row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))

        self._nexoai_key_var = tk.StringVar(value=NEXOAI_CONFIG.get("groq_api_key", ""))
        self._nexoai_key_entry = ttk.Entry(
            setup_card, textvariable=self._nexoai_key_var,
            width=44, font=("Segoe UI", 9), show="•")
        self._nexoai_key_entry.grid(row=1, column=0, columnspan=2, sticky="ew",
                                     padx=(0, 6), ipady=3)

        self._nexoai_key_visible = False

        def _toggle_key_visibility():
            self._nexoai_key_visible = not self._nexoai_key_visible
            self._nexoai_key_entry.configure(show="" if self._nexoai_key_visible else "•")
            show_btn.configure(text="🙈 Hide" if self._nexoai_key_visible else "👁 Show")

        show_btn = ttk.Button(setup_card, text="👁 Show", style="Dim.TButton",
                               command=_toggle_key_visibility)
        show_btn.grid(row=1, column=2, padx=(0, 6))

        ttk.Button(setup_card, text="💾 Save Key", style="Green.TButton",
                   command=self._nexoai_save_key).grid(row=1, column=3)

        tk.Label(setup_card,
                 text="Saved locally in nexoai_config.json — entered once, reused on every launch. "
                      "Get a free key at console.groq.com/keys",
                 bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 8), justify="left").grid(
                 row=2, column=0, columnspan=4, sticky="w", pady=(4, 10))

        tk.Label(setup_card, text="Model:", bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI", 9)).grid(row=3, column=0, sticky="w", padx=(0, 8))

        self._nexoai_model_var = tk.StringVar(value=NEXOAI_CONFIG.get("model", NEXOAI_FALLBACK_MODELS[0]))
        self._nexoai_model_combo = ttk.Combobox(
            setup_card, textvariable=self._nexoai_model_var,
            values=NEXOAI_FALLBACK_MODELS, width=32,
            font=("Segoe UI", 9), state="readonly")
        self._nexoai_model_combo.grid(row=3, column=1, sticky="w")
        self._nexoai_model_combo.bind("<<ComboboxSelected>>",
                                       lambda e: self._nexoai_save_model())

        ttk.Button(setup_card, text="🔄 Refresh Models", style="Dim.TButton",
                   command=self._nexoai_refresh_models).grid(row=3, column=2, padx=(6, 0))

        self._nexoai_model_status = tk.Label(setup_card, text="", bg=self.BG2,
                                              fg=self.TEXTDIM, font=("Segoe UI", 8))
        self._nexoai_model_status.grid(row=4, column=0, columnspan=4, sticky="w", pady=(4, 0))

        setup_card.columnconfigure(1, weight=1)

        # ── Chat card ──
        chat_card = ttk.Frame(outer, style="Card.TFrame", padding=14)
        chat_card.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        tk.Label(chat_card, text="Chat",
                 bg=self.BG2, fg=self.ACCENT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))

        # Input row is packed FIRST and anchored to the bottom, so it always
        # stays visible; the chat history frame is packed after and fills
        # whatever space remains above it. (Packing order matters here —
        # an expand=True widget packed first would claim all the space and
        # push a later side="bottom" widget out of view.)
        input_row = tk.Frame(chat_card, bg=self.BG2)
        input_row.pack(side="bottom", fill="x", pady=(8, 0))

        self._nexoai_input_var = tk.StringVar()
        nexoai_entry = ttk.Entry(input_row, textvariable=self._nexoai_input_var,
                                  font=("Segoe UI", 10))
        nexoai_entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 6))
        nexoai_entry.bind("<Return>", lambda e: self._nexoai_send())

        self._nexoai_send_btn = ttk.Button(input_row, text="Send ➤", style="Accent.TButton",
                                            command=self._nexoai_send)
        self._nexoai_send_btn.pack(side="left", padx=(0, 6))

        ttk.Button(input_row, text="🗑 Clear Chat", style="Dim.TButton",
                   command=self._nexoai_clear_chat).pack(side="left")

        chat_frame = tk.Frame(chat_card, bg=self.BORDER, bd=1)
        chat_frame.pack(fill="both", expand=True)
        self._nexoai_chat_view = scrolledtext.ScrolledText(
            chat_frame,
            bg=self.CONSOLE, fg=self.TEXT,
            font=("Segoe UI", 10),
            insertbackground=self.TEXT,
            selectbackground=self.ACCENT,
            relief="flat", bd=0, state="disabled", wrap="word")
        self._nexoai_chat_view.pack(fill="both", expand=True, padx=1, pady=1)
        self._nexoai_chat_view.tag_config("user_tag", foreground=self.ACCENT2, font=("Segoe UI", 10, "bold"))
        self._nexoai_chat_view.tag_config("ai_tag", foreground=self.GREEN, font=("Segoe UI", 10, "bold"))
        self._nexoai_chat_view.tag_config("err_tag", foreground=self.RED)

        self._nexoai_history = []   # list of {"role":.., "content":..} sent to Groq for context
        self._nexoai_busy = False


        # If a key is already saved, quietly refresh the model list in the
        # background so the dropdown reflects what's actually available.
        if NEXOAI_CONFIG.get("groq_api_key"):
            self._nexoai_refresh_models(silent=True)

    def _nexoai_safe_after(self, callback):
        """
        Like self.root.after(0, callback), but tolerates the app having
        already closed. Background NexoAI requests run in daemon threads
        and can finish after the user closes the window / the Tk main
        loop has exited — calling root.after() at that point raises
        RuntimeError: main thread is not in main loop. That's not a real
        bug (there's simply no UI left to update), so we just drop the
        update instead of crashing the thread with a traceback.
        """
        try:
            self.root.after(0, callback)
        except RuntimeError:
            pass

    def _nexoai_append_chat(self, who: str, text: str, tag: str):
        self._nexoai_chat_view.configure(state="normal")
        self._nexoai_chat_view.insert("end", f"{who}: ", tag)
        self._nexoai_chat_view.insert("end", f"{text}\n\n")
        self._nexoai_chat_view.configure(state="disabled")
        self._nexoai_chat_view.see("end")

    def _nexoai_clear_chat(self):
        self._nexoai_history = []
        self._nexoai_chat_view.configure(state="normal")
        self._nexoai_chat_view.delete("1.0", "end")
        self._nexoai_chat_view.configure(state="disabled")

    def _nexoai_save_key(self):
        key = self._nexoai_key_var.get().strip()
        NEXOAI_CONFIG["groq_api_key"] = key
        save_nexoai_config()
        if key:
            messagebox.showinfo("NexoAI", "Groq API key saved. It will be reused automatically next time you open the app.")
            self._nexoai_refresh_models(silent=True)
        else:
            messagebox.showinfo("NexoAI", "API key cleared.")

    def _nexoai_save_model(self):
        NEXOAI_CONFIG["model"] = self._nexoai_model_var.get().strip()
        save_nexoai_config()

    def _nexoai_refresh_models(self, silent: bool = False):
        key = self._nexoai_key_var.get().strip()
        if not silent:
            self._nexoai_model_status.configure(text="Fetching model list...", fg=self.TEXTDIM)

        def _work():
            models = groq_list_models(key)

            def _apply():
                current = self._nexoai_model_var.get()
                self._nexoai_model_combo.configure(values=models)
                if current not in models and models:
                    self._nexoai_model_var.set(models[0])
                    NEXOAI_CONFIG["model"] = models[0]
                    save_nexoai_config()
                if not silent:
                    self._nexoai_model_status.configure(
                        text=f"{len(models)} model(s) available.", fg=self.GREEN)
            self._nexoai_safe_after(_apply)

        threading.Thread(target=_work, daemon=True).start()

    def _nexoai_send(self):
        if self._nexoai_busy:
            return
        text = self._nexoai_input_var.get().strip()
        if not text:
            return

        key = self._nexoai_key_var.get().strip()
        if not key:
            messagebox.showwarning("NexoAI", "Enter and save your Groq API key first.")
            return

        model = self._nexoai_model_var.get().strip() or NEXOAI_FALLBACK_MODELS[0]

        self._nexoai_input_var.set("")
        self._nexoai_append_chat("You", text, "user_tag")
        self._nexoai_history.append({"role": "user", "content": text})

        self._nexoai_busy = True
        self._nexoai_send_btn.configure(state="disabled")

        def _work():
            try:
                messages = [{"role": "system", "content": NEXOAI_CONFIG.get("system_prompt", NEXOAI_CONFIG_DEFAULT_PROMPT)}]
                messages.extend(self._nexoai_history[-20:])   # keep last 20 turns of context
                reply = groq_chat_completion(key, model, messages)
            except Exception as e:
                reply = None
                error = str(e)
            else:
                error = None

            def _apply():
                self._nexoai_busy = False
                self._nexoai_send_btn.configure(state="normal")
                if error:
                    self._nexoai_append_chat("Error", error, "err_tag")
                else:
                    self._nexoai_history.append({"role": "assistant", "content": reply})
                    self._nexoai_append_chat("NexoAI", reply, "ai_tag")
            self._nexoai_safe_after(_apply)

        threading.Thread(target=_work, daemon=True).start()

    def _root_after_reconnect_poll(self):
        """Poll the bot's reconnect failure count and update the status label."""
        def _poll():
            try:
                # Find the current YouTubeChatBot instance via _gui_app
                failures = 0
                if _gui_app and hasattr(_gui_app, '_bot_instance') and _gui_app._bot_instance:
                    failures = getattr(_gui_app._bot_instance, '_reconnect_failures', 0)

                if failures == 0:
                    self._reconn_status_lbl.configure(
                        text="Connected — no failures.", fg=self.GREEN)
                elif failures < RECONNECT_CONFIG.get("notify_threshold", 3):
                    self._reconn_status_lbl.configure(
                        text=f"Reconnecting... ({failures} consecutive failure(s))",
                        fg=self.YELLOW)
                else:
                    max_f = RECONNECT_CONFIG.get("max_failures", 10)
                    self._reconn_status_lbl.configure(
                        text=f"WARNING: {failures} consecutive failure(s)"
                             + (f" — bot stops at {max_f}" if max_f > 0 else " — retrying forever"),
                        fg=self.RED)
            except Exception:
                pass
            self.root.after(3000, _poll)
        self.root.after(3000, _poll)

    def _save_reconnect_config(self):
        for key, var in self._reconn_vars.items():
            try:
                RECONNECT_CONFIG[key] = max(0, int(var.get()))
            except (ValueError, tk.TclError):
                pass
        save_reconnect_config()
        self._clear_dirty(14)
        self._reconn_saved_lbl.configure(
            text=f"Saved — max:{RECONNECT_CONFIG['max_failures']}  "
                 f"base:{RECONNECT_CONFIG['base_delay']}s  "
                 f"max-delay:{RECONNECT_CONFIG['max_delay']}s  "
                 f"notify@:{RECONNECT_CONFIG['notify_threshold']}")
        self._log("[Reconnect] Config saved.")

    # ──────────────── Welcome / User Guide ────────────────
    GUIDE_FLAG_FILE = "guide_seen.flag"

    # ── System resource monitor ──
    def _start_system_monitor(self):
        """
        Periodically refreshes the CPU/RAM usage label in the title bar
        using psutil. Uses root.after() so it runs on Tkinter's own event
        loop — no extra thread needed. Refresh interval is slower in Lite
        Mode to keep background overhead minimal on weaker machines.
        """
        if not _PSUTIL_OK:
            return

        # First call to cpu_percent() with no interval just primes the
        # internal counter and returns 0.0 — call it once up front so the
        # first real reading a moment later is meaningful.
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass

        refresh_ms = 4000 if APP_LITE_MODE else 2000

        def _update_sysmon():
            try:
                cpu_pct = psutil.cpu_percent(interval=None)
                ram = psutil.virtual_memory()
                ram_pct = ram.percent

                # Color-code so a glance at the title bar tells you if
                # something is under real load, without needing to open
                # Task Manager.
                def _color_for(pct):
                    if pct >= 85:
                        return self.RED
                    if pct >= 60:
                        return "#f0c060"
                    return self.TEXTDIM

                cpu_color = _color_for(cpu_pct)
                ram_color = _color_for(ram_pct)

                # Tkinter labels can't mix colors in one widget, so we show
                # the more urgent of the two as the label's color and both
                # numbers together in the text.
                worst_color = cpu_color if cpu_pct >= ram_pct else ram_color
                self._sysmon_label.configure(
                    text=f"🧠 CPU {cpu_pct:.0f}%   💾 RAM {ram_pct:.0f}%",
                    fg=worst_color if (cpu_pct >= 60 or ram_pct >= 60) else self.TEXTDIM,
                )
            except Exception:
                pass
            finally:
                self.root.after(refresh_ms, _update_sysmon)

        self.root.after(500, _update_sysmon)

    # ── Easter eggs ──
    def _on_title_click(self, event=None):
        """
        Counts rapid clicks on the title label. 10 clicks within a few
        seconds triggers a little celebration overlay. The counter resets
        if the person pauses for more than 2 seconds between clicks.
        """
        self._title_click_count += 1

        if self._title_click_reset_job is not None:
            try:
                self.root.after_cancel(self._title_click_reset_job)
            except Exception:
                pass

        if self._title_click_count >= 10:
            self._title_click_count = 0
            self._trigger_easter_egg("clicks")
        else:
            def _reset():
                self._title_click_count = 0
            self._title_click_reset_job = self.root.after(2000, _reset)

    def _setup_konami_code_listener(self):
        """
        Binds a global key listener for the classic Konami Code
        (↑ ↑ ↓ ↓ ← → ← → B A). Matching the full sequence triggers the
        same celebration overlay as the title-click easter egg.
        """
        konami_sequence = [
            "Up", "Up", "Down", "Down",
            "Left", "Right", "Left", "Right",
            "b", "a",
        ]
        self._konami_progress = []

        def _on_key(event):
            # Don't track keystrokes while the user is typing in a text
            # input — avoids both accidental triggers and broken typing
            # flow if arrow keys happen to be used for cursor movement.
            widget_class = event.widget.winfo_class() if event.widget else ""
            if widget_class in ("Entry", "TEntry", "Text", "TCombobox"):
                return

            key = event.keysym
            expected = konami_sequence[len(self._konami_progress)]
            # Letter keys are compared case-insensitively; arrow keys are
            # compared as-is (Tkinter keysyms are already "Up"/"Down"/etc).
            match = (key.lower() == expected.lower()) if len(expected) == 1 else (key == expected)

            if match:
                self._konami_progress.append(key)
                if len(self._konami_progress) == len(konami_sequence):
                    self._konami_progress = []
                    self._trigger_easter_egg("konami")
            else:
                # Allow the sequence to restart from this key if it happens
                # to also be the first key of the sequence.
                self._konami_progress = [key] if key == konami_sequence[0] else []

        self.root.bind_all("<KeyPress>", _on_key)
        self._setup_secret_code_listener()

    def _setup_secret_code_listener(self):
        """
        Tracks keystrokes anywhere in the GUI for the hidden sequence
        "SECRET0091" (case-insensitive). Typing it in full reveals a
        hidden "🎉 Fun" tab next to Reconnect, with a couple of small
        just-for-fun tools (CPS test, typing speed test). Unlike the
        Konami listener, this one still tracks keystrokes while an Entry
        or Text widget has focus, since the whole point is that the user
        can type it anywhere without needing to click away first.
        """
        secret_code = "secret0091"
        self._secret_code_progress = ""

        def _on_key(event):
            char = event.char.lower() if event.char else ""
            if not char or not char.isprintable():
                return

            expected_next = secret_code[len(self._secret_code_progress)]
            if char == expected_next:
                self._secret_code_progress += char
                if self._secret_code_progress == secret_code:
                    self._secret_code_progress = ""
                    self._reveal_fun_tab()
            else:
                # Restart the match from this character if it happens to
                # also be the sequence's first character.
                self._secret_code_progress = char if char == secret_code[0] else ""

        self.root.bind_all("<KeyPress>", _on_key, add="+")

    def _trigger_easter_egg(self, source):
        """
        Plays a short, fun celebration overlay on top of the main window:
        a burst of colorful confetti pieces falling with physics-like
        drift, plus a cheeky congratulatory message and a quick chime.
        Fully driven by root.after() on the main thread — no extra thread
        needed, and no risk of touching Tkinter widgets off the main thread.
        """
        print(f"[EasterEgg] triggered via {source}")

        overlay = tk.Toplevel(self.root)
        overlay.overrideredirect(True)
        overlay.attributes("-topmost", True)
        overlay.attributes("-alpha", 0.0)
        try:
            overlay.attributes("-transparentcolor", "#010101")
            overlay.configure(bg="#010101")
            bg_color = "#010101"
        except Exception:
            # -transparentcolor isn't supported on all platforms; fall back
            # to a solid dark overlay instead of a see-through one.
            overlay.configure(bg="#0f0f1a")
            bg_color = "#0f0f1a"

        import random as _random
        import math as _math

        rw = self.root.winfo_width() or 900
        rh = self.root.winfo_height() or 650
        rx = self.root.winfo_x()
        ry = self.root.winfo_y()
        overlay.geometry(f"{rw}x{rh}+{rx}+{ry}")

        canvas = tk.Canvas(overlay, width=rw, height=rh, bg=bg_color,
                            highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        overlay.attributes("-alpha", 1.0)

        messages = [
            "🎉 You found a secret!",
            "✨ Nice one, explorer!",
            "🎊 Achievement unlocked: Curious Clicker",
            "🥚 Easter egg found!",
        ]
        msg = tk.Label(canvas, text=_random.choice(messages),
                       bg=bg_color, fg="#f0c060",
                       font=("Segoe UI", 18, "bold"))
        msg_window = canvas.create_window(rw // 2, 50, window=msg)

        _play_chime([659.25, 830.61, 987.77, 1318.51], note_duration=0.09, volume=0.22)

        confetti_colors = ["#a684e8", "#3ddc97", "#f0c060", "#ff6b9d", "#4ec5ff"]
        pieces = []
        for _ in range(70):
            x = _random.randint(0, rw)
            y = _random.randint(-rh, 0)
            size = _random.uniform(3, 7)
            color = _random.choice(confetti_colors)
            item = canvas.create_rectangle(x, y, x + size, y + size,
                                            fill=color, outline="")
            pieces.append({
                "item": item, "x": x, "y": y, "size": size,
                "vy": _random.uniform(2.5, 5.5),
                "drift": _random.uniform(-1.5, 1.5),
                "phase": _random.uniform(0, 6.28),
            })

        def _animate(frame=0):
            if frame >= 90 or not overlay.winfo_exists():
                try:
                    overlay.destroy()
                except Exception:
                    pass
                return
            try:
                for p in pieces:
                    p["y"] += p["vy"]
                    p["x"] += p["drift"] + _math.sin(frame * 0.15 + p["phase"]) * 0.8
                    canvas.coords(p["item"], p["x"], p["y"],
                                  p["x"] + p["size"], p["y"] + p["size"])
                    if p["y"] > rh:
                        p["y"] = _random.randint(-40, -10)
                        p["x"] = _random.randint(0, rw)
                # Fade the message out over the last ~20 frames.
                if frame > 65:
                    fade = max(0.0, 1.0 - (frame - 65) / 25)
                    color = self._lerp_color_static(bg_color, "#f0c060", fade)
                    canvas.itemconfigure(msg_window, state="normal")
                    msg.configure(fg=color)
                self.root.after(16, lambda: _animate(frame + 1))
            except Exception:
                try:
                    overlay.destroy()
                except Exception:
                    pass

        _animate()

    @staticmethod
    def _lerp_color_static(c1, c2, t):
        """Standalone hex color interpolation helper, used by the easter egg overlay."""
        r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
        r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _reveal_fun_tab(self, celebrate=True):
        """
        Inserts a hidden "🎉 Fun" tab right before the Reconnect tab, the
        first time the secret code is typed. Safe to trigger more than
        once — does nothing if the tab already exists. Pass
        celebrate=False when silently re-adding the tab after a theme
        rebuild, so the confetti/chime only ever plays once per real
        discovery.
        """
        if getattr(self, "_fun_tab_revealed", False):
            return
        self._fun_tab_revealed = True

        print("[EasterEgg] secret code entered — revealing Fun tab")

        fun_tab = ttk.Frame(self.nb)
        try:
            reconnect_idx = self.nb.index(self._fun_tab_anchor)
        except Exception:
            reconnect_idx = "end"
        self.nb.insert(reconnect_idx, fun_tab, text="🎉 Fun")
        self._build_fun_tab(fun_tab)

        if celebrate:
            # Small celebratory flourish so it's obvious something happened,
            # then jump straight to the new tab.
            _play_chime([523.25, 659.25, 783.99, 1046.50], note_duration=0.1, volume=0.22)
            self.nb.select(fun_tab)
            self._trigger_easter_egg("secret_code")

    def _build_fun_tab(self, parent):
        """
        Builds the hidden Fun tab as its own small notebook of just-for-fun
        tools: skill tests (typing speed + CPS), a reaction time test, a
        Snake mini-game, and a random tools panel (dice/coin flip/name
        picker). Everything here is purely local — nothing is saved or
        sent anywhere.
        """
        outer = tk.Frame(parent, bg=self.BG)
        outer.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(outer, text="🎉 Just for Fun",
                 bg=self.BG, fg=self.TEXT,
                 font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(0, 12))

        fun_nb = ttk.Notebook(outer)
        fun_nb.pack(fill="both", expand=True)

        skills_tab   = ttk.Frame(fun_nb)
        reaction_tab = ttk.Frame(fun_nb)
        snake_tab    = ttk.Frame(fun_nb)
        random_tab   = ttk.Frame(fun_nb)

        fun_nb.add(skills_tab,   text="⌨ Skill Tests")
        fun_nb.add(reaction_tab, text="🎯 Reaction Time")
        fun_nb.add(snake_tab,    text="🐍 Snake")
        fun_nb.add(random_tab,   text="🎲 Random Tools")

        cols = tk.Frame(skills_tab, bg=self.BG)
        cols.pack(fill="both", expand=True, padx=4, pady=4)
        self._build_typing_test_panel(cols)
        self._build_cps_test_panel(cols)

        self._build_reaction_test_panel(reaction_tab)
        self._build_snake_game_panel(snake_tab)
        self._build_random_tools_panel(random_tab)

    # ── Typing Speed Test ──
    def _build_typing_test_panel(self, cols):
        """
        Left-hand panel: a duration picker list (like the reference
        screenshot) plus a live test area that streams a paragraph of
        random words, coloring each one green (correct), red-strikethrough
        (wrong), or dim gray (not yet typed) as the user types, with a
        countdown timer that starts on the first keystroke.
        """
        left = tk.Frame(cols, bg=self.BG)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))

        # Word pool the test paragraph is randomly generated from.
        word_pool = (
            "the be to of and a in that have I it for not on with he as you "
            "do at this but his by from they we say her she or an will my "
            "one all would there their what so up out if about who get which "
            "go me when make can like time no just him know take people into "
            "year your good some could them see other than then now look "
            "only come its over think also back after use two how our work "
            "first well way even new want because any these give day most us "
            "gained moments fervor eyes success determination influence "
            "community investors sheer money backgrounds dreamer young armed "
            "family venture together sought early influence household"
        ).split()

        durations = [
            ("Typing Speed Test", 15),   # quick default test
            ("1 Minute Typing Test", 60),
            ("2 Minute Typing Test", 120),
            ("5 Minute Typing Test", 300),
            ("7 Minute Typing Test", 420),
            ("10 Minute Typing Test", 600),
            ("15 Minute Typing Test", 900),
        ]

        # ── Collapsible duration picker (left column) ──
        picker_frame = tk.LabelFrame(
            left, text="  ⌨ Typing Test  ",
            bg=self.BG2, fg=self.TEXT, font=("Segoe UI", 10, "bold"),
            labelanchor="n", bd=1, relief="solid")
        picker_frame.pack(fill="both", expand=True)

        picker_buttons = {}

        def _make_picker_row(label_text, seconds):
            row = tk.Button(
                picker_frame, text=f"⌨  {label_text}",
                bg=self.BG2, fg=self.ACCENT2, activebackground=self.BG3,
                activeforeground=self.ACCENT2, relief="flat", bd=0,
                anchor="w", font=("Segoe UI", 9, "bold"), padx=14, pady=8,
                cursor="hand2",
                command=lambda: _start_test(seconds),
            )
            row.pack(fill="x", padx=6, pady=2)
            picker_buttons[seconds] = row

        for label_text, seconds in durations:
            _make_picker_row(label_text, seconds)

        # ── Test area (right side of this panel) ──
        test_frame = tk.Frame(left, bg=self.BG2)
        # not packed until a duration is picked — see _start_test

        header_row = tk.Frame(test_frame, bg=self.BG2)
        header_row.pack(fill="x", padx=14, pady=(12, 6))

        test_title_label = tk.Label(header_row, text="",
                                     bg=self.BG2, fg=self.TEXT,
                                     font=("Segoe UI", 12, "bold"))
        test_title_label.pack(side="left")

        timer_frame = tk.Frame(header_row, bg=self.BG2)
        timer_frame.pack(side="right")
        tk.Label(timer_frame, text="🕐 Timer:", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 9)).pack(side="left", padx=(0, 4))
        timer_label = tk.Label(timer_frame, text="0s", bg=self.BG2, fg=self.TEXT,
                                font=("Segoe UI", 9, "bold"))
        timer_label.pack(side="left")

        text_display = tk.Text(
            test_frame, bg=self.BG2, fg=self.TEXTDIM,
            font=("Consolas", 13), wrap="word", height=8,
            relief="flat", bd=0, cursor="arrow", padx=14, pady=10,
            state="disabled", highlightthickness=0)
        text_display.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        # Tag styles for word coloring.
        text_display.tag_configure("untyped", foreground=self.TEXTDIM)
        text_display.tag_configure("current_untyped", foreground=self.TEXT,
                                    underline=True)
        text_display.tag_configure("correct", foreground=self.GREEN)
        text_display.tag_configure("wrong", foreground=self.RED,
                                    overstrike=True)
        text_display.tag_configure("cursor", foreground=self.ACCENT2)

        result_label = tk.Label(test_frame, text="",
                                 bg=self.BG2, fg=self.ACCENT2,
                                 font=("Segoe UI", 13, "bold"))
        result_label.pack(pady=(0, 4))

        # Hidden entry that actually captures keystrokes — the visible
        # Text widget is read-only and only used for rendering. Since the
        # Text widget (and the frame around it) can still steal focus when
        # clicked even while disabled, clicking anywhere in the test area
        # sends focus back to this hidden entry so typing never "goes
        # nowhere".
        capture_entry = tk.Entry(test_frame)
        # Placed off-screen; still receives focus and key events normally.
        capture_entry.place(x=-500, y=-500, width=1, height=1)

        def _refocus_capture(event=None):
            if typing_state["running"]:
                capture_entry.focus_set()

        text_display.bind("<Button-1>", _refocus_capture)
        test_frame.bind("<Button-1>", _refocus_capture)
        header_row.bind("<Button-1>", _refocus_capture)

        typing_state = {
            "words": [], "target_text": "", "duration": 15,
            "start_time": None, "running": False, "timer_job": None,
            "current_word_idx": 0,
        }

        def _generate_paragraph(min_words=60):
            import random as _random
            words = [_random.choice(word_pool) for _ in range(min_words)]
            return words

        def _render_words(typed_text):
            """
            Re-renders the whole word list with correct/wrong/untyped
            coloring. The word currently being typed gets character-level
            coloring (each typed character shown correct/wrong) plus an
            underline and a blinking-style cursor bar at the exact typing
            position, so the user always has a clear "you are here" marker.
            """
            text_display.configure(state="normal")
            text_display.delete("1.0", "end")

            typed_words = typed_text.split(" ")
            words = typing_state["words"]
            current_word_pos = len(typed_words) - 1

            for i, word in enumerate(words):
                if i < current_word_pos:
                    # A fully committed word (user has moved past it).
                    tag = "correct" if typed_words[i] == word else "wrong"
                    text_display.insert("end", word, tag)
                elif i == current_word_pos:
                    # The word currently being typed — render character by
                    # character so correct/wrong letters are visible as you
                    # type, with a cursor bar right after the last typed
                    # character.
                    current_typed = typed_words[i]
                    overlap = min(len(current_typed), len(word))

                    for ci in range(overlap):
                        tag = "correct" if current_typed[ci] == word[ci] else "wrong"
                        text_display.insert("end", word[ci], tag)

                    # Cursor bar sits right where typing currently is.
                    text_display.insert("end", "\u2502", "cursor")

                    if len(word) > overlap:
                        # Remaining letters of the word not yet typed.
                        text_display.insert("end", word[overlap:], "current_untyped")
                    if len(current_typed) > overlap:
                        # A typo that overshoots the word's length still
                        # shows up, marked wrong, after the cursor.
                        text_display.insert("end", current_typed[overlap:], "wrong")
                else:
                    text_display.insert("end", word, "untyped")
                if i < len(words) - 1:
                    text_display.insert("end", " ")

            text_display.configure(state="disabled")
            typing_state["current_word_idx"] = max(0, current_word_pos)

            # Auto-scroll so the current word stays visible as the
            # paragraph grows (relevant for the longer 10-15 minute tests).
            text_display.see("end")

        def _timer_tick():
            if not typing_state["running"]:
                return
            elapsed = time.time() - typing_state["start_time"]
            remaining = typing_state["duration"] - elapsed
            if remaining <= 0:
                _finish_test()
                return
            timer_label.configure(text=f"{remaining:.0f}s")
            typing_state["timer_job"] = self.root.after(200, _timer_tick)

        def _finish_test():
            typing_state["running"] = False
            if typing_state["timer_job"] is not None:
                try:
                    self.root.after_cancel(typing_state["timer_job"])
                except Exception:
                    pass
            timer_label.configure(text="0s")

            typed_text = capture_entry.get()
            typed_words = typed_text.split(" ")
            words = typing_state["words"]
            correct_words = sum(
                1 for i, w in enumerate(typed_words)
                if i < len(words) and w == words[i]
            )
            elapsed_minutes = typing_state["duration"] / 60
            wpm = correct_words / max(elapsed_minutes, 1 / 60)
            accuracy = (correct_words / max(1, len(typed_words))) * 100

            result_label.configure(
                text=f"🎉 {wpm:.0f} WPM   •   {accuracy:.0f}% accuracy")
            capture_entry.configure(state="disabled")
            _play_chime([523.25, 659.25, 783.99], note_duration=0.1, volume=0.2)

        def _on_typed(event=None):
            if not typing_state["running"]:
                return

            if typing_state["start_time"] is None:
                typing_state["start_time"] = time.time()
                _timer_tick()

            typed_text = capture_entry.get()
            _render_words(typed_text)

            # Once every generated word has been passed, extend with more
            # random words so long tests (10-15 min) never run out.
            typed_word_count = len(typed_text.split(" "))
            if typed_word_count >= len(typing_state["words"]) - 5:
                typing_state["words"].extend(_generate_paragraph(40))

        def _start_test(seconds):
            picker_frame.pack_forget()
            test_frame.pack(fill="both", expand=True)

            duration_label = next((d[0] for d in durations if d[1] == seconds),
                                   "Typing Test")
            test_title_label.configure(text=duration_label)
            timer_label.configure(text=f"{seconds}s")
            result_label.configure(text="")

            typing_state["words"] = _generate_paragraph(80)
            typing_state["duration"] = seconds
            typing_state["start_time"] = None
            typing_state["running"] = True

            capture_entry.configure(state="normal")
            capture_entry.delete(0, "end")
            _render_words("")
            capture_entry.focus_set()

        def _reset_test():
            if typing_state["timer_job"] is not None:
                try:
                    self.root.after_cancel(typing_state["timer_job"])
                except Exception:
                    pass
            test_frame.pack_forget()
            picker_frame.pack(fill="both", expand=True)
            typing_state["running"] = False

        capture_entry.bind("<KeyRelease>", _on_typed)
        capture_entry.bind("<Return>", lambda e: "break")

        back_btn = tk.Button(
            test_frame, text="↺ Choose another test", bg=self.BG3, fg=self.TEXT,
            activebackground=self.ACCENT, activeforeground="#fff",
            relief="flat", bd=0, font=("Segoe UI", 9, "bold"),
            cursor="hand2", command=_reset_test)
        back_btn.pack(pady=(0, 10))

    # ── CPS Test ──
    def _build_cps_test_panel(self, cols):
        """
        Right-hand panel: a CPS (clicks-per-second) test with a selectable
        duration. Once the timer runs out, the click button is disabled
        for 3 seconds to prevent an accidental extra click from starting a
        new run immediately.
        """
        cps_frame = tk.LabelFrame(cols, text="  🖱 CPS Test (Clicks Per Second)  ",
                                   bg=self.BG2, fg=self.TEXT,
                                   font=("Segoe UI", 10, "bold"),
                                   labelanchor="n", bd=1, relief="solid")
        cps_frame.pack(side="left", fill="both", expand=True, padx=(8, 0))

        tk.Label(cps_frame, text="Choose a duration, then click as fast as you can.",
                 bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 9), wraplength=220,
                 justify="center").pack(pady=(14, 6))

        # ── Duration selector ──
        duration_var = tk.IntVar(value=5)
        duration_row = tk.Frame(cps_frame, bg=self.BG2)
        duration_row.pack(pady=(0, 10))

        cps_duration_options = [1, 3, 5, 10, 30, 60]
        duration_buttons = {}

        def _select_duration(seconds):
            duration_var.set(seconds)
            for s, btn in duration_buttons.items():
                if s == seconds:
                    btn.configure(bg=self.ACCENT, fg="#ffffff")
                else:
                    btn.configure(bg=self.BG3, fg=self.TEXTDIM)

        for seconds in cps_duration_options:
            btn = tk.Button(
                duration_row, text=f"{seconds}s",
                bg=self.BG3, fg=self.TEXTDIM,
                activebackground=self.ACCENT, activeforeground="#ffffff",
                relief="flat", bd=0, font=("Segoe UI", 9, "bold"),
                width=4, cursor="hand2",
                command=lambda s=seconds: _select_duration(s),
            )
            btn.pack(side="left", padx=2)
            duration_buttons[seconds] = btn
        _select_duration(5)

        cps_result_label = tk.Label(cps_frame, text="Ready",
                                     bg=self.BG2, fg=self.ACCENT2,
                                     font=("Segoe UI", 20, "bold"))
        cps_result_label.pack(pady=(0, 8))

        cps_state = {"clicks": 0, "running": False, "end_time": 0.0, "locked": False}

        def _cps_tick():
            if not cps_state["running"]:
                return
            remaining = cps_state["end_time"] - time.time()
            if remaining <= 0:
                cps_state["running"] = False
                elapsed = duration_var.get()
                cps = cps_state["clicks"] / elapsed
                cps_result_label.configure(
                    text=f"{cps:.2f} CPS", fg=self.GREEN)
                _play_chime([523.25, 659.25, 783.99], note_duration=0.1, volume=0.2)
                _lock_button_briefly()
                return
            cps_result_label.configure(
                text=f"{cps_state['clicks']} clicks — {remaining:0.1f}s left",
                fg=self.ACCENT2)
            self.root.after(50, _cps_tick)

        def _lock_button_briefly(seconds=3):
            """
            Disables the click button for a few seconds after a test ends,
            so an accidental extra click right at 0s doesn't immediately
            start a new run.
            """
            cps_state["locked"] = True
            cps_button.configure(state="disabled")

            def _tick_lock(remaining):
                if remaining <= 0:
                    cps_state["locked"] = False
                    cps_button.configure(
                        text="Click to start!", state="normal")
                    for btn in duration_buttons.values():
                        btn.configure(state="normal")
                    return
                cps_button.configure(text=f"Wait {remaining}s...")
                self.root.after(1000, lambda: _tick_lock(remaining - 1))

            _tick_lock(seconds)

        def _cps_click():
            if cps_state["locked"]:
                return
            if not cps_state["running"]:
                cps_state["clicks"] = 0
                cps_state["running"] = True
                cps_state["end_time"] = time.time() + duration_var.get()
                cps_button.configure(text="CLICK!")
                for btn in duration_buttons.values():
                    btn.configure(state="disabled")
                _cps_tick()
            else:
                cps_state["clicks"] += 1

        cps_button = tk.Button(
            cps_frame, text="Click to start!",
            bg=self.ACCENT, fg="#ffffff", activebackground=self.ACCENT2,
            activeforeground="#ffffff", relief="flat", bd=0,
            font=("Segoe UI", 11, "bold"), width=18, height=3,
            cursor="hand2", command=_cps_click,
        )
        cps_button.pack(pady=(0, 16))

    # ── Reaction Time Test ──
    def _build_reaction_test_panel(self, parent):
        """
        Classic reaction time test: wait for the box to turn green, then
        click as fast as possible. Clicking too early (while still red)
        is called out and the round restarts. Keeps the best time across
        rounds for the current session.
        """
        import random as _random

        wrap = tk.Frame(parent, bg=self.BG)
        wrap.pack(fill="both", expand=True, padx=20, pady=20)

        tk.Label(wrap, text="Wait for the box to turn green, then click it as fast as you can.",
                 bg=self.BG, fg=self.TEXTDIM, font=("Segoe UI", 9)).pack(pady=(0, 14))

        state = {"phase": "idle", "wait_job": None, "start_time": 0.0, "best_ms": None}

        box = tk.Label(wrap, text="Click to start", bg=self.BG3, fg=self.TEXT,
                        font=("Segoe UI", 14, "bold"), width=32, height=8,
                        cursor="hand2")
        box.pack(pady=(0, 12))

        result_label = tk.Label(wrap, text="Best: —", bg=self.BG, fg=self.ACCENT2,
                                 font=("Segoe UI", 11, "bold"))
        result_label.pack()

        def _arm_round():
            state["phase"] = "waiting"
            box.configure(bg=self.RED, text="Wait for green...")
            delay_ms = _random.randint(1500, 4000)

            def _go_green():
                state["phase"] = "ready"
                state["start_time"] = time.time()
                box.configure(bg=self.GREEN, text="CLICK NOW!")

            state["wait_job"] = self.root.after(delay_ms, _go_green)

        def _on_box_click(event=None):
            phase = state["phase"]
            if phase == "idle":
                _arm_round()
            elif phase == "waiting":
                # Clicked too early — penalize and restart.
                if state["wait_job"] is not None:
                    try:
                        self.root.after_cancel(state["wait_job"])
                    except Exception:
                        pass
                box.configure(bg=self.RED, text="Too soon! Click to try again.")
                state["phase"] = "idle"
            elif phase == "ready":
                elapsed_ms = (time.time() - state["start_time"]) * 1000
                if state["best_ms"] is None or elapsed_ms < state["best_ms"]:
                    state["best_ms"] = elapsed_ms
                    result_label.configure(text=f"Best: {elapsed_ms:.0f} ms 🎉")
                else:
                    result_label.configure(text=f"Best: {state['best_ms']:.0f} ms")
                box.configure(bg=self.BG3, text=f"{elapsed_ms:.0f} ms — click to try again")
                state["phase"] = "idle"

        box.bind("<Button-1>", _on_box_click)

    # ── Snake Mini-Game ──
    def _build_snake_game_panel(self, parent):
        """
        A small classic Snake game rendered on a Canvas grid. Arrow keys
        change direction; the snake grows each time it eats a piece of
        food, and the game ends on a wall or self collision. Speed
        increases slightly as the score grows. Purely local — no saving,
        no networking.
        """
        import random as _random

        wrap = tk.Frame(parent, bg=self.BG)
        wrap.pack(fill="both", expand=True, padx=20, pady=20)

        GRID = 18
        CELL = 20
        CANVAS_SIZE = GRID * CELL

        top_row = tk.Frame(wrap, bg=self.BG)
        top_row.pack(fill="x", pady=(0, 8))
        score_label = tk.Label(top_row, text="Score: 0", bg=self.BG, fg=self.TEXT,
                                font=("Segoe UI", 11, "bold"))
        score_label.pack(side="left")
        best_label = tk.Label(top_row, text="Best: 0", bg=self.BG, fg=self.TEXTDIM,
                               font=("Segoe UI", 10))
        best_label.pack(side="right")

        canvas = tk.Canvas(wrap, width=CANVAS_SIZE, height=CANVAS_SIZE,
                            bg=self.BG2, highlightthickness=1,
                            highlightbackground=self.BORDER)
        canvas.pack()

        hint_label = tk.Label(wrap, text="Click the board, then use arrow keys. Space to restart.",
                               bg=self.BG, fg=self.TEXTDIM, font=("Segoe UI", 8))
        hint_label.pack(pady=(6, 0))

        state = {
            "snake": [(9, 9), (8, 9), (7, 9)],
            "direction": (1, 0),
            "next_direction": (1, 0),
            "food": (12, 9),
            "score": 0,
            "best": 0,
            "running": False,
            "job": None,
        }

        def _random_food():
            while True:
                pos = (_random.randint(0, GRID - 1), _random.randint(0, GRID - 1))
                if pos not in state["snake"]:
                    return pos

        def _draw():
            canvas.delete("all")
            for i, (x, y) in enumerate(state["snake"]):
                color = self.GREEN if i == 0 else self.ACCENT2
                canvas.create_rectangle(
                    x * CELL + 1, y * CELL + 1, x * CELL + CELL - 1, y * CELL + CELL - 1,
                    fill=color, outline="")
            fx, fy = state["food"]
            canvas.create_oval(
                fx * CELL + 3, fy * CELL + 3, fx * CELL + CELL - 3, fy * CELL + CELL - 3,
                fill="#f0c060", outline="")

        def _game_over():
            state["running"] = False
            if state["job"] is not None:
                try:
                    self.root.after_cancel(state["job"])
                except Exception:
                    pass
            canvas.create_text(
                CANVAS_SIZE // 2, CANVAS_SIZE // 2,
                text="Game Over\nSpace to restart", fill=self.RED,
                font=("Segoe UI", 13, "bold"), justify="center")
            _play_chime([392.00, 329.63, 261.63], note_duration=0.12, volume=0.2)

        def _tick():
            if not state["running"]:
                return
            state["direction"] = state["next_direction"]
            dx, dy = state["direction"]
            hx, hy = state["snake"][0]
            new_head = (hx + dx, hy + dy)

            if (not (0 <= new_head[0] < GRID) or not (0 <= new_head[1] < GRID)
                    or new_head in state["snake"]):
                _game_over()
                return

            state["snake"].insert(0, new_head)
            if new_head == state["food"]:
                state["score"] += 1
                score_label.configure(text=f"Score: {state['score']}")
                state["food"] = _random_food()
                _play_chime([523.25, 659.25], note_duration=0.06, volume=0.15)
            else:
                state["snake"].pop()

            _draw()
            speed_ms = max(60, 140 - state["score"] * 3)
            state["job"] = self.root.after(speed_ms, _tick)

        def _start_game():
            state["snake"] = [(9, 9), (8, 9), (7, 9)]
            state["direction"] = (1, 0)
            state["next_direction"] = (1, 0)
            state["food"] = _random_food()
            state["score"] = 0
            score_label.configure(text="Score: 0")
            state["running"] = True
            _draw()
            if state["job"] is not None:
                try:
                    self.root.after_cancel(state["job"])
                except Exception:
                    pass
            state["job"] = self.root.after(140, _tick)

        def _on_key(event):
            dx, dy = state["direction"]
            key = event.keysym
            if key == "space" or key == "Return":
                if state["score"] > state["best"]:
                    state["best"] = state["score"]
                    best_label.configure(text=f"Best: {state['best']}")
                _start_game()
                return
            new_dir = {
                "Up": (0, -1), "Down": (0, 1),
                "Left": (-1, 0), "Right": (1, 0),
            }.get(key)
            if new_dir is None:
                return
            # Prevent reversing directly into yourself.
            if (new_dir[0], new_dir[1]) != (-dx, -dy):
                state["next_direction"] = new_dir

        def _on_canvas_click(event=None):
            canvas.focus_set()
            if not state["running"] and state["job"] is None:
                _start_game()

        canvas.bind("<Button-1>", _on_canvas_click)
        canvas.bind("<KeyPress>", _on_key)
        canvas.focus_set()

        _draw()
        canvas.create_text(
            CANVAS_SIZE // 2, CANVAS_SIZE // 2,
            text="Click to start\nArrow keys to move", fill=self.TEXTDIM,
            font=("Segoe UI", 11, "bold"), justify="center")

    # ── Random Tools (dice, coin flip, name picker) ──
    def _build_random_tools_panel(self, parent):
        """
        A few small randomness-based tools: dice roller, coin flip, and a
        random name/option picker for deciding between choices — handy for
        stream giveaways or picking who goes first in something.
        """
        import random as _random

        wrap = tk.Frame(parent, bg=self.BG)
        wrap.pack(fill="both", expand=True, padx=16, pady=16)

        cols = tk.Frame(wrap, bg=self.BG)
        cols.pack(fill="both", expand=True)

        # ── Dice Roller ──
        dice_frame = tk.LabelFrame(cols, text="  🎲 Dice Roller  ",
                                    bg=self.BG2, fg=self.TEXT,
                                    font=("Segoe UI", 10, "bold"),
                                    labelanchor="n", bd=1, relief="solid")
        dice_frame.pack(side="left", fill="both", expand=True, padx=(0, 6))

        dice_result = tk.Label(dice_frame, text="🎲", bg=self.BG2, fg=self.TEXT,
                                font=("Segoe UI", 36))
        dice_result.pack(pady=(16, 4))

        dice_sides_var = tk.IntVar(value=6)
        dice_row = tk.Frame(dice_frame, bg=self.BG2)
        dice_row.pack(pady=(0, 8))
        for sides in (4, 6, 8, 10, 12, 20):
            tk.Radiobutton(
                dice_row, text=f"d{sides}", variable=dice_sides_var, value=sides,
                bg=self.BG2, fg=self.TEXTDIM, selectcolor=self.BG3,
                activebackground=self.BG2, font=("Segoe UI", 8),
            ).pack(side="left", padx=2)

        def _roll_dice():
            result = _random.randint(1, dice_sides_var.get())
            dice_result.configure(text=str(result))
            _play_chime([440.00, 554.37], note_duration=0.07, volume=0.15)

        tk.Button(dice_frame, text="Roll", bg=self.ACCENT, fg="#ffffff",
                  activebackground=self.ACCENT2, activeforeground="#ffffff",
                  relief="flat", bd=0, font=("Segoe UI", 10, "bold"),
                  width=14, cursor="hand2", command=_roll_dice,
                  ).pack(pady=(0, 16))

        # ── Coin Flip ──
        coin_frame = tk.LabelFrame(cols, text="  🪙 Coin Flip  ",
                                    bg=self.BG2, fg=self.TEXT,
                                    font=("Segoe UI", 10, "bold"),
                                    labelanchor="n", bd=1, relief="solid")
        coin_frame.pack(side="left", fill="both", expand=True, padx=(6, 6))

        coin_result = tk.Label(coin_frame, text="🪙", bg=self.BG2, fg=self.TEXT,
                                font=("Segoe UI", 36))
        coin_result.pack(pady=(16, 8))

        coin_text_label = tk.Label(coin_frame, text="Flip to decide!",
                                    bg=self.BG2, fg=self.TEXTDIM,
                                    font=("Segoe UI", 10))
        coin_text_label.pack(pady=(0, 8))

        def _flip_coin():
            outcome = _random.choice(["Heads", "Tails"])
            coin_text_label.configure(text=outcome, fg=self.GREEN)
            _play_chime([659.25, 523.25], note_duration=0.08, volume=0.15)

        tk.Button(coin_frame, text="Flip", bg=self.ACCENT, fg="#ffffff",
                  activebackground=self.ACCENT2, activeforeground="#ffffff",
                  relief="flat", bd=0, font=("Segoe UI", 10, "bold"),
                  width=14, cursor="hand2", command=_flip_coin,
                  ).pack(pady=(0, 16))

        # ── Random Picker ──
        picker_frame = tk.LabelFrame(cols, text="  🎯 Random Picker  ",
                                      bg=self.BG2, fg=self.TEXT,
                                      font=("Segoe UI", 10, "bold"),
                                      labelanchor="n", bd=1, relief="solid")
        picker_frame.pack(side="left", fill="both", expand=True, padx=(6, 0))

        tk.Label(picker_frame, text="One name/option per line:",
                 bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 8)).pack(pady=(12, 4))

        picker_text = tk.Text(picker_frame, bg=self.BG3, fg=self.TEXT,
                               font=("Segoe UI", 9), height=5, width=24,
                               insertbackground=self.TEXT, relief="flat", bd=0)
        picker_text.pack(padx=10, pady=(0, 8))

        picker_result = tk.Label(picker_frame, text="",
                                  bg=self.BG2, fg=self.GREEN,
                                  font=("Segoe UI", 12, "bold"),
                                  wraplength=200)
        picker_result.pack(pady=(0, 4))

        def _pick_random():
            options = [line.strip() for line in picker_text.get("1.0", "end").split("\n")
                       if line.strip()]
            if not options:
                picker_result.configure(text="Add some options first!", fg=self.RED)
                return
            winner = _random.choice(options)
            picker_result.configure(text=f"🎉 {winner}", fg=self.GREEN)
            _play_chime([523.25, 659.25, 783.99], note_duration=0.09, volume=0.2)

        tk.Button(picker_frame, text="Pick Random", bg=self.ACCENT, fg="#ffffff",
                  activebackground=self.ACCENT2, activeforeground="#ffffff",
                  relief="flat", bd=0, font=("Segoe UI", 10, "bold"),
                  width=16, cursor="hand2", command=_pick_random,
                  ).pack(pady=(0, 16))

    def show_welcome_guide(self, force=False):
        if not force and os.path.exists(self.GUIDE_FLAG_FILE):
            return

        W, H = 800, 560
        dlg = tk.Toplevel(self.root)
        dlg.title("📖  Nexovative Control Center — User Guide")
        dlg.configure(bg=self.BG)
        dlg.resizable(False, False)
        dlg.grab_set()
        self.root.update_idletasks()
        rx = self.root.winfo_x() + (self.root.winfo_width()  - W) // 2
        ry = self.root.winfo_y() + (self.root.winfo_height() - H) // 2
        dlg.geometry(f"{W}x{H}+{rx}+{ry}")

        # Header
        hdr = tk.Frame(dlg, bg=self.ACCENT, height=54)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="📖  Nexovative Control Center — User Guide",
                 bg=self.ACCENT, fg="#ffffff",
                 font=("Segoe UI", 13, "bold")).pack(side="left", padx=18, pady=10)
        tk.Label(hdr, text=f"v{VERSION}",
                 bg=self.ACCENT, fg="#ccbbee",
                 font=("Segoe UI", 9)).pack(side="right", padx=18)

        # Body
        body = tk.Frame(dlg, bg=self.BG)
        body.pack(fill="both", expand=True)

        # Sidebar — scrollable canvas so all chapters fit
        sidebar_outer = tk.Frame(body, bg=self.BG2, width=210)
        sidebar_outer.pack(side="left", fill="y")
        sidebar_outer.pack_propagate(False)

        tk.Label(sidebar_outer, text="CHAPTERS", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 7, "bold")).pack(anchor="w", padx=12, pady=(10, 2))

        sb_canvas = tk.Canvas(sidebar_outer, bg=self.BG2, highlightthickness=0)
        sb_scroll = ttk.Scrollbar(sidebar_outer, orient="vertical", command=sb_canvas.yview)
        sb_canvas.configure(yscrollcommand=sb_scroll.set)
        sb_scroll.pack(side="right", fill="y")
        sb_canvas.pack(side="left", fill="both", expand=True)

        sidebar = tk.Frame(sb_canvas, bg=self.BG2)
        sidebar_window = sb_canvas.create_window((0, 0), window=sidebar, anchor="nw")

        def _on_sidebar_configure(event):
            sb_canvas.configure(scrollregion=sb_canvas.bbox("all"))
            sb_canvas.itemconfig(sidebar_window, width=event.width)

        sidebar.bind("<Configure>", lambda e: sb_canvas.configure(
            scrollregion=sb_canvas.bbox("all")))
        sb_canvas.bind("<Configure>", _on_sidebar_configure)
        sb_canvas.bind("<MouseWheel>",
            lambda e: sb_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        sidebar.bind("<MouseWheel>",
            lambda e: sb_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        # Right text area
        right_pane = tk.Frame(body, bg=self.BG)
        right_pane.pack(side="left", fill="both", expand=True)
        txt_frame = tk.Frame(right_pane, bg=self.BORDER, bd=1)
        txt_frame.pack(fill="both", expand=True, padx=10, pady=10)
        txt = tk.Text(txt_frame, bg=self.BG3, fg=self.TEXT,
                      font=("Segoe UI", 10), wrap="word",
                      relief="flat", bd=0, padx=16, pady=12,
                      state="disabled", cursor="arrow",
                      selectbackground=self.ACCENT)
        sb = ttk.Scrollbar(txt_frame, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(fill="both", expand=True)

        # Text tags
        txt.tag_configure("h1",   font=("Segoe UI", 15, "bold"), foreground=self.ACCENT2,  spacing1=4,  spacing3=6)
        txt.tag_configure("h2",   font=("Segoe UI", 11, "bold"), foreground=self.YELLOW,   spacing1=12, spacing3=3)
        txt.tag_configure("body", font=("Segoe UI", 10),          foreground=self.TEXT,     spacing1=2,  lmargin1=4, lmargin2=4)
        txt.tag_configure("code", font=("Consolas", 9),           foreground=self.GREEN,    background=self.BG2, spacing1=1, lmargin1=16, lmargin2=16)
        txt.tag_configure("tip",  font=("Segoe UI", 9, "italic"), foreground=self.TEXTDIM,  spacing1=3,  lmargin1=4)

        CHAPTERS = [
            ("🚀  Getting Started", [
                ("h1",   "🚀  Getting Started"),
                ("body", "Welcome to Nexovative Control Center! This guide explains every feature so you can hit the ground running."),
                ("body", "You're running in Lite Mode — tabs other than Main, VM, and Real PC load the first time you click on them, and background refresh happens less often, to keep RAM/CPU usage lower on older computers." if APP_LITE_MODE else ""),
                ("h2",   "First-time setup"),
                ("body", "1.  Paste your YouTube Video ID into the Main tab."),
                ("body", "    e.g. if your URL is  youtube.com/watch?v=abc123XYZ  →  enter  abc123XYZ"),
                ("code", "  YouTube Video ID  →  abc123XYZ"),
                ("body", "2.  Pick your VirtualBox VM from the dropdown (click 🔄 Refresh if it is empty)."),
                ("body", "3.  Click  ▶ Start Bot  — the bot connects to chat and starts listening."),
                ("h2",   "Stopping the bot"),
                ("body", "Press  ⏹ Stop Bot.  The VM keeps running; only the chat listener stops."),
                ("h2",   "Minimize to tray"),
                ("body", "Click  📌 Minimize to Tray,  or close the window and choose Yes. The bot keeps running in the background.  Right-click the tray icon to restore or fully exit."),
                ("h2",   "Auto-Start Watchdog"),
                ("body", "Check  Auto-Start Watchdog  on the Main tab. If the VM crashes or powers off, the bot restarts it automatically within 10 seconds."),
            ]),
            ("⌨️  Chat Commands", [
                ("h1",   "⌨️  Chat Commands"),
                ("body", "Viewers type commands in your live chat. Every command starts with  !"),
                ("h2",   "Keyboard"),
                ("code", "  !type hello         →  types  hello  into the VM"),
                ("code", "  !send notepad.exe   →  types text and presses Enter"),
                ("code", "  !combo win+r        →  presses Win + R together"),
                ("code", "  !key enter          →  presses a single key"),
                ("code", "  !keydown shift       →  holds a key down"),
                ("code", "  !keyup   shift       →  releases a held key"),
                ("h2",   "Mouse"),
                ("code", "  !click              →  left-click at current position"),
                ("code", "  !rclick             →  right-click"),
                ("code", "  !move 500 300       →  move cursor to x=500 y=300"),
                ("code", "  !scroll 3           →  scroll up 3 ticks  (negative = down)"),
                ("code", "  !drag 100 200       →  click-drag by 100x 200y"),
                ("h2",   "VM actions  (vote required — thresholds set in 🔒 Permissions tab)"),
                ("code", "  !restart            →  reset the VM"),
                ("code", "  !revert             →  restore snapshot"),
                ("code", "  !ban @username      →  ban a user by chat vote"),
                ("h2",   "Misc"),
                ("code", "  !votehelp           →  shows  'Commands in description!'  on overlay"),
                ("code", "  !clearvotes         →  admin only: clear all active votes"),
                ("tip",  "Tip: votes expire after 120 seconds if the threshold is not reached."),
                ("tip",  "Tip: the stream owner (isChatOwner) always bypasses vote requirements."),
                ("tip",  "Tip: vote thresholds are now fully configurable in the 🔒 Permissions tab — no code editing needed."),
            ]),
            ("⚙️  Command Builder", [
                ("h1",   "⚙️  Command Builder"),
                ("body", "Create custom chat commands — no coding required."),
                ("h2",   "Quick Chain Input  (fastest)"),
                ("body", "Type a full sequence in chat syntax in the chain field, then press  ⇨ Parse Steps:"),
                ("code", "  !combo win+r !wait 1 !send notepad.exe !key enter"),
                ("body", "This generates a 4-step command instantly."),
                ("h2",   "Step-by-step"),
                ("body", "1.  Click  ＋ New  to start fresh."),
                ("body", "2.  Set the trigger name, e.g.  !bubbles"),
                ("body", "3.  Pick an action (combo / send / wait / click…), fill in args, press  ＋ Add Step."),
                ("body", "4.  Reorder with  ▲ Up / ▼ Down.  Remove a step with  ✕ Remove."),
                ("body", "5.  Press  💾 Save Command,  then  ▶ Test Now  to try it live."),
                ("tip",  "Tip: commands are saved to  custom_commands.json  and survive restarts."),
                ("tip",  "Tip: available actions —  combo, send, sendenter, key, keydown, keyup, wait, click, rclick, move, abs, scroll"),
            ]),
            ("🖥️  VM Controls", [
                ("h1",   "🖥️  VM Controls"),
                ("body", "Admin-only actions — no vote needed, only you can trigger these."),
                ("code", "  ▶  Start VM     →  power on the VM"),
                ("code", "  🔄 Restart VM   →  send a hardware reset signal"),
                ("code", "  ⏮  Revert VM   →  power off → restore snapshot → boot"),
                ("code", "  ⏹  Shutdown VM →  force power off  (ACPI)"),
                ("h2",   "Admin CMD bar  (Main tab, bottom)"),
                ("body", "Type a command and press Enter or click Send. Works even when the bot is stopped:"),
                ("code", "  !startvm          →  start the VM"),
                ("code", "  !restart          →  reset the VM"),
                ("code", "  !revert           →  restore snapshot"),
                ("code", "  !speak Hello!     →  TTS announcement"),
                ("code", "  !clearvotes       →  wipe all active votes"),
            ]),
            ("🗳️  OS Voting", [
                ("h1",   "🗳️  OS Voting"),
                ("body", "Let your chat vote to switch between different operating systems live."),
                ("h2",   "Setup"),
                ("body", "1.  Go to the  OS Voting  tab and tick  Enable OS Voting."),
                ("body", "2.  Fill in up to 15 rows: Display Name, Chat Trigger (no ! needed), VirtualBox VM."),
                ("body", "3.  Click  💾 Save OS Voting Config."),
                ("h2",   "How it works"),
                ("body", "Viewers type e.g.  !win7.  When enough votes accumulate (default: 3), the bot powers off the current VM and boots the target one. Progress is shown on the overlay."),
                ("tip",  "Tip: the stream owner bypasses voting and switches instantly."),
                ("tip",  "Tip: the last active OS is remembered across bot restarts."),
            ]),
            ("📊  Statistics", [
                ("h1",   "📊  Statistics"),
                ("body", "Real-time tracking of everything that happens in your stream."),
                ("h2",   "Counter cards  (refreshed every 2 seconds)"),
                ("code", "  Commands (session)  →  resets each time the bot starts"),
                ("code", "  Commands (total)    →  accumulates across all sessions"),
                ("code", "  OS Switches         →  how many OS changes happened"),
                ("code", "  Restarts / Reverts  →  VM action counters"),
                ("code", "  Bot Uptime          →  hh : mm : ss  since last start"),
                ("h2",   "Leaderboards"),
                ("body", "Top 15 most used commands and top 15 most active users, sorted by count."),
                ("h2",   "Reset session"),
                ("body", "Click  🗑 Reset Session Stats  to wipe session counters and both leaderboards. The all-time total command count is NOT reset."),
                ("tip",  "Tip: for a full history of who did what and when, see the 📋 Event Log tab."),
            ]),
            ("🚫  User Management", [
                ("h1",   "🚫  User Management"),
                ("h2",   "Ban / Unban  (without typing in chat)"),
                ("body", "1.  Type a username + duration in minutes into the fields."),
                ("body", "2.  Press  🚫 Ban.  The user is blocked for that many minutes immediately."),
                ("body", "To unban: select from the list and press  ✅ Unban,  or type the name and press Unban."),
                ("tip",  "Tip: the ban list auto-refreshes every 5 seconds and removes expired bans."),
                ("h2",   "Whitelist"),
                ("body", "When enabled, ONLY listed users can use chat commands. The stream owner always bypasses this. Great for private / member-only streams."),
                ("tip",  "Tip: leave whitelist disabled (default) to allow everyone."),
                ("h2",   "VIP users"),
                ("body", "VIPs need fewer votes to trigger restart / revert.  Set  Votes needed = 1  to give a user instant-action power (same as stream owner)."),
                ("code", "  Example: add  nexoraWN  as VIP with 1 vote"),
                ("code", "           →  they can solo-restart the VM without other viewers voting"),
                ("tip",  "Tip: to change how many votes everyone needs (not just VIPs), use the 🔒 Permissions tab."),
            ]),
            ("🎨  Appearance", [
                ("h1",   "🎨  Appearance & Themes"),
                ("h2",   "Theme presets"),
                ("body", "Click any preset button to switch theme instantly: Dark Purple, Dark Blue, Dark Green, Dark Red, Dark Orange, Light, Light Blue, OLED Black."),
                ("h2",   "Custom colors"),
                ("body", "Click any color swatch to open the color picker and choose an exact hex value. All changes apply live — no restart needed."),
                ("h2",   "Font size"),
                ("body", "Drag the font size slider to scale text up or down globally."),
                ("body", "Press  💾 Save Appearance  to persist settings across restarts."),
            ]),
            ("📡  OBS Integration", [
                ("h1",   "📡  OBS Integration"),
                ("body", "Automatically switch OBS scenes when bot events happen."),
                ("h2",   "Setup"),
                ("body", "1.  In OBS: Tools → WebSocket Server Settings → Enable WebSocket.  Set a port & password."),
                ("body", "2.  In the OBS tab: enter  host  (usually localhost),  port,  password."),
                ("body", "3.  Click  Connect — the dot turns green on success."),
                ("h2",   "Scene Triggers"),
                ("body", "Click  ＋ Add Trigger  to add a new row.  Each row maps an event key to an exact OBS scene name."),
                ("code", "  Event Key        →  OBS Scene Name"),
                ("code", "  bot_start        →  Live Scene"),
                ("code", "  bot_stop         →  BRB Scene"),
                ("code", "  restart          →  Restart Scene"),
                ("code", "  revert_start     →  Loading Scene"),
                ("code", "  revert_done      →  Live Scene"),
                ("code", "  os_switch        →  OS Switch Scene"),
                ("code", "  ban              →  Ban Alert Scene"),
                ("code", "  scheduler        →  Maintenance Scene"),
                ("body", "You can use any event key — including custom ones you fire via  obs_trigger()  in your own commands.  Leave a row's scene field empty to disable that trigger.  Click  ✕  to remove a row entirely."),
                ("tip",  "Tip: event keys are case-sensitive.  Use lowercase with underscores, e.g.  revert_done."),
                ("h2",   "Per-OS scenes"),
                ("body", "Each OS entry in the OS Voting tab can have its own OBS scene that activates automatically when that OS is selected."),
            ]),
            ("📋  Event Log", [
                ("h1",   "📋  Event Log / History"),
                ("body", "A full audit trail of everything that happens while the bot runs — commands, votes, bans, restarts, reverts, OS switches, and scheduled actions."),
                ("h2",   "Filtering"),
                ("body", "Use the  Type  dropdown to show only a specific category:"),
                ("code", "  ALL         →  everything"),
                ("code", "  COMMAND     →  every chat command dispatched"),
                ("code", "  RESTART     →  VM restart events"),
                ("code", "  REVERT      →  VM revert / snapshot restore events"),
                ("code", "  OS_SWITCH   →  OS voting switch events"),
                ("code", "  BAN_VOTE    →  individual ban vote casts"),
                ("code", "  BAN         →  confirmed bans (threshold reached)"),
                ("code", "  SCHEDULER   →  actions fired by the scheduler"),
                ("body", "Use the  User  field to filter by a specific viewer's username.  Click  🔍 Apply Filter  or  🔄 Refresh  to update the table."),
                ("h2",   "Export"),
                ("body", "Click  💾 Export CSV  to save all log entries to a .csv file you can open in Excel or any spreadsheet app."),
                ("h2",   "Storage"),
                ("body", "The log is kept in memory (last 5 000 entries) and persisted to  event_log.json  in the bot folder.  It survives restarts."),
                ("tip",  "Tip: the table shows the 1 000 most recent matching entries, newest first."),
            ]),
            ("🔒  Permissions", [
                ("h1",   "🔒  Permissions"),
                ("body", "Set how many chat votes are required for each action — directly from the GUI, no code editing needed."),
                ("h2",   "Available settings"),
                ("code", "  Restart votes  →  votes needed to reset the VM         (default: 2)"),
                ("code", "  Revert votes   →  votes needed to restore the snapshot  (default: 2)"),
                ("code", "  Ban votes      →  votes needed to ban a viewer          (default: 3)"),
                ("h2",   "How to change"),
                ("body", "1.  Go to the  🔒 Permissions  tab."),
                ("body", "2.  Use the spinboxes to set the desired vote count for each action."),
                ("body", "3.  Click  💾 Save Permissions.  Changes take effect immediately — no bot restart needed."),
                ("h2",   "Interaction with VIPs"),
                ("body", "VIP users (configured in 🚫 User Management) can have a personal lower threshold that overrides the global value here.  The stream owner always bypasses voting entirely."),
                ("tip",  "Tip: set restart/revert to 1 to allow any single viewer to trigger them instantly."),
                ("tip",  "Tip: settings are saved to  permissions_config.json."),
            ]),
            ("🔊  Sound & TTS", [
                ("h1",   "🔊  Sound & TTS"),
                ("body", "Configure which sound file plays for each bot event, and fine-tune the Text-to-Speech voice."),
                ("h2",   "Per-event sound files"),
                ("body", "Each event has its own file field.  Leave a field empty to silence that event."),
                ("code", "  Success (default)  →  plays on any successful action"),
                ("code", "  VM Restart         →  plays when a restart completes"),
                ("code", "  VM Revert          →  plays when a snapshot restore completes"),
                ("code", "  User Banned        →  plays when a ban vote passes"),
                ("code", "  OS Switch          →  plays when the active OS changes"),
                ("body", "Click  📂  next to a field to browse for a file.  Click  ▶ Test  to preview the sound immediately."),
                ("h2",   "Text-to-Speech  (SAPI)"),
                ("body", "The bot uses Windows SAPI to announce events like  'Restarting Virtual Machine'."),
                ("code", "  TTS Enabled   →  toggle announcements on/off"),
                ("code", "  Speed         →  words per minute  (50 – 400, default 150)"),
                ("code", "  Volume        →  0 – 100  (default 100)"),
                ("body", "Type a test phrase and click  🗣 Test TTS  to hear the current settings live."),
                ("body", "Click  💾 Save Sound & TTS Config  to persist all settings to  sound_config.json."),
                ("tip",  "Tip: .mp3 and .wav files both work.  Use relative paths (e.g.  success.mp3) or full absolute paths."),
            ]),
            ("🌐  Multi-Stream", [
                ("h1",   "🌐  Multi-Stream"),
                ("body", "Listen to multiple YouTube live streams simultaneously — useful for backup streams or running the bot across multiple channels at once."),
                ("h2",   "How it works"),
                ("body", "The  Main tab  Video ID is the primary stream.  Any IDs added here are secondary streams.  All streams share the same command handling: keyboard, mouse, and custom commands all work from any stream."),
                ("tip",  "Tip: vote state (restart/revert/ban) is only tracked in the primary stream to avoid conflicts."),
                ("h2",   "Setup"),
                ("body", "1.  Go to the  🌐 Multi-Stream  tab."),
                ("body", "2.  Type an extra Video ID into the field and click  ＋ Add."),
                ("body", "3.  Repeat for each additional stream."),
                ("body", "4.  Click  💾 Save."),
                ("body", "5.  (Re)start the bot — secondary listeners launch automatically."),
                ("h2",   "Removing a stream"),
                ("body", "Select the ID in the list and click  ✕ Remove Selected,  then save and restart the bot."),
                ("tip",  "Tip: IDs are saved to  multi_stream_config.json.  The list persists across restarts."),
            ]),
            ("📅  Scheduler", [
                ("h1",   "📅  Scheduler"),
                ("body", "Automatically trigger a revert or restart at specific times — for example, reset the VM every night at 03:00 without being online."),
                ("h2",   "Enable / Disable"),
                ("body", "Tick  Enable Scheduler  at the top of the tab.  Tasks only fire when the scheduler is enabled AND the bot is running."),
                ("h2",   "Creating a task"),
                ("body", "Fill in the right-hand editor and click  ＋ Add / Update Task:"),
                ("code", "  Label    →  a name for the task, e.g.  Nightly Revert"),
                ("code", "  Action   →  revert  or  restart"),
                ("code", "  Time     →  HH : MM  in 24-hour format  (e.g. 03:00)"),
                ("code", "  Days     →  tick specific weekdays, or leave all unchecked for every day"),
                ("h2",   "Editing an existing task"),
                ("body", "Select it in the left list — the editor fills in.  Change the values and click  ＋ Add / Update Task  (same label = update)."),
                ("h2",   "Deleting a task"),
                ("body", "Select the task in the list and click  🗑 Delete.  Then  💾 Save All Scheduler Tasks."),
                ("h2",   "How it fires"),
                ("body", "The scheduler checks the time every 15 seconds.  Each task fires at most once per calendar day per label, so a bot restart mid-day will not double-fire a task that already ran today."),
                ("tip",  "Tip: scheduled events are recorded in the 📋 Event Log so you can confirm they fired."),
                ("tip",  "Tip: tasks are saved to  scheduler_config.json."),
            ]),
            ("⌨️  Keyboard Shortcuts", [
                ("h1",   "⌨️  Keyboard Shortcuts"),
                ("h2",   "Tab navigation"),
                ("code", "  Ctrl + Tab             →  next tab"),
                ("code", "  Ctrl + Shift + Tab     →  previous tab"),
                ("code", "  Mouse wheel on tabs    →  scroll through tabs"),
                ("h2",   "Text fields  (right-click context menu)"),
                ("code", "  Right-click  →  Copy / Paste / Cut / Select All"),
                ("h2",   "Admin CMD bar  (Main tab)"),
                ("code", "  Enter key  →  send admin command (no button click needed)"),
                ("h2",   "Command Builder chain field"),
                ("code", "  Enter key  →  parse chain into steps immediately"),
                ("h2",   "This guide"),
                ("code", "  ❓ Help button  (title bar)  →  reopen this guide at any time"),
                ("tip",  "Tip: tick  'Don't show on startup'  below to skip this guide next time."),
            ]),
            ("🖱  Real PC Control", [
                ("h1",   "🖱  Real PC Control"),
                ("body", "Let YouTube chat control THIS physical computer — keyboard, mouse, hotkeys and more — using pyautogui.  The VM bot and the Real PC bot are completely independent and can run simultaneously on different streams."),
                ("h2",   "Requirements"),
                ("body", "pyautogui must be installed.  If the tab shows a warning, open a terminal and run:"),
                ("code", "  pip install pyautogui"),
                ("body", "Then restart the bot.  The tab will become fully functional."),
                ("h2",   "Setup"),
                ("body", "1.  Go to the  🖱 Real PC  tab."),
                ("body", "2.  Enter the YouTube Video ID to listen on  (can be the same as the main bot or a different stream)."),
                ("body", "3.  Click  ▶ Start Real PC Bot."),
                ("body", "4.  Confirm all three safety warnings — read them carefully."),
                ("h2",   "Safety warnings"),
                ("body", "Starting the Real PC bot shows three mandatory confirmation dialogs explaining the risks.  You must click OK on all three before the bot starts.  This is intentional — giving chat access to your real computer is serious."),
                ("h2",   "Dangerous Command Filter"),
                ("body", "A hard-coded filter is ON by default and cannot be bypassed by chat.  It blocks destructive commands (format, shutdown, del /f, rm -rf, registry edits, PowerShell/download-and-run chains, etc.)."),
                ("body", "The filter tracks what each viewer is actually typing across their commands, not just one command at a time — so splitting a command into pieces (!type shu then !type tdown), or spelling it key-by-key, or editing it with !backspace, does NOT get around it.  The moment the dangerous command would actually appear on screen, it's blocked."),
                ("body", "You can turn this filter off in the Allowed Action Categories section, but doing so requires two separate hard warning confirmations.  Turning it off means you accept full responsibility for anything chat does to this computer — the developer is not responsible for the consequences."),
                ("tip",  "Tip: enable Failsafe.  Move your mouse to the top-left corner of the screen to instantly abort all actions."),
                ("tip",  "Tip: use the Whitelist to restrict which viewers can send commands."),
                ("tip",  "Tip: disable action categories you don't need  (e.g. Screenshot, Combo)  in the Allowed Actions section."),
                ("h2",   "Commands  (no prefix — same  !command  style as main bot)"),
                ("code", "  !type hello world    →  types text into the focused window"),
                ("code", "  !send hello          →  types text then presses Enter"),
                ("code", "  !key f5              →  presses a single key"),
                ("code", "  !enter               →  presses Enter"),
                ("code", "  !space               →  presses Space"),
                ("code", "  !backspace           →  deletes last character"),
                ("code", "  !combo win+r         →  presses Win + R together"),
                ("code", "  !combo ctrl+c        →  copy"),
                ("code", "  !combo alt+f4        →  close focused window"),
                ("code", "  !click               →  left-click at current cursor position"),
                ("code", "  !click 960 540       →  left-click at x=960  y=540"),
                ("code", "  !rclick              →  right-click"),
                ("code", "  !dclick              →  double-click"),
                ("code", "  !move 960 540        →  move cursor to exact coordinates"),
                ("code", "  !moverel up          →  move cursor up by step pixels"),
                ("code", "  !moverel down / left / right"),
                ("code", "  !moverel 100 -50     →  move cursor by +100x  -50y"),
                ("code", "  !scroll 3            →  scroll up 3 clicks"),
                ("code", "  !scroll -3           →  scroll down 3 clicks"),
                ("code", "  !drag 200 0          →  drag mouse 200px right"),
                ("code", "  !screenshot          →  save a PNG to the bot folder"),
                ("code", "  !pos                 →  show current cursor position in status bar"),
                ("code", "  !size                →  show screen resolution in status bar"),
                ("h2",   "Chain commands"),
                ("body", "Multiple commands can be combined in a single chat message — they execute left-to-right in order:"),
                ("code", "  !combo win+r !wait 1 !send cmd !wait 0.5 !key enter"),
                ("code", "  !click 960 540 !wait 0.3 !type hello !enter"),
                ("h2",   "Wait / Delay"),
                ("code", "  !wait 1              →  wait 1 second before next command  (max 10s)"),
                ("code", "  !wait 0.5            →  wait 500ms"),
                ("code", "  !sleep 2             →  same as !wait"),
                ("h2",   "Settings"),
                ("body", "All settings are in the 🖱 Real PC tab and saved to  realpc_config.json:"),
                ("code", "  Per-user cooldown    →  minimum seconds between commands from the same user"),
                ("code", "  Mouse step           →  pixels moved per  !moverel up/down/left/right"),
                ("code", "  Scroll step          →  clicks per  !scroll  without an explicit number"),
                ("code", "  Max type length      →  character limit for  !type  and  !send"),
                ("code", "  Failsafe             →  move mouse to top-left corner to abort"),
                ("h2",   "Access control"),
                ("body", "Whitelist — only listed usernames can send commands.  Leave disabled to allow everyone."),
                ("body", "Blocked — listed users are always ignored, regardless of whitelist setting."),
                ("body", "Both lists accept usernames with or without  @."),
                ("h2",   "Live Action Log"),
                ("body", "The bottom of the tab shows a live log of every Real PC command executed, updated every 500ms.  All events are also recorded in the 📋 Event Log tab under the  REALPC_CMD  type."),
                ("tip",  "WARNING: This feature gives chat control over your real computer.  The developer is not responsible for any damage, data loss, or privacy breach caused by its use.  Always supervise the stream while this feature is active."),
            ]),
        ]

        _chapter_btns = []

        def _show_chapter(idx):
            _, sections = CHAPTERS[idx]
            txt.configure(state="normal")
            txt.delete("1.0", "end")
            for tag, content in sections:
                if not content:
                    continue
                txt.insert("end", content + "\n", tag)
            txt.configure(state="disabled")
            txt.yview_moveto(0)
            for i, btn in enumerate(_chapter_btns):
                btn.configure(
                    bg=self.ACCENT if i == idx else self.BG2,
                    fg="#ffffff" if i == idx else self.TEXT,
                )

        for i, (title, _) in enumerate(CHAPTERS):
            btn = tk.Button(
                sidebar, text=title,
                bg=self.BG2, fg=self.TEXT,
                activebackground=self.ACCENT, activeforeground="#fff",
                relief="flat", bd=0, anchor="w",
                font=("Segoe UI", 9), padx=12, pady=7, cursor="hand2",
                command=lambda idx=i: _show_chapter(idx),
            )
            btn.pack(fill="x", pady=1)
            btn.bind("<MouseWheel>",
                lambda e: sb_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
            _chapter_btns.append(btn)

        _show_chapter(0)

        # Footer
        footer = tk.Frame(dlg, bg=self.BG2, pady=8)
        footer.pack(fill="x", side="bottom")

        dont_show_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            footer, text="Don't show this guide on startup",
            variable=dont_show_var,
            bg=self.BG2, fg=self.TEXTDIM,
            selectcolor=self.BG3,
            activebackground=self.BG2, activeforeground=self.TEXT,
            font=("Segoe UI", 9),
        ).pack(side="left", padx=16)

        def _close_guide():
            if dont_show_var.get():
                try:
                    with open(self.GUIDE_FLAG_FILE, "w") as f:
                        f.write("seen")
                except Exception:
                    pass
            dlg.destroy()

        ttk.Button(footer, text="✔  Got it, close guide",
                   style="Green.TButton",
                   command=_close_guide).pack(side="right", padx=16)

        dlg.protocol("WM_DELETE_WINDOW", _close_guide)
        dlg.bind("<Escape>", lambda e: _close_guide())
        txt.bind("<MouseWheel>",
                 lambda e: txt.yview_scroll(int(-1 * (e.delta / 120)), "units"))


# ========================= MAIN =========================
if __name__ == '__main__':
    load_custom_commands()
    load_user_mgmt()
    load_event_log()
    load_permissions_config()
    load_sound_config()
    load_multi_stream_config()
    load_scheduler_config()
    load_realpc_config()
    load_realpc_unblocked_patterns()
    load_reconnect_config()
    load_nexoai_config()
    load_vm_danger_filter_config()
    load_youtube_api_key_config()
    _update_splash(97, "Building interface...")

    # Reuse the hidden host root that was created alongside the splash.
    # Never call tk.Tk() a second time — that would reset all ttk styles.
    root = _host_root
    _gui_root = root
    app  = NexovativeControlCenter(root)   # builds GUI while root is still hidden

    _update_splash(100, "Ready!")
    time.sleep(0.25)    # let the user see 100% for a moment
    if not APP_LITE_MODE:
        if APP_EXTENDED_INTRO:
            _play_extended_intro_animation()   # ~8s full-screen cinematic intro
        else:
            _play_splash_outro_animation()     # short animated "NEXOVATIVE" reveal
    _close_splash()     # destroy splash Toplevel
    root.deiconify()    # NOW show the fully-built main window
    root.lift()
    root.focus_force()

    app.show_welcome_guide()   # show user guide on first launch

    start_tray_icon()

    def _on_close():
        import ctypes
        MB_YESNOCANCEL  = 0x03
        MB_ICONQUESTION = 0x20
        IDYES           = 6
        IDNO            = 7
        answer = ctypes.windll.user32.MessageBoxW(
            0,
            "Minimize to system tray instead of closing?\n\n"
            "Yes  → minimize to tray (bot keeps running)\n"
            "No   → exit completely\n"
            "Cancel → go back",
            "Close",
            MB_YESNOCANCEL | MB_ICONQUESTION
        )
        if answer == IDYES:
            root.withdraw()
            notify("Running in Tray", "Bot is still running. Right-click the tray icon to exit.")
        elif answer == IDNO:
            bot_stop_event.set()
            stop_realpc_bot()
            stop_tray_icon()
            root.destroy()
            os._exit(0)

    root.protocol("WM_DELETE_WINDOW", _on_close)
    root.mainloop()
    stop_tray_icon()
