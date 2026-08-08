import subprocess
import time
import traceback
import signal as _signal_module
import threading as _threading_module
import tkinter as tk
import tkinter.font as tkfont
import os
import sys
import platform
import select

def _native_dialog_yesno(msg, title):
    """Shows a native Yes/No dialog WITHOUT needing tkinter initialized yet (used during
    the UAC-elevation and update-check flows, both of which run before the GUI exists).
    Returns True for Yes, False for No -- or True if the dialog couldn't be shown at all,
    since defaulting to "proceed" is safer than silently blocking startup forever."""
    if platform.system() == "Windows":
        import ctypes
        MB_YESNO, MB_ICONQUESTION, IDYES = 0x04, 0x20, 6
        try:
            return ctypes.windll.user32.MessageBoxW(0, msg, title, MB_YESNO | MB_ICONQUESTION) == IDYES
        except Exception:
            return True
    elif platform.system() == "Darwin":
        try:
            esc_msg = msg.replace('\\', '\\\\').replace('"', '\\"')
            esc_title = title.replace('\\', '\\\\').replace('"', '\\"')
            script = f'display dialog "{esc_msg}" with title "{esc_title}" buttons {{"No", "Yes"}} default button "Yes"'
            result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=120)
            return "button returned:Yes" in (result.stdout or "")
        except Exception:
            return True
    else:
        print(f"[{title}] {msg}")
        return True

def _native_dialog_error(msg, title):
    """Shows a native error/info dialog WITHOUT needing tkinter initialized yet."""
    if platform.system() == "Windows":
        import ctypes
        MB_ICONERROR = 0x10
        try:
            ctypes.windll.user32.MessageBoxW(0, msg, title, MB_ICONERROR)
        except Exception:
            pass
    elif platform.system() == "Darwin":
        try:
            esc_msg = msg.replace('\\', '\\\\').replace('"', '\\"')
            esc_title = title.replace('\\', '\\\\').replace('"', '\\"')
            script = f'display alert "{esc_title}" message "{esc_msg}"'
            subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=60)
        except Exception:
            pass
    else:
        print(f"[{title}] {msg}")

# ── Detect "--flaskport=NNNN" (set on spawned multi-instance copies by the
#    Web Dashboard's Start button so the new process knows which port to
#    auto-start Flask on once its GUI is ready). ──
_LAUNCH_FLASK_PORT = None
for _a in sys.argv[1:]:
    if _a.startswith("--flaskport="):
        try:
            _LAUNCH_FLASK_PORT = int(_a.split("=", 1)[1])
        except Exception:
            _LAUNCH_FLASK_PORT = None
        break

# ── Detect "--autostart-everything" (set by the auto-update/hot-reload relaunch
#    pipeline's generated batch file on the freshly downloaded *_autostarteverything.py
#    copy) -- tells this instance to read video_id.json and self-start the bot,
#    extra streams, and the web dashboard without anyone at the keyboard. ──
_AUTOSTART_EVERYTHING = "--autostart-everything" in sys.argv[1:]

# ========================= UAC ELEVATION (Windows only) =========================
# If not already running as administrator, re-launch with ShellExecuteW so Windows
# shows the UAC prompt. The original process exits immediately.
#
# WINDOWS-ONLY: ctypes.windll doesn't exist at all outside Windows (it's a
# dynamically-created module attribute, not a real cross-platform ctypes feature),
# so every call in this block would raise AttributeError on macOS/Linux. There's
# also no macOS/Linux equivalent needed here in the first place -- writing files to
# the folder the script itself lives in (where the overlay HTML files go) never
# requires elevated privileges on those platforms the way Windows historically
# assumed for Program Files-style locations.
def _is_admin():
    if platform.system() != "Windows":
        return True  # nothing to elevate for outside Windows -- treat as "already fine"
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

if platform.system() == "Windows" and not _is_admin():
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

# ========================= VERSION & AUTO-UPDATE =========================
VERSION = "1.0"   # increment this with every release

# This script's own filename -- used to make sure a shared/misconfigured version.json
# is actually meant for THIS file before ever applying an update. A single version.json
# with one sha256/signature pair can only ever be valid for ONE file's actual content --
# if the repo hosts multiple platform/backend variants (like this one does), each variant
# needs its OWN version.json with a "filename" field matching this constant, or this
# script has no way to tell "a new version exists" apart from "a DIFFERENT file's new
# version exists, and applying it here would silently corrupt this install."
# If version.json has no "filename" field at all, this check is skipped (so this still
# works with a simple single-file repo) -- but IS enforced the moment that field appears.
CURRENT_FILENAME = "YouTubeChatUsesVM-MacOSIntel-VBox.py"

# Replace these two URLs with your own GitHub repo paths.
# GITHUB_VERSION_URL  → raw URL of version.json in your repo
# GITHUB_SCRIPT_URL   → raw URL of THIS file (YouTubeChatUsesVM-MacOSIntel-VBox.py) in your repo
#   Browsable page: https://github.com/mrtristin449/TheUltimateYouTubeChatUsesVMsPythonScriptLiveBot247ScriptMrTristin/blob/main/YouTubeChatUsesVMs/YouTubeChatUsesVM-MacOSIntel-VBox.py
#   (urllib needs the RAW content URL below, not the browsable page above --
#   raw.githubusercontent.com serves the actual file bytes, github.com/.../blob/
#   serves an HTML viewer page that urlopen() can't parse as source code.)
#
# Other macOS Intel variants in this repo (for reference only -- deliberately NOT fetched
# or checked by this script, only its OWN file above is ever downloaded/verified/replaced):
#   https://github.com/mrtristin449/TheUltimateYouTubeChatUsesVMsPythonScriptLiveBot247ScriptMrTristin/blob/main/YouTubeChatUsesVMs/YouTubeChatUsesVM-MacOSIntel-VMware.py
GITHUB_VERSION_URL = "https://raw.githubusercontent.com/mrtristin449/TheUltimateYouTubeChatUsesVMsPythonScriptLiveBot247ScriptMrTristin/main/version.json"
GITHUB_SCRIPT_URL  = "https://raw.githubusercontent.com/mrtristin449/TheUltimateYouTubeChatUsesVMsPythonScriptLiveBot247ScriptMrTristin/main/YouTubeChatUsesVMs/YouTubeChatUsesVM-MacOSIntel-VBox.py"

# Public key used to verify the signature of downloaded updates.
# This is SAFE to keep here — it can only verify signatures, not create them.
# Generate this pair locally with generate_keys.py and paste the public key below.
UPDATE_PUBLIC_KEY_HEX = "13eebf036b59fe64547d23cd2e3e23fae1d5ee086e912939a91d5535ed4df08b"


def _verify_update_signature(file_bytes, expected_sha256_hex, signature_hex):
    """
    Verifies that file_bytes matches the expected SHA-256 hash, and that the
    hash was signed by the holder of the private key matching
    UPDATE_PUBLIC_KEY_HEX. Returns True only if both checks pass.
    """
    import hashlib
    import binascii

    try:
        from nacl.signing import VerifyKey
        from nacl.exceptions import BadSignatureError
    except ImportError:
        print("[Updater] PyNaCl is not installed; cannot verify update signature. Aborting update.")
        return False

    actual_hash = hashlib.sha256(file_bytes).hexdigest()
    if actual_hash != expected_sha256_hex:
        print("[Updater] Hash mismatch -- downloaded file does not match version.json. Rejecting update.")
        return False

    try:
        verify_key = VerifyKey(binascii.unhexlify(UPDATE_PUBLIC_KEY_HEX))
        verify_key.verify(expected_sha256_hex.encode("ascii"), binascii.unhexlify(signature_hex))
        return True
    except BadSignatureError:
        print("[Updater] Signature is invalid. Rejecting update.")
        return False
    except Exception as e:
        print(f"[Updater] Signature verification error: {e}. Rejecting update.")
        return False


def _check_for_update():
    """
    Downloads version.json from GitHub and compares it to the running version.
    If a newer version is available, asks the user whether to update.
    Called once during splash, before the main GUI is built.
    Returns True if the script restarted (caller should exit), False otherwise.
    """
    import urllib.request
    import urllib.error
    import json as _json

    try:
        _update_splash(8, "Checking for updates...")
        with urllib.request.urlopen(GITHUB_VERSION_URL, timeout=5) as resp:
            data            = _json.loads(resp.read().decode("utf-8"))
            latest_ver      = data.get("version", "0.0.0").strip()
            expected_sha256 = data.get("sha256", "").strip()
            signature_hex   = data.get("signature", "").strip()
            version_filename = str(data.get("filename", "")).strip()
    except Exception as e:
        # Network unavailable or repo not configured — silently skip.
        print(f'[Updater] Could not check for updates: Python exception: "{traceback.format_exc()}"')
        return False

    if version_filename and version_filename != CURRENT_FILENAME:
        # version.json is declaring itself as meant for a DIFFERENT file in this repo
        # (a different platform/backend variant) -- this is exactly the "shared
        # version.json breaks multi-variant repos" scenario. Refuse rather than risk
        # applying a mismatched update: staying on the current version is always safer
        # than silently overwriting this file with a different variant's content.
        print(f"[Updater] version.json is for '{version_filename}', not this file "
              f"('{CURRENT_FILENAME}') -- skipping update. This is expected if you just "
              f"updated a DIFFERENT variant's version.json and haven't gotten to this "
              f"one yet.")
        return False

    def _ver_tuple(v):
        try:
            return tuple(int(x) for x in v.strip().split("."))
        except Exception:
            return (0, 0, 0)

    if _ver_tuple(latest_ver) <= _ver_tuple(VERSION):
        print(f"[Updater] Up to date ({VERSION}).")
        return False

    if not expected_sha256 or not signature_hex:
        print("[Updater] version.json is missing sha256/signature fields. Refusing to update.")
        return False

    # New version found — ask the user.
    msg = (
        f"A new version is available!\n\n"
        f"  Current version : {VERSION}\n"
        f"  New version     : {latest_ver}\n\n"
        f"Update now? The bot will restart automatically after downloading."
    )
    if not _native_dialog_yesno(msg, "Update Available"):
        print(f"[Updater] User declined update to {latest_ver}.")
        return False

    # Download new script to a temporary file first (atomic update).
    _update_splash(9, f"Downloading version {latest_ver}...")
    script_path = os.path.abspath(sys.argv[0])
    tmp_path    = script_path + ".update_tmp"
    try:
        with urllib.request.urlopen(GITHUB_SCRIPT_URL, timeout=30) as resp:
            new_code = resp.read()

        _update_splash(9, "Verifying update signature...")
        if not _verify_update_signature(new_code, expected_sha256, signature_hex):
            _native_dialog_error(
                "Update rejected: the downloaded file failed signature verification.\n\n"
                "This could mean the update source has been compromised.\n"
                "The bot will start with the current version.",
                "Update Security Warning"
            )
            print("[Updater] Update rejected due to failed signature verification.")
            return False

        with open(tmp_path, "wb") as f:
            f.write(new_code)
        # Atomic replace: rename tmp over the live file.
        if os.path.exists(script_path):
            os.replace(tmp_path, script_path)
        print(f"[Updater] Updated to {latest_ver}. Restarting...")
        # Restart the process with the same arguments.
        subprocess.Popen([sys.executable, script_path] + sys.argv[1:])
        sys.exit(0)
    except Exception as e:
        # Clean up temp file if something went wrong.
        if os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except Exception: pass
        _native_dialog_error(
            f"Update failed:\n{e}\n\nThe bot will start with the current version.",
            "Update Error"
        )
        print(f'[Updater] Update failed: Python exception: "{traceback.format_exc()}"')
        return False


# ========================= CONTINUOUS AUTO-UPDATE + AUTO-RELAUNCH =========================
# Separate from the signature-verified startup updater above. This runs continuously
# in the background the whole time the bot is open, checking a NEW GitHub source once
# per second (quietly -- only logs when something actually changes or on real errors,
# not on every check). When it finds a new version, instead of overwriting the running
# file in place, it hands off to a generated batch file that: kills the running python
# process, re-downloads every file from GitHub, and launches a NEW copy of the script
# named "{filename}_autostarteverything.py" that self-starts the bot, extra streams,
# and (if one was running) the web dashboard -- all without needing anyone at the
# keyboard. Real PC Control is deliberately NOT auto-resumed this way -- see below.

# Browsable page: https://github.com/mrtristin449/TheUltimateYouTubeChatUsesVMsPythonScriptLiveBot247ScriptMrTristin/blob/main/YouTubeChatUsesVMs/YouTubeChatUsesVM-MacOSIntel-VBox.py
AUTOUPDATE_VERSION_URL = "https://raw.githubusercontent.com/mrtristin449/TheUltimateYouTubeChatUsesVMsPythonScriptLiveBot247ScriptMrTristin/main/version.json"
AUTOUPDATE_SCRIPT_URL  = "https://raw.githubusercontent.com/mrtristin449/TheUltimateYouTubeChatUsesVMsPythonScriptLiveBot247ScriptMrTristin/main/YouTubeChatUsesVMs/YouTubeChatUsesVM-MacOSIntel-VBox.py"
AUTOUPDATE_POLL_INTERVAL = 5  # seconds -- checked with a conditional GET (ETag), so most
                              # checks are cheap "304 Not Modified" responses, not full downloads.

_autoupdate_relaunch_triggered = False   # guards against triggering the pipeline twice
_autoupdate_lock = _threading_module.Lock()

import re as _re_early
_AUTOSTART_SUFFIX_RE = _re_early.compile(r"_autostarteverything(\(\d+\)|_\d+)?$")

def _script_paths():
    """(full script path, folder, base filename without .py)."""
    script_path = os.path.abspath(sys.argv[0])
    folder = os.path.dirname(script_path)
    base_name = os.path.splitext(os.path.basename(script_path))[0]
    # If we're already running as a previously-generated "_autostarteverything" copy --
    # plain OR numbered, e.g. "_autostarteverything(3)" -- strip that suffix so we don't
    # end up with "..._autostarteverything_autostarteverything" or comparing the wrong
    # name against CURRENT_FILENAME/GITHUB_SCRIPT_URL.
    base_name = _AUTOSTART_SUFFIX_RE.sub("", base_name)
    return script_path, folder, base_name

def _next_autostart_filename(folder, base_name, current_script_path):
    """Picks the filename to write this relaunch's autostart copy to. Must NEVER be the
    file we're currently running as -- shutil.copyfile refuses to copy a file onto
    itself, which is exactly what happens on a second (or later) restart if this always
    returned the same plain "_autostarteverything.py" name: by then that plain name IS
    the currently-running file. So: try the plain name first (covers the first restart,
    from the original script), then (0), (1), (2)... skipping both the currently-running
    file and any name that already exists on disk from an earlier restart, so every
    restart gets its own distinct copy rather than colliding with or overwriting a
    previous one."""
    current_abs = os.path.abspath(current_script_path)
    candidate = os.path.join(folder, f"{base_name}_autostarteverything.py")
    if os.path.abspath(candidate) != current_abs and not os.path.exists(candidate):
        return os.path.basename(candidate)
    n = 0
    while True:
        candidate = os.path.join(folder, f"{base_name}_autostarteverything_{n}.py")
        if os.path.abspath(candidate) != current_abs and not os.path.exists(candidate):
            return os.path.basename(candidate)
        n += 1
        if n > 9999:   # sanity guard -- should never realistically be reached
            return f"{base_name}_autostarteverything_{int(time.time())}.py"

def _write_video_id_json(folder):
    """Persists the currently-active video ID so a relaunched instance can auto-resume
    on it. If VIDEO_ID is currently blank (bot stopped/idle when a restart happens to
    fire) this does NOT blank out a previously-saved, valid video ID -- it keeps
    whatever was already there. Only writes blank when there's genuinely nothing to
    preserve yet (no file, or the existing value is itself blank) -- e.g. the very
    first restart before the bot has ever been started on anything."""
    path = os.path.join(folder, "video_id.json")
    try:
        if not VIDEO_ID:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing = json.load(f).get("video_id", "")
                if existing:
                    return   # keep the existing, valid value -- don't overwrite with blank
            except Exception:
                pass   # no existing file, or it's unreadable/blank -- fine to write blank
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"video_id": VIDEO_ID}, f, indent=2)
    except Exception as e:
        print(f'[AutoUpdate] Could not write video_id.json: Python exception: "{traceback.format_exc()}"')

def _write_autostart_flags_json(folder):
    """Captures anything that isn't already in its own persisted config file, so the
    relaunched instance knows to resume it -- currently just the web dashboard port,
    if one was running (extra video IDs / VM config already persist in their own
    json files in this same folder and carry over automatically)."""
    flags = {"flask_port": FLASK_CONFIG.get("port") if '_flask_running' in globals() and _flask_running else None}
    try:
        with open(os.path.join(folder, "autostart_flags.json"), "w", encoding="utf-8") as f:
            json.dump(flags, f, indent=2)
    except Exception as e:
        print(f'[AutoUpdate] Could not write autostart_flags.json: Python exception: "{traceback.format_exc()}"')
    return flags

def _download_and_verify_update(version_data):
    """Downloads the new script and verifies it against version.json's sha256+signature
    using the exact same Ed25519 verification the safe startup updater uses (same
    UPDATE_PUBLIC_KEY_HEX). Returns the verified bytes on success. Returns None (with
    a clear log explaining why) if verification fails -- the caller must NOT proceed
    with the update in that case. If version.json has no sha256/signature at all, this
    downloads unverified with a clear warning, so the pipeline stays usable while
    you're still setting up signing, but that gap is loud, not silent."""
    import urllib.request
    version_filename = str(version_data.get("filename", "")).strip()
    if version_filename and version_filename != CURRENT_FILENAME:
        print(f"[AutoUpdate] SECURITY: version_data is for '{version_filename}', not this "
              f"file ('{CURRENT_FILENAME}') -- refusing to download/apply. This should "
              f"have been caught before this function was ever called; if you're seeing "
              f"this, something upstream isn't checking version.json's filename first.")
        return None
    expected_sha256 = str(version_data.get("sha256", "")).strip()
    signature_hex   = str(version_data.get("signature", "")).strip()
    try:
        with urllib.request.urlopen(AUTOUPDATE_SCRIPT_URL, timeout=30) as resp:
            new_code = resp.read()
    except Exception as e:
        print(f'[AutoUpdate] Download failed: Python exception: "{traceback.format_exc()}"')
        return None

    if not expected_sha256 or not signature_hex:
        print("[AutoUpdate] WARNING: version.json has no sha256/signature -- installing "
              "UNVERIFIED. Add both fields (signed with the key matching "
              "UPDATE_PUBLIC_KEY_HEX) to get real update verification.")
        return new_code

    if not _verify_update_signature(new_code, expected_sha256, signature_hex):
        print("[AutoUpdate] SECURITY: the downloaded update failed signature verification "
              "-- staying on the current version. This means either version.json's "
              "sha256/signature don't match the file at AUTOUPDATE_SCRIPT_URL, or they "
              "weren't signed with the private key matching this script's "
              "UPDATE_PUBLIC_KEY_HEX. Re-sign the release, or update UPDATE_PUBLIC_KEY_HEX "
              "to your own key pair's public key if this repo uses a different one.")
        return None

    print("[AutoUpdate] Update signature verified OK.")
    return new_code

def _generate_relaunch_script_macos(folder, base_name, flags):
    """macOS equivalent of _generate_relaunch_batch() below -- same steps (stop the
    running bot, refresh version.json for the record, launch the new instance with
    everything auto-starting), just in shell instead of batch. Uses curl (built into
    macOS, no PowerShell equivalent needed) instead of Invoke-WebRequest, and pkill
    instead of taskkill."""
    autostart_script = flags.get("autostart_filename", f"{base_name}_autostarteverything.py")
    autostart_path   = os.path.join(folder, autostart_script)
    script_path      = os.path.join(folder, "run_update.sh")
    python_exe       = sys.executable

    launch_args = "--autostart-everything"
    if flags.get("flask_port"):
        launch_args += f" --flaskport={flags['flask_port']}"

    sh = f"""#!/bin/bash
# ============================================================
# Auto-generated by the bot's auto-update system. Do not run
# this by hand unless you mean to force an update/relaunch --
# step 1 below kills any running copy of THIS bot specifically
# (matched by its own filename), not every python process on
# the machine -- an earlier version of this script used a much
# broader match that could accidentally kill unrelated Python
# applications you had open, like virt-manager.
# ============================================================
echo "Stopping the running bot..."
pkill -9 -u "$(whoami)" -f "{base_name}" 2>/dev/null
sleep 2

echo "Refreshing version.json..."
curl -fsSL "{AUTOUPDATE_VERSION_URL}" -o "{os.path.join(folder, 'version.json')}" || \\
    echo "WARNING: could not refresh version.json (non-fatal, continuing)"

if [ ! -f "{autostart_path}" ]; then
    echo "============================================================"
    echo "ERROR: \\"{autostart_script}\\" is missing -- nothing to launch."
    echo "This should have been written by the bot before this script"
    echo "ran. Nothing was started."
    echo "============================================================"
    read -p "Press Enter to close..."
    exit 1
fi

echo "Launching the updated bot with everything auto-starting..."
echo "Using interpreter: {python_exe}"
cd "{folder}"
"{python_exe}" "{autostart_script}" {launch_args}
if [ $? -ne 0 ]; then
    echo "============================================================"
    echo "ERROR: the relaunch exited with an error."
    echo "Common causes: a missing pip package, or \\"{python_exe}\\""
    echo "no longer being a valid Python install on this machine."
    echo "============================================================"
    read -p "Press Enter to close..."
    exit 1
fi

echo "Update complete."
"""
    try:
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(sh)
        os.chmod(script_path, 0o755)
        return script_path
    except Exception as e:
        print(f'[AutoUpdate] Could not write relaunch script: Python exception: "{traceback.format_exc()}"')
        return None

def _generate_relaunch_batch(folder, base_name, flags):
    """Writes the batch file: kill python, fetch a fresh version.json (for the record --
    the actual script content was already downloaded and signature-verified by Python
    before this was even called, and is written straight to disk, not re-fetched here
    unverified), then launch the new {base_name}_autostarteverything.py with everything
    auto-starting.

    Uses sys.executable (the exact interpreter this process is actually running under)
    rather than a bare "python" -- a bare "python" on PATH can silently resolve to a
    different install than the one with all this bot's pip packages, or not exist on
    PATH at all, which looks exactly like "the bot never comes back" with no visible
    error, since the console window closes before anyone can read it."""
    autostart_script = flags.get("autostart_filename", f"{base_name}_autostarteverything.py")
    autostart_path   = os.path.join(folder, autostart_script)
    batch_path       = os.path.join(folder, "run_update.bat")
    python_exe       = sys.executable

    launch_args = "--autostart-everything"
    if flags.get("flask_port"):
        launch_args += f" --flaskport={flags['flask_port']}"

    bat = f"""@echo off
REM ============================================================
REM  Auto-generated by the bot's auto-update system. Do not run
REM  this by hand unless you mean to force an update/relaunch --
REM  step 1 below kills EVERY python.exe/pythonw.exe process on
REM  this machine, not just this bot. The updated script itself
REM  was already downloaded and signature-verified by Python
REM  before this batch file was written -- this just re-fetches
REM  version.json for the record and launches the new instance.
REM ============================================================
echo Stopping the running bot...
taskkill /IM python.exe /F >nul 2>&1
taskkill /IM pythonw.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul

echo Refreshing version.json...
powershell -NoProfile -Command "Invoke-WebRequest -Uri '{AUTOUPDATE_VERSION_URL}' -OutFile '{os.path.join(folder, 'version.json')}'"

if not exist "{autostart_path}" (
    echo ============================================================
    echo ERROR: "{autostart_script}" is missing -- nothing to launch.
    echo This should have been written by the bot before this batch
    echo file ran. Nothing was started.
    echo ============================================================
    pause
    exit /b 1
)

echo Launching the updated bot with everything auto-starting...
echo Using interpreter: "{python_exe}"
cd /d "{folder}"
"{python_exe}" "{autostart_script}" {launch_args}
if errorlevel 1 (
    echo ============================================================
    echo ERROR: the relaunch exited with an error ^(code %errorlevel%^).
    echo Common causes: a missing pip package, or "{python_exe}"
    echo no longer being a valid Python install on this machine.
    echo ============================================================
    pause
    exit /b 1
)

echo Update complete.
"""
    try:
        with open(batch_path, "w", encoding="utf-8") as f:
            f.write(bat)
        return batch_path
    except Exception as e:
        print(f'[AutoUpdate] Could not write batch file: Python exception: "{traceback.format_exc()}"')
        return None

def _save_all_configs_before_relaunch():
    """Flushes every persisted-config category to disk before the old process gets
    killed. Without this, only whatever the user had already explicitly clicked
    "Save" on (each tab has its own save_*_config() call, not auto-saved on every
    change) would survive a relaunch -- anything changed but not yet saved on a tab
    the user hadn't clicked Save on would silently vanish the moment the old process
    was killed (os._exit() + kill give zero opportunity for cleanup code to run).
    Each save is independently wrapped so one failing doesn't block the rest."""
    savers = [
        save_flask_config, save_realpc_config, save_permissions_config,
        save_sound_config, save_multi_stream_config, save_scheduler_config,
        save_obs_config, save_auto_start_config, save_gemini_config, save_reconnect_config,
        save_os_voting_config, save_music_config, save_video_config,
        save_soundboard_config, save_internet_config,
        save_mrtristinai_config,
        lambda: save_autostart_everything_config(
            backend=current_vm_backend, vm=VM_NAME,
            os_voting_vm=(current_os_vm if OS_VOTING_ENABLED and current_os_vm else None),
            os_voting_backend=(current_vm_backend if OS_VOTING_ENABLED and current_os_vm else None),
            ai_safety_enabled=gemini_config.get("enabled"),
            ai_safety_provider=gemini_config.get("provider"),
            music_playback_enabled=music_config.get("enabled"),
            video_playback_enabled=video_config.get("enabled")),
    ]
    for saver in savers:
        try:
            saver()
        except Exception as e:
            print(f'[AutoUpdate] Could not save {saver.__name__} before relaunch: Python exception: "{traceback.format_exc()}"')
    # save_appearance_config() is the one outlier that takes arguments instead of
    # reading straight from a module-level dict -- same colors/font_size construction
    # _save_appearance() (the GUI's own Save button handler) uses. BG/ACCENT/etc. are
    # class attributes on UltraBotGUI itself, so no instance reference is needed.
    try:
        colors = {key: getattr(UltraBotGUI, key)
                  for key in ["BG", "BG2", "BG3", "ACCENT", "ACCENT2",
                              "TEXT", "TEXTDIM", "CONSOLE", "BORDER"]}
        save_appearance_config(colors, UltraBotGUI._FONT_SIZE)
    except Exception as e:
        print(f'[AutoUpdate] Could not save appearance config before relaunch: Python exception: "{traceback.format_exc()}"')

def trigger_relaunch_pipeline(reason, version_data=None):
    """Shared by both the version-update watcher and the file-edit watchdog below.
    If version_data is given (came from a real version.json check), the new script
    is downloaded and signature-verified FIRST -- the pipeline aborts cleanly if
    that fails, instead of installing something that didn't check out. If
    version_data is None (a local file-edit trigger, nothing remote to verify
    against), it skips straight to relaunching."""
    global _autoupdate_relaunch_triggered
    with _autoupdate_lock:
        if _autoupdate_relaunch_triggered:
            return
        _autoupdate_relaunch_triggered = True

    print(f"[AutoUpdate] {reason} -- preparing to relaunch.")
    _save_all_configs_before_relaunch()
    script_path, folder, base_name = _script_paths()
    autostart_filename = _next_autostart_filename(folder, base_name, script_path)
    print(f"[AutoUpdate] This relaunch's autostart copy: {autostart_filename}")

    if version_data is not None:
        verified_code = _download_and_verify_update(version_data)
        if verified_code is None:
            _autoupdate_relaunch_triggered = False
            return
        try:
            with open(os.path.join(folder, f"{base_name}.py"), "wb") as f:
                f.write(verified_code)
            with open(os.path.join(folder, autostart_filename), "wb") as f:
                f.write(verified_code)
        except Exception as e:
            print(f'[AutoUpdate] Could not write verified update to disk: Python exception: "{traceback.format_exc()}"')
            _autoupdate_relaunch_triggered = False
            return
    else:
        # Local file-edit trigger, not a version update -- nothing remote to verify,
        # just carry the just-edited file's content over to the autostart copy.
        try:
            shutil.copyfile(script_path, os.path.join(folder, autostart_filename))
        except Exception as e:
            print(f'[AutoUpdate] Could not copy edited file: Python exception: "{traceback.format_exc()}"')
            _autoupdate_relaunch_triggered = False
            return

    _write_video_id_json(folder)
    flags = _write_autostart_flags_json(folder)
    flags["autostart_filename"] = autostart_filename

    if REALPC_CONFIG.get("enabled"):
        print("[AutoUpdate] NOTE: Real PC Control was enabled before this relaunch. "
              "It will NOT auto-resume for safety -- go to the Real PC Control tab "
              "and click Start again once the new instance is up.")

    if platform.system() == "Darwin":
        script_path = _generate_relaunch_script_macos(folder, base_name, flags)
        if not script_path:
            _autoupdate_relaunch_triggered = False
            return
        try:
            # osascript + Terminal.app is the macOS equivalent of Windows'
            # CREATE_NEW_CONSOLE -- subprocess.Popen alone would run the script hidden
            # in the background, with no visible window to see progress or errors in.
            osa = f'tell application "Terminal" to do script "\\"{script_path}\\""'
            subprocess.Popen(["osascript", "-e", osa], close_fds=True)
            print(f"[AutoUpdate] Launched {os.path.basename(script_path)} in a new Terminal window. Exiting so it can take over...")
        except Exception as e:
            print(f'[AutoUpdate] Failed to launch relaunch script: Python exception: "{traceback.format_exc()}"')
            _autoupdate_relaunch_triggered = False
            return
        time.sleep(1.0)
        os._exit(0)
        return

    batch_path = _generate_relaunch_batch(folder, base_name, flags)
    if not batch_path:
        _autoupdate_relaunch_triggered = False
        return

    try:
        subprocess.Popen(["cmd", "/c", batch_path], creationflags=0x00000010,  # CREATE_NEW_CONSOLE
                          cwd=folder, close_fds=True)
        print(f"[AutoUpdate] Launched {os.path.basename(batch_path)}. Exiting so it can take over...")
    except Exception as e:
        print(f'[AutoUpdate] Failed to launch batch file: Python exception: "{traceback.format_exc()}"')
        _autoupdate_relaunch_triggered = False
        return

    time.sleep(1.0)
    os._exit(0)   # hard exit -- the batch file's taskkill would get us anyway

def _ver_tuple_v2(v):
    try:
        return tuple(int(x) for x in v.strip().split("."))
    except Exception:
        return (0, 0, 0)

def _autoupdate_watcher():
    """Runs the whole time the bot is open. Checks AUTOUPDATE_VERSION_URL every
    AUTOUPDATE_POLL_INTERVAL seconds (5) using a conditional GET (If-None-Match/ETag)
    so repeated checks are cheap 304 responses -- logs nothing on a normal check, only
    when a new version is actually found or on a real (non-network-hiccup) error.
    On detecting a new version: the new script is downloaded and signature-verified,
    written to disk, and the bot restarts itself via the relaunch pipeline."""
    import urllib.request
    import urllib.error
    last_etag = None
    consecutive_errors = 0
    while not bot_stop_event.is_set():
        if bot_stop_event.wait(AUTOUPDATE_POLL_INTERVAL):
            break
        try:
            req = urllib.request.Request(AUTOUPDATE_VERSION_URL)
            if last_etag:
                req.add_header("If-None-Match", last_etag)
            with urllib.request.urlopen(req, timeout=5) as resp:
                last_etag = resp.headers.get("ETag", last_etag)
                data = json.loads(resp.read().decode("utf-8"))
            consecutive_errors = 0
            version_filename = str(data.get("filename", "")).strip()
            if version_filename and version_filename != CURRENT_FILENAME:
                # Same "shared version.json across multiple variants" safety check as
                # _check_for_update() -- if it's declared for a different file, this
                # isn't a real update for THIS script, so don't act on it.
                continue
            latest_ver = str(data.get("version", "0.0.0")).strip()
            if _ver_tuple_v2(latest_ver) > _ver_tuple_v2(VERSION):
                print(f"[AutoUpdate] New version detected: {latest_ver} (current: {VERSION}).")
                trigger_relaunch_pipeline(f"New version {latest_ver} available", version_data=data)
                break
        except urllib.error.HTTPError as e:
            if e.code == 304:
                consecutive_errors = 0   # not modified -- totally normal, stay silent
            else:
                consecutive_errors += 1
                if consecutive_errors in (1, 60) or consecutive_errors % 360 == 0:   # ~first failure, ~5 min, then every ~30 min at the 5s interval
                    print(f"[AutoUpdate] Version check failed (HTTP {e.code}). Will keep retrying quietly.")
        except Exception:
            consecutive_errors += 1
            if consecutive_errors in (1, 60) or consecutive_errors % 360 == 0:   # ~first failure, ~5 min, then every ~30 min at the 5s interval
                print("[AutoUpdate] Version check failed (network). Will keep retrying quietly.")

def _discover_autostart_generations(folder, base_name):
    """Finds every existing generation of this script on disk: the original
    base_name.py, the plain base_name_autostarteverything.py, and every numbered
    base_name_autostarteverything(N).py -- returns their full paths. Used so the
    watchdog can watch ALL of them, not just whichever one happens to be running."""
    found = []
    original = os.path.join(folder, f"{base_name}.py")
    if os.path.isfile(original):
        found.append(original)
    try:
        for fname in os.listdir(folder):
            if not fname.lower().endswith(".py"):
                continue
            stem = fname[:-3]
            if not stem.startswith(f"{base_name}_autostarteverything"):
                continue
            suffix = stem[len(f"{base_name}_autostarteverything"):]
            if suffix == "" or _AUTOSTART_SUFFIX_RE.fullmatch(f"_autostarteverything{suffix}"):
                found.append(os.path.join(folder, fname))
    except Exception:
        pass
    return found

def _file_edit_watchdog():
    """Watches for on-disk changes to relaunch from -- EVERY existing generation of
    this script found in the folder: the original base_name.py, the plain
    _autostarteverything.py, and every numbered _autostarteverything(N).py, not just
    whichever one happens to be currently running. Watching only the running file was
    the actual bug: once running as, say, "..._autostarteverything(1).py", replacing
    the ORIGINAL "base_name.py" -- or an older generation like "(0)" -- went
    completely unnoticed, since those are different files the watchdog was never
    looking at. Re-scans the folder each cycle (cheap -- one os.listdir() a second) so
    a generation created mid-session gets picked up too. Whichever file actually
    changes on disk is the one carried over to the new autostart copy, not blindly
    whichever file this process happens to be running as."""
    script_path, folder, base_name = _script_paths()
    last_mtimes = {}

    def _rescan():
        for p in _discover_autostart_generations(folder, base_name):
            if p not in last_mtimes:
                try:
                    last_mtimes[p] = os.path.getmtime(p)
                except Exception:
                    pass

    _rescan()
    # Always track the running file itself even if, for some reason, it wasn't
    # picked up by the discovery scan (e.g. an unusual filename edge case).
    if script_path not in last_mtimes:
        try:
            last_mtimes[script_path] = os.path.getmtime(script_path)
        except Exception:
            pass
    if not last_mtimes:
        return

    while not bot_stop_event.is_set():
        if bot_stop_event.wait(1):
            break
        _rescan()   # pick up any generation created since the last check
        for p in list(last_mtimes.keys()):
            try:
                mtime = os.path.getmtime(p)
                if mtime != last_mtimes[p]:
                    last_mtimes[p] = mtime
                    # Debounce: a big (~500KB+) file replacement can take a
                    # perceptible moment to finish writing, and this could
                    # otherwise catch it mid-copy -- relaunching into a
                    # partially-written, likely-broken script, which fails
                    # in a way that looks exactly like "the restart just
                    # didn't happen" to anyone watching. Wait 5s and check
                    # again: if the mtime changed AGAIN in that window, the
                    # file is still actively being written, so keep waiting
                    # (the loop's own next iteration will catch that) rather
                    # than triggering on what might still be a half-written
                    # file.
                    if bot_stop_event.wait(5):
                        return
                    try:
                        settled_mtime = os.path.getmtime(p)
                    except Exception:
                        continue   # still mid-write/briefly missing -- try again next second
                    if settled_mtime != mtime:
                        last_mtimes[p] = settled_mtime
                        continue   # still changing -- not settled yet, don't trigger
                    trigger_relaunch_pipeline(f"{os.path.basename(p)} was modified on disk",
                                               source_path=p)
                    return
            except Exception:
                pass   # file briefly missing mid-write, etc. -- just try again next second


# Show the splash immediately — before any heavy imports — so the user
# sees something within milliseconds of launching the script.

_splash_root   = None
_splash_bar    = None
_splash_label  = None
_splash_pct    = None
_host_root     = None   # the one-and-only tk.Tk() instance (kept hidden during splash)

def _create_splash():
    global _splash_root, _splash_bar, _splash_label, _splash_pct, _host_root

    # Create the single tk.Tk() host window and keep it hidden.
    # All ttk styles will be registered on this interpreter.
    _host_root = tk.Tk()
    _host_root.withdraw()

    W, H = 480, 220
    # Splash is a Toplevel so it shares the same Tk interpreter
    splash = tk.Toplevel(_host_root)
    splash.title("")
    splash.resizable(False, False)
    splash.overrideredirect(True)          # borderless window
    sw = splash.winfo_screenwidth()
    sh = splash.winfo_screenheight()
    x  = (sw - W) // 2
    y  = (sh - H) // 2
    splash.geometry(f"{W}x{H}+{x}+{y}")
    splash.configure(bg="#0f0f1a")

    # Border frame
    border = tk.Frame(splash, bg="#7c5cbf", padx=2, pady=2)
    border.place(relx=0, rely=0, relwidth=1, relheight=1)
    inner = tk.Frame(border, bg="#0f0f1a")
    inner.pack(fill="both", expand=True)

    # "Script by MrTristin, Nexovative, and ReallyIron"
    tk.Label(inner, text="Script by MrTristin, Nexovative, and ReallyIron",
             bg="#0f0f1a", fg="#f0c060",
             font=("Segoe UI", 11, "bold")).pack(pady=(22, 0))

    # App title
    tk.Label(inner, text="VirtualBox Chat Bot",
             bg="#0f0f1a", fg="#ffffff",
             font=("Segoe UI", 18, "bold")).pack(pady=(4, 0))

    # Status label
    _splash_label = tk.Label(inner, text="Loading GUI...",
                              bg="#0f0f1a", fg="#aaaaaa",
                              font=("Segoe UI", 9))
    _splash_label.pack(pady=(14, 4))

    # Progress bar container
    bar_bg = tk.Frame(inner, bg="#1e1e2e", height=18, width=380)
    bar_bg.pack(pady=(0, 8))
    bar_bg.pack_propagate(False)

    _splash_bar = tk.Frame(bar_bg, bg="#3ddc97", width=0, height=18)
    _splash_bar.place(x=0, y=0, relheight=1)

    _splash_pct = tk.Label(inner, text="0%",
                            bg="#0f0f1a", fg="#3ddc97",
                            font=("Segoe UI", 8))
    _splash_pct.pack()

    _splash_root = splash
    splash.lift()
    # splash.attributes("-topmost", True)  # removed: caused splash to stay always on top
    splash.update()

def _update_splash(pct, label=None):
    """Update progress bar (0-100) and optional status text (call from main thread)."""
    if _splash_root is None:
        return
    try:
        bar_width = int(380 * pct / 100)
        _splash_bar.place(x=0, y=0, relheight=1, width=bar_width)
        _splash_pct.configure(text=f"{pct}%")
        if label:
            _splash_label.configure(text=label)
        _splash_root.update()
    except Exception:
        pass

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
_check_for_update()   # checks GitHub, asks user if update available, restarts if accepted

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
import pytchat

_update_splash(35, "Importing VirtualBox API...")
from vboxapi import VirtualBoxManager

_update_splash(50, "Importing system libraries...")
import threading
import re
try:
    import win32com.client  # Windows-only (pywin32) -- speak_text() below falls back to
                             # macOS's native 'say' command when this isn't available.
except ImportError:
    pass
import http.server
import socketserver
import json
from tkinter import ttk, scrolledtext, messagebox

_update_splash(58, "Importing media / web libraries...")

# ── Optional dep for Gemini-based pre-execution safety/copyright screening ──
try:
    from google import genai as _gemini_genai
    from google.genai import types as _gemini_types
    gemini_available = True
except ImportError:
    _gemini_genai = None
    _gemini_types = None
    gemini_available = False

# ── Optional dep for Groq -- the alternative provider for the same pre-execution
#    safety/copyright screening. Groq's API is OpenAI-compatible (same request/
#    response shape, just a different base_url and key), so this reuses the
#    standard `openai` package rather than needing a Groq-specific SDK. ──
try:
    import openai as _groq_openai_sdk
    groq_available = True
except ImportError:
    _groq_openai_sdk = None
    groq_available = False

# ── Optional deps for Music/Video/Soundboard/Flask dashboard (ported from the VMware build) ──
try:
    import vlc as _vlc
    vlc_available = True
except ImportError:
    _vlc = None
    vlc_available = False

try:
    import yt_dlp
    ytdlp_available = True
except ImportError:
    yt_dlp = None
    ytdlp_available = False

try:
    from flask import Flask, jsonify, render_template_string, request as flask_request
    flask_available = True
except ImportError:
    flask_available = False

try:
    from flask_cors import CORS as _FlaskCORS
    flask_cors_available = True
except ImportError:
    _FlaskCORS = None
    flask_cors_available = False

try:
    from gtts import gTTS as _gTTS
    gtts_available = True
except ImportError:
    _gTTS = None
    gtts_available = False

try:
    import winsound as _winsound
    winsound_available = True
except ImportError:
    _winsound = None
    winsound_available = False

import webbrowser
import urllib.request, urllib.error, urllib.parse
import shutil
import random
import platform
import math
from tkinter import simpledialog as _simpledialog

def script_dir():
    """Folder the script itself lives in."""
    try: return os.path.dirname(os.path.abspath(__file__))
    except Exception: return os.getcwd()

def safe_json_dump(filename, data):
    """Write JSON atomically (temp file + rename) so a crash mid-write never corrupts the file."""
    tmp_file = filename + ".tmp"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f: json.dump(data, f, indent=4)
        os.replace(tmp_file, filename)
    except Exception:
        try:
            with open(filename, "w", encoding="utf-8") as f: json.dump(data, f, indent=4)
        except Exception: pass

def console_log(level, msg):
    """Lightweight logger used by the ported Music/Video/Soundboard/Flask code."""
    timestamp = time.strftime("%H:%M:%S")
    log_line = f"[{timestamp}] [{level.lower()}] {msg}"
    print(log_line, flush=True)
    try:
        if _gui_app is not None:
            _gui_app._log(log_line)
    except Exception:
        pass

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
except Exception:
    # Broader than ImportError on purpose: on Linux, pystray's own import-time backend
    # selection can raise ValueError (not ImportError) if a required GObject
    # Introspection namespace -- AppIndicator3, AyatanaAppIndicator3 -- isn't installed
    # on the system (gi.require_version() raises ValueError, not ImportError, when the
    # namespace is missing). That was propagating straight through this except clause
    # and crashing the whole script at startup, instead of just disabling the tray icon
    # like this try/except was meant to do. If you hit this, `sudo apt install
    # gir1.2-ayatanaappindicator3-0.1` (or gir1.2-appindicator3-0.1 on older distros)
    # fixes it, but the bot now starts fine either way -- tray icon is optional.
    _PYSTRAY_OK = False
    print("[Tray] pystray/Pillow not installed — system tray disabled. Run: pip install pystray pillow")

try:
    import pyautogui
    pyautogui.FAILSAFE   = True   # move mouse to top-left corner to abort
    pyautogui.PAUSE      = 0.05   # small delay between actions for stability
    _PYAUTOGUI_OK = True
except ImportError:
    pyautogui     = None
    _PYAUTOGUI_OK = False
    print("[RealPC] pyautogui not installed — Real PC Control tab will show install prompt. "
          "Run: pip install pyautogui")

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
                print(f'[Notify] Error: Python exception: "{traceback.format_exc()}"')
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
    if platform.system() == "Darwin":
        # macOS: pystray.Icon.run() needs to own the Cocoa/AppKit run loop -- the SAME
        # run loop Tkinter's Cocoa-backed Tk relies on for its own event notifier.
        # Running .run() on a background thread (the old pattern below, which is fine
        # on Windows/Linux) creates a run-loop ownership conflict that can corrupt
        # Tcl's notifier and crash with "Tcl_WaitForEvent: Notifier not initialized" --
        # possibly not immediately, and not necessarily from code that looks related.
        # run_detached() is pystray's own documented answer for apps that already have
        # a different main loop (Tkinter's mainloop() here): it integrates without
        # needing to own the thread, instead of fighting Tkinter for it.
        try:
            _tray_icon.run_detached()
            _tray_thread = None
            print("[Tray] System tray icon started (macOS run_detached).")
            return
        except Exception as e:
            print(f"[Tray] run_detached failed ({e}) -- tray icon disabled this session.")
            _tray_icon = None
            return
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
        print(f'[CustomCmd] Load error: Python exception: "{traceback.format_exc()}"')
        custom_commands = {}

def save_custom_commands():
    try:
        with open(CUSTOM_COMMANDS_FILE, "w", encoding="utf-8") as f:
            json.dump(custom_commands, f, indent=2, ensure_ascii=False)
        print(f"[CustomCmd] Saved {len(custom_commands)} command(s).")
    except Exception as e:
        print(f'[CustomCmd] Save error: Python exception: "{traceback.format_exc()}"')

def execute_custom_command(trigger):
    steps = custom_commands.get(trigger, [])
    print(f"[CustomCmd] Executing '{trigger}' ({len(steps)} steps)")
    for step in steps:
        action = step.get("action", "").lower().strip()
        args   = step.get("args",   "").strip()
        try:
            if action == "combo":
                keys = parse_combo_keys(args)
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
                k = args.lower().strip()
                if k in SCANCODES:
                    send_scancode(SCANCODES[k][0])
            elif action in ("keyup", "release"):
                k = args.lower().strip()
                if k in SCANCODES:
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
            elif action in ("move", "mouse", "mv"):
                handle_mouse("move", args)
            elif action in ("abs", "cursor", "moveabs"):
                handle_mouse("abs", args)
            elif action in ("scroll", "wheel"):
                handle_mouse("scroll", args)
            print(f"[CustomCmd]   → {action} {args}")
        except Exception as e:
            print(f'[CustomCmd] Step error ({action} {args}): Python exception: "{traceback.format_exc()}"')

# ========================= OVERLAY SYSTEM =========================
overlay_data = {"chat": [], "running_command": "", "viewers": None, "likes": None, "subscribers": None}
seen_message_ids = set()
last_write_time = 0
_overlay_seq_counter = 0

def update_overlay(author=None, message=None, running=None, msg_id=None):
    global last_write_time, _overlay_seq_counter
    changed = False
    current_time = time.time()
    if running is not None and overlay_data.get("running_command") != running:
        overlay_data["running_command"] = running
        changed = True
    if author and message and msg_id and msg_id not in seen_message_ids:
        seen_message_ids.add(msg_id)
        _overlay_seq_counter += 1
        overlay_data["chat"].append({"author": str(author), "message": str(message),
                                      "id": str(msg_id), "seq": _overlay_seq_counter})
        if len(overlay_data["chat"]) > 150:
            removed = overlay_data["chat"].pop(0)
            seen_message_ids.discard(removed.get("id"))
        changed = True
    if changed and (current_time - last_write_time > 0.15):
        try:
            with open("overlay.json", "w", encoding="utf-8") as f:
                json.dump(overlay_data, f, ensure_ascii=False, separators=(',', ':'))
            last_write_time = current_time
        except Exception as e:
            print(f"[Overlay Error] {e}")

_youtube_stats_channel_id = None

def fetch_youtube_stats():
    """Background thread: polls YouTube Data API v3 every 30s for live viewer/like/
    subscriber counts. Needs YOUTUBE_API_KEY set (Permissions tab) -- silently does
    nothing if it isn't, since this is optional (vote-threshold-by-percent falls
    back to fixed vote counts when no live viewer number is available)."""
    global _youtube_stats_channel_id
    import urllib.request
    while not bot_stop_event.is_set():
        try:
            if YOUTUBE_API_KEY and VIDEO_ID:
                url_video = (
                    f"https://www.googleapis.com/youtube/v3/videos"
                    f"?part=statistics,liveStreamingDetails&id={VIDEO_ID}&key={YOUTUBE_API_KEY}"
                )
                with urllib.request.urlopen(url_video, timeout=10) as r:
                    vdata = json.loads(r.read().decode())
                items = vdata.get("items", [])
                if items:
                    stats = items[0].get("statistics", {})
                    live  = items[0].get("liveStreamingDetails", {})
                    overlay_data["viewers"] = int(live.get("concurrentViewers", 0)) if live.get("concurrentViewers") else None
                    overlay_data["likes"]   = int(stats.get("likeCount", 0))        if stats.get("likeCount")       else None

                    if _youtube_stats_channel_id is None:
                        url_snap = (
                            f"https://www.googleapis.com/youtube/v3/videos"
                            f"?part=snippet&id={VIDEO_ID}&key={YOUTUBE_API_KEY}"
                        )
                        with urllib.request.urlopen(url_snap, timeout=10) as r2:
                            snap = json.loads(r2.read().decode())
                        _youtube_stats_channel_id = snap.get("items", [{}])[0].get("snippet", {}).get("channelId", "")
                    if _youtube_stats_channel_id:
                        url_ch = (
                            f"https://www.googleapis.com/youtube/v3/channels"
                            f"?part=statistics&id={_youtube_stats_channel_id}&key={YOUTUBE_API_KEY}"
                        )
                        with urllib.request.urlopen(url_ch, timeout=10) as r3:
                            cdata = json.loads(r3.read().decode())
                        sub_count = cdata.get("items", [{}])[0].get("statistics", {}).get("subscriberCount")
                        overlay_data["subscribers"] = int(sub_count) if sub_count else None
                    try:
                        with open("overlay.json", "w", encoding="utf-8") as f:
                            json.dump(overlay_data, f, ensure_ascii=False, separators=(',', ':'))
                    except Exception:
                        pass
        except Exception as e:
            print(f'[Stats] Fetch error: Python exception: "{traceback.format_exc()}"')
        if bot_stop_event.wait(30):
            break

_overlay_server_started = False

def start_overlay_server():
    """Serves the OBS browser-source overlay pages and polls chat history/status over
    HTTP -- this is independent of the bot's own YouTube connection lifecycle (the
    overlay just has less to show while disconnected, it doesn't need to restart
    alongside the bot). Guarded to only ever actually start once: the bot itself can
    be started and stopped many times across a session, but each restart used to call
    this again, and since serve_forever() has no hook into bot_stop_event and never
    actually stops on its own, every restart after the first was trying to rebind an
    already-occupied port -- which is what previously showed up as
    "[Overlay] Port 8083 is busy" following any bot restart."""
    global _overlay_server_started
    if _overlay_server_started:
        return
    _overlay_server_started = True
    PORT = 8083
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format, *args): pass
    class ReusableTCPServer(socketserver.TCPServer):
        allow_reuse_address = True   # defensive: helps a fresh process rebind even if
                                      # the OS hasn't fully released the port yet from a
                                      # just-exited previous process (e.g. right after
                                      # this script's own auto-update/relaunch)
    try:
        with ReusableTCPServer(("", PORT), QuietHandler) as httpd:
            print(f"[Overlay] Server running at: http://localhost:{PORT}/chat.html")
            httpd.serve_forever()
    except OSError:
        print("[Overlay] Port 8083 is busy.")
        _overlay_server_started = False   # didn't actually start -- allow a later retry

html_index = """<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Chat Controls</title><style>body{background:#09090b;color:#00E5FF;font-family:'Segoe UI',Consolas,monospace;text-align:center;padding:40px}h1{color:#10B981;font-size:36px;text-shadow:0 0 10px rgba(16,185,129,0.3);margin-bottom:5px}.grid{display:flex;flex-wrap:wrap;gap:20px;justify-content:center;max-width:800px;margin:40px auto}a{background:#18181b;border:1px solid #27272a;color:#fff;text-decoration:none;padding:20px;border-radius:12px;width:300px;transition:all 0.2s;box-shadow:0 4px 6px rgba(0,0,0,0.3);text-align:left}a:hover{transform:translateY(-5px);border-color:#00E5FF;box-shadow:0 8px 15px rgba(0,229,255,0.2)}.title{font-size:20px;font-weight:bold;margin-bottom:10px;color:#00E5FF}.desc{font-size:14px;color:#a1a1aa}</style></head><body><h1>[active] chat server active</h1><p style="color:#71717a;font-size:18px">Add one of these links to your OBS Browser Source:</p><div class="grid"><a href="/obsnew"><div class="title">Liquid Glass Chat (/obsnew)</div><div class="desc">Sleek gray bubbles with a glass background.</div></a><a href="/oldobsnew"><div class="title">Classic Dark Chat (/oldobsnew)</div><div class="desc">The OG dark background modern chat.</div></a><a href="/ultradebug"><div class="title">Ultra Debug (/ultradebug)</div><div class="desc">Shows core system status and queues.</div></a><a href="/stats"><div class="title">Live Stats (/stats)</div><div class="desc">Viewers, Likes, and Uptime widget.</div></a><a href="/obs"><div class="title">Legacy Chat (/obs)</div><div class="desc">The original transparent overlay.</div></a><a href="/nowplaying"><div class="title">Now Playing (/nowplaying)</div><div class="desc">Bottom-left song title + artist overlay for !sr.</div></a><a href="/votes-overlay"><div class="title">Restart/Revert Votes (/votes-overlay)</div><div class="desc">Live progress bars for pending restart/revert votes.</div></a><a href="/osvotestatus"><div class="title">OS Vote Status (/osvotestatus)</div><div class="desc">Per-OS voting tally, highlights the currently running OS.</div></a><a href="/banvote"><div class="title">Ban Vote (/banvote)</div><div class="desc">Progress toward the current ban vote, if any.</div></a><a href="/status"><div class="title">Bot Status (/status)</div><div class="desc">Simple current-status text box.</div></a></div></body></html>"""

html_template = """<!DOCTYPE html><html><head><meta charset="UTF-8"><style>@import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@500;700&display=swap');@keyframes slideIn{from{transform:translateX(20px);opacity:0}to{transform:translateX(0);opacity:1}}html,body{background-color:rgba(0,0,0,0)!important;margin:0;padding:0;width:100vw;height:100vh;overflow:hidden}body{font-family:'Fira Code','Consolas',monospace;display:flex;flex-direction:column;padding:10px;text-shadow:2px 2px 0 #000;color:#ccc;font-size:16px;justify-content:flex-end}.header{position:absolute;top:10px;right:10px;text-align:right;display:flex;flex-direction:column;align-items:flex-end;z-index:10}div[id="vote-text"]{font-family:'Impact',sans-serif;font-size:24px;color:red;text-transform:uppercase;margin-bottom:5px;text-shadow:2px 2px 0 #000;background:rgba(0,0,0,0.85);padding:5px 12px;border:1px solid #444;border-radius:4px;display:none}.stats-container{display:flex;gap:15px;font-family:'Fira Code',monospace;font-weight:bold;font-size:20px;align-items:center;background:rgba(0,0,0,0.85);padding:5px 12px;border:1px solid #444;border-radius:4px}.stat-item{display:flex;align-items:center;gap:6px}.icon-eye{fill:#0af;width:22px;height:22px;filter:drop-shadow(0 0 2px #0af)}.icon-thumb{fill:#0f0;width:22px;height:22px;filter:drop-shadow(0 0 2px #0f0)}.stat-text{color:#fff;text-shadow:0 0 2px #fff}.chat-box{flex-grow:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:flex-end;padding-bottom:10px;z-index:5}.line{font-size:18px;font-weight:500;margin-bottom:3px;color:#fff;line-height:1.3;word-wrap:break-word;overflow-wrap:break-word;display:flex;align-items:flex-start;justify-content:flex-end;width:100%;animation:slideIn 0.2s ease-out forwards}.admin-name{color:#5e84f1;font-weight:700;text-shadow:0 0 3px #5e84f1}.owner-name{color:#ffd700;font-weight:700;text-shadow:0 0 3px #ffd700}.user-name{color:#e0e0e0;font-weight:700}.sys-text{color:#f0f;font-weight:700;text-shadow:0 0 3px #f0f}.sys-msg-text{color:#0f0;font-weight:bold}.err-text{color:#f33;font-weight:bold}.msg-text{color:#fff}.separator{margin-right:8px;color:#888;font-weight:bold}</style></head><body><div class="header"><div id="vote-text">no active votes</div><div class="stats-container"><div class="stat-item"><svg class="icon-eye" viewBox="0 0 24 24"><path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.61 11 7.61s9.27-3.22 11-7.61C21.27 7.61 17 4.5 12 4.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z"/></svg><span id="viewers" class="stat-text">0</span></div><div class="stat-item"><svg class="icon-thumb" viewBox="0 0 24 24"><path d="M1 21h4V9H1v12zm22-11c0-1.1-.9-2-2-2h-6.31l.95-4.57.03-.32c0-.41-.17-.79-.44-1.06L14.17 1 7.59 7.59C7.22 7.95 7 8.45 7 9v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-1.91l-.01-.01L23 10z"/></svg><span id="likes" class="stat-text">0</span></div></div></div><div class="chat-box" id="chat"></div><script>let lastId=-1;let fetchingUpdates=!1;setInterval(function(){if(fetchingUpdates)return;fetchingUpdates=!0;fetch('/history?t='+Date.now()).then(r=>r.json()).then(data=>{if(data&&Array.isArray(data)){const c=document.getElementById('chat');if(!c)return;const fragment=document.createDocumentFragment();let added=!1;data.forEach(i=>{if(i.id>lastId){lastId=i.id;try{let nameClass="user-name";let msgClass="msg-text";if(i.is_owner){nameClass="owner-name";}else if(i.is_admin){nameClass="admin-name";}let u=i.u||"Unknown";let m=i.m||"";if(u==='[system]'||u==='system'){u="[system]";nameClass="sys-text";msgClass=m.includes("[err]")?"err-text":"sys-msg-text";}else if(u==='[console]'||u==='[announcement]'){nameClass="admin-name";}else{if(typeof u==='string'&&!u.startsWith('@'))u="@"+u;}const div=document.createElement('div');div.className='line';div.innerHTML=`<span class='${nameClass}'>${u}</span><span class="separator">:</span><span class='${msgClass}'>${m}</span>`;fragment.appendChild(div);added=!0;}catch(err){}}});if(added){c.appendChild(fragment);window.scrollTo(0,document.body.scrollHeight);while(c.children.length>50)c.removeChild(c.firstChild);}}fetchingUpdates=!1;}).catch(e=>{fetchingUpdates=!1;});},1000);let fetchingStatus=!1;setInterval(function(){if(fetchingStatus)return;fetchingStatus=!0;fetch('/status_update?t='+Date.now()).then(r=>r.json()).then(data=>{try{const v=document.getElementById('vote-text');const chatBox=document.getElementById('chat');const headerBox=document.querySelector('.header');if(chatBox){chatBox.style.display=data.chat_visible?'flex':'none';}if(headerBox){if(data.split_mode){headerBox.style.display='none';}else{headerBox.style.display='flex';if(v&&data.vote&&data.vote.active){v.innerHTML=(data.vote.text||"").replace('[vote] ','');v.style.display="block";}else if(v){v.style.display="none";}const viewEl=document.getElementById('viewers');const likeEl=document.getElementById('likes');if(viewEl)viewEl.innerText=data.viewers||"0";if(likeEl)likeEl.innerText=data.likes||"0";}}}catch(err){}fetchingStatus=!1;}).catch(e=>{fetchingStatus=!1;});},2000);</script></body></html>"""

html_template_2 = """<!DOCTYPE html><html><head><meta charset="UTF-8"><style>@import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@500;700&display=swap');html,body{background-color:rgba(0,0,0,0)!important;margin:0;padding:0;width:100vw;height:100vh;overflow:hidden}body{font-family:'Fira Code','Consolas',monospace;display:flex;flex-direction:column;align-items:flex-end;padding:3vw;box-sizing:border-box}.header{text-align:right;display:flex;flex-direction:column;align-items:flex-end}div[id="vote-text"]{font-family:'Impact',sans-serif;font-size:10vw;color:red;text-transform:uppercase;margin-bottom:2vw;text-shadow:0.5vw 0.5vw 0 #000;display:none;line-height:1}.stats-container{display:flex;gap:5vw;font-family:'Fira Code',monospace;font-weight:bold;font-size:8vw;align-items:center}.stat-item{display:flex;align-items:center;gap:2vw}.icon-eye{fill:#0af;width:9vw;height:9vw;filter:drop-shadow(0.4vw 0.4vw 0 #000)}.icon-thumb{fill:#0f0;width:9vw;height:9vw;filter:drop-shadow(0.4vw 0.4vw 0 #000)}.stat-text{color:#fff;text-shadow:0.4vw 0.4vw 0 #000}</style></head><body><div class="header"><div id="vote-text"></div><div class="stats-container"><div class="stat-item"><svg class="icon-eye" viewBox="0 0 24 24"><path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.61 11 7.61s9.27-3.22 11-7.61C21.27 7.61 17 4.5 12 4.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z"/></svg><span id="viewers" class="stat-text">0</span></div><div class="stat-item"><svg class="icon-thumb" viewBox="0 0 24 24"><path d="M1 21h4V9H1v12zm22-11c0-1.1-.9-2-2-2h-6.31l.95-4.57.03-.32c0-.41-.17-.79-.44-1.06L14.17 1 7.59 7.59C7.22 7.95 7 8.45 7 9v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-1.91l-.01-.01L23 10z"/></svg><span id="likes" class="stat-text">0</span></div></div></div><script>let fetchingStatus2=!1;setInterval(function(){if(fetchingStatus2)return;fetchingStatus2=!0;fetch('/status_update?t='+Date.now()).then(r=>r.json()).then(data=>{try{const v=document.getElementById('vote-text');if(data.vote&&data.vote.active){v.innerHTML=(data.vote.text||"").replace('[vote] ','');v.style.display="block";}else if(v){v.style.display="none";}const viewEl=document.getElementById('viewers');const likeEl=document.getElementById('likes');if(viewEl)viewEl.innerText=data.viewers||"0";if(likeEl)likeEl.innerText=data.likes||"0";}catch(err){}fetchingStatus2=!1;}).catch(e=>{fetchingStatus2=!1;});},2000);</script></body></html>"""

html_template_new = """<!DOCTYPE html><html><head><meta charset="UTF-8"><style>@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');html,body{background-color:rgba(0,0,0,0)!important;margin:0;padding:0;width:100%;height:100%;overflow:hidden}body{font-family:'-apple-system','BlinkMacSystemFont','Inter',sans-serif;display:flex;flex-direction:column;padding:25px;justify-content:flex-end;box-sizing:border-box}.chat-box{display:flex;flex-direction:column;align-items:flex-end;gap:16px;width:100%}.msg-block{background:rgba(80,80,85,0.25);backdrop-filter:blur(25px) saturate(200%);-webkit-backdrop-filter:blur(25px) saturate(200%);padding:12px 18px;display:flex;align-items:flex-start;font-size:16px;border-radius:22px;box-shadow:0 8px 32px rgba(0,0,0,0.15),inset 0 1px 1px rgba(255,255,255,0.4);animation:popIn 0.35s cubic-bezier(0.175,0.885,0.32,1.2) forwards;max-width:90%;word-wrap:break-word;border:1px solid rgba(255,255,255,0.15);border-bottom:1px solid rgba(255,255,255,0.05)}.msg-block.cmd-border{box-shadow:0 8px 32px rgba(0,0,0,0.15),inset 0 1px 1px rgba(255,255,255,0.4),inset 4px 0 0 #00E5FF}.msg-block.chat-border{box-shadow:0 8px 32px rgba(0,0,0,0.15),inset 0 1px 1px rgba(255,255,255,0.4),inset 4px 0 0 #10B981}.msg-block.vote-border{box-shadow:0 8px 32px rgba(0,0,0,0.15),inset 0 1px 1px rgba(255,255,255,0.4),inset 4px 0 0 #F59E0B}.msg-block.err-border{box-shadow:0 8px 32px rgba(0,0,0,0.15),inset 0 1px 1px rgba(255,255,255,0.4),inset 4px 0 0 #EF4444}.msg-block.info-border{box-shadow:0 8px 32px rgba(0,0,0,0.15),inset 0 1px 1px rgba(255,255,255,0.4),inset 4px 0 0 #3B82F6}.badge{padding:4px 10px;font-weight:800;font-size:11px;border-radius:20px;margin-right:14px;flex-shrink:0;align-self:center;color:#fff;letter-spacing:0.8px;text-transform:uppercase;box-shadow:0 4px 10px rgba(0,0,0,0.2)}.badge.cmd{background:linear-gradient(135deg,#00E5FF,#0083B0)}.badge.chat{background:linear-gradient(135deg,#10B981,#047857)}.badge.vote{background:linear-gradient(135deg,#F59E0B,#B45309)}.badge.err{background:linear-gradient(135deg,#EF4444,#991B1B)}.badge.info{background:linear-gradient(135deg,#3B82F6,#1D4ED8)}.msg-content{display:flex;flex-direction:column;gap:2px}.username{font-weight:700;font-size:14px;letter-spacing:0.3px;text-shadow:0 1px 4px rgba(0,0,0,0.3)}.username.cmd{color:#40C4FF}.username.chat{color:#34D399}.username.vote{color:#FBBF24}.username.err{color:#FF8A8A}.username.info{color:#60A5FA}.message{color:#fff;font-weight:500;line-height:1.4;font-size:16px;text-shadow:0 1px 3px rgba(0,0,0,0.4)}.msg-block.warn-border{box-shadow:0 8px 32px rgba(0,0,0,0.15),inset 0 1px 1px rgba(255,255,255,0.4),inset 4px 0 0 #EAB308}.badge.warn{background:linear-gradient(135deg,#EAB308,#A16207)}.username.warn{color:#FDE047}.avatar{width:34px;height:34px;border-radius:50%;margin-right:12px;flex-shrink:0;object-fit:cover;align-self:center;box-shadow:0 0 0 2px rgba(255,255,255,0.35)}.avatar-sys{width:34px;height:34px;border-radius:50%;margin-right:12px;flex-shrink:0;align-self:center;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:15px;color:#fff}.avatar-sys.success{background:#10B981;box-shadow:0 0 10px rgba(16,185,129,0.6)}.avatar-sys.fail{background:#EF4444;box-shadow:0 0 10px rgba(239,68,68,0.6)}.avatar-sys.warn{background:#EAB308;box-shadow:0 0 10px rgba(234,179,8,0.6)}.avatar-sys.neutral{background:#71717A;box-shadow:0 0 10px rgba(113,113,122,0.4)}@keyframes popIn{from{transform:translateY(20px) scale(0.95);opacity:0;filter:blur(4px)}to{transform:translateY(0) scale(1);opacity:1;filter:blur(0)}}</style></head><body><div class="chat-box" id="chat"></div><script>let lastId=-1;let fetchingUpdates=!1;let hasConnected=!1;setInterval(function(){if(fetchingUpdates)return;fetchingUpdates=!0;fetch('/history?t='+Date.now()).then(r=>r.json()).then(data=>{try{if(data&&Array.isArray(data)){const c=document.getElementById('chat');if(c){if(!hasConnected){hasConnected=!0;const div=document.createElement('div');div.className='msg-block chat-border';div.innerHTML=`<div class="badge chat">SYS</div><div class="msg-content"><span class="username chat">system</span> <span class="message">ui connected successfully</span></div>`;c.appendChild(div);}const fragment=document.createDocumentFragment();let added=!1;data.forEach(i=>{if(i.id>lastId){lastId=i.id;try{let u=i.u||"Unknown";let m=i.m||"";if(u==='[system]'&&!m.includes('vote')&&!m.includes('[err]')&&!m.includes('[info]')&&!m.includes('waiting')&&!m.includes('ready')&&!m.includes('chat listener')&&!m.includes('running')&&!m.includes('[ban]')&&!m.includes('[warn]'))return;let isCmd=m.trim().startsWith('!');let badgeClass=isCmd?'cmd':'chat';let badgeText=isCmd?'CMD':'CHAT';let borderClass=isCmd?'cmd-border':'chat-border';let unameClass=isCmd?'username cmd':'username chat';let cleanU=u.replace(/^@+/,'');let displayU='@'+cleanU;if(u==='[console]'){displayU='CONSOLE';badgeText='SYS';}else if(u==='[announcement]'){displayU='ANNOUNCEMENT';badgeText='INFO';badgeClass='info';borderClass='info-border';unameClass='username info';}else if(u==='[system]'){displayU='SYSTEM';badgeText='SYS';badgeClass='cmd';borderClass='cmd-border';unameClass='username cmd';if(m.includes('[vote]')){badgeText='VOTE';badgeClass='vote';borderClass='vote-border';unameClass='username vote';}else if(m.includes('[err]')||m.includes('[ban]')){badgeText='ERR';badgeClass='err';borderClass='err-border';unameClass='username err';}else if(m.includes('[warn]')){badgeText='WARN';badgeClass='warn';borderClass='warn-border';unameClass='username warn';}else if(m.includes('[info]')){badgeText='INFO';badgeClass='info';borderClass='info-border';unameClass='username info';}else if(m.includes('running:')){badgeText='EXEC';badgeClass='cmd';borderClass='cmd-border';unameClass='username cmd';}else if(m.includes('[debug]')){badgeText='DBG';badgeClass='cmd';borderClass='cmd-border';unameClass='username cmd';}}let avatarClass=badgeClass==='err'?'fail':(badgeClass==='warn'?'warn':((u==='[system]'&&badgeText==='SYS')?'neutral':'success'));let avatarHtml=i.img?`<img class="avatar" src="${i.img}" onerror="this.style.display='none'">`:`<div class="avatar-sys ${avatarClass}">${avatarClass==='fail'?'&#10005;':(avatarClass==='warn'?'!':(avatarClass==='neutral'?'&#8226;':'&#10003;'))}</div>`;const div=document.createElement('div');div.className=`msg-block ${borderClass}`;div.innerHTML=avatarHtml+`<div class="badge ${badgeClass}">${badgeText}</div><div class="msg-content"><span class="${unameClass}">${displayU}</span> <span class="message">${m}</span></div>`;fragment.appendChild(div);added=!0;}catch(err){}}});if(added){c.appendChild(fragment);window.scrollTo(0,document.body.scrollHeight);while(c.children.length>15)c.removeChild(c.firstChild);}}}}finally{fetchingUpdates=!1;}}).catch(e=>{fetchingUpdates=!1;});},1000);</script></body></html>"""

html_template_oldnew = """<!DOCTYPE html><html><head><meta charset="UTF-8"><style>@import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@500;700&display=swap');html,body{background-color:rgba(0,0,0,0)!important;margin:0;padding:0;width:100%;height:100%;overflow:hidden}body{font-family:'Fira Code','Consolas',monospace;display:flex;flex-direction:column;padding:15px;justify-content:flex-end;box-sizing:border-box}.chat-box{display:flex;flex-direction:column;align-items:flex-end;gap:6px;width:100%}.msg-block{background-color:rgba(0,0,0,0.85);padding:6px 10px;display:flex;align-items:baseline;font-size:16px;border-radius:6px;box-shadow:2px 2px 4px rgba(0,0,0,0.5);animation:slideIn 0.2s ease-out forwards;margin-bottom:2px;max-width:95%;word-wrap:break-word}.msg-block.cmd-border{border-left:5px solid #00e5ff}.msg-block.chat-border{border-left:5px solid #00e676}.msg-block.vote-border{border-left:5px solid orange}.msg-block.err-border{border-left:5px solid #f33}.msg-block.info-border{border-left:5px solid #3B82F6}.badge{padding:2px 6px;font-weight:800;color:#111;font-size:11px;border-radius:3px;margin-right:8px;flex-shrink:0;align-self:flex-start;margin-top:3px}.badge.cmd{background-color:#00e5ff}.badge.chat{background-color:#00e676}.badge.vote{background-color:orange}.badge.err{background-color:#f33;color:#fff}.badge.info{background-color:#3B82F6;color:#fff}.msg-content{display:block;word-break:break-word}.username{font-weight:900;text-shadow:1px 1px 0 rgba(0,0,0,0.8);margin-right:5px}.username.cmd{color:#00e5ff}.username.chat{color:#00e676}.username.vote{color:orange}.username.err{color:#f33}.username.info{color:#60A5FA}.message{color:#fff;font-weight:600;text-shadow:1px 1px 0 rgba(0,0,0,0.8);line-height:1.4}@keyframes slideIn{from{transform:translateX(30px);opacity:0}to{transform:translateX(0);opacity:1}}</style></head><body><div class="chat-box" id="chat"></div><script>let lastId=-1;let fetchingUpdates=!1;let hasConnected=!1;setInterval(function(){if(fetchingUpdates)return;fetchingUpdates=!0;fetch('/history?t='+Date.now()).then(r=>r.json()).then(data=>{try{if(data&&Array.isArray(data)){const c=document.getElementById('chat');if(c){if(!hasConnected){hasConnected=!0;const div=document.createElement('div');div.className='msg-block cmd-border';div.innerHTML=`<div class="badge cmd">SYS</div><div class="msg-content"><span class="username cmd">system</span> <span class="message">connected</span></div>`;c.appendChild(div);}const fragment=document.createDocumentFragment();let added=!1;data.forEach(i=>{if(i.id>lastId){lastId=i.id;try{let u=i.u||"Unknown";let m=i.m||"";if(u==='[system]'&&!m.includes('vote')&&!m.includes('[debug]')&&!m.includes('[err]')&&!m.includes('[info]')&&!m.includes('waiting')&&!m.includes('ready')&&!m.includes('chat listener')&&!m.includes('running')&&!m.includes('[ban]')&&!m.includes('[warn]'))return;let isCmd=m.trim().startsWith('!');let badgeClass=isCmd?'cmd':'chat';let badgeText=isCmd?'CMD':'CHAT';let borderClass=isCmd?'cmd-border':'chat-border';let unameClass=isCmd?'username cmd':'username chat';let cleanU=u.replace(/^@+/,'');let displayU='@'+cleanU;if(u==='[console]'){displayU='CONSOLE';badgeText='SYS';}else if(u==='[announcement]'){displayU='ANNOUNCEMENT';badgeText='INFO';badgeClass='info';borderClass='info-border';unameClass='username info';}else if(u==='[system]'){displayU='SYSTEM';badgeText='SYS';badgeClass='cmd';borderClass='cmd-border';unameClass='username cmd';if(m.includes('[vote]')){badgeText='VOTE';badgeClass='vote';borderClass='vote-border';unameClass='username vote';}else if(m.includes('[err]')||m.includes('[ban]')||m.includes('[warn]')){badgeText='ERR';badgeClass='err';borderClass='err-border';unameClass='username err';}else if(m.includes('[info]')){badgeText='INFO';badgeClass='info';borderClass='info-border';unameClass='username info';}else if(m.includes('running:')){badgeText='EXEC';badgeClass='cmd';borderClass='cmd-border';unameClass='username cmd';}else if(m.includes('[debug]')){badgeText='DBG';badgeClass='cmd';borderClass='cmd-border';unameClass='username cmd';}}const div=document.createElement('div');div.className=`msg-block ${borderClass}`;div.innerHTML=`<div class="badge ${badgeClass}">${badgeText}</div><div class="msg-content"><span class="${unameClass}">${displayU}</span> <span class="message">${m}</span></div>`;fragment.appendChild(div);added=!0;}catch(err){}}});if(added){c.appendChild(fragment);window.scrollTo(0,document.body.scrollHeight);while(c.children.length>20)c.removeChild(c.firstChild);}}}}finally{fetchingUpdates=!1;}}).catch(e=>{fetchingUpdates=!1;});},1000);</script></body></html>"""

html_debugchat = """<!DOCTYPE html><html><head><meta charset="UTF-8"><style>@import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@500;700&display=swap');html,body{background-color:rgba(0,0,0,0)!important;margin:0;padding:0;width:100%;height:100%;overflow:hidden}body{font-family:'Fira Code','Consolas',monospace;display:flex;flex-direction:column;padding:15px;justify-content:flex-end;box-sizing:border-box}.chat-box{display:flex;flex-direction:column;align-items:flex-end;gap:6px;width:100%}.msg-block{background-color:rgba(0,0,0,0.85);padding:6px 10px;display:flex;align-items:baseline;font-size:16px;border-radius:6px;box-shadow:2px 2px 4px rgba(0,0,0,0.5);animation:slideIn 0.2s ease-out forwards;margin-bottom:2px;max-width:95%;word-wrap:break-word}.msg-block.cmd-border{border-left:5px solid #00e5ff}.msg-block.chat-border{border-left:5px solid #00e676}.msg-block.vote-border{border-left:5px solid orange}.msg-block.err-border{border-left:5px solid #f33}.badge{padding:2px 6px;font-weight:800;color:#111;font-size:11px;border-radius:3px;margin-right:8px;flex-shrink:0;align-self:flex-start;margin-top:3px}.badge.cmd{background-color:#00e5ff}.badge.chat{background-color:#00e676}.badge.vote{background-color:orange}.badge.err{background-color:#f33;color:#fff}.msg-content{display:block;word-break:break-word}.username{font-weight:900;text-shadow:1px 1px 0 rgba(0,0,0,0.8);margin-right:5px}.username.cmd{color:#00e5ff}.username.chat{color:#00e676}.username.vote{color:orange}.username.err{color:#f33}.message{color:#fff;font-weight:600;text-shadow:1px 1px 0 rgba(0,0,0,0.8);line-height:1.4}@keyframes slideIn{from{transform:translateX(30px);opacity:0}to{transform:translateX(0);opacity:1}}</style></head><body><div class="chat-box" id="chat"></div><script>let lastId=-1;let fetchingUpdates=!1;setInterval(function(){if(fetchingUpdates)return;fetchingUpdates=!0;fetch('/history?t='+Date.now()).then(r=>r.json()).then(data=>{try{if(data&&Array.isArray(data)){const c=document.getElementById('chat');if(c){const fragment=document.createDocumentFragment();let added=!1;data.forEach(i=>{if(i.id>lastId){lastId=i.id;try{let u=i.u||"Unknown";let m=i.m||"";let isCmd=m.trim().startsWith('!');let badgeClass=isCmd?'cmd':'chat';let badgeText=isCmd?'CMD':'CHAT';let borderClass=isCmd?'cmd-border':'chat-border';let unameClass=isCmd?'username cmd':'username chat';let cleanU=u.replace(/^@+/,'');let displayU='@'+cleanU;if(u==='[console]'){displayU='CONSOLE';badgeText='SYS';}else if(u==='[announcement]'){displayU='ANNOUNCEMENT';badgeText='INFO';badgeClass='cmd';borderClass='cmd-border';unameClass='username cmd';}else if(u==='[system]'){displayU='SYSTEM';badgeText='SYS';badgeClass='cmd';borderClass='cmd-border';unameClass='username cmd';if(m.includes('[vote]')){badgeText='VOTE';badgeClass='vote';borderClass='vote-border';unameClass='username vote';}else if(m.includes('[err]')||m.includes('[ban]')||m.includes('[warn]')){badgeText='ERR';badgeClass='err';borderClass='err-border';unameClass='username err';}else if(m.includes('[info]')){badgeText='INFO';badgeClass='cmd';borderClass='cmd-border';unameClass='username cmd';}else if(m.includes('running:')){badgeText='EXEC';badgeClass='cmd';borderClass='cmd-border';unameClass='username cmd';}else if(m.includes('[debug]')){badgeText='DBG';badgeClass='cmd';borderClass='cmd-border';unameClass='username cmd';}}const div=document.createElement('div');div.className=`msg-block ${borderClass}`;div.innerHTML=`<div class="badge ${badgeClass}">${badgeText}</div><div class="msg-content"><span class="${unameClass}">${displayU}</span> <span class="message">${m}</span></div>`;fragment.appendChild(div);added=!0;}catch(err){}}});if(added){c.appendChild(fragment);window.scrollTo(0,document.body.scrollHeight);while(c.children.length>20)c.removeChild(c.firstChild);}}}}finally{fetchingUpdates=!1;}}).catch(e=>{fetchingUpdates=!1;});},1000);</script></body></html>"""

html_ultradebug = """<!DOCTYPE html><html><head><meta charset="UTF-8"><style>@import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@500;700&display=swap');html,body{background-color:#09090b!important;margin:0;padding:20px;overflow:hidden;font-family:'Fira Code',Consolas,monospace;color:#00FF41}.stats-widget{background:rgba(20,20,25,0.95);border:1px solid #00FF41;border-radius:12px;padding:20px 30px;box-shadow:0 0 15px rgba(0,255,65,0.2)}.stat-row{display:flex;align-items:center;justify-content:space-between;margin:12px 0;gap:40px;border-bottom:1px solid #18181b;padding-bottom:8px}.stat-label{color:#a1a1aa;font-weight:bold;font-size:16px;text-transform:uppercase}.stat-value{color:#00FF41;font-weight:bold;font-size:24px;text-shadow:0 0 8px rgba(0,255,65,0.5)}</style></head><body><div class="stats-widget"><div class="stat-row"><span class="stat-label">QUEUE SIZE</span><span class="stat-value" id="qsize">0</span></div><div class="stat-row"><span class="stat-label">COM LOCKED</span><span class="stat-value" id="comstate">FALSE</span></div><div class="stat-row"><span class="stat-label">ACTIVE THREADS</span><span class="stat-value" id="threads">0</span></div><div class="stat-row"><span class="stat-label">LAST REBUILD</span><span class="stat-value" id="rebuild">0s ago</span></div><div class="stat-row"><span class="stat-label">FAILED ACTIONS</span><span class="stat-value" style="color:#FF3333" id="failed">0</span></div></div><script>setInterval(function(){fetch('/debug_data?t='+Date.now()).then(r=>r.json()).then(data=>{document.getElementById('qsize').innerText=data.qsize;document.getElementById('comstate').innerText=data.comstate;document.getElementById('threads').innerText=data.threads;document.getElementById('rebuild').innerText=data.rebuild;document.getElementById('failed').innerText=data.failed;}).catch(e=>{});},500);</script></body></html>"""

html_stats = """<!DOCTYPE html><html><head><meta charset="UTF-8"><style>@import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@500;700&display=swap');html,body{background-color:rgba(0,0,0,0)!important;margin:0;padding:20px;overflow:hidden;font-family:'Fira Code',Consolas,monospace}.stats-widget{background:rgba(20,20,25,0.85);backdrop-filter:blur(8px);border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:20px 30px;display:inline-block;box-shadow:0 10px 25px rgba(0,0,0,0.5)}.stat-row{display:flex;align-items:center;justify-content:space-between;margin:12px 0;gap:40px}.stat-label{color:#a1a1aa;font-weight:bold;font-size:16px;text-transform:uppercase;letter-spacing:1px}.stat-value{color:#fff;font-weight:bold;font-size:24px;text-shadow:0 0 10px rgba(255,255,255,0.2)}.stat-row.cmds .stat-value{color:#00E5FF;text-shadow:0 0 10px rgba(0,229,255,0.3)}.stat-row.views .stat-value{color:#3B82F6;text-shadow:0 0 10px rgba(59,130,246,0.3)}.stat-row.likes .stat-value{color:#10B981;text-shadow:0 0 10px rgba(16,185,129,0.3)}.stat-row.errs .stat-value{color:#EF4444;text-shadow:0 0 10px rgba(239,68,68,0.3)}.version-tag{font-size:12px;color:#52525b;text-align:right;margin-top:15px;font-weight:bold;border-top:1px solid #3f3f46;padding-top:10px}</style></head><body><div class="stats-widget"><div class="stat-row"><span class="stat-label">UPTIME</span><span class="stat-value" id="uptime">0d 0h 0m 0s</span></div><div class="stat-row views"><span class="stat-label">VIEWERS</span><span class="stat-value" id="viewers">0</span></div><div class="stat-row likes"><span class="stat-label">LIKES</span><span class="stat-label" id="likes">0</span></div><div class="stat-row cmds"><span class="stat-label">CMDS EXECUTED</span><span class="stat-value" id="cmds">0</span></div><div class="stat-row errs"><span class="stat-label">FAILED CMDS</span><span class="stat-value" id="failed">0</span></div><div class="version-tag">{{ version }}</div></div><script>setInterval(function(){fetch('/stats_data?t='+Date.now()).then(r=>r.json()).then(data=>{document.getElementById('uptime').innerText=data.uptime;document.getElementById('cmds').innerText=data.commands;document.getElementById('failed').innerText=data.failed;if(document.getElementById('viewers'))document.getElementById('viewers').innerText=data.viewers||"0";if(document.getElementById('likes'))document.getElementById('likes').innerText=data.likes||"0";}).catch(e=>{});},1000);</script></body></html>"""


# ========================= WEB / MULTISTREAM DASHBOARD (Flask, from chatuses.py) =========================
# All eight OBS/browser-source overlay pages from chatuses.py, "mixed" together into one Flask
# app so every overlay style (Legacy, Liquid Glass, Classic Dark, Ultra Debug, Debug Chat, Stats)
# is available from a single running instance, picked via the Multistream Dashboard link page (/).
# Controlled from the "🖧 VNC / Web" tab: pick a port 5900-5999, Start/Stop, then "Open" launches
# the dashboard (/) in your browser.

def _parse_song_artist_title(desc):
    """Best-effort split of a YouTube video title into (artist, title), for the
    !sr Now Playing overlay. Handles the common 'Artist - Title' upload format;
    falls back to putting the whole string in the title slot."""
    desc = (desc or "").strip()
    if not desc:
        return "", ""
    for sep in (" - ", " – ", " — ", " | "):
        if sep in desc:
            artist, title = desc.split(sep, 1)
            return artist.strip(), title.strip()
    return "", desc

html_overlay_votes = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>OBS Vote Overlay</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }

        html, body {
            background-color: transparent;
            width: 320px;
            overflow: hidden;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            color: white;
            padding: 10px;
        }

        .vote-box {
            border-radius: 10px;
            padding: 15px;
            margin-bottom: 15px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.9);
            transform: translateZ(0);
        }

        /* RESTART — green */
        #restart-box {
            background-color: #0a2a12;
            border: 2px solid #00ff87;
        }

        #restart-box .vote-title  { color: #00ff87; text-shadow: 0 0 10px rgba(0,255,135,0.8); }
        #restart-box .vote-info   { color: #ccffdd; }
        #restart-box .vote-info.timer { color: #aaffcc; }
        #restart-box .progress-container { background-color: #0a2010; border: 1px solid #00aa55; }
        #restart-box .progress-bar {
            background: linear-gradient(90deg, #00aa55, #00ff87);
            box-shadow: 0 0 8px #00ff87;
        }

        /* REVERT — blue */
        #revert-box {
            background-color: #0a1a3a;
            border: 2px solid #00aaff;
        }

        #revert-box .vote-title  { color: #00aaff; text-shadow: 0 0 10px rgba(0,170,255,0.8); }
        #revert-box .vote-info   { color: #cceeff; }
        #revert-box .vote-info.timer { color: #aaddff; }
        #revert-box .progress-container { background-color: #071525; border: 1px solid #0066aa; }
        #revert-box .progress-bar {
            background: linear-gradient(90deg, #0066cc, #00aaff);
            box-shadow: 0 0 8px #00aaff;
        }

        .vote-title {
            font-size: 18px;
            font-weight: bold;
            text-align: center;
            margin-bottom: 10px;
        }

        .vote-info {
            font-size: 15px;
            font-weight: 700;
            text-align: center;
            margin-bottom: 5px;
        }

        .vote-info.timer {
            font-size: 13px;
            font-weight: 600;
        }

        .progress-container {
            border-radius: 10px;
            width: 100%;
            height: 12px;
            margin-top: 10px;
            overflow: hidden;
        }

        .progress-bar {
            height: 100%;
            width: 0%;
            transition: width 0.3s ease;
        }
    </style>
</head>
<body>

    <div class="vote-box" id="restart-box">
        <div class="vote-title">⟳ Restart Vote</div>
        <div class="vote-info" id="restart-collected">0 / 2 votes</div>
        <div class="vote-info timer" id="restart-time">Waiting...</div>
        <div class="progress-container">
            <div class="progress-bar" id="restart-bar"></div>
        </div>
    </div>

    <div class="vote-box" id="revert-box">
        <div class="vote-title">↩ Revert Vote</div>
        <div class="vote-info" id="revert-collected">0 / 2 votes</div>
        <div class="vote-info timer" id="revert-time">Waiting...</div>
        <div class="progress-container">
            <div class="progress-bar" id="revert-bar"></div>
        </div>
    </div>

    <script>
        const state = {
            restartvm: { remaining: 0, interval: null, required: 2, current: 0 },
            revert:    { remaining: 0, interval: null, required: 2, current: 0 }
        };

        const elements = {
            restartvm: {
                box:       document.getElementById('restart-box'),
                collected: document.getElementById('restart-collected'),
                time:      document.getElementById('restart-time'),
                bar:       document.getElementById('restart-bar')
            },
            revert: {
                box:       document.getElementById('revert-box'),
                collected: document.getElementById('revert-collected'),
                time:      document.getElementById('revert-time'),
                bar:       document.getElementById('revert-bar')
            }
        };

        function updateDisplay(type) {
            const s = state[type];
            const el = elements[type];
            const active = s.remaining > 0;
            el.collected.textContent = `${s.current} / ${s.required} votes`;
            el.time.textContent = active ? `⏱ ${s.remaining}s remaining` : 'Waiting...';
            const pct = s.required > 0 ? (s.current / s.required) * 100 : 0;
            el.bar.style.width = Math.min(pct, 100) + '%';
        }

        function startClientCountdown(type, fromSeconds) {
            const s = state[type];
            if (s.interval) { clearInterval(s.interval); s.interval = null; }
            s.remaining = fromSeconds;
            updateDisplay(type);
            if (fromSeconds <= 0) return;
            s.interval = setInterval(() => {
                if (s.remaining > 0) {
                    s.remaining--;
                    updateDisplay(type);
                } else {
                    clearInterval(s.interval);
                    s.interval = null;
                    updateDisplay(type);
                }
            }, 1000);
        }

        function syncFromServer(type, serverRemaining, serverCurrent, serverRequired) {
            const s = state[type];
            s.current  = serverCurrent;
            s.required = serverRequired;
            const diff = Math.abs(serverRemaining - s.remaining);
            if (serverRemaining <= 0) {
                if (s.interval) { clearInterval(s.interval); s.interval = null; }
                s.remaining = 0;
                updateDisplay(type);
            } else if (!s.interval || diff > 2) {
                startClientCountdown(type, serverRemaining);
            } else {
                updateDisplay(type);
            }
        }

        function fetchVotes() {
            fetch('votes.json?t=' + Date.now())
                .then(r => r.json())
                .then(data => {
                    syncFromServer('restartvm',
                        data.restartvm.remaining_time,
                        data.restartvm.current,
                        data.restartvm.required
                    );
                    syncFromServer('revert',
                        data.revert.remaining_time,
                        data.revert.current,
                        data.revert.required
                    );
                })
                .catch(() => {});
        }

        setInterval(fetchVotes, 2000);
        fetchVotes();
    </script>
</body>
</html>"""


html_ban_vote_overlay = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Ban Vote Overlay</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }

        html, body {
            background-color: transparent;
            width: 320px;
            overflow: hidden;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            color: white;
            padding: 10px;
        }

        .vote-box {
            border-radius: 10px;
            padding: 15px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.9);
            transform: translateZ(0);
        }

        /* BAN — red, matching this bot's existing ban-vote color scheme */
        #ban-box {
            background-color: #2a0a0a;
            border: 2px solid #ff4444;
        }

        #ban-box .vote-title  { color: #ff4444; text-shadow: 0 0 10px rgba(255,68,68,0.8); }
        #ban-box .vote-info   { color: #ffdddd; }
        #ban-box .vote-info.timer { color: #ffaaaa; }
        #ban-box .progress-container { background-color: #200a0a; border: 1px solid #aa0000; }
        #ban-box .progress-bar {
            background: linear-gradient(90deg, #aa0000, #ff4444);
            box-shadow: 0 0 8px #ff4444;
        }

        .vote-title {
            font-size: 18px;
            font-weight: bold;
            text-align: center;
            margin-bottom: 10px;
        }

        .vote-info {
            font-size: 15px;
            font-weight: 700;
            text-align: center;
            margin-bottom: 5px;
        }

        .vote-info.timer {
            font-size: 13px;
            font-weight: 600;
        }

        .progress-container {
            border-radius: 10px;
            width: 100%;
            height: 12px;
            margin-top: 10px;
            overflow: hidden;
        }

        .progress-bar {
            height: 100%;
            width: 0%;
            transition: width 0.3s ease;
        }
    </style>
</head>
<body>
    <div class="vote-box" id="ban-box">
        <div class="vote-title">🚫 Ban Vote</div>
        <div class="vote-info" id="ban-collected">No ban vote active — 0 / 3 votes</div>
        <div class="vote-info timer" id="ban-time">Waiting...</div>
        <div class="progress-container">
            <div class="progress-bar" id="ban-bar"></div>
        </div>
    </div>

    <script>
        const s = { remaining: 0, interval: null, required: 3, current: 0, target: null };
        const el = {
            collected: document.getElementById('ban-collected'),
            time:      document.getElementById('ban-time'),
            bar:       document.getElementById('ban-bar')
        };

        function updateDisplay() {
            const label = s.target ? `Ban @${s.target}` : 'No ban vote active';
            el.collected.textContent = `${label} — ${s.current} / ${s.required} votes`;
            el.time.textContent = s.remaining > 0 ? `⏱ ${s.remaining}s remaining` : 'Waiting...';
            const pct = s.required > 0 ? (s.current / s.required) * 100 : 0;
            el.bar.style.width = Math.min(pct, 100) + '%';
        }

        function startClientCountdown(fromSeconds) {
            if (s.interval) { clearInterval(s.interval); s.interval = null; }
            s.remaining = fromSeconds;
            updateDisplay();
            if (fromSeconds <= 0) return;
            s.interval = setInterval(() => {
                if (s.remaining > 0) {
                    s.remaining--;
                    updateDisplay();
                } else {
                    clearInterval(s.interval);
                    s.interval = null;
                    updateDisplay();
                }
            }, 1000);
        }

        function fetchBanVote() {
            fetch('/banvote_data?t=' + Date.now())
                .then(r => r.json())
                .then(data => {
                    s.target   = data.target;
                    s.current  = data.current;
                    s.required = data.required;
                    const serverRemaining = Math.round(data.remaining_time);
                    const diff = Math.abs(serverRemaining - s.remaining);
                    if (serverRemaining <= 0) {
                        if (s.interval) { clearInterval(s.interval); s.interval = null; }
                        s.remaining = 0;
                        updateDisplay();
                    } else if (!s.interval || diff > 2) {
                        startClientCountdown(serverRemaining);
                    } else {
                        updateDisplay();
                    }
                })
                .catch(() => {});
        }

        setInterval(fetchBanVote, 2000);
        fetchBanVote();
    </script>
</body>
</html>"""


html_nowplaying = """<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Now Playing</title>
<style>
@font-face { font-family: 'Avenir'; src: local('Avenir'), local('Avenir Next'), local('Avenir LT Std'); }
html,body{margin:0;padding:0;background:transparent;width:100%;height:100%;overflow:hidden;}
#np{position:fixed;left:24px;bottom:24px;max-width:640px;font-family:'Avenir','Avenir Next','Segoe UI',sans-serif;
    color:#ffffff;text-shadow:0 2px 6px rgba(0,0,0,0.85);text-transform:uppercase;
    opacity:0;transition:opacity 0.6s ease;}
#np.show{opacity:1;}
#np .label{font-size:12px;letter-spacing:2px;color:#00E5FF;margin-bottom:4px;font-weight:600;}
#np .title{font-size:26px;font-weight:bold;line-height:1.15;}
#np .artist{font-size:16px;font-weight:400;color:#d4d4d8;margin-top:2px;}
</style></head>
<body>
<div id="np">
  <div class="label">NOW PLAYING</div>
  <div class="title" id="np-title"></div>
  <div class="artist" id="np-artist"></div>
</div>
<script>
const params = new URLSearchParams(window.location.search);
const testMode = params.get('test') === '1';
async function poll() {
  try {
    const el = document.getElementById('np');
    const t = document.getElementById('np-title');
    const a = document.getElementById('np-artist');
    if (testMode) {
      t.textContent = 'BLINDING LIGHTS';
      a.textContent = 'THE WEEKND';
      el.classList.add('show');
      return;
    }
    const res = await fetch('/nowplaying_data');
    const data = await res.json();
    if (data.playing && data.title) {
      t.textContent = data.title;
      a.textContent = data.artist || '';
      a.style.display = data.artist ? 'block' : 'none';
      el.classList.add('show');
    } else {
      el.classList.remove('show');
    }
  } catch (e) { /* ignore transient fetch errors */ }
}
poll();
setInterval(poll, 3000);
</script>
</body></html>"""

def _flask_nowplaying_payload():
    artist, title = _parse_song_artist_title(music_current_desc)
    is_playing = False
    try:
        is_playing = bool(music_current_desc) and music_media_player is not None and music_media_player.is_playing()
    except Exception:
        is_playing = bool(music_current_desc)
    return {"playing": is_playing, "title": title.upper(), "artist": artist.upper()}

def _flask_ban_vote_payload():
    """Reads straight from the live in-memory ban_votes dict -- unlike ban_vote.html
    on disk, this always has a real answer (0/required, no active vote) even before
    the bot has started or any ban vote has ever happened."""
    required = get_vote_threshold("ban_votes", 3)
    if not ban_votes:
        return {"target": None, "current": 0, "required": required, "remaining_time": 0}
    target, info = next(iter(ban_votes.items()))
    current = len(info.get("voters", []))
    remaining = max(0, VOTE_TIMEOUT - (time.time() - info.get("start_time", time.time())))
    return {"target": target, "current": current, "required": required, "remaining_time": remaining}

FLASK_CONFIG_FILE = "flask_dashboard_config.json"
FLASK_CONFIG = {"port": 5900}


def load_flask_config():
    global FLASK_CONFIG
    try:
        if os.path.exists(FLASK_CONFIG_FILE):
            with open(FLASK_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            FLASK_CONFIG.update(data)
    except Exception:
        pass

def save_flask_config():
    safe_json_dump(FLASK_CONFIG_FILE, FLASK_CONFIG)

load_flask_config()

_flask_app = None
_flask_thread = None
_flask_running = False
_flask_lock = threading.Lock()

def post_queue_to_overlay(label, requests_list, active_queue):
    """Formats the current Music (!srqueue) or Video (!vrqueue) request queue and posts it
    into the chat overlay (overlay_data['chat']) so it shows up in chat.html / the Flask
    dashboard's /history feed, same as any other chat/system message."""
    parts = []
    if active_queue:
        parts.append(f"{len(active_queue)} item(s) currently queued/playing")
    if requests_list:
        for i, r in enumerate(requests_list[:10], 1):
            who = f" (req by {r.get('user')})" if r.get("user") else ""
            parts.append(f"{i}. {r.get('raw') or r.get('url', '')}{who}")
    else:
        parts.append("no pending requests")
    msg_text = f"[{label}] " + " | ".join(parts)
    print(msg_text)
    update_overlay(author="[system]", message=msg_text, msg_id=f"{label.lower().replace(' ', '')}-{time.time()}")
    return msg_text

def _flask_history_payload():
    """Adapts the bot's existing overlay_data['chat'] ring buffer (author/message/seq) into the
    {id,u,m,is_owner,is_admin} shape all of the mixed-in HTML templates expect. Uses the
    stable, ever-increasing 'seq' number (not list position) as the id -- list position
    shifts every time an old message is evicted, which made the overlay JS think nothing
    new had arrived and stop updating."""
    out = []
    for item in overlay_data.get("chat", []):
        author = str(item.get("author", ""))
        out.append({
            "id": item.get("seq", 0),
            "u": author,
            "m": str(item.get("message", "")),
            "is_owner": author.lower() == ADMIN_USERNAME.lower() if ADMIN_USERNAME else False,
            "is_admin": False,
        })
    return out

def _flask_status_payload():
    vote_active = bool(vote_restart) or bool(vote_revert) or bool(ban_votes)
    vote_text = ""
    if vote_restart:
        vote_text = f"[vote] restart {len(vote_restart)}/{PERMISSIONS_CONFIG.get('restart_votes', 2)}"
    elif vote_revert:
        vote_text = f"[vote] revert {len(vote_revert)}/{PERMISSIONS_CONFIG.get('revert_votes', 2)}"
    elif ban_votes:
        vote_text = "[vote] ban in progress"
    return {
        "status": overlay_data.get("running_command") or "Running",
        "vote": {"active": vote_active, "text": vote_text},
        "viewers": overlay_data.get("viewers"),
        "likes": overlay_data.get("likes"),
        "chat_visible": True,
        "split_mode": False,
    }

def build_flask_app():
    """Builds (once) the Flask app with every mixed-in overlay route."""
    global _flask_app
    if _flask_app is not None:
        return _flask_app
    if not flask_available:
        return None
    app = Flask(__name__)
    if flask_cors_available and _FlaskCORS is not None:
        _FlaskCORS(app)
    else:
        @app.after_request
        def _add_cors_headers(response):
            response.headers['Access-Control-Allow-Origin'] = '*'
            return response

    @app.route('/')
    def index_page(): return render_template_string(html_index)
    @app.route('/obs')
    def obs_overlay(): return render_template_string(html_template)
    @app.route('/obs2')
    def obs_overlay2(): return render_template_string(html_template_2)
    @app.route('/obsnew')
    def obs_overlay_new(): return render_template_string(html_template_new)
    @app.route('/oldobsnew')
    def obs_overlay_oldnew(): return render_template_string(html_template_oldnew)
    @app.route('/debugchat')
    def obs_overlay_debugchat(): return render_template_string(html_debugchat)
    @app.route('/ultradebug')
    def ultradebug_overlay(): return render_template_string(html_ultradebug)
    @app.route('/stats')
    def stats_overlay(): return render_template_string(html_stats, version="UltraBot")
    @app.route('/stats_data')
    def get_stats_data():
        uptime_sec = int(time.time() - _flask_start_time[0])
        d, r = divmod(uptime_sec, 86400)
        h, r = divmod(r, 3600)
        m, s = divmod(r, 60)
        uptime_str = f"{d}d {h}h {m}m {s}s" if d > 0 else f"{h}h {m}m {s}s"
        return jsonify({"uptime": uptime_str, "commands": _stats.get("total_commands", 0),
                         "failed": _stats.get("failed_commands", 0),
                         "viewers": overlay_data.get("viewers"), "likes": overlay_data.get("likes")})
    @app.route('/debug_data')
    def get_debug_data():
        return jsonify({"qsize": "UNLIMITED", "comstate": "TRUE" if bot_stop_event and not bot_stop_event.is_set() else "FALSE",
                         "threads": threading.active_count(), "rebuild": "0s ago",
                         "failed": _stats.get("failed_commands", 0)})
    @app.route('/history')
    def get_history(): return jsonify(_flask_history_payload())
    @app.route('/status_update')
    def get_status_update(): return jsonify(_flask_status_payload())
    @app.route('/nowplaying')
    def nowplaying_overlay(): return render_template_string(html_nowplaying)
    @app.route('/nowplaying_data')
    def nowplaying_data(): return jsonify(_flask_nowplaying_payload())

    # ── The other overlay boxes the bot already writes to disk (STATUS_FILE,
    #    VOTE_FILE_BAN, OS_VOTE_STATUS_FILE) -- served here too so they're reachable
    #    from the Flask dashboard/port, not just the plain static file server. These
    #    read the live on-disk file each request, so they always match whatever the
    #    file server on 8083 is currently showing. ──
    def _read_overlay_file(path, label):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return (f"<html><body style='background:transparent;color:#888;"
                    f"font-family:sans-serif;padding:20px;'>{label} hasn't been "
                    f"written yet -- it appears once the bot has something to show "
                    f"here.<script>setTimeout(()=>location.reload(),3000)</script>"
                    f"</body></html>")

    @app.route('/status')
    def status_overlay_box(): return _read_overlay_file(STATUS_FILE, "Status")
    @app.route('/osvotestatus')
    def os_vote_status_overlay_box(): return _read_overlay_file(OS_VOTE_STATUS_FILE, "OS vote status")
    @app.route('/votes-overlay')
    def votes_overlay_box(): return render_template_string(html_overlay_votes)
    @app.route('/votes.json')
    def votes_json_data(): return jsonify(_votes_state)

    # !ban vote box -- embedded template + live data endpoint, same pattern as
    # /votes-overlay above, so the PAGE itself is always available immediately
    # (not dependent on ban_vote.html having been written to disk yet, which only
    # happens once an actual ban vote starts or the bot has fully started).
    @app.route('/banvote')
    def ban_vote_overlay_box(): return render_template_string(html_ban_vote_overlay)
    @app.route('/banvote_data')
    def ban_vote_data(): return jsonify(_flask_ban_vote_payload())

    _flask_app = app
    return app

_flask_start_time = [time.time()]

def start_flask_server(port=None):
    """Starts the Flask dashboard in a daemon thread on the given port (5900-5999).
    Safe to call multiple times -- no-ops if already running."""
    global _flask_thread, _flask_running
    with _flask_lock:
        if _flask_running:
            return True, "already running"
        if not flask_available:
            return False, "flask is not installed (pip install flask flask-cors)"
        p = int(port if port is not None else FLASK_CONFIG.get("port", 5900))
        if not (5900 <= p <= 5999):
            return False, "port must be between 5900 and 5999"
        app = build_flask_app()
        if app is None:
            return False, "flask app failed to build"
        FLASK_CONFIG["port"] = p
        save_flask_config()
        _flask_start_time[0] = time.time()

        def _run():
            global _flask_running
            _flask_running = True
            try:
                app.run(host="0.0.0.0", port=p, debug=False, use_reloader=False, threaded=True)
            except Exception as e:
                print(f'[FlaskDashboard] Server error: Python exception: "{traceback.format_exc()}"')
            finally:
                _flask_running = False

        _flask_thread = threading.Thread(target=_run, daemon=True, name="flask_dashboard")
        _flask_thread.start()
        return True, f"starting on port {p}"

def stop_flask_server():
    """Flask's dev server has no clean programmatic stop; since it's a daemon thread it dies
    with the process. We just mark it not-running for UI purposes and note a restart is needed."""
    global _flask_running
    _flask_running = False
    return True, "marked stopped (restart the bot to fully release the port)"

def open_flask_dashboard(port=None):
    p = int(port if port is not None else FLASK_CONFIG.get("port", 5900))
    webbrowser.open(f"http://localhost:{p}/")


def _canonical_script_path():
    """Resolves to the TRUE main script file, even if the currently running process
    is itself an already-spawned derivative (a "_flaskNNNN.py" or
    "_autostarteverything.py" copy) -- otherwise spawning again from inside one of
    those windows would copy whatever was frozen into that derivative at the time
    IT was created, not your latest edits to the real file."""
    script_path = os.path.abspath(sys.argv[0])
    folder = os.path.dirname(script_path)
    name, ext = os.path.splitext(os.path.basename(script_path))
    canonical_name = re.sub(r'_flask\d+$', '', name)
    canonical_name = re.sub(r'_autostarteverything$', '', canonical_name)
    canonical_path = os.path.join(folder, canonical_name + ext)
    if canonical_path != script_path and os.path.exists(canonical_path):
        return canonical_path
    return script_path

def spawn_flask_multistream(port):
    """Copies the canonical main script to a new file and launches it as its own
    detached process with --flaskport=<port>, exactly like chatuses.py's
    spawn_multistream did for extra YouTube streams. The spawned instance runs its
    own full copy of the bot and, because it sees --flaskport on its argv,
    auto-starts the Flask dashboard on that port and opens it in your browser once
    its window is ready -- you don't have to click Start again."""
    try:
        console_log("INFO", f"[WebDashboard] spawning multi-instance for port {port}...")

        # Kill any instance we already spawned for this exact port -- otherwise it
        # stays alive as an orphan and keeps serving its old code on that port,
        # which looks exactly like "the update didn't take" even though it did.
        global _gui_app
        if _gui_app is not None:
            old_proc = getattr(_gui_app, "_flask_spawned_procs", {}).get(port)
            if old_proc is not None and old_proc.poll() is None:
                console_log("INFO", f"[WebDashboard] stopping the previous instance on port {port} first...")
                try:
                    old_proc.terminate()
                    old_proc.wait(timeout=5)
                except Exception:
                    try: old_proc.kill()
                    except Exception: pass

        script_path = _canonical_script_path()
        base_dir, base_name = os.path.dirname(script_path), os.path.basename(script_path)
        name, ext = os.path.splitext(base_name)
        multi_script_path = os.path.join(base_dir, f"{name}_flask{port}{ext}")
        try:
            shutil.copyfile(script_path, multi_script_path)
        except Exception as e:
            console_log("ERROR", f"[WebDashboard] failed to copy script: {e}. using original.")
            multi_script_path = script_path
        args = [sys.executable, multi_script_path, f"--flaskport={port}"]
        if platform.system() == "Windows":
            proc = subprocess.Popen(args, creationflags=0x00000010, close_fds=True)  # CREATE_NEW_CONSOLE
        else:
            proc = subprocess.Popen(args, start_new_session=True, close_fds=True)
        console_log("INFO", f"[WebDashboard] spawned new instance on port {port}: {multi_script_path}")
        return True, proc
    except Exception as e:
        console_log("ERROR", f'[WebDashboard] spawn_flask_multistream crashed: Python exception: "{traceback.format_exc()}"')
        return False, str(e)



# ========================= SCANCODES =========================
SCANCODES = {
    "esc": ("01","81"), "tab": ("0f","8f"), "enter": ("1c","9c"), "space": ("39","b9"),
    "backspace": ("0e","8e"), "delete": ("53","d3"), "del": ("53","d3"),
    "insert": ("52","d2"), "home": ("47","c7"), "end": ("4f","cf"),
    "pageup": ("49","c9"), "pagedown": ("51","d1"),
    "ctrl": ("1d","9d"), "alt": ("38","b8"), "shift": ("2a","aa"), "capslock": ("3a","ba"),
    "win": ("e05b","e0db"), "super": ("e05b","e0db"),
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
}

def parse_combo_keys(args):
    """Splits a combo argument string into individual key names, accepting THREE
    interchangeable input styles: space-separated ('win r'), plus-separated
    ('win+r'), or no separator at all ('winr'). Used everywhere !combo/!winkey
    (and anything else taking a multi-key argument) parses its input, so all of
    them get all three styles consistently from one place.

    If a space or '+' is present anywhere, that's unambiguous -- just split on it.
    Only when there's NO separator at all does this fall back to a greedy
    longest-match scan against known key names in SCANCODES (checked longest name
    first, so e.g. "win" matches before a shorter key that happens to be a
    prefix would). This keeps things safe: a combo that's already properly
    delimited is never at risk of being creatively re-split."""
    text = (args or "").strip().lower()
    if not text:
        return []
    if ' ' in text or '+' in text:
        return [k for k in text.replace('+', ' ').split() if k]
    known_keys = sorted(SCANCODES.keys(), key=len, reverse=True)
    result = []
    i = 0
    while i < len(text):
        for k in known_keys:
            if text.startswith(k, i):
                result.append(k)
                i += len(k)
                break
        else:
            # Nothing matched at this position -- stop here rather than loop
            # forever; whatever's left becomes one final (likely unrecognized)
            # token, same as how a single unknown key is already handled.
            result.append(text[i:])
            break
    return result

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
    """Locates VBoxManage, VirtualBox's command-line control tool."""
    possible_paths = [
        r"C:\Program Files\Oracle\VirtualBox\VBoxManage.exe",
        r"C:\Program Files (x86)\Oracle\VirtualBox\VBoxManage.exe",
        r"D:\Program Files\Oracle\VirtualBox\VBoxManage.exe",
        r"E:\Program Files\Oracle\VirtualBox\VBoxManage.exe",
        "/Applications/VirtualBox.app/Contents/MacOS/VBoxManage",
        "/usr/bin/VBoxManage", "/usr/local/bin/VBoxManage",
    ]
    for path in possible_paths:
        if os.path.exists(path):
            return path
    return "VBoxManage"  # fall back to PATH resolution

VMRUN_TARGET_TYPE = "fusion" if platform.system() == "Darwin" else "ws"
# vmrun's -T flag identifies which VMware product is being driven -- 'ws' (Workstation)
# on Windows/Linux, 'fusion' (VMware Fusion) on macOS.

def get_vmrun_path():
    """Locates vmrun.exe, VMware Workstation's command-line control tool -- this script
    is VBox-first, but OS Voting rows (and the single-VM config) can ALSO point at a
    VMware VM, so this needs to be findable here too, not just in the VMware-flavored
    script."""
    possible_paths = [
        r"C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe",
        r"C:\Program Files\VMware\VMware Workstation\vmrun.exe",
        r"D:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe",
        r"E:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe",
        "/Applications/VMware Fusion.app/Contents/Library/vmrun",
        "/usr/bin/vmrun", "/usr/local/bin/vmrun",
    ]
    for path in possible_paths:
        if os.path.exists(path):
            return path
    return None

# vmrun has no "list all registered VMs" command (only running ones), so VMware VMs
# are tracked locally by alias -> .vmx path, the same approach the VMware-styled bot uses.
VMRUN_VM_REGISTRY_FILE = "vmware_vms.json"

def _load_vmware_vm_registry():
    try:
        if os.path.exists(VMRUN_VM_REGISTRY_FILE):
            with open(VMRUN_VM_REGISTRY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f'[VMware VM Registry] Load error: Python exception: "{traceback.format_exc()}"')
    return {}

def _save_vmware_vm_registry(registry):
    try:
        with open(VMRUN_VM_REGISTRY_FILE, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f'[VMware VM Registry] Save error: Python exception: "{traceback.format_exc()}"')

def register_vmware_vm(vmx_path, alias=None):
    registry = _load_vmware_vm_registry()
    alias = alias or os.path.splitext(os.path.basename(vmx_path))[0]
    registry[alias] = vmx_path
    _save_vmware_vm_registry(registry)
    return alias

def get_all_vmware_vms(vmrun_path=None):
    """Returns known .vmx paths: everything in the local registry, plus anything vmrun
    currently reports as running (auto-registered if not already known)."""
    vmrun_path = vmrun_path or VMRUN_PATH
    registry = _load_vmware_vm_registry()
    vms = list(registry.values())
    if vmrun_path:
        try:
            res = subprocess.run([vmrun_path, "-T", VMRUN_TARGET_TYPE, "list"], capture_output=True, text=True, timeout=5)
            for line in res.stdout.splitlines():
                line = line.strip()
                if line.lower().endswith(".vmx") and line not in vms:
                    vms.append(line)
                    register_vmware_vm(line)
        except Exception: pass
    return vms

def vmware_is_running(vmx_path, vmrun_path=None):
    vmrun_path = vmrun_path or VMRUN_PATH
    if not vmx_path or not vmrun_path:
        return False
    try:
        result = subprocess.run([vmrun_path, "-T", VMRUN_TARGET_TYPE, "list"], capture_output=True, text=True, timeout=15)
        return vmx_path.lower() in result.stdout.lower()
    except Exception as e:
        print(f'[VMRun] list error: Python exception: "{traceback.format_exc()}"')
        return False

def vmware_start(vmx_path, gui=True, vmrun_path=None):
    vmrun_path = vmrun_path or VMRUN_PATH
    return subprocess.run([vmrun_path, "-T", VMRUN_TARGET_TYPE, "start", vmx_path, "gui" if gui else "nogui"], capture_output=True, text=True, timeout=30)

def vmware_stop(vmx_path, hard=True, vmrun_path=None):
    vmrun_path = vmrun_path or VMRUN_PATH
    return subprocess.run([vmrun_path, "-T", VMRUN_TARGET_TYPE, "stop", vmx_path, "hard" if hard else "soft"], capture_output=True, text=True, timeout=20)

def vmware_reset(vmx_path, vmrun_path=None):
    vmrun_path = vmrun_path or VMRUN_PATH
    return subprocess.run([vmrun_path, "-T", VMRUN_TARGET_TYPE, "reset", vmx_path, "hard"], capture_output=True, text=True, timeout=20)

def vmware_revert_to_snapshot(vmx_path, snapshot_name, vmrun_path=None):
    vmrun_path = vmrun_path or VMRUN_PATH
    return subprocess.run([vmrun_path, "-T", VMRUN_TARGET_TYPE, "revertToSnapshot", vmx_path, snapshot_name], capture_output=True, text=True, timeout=60)

def vmware_take_snapshot(vmx_path, snapshot_name, vmrun_path=None):
    vmrun_path = vmrun_path or VMRUN_PATH
    return subprocess.run([vmrun_path, "-T", VMRUN_TARGET_TYPE, "snapshot", vmx_path, snapshot_name], capture_output=True, text=True, timeout=60)

def vmware_toggle_internet(enable, vmrun_path=None):
    """Host-wide VMware NAT Service toggle -- matches the mechanism used in the
    VMware-flavored script (net start/stop), since vmrun has no live per-VM
    connectionType override exposed the way this codebase's VBox internet toggle does.

    macOS: VMware Fusion has no Windows-style service -- NAT networking runs under a
    LaunchDaemon (com.vmware.launchd.vmnet). launchctl needs admin privileges, and raw
    subprocess sudo doesn't work from a GUI app, so this uses osascript's "with
    administrator privileges" to pop the native macOS auth dialog instead.
    HONEST NOTE: the exact LaunchDaemon label can vary by Fusion version -- if this fails,
    check `sudo launchctl list | grep vmware` on your machine and adjust to match."""
    if platform.system() == "Darwin":
        verb = "start" if enable else "stop"
        script = f'do shell script "launchctl {verb} com.vmware.launchd.vmnet" with administrator privileges'
        try:
            return subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30)
        except Exception as e:
            return subprocess.CompletedProcess([], 1, "", str(e))
    try:
        args = ["net", "start" if enable else "stop", "VMware NAT Service"]
        return subprocess.run(args, capture_output=True, text=True, timeout=20)
    except Exception as e:
        return subprocess.CompletedProcess([], 1, "", str(e))

current_vm_backend = "vbox"  # "vbox" or "vmware" -- which backend controls the CURRENTLY
                             # ACTIVE vm (VM_NAME when vbox, a .vmx path when vmware).
                             # Every VM-lifecycle command and OS Voting row checks this.

def _checked(completed_process):
    """subprocess.run's check=True equivalent for the generic vm_*() wrappers below,
    which deliberately return a CompletedProcess without raising (so callers that just
    want to check .returncode can). retry_vbox()-style retry helpers need a raise on
    failure to detect a failed attempt and retry -- this bridges that."""
    if completed_process is not None and completed_process.returncode != 0:
        raise subprocess.CalledProcessError(completed_process.returncode, "vm command",
                                             completed_process.stdout, completed_process.stderr)
    return completed_process

def vm_start(target, backend=None, gui=True):
    backend = backend or current_vm_backend
    if backend == "vmware":
        return vmware_start(target, gui, VMRUN_PATH)
    return subprocess.run([VBOXMANAGE_PATH, "startvm", target, "--type", "gui" if gui else "headless"], capture_output=True, text=True)

def vm_stop(target, backend=None, hard=True):
    backend = backend or current_vm_backend
    if backend == "vmware":
        return vmware_stop(target, hard, VMRUN_PATH)
    verb = "poweroff" if hard else "acpipowerbutton"
    return subprocess.run([VBOXMANAGE_PATH, "controlvm", target, verb], capture_output=True, text=True)

def vm_reset(target, backend=None):
    backend = backend or current_vm_backend
    if backend == "vmware":
        return vmware_reset(target, VMRUN_PATH)
    return subprocess.run([VBOXMANAGE_PATH, "controlvm", target, "reset"], capture_output=True, text=True)

def vm_revert_to_snapshot(target, snapshot_name, backend=None):
    backend = backend or current_vm_backend
    if backend == "vmware":
        return vmware_revert_to_snapshot(target, snapshot_name, VMRUN_PATH)
    return subprocess.run([VBOXMANAGE_PATH, "snapshot", target, "restore", snapshot_name], capture_output=True, text=True)

def vm_take_snapshot(target, snapshot_name, backend=None):
    backend = backend or current_vm_backend
    if backend == "vmware":
        return vmware_take_snapshot(target, snapshot_name, VMRUN_PATH)
    return subprocess.run([VBOXMANAGE_PATH, "snapshot", target, "take", snapshot_name, "--live"], capture_output=True, text=True)

def vm_is_running(target, backend=None):
    backend = backend or current_vm_backend
    if backend == "vmware":
        return vmware_is_running(target, VMRUN_PATH)
    if not target or not VBOXMANAGE_PATH:
        return False
    try:
        res = subprocess.run([VBOXMANAGE_PATH, "list", "runningvms"], capture_output=True, text=True, timeout=15)
        return f'"{target}"' in (res.stdout or "")
    except Exception as e:
        print(f'[VBoxManage] list error: Python exception: "{traceback.format_exc()}"')
        return False

def get_backend_for_vm(vm_identifier):
    """Looks up which backend a given VM identifier belongs to, by matching it against
    OS_LIST entries. Falls back to current_vm_backend if it's not one of the configured
    OS Voting rows (e.g. the single-VM VM_NAME in non-voting mode)."""
    for e in OS_LIST:
        if e.get("vm") == vm_identifier:
            return e.get("backend", "vbox")
    return current_vm_backend

SNAPSHOT_NAME_VMWARE = "snp"   # fixed snapshot name used for !revert when the current vm is
                               # VMware-backed (vmrun has no "revert to current" concept the
                               # way VBoxManage's restorecurrent does -- it always needs an
                               # explicit name, so this is the fixed convention name for it)

def vm_revert_to_current(target, backend=None):
    """Reverts to the 'current' snapshot. VBox has a native concept of this (restorecurrent
    needs no name) -- VMware/vmrun does not, so this uses SNAPSHOT_NAME_VMWARE as the fixed
    convention name for that side."""
    backend = backend or current_vm_backend
    if backend == "vmware":
        return vmware_revert_to_snapshot(target, SNAPSHOT_NAME_VMWARE, VMRUN_PATH)
    return subprocess.run([VBOXMANAGE_PATH, "snapshot", target, "restorecurrent"], capture_output=True, text=True)

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
        print(f'[VM List] Error: Python exception: "{traceback.format_exc()}"')
        return []

VBOXMANAGE_PATH = get_vboxmanage_path()
VMRUN_PATH = get_vmrun_path()
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
        print(f'[Votes] Write error: Python exception: "{traceback.format_exc()}"')
BAN_DURATION      = 1800
VOTE_TIMEOUT      = 120
SUCCESS_SOUND_FILE = "success.mp3"
ADMIN_USERNAME     = "Nexora-WN"
YOUTUBE_API_KEY    = ""   # Optional: paste your YouTube Data API v3 key here for live stats

# Global bot state (set at runtime from GUI)
VIDEO_ID = ""
VM_NAME  = ""

# ========================= REAL PC CONTROL =========================
REALPC_CONFIG_FILE = "realpc_config.json"
REALPC_CONFIG = {
    "video_id":          "",       # YouTube video ID to listen on
    "enabled":           False,    # master on/off switch
    "failsafe":          True,     # pyautogui failsafe (mouse to corner = abort)
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
}

_realpc_bot_thread   = None
_realpc_stop_event   = threading.Event()
_realpc_user_cd      = {}          # {username: last_action_time}
_realpc_cd_lock      = threading.Lock()
_realpc_status_cb    = None        # GUI callback to update status label


def load_realpc_config():
    global REALPC_CONFIG
    try:
        if os.path.exists(REALPC_CONFIG_FILE):
            with open(REALPC_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            REALPC_CONFIG.update(data)
            print("[RealPC] Config loaded.")
    except Exception as e:
        print(f'[RealPC] Load error: Python exception: "{traceback.format_exc()}"')


def save_realpc_config():
    try:
        with open(REALPC_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(REALPC_CONFIG, f, indent=2)
        print("[RealPC] Config saved.")
    except Exception as e:
        print(f'[RealPC] Save error: Python exception: "{traceback.format_exc()}"')


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


def _realpc_execute(username: str, action: str, args: str):
    """
    Execute a single Real-PC command.
    action : command name without !  (e.g. 'type', 'click', 'combo')
    args   : everything after the command word
    """
    if not _PYAUTOGUI_OK:
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
            keys = parse_combo_keys(args)
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

        elif action in ("move", "moveto", "abs", "cursor", "moveabs"):
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
        print(f'[RealPC] Execute error (!{action}): Python exception: "{traceback.format_exc()}"')
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

    wl_only   = REALPC_CONFIG.get("whitelist_only", False)
    whitelist = {normalize_username(u) for u in REALPC_CONFIG.get("whitelist", [])}
    blocked   = {normalize_username(u) for u in REALPC_CONFIG.get("blocked",   [])}

    pyautogui.FAILSAFE = REALPC_CONFIG.get("failsafe", True)
    pyautogui.PAUSE    = REALPC_CONFIG.get("action_delay", 0.05)

    _realpc_set_status(f"Connecting to stream: {vid}")
    chat = None
    try:
        chat = pytchat.create(video_id=vid)
    except Exception as e:
        _realpc_set_status(f"Connection failed: {e}")
        return

    _realpc_set_status("Listening — commands: !type  !send  !combo  !click  !move  etc.")

    while not _realpc_stop_event.is_set():
        if not chat.is_alive():
            _realpc_set_status("Chat ended or disconnected.")
            break
        try:
            for msg_obj in chat.get().sync_items():
                if _realpc_stop_event.is_set():
                    break

                user = normalize_username(msg_obj.author.name)
                msg  = msg_obj.message.strip()

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
                for seg in segments:
                    if seg.startswith("!"):
                        seg = seg[1:].strip()
                    if not seg:
                        continue
                    parts  = seg.split(maxsplit=1)
                    action = parts[0].lower()
                    args   = parts[1] if len(parts) > 1 else ""
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
                print(f'[RealPC] Loop error: Python exception: "{traceback.format_exc()}"')

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
            print(f'[EventLog] Write error: Python exception: "{traceback.format_exc()}"')
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
        print(f'[EventLog] Load error: Python exception: "{traceback.format_exc()}"')
        _event_log = []

# ========================= PERMISSIONS CONFIG =========================
PERMISSIONS_CONFIG_FILE = "permissions_config.json"
# Default required-votes table (overridden by GUI / config file)
# {username: last_command_timestamp} -- used by the global per-user command cooldown below
_global_command_cooldowns = {}

PERMISSIONS_CONFIG = {
    "restart_votes":   2,
    "revert_votes":    2,
    "ban_votes":       3,
    "action_cooldown": 60,   # seconds between restart/revert actions
    "vote_threshold_percent_enabled": False,  # if True, ALL vote commands need this % of live viewers instead of a fixed count
    "vote_threshold_percent": 30,
    "global_command_cooldown": 60,  # seconds a non-mod must wait between ANY two commands, 0 = disabled
}

def get_vote_threshold(key, default):
    """Returns the votes required for a given vote type (restart_votes/revert_votes/
    ban_votes/os_vote_required). If percent-based voting is enabled, computes
    ceil(live_viewers * percent/100) instead -- falls back to the fixed count if
    no live viewer number is available yet (needs YOUTUBE_API_KEY set)."""
    if PERMISSIONS_CONFIG.get("vote_threshold_percent_enabled"):
        viewers = overlay_data.get("viewers")
        if viewers and viewers > 0:
            pct = PERMISSIONS_CONFIG.get("vote_threshold_percent", 30)
            return max(1, math.ceil(viewers * pct / 100))
    return PERMISSIONS_CONFIG.get(key, default)

def load_permissions_config():
    global PERMISSIONS_CONFIG
    try:
        if os.path.exists(PERMISSIONS_CONFIG_FILE):
            with open(PERMISSIONS_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            PERMISSIONS_CONFIG.update(data)
            print("[Permissions] Config loaded.")
    except Exception as e:
        print(f'[Permissions] Load error: Python exception: "{traceback.format_exc()}"')

def save_permissions_config():
    try:
        with open(PERMISSIONS_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(PERMISSIONS_CONFIG, f, indent=2)
        print("[Permissions] Config saved.")
    except Exception as e:
        print(f'[Permissions] Save error: Python exception: "{traceback.format_exc()}"')

# ========================= YT CHAT LOG RELAY =========================
# Mirrors every line that shows up in this app's own console/log box out to the
# YouTube Live Chat itself. This uses a real OAuth "send message" call (the
# same flow used by liveChat.messages.insert) -- authenticated as YOUR OWN
# Google account. This is separate from the read-only YOUTUBE_API_KEY above:
# an API key alone can read stats but cannot send chat messages.
YT_LOG_RELAY_CONFIG_FILE = "yt_log_relay_config.json"
YT_LOG_RELAY_CONFIG = {
    "enabled":       False,   # master on/off switch for mirroring console lines to YT chat
    "client_id":     "",      # OAuth client ID (Google Cloud Console -> OAuth client)
    "client_secret": "",      # OAuth client secret
    "auth_code":     "",      # one-time authorization code -- consumed once, then cleared
    "access_token":  "",      # short-lived bearer token (auto-refreshed on expiry)
    "refresh_token": "",      # long-lived token used to mint new access tokens
    "live_chat_id":  "",      # target liveChatId messages get posted into
}

import queue as _yt_relay_queue_module
_yt_relay_queue = _yt_relay_queue_module.Queue()
_yt_relay_thread = None
_yt_relay_stop_event = threading.Event()

def load_yt_log_relay_config():
    global YT_LOG_RELAY_CONFIG
    try:
        if os.path.exists(YT_LOG_RELAY_CONFIG_FILE):
            with open(YT_LOG_RELAY_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            YT_LOG_RELAY_CONFIG.update(data)
            print("[YTLogRelay] Config loaded.")
    except Exception:
        print(f'[YTLogRelay] Load error: Python exception: "{traceback.format_exc()}"')

def save_yt_log_relay_config():
    try:
        with open(YT_LOG_RELAY_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(YT_LOG_RELAY_CONFIG, f, indent=2)
        print("[YTLogRelay] Config saved.")
    except Exception:
        print(f'[YTLogRelay] Save error: Python exception: "{traceback.format_exc()}"')

def yt_relay_exchange_auth_code():
    """
    One-time exchange: turns a fresh OAuth 'auth_code' (from the Google consent
    screen) into an access_token + refresh_token pair. Requires client_id and
    client_secret to already be filled in on the panel.
    """
    import urllib.request
    import urllib.parse
    import urllib.error
    import json as _json

    cid = YT_LOG_RELAY_CONFIG.get("client_id", "").strip()
    csec = YT_LOG_RELAY_CONFIG.get("client_secret", "").strip()
    code = YT_LOG_RELAY_CONFIG.get("auth_code", "").strip()
    if not (cid and csec and code):
        print("[YTLogRelay] Need Client ID, Client Secret, and Auth Code to exchange.")
        return False

    payload = urllib.parse.urlencode({
        "code": code,
        "client_id": cid,
        "client_secret": csec,
        "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
        "grant_type": "authorization_code",
    }).encode()
    try:
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=payload)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = _json.loads(resp.read().decode())
        YT_LOG_RELAY_CONFIG["access_token"] = data.get("access_token", "")
        if data.get("refresh_token"):
            YT_LOG_RELAY_CONFIG["refresh_token"] = data.get("refresh_token")
        YT_LOG_RELAY_CONFIG["auth_code"] = ""   # single-use -- clear it once consumed
        save_yt_log_relay_config()
        print("[YTLogRelay] Auth code exchanged for tokens.")
        return True
    except Exception as e:
        print(f"[YTLogRelay] Auth code exchange failed: {e}")
        return False

def yt_relay_refresh_access_token():
    """Uses the stored refresh_token to mint a new access_token."""
    import urllib.request
    import urllib.parse
    import json as _json

    cid = YT_LOG_RELAY_CONFIG.get("client_id", "").strip()
    csec = YT_LOG_RELAY_CONFIG.get("client_secret", "").strip()
    rtok = YT_LOG_RELAY_CONFIG.get("refresh_token", "").strip()
    if not (cid and csec and rtok):
        print("[YTLogRelay] Need Client ID, Client Secret, and Refresh Token to refresh.")
        return None

    payload = urllib.parse.urlencode({
        "client_id": cid,
        "client_secret": csec,
        "refresh_token": rtok,
        "grant_type": "refresh_token",
    }).encode()
    try:
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=payload)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = _json.loads(resp.read().decode())
        token = data.get("access_token")
        if token:
            YT_LOG_RELAY_CONFIG["access_token"] = token
            save_yt_log_relay_config()
            print("[YTLogRelay] Access token refreshed.")
        return token
    except Exception as e:
        print(f"[YTLogRelay] Token refresh failed: {e}")
        return None

def yt_relay_send_message(text):
    """
    Sends one line of text into the target live chat via liveChat.messages.insert,
    by shelling out to curl (equivalent to running the curl command below by hand):

        curl -X POST "https://www.googleapis.com/youtube/v3/liveChat/messages?part=snippet" \
          -H "Authorization: Bearer <access_token>" \
          -H "Accept: application/json" \
          -H "Content-Type: application/json" \
          -d '{"snippet": {"liveChatId": "<chat_id>", "type": "textMessageEvent",
                "textMessageDetails": {"messageText": "<text>"}}}'

    Auto-refreshes the access token on a 401 and retries once.
    """
    import subprocess
    import json as _json

    chat_id = YT_LOG_RELAY_CONFIG.get("live_chat_id", "").strip()
    if not chat_id:
        return False
    text = text.strip()
    if not text:
        return False
    if len(text) > 200:   # YouTube live chat message length limit
        text = text[:197] + "..."

    def _curl_post(token):
        body = _json.dumps({
            "snippet": {
                "liveChatId": chat_id,
                "type": "textMessageEvent",
                "textMessageDetails": {"messageText": text},
            }
        })
        cmd = [
            "curl", "-sS", "-X", "POST",
            "https://www.googleapis.com/youtube/v3/liveChat/messages?part=snippet",
            "-H", f"Authorization: Bearer {token}",
            "-H", "Accept: application/json",
            "-H", "Content-Type: application/json",
            "-w", "\n%{http_code}",
            "-d", body,
        ]
        # List-form subprocess call -- no shell=True, so the token/body are passed
        # as literal argv entries and never touch a shell for interpretation.
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        stdout = result.stdout.strip()
        # The "-w" flag appended the HTTP status code as the final line of stdout.
        if "\n" in stdout:
            resp_body, _, status_code = stdout.rpartition("\n")
        else:
            resp_body, status_code = "", stdout
        try:
            status = int(status_code.strip())
        except ValueError:
            status = 0
        return status, resp_body, result.returncode

    token = YT_LOG_RELAY_CONFIG.get("access_token", "").strip()
    if not token:
        return False
    try:
        status, resp_body, rc = _curl_post(token)
        if rc == 0 and 200 <= status < 300:
            return True
        if status == 401:
            new_token = yt_relay_refresh_access_token()
            if new_token:
                status2, resp_body2, rc2 = _curl_post(new_token)
                if rc2 == 0 and 200 <= status2 < 300:
                    return True
                print(f"[YTLogRelay] curl send failed after refresh (HTTP {status2}): {resp_body2[:200]}")
                return False
        print(f"[YTLogRelay] curl send failed (HTTP {status}): {resp_body[:200]}")
        return False
    except subprocess.TimeoutExpired:
        print("[YTLogRelay] curl send timed out.")
        return False
    except Exception as e:
        print(f"[YTLogRelay] curl send error: {e}")
        return False

def _yt_relay_worker():
    """
    Background thread: drains the console-log queue and forwards each line to
    the live chat, one at a time, with a short delay between sends so it can't
    flood chat or blow through the API's per-minute quota.
    """
    while not _yt_relay_stop_event.is_set():
        try:
            line = _yt_relay_queue.get(timeout=0.5)
        except _yt_relay_queue_module.Empty:
            continue
        if YT_LOG_RELAY_CONFIG.get("enabled"):
            try:
                yt_relay_send_message(line)
            except Exception:
                pass
        time.sleep(1.2)   # stay well under YouTube live chat's rate limits

def start_yt_log_relay_worker():
    global _yt_relay_thread
    if _yt_relay_thread is None or not _yt_relay_thread.is_alive():
        _yt_relay_stop_event.clear()
        _yt_relay_thread = threading.Thread(target=_yt_relay_worker, daemon=True)
        _yt_relay_thread.start()

def enqueue_log_line_for_yt_relay(text):
    """Called from ConsoleRedirect.write() for every console line. Cheap/non-blocking."""
    if YT_LOG_RELAY_CONFIG.get("enabled") and text and text.strip():
        try:
            _yt_relay_queue.put_nowait(text.strip())
        except Exception:
            pass

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
    global SOUND_CONFIG, SUCCESS_SOUND_FILE
    try:
        if os.path.exists(SOUND_CONFIG_FILE):
            with open(SOUND_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            SOUND_CONFIG.update(data)
            SUCCESS_SOUND_FILE = SOUND_CONFIG.get("success_sound", "success.mp3")
            print("[Sound] Config loaded.")
    except Exception as e:
        print(f'[Sound] Load error: Python exception: "{traceback.format_exc()}"')

def save_sound_config():
    try:
        with open(SOUND_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(SOUND_CONFIG, f, indent=2)
        print("[Sound] Config saved.")
    except Exception as e:
        print(f'[Sound] Save error: Python exception: "{traceback.format_exc()}"')

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

# ========================= MRTRISTINAI (GROQ CHAT) CONFIG =========================
MRTRISTINAI_CONFIG_FILE = "mrtristinai_config.json"
MRTRISTINAI_CONFIG_DEFAULT_PROMPT = (
    "You are MrTristinAI, the built-in AI assistant of UltraBot Control Panel "
    "(a YouTube livestream chat-bot / VM control app). You run on "
    "Groq's LPU infrastructure. Introduce yourself as MrTristinAI if asked who "
    "you are, and don't claim to be ChatGPT, Gemini, or any other assistant. "
    "Be concise, friendly, and helpful."
)
MRTRISTINAI_CONFIG = {
    "groq_api_key": "",                        # saved once entered, never shown again in plain sight after restart
    "model":        "llama-3.3-70b-versatile",  # default Groq model
    "system_prompt": MRTRISTINAI_CONFIG_DEFAULT_PROMPT,
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
MRTRISTINAI_FALLBACK_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "llama3-70b-8192",
    "llama3-8b-8192",
    "mixtral-8x7b-32768",
    "gemma2-9b-it",
]


def load_mrtristinai_config():
    global MRTRISTINAI_CONFIG
    try:
        if os.path.exists(MRTRISTINAI_CONFIG_FILE):
            with open(MRTRISTINAI_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            MRTRISTINAI_CONFIG.update(data)
            print("[MrTristinAI] Config loaded.")
    except Exception as e:
        print(f"[MrTristinAI] Load error: {e}")


def save_mrtristinai_config():
    try:
        with open(MRTRISTINAI_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(MRTRISTINAI_CONFIG, f, indent=2)
        print("[MrTristinAI] Config saved.")
    except Exception as e:
        print(f"[MrTristinAI] Save error: {e}")


def groq_list_models(api_key: str):
    """
    Fetches the list of available model IDs from Groq's /models endpoint.
    Returns a list of model id strings, or the fallback list on any error
    (bad key, no internet, endpoint change, etc.) so the caller never has
    to special-case failure.
    """
    if not api_key:
        return list(MRTRISTINAI_FALLBACK_MODELS)
    try:
        req = urllib.request.Request(
            GROQ_MODELS_URL,
            headers={**GROQ_REQUEST_HEADERS, "Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        ids = [m.get("id") for m in data.get("data", []) if m.get("id")]
        return sorted(ids) if ids else list(MRTRISTINAI_FALLBACK_MODELS)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body).get("error", {}).get("message", body)
        except Exception:
            detail = body
        print(f"[MrTristinAI] Could not fetch model list (HTTP {e.code}): {detail} — using fallback list.")
        return list(MRTRISTINAI_FALLBACK_MODELS)
    except Exception as e:
        print(f"[MrTristinAI] Could not fetch model list, using fallback list: {e}")
        return list(MRTRISTINAI_FALLBACK_MODELS)


def groq_chat_completion(api_key: str, model: str, messages: list):
    """
    Sends a chat completion request to Groq (OpenAI-compatible endpoint).
    messages: list of {"role": "user"/"assistant"/"system", "content": str}
    Returns the assistant's reply text.
    Raises an exception on any failure — the caller is expected to catch
    it and show the message to the user.
    """
    if not api_key:
        raise ValueError("No Groq API key set. Enter one in the MrTristinAI tab first.")

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
    global MULTI_STREAM_CONFIG
    try:
        if os.path.exists(MULTI_STREAM_CONFIG_FILE):
            with open(MULTI_STREAM_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            MULTI_STREAM_CONFIG.update(data)
            print(f"[MultiStream] Config loaded. {len(MULTI_STREAM_CONFIG['video_ids'])} extra stream(s).")
    except Exception as e:
        print(f'[MultiStream] Load error: Python exception: "{traceback.format_exc()}"')

def save_multi_stream_config():
    try:
        with open(MULTI_STREAM_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(MULTI_STREAM_CONFIG, f, indent=2)
        print("[MultiStream] Config saved.")
    except Exception as e:
        print(f'[MultiStream] Save error: Python exception: "{traceback.format_exc()}"')

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
    global SCHEDULER_CONFIG
    try:
        if os.path.exists(SCHEDULER_CONFIG_FILE):
            with open(SCHEDULER_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            SCHEDULER_CONFIG.update(data)
            print(f"[Scheduler] Config loaded. {len(SCHEDULER_CONFIG['tasks'])} task(s).")
    except Exception as e:
        print(f'[Scheduler] Load error: Python exception: "{traceback.format_exc()}"')

def save_scheduler_config():
    try:
        with open(SCHEDULER_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(SCHEDULER_CONFIG, f, indent=2)
        print("[Scheduler] Config saved.")
    except Exception as e:
        print(f'[Scheduler] Save error: Python exception: "{traceback.format_exc()}"')

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
                    lambda: _checked(vm_stop(VM_NAME, current_vm_backend, hard=True)),
                    attempts=3, delay=3, source="Scheduler/poweroff"
                )
                time.sleep(3)
                ok2, _ = retry_vbox(
                    lambda: _checked(vm_revert_to_current(VM_NAME, current_vm_backend)),
                    attempts=3, delay=3, source="Scheduler/snapshot"
                )
                time.sleep(3)
                ok3, _ = retry_vbox(
                    lambda: _checked(vm_start(VM_NAME, current_vm_backend, gui=True)),
                    attempts=3, delay=4, source="Scheduler/startvm"
                )
                if ok2 and ok3:
                    update_status("Running")
                    play_success_sound()
                    obs_trigger("revert_done")
                    apply_current_os_scene()
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
                    lambda: _checked(vm_reset(VM_NAME, current_vm_backend)),
                    attempts=3, delay=3, source="Scheduler/restart"
                )
                if ok:
                    update_status("Running")
                    play_success_sound()
                    obs_trigger("restart")
                    obs_trigger("restart_done")
                    apply_current_os_scene()
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
    DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
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
mgr  = VirtualBoxManager(None, None)
vbox = mgr.getVirtualBox()
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
        print(f'[ErrorLog] Could not write log: Python exception: "{traceback.format_exc()}"')
    try:
        obs_trigger("error_occurred_with_script")
    except Exception:
        pass

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


def _process_test_mode_line(line):
    """Processes one test-mode command line exactly as the chat loop would. Returns
    False if this line means "stop test mode" (!quit/!exit/!stop), True otherwise.
    Split out from run_test_mode() so both the blocking-input() loop (Windows/Linux)
    and the non-blocking stdin poller (macOS, see _test_mode_poll_stdin) can share the
    exact same command handling instead of duplicating it."""
    line = line.strip()
    if not line:
        return True
    if line.lower() in ("!quit", "!exit", "!stop"):
        print("[TestMode] Stopping test mode.")
        bot_stop_event.set()
        return False

    # Parse exactly like the chat loop does
    if not line.startswith("!"):
        print("[TestMode] Commands must start with '!' — e.g. !type hello")
        return True

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
            return True

    # Custom commands
    trigger = "!" + cmd
    if trigger in custom_commands:
        threading.Thread(target=execute_custom_command, args=(trigger,), daemon=True).start()
        return True

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
            keys = parse_combo_keys(args)
            if keys:
                send_combo(keys)
        elif cmd in ("click", "lclick", "rclick", "rightclick",
                     "mclick", "middleclick", "move", "mouse", "mv",
                     "abs", "cursor", "moveabs", "drag", "dragrel",
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
            return True
        print(f"[TestMode] OK: !{cmd} {args}")
    except Exception as e:
        print(f'[TestMode] Error executing !{cmd}: Python exception: "{traceback.format_exc()}"')
    return True

def run_single_bot_command(line):
    """Executes one "!cmd args" line exactly as the chat loop or test mode console
    would -- OS-voting triggers, custom commands, then built-in commands (!type,
    !send, !click, !combo, !key, etc.). Returns (ok: bool, message: str) instead of
    printing directly, so callers (test mode's stdin loop, the GUI's Admin CMD box,
    anything else) can each show the result wherever makes sense for them, rather
    than this function assuming it's always talking to a terminal.
    Does NOT handle !quit/!exit/!stop -- those are test-mode-console-specific and
    stay in run_test_mode()'s own loop, since "stop test mode" isn't a sensible
    action to trigger from, say, the Admin CMD box."""
    line = line.strip()
    if not line.startswith("!"):
        return False, "Commands must start with '!' — e.g. !type hello"

    parts = line[1:].split(" ", 1)
    cmd   = parts[0].lower().strip()
    args  = parts[1].strip() if len(parts) > 1 else ""

    # OS voting triggers
    if OS_VOTING_ENABLED:
        os_trigger_map = get_os_trigger_map()
        if cmd in os_trigger_map:
            target_entry = os_trigger_map[cmd]
            threading.Thread(target=switch_os, args=(target_entry,), daemon=True).start()
            return True, f"Owner-bypass OS switch → {target_entry['name']}"

    # Custom commands
    trigger = "!" + cmd
    if trigger in custom_commands:
        threading.Thread(target=execute_custom_command, args=(trigger,), daemon=True).start()
        return True, f"Running custom command {trigger}"

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
            keys = parse_combo_keys(args)
            if keys:
                send_combo(keys)
        elif cmd in ("click", "lclick", "rclick", "rightclick",
                     "mclick", "middleclick", "move", "mouse", "mv",
                     "abs", "cursor", "moveabs", "drag", "dragrel",
                     "dragabs", "drag_absolute", "scroll", "wheel"):
            handle_mouse(cmd, args)
        elif cmd in ("startvm", "launchvm"):
            start_vm()
        elif cmd in ("restartvm", "restart"):
            speak_text("Restarting Virtual Machine...")
            update_status("Restarting...")
            _checked(vm_reset(VM_NAME, current_vm_backend))
            update_status("Running")
            play_success_sound()
            obs_trigger("restart")
            obs_trigger("restart_done")
            apply_current_os_scene()
        elif cmd == "revert":
            global revert_in_progress, revert_start_time
            speak_text("Reverting Virtual Machine...")
            revert_in_progress = True
            update_status("Reverting...")
            try:
                _checked(vm_stop(VM_NAME, current_vm_backend, hard=True))
                time.sleep(3)
                _checked(vm_revert_to_current(VM_NAME, current_vm_backend))
                time.sleep(3)
                _checked(vm_start(VM_NAME, current_vm_backend, gui=True))
                update_status("Running")
                play_success_sound()
                obs_trigger("revert_done")
                apply_current_os_scene()
                vote_revert.clear()
                update_votes_json("revert", 0, 2, 0)
            finally:
                revert_start_time = None
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
            return False, f"Unknown command: !{cmd}"
        return True, f"OK: !{cmd} {args}"
    except Exception as e:
        return False, f"Error executing !{cmd}: {e}"

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
        ok, message = run_single_bot_command(line)
        print(f"[TestMode] {message}")
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
        print(f'[UserMgmt] Load error: Python exception: "{traceback.format_exc()}"')

def save_user_mgmt():
    try:
        with open(USER_MGMT_FILE, "w", encoding="utf-8") as f:
            json.dump({"whitelist": sorted(whitelist_users),
                       "vip":       vip_users}, f, indent=2, ensure_ascii=False)
        print("[UserMgmt] Saved.")
    except Exception as e:
        print(f'[UserMgmt] Save error: Python exception: "{traceback.format_exc()}"')
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
    "os_scenes": {},
    # Per-OS switching scenes — {trigger_key: obs_scene_name}. Shown the moment
    # a switch to THAT OS starts, before its own os_scenes entry above takes over.
    "switching_scenes": {},
    # Per-OS RECEIVER switching scenes — {trigger_key: obs_scene_name}. Shown ONLY on the
    # machine that is RECEIVING a Host-Switch handoff, the moment it accepts the incoming
    # VM -- lets the receiver show a different "incoming" scene than whatever the sender
    # shows on its own end via "switching_scenes" above.
    "recv_switching_scenes": {}
}

def load_obs_config():
    global OBS_CONFIG
    try:
        if os.path.exists(OBS_CONFIG_FILE):
            with open(OBS_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            OBS_CONFIG.update(data)
            print("[OBS] Config loaded.")
    except Exception as e:
        print(f'[OBS] Load error: Python exception: "{traceback.format_exc()}"')

def save_obs_config():
    try:
        with open(OBS_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(OBS_CONFIG, f, indent=2)
        print("[OBS] Config saved.")
    except Exception as e:
        print(f'[OBS] Save error: Python exception: "{traceback.format_exc()}"')

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
        print(f'[OBS] Connection failed: Python exception: "{traceback.format_exc()}"')
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
        print(f'[OBS] Scene switch error: Python exception: "{traceback.format_exc()}"')
        log_error("OBS", e)

def obs_trigger(event: str):
    """Fire a named trigger event if OBS is enabled and connected."""
    if not OBS_CONFIG.get("enabled") or not _obs_connected:
        return
    scene = OBS_CONFIG["triggers"].get(event, "")
    if scene:
        threading.Thread(target=obs_set_scene, args=(scene,), daemon=True).start()

# ========================= PER-OS HOST SWITCHING (EXPERIMENTAL) =========================
# Lets two machines running this same bot -- one per OS -- hand a live stream back and
# forth: whichever machine is currently live tells the OTHER machine "boot up and take
# over," while it fades its own OBS scene out and stops its own stream. See the
# "Per-OS Host Switching (EXPERIMENTAL)" panel on the OS Voting tab.
HOST_SWITCH_CONFIG_FILE  = "host_switch_config.json"
HOST_SWITCH_SENDER_URL   = "https://stale-chicken-beam.loca.lt"
HOST_SWITCH_RECEIVER_URL = "https://good-soup-beam.loca.lt"
CURRENT_VM_FILE          = "current_vm.json"

HOST_SWITCH_CONFIG = {
    "role":               "Sender",   # "Sender" or "Receiver" -- auto-detected at startup
    "obs_ws_address":     "",         # e.g. ws://localhost:4455 -- THIS machine's own OBS,
                                       # independent of the OBS_CONFIG host/port used elsewhere
    "switching_scene":    "",         # OBS scene shown on both ends during a handoff
    "migration_software": "None",     # "None", "Hyper-V", "UTM", or "Parallels Desktop"
    "local_port":         8765,       # port this machine's signaling server listens on --
                                       # what you point `lt --port 8765 --subdomain ...` at
    "sync_vm_name":       False,      # if True, push this machine's VM name to the other
                                       # Host-Switch machine whenever the watchdog restarts it
                                       # or a handoff is sent, so both sides agree on "current"
}

_host_switch_server    = None
_host_switch_other_os  = None   # OS string reported by the other machine's /whoami, once known

def load_host_switch_config():
    global HOST_SWITCH_CONFIG
    try:
        if os.path.exists(HOST_SWITCH_CONFIG_FILE):
            with open(HOST_SWITCH_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            HOST_SWITCH_CONFIG.update(data)
            print("[HostSwitch] Config loaded.")
    except Exception:
        print(f'[HostSwitch] Load error: Python exception: "{traceback.format_exc()}"')

def save_host_switch_config():
    try:
        with open(HOST_SWITCH_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(HOST_SWITCH_CONFIG, f, indent=2)
        print("[HostSwitch] Config saved.")
    except Exception:
        print(f'[HostSwitch] Save error: Python exception: "{traceback.format_exc()}"')

def host_switch_current_os():
    """Returns this machine's OS as one of 'Windows', 'macOS', 'Linux'."""
    sysname = platform.system()
    if sysname == "Darwin":
        return "macOS"
    if sysname == "Windows":
        return "Windows"
    return "Linux"

def save_current_vm(vm_name, backend=None):
    """Writes current_vm.json -- what the OTHER machine reads on a handoff to know which
    VM to boot once it takes over."""
    try:
        data = {"vm": vm_name, "backend": backend or globals().get("current_vm_backend"),
                "saved_at": time.time()}
        with open(CURRENT_VM_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"[HostSwitch] Saved current_vm.json -> {vm_name}")
    except Exception:
        print(f'[HostSwitch] current_vm.json save error: Python exception: "{traceback.format_exc()}"')

def load_current_vm():
    try:
        if os.path.exists(CURRENT_VM_FILE):
            with open(CURRENT_VM_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        print(f'[HostSwitch] current_vm.json load error: Python exception: "{traceback.format_exc()}"')
    return {}

# ── migration-software dispatch: Hyper-V / UTM / Parallels Desktop ──
def migration_start_vm(vm_name):
    """Starts vm_name with whichever hypervisor CLI is selected on the panel. Falls back
    to this file's own normal vm_start()/backend path when 'None' is selected (i.e. both
    hosts are running the same hypervisor this script already drives directly)."""
    software = HOST_SWITCH_CONFIG.get("migration_software", "None")
    try:
        if software == "Hyper-V":
            subprocess.run(["powershell", "-NoProfile", "-Command",
                             f"Start-VM -Name '{vm_name}'"], check=False, timeout=60)
        elif software == "UTM":
            subprocess.run(["utmctl", "start", vm_name], check=False, timeout=60)
        elif software == "Parallels Desktop":
            subprocess.run(["prlctl", "start", vm_name], check=False, timeout=60)
        else:
            vm_start(vm_name, globals().get("current_vm_backend"), gui=True)
        print(f"[HostSwitch] Start VM '{vm_name}' via {software}")
        return True
    except Exception as e:
        print(f"[HostSwitch] migration_start_vm failed ({software}): {e}")
        return False

def migration_stop_vm(vm_name):
    software = HOST_SWITCH_CONFIG.get("migration_software", "None")
    try:
        if software == "Hyper-V":
            subprocess.run(["powershell", "-NoProfile", "-Command",
                             f"Stop-VM -Name '{vm_name}' -Force"], check=False, timeout=60)
        elif software == "UTM":
            subprocess.run(["utmctl", "stop", vm_name], check=False, timeout=60)
        elif software == "Parallels Desktop":
            subprocess.run(["prlctl", "stop", vm_name], check=False, timeout=60)
        else:
            robust_vm_poweroff(vm_name, globals().get("current_vm_backend"), source="HostSwitch/stop")
        print(f"[HostSwitch] Stop VM '{vm_name}' via {software}")
        return True
    except Exception as e:
        print(f"[HostSwitch] migration_stop_vm failed ({software}): {e}")
        return False

# ── setup-instruction prompts (printed to console/log -- also mirrored to YT chat if the
#    log relay panel above is enabled) ──
def print_host_switch_setup_instructions(target_os):
    lines = {
        "macOS": [
            "Per-OS Host Switching -> macOS setup:",
            "  1. Install localtunnel on this Mac:  npm install -g localtunnel",
            "  2. Run:  lt --port <local_port from the panel> --subdomain <your subdomain>",
            "  3. In OBS on this Mac, enable obs-websocket (Tools -> obs-websocket Settings) "
            "and paste that ws:// address into the panel's OBS Websocket Address field.",
            "  4. If using UTM or Parallels Desktop, select it under Migration Software and "
            "make sure `utmctl` / `prlctl` is on PATH.",
        ],
        "Linux": [
            "Per-OS Host Switching -> Linux setup:",
            "  1. Install localtunnel:  npm install -g localtunnel",
            "  2. Run:  lt --port <local_port from the panel> --subdomain <your subdomain>",
            "  3. In OBS on this machine, enable obs-websocket and paste the ws:// address "
            "into the panel's OBS Websocket Address field.",
            "  4. Libvirt/VirtualBox VMs are driven directly by this bot -- leave Migration "
            "Software set to None unless you're actually running Hyper-V/UTM/Parallels here.",
        ],
        "Windows": [
            "Per-OS Host Switching -> Windows setup:",
            "  1. Install localtunnel:  npm install -g localtunnel",
            "  2. Run:  lt --port <local_port from the panel> --subdomain <your subdomain>",
            "  3. In OBS on this PC, enable obs-websocket and paste the ws:// address into "
            "the panel's OBS Websocket Address field.",
            "  4. If this PC is the Hyper-V host for another OS's VM, select Hyper-V under "
            "Migration Software and run the bot as Administrator (Hyper-V's cmdlets require it).",
        ],
    }
    for line in lines.get(target_os, [f"No setup instructions available for '{target_os}'."]):
        print(f"[HostSwitch] {line}")

# ── local signaling server: /ping, /whoami, /whoami_report, /start_vm ──
class _HostSwitchHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep the console log clean -- this fires on every poll

    def _send_json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/ping"):
            self._send_json(200, {"ok": True})
        elif self.path.startswith("/whoami"):
            self._send_json(200, {"os": host_switch_current_os(),
                                   "role": HOST_SWITCH_CONFIG.get("role", "Sender")})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        global _host_switch_other_os
        if self.path.startswith("/start_vm"):
            try:
                length = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                data = {}
            vm_name    = data.get("vm", "")
            scene      = data.get("scene", "")
            recv_scene = data.get("recv_scene", "")
            self._send_json(200, {"ok": True})
            threading.Thread(target=_host_switch_receive_start, args=(vm_name, scene, recv_scene), daemon=True).start()
        elif self.path.startswith("/whoami_report"):
            try:
                length = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(length) or b"{}")
                _host_switch_other_os = data.get("os")
                print(f"[HostSwitch] Other host reported its OS: {_host_switch_other_os}")
            except Exception:
                pass
            self._send_json(200, {"ok": True})
        elif self.path.startswith("/sync_vm_name"):
            try:
                length = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(length) or b"{}")
                vm_name = data.get("vm", "")
                if vm_name:
                    save_current_vm(vm_name)
                    print(f"[HostSwitch] Synced VM name from other host: '{vm_name}'")
            except Exception:
                print(f'[HostSwitch] /sync_vm_name error: Python exception: "{traceback.format_exc()}"')
            self._send_json(200, {"ok": True})
        else:
            self._send_json(404, {"error": "not found"})

def _host_switch_receive_start(vm_name, scene, recv_scene=""):
    """Runs on the RECEIVING machine once the Sender hands off: switch scene, start the
    stream, start the VM that was assigned in current_vm.json. Uses recv_scene (this OS's
    "Receiver Scene" from the OBS tab) instead of `scene` when one was provided, so the
    receiving machine can show a different "incoming" scene than the sender used."""
    print(f"[HostSwitch] Received handoff -- starting '{vm_name}'")
    effective_scene = recv_scene or scene
    if effective_scene:
        obs_set_scene(effective_scene)
    try:
        if _obs_connected and _obs_client:
            _obs_client.start_stream()
            print("[HostSwitch] OBS stream started on receiver.")
    except Exception:
        print(f'[HostSwitch] Could not start OBS stream: Python exception: "{traceback.format_exc()}"')
    migration_start_vm(vm_name)

def host_switch_sync_vm_name(vm_name):
    """Fire-and-forget: tells the other Host-Switch machine to treat vm_name as the current
    VM too, so all Per-OS Host Switching machines agree on which VM is "current" even
    outside of an actual handoff (e.g. after the Auto-Start Watchdog restarts it locally).
    Gated by the "Sync VM Name to Receiver" checkbox on the Main tab."""
    import urllib.request
    other = _host_switch_other_url()
    def _send():
        try:
            body = json.dumps({"vm": vm_name}).encode()
            req = urllib.request.Request(f"{other}/sync_vm_name", data=body,
                                          headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=10)
            print(f"[HostSwitch] Synced VM name '{vm_name}' to {other}")
        except Exception:
            print(f'[HostSwitch] Could not sync VM name to {other}: Python exception: "{traceback.format_exc()}"')
    threading.Thread(target=_send, daemon=True).start()

def start_host_switch_server():
    global _host_switch_server
    try:
        port = int(HOST_SWITCH_CONFIG.get("local_port", 8765))
        _host_switch_server = socketserver.TCPServer(("0.0.0.0", port), _HostSwitchHandler)
        threading.Thread(target=_host_switch_server.serve_forever, daemon=True).start()
        print(f"[HostSwitch] Signaling server listening on :{port} "
              f"(tunnel it with:  lt --port {port} --subdomain <yours>)")
    except Exception:
        print(f'[HostSwitch] Could not start signaling server: Python exception: "{traceback.format_exc()}"')

def _host_switch_other_url():
    role = HOST_SWITCH_CONFIG.get("role", "Sender")
    return HOST_SWITCH_RECEIVER_URL if role == "Sender" else HOST_SWITCH_SENDER_URL

def host_switch_test_connection_and_handshake():
    """Startup routine: ping the other machine, and if it answers, ask it which OS it's
    running (and tell it which OS we're running) so 'Current' in the OS Host dropdown can
    be populated automatically. Safe to run even if the other side isn't up yet."""
    global _host_switch_other_os
    import urllib.request
    other = _host_switch_other_url()
    try:
        r = urllib.request.urlopen(f"{other}/ping", timeout=8)
        if r.status != 200:
            raise Exception(f"bad status {r.status}")
        print(f"[HostSwitch] Connected to other host at {other}")
        r2 = urllib.request.urlopen(f"{other}/whoami", timeout=8)
        info = json.loads(r2.read().decode())
        _host_switch_other_os = info.get("os")
        print(f"[HostSwitch] Other host reports OS: {_host_switch_other_os}")
        try:
            body = json.dumps({"os": host_switch_current_os()}).encode()
            req = urllib.request.Request(f"{other}/whoami_report", data=body,
                                          headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=8)
        except Exception:
            pass
    except Exception as e:
        print(f"[HostSwitch] No connection to other host at {other} yet ({e}).")

def host_switch_autodetect_role():
    """If a Sender already answers at its URL, become Receiver -- otherwise default to
    Sender. Only runs when there's no saved config yet, so it never overrides a role you
    picked and saved by hand on the panel."""
    global HOST_SWITCH_CONFIG
    import urllib.request
    if os.path.exists(HOST_SWITCH_CONFIG_FILE):
        return
    try:
        r = urllib.request.urlopen(f"{HOST_SWITCH_SENDER_URL}/ping", timeout=5)
        if r.status == 200:
            HOST_SWITCH_CONFIG["role"] = "Receiver"
            print("[HostSwitch] Detected an existing Sender -- defaulting this machine to Receiver.")
            return
    except Exception:
        pass
    HOST_SWITCH_CONFIG["role"] = "Sender"
    print("[HostSwitch] No Sender detected -- defaulting this machine to Sender.")

def host_switch_send_handoff(vm_name, scene, recv_scene=""):
    """Runs on the SENDING machine: switch our own OBS scene, stop our own stream, save
    current_vm.json, then tell the other machine to switch scene / start stream / start VM.
    recv_scene (optional) is the scene the OTHER machine should use instead of `scene` --
    set per-OS on the OBS tab's "Receiver Scene" column."""
    import urllib.request
    if scene:
        obs_set_scene(scene)
    try:
        if _obs_connected and _obs_client:
            _obs_client.stop_stream()
            print("[HostSwitch] OBS stream stopped on sender.")
    except Exception:
        print(f'[HostSwitch] Could not stop OBS stream: Python exception: "{traceback.format_exc()}"')
    save_current_vm(vm_name)
    if HOST_SWITCH_CONFIG.get("sync_vm_name"):
        host_switch_sync_vm_name(vm_name)
    other = _host_switch_other_url()
    try:
        body = json.dumps({"vm": vm_name, "scene": scene, "recv_scene": recv_scene}).encode()
        req = urllib.request.Request(f"{other}/start_vm", data=body,
                                      headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=10)
        print(f"[HostSwitch] Handoff sent to {other} for VM '{vm_name}'")
    except Exception:
        print(f'[HostSwitch] Handoff send failed: Python exception: "{traceback.format_exc()}"')

_HOST_SWITCH_CMD_RE = re.compile(
    r"^(?P<os>win(?:dows)?|mac(?:os)?|linux)(?P<rest>[a-z0-9_]*)$", re.IGNORECASE)

def try_handle_host_switch_command(cmd_no_bang):
    """Matches chat commands shaped like !{os}{name}{vm} or !{os}{vm}, e.g. winwin11,
    macmonterey, linuxmint (the '!' is already stripped by the caller). Returns True if it
    handled the command, False if cmd_no_bang isn't one of these at all -- so callers can
    fall through to their normal command handling on a miss."""
    m = _HOST_SWITCH_CMD_RE.match((cmd_no_bang or "").strip())
    if not m:
        return False
    os_token = m.group("os").lower()
    target_os = {"win": "Windows", "windows": "Windows",
                 "mac": "macOS", "macos": "macOS",
                 "linux": "Linux"}.get(os_token, "Windows")

    print_host_switch_setup_instructions(target_os)

    rest = m.group("rest") or ""
    # rest is the {name}{vm} portion -- match it against OS_LIST entries whose trigger
    # (with the os prefix stripped) matches, falling back to using it directly as a VM name.
    vm_name = rest
    for entry in OS_LIST:
        trig = (entry.get("trigger") or "").lower().lstrip("!")
        if trig == rest or (rest and trig.endswith(rest)):
            vm_name = entry.get("vm", rest)
            break

    scene = HOST_SWITCH_CONFIG.get("switching_scene", "")
    os_trigger_key = {"Windows": "win", "macOS": "mac", "Linux": "linux"}.get(target_os, os_token)
    recv_scene = (OBS_CONFIG.get("recv_switching_scenes", {}).get(os_token, "")
                  or OBS_CONFIG.get("recv_switching_scenes", {}).get(os_trigger_key, ""))
    role = HOST_SWITCH_CONFIG.get("role", "Sender")
    if role == "Sender":
        threading.Thread(target=host_switch_send_handoff, args=(vm_name, scene, recv_scene), daemon=True).start()
    else:
        # A Receiver getting this chat command directly relays it to the actual Sender
        # instead of acting on it locally.
        def _relay():
            import urllib.request
            other = _host_switch_other_url()
            try:
                body = json.dumps({"vm": vm_name, "scene": scene, "recv_scene": recv_scene}).encode()
                req = urllib.request.Request(f"{other}/start_vm", data=body,
                                              headers={"Content-Type": "application/json"}, method="POST")
                urllib.request.urlopen(req, timeout=10)
            except Exception:
                print(f'[HostSwitch] Could not relay command to Sender: Python exception: "{traceback.format_exc()}"')
        threading.Thread(target=_relay, daemon=True).start()
    return True




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
    """Load saved appearance settings and apply them to UltraBotGUI class attributes."""
    try:
        if os.path.exists(APPEARANCE_CONFIG_FILE):
            with open(APPEARANCE_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            colors = data.get("colors", {})
            for key, val in colors.items():
                if hasattr(UltraBotGUI, key) and isinstance(val, str) and val.startswith("#"):
                    setattr(UltraBotGUI, key, val)
            font_size = data.get("font_size")
            if font_size:
                UltraBotGUI._FONT_SIZE = int(font_size)
            print(f"[Appearance] Config loaded.")
    except Exception as e:
        print(f'[Appearance] Load error: Python exception: "{traceback.format_exc()}"')

def save_appearance_config(colors: dict, font_size: int):
    try:
        with open(APPEARANCE_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"colors": colors, "font_size": font_size}, f, indent=2)
        print("[Appearance] Config saved.")
    except Exception as e:
        print(f'[Appearance] Save error: Python exception: "{traceback.format_exc()}"')

def load_auto_start_config():
    global AUTO_START_ENABLED
    try:
        if os.path.exists(AUTO_START_CONFIG_FILE):
            with open(AUTO_START_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            AUTO_START_ENABLED = bool(data.get("enabled", True))
            print(f"[AutoStart] Config loaded. Enabled={AUTO_START_ENABLED}")
    except Exception as e:
        print(f'[AutoStart] Load error: Python exception: "{traceback.format_exc()}"')
        AUTO_START_ENABLED = True

def save_auto_start_config():
    try:
        with open(AUTO_START_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"enabled": AUTO_START_ENABLED}, f, indent=2)
        print(f"[AutoStart] Config saved. Enabled={AUTO_START_ENABLED}")
    except Exception as e:
        print(f'[AutoStart] Save error: Python exception: "{traceback.format_exc()}"')

AUTOSTART_EVERYTHING_CONFIG_FILE = "autostarteverything.json"

# ── Pre-execution safety/copyright screening -- Gemini or Groq, selectable ──
# Gemini uses the current (as of July 2026) google-genai SDK, NOT the deprecated
# google-generativeai package -- that older package's genai.GenerativeModel(...)
# pattern is legacy, and gemini-1.5-flash/gemini-2.0-flash (the models most commonly
# seen in older examples) have both been shut down and now 404. gemini-3.6-flash is
# the current stable, generally-available Flash model.
# Groq is OpenAI-API-compatible, so it's called through the standard `openai` package
# rather than a Groq-specific SDK, just pointed at Groq's base_url. openai/gpt-oss-120b
# is Groq's current, non-deprecated model confirmed to support Structured Outputs
# (several other Groq models were deprecated earlier this year with users migrated
# toward this one specifically). Both providers are fast/cheap Flash-tier models,
# which matters here since this runs before every checked command, not a heavy
# reasoning task -- Groq in particular is chosen by users who want the extra speed
# of its LPU hardware over Gemini's.
GEMINI_CONFIG_FILE = "gemini_config.json"   # filename kept as-is for backward
                                             # compatibility with any already-saved
                                             # config from before Groq support existed
GEMINI_MODEL = "gemini-3.6-flash"
GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
gemini_config = {"enabled": False, "provider": "gemini", "gemini_api_key": "", "groq_api_key": ""}
_gemini_client = None
_groq_client = None

def load_gemini_config():
    global gemini_config
    try:
        if os.path.exists(GEMINI_CONFIG_FILE):
            with open(GEMINI_CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            # Migrate the old single "api_key" field (from before Groq support
            # existed) to "gemini_api_key" if present, so an already-saved key isn't
            # silently lost on upgrade.
            if "api_key" in loaded and "gemini_api_key" not in loaded:
                loaded["gemini_api_key"] = loaded.pop("api_key")
            gemini_config.update(loaded)
        print(f"[AI Safety] Config loaded. Enabled={gemini_config.get('enabled')}, "
              f"provider={gemini_config.get('provider')}")
    except Exception as e:
        print(f'[AI Safety] Load error: Python exception: "{traceback.format_exc()}"')

def save_gemini_config():
    try:
        with open(GEMINI_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(gemini_config, f, indent=2)
        print(f"[AI Safety] Config saved. Enabled={gemini_config.get('enabled')}, "
              f"provider={gemini_config.get('provider')}")
    except Exception as e:
        print(f'[AI Safety] Save error: Python exception: "{traceback.format_exc()}"')

def _get_gemini_client():
    """Lazily creates (and caches) the Gemini client -- only if the library is
    installed and an API key has actually been entered. Returns None otherwise."""
    global _gemini_client
    if not gemini_available or not gemini_config.get("gemini_api_key", "").strip():
        return None
    if _gemini_client is None:
        try:
            _gemini_client = _gemini_genai.Client(api_key=gemini_config["gemini_api_key"].strip())
        except Exception as e:
            print(f'[AI Safety] Gemini client init error: Python exception: "{traceback.format_exc()}"')
            return None
    return _gemini_client

def _get_groq_client():
    """Lazily creates (and caches) the Groq client -- just the standard OpenAI client
    pointed at Groq's own base_url, since Groq's API is OpenAI-compatible. Only if
    the library is installed and an API key has actually been entered."""
    global _groq_client
    if not groq_available or not gemini_config.get("groq_api_key", "").strip():
        return None
    if _groq_client is None:
        try:
            _groq_client = _groq_openai_sdk.OpenAI(api_key=gemini_config["groq_api_key"].strip(),
                                                    base_url=GROQ_BASE_URL)
        except Exception as e:
            print(f'[AI Safety] Groq client init error: Python exception: "{traceback.format_exc()}"')
            return None
    return _groq_client

# Gemini's response_schema uses UPPERCASE type names (its own convention); Groq's
# json_schema uses standard lowercase JSON Schema types (OpenAI's convention) and
# additionally requires additionalProperties to be set for strict validation. Two
# separate schema constants because the wire formats genuinely differ, not because
# the underlying shape does -- both describe the exact same {risky, reason} decision.
GEMINI_RISK_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "risky": {"type": "BOOLEAN"},
        "reason": {"type": "STRING"},
    },
    "required": ["risky", "reason"],
}
GROQ_RISK_SCHEMA = {
    "type": "object",
    "properties": {
        "risky": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["risky", "reason"],
    "additionalProperties": False,
}

_AI_SAFETY_BASE = (
    "You are a pre-execution safety screen for a YouTube Live stream that is fully "
    "automated and unmoderated in the moment -- viewer chat commands execute "
    "immediately, live, with no human review before they happen. "
)

# !sr is a music request -- copyright is the only relevant risk there, so this stays
# narrowly scoped to that alone.
AI_SAFETY_SONG_INSTRUCTION = _AI_SAFETY_BASE + (
    "Your ONLY job is to flag content that poses a REAL, meaningful risk of a "
    "YouTube copyright claim/strike or channel-level enforcement action (e.g. "
    "well-known copyrighted song titles or artists being queued for on-stream "
    "playback). Do not flag generic, clearly non-infringing, or ambiguous content "
    "-- when genuinely uncertain, do NOT flag it; this is a narrow safety net for "
    "obvious cases, not a general content moderator, and over-flagging harmless "
    "viewer requests defeats its purpose. Respond only with the requested JSON."
)

# !vr queues actual video playback live on stream, so this also screens for
# inappropriate video content, not copyright alone.
AI_SAFETY_VIDEO_INSTRUCTION = _AI_SAFETY_BASE + (
    "Your job is to flag EITHER of two separate things about this video request: "
    "(1) content that poses a REAL, meaningful risk of a YouTube copyright "
    "claim/strike (e.g. well-known copyrighted movie/show titles being queued for "
    "on-stream playback), OR (2) content that is sexual, graphic/violent, or "
    "otherwise clearly inappropriate to play unsupervised on a public live stream "
    "-- based on the title/URL/description given, not content you can't actually "
    "see. Do not flag generic, harmless, or ambiguous requests -- when genuinely "
    "uncertain, do NOT flag it; this is a narrow safety net for obvious cases, not "
    "a general content moderator, and over-flagging harmless viewer requests "
    "defeats its purpose. Respond only with the requested JSON."
)

# Typed/displayed text (!type, !send, !sendline, !typeenter, and any future
# non-media command) is text that can end up literally executed on the machine
# being controlled, not just displayed -- so this screens for destructive
# commands and inappropriate browser navigation too, not copyright alone.
AI_SAFETY_TEXT_INSTRUCTION = _AI_SAFETY_BASE + (
    "Your job is to flag ANY of three separate things: "
    "(1) content that poses a REAL, meaningful risk of a YouTube copyright "
    "claim/strike (e.g. copyrighted lyrics/text being displayed on stream); "
    "(2) commands or text that would cause REAL, meaningful DESTRUCTIVE harm if "
    "executed on the machine being controlled -- e.g. deleting or overwriting "
    "files/directories, formatting or wiping drives, disabling security software, "
    "shutting down or corrupting the operating system, or similar commands run "
    "through a shell/terminal/run-dialog that a reasonable operator would never "
    "want a random anonymous viewer to be able to trigger unsupervised; or "
    "(3) a link/URL/browser-navigation command aimed at sexual, graphic, or "
    "otherwise clearly inappropriate content, INCLUDING when it looks like it's "
    "being assembled a piece at a time across the 'RECENT COMMANDS' context "
    "provided below and the new command together -- evaluate the recent commands "
    "and the new one as a single combined sequence, not just the new command in "
    "isolation, since a viewer can split an inappropriate link across several "
    "separate messages specifically to evade a check that only looks at one "
    "message at a time. "
    "Do not flag generic, harmless, or ambiguous content -- when genuinely "
    "uncertain, do NOT flag it; this is a narrow safety net for obvious cases, "
    "not a general content moderator, and over-flagging harmless viewer input "
    "defeats its purpose. Respond only with the requested JSON."
)

def _system_instruction_for(kind):
    """song (!sr) stays copyright-only. video (!vr) also screens for inappropriate
    video content. Everything else (typed/displayed text) also screens for
    destructive commands and inappropriate browser-navigation links/chains."""
    if kind == "song":
        return AI_SAFETY_SONG_INSTRUCTION
    elif kind == "video":
        return AI_SAFETY_VIDEO_INSTRUCTION
    return AI_SAFETY_TEXT_INSTRUCTION

# Rolling history of recently typed/sent text, used so the "text" instruction above
# can catch an inappropriate link/command being deliberately split across several
# separate chat messages to evade a check that only ever looked at one message at a
# time. Bounded by both count and age so it can't grow unbounded across a long
# session, and old entries stop influencing new checks once they're no longer
# plausibly part of the same in-progress chain.
_RECENT_TEXT_HISTORY_MAX_ENTRIES = 8
_RECENT_TEXT_HISTORY_MAX_AGE_SECONDS = 45
_recent_typed_text = []   # list of (timestamp, text) tuples, oldest first

def _record_and_get_recent_text_context(new_text):
    """Appends new_text to the rolling history, trims anything too old or beyond the
    max entry count, and returns a short context string of what came immediately
    before it (oldest first) for the AI prompt -- empty string if there's no
    relevant recent history yet."""
    now = time.time()
    _recent_typed_text.append((now, new_text))
    while _recent_typed_text and (
        len(_recent_typed_text) > _RECENT_TEXT_HISTORY_MAX_ENTRIES + 1
        or now - _recent_typed_text[0][0] > _RECENT_TEXT_HISTORY_MAX_AGE_SECONDS
    ):
        _recent_typed_text.pop(0)
    prior = [t for _, t in _recent_typed_text[:-1]]   # everything except the just-appended entry
    if not prior:
        return ""
    joined = " | ".join(prior)
    return f"RECENT COMMANDS (oldest first, for detecting a split/chained attempt): {joined}\n\n"

def _generate_via_gemini(client, prompt, instruction):
    """Returns the raw JSON text of the model's response, or raises on failure --
    ai_check_risk handles the shared try/except/logging around whichever provider
    function actually gets called.

    thinking_level=LOW and a generous max_output_tokens matter specifically for
    gemini-3.6-flash: it defaults to "medium" thinking, and thinking tokens are
    billed/counted against the same output budget as the final answer -- the exact
    same failure class discovered on the Groq side (a reasoning model exhausting a
    low token budget before ever emitting the answer), just not yet hit here since
    "medium" thinking is comparatively cheap for a prompt this short. LOW is enough
    for a quick classification like this one; deep thinking isn't needed. temperature
    is also deliberately omitted -- gemini-3.6-flash's own migration guidance says to
    remove temperature/top_p/top_k from configs for this model rather than pass 0."""
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=_gemini_types.GenerateContentConfig(
            system_instruction=instruction,
            response_mime_type="application/json",
            response_schema=GEMINI_RISK_SCHEMA,
            max_output_tokens=1024,
            thinking_config=_gemini_types.ThinkingConfig(thinking_level=_gemini_types.ThinkingLevel.LOW),
        ),
    )
    if not (response.text or "").strip():
        finish_reason = getattr(response.candidates[0], "finish_reason", None) if response.candidates else None
        raise RuntimeError(f"Gemini returned an empty response (finish_reason={finish_reason}) -- "
                            f"this should be rare with the current token budget.")
    return response.text

def _generate_via_groq(client, prompt, instruction):
    """Same contract as _generate_via_gemini -- returns raw JSON text or raises.

    reasoning_effort="low" and a generous max_tokens matter specifically for
    openai/gpt-oss-120b: it's a reasoning model that spends tokens on internal
    chain-of-thought BEFORE producing the final answer, and a low max_tokens (200,
    what this used to be) can let it run out of budget mid-reasoning, returning
    nothing at all -- Groq's own JSON-schema validation then rejects the empty
    output with a 400, which is indistinguishable at a glance from an actual
    validation failure. 'low' effort is enough for a quick classification like this
    one; deep reasoning isn't needed here."""
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": instruction},
            {"role": "user", "content": prompt},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "copyright_risk_check", "schema": GROQ_RISK_SCHEMA},
        },
        temperature=0,
        max_tokens=1024,
        reasoning_effort="low",
    )
    choice = response.choices[0]
    if choice.finish_reason == "length" and not (choice.message.content or "").strip():
        raise RuntimeError("Groq ran out of tokens mid-reasoning before producing an "
                            "answer (finish_reason=length, empty content) -- this "
                            "should be rare with the current token budget.")
    return choice.message.content or ""

def ai_check_risk(text, kind="text"):
    """Asks whichever provider is configured (Gemini or Groq) whether `text` poses a
    meaningful risk if it were displayed, played, or executed live on a YouTube live
    stream. For kind "song"/"video" (!sr/!vr media requests) this checks copyright
    risk only. For any other kind -- "text" (!type/!send/!sendline/!typeenter) and
    any future non-media command kind -- this ALSO checks for destructive commands
    (e.g. file deletion, drive formatting, OS-damaging shell commands), since that
    text can end up literally executed on the machine being controlled, not just
    displayed. Returns (should_block: bool, reason: str).

    Fails OPEN (returns should_block=False) on any error, timeout, or missing
    configuration -- a broken safety check should never itself become the reason
    legitimate commands stop working. This is explicitly a best-effort screen for
    obvious cases, not a guarantee or a substitute for the streamer's own judgment.

    Always prints exactly one [AI Safety] line per call, for every outcome (skipped,
    allowed, blocked, or error) -- not just when something gets blocked, so it's
    always possible to tell from the console whether this is actually running."""
    if not gemini_config.get("enabled"):
        print(f"[AI Safety] SKIPPED ({kind}) -- disabled in Perms tab. "
              f"\"{(text or '')[:60]}\" was allowed unchecked.")
        return False, "AI safety check skipped (disabled in Perms tab)"

    provider = gemini_config.get("provider", "gemini")
    if provider == "groq":
        client = _get_groq_client()
        generate = _generate_via_groq
        label = "Groq"
    else:
        client = _get_gemini_client()
        generate = _generate_via_gemini
        label = "Gemini"

    if client is None:
        why = (f"{label} library not installed" if (not groq_available if provider == "groq" else not gemini_available)
               else f"no {label} API key entered in Perms tab")
        print(f"[AI Safety] SKIPPED ({kind}) -- {why}. \"{(text or '')[:60]}\" was allowed unchecked.")
        return False, f"AI safety check skipped ({why})"

    text = (text or "").strip()
    if not text:
        return False, "empty input"
    kind_label = {
        "song": "a viewer-requested SONG TITLE/URL a bot is about to queue and play live on stream",
        "video": "a viewer-requested VIDEO TITLE/URL a bot is about to queue and play live on stream",
        "text": "TEXT a bot is about to type/display live on stream",
    }.get(kind, "content a bot is about to act on live on stream")
    instruction = _system_instruction_for(kind)
    history_context = _record_and_get_recent_text_context(text) if kind == "text" else ""
    try:
        raw = generate(client, f"{history_context}Evaluate this {kind_label}:\n\n{text}", instruction)
        result = json.loads(raw)
        risky = bool(result.get("risky", False))
        reason = str(result.get("reason", "")).strip() or "(no reason given)"
        verdict = "BLOCKED" if risky else "ALLOWED"
        print(f"[AI Safety/{label}] {verdict} ({kind}): \"{text[:60]}\" -- {reason}")
        return risky, reason
    except Exception as e:
        print(f'[AI Safety/{label}] CHECK ERROR ({kind}) -- failing open, "{text[:60]}" was allowed unchecked. '
              f'Python exception: "{traceback.format_exc()}"')
        return False, f"check failed, allowed by default: {e}"
def save_autostart_everything_config(backend=None, vm=None, watchdog=None, test_mode=None,
                                      os_voting_vm=None, os_voting_backend=None,
                                      ai_safety_enabled=None, ai_safety_provider=None,
                                      music_playback_enabled=None, video_playback_enabled=None):
    """Persists backend, VM, Auto-Start Watchdog, Test Mode, last-active OS Voting
    VM+backend, AI Safety screening enabled+provider, and automatic music/video
    playback enabled to a single unified file so startup (or any relaunch -- update
    or file replacement) can fully restore what was active before. The OS Voting
    fields are separate from plain backend/vm because they need to survive
    independently: os_voting_config.json already restores current_os_vm on its own,
    but never the matching backend for that specific entry, which is the actual gap
    this closes -- two OS Voting rows can each be on a different backend, so knowing
    the VM name alone isn't enough to correctly resume it. AI Safety's and playback's
    enabled fields are saved here too for visibility alongside everything else, but
    gemini_config.json/music_config.json/video_config.json remain the authoritative
    sources actually applied at startup (their own loads already run before the GUI
    is built, which is earlier/more reliable timing than this file's own restore
    step) -- this avoids multiple mechanisms racing to set the same checkbox.
    Any argument left as None keeps whatever was already saved for that field, so a
    caller that only changed one setting doesn't need to know or re-supply the rest --
    this reads the existing file first and merges."""
    try:
        existing = {}
        if os.path.exists(AUTOSTART_EVERYTHING_CONFIG_FILE):
            try:
                with open(AUTOSTART_EVERYTHING_CONFIG_FILE, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                pass   # corrupt/unreadable -- fine to start fresh below
        data = {
            "backend": backend if backend is not None else existing.get("backend", "vmware"),
            "vm": vm if vm is not None else existing.get("vm", ""),
            "auto_start_watchdog": watchdog if watchdog is not None else existing.get("auto_start_watchdog", False),
            "test_mode": test_mode if test_mode is not None else existing.get("test_mode", False),
            "os_voting_vm": os_voting_vm if os_voting_vm is not None else existing.get("os_voting_vm", ""),
            "os_voting_backend": os_voting_backend if os_voting_backend is not None else existing.get("os_voting_backend", ""),
            "ai_safety_enabled": ai_safety_enabled if ai_safety_enabled is not None else existing.get("ai_safety_enabled", False),
            "ai_safety_provider": ai_safety_provider if ai_safety_provider is not None else existing.get("ai_safety_provider", "gemini"),
            "music_playback_enabled": music_playback_enabled if music_playback_enabled is not None else existing.get("music_playback_enabled", False),
            "video_playback_enabled": video_playback_enabled if video_playback_enabled is not None else existing.get("video_playback_enabled", False),
        }
        abs_path = os.path.abspath(AUTOSTART_EVERYTHING_CONFIG_FILE)
        with open(AUTOSTART_EVERYTHING_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"[AutostartEverything] Saved {data} to {abs_path}")
    except Exception as e:
        print(f'[AutostartEverything] Save error: Python exception: "{traceback.format_exc()}"')

def load_autostart_everything_config():
    """Returns (backend, vm, watchdog, test_mode, os_voting_vm, os_voting_backend,
    ai_safety_enabled, ai_safety_provider, music_playback_enabled,
    video_playback_enabled) from the last saved state, or
    ("vmware", "", False, False, "", "", False, "gemini", False, False) if none
    exists yet (first-ever launch). ai_safety_enabled/ai_safety_provider/
    music_playback_enabled/video_playback_enabled are returned for completeness but
    are NOT applied by the startup restore logic -- see
    save_autostart_everything_config's docstring for why their own dedicated config
    files are the authoritative source for those specifically."""
    abs_path = os.path.abspath(AUTOSTART_EVERYTHING_CONFIG_FILE)
    try:
        if os.path.exists(AUTOSTART_EVERYTHING_CONFIG_FILE):
            with open(AUTOSTART_EVERYTHING_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            backend                = data.get("backend", "vmware")
            vm                     = data.get("vm", "")
            watchdog                = data.get("auto_start_watchdog", False)
            test_mode              = data.get("test_mode", False)
            os_voting_vm            = data.get("os_voting_vm", "")
            os_voting_backend       = data.get("os_voting_backend", "")
            ai_safety_enabled       = data.get("ai_safety_enabled", False)
            ai_safety_provider      = data.get("ai_safety_provider", "gemini")
            music_playback_enabled  = data.get("music_playback_enabled", False)
            video_playback_enabled  = data.get("video_playback_enabled", False)
            print(f"[AutostartEverything] Loaded backend={backend!r} vm={vm!r} "
                  f"watchdog={watchdog!r} test_mode={test_mode!r} "
                  f"os_voting_vm={os_voting_vm!r} os_voting_backend={os_voting_backend!r} "
                  f"ai_safety_enabled={ai_safety_enabled!r} ai_safety_provider={ai_safety_provider!r} "
                  f"music_playback_enabled={music_playback_enabled!r} "
                  f"video_playback_enabled={video_playback_enabled!r} from {abs_path}")
            return (backend, vm, watchdog, test_mode, os_voting_vm, os_voting_backend,
                    ai_safety_enabled, ai_safety_provider,
                    music_playback_enabled, video_playback_enabled)
        else:
            print(f"[AutostartEverything] No saved config found at {abs_path} -- using defaults.")
    except Exception as e:
        print(f'[AutostartEverything] Load error: Python exception: "{traceback.format_exc()}"')
    return "vmware", "", False, False, "", "", False, "gemini", False, False

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
    global RECONNECT_CONFIG
    try:
        if os.path.exists(RECONNECT_CONFIG_FILE):
            with open(RECONNECT_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            RECONNECT_CONFIG.update(data)
            print("[Reconnect] Config loaded.")
    except Exception as e:
        print(f'[Reconnect] Load error: Python exception: "{traceback.format_exc()}"')

def save_reconnect_config():
    try:
        with open(RECONNECT_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(RECONNECT_CONFIG, f, indent=2)
        print("[Reconnect] Config saved.")
    except Exception as e:
        print(f'[Reconnect] Save error: Python exception: "{traceback.format_exc()}"')

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
        print(f'[OSVoting] Load error: Python exception: "{traceback.format_exc()}"')
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
        print(f'[OSVoting] Save error: Python exception: "{traceback.format_exc()}"')

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
    os_vote_required_now = get_vote_threshold("os_vote_required", OS_VOTE_REQUIRED)
    for trig, entry in trigger_map.items():
        count   = len(os_votes.get(trig, set()))
        pct     = min(100, int(count / os_vote_required_now * 100))
        is_cur  = (entry.get("vm") == current_os_vm)
        bar_col = "#3ddc97" if is_cur else "#7c5cbf"
        name_style = "color:#3ddc97;font-weight:bold;" if is_cur else ""
        rows += f"""
        <div class="row">
          <div class="label" style="{name_style}">{entry['name']}
            <span class="trigger">!{trig}</span>
          </div>
          <div class="bar-wrap">
            <div class="bar" style="width:{pct}%;background:{bar_col};"></div>
          </div>
          <div class="count" style="color:{bar_col};">{count}<span class="sep">/</span>{os_vote_required_now}</div>
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
      border-radius:16px;
      padding:18px 22px 14px;
      min-width:340px;
      max-width:420px;
      backdrop-filter:blur(6px);
    }}
    #title{{
      font-size:22px;
      font-weight:700;
      color:#b39ddb;
      letter-spacing:1px;
      text-align:center;
      margin-bottom:4px;
    }}
    #current{{
      font-size:13px;
      color:#3ddc97;
      text-align:center;
      margin-bottom:14px;
      opacity:0.9;
    }}
    .row{{
      display:flex;
      align-items:center;
      gap:10px;
      margin-bottom:9px;
    }}
    .label{{
      font-size:15px;
      font-weight:600;
      min-width:120px;
      flex-shrink:0;
      white-space:nowrap;
      overflow:hidden;
      text-overflow:ellipsis;
    }}
    .trigger{{
      font-size:11px;
      color:#aaa;
      font-weight:400;
      margin-left:5px;
    }}
    .bar-wrap{{
      flex:1;
      background:rgba(255,255,255,0.1);
      border-radius:8px;
      height:16px;
      overflow:hidden;
    }}
    .bar{{
      height:100%;
      border-radius:8px;
      transition:width 0.4s ease;
      min-width:4px;
    }}
    .count{{
      font-size:16px;
      font-weight:700;
      min-width:36px;
      text-align:right;
    }}
    .sep{{color:rgba(255,255,255,0.3);font-weight:300;margin:0 1px;}}
    #empty{{color:#888;font-size:13px;text-align:center;padding:8px 0;}}
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
        print(f'[OSVoting] Status write error: Python exception: "{traceback.format_exc()}"')

def apply_current_os_scene():
    """If OS Voting is enabled, finds which configured OS the currently active VM
    corresponds to and switches OBS to that OS's own Live scene (Per-OS Scene
    Switching / os_scenes). switch_os() already does this at the end of an actual
    OS-voting switch -- this covers everywhere ELSE the VM boots back up with OS
    voting on: !restart, !revert, !startvm, the scheduler, and the down-VM watchdog
    auto-restart. Those all bring the SAME OS back up, so OBS should return to
    'live for that OS', not sit on whatever scene was showing before (e.g. a
    Switching Scene, or one a mod changed to manually)."""
    if not OS_VOTING_ENABLED:
        return
    try:
        for entry in OS_LIST:
            if entry.get("vm") == VM_NAME:
                trig = (entry.get("trigger") or "").strip().lower().lstrip("!")
                scene = OBS_CONFIG.get("os_scenes", {}).get(trig, "")
                if scene:
                    threading.Thread(target=obs_set_scene, args=(scene,), daemon=True).start()
                break
    except Exception as e:
        print(f'[OBS] apply_current_os_scene error: Python exception: "{traceback.format_exc()}"')

def _kill_backend_processes(vm_name, backend, nuclear=False):
    """Force-kills the OS-level process(es) actually backing a specific VM -- used as
    an escalation step when the backend's own stop/poweroff command hasn't actually
    gotten the VM to stop within the allotted time. Targets only THIS VM's process by
    matching its name/path in the process command line, not every VM under that
    backend. nuclear=True additionally widens the match, for the final, most
    aggressive tier."""
    try:
        pattern = re.escape(vm_name)
        if backend == "vmware":
            # vmware-vmx is the actual per-VM process; its command line includes the
            # .vmx path, so this targets only this specific VM.
            subprocess.run(["pkill", "-9", "-f", f"vmware-vmx.*{pattern}"],
                            capture_output=True, timeout=10)
            if nuclear:
                subprocess.run(["pkill", "-9", "-f", f"vmware.*{pattern}"],
                                capture_output=True, timeout=10)
        elif backend == "vbox":
            subprocess.run(["pkill", "-9", "-f", f"VBoxHeadless.*{pattern}"],
                            capture_output=True, timeout=10)
            subprocess.run(["pkill", "-9", "-f", f"VBoxSDL.*{pattern}"],
                            capture_output=True, timeout=10)
            if nuclear:
                subprocess.run(["pkill", "-9", "-f", f"VirtualBoxVM.*{pattern}"],
                                capture_output=True, timeout=10)
    except Exception as e:
        print(f'[Poweroff] Process-kill error: Python exception: "{traceback.format_exc()}"')

def robust_vm_poweroff(vm_name, backend, source="Poweroff"):
    """Escalating, verified shutdown for ANY backend -- this is the actual fix for VMs
    not powering off when switching to a different one: the old logic fired a single
    hard-stop command and just slept 3 seconds, with no check that it actually worked
    before moving on to start the next VM. This instead:
      1. Tries a graceful ACPI shutdown, then polls actual VM state for up to 15s.
      2. If still running, does a force poweroff (hard stop) AND kills the specific
         backend process for this VM, then polls for up to another 15s.
      3. If STILL running, does a final nuclear pass: kills every related process for
         this VM more broadly.
    Returns True once the VM is confirmed stopped (or was never running to begin
    with), False if even the nuclear tier didn't get it to stop."""
    if not vm_name:
        return True   # nothing to power off

    def _confirm_stopped(timeout_s):
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if not vm_is_running(vm_name, backend):
                return True
            time.sleep(1)
        return not vm_is_running(vm_name, backend)

    if not vm_is_running(vm_name, backend):
        return True   # already off

    # Tier 1: graceful ACPI shutdown
    print(f"[{source}] Requesting graceful shutdown of '{vm_name}' ({backend})...")
    try:
        _checked(vm_stop(vm_name, backend, hard=False))
    except Exception as e:
        print(f'[{source}] Graceful shutdown command error (continuing to escalate): '
              f'Python exception: "{traceback.format_exc()}"')
    if _confirm_stopped(15):
        print(f"[{source}] '{vm_name}' confirmed stopped after graceful shutdown.")
        return True

    # Tier 2: force poweroff + kill this VM's specific backend process
    print(f"[{source}] '{vm_name}' still running after 15s -- forcing poweroff.")
    try:
        _checked(vm_stop(vm_name, backend, hard=True))
    except Exception as e:
        print(f'[{source}] Force poweroff command error (continuing to escalate): '
              f'Python exception: "{traceback.format_exc()}"')
    _kill_backend_processes(vm_name, backend, nuclear=False)
    if _confirm_stopped(15):
        print(f"[{source}] '{vm_name}' confirmed stopped after force poweroff.")
        return True

    # Tier 3: nuclear -- kill everything related to this VM
    print(f"[{source}] '{vm_name}' still running after force poweroff -- nuclear kill.")
    _kill_backend_processes(vm_name, backend, nuclear=True)
    if _confirm_stopped(10):
        print(f"[{source}] '{vm_name}' confirmed stopped after nuclear kill.")
        return True

    log_error(source, f"Could not confirm '{vm_name}' ({backend}) stopped even after "
                       f"graceful, force, and nuclear kill attempts.")
    return False

def switch_os(target_entry, announce=True):
    """
    Powers off the current OS VM (if different) and boots the target OS VM.
    Retries startvm up to 3 times. If all attempts fail, tries to revive
    the previous (loser) VM so at least something is running.
    """
    global current_os_vm, VM_NAME, os_switch_in_progress, os_votes, os_vote_start_time, current_vm_backend
    if not os_switch_lock.acquire(blocking=False):
        print("[OSVoting] Switch already in progress, ignoring duplicate request.")
        return
    os_switch_in_progress = True
    previous_vm = current_os_vm   # remember loser in case winner fails to start
    try:
        target_name = target_entry.get("name", "Unknown OS")
        target_vm   = target_entry.get("vm", "")
        target_backend = target_entry.get("backend", "vbox")
        if not target_vm:
            print("[OSVoting] Target entry has no VM assigned, aborting switch.")
            return
        if announce:
            speak_text(f"Switching to {target_name}...")
        update_status(f"Switching to {target_name}...")

        # Show this OS's own "switching" placeholder scene right away, before its
        # per-OS scene (os_scenes) takes over once it's actually up and running.
        target_trig = (target_entry.get("trigger") or "").strip().lower().lstrip("!")
        sw_scene = OBS_CONFIG.get("switching_scenes", {}).get(target_trig, "")
        if sw_scene:
            threading.Thread(target=obs_set_scene, args=(sw_scene,), daemon=True).start()

        # Step 1: power off the loser (best-effort, non-fatal). The loser might be on a
        # DIFFERENT backend than the winner -- look its own backend up independently
        # rather than assuming, so it gets powered off with the right tool.
        if current_os_vm and current_os_vm != target_vm:
            previous_backend = get_backend_for_vm(current_os_vm)
            ok = robust_vm_poweroff(current_os_vm, previous_backend, source="OSVoting/poweroff")
            if not ok:
                log_error("OSVoting", f"Could not confirm loser VM '{current_os_vm}' "
                                       f"({previous_backend}) fully powered off -- "
                                       f"proceeding to start the target anyway.")

        # Step 2: start the winner, using ITS OWN configured backend
        ok, err = retry_vbox(
            lambda: _checked(vm_start(target_vm, target_backend, gui=True)),
            attempts=3, delay=4, source="OSVoting/startvm"
        )

        if ok:
            current_os_vm = target_vm
            VM_NAME = target_vm
            current_vm_backend = target_backend  # every subsequent VM-lifecycle command
                                                  # now follows this OS's backend
            update_status(f"Running {target_name}")
            play_success_sound()
            play_event_sound("os_switch_sound")
            _append_event("OS_SWITCH", "vote", f"switched to {target_name} ({target_backend})")
            notify("OS Switched", f"Now running: {target_name}")
            obs_trigger("os_switch")
            _stats["os_switches"] += 1
            # Per-OS scene: look up by trigger key
            trig_key = target_entry.get("trigger", "").strip().lower().lstrip("!")
            os_scene = OBS_CONFIG.get("os_scenes", {}).get(trig_key, "")
            if os_scene:
                threading.Thread(target=obs_set_scene, args=(os_scene,), daemon=True).start()
            save_os_voting_config()
            print(f"[OSVoting] Switched to '{target_name}' ({target_vm}, backend: {target_backend})")
        else:
            # Winner failed — attempt to revive the previous (loser) VM, using ITS OWN backend
            log_error("OSVoting", f"All startvm attempts failed for '{target_name}' ({target_backend})", str(err))
            notify("OS Switch Failed",
                   f"Could not start {target_name}. Attempting to restore previous OS...",
                   timeout=7)
            update_status("OS switch failed — restoring previous OS...")
            if previous_vm and previous_vm != target_vm:
                recover_backend = get_backend_for_vm(previous_vm)
                ok2, err2 = retry_vbox(
                    lambda: _checked(vm_start(previous_vm, recover_backend, gui=True)),
                    attempts=3, delay=4, source="OSVoting/fallback"
                )
                if ok2:
                    current_vm_backend = recover_backend
                    VM_NAME = previous_vm
                    update_status(f"Restored previous OS")
                    notify("Previous OS Restored", "The previous OS was brought back online.")
                    print(f"[OSVoting] Fallback: restored previous VM '{previous_vm}' ({recover_backend})")
                else:
                    log_error("OSVoting", f"Fallback also failed for '{previous_vm}'", str(err2))
                    notify("Critical: No VM Running",
                           "Both the target and previous OS failed to start. Check VirtualBox / VMware Workstation.",
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
    global os_votes, os_vote_start_time
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

def speak_text(text):
    if not SOUND_CONFIG.get("tts_enabled", True):
        return
    def _speak():
        try:
            rate   = int(SOUND_CONFIG.get("tts_rate", 150))
            if platform.system() == "Darwin":
                # macOS's native 'say' command -- no pywin32/SAPI equivalent needed.
                # HONEST NOTE: 'say' has no direct per-utterance volume control the way
                # SAPI's speaker.Volume does (it would need `osascript -e "set volume ..."`,
                # which changes the whole system's output volume, not just this one
                # utterance) -- rate maps cleanly to -r (words per minute), volume doesn't
                # port here.
                wpm = max(90, min(360, rate))
                subprocess.run(["say", "-r", str(wpm), text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
                return
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            volume = int(SOUND_CONFIG.get("tts_volume", 100))
            # SAPI Rate: -10 to +10 (maps from words-per-minute ~50-400)
            # We convert: rate=150 → 0; rate=300 → +5; rate=50 → -5
            sapi_rate = max(-10, min(10, int((rate - 150) / 25)))
            speaker.Rate   = sapi_rate
            speaker.Volume = max(0, min(100, volume))
            speaker.Speak(text)
        except Exception as e:
            print(f'[Speech] Error: Python exception: "{traceback.format_exc()}"')
    threading.Thread(target=_speak, daemon=True).start()

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


def send_keyboard(text):
    risky, reason = ai_check_risk(text, kind="text")
    if risky:
        console_log("WARN", f'[Gemini] Blocked typed text: "{text}" -- {reason}')
        notify("Text Command Blocked", f"Gemini flagged a possible copyright risk: {reason}", timeout=8)
        return
    try:
        subprocess.run([VBOXMANAGE_PATH, 'controlvm', VM_NAME, 'keyboardputstring', text], check=True)
        print(f"[KB] Typed: {text}")
    except Exception as e:
        print(f'[KB] Error: Python exception: "{traceback.format_exc()}"')

def send_scancode(scancode_str):
    try:
        bytes_list = [scancode_str[i:i+2] for i in range(0, len(scancode_str), 2)]
        for byte in bytes_list:
            subprocess.run([VBOXMANAGE_PATH, 'controlvm', VM_NAME, 'keyboardputscancode', byte], check=True)
            time.sleep(0.008)
    except Exception as e:
        print(f'[Scancode] Error: Python exception: "{traceback.format_exc()}"')

def send_special_enter():
    send_scancode('1c')
    time.sleep(0.015)
    send_scancode('9c')

def play_success_sound():
    try:
        subprocess.Popen(['start', SUCCESS_SOUND_FILE], shell=True)
    except Exception as e:
        print(f'[Sound] Error: Python exception: "{traceback.format_exc()}"')

def start_vm():
    try:
        update_status("Starting...")
        obs_trigger("vm_starting")
        _checked(vm_start(VM_NAME, current_vm_backend, gui=True))
        update_status("Running")
        obs_trigger("start_done")
        apply_current_os_scene()
        print("[VM] Started!")
    except Exception as e:
        update_status("VM is already running!")
        print(f'[VM] Already running: Python exception: "{traceback.format_exc()}"')

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

_MOUSE_CLICK_COMMANDS = {"click", "lclick", "lc", "rclick", "rightclick", "rc",
                         "mclick", "middleclick", "dclick", "tripleclick"}

def handle_mouse(cmd, args):
    action_desc = f"[mouse {cmd} {args}]".strip()
    if cmd in _MOUSE_CLICK_COMMANDS:
        # Only click-type commands actually trigger a full AI check -- a click is
        # what would complete/submit a navigation (an address bar's Go, a link),
        # whereas move/drag/scroll alone have no meaningful content to evaluate and
        # are far too high-frequency to check individually without being needlessly
        # slow/expensive. Still recorded into history below either way, so a
        # subsequent text check can see the full recent sequence.
        risky, reason = ai_check_risk(action_desc, kind="text")
        if risky:
            console_log("WARN", f'[Gemini] Blocked mouse action: "{action_desc}" -- {reason}')
            notify("Mouse Command Blocked", f"AI safety flagged a possible risk: {reason}", timeout=8)
            return
    else:
        _record_and_get_recent_text_context(action_desc)   # record only, no API call
    session = None
    try:
        mouse, session = get_mouse_and_session()
        parts   = args.split()
        buttons = 0

        def _is_int(s):
            s = s.strip()
            return s.lstrip('-').isdigit()

        _DIRS = {'left': (-1, 0), 'right': (1, 0), 'up': (0, -1), 'down': (0, 1)}

        if cmd in ['move', 'mouse', 'mv', 'm']:
            if len(parts) == 2:
                p0, p1 = parts[0].lower(), parts[1].lower()
                if p0 in _DIRS and _is_int(p1):
                    ux, uy = _DIRS[p0]; amt = int(p1)
                    mouse.putMouseEvent(ux * amt, uy * amt, 0, 0, buttons)
                elif p1 in _DIRS and _is_int(p0):
                    ux, uy = _DIRS[p1]; amt = int(p0)
                    mouse.putMouseEvent(ux * amt, uy * amt, 0, 0, buttons)
                elif _is_int(p0) and _is_int(p1):
                    mouse.putMouseEvent(int(p0), int(p1), 0, 0, buttons)
            elif len(parts) == 1 and parts[0].lower() in _DIRS:
                ux, uy = _DIRS[parts[0].lower()]
                mouse.putMouseEvent(ux * 20, uy * 20, 0, 0, buttons)
        elif cmd in ['abs', 'cursor', 'moveabs']:
            if len(parts) == 2:
                mouse.putMouseEventAbsolute(int(parts[0]), int(parts[1]), 0, 0, buttons)
        elif cmd in ['click', 'lclick', 'lc']:
            count = int(args) if args.isdigit() else 1
            for _ in range(count):
                mouse.putMouseEvent(0,0,0,0,1)
                mouse.putMouseEvent(0,0,0,0,0)
        elif cmd == 'dclick':
            for _ in range(2):
                mouse.putMouseEvent(0,0,0,0,1)
                mouse.putMouseEvent(0,0,0,0,0)
        elif cmd == 'tripleclick':
            for _ in range(3):
                mouse.putMouseEvent(0,0,0,0,1)
                mouse.putMouseEvent(0,0,0,0,0)
        elif cmd in ['rclick', 'rightclick', 'rc']:
            count = int(args) if args.isdigit() else 1
            for _ in range(count):
                mouse.putMouseEvent(0,0,0,0,2)
                mouse.putMouseEvent(0,0,0,0,0)   # release right button
        elif cmd in ['mclick', 'middleclick']:
            count = int(args) if args.isdigit() else 1
            for _ in range(count):
                mouse.putMouseEvent(0,0,0,0,4)
                mouse.putMouseEvent(0,0,0,0,0)   # release middle button
        elif cmd in ['drag', 'dragrel', 'd']:
            if len(parts) >= 2:
                button = 1 if len(parts)==2 else (1 if parts[0]=='left' else 2 if parts[0]=='right' else 4)
                dx, dy = int(parts[-2]), int(parts[-1])
                mouse.putMouseEvent(0,0,0,0,button)
                mouse.putMouseEvent(dx,dy,0,0,button)
                mouse.putMouseEvent(0,0,0,0,0)
        elif cmd in ['dragabs', 'drag_absolute']:
            if len(parts) >= 2:
                button = 1 if len(parts)==2 else (1 if parts[0]=='left' else 2 if parts[0]=='right' else 4)
                x, y = int(parts[-2]), int(parts[-1])
                mouse.putMouseEventAbsolute(x,y,0,0,button)
                mouse.putMouseEventAbsolute(x,y,0,0,0)
        elif cmd in ['scroll', 'wheel']:
            dz = int(args) if args else 0
            mouse.putMouseEvent(0,0,dz,0,0)
        elif cmd == 'scrollup':
            amt = int(args) if args.strip().isdigit() else 3
            mouse.putMouseEvent(0,0,amt,0,0)
        elif cmd == 'scrolldown':
            amt = int(args) if args.strip().isdigit() else 3
            mouse.putMouseEvent(0,0,-amt,0,0)
        print(f"[Mouse] {cmd} {args}")
    except Exception as e:
        print(f'[Mouse] Error: Python exception: "{traceback.format_exc()}"')
    finally:
        # Always release the session — even if the command raised an exception.
        # Skipping this locks the VirtualBox machine permanently until process restart.
        if session is not None:
            unlock_session(session)

def update_ban_vote_display(target, current_votes, required, remaining_time=None):
    action_text = f"Ban @{target}" if target else "No ban vote active"
    active = bool(target) and current_votes > 0
    timer_text = f"⏱ {int(remaining_time)}s remaining" if (remaining_time is not None and active) else "Waiting..."
    pct = min(100, int((current_votes / required) * 100)) if required else 0
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Ban Vote Overlay</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}

        html, body {{
            background-color: transparent;
            width: 320px;
            overflow: hidden;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            color: white;
            padding: 10px;
        }}

        .vote-box {{
            border-radius: 10px;
            padding: 15px;
            margin-bottom: 15px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.9);
            transform: translateZ(0);
        }}

        /* BAN — red, matching this bot's existing ban-vote color scheme */
        #ban-box {{
            background-color: #2a0a0a;
            border: 2px solid #ff4444;
        }}

        #ban-box .vote-title  {{ color: #ff4444; text-shadow: 0 0 10px rgba(255,68,68,0.8); }}
        #ban-box .vote-info   {{ color: #ffdddd; }}
        #ban-box .vote-info.timer {{ color: #ffaaaa; }}
        #ban-box .progress-container {{ background-color: #200a0a; border: 1px solid #aa0000; }}
        #ban-box .progress-bar {{
            background: linear-gradient(90deg, #aa0000, #ff4444);
            box-shadow: 0 0 8px #ff4444;
        }}

        .vote-title {{
            font-size: 18px;
            font-weight: bold;
            text-align: center;
            margin-bottom: 10px;
        }}

        .vote-info {{
            font-size: 15px;
            font-weight: 700;
            text-align: center;
            margin-bottom: 5px;
        }}

        .vote-info.timer {{
            font-size: 13px;
            font-weight: 600;
        }}

        .progress-container {{
            border-radius: 10px;
            width: 100%;
            height: 12px;
            margin-top: 10px;
            overflow: hidden;
        }}

        .progress-bar {{
            height: 100%;
            width: {pct}%;
            transition: width 0.3s ease;
        }}
    </style>
</head>
<body>
    <div class="vote-box" id="ban-box">
        <div class="vote-title">🚫 Ban Vote</div>
        <div class="vote-info" id="ban-collected">{action_text} — {current_votes} / {required} votes</div>
        <div class="vote-info timer" id="ban-time">{timer_text}</div>
        <div class="progress-container">
            <div class="progress-bar" id="ban-bar"></div>
        </div>
    </div>
    <script>setInterval(()=>location.reload(),3000);</script>
</body>
</html>"""
    with open(VOTE_FILE_BAN, "w", encoding="utf-8") as f: f.write(html)

def update_status(message):
    html = f"""<html><head><style>
    body{{background:rgba(0,0,0,0);color:white;font-family:Arial;font-size:32px;text-align:center;text-shadow:2px 2px 4px #000;}}
    #s{{margin-top:20px;padding:10px;background:rgba(0,0,0,0.4);border-radius:8px;display:inline-block;}}
    </style></head><body><div id="s">Status: {message}</div>
    <script>setInterval(()=>location.reload(),10000);</script></body></html>"""
    with open(STATUS_FILE, "w", encoding="utf-8") as f: f.write(html)
    print(f"[Status] {message}")

def vote_timeout_checker():
    global vote_restart, vote_revert, ban_votes, restart_start_time, revert_start_time
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
    global revert_in_progress
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
                        obs_trigger("vm_starting")
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
                            if HOST_SWITCH_CONFIG.get("sync_vm_name"):
                                host_switch_sync_vm_name(VM_NAME)
                        else:
                            log_error("Watchdog", f"Failed to auto-restart VM after 3 attempts", str(err))
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

# ── Config file paths for Music / Video / Soundboard (transferred from chatuses.py) ──
music_config_file = "music_config.json"
video_config_file = "video_config.json"
soundboard_config_file = "soundboard_config.json"
fun_high_scores_file = "fun_high_scores.json"
# Best-ever results across sessions for the Fun tab's tests/games. None means "not
# set yet" for reaction_ms specifically (0 would incorrectly look like an
# impossibly-fast real result); the others default sensibly to 0.
fun_high_scores = {
    "wpm": 0.0,
    "accuracy": 0.0,
    "cps": 0.0,
    "reaction_ms": None,
    "snake_score": 0,
}

def load_fun_high_scores():
    global fun_high_scores
    try:
        if os.path.exists(fun_high_scores_file):
            with open(fun_high_scores_file, "r", encoding="utf-8") as f:
                fun_high_scores.update(json.load(f))
        print(f"[FunTab] High scores loaded: {fun_high_scores}")
    except Exception:
        pass

def save_fun_high_scores():
    safe_json_dump(fun_high_scores_file, fun_high_scores)
    print(f"[FunTab] High scores saved: {fun_high_scores}")


# ---------------- Music panel (yt-dlp + python-vlc) ----------------
MUSIC_SCHEDULE_MAX = 20
music_config = {
    "tracks": [],       # list of single yt urls
    "playlists": [],    # list of yt playlist urls (played shuffle+loop)
    "schedule": [],     # ordered list: {"type": "track"/"playlist", "url": "..."}
    "change_hours": 1,  # advance to next schedule slot every N hours
    "enabled": False,
}
music_lock = threading.RLock()
music_player = None            # vlc.Instance
music_media_player = None      # vlc.MediaPlayer
music_media_list_player = None # vlc.MediaListPlayer (for shuffled/looped playlists)
music_stop_event = threading.Event()
music_thread = None
music_status_text = "stopped"
music_current_desc = ""
music_track_naturally_ended = threading.Event()  # set when a single track finishes -- change_hours
                                                   # is a PLAYLIST-only wait; a lone track should
                                                   # advance the schedule immediately when it ends.

# ========================= MUSIC / VIDEO / SOUNDBOARD ENGINE =========================
# Transferred from chatuses.py (VLC-based YouTube music/video queue players + web-search
# soundboard). Controlled via the new ð§ Media tab and the !play / !video / !sb chat commands.
def load_music_config():
    global music_config
    try:
        if os.path.exists(music_config_file):
            with open(music_config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            music_config.update(data)
    except Exception: pass
    music_config["schedule"] = music_config.get("schedule", [])[:MUSIC_SCHEDULE_MAX]

def save_music_config():
    safe_json_dump(music_config_file, music_config)

_DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

def _music_resolve_playlist_entries(url):
    """Lightweight (no stream resolution) listing of a playlist's video urls, via yt-dlp's flat extraction."""
    if not ytdlp_available: return []
    ydl_opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist", "skip_download": True}
    urls = []
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        entries = info.get("entries") if isinstance(info, dict) else None
        if entries:
            for entry in entries:
                if not entry: continue
                vid = entry.get("id") or entry.get("url")
                if not vid: continue
                urls.append(vid if str(vid).startswith("http") else f"https://www.youtube.com/watch?v={vid}")
        elif isinstance(info, dict) and info.get("id"):
            urls.append(url)
    except Exception as e:
        console_log("ERROR", f'[music] failed to list playlist {url}: Python exception: "{traceback.format_exc()}"')
    return urls

def _music_resolve_stream(url):
    """Use yt-dlp to resolve a single video/track to a direct playable stream url + http headers."""
    if not ytdlp_available: return None, None, None
    ydl_opts = {
        "format": "bestaudio[ext=m4a]/bestaudio/best", "quiet": True, "no_warnings": True,
        "noplaylist": True, "skip_download": True,
        # The "android" client is far less likely to get throttled/require extra signature
        # work than the default web client, which is the #1 cause of resolved-but-unplayable
        # streams. Falls back to "web" if android extraction fails for a given video.
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        stream_url = info.get("url")
        if not stream_url and info.get("entries"):
            info = info["entries"][0]
            stream_url = info.get("url")
        if not stream_url: return None, None, None
        headers = info.get("http_headers") or {}
        title = info.get("title") or url
        return stream_url, headers, title
    except Exception as e:
        console_log("ERROR", f'[music] yt-dlp resolve failed for {url}: Python exception: "{traceback.format_exc()}"')
        return None, None, None

def _music_get_vlc_instance():
    global music_player
    if not vlc_available: return None
    if music_player is None:
        try: music_player = _vlc.Instance("--no-video", "--quiet", "--aout=any")
        except Exception as e:
            console_log("ERROR", f'[music] vlc init failed: Python exception: "{traceback.format_exc()}"')
            return None
    return music_player

# ---- queue-based engine: resolves + plays one track at a time, auto-advances on end ----
music_queue = []          # list of source urls (watch page urls) for the current schedule item
music_queue_index = -1
music_queue_is_playlist = False
music_queue_source_url = ""

# ---- !sr song requests: queued and played at the NEXT scheduled music change, not immediately ----
music_song_requests = []  # list of {"url": watch/playlist url, "is_playlist": bool, "raw": original text, "user": requester}

def _music_parse_request(raw):
    """Turns a video id/url or playlist id/url into (watch_or_playlist_url, is_playlist)."""
    raw = (raw or "").strip().strip("<>").strip()
    if not raw: return None, False
    if raw.startswith("http://") or raw.startswith("https://"):
        m = re.search(r"[?&]list=([A-Za-z0-9_-]+)", raw)
        if m: return f"https://www.youtube.com/playlist?list={m.group(1)}", True
        return raw, False
    if raw.upper().startswith(("PL", "UU", "OL", "RD", "LL", "FL", "WL")) and len(raw) >= 10:
        return f"https://www.youtube.com/playlist?list={raw}", True
    return f"https://www.youtube.com/watch?v={raw}", False

def queue_song_request(raw, user=""):
    """Queues a !sr request; it plays automatically the next time the music schedule advances."""
    risky, reason = ai_check_risk(raw, kind="song")
    if risky:
        console_log("WARN", f"[Gemini] Blocked song request from {user}: \"{raw}\" -- {reason}")
        notify("Song Request Blocked", f"Gemini flagged a possible copyright risk: {reason}", timeout=8)
        return None
    url, is_playlist = _music_parse_request(raw)
    if not url: return None
    with music_lock:
        music_song_requests.append({"url": url, "is_playlist": is_playlist, "raw": raw, "user": user})
    return url, is_playlist

def find_youtube_video_id(query):
    """The engine behind !findsr: searches YouTube for `query` and returns the first result's
    video id, or None if nothing was found / the search failed."""
    query = (query or "").strip()
    if not query: return None
    try:
        search_url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
        req = urllib.request.Request(search_url, headers={"User-Agent": _DEFAULT_UA})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        m = re.search(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)
        return m.group(1) if m else None
    except Exception as e:
        console_log("ERROR", f'[findsr] youtube search failed: Python exception: "{traceback.format_exc()}"')
        return None

def _music_on_end_reached(event):
    # Runs on a libvlc-internal thread; hop to a normal Python thread before doing real work.
    console_log("INFO", "[music] track finished, advancing to next in queue.")
    threading.Thread(target=_music_advance_queue, daemon=True).start()

def _music_on_playback_error(event):
    global music_status_text
    music_status_text = "playback error encountered mid-track, skipping after short delay..."
    console_log("ERROR", f"[music] {music_status_text}")
    notify("Music Playback Error", "A track failed to stream and will be skipped.", timeout=5)
    def _delayed_advance():
        time.sleep(2.5)  # avoid hammering the CDN/VLC in a tight failure loop
        _music_advance_queue()
    threading.Thread(target=_delayed_advance, daemon=True).start()

def _music_advance_queue():
    global music_queue_index
    if music_stop_event.is_set(): return
    with music_lock:
        if not music_queue: return
        if not music_queue_is_playlist:
            # A single track just finished. change_hours is meant to govern how long a
            # PLAYLIST stays on rotation -- a lone track shouldn't loop itself or sit waiting
            # out the rest of that hour. Signal music_player_loop to move on right away.
            music_track_naturally_ended.set()
            return
        music_queue_index += 1
        if music_queue_index >= len(music_queue):
            music_queue_index = 0
            if music_queue_is_playlist:
                random.shuffle(music_queue)  # loop = restart shuffled playlist from the top
        target = music_queue[music_queue_index]
    _music_play_queue_current(target)

def _music_play_queue_current(watch_url, _attempt=1):
    global music_media_player, music_status_text, music_current_desc
    inst = _music_get_vlc_instance()
    if inst is None:
        music_status_text = "vlc/yt-dlp not available"
        return False
    stream, headers, title = _music_resolve_stream(watch_url)
    if not stream:
        if _attempt < 3:
            music_status_text = f"resolve failed (attempt {_attempt}/3), retrying: {watch_url}"
            console_log("WARN", f"[music] {music_status_text}")
            def _retry():
                time.sleep(2.5)
                _music_play_queue_current(watch_url, _attempt + 1)
            threading.Thread(target=_retry, daemon=True).start()
            return False
        music_status_text = f"failed to resolve after 3 attempts, skipping: {watch_url}"
        console_log("WARN", f"[music] {music_status_text}")
        notify("Music Error", f"Couldn't resolve after 3 tries: {watch_url}", timeout=5)
        threading.Thread(target=_music_advance_queue, daemon=True).start()
        return False
    try:
        media = inst.media_new(stream)
        ua = (headers or {}).get("User-Agent", _DEFAULT_UA)
        media.add_option(f":http-user-agent={ua}")
        media.add_option(":http-referrer=https://www.youtube.com/")
        media.add_option(":http-reconnect")
        media.add_option(":network-caching=4000")
        mp = inst.media_player_new()
        mp.set_media(media)
        try: mp.audio_set_volume(int(music_config.get("volume", 90)))
        except Exception: pass
        ev = mp.event_manager()
        ev.event_attach(_vlc.EventType.MediaPlayerEndReached, _music_on_end_reached)
        ev.event_attach(_vlc.EventType.MediaPlayerEncounteredError, _music_on_playback_error)
        mp.play()
        old = music_media_player
        music_media_player = mp
        try:
            if old is not None: old.stop()
        except Exception: pass
        music_current_desc = title or watch_url
        music_status_text = f"playing: {music_current_desc}"
        console_log("INFO", f"[music] {music_status_text}")
        notify("Now Playing", music_current_desc, timeout=4)
        return True
    except Exception as e:
        music_status_text = f"playback error: {e}"
        console_log("ERROR", f"[music] {music_status_text}")
        notify("Music Error", str(e), timeout=5)
        return False

def music_play_url(url, shuffle_loop=False):
    """Start playing a single track, or (if shuffle_loop) a playlist url shuffled+looping."""
    global music_queue, music_queue_index, music_queue_is_playlist, music_queue_source_url, music_status_text
    if not vlc_available or not ytdlp_available:
        music_status_text = "vlc/yt-dlp not available"
        return False
    music_stop_current()
    music_track_naturally_ended.clear()
    with music_lock:
        if shuffle_loop:
            entries = _music_resolve_playlist_entries(url)
            if not entries: entries = [url]
            random.shuffle(entries)
            music_queue = entries
        else:
            music_queue = [url]
        music_queue_index = 0
        music_queue_is_playlist = shuffle_loop
        music_queue_source_url = url
        first = music_queue[0]
    return _music_play_queue_current(first)

def music_skip_track():
    """Manually skip to the next track in the current queue."""
    threading.Thread(target=_music_advance_queue, daemon=True).start()

def music_stop_current():
    global music_media_player
    try:
        if music_media_player is not None:
            ev = music_media_player.event_manager()
            try:
                ev.event_detach(_vlc.EventType.MediaPlayerEndReached)
                ev.event_detach(_vlc.EventType.MediaPlayerEncounteredError)
            except Exception: pass
            music_media_player.stop()
    except Exception: pass
    music_media_player = None

def music_pause_toggle():
    try:
        if music_media_player is not None:
            music_media_player.pause()
    except Exception: pass

def music_set_volume(vol):
    music_config["volume"] = max(0, min(100, int(vol)))
    save_music_config()
    try:
        if music_media_player is not None: music_media_player.audio_set_volume(music_config["volume"])
    except Exception: pass

def music_player_loop():
    """Advances through the schedule every `change_hours` hours, in order, looping.
    Any pending !sr song requests are played first, ahead of the schedule, at each change."""
    global music_status_text
    idx = 0
    while _gui_app is None:
        time.sleep(1)
    while (not bot_stop_event.is_set()) and not music_stop_event.is_set():
        with music_lock:
            pending = music_song_requests.pop(0) if music_song_requests else None
            schedule = list(music_config.get("schedule", []))
            hours = float(music_config.get("change_hours", 1) or 1)

        if pending:
            music_play_url(pending["url"], shuffle_loop=pending["is_playlist"])
            kind = "playlist" if pending["is_playlist"] else "track"
            who = f" (requested by {pending['user']})" if pending.get("user") else ""
            notify("Song Request", f"Now playing requested {kind}{who}.", timeout=5)
            wait_seconds = max(30, hours * 3600)
            waited = 0
            while waited < wait_seconds and not music_stop_event.is_set() and (not bot_stop_event.is_set()):
                if not pending["is_playlist"] and music_track_naturally_ended.is_set():
                    music_track_naturally_ended.clear()
                    break  # single track -- move on the moment it ends, don't wait out the hour
                if music_stop_event.wait(2): break
                waited += 2
            continue  # request didn't consume a schedule slot -- idx stays put

        if not schedule or not music_config.get("enabled", False):
            music_status_text = "stopped (no schedule / disabled)"
            music_stop_current()
            if music_stop_event.wait(5): break
            continue
        idx = idx % len(schedule)
        item = schedule[idx]
        url, itype = item.get("url", ""), item.get("type", "track")
        if url:
            music_play_url(url, shuffle_loop=(itype == "playlist"))
            notify("Music Schedule", f"Now on schedule slot {idx + 1}/{len(schedule)} ({itype}).", timeout=4)
        else:
            music_track_naturally_ended.clear()
        wait_seconds = max(30, hours * 3600)
        waited = 0
        while waited < wait_seconds and not music_stop_event.is_set() and (not bot_stop_event.is_set()):
            if itype != "playlist" and music_track_naturally_ended.is_set():
                music_track_naturally_ended.clear()
                break  # single track -- move on the moment it ends, don't wait out the hour
            if music_stop_event.wait(2): break
            waited += 2
        idx += 1
    music_stop_current()
    console_log("INFO", "[music] player loop stopped.")

def start_music_player():
    global music_thread
    music_stop_event.clear()
    if music_thread is None or not music_thread.is_alive():
        music_thread = threading.Thread(target=music_player_loop, daemon=True)
        music_thread.start()

def stop_music_player():
    music_stop_event.set()
    music_stop_current()

# ---------------- Video panel (yt-dlp + python-vlc, rendered into a movable window) ----------------
# Same engine/schedule design as the Music panel above, except tracks are resolved as a playable
# VIDEO stream (not audio-only) and rendered into a floating, draggable Toplevel window (the OS
# window titlebar itself is what makes it "movable" -- position/size persist across restarts).
VIDEO_SCHEDULE_MAX = 20
video_config = {
    "tracks": [],       # list of single yt urls
    "playlists": [],    # list of yt playlist urls (played shuffle+loop)
    "schedule": [],     # ordered list: {"type": "track"/"playlist", "url": "..."}
    "change_hours": 1,  # advance to next schedule slot every N hours
    "enabled": False,
    "volume": 90,
    "window_x": None, "window_y": None, "window_w": 640, "window_h": 360,
    "always_on_top": False,
}
video_lock = threading.RLock()
video_player = None            # vlc.Instance (video-enabled, separate from the Music panel's)
video_media_player = None      # vlc.MediaPlayer
video_stop_event = threading.Event()
video_thread = None
video_status_text = "stopped"
video_current_desc = ""
video_track_naturally_ended = threading.Event()  # same purpose as the Music panel's flag

def load_video_config():
    global video_config
    try:
        if os.path.exists(video_config_file):
            with open(video_config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            video_config.update(data)
    except Exception: pass
    video_config["schedule"] = video_config.get("schedule", [])[:VIDEO_SCHEDULE_MAX]

def save_video_config():
    safe_json_dump(video_config_file, video_config)

# playlist listing and id/url parsing are format-agnostic (audio vs video), so the Music panel's
# helpers are reused as-is instead of duplicating them.
_video_resolve_playlist_entries = _music_resolve_playlist_entries
_video_parse_request = _music_parse_request

def _video_resolve_stream(url):
    """Use yt-dlp to resolve a single video/track to a direct playable VIDEO stream url + headers."""
    if not ytdlp_available: return None, None, None
    ydl_opts = {
        "format": "best[ext=mp4]/best", "quiet": True, "no_warnings": True,
        "noplaylist": True, "skip_download": True,
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        stream_url = info.get("url")
        if not stream_url and info.get("entries"):
            info = info["entries"][0]
            stream_url = info.get("url")
        if not stream_url: return None, None, None
        headers = info.get("http_headers") or {}
        title = info.get("title") or url
        return stream_url, headers, title
    except Exception as e:
        console_log("ERROR", f'[video] yt-dlp resolve failed for {url}: Python exception: "{traceback.format_exc()}"')
        return None, None, None

def _video_get_vlc_instance():
    global video_player
    if not vlc_available: return None
    if video_player is None:
        try: video_player = _vlc.Instance("--quiet")
        except Exception as e:
            console_log("ERROR", f'[video] vlc init failed: Python exception: "{traceback.format_exc()}"')
            return None
    return video_player

def _video_ensure_window_sync(timeout=5):
    """Runs from a background thread: hops to the Tk main thread to (re)create/show the movable
    video window, waits for it, then returns the native window id VLC should render into."""
    if _gui_app is None: return None
    ready = threading.Event()
    result = {}
    def _create():
        try:
            _gui_app.ensure_video_window()
            result["winid"] = _gui_app.video_canvas.winfo_id()
        except Exception as e:
            result["error"] = e
        ready.set()
    try:
        _gui_app.root.after(0, _create)
    except Exception:
        return None
    ready.wait(timeout)
    return result.get("winid")

# ---- queue-based engine: resolves + plays one clip at a time, auto-advances on end ----
video_queue = []          # list of source urls (watch page urls) for the current schedule item
video_queue_index = -1
video_queue_is_playlist = False
video_queue_source_url = ""

# ---- !vr video requests: queued and played at the NEXT scheduled video change, not immediately ----
video_requests = []  # list of {"url": watch/playlist url, "is_playlist": bool, "raw": original text, "user": requester}

def queue_video_request(raw, user=""):
    """Queues a !vr request; it plays automatically the next time the video schedule advances."""
    risky, reason = ai_check_risk(raw, kind="video")
    if risky:
        console_log("WARN", f"[Gemini] Blocked video request from {user}: \"{raw}\" -- {reason}")
        notify("Video Request Blocked", f"Gemini flagged a possible copyright risk: {reason}", timeout=8)
        return None
    url, is_playlist = _video_parse_request(raw)
    if not url: return None
    with video_lock:
        video_requests.append({"url": url, "is_playlist": is_playlist, "raw": raw, "user": user})
    return url, is_playlist

def _video_on_end_reached(event):
    # Runs on a libvlc-internal thread; hop to a normal Python thread before doing real work.
    console_log("INFO", "[video] clip finished, advancing to next in queue.")
    threading.Thread(target=_video_advance_queue, daemon=True).start()

def _video_on_playback_error(event):
    global video_status_text
    video_status_text = "playback error encountered mid-clip, skipping after short delay..."
    console_log("ERROR", f"[video] {video_status_text}")
    notify("Video Playback Error", "A clip failed to stream and will be skipped.", timeout=5)
    def _delayed_advance():
        time.sleep(2.5)  # avoid hammering the CDN/VLC in a tight failure loop
        _video_advance_queue()
    threading.Thread(target=_delayed_advance, daemon=True).start()

def _video_advance_queue():
    global video_queue_index
    if video_stop_event.is_set(): return
    with video_lock:
        if not video_queue: return
        if not video_queue_is_playlist:
            # A single clip just finished. change_hours is meant to govern how long a
            # PLAYLIST stays on rotation -- a lone clip shouldn't loop itself or sit waiting
            # out the rest of that hour. Signal video_player_loop to move on right away.
            video_track_naturally_ended.set()
            return
        video_queue_index += 1
        if video_queue_index >= len(video_queue):
            video_queue_index = 0
            if video_queue_is_playlist:
                random.shuffle(video_queue)  # loop = restart shuffled playlist from the top
        target = video_queue[video_queue_index]
    _video_play_queue_current(target)

def _video_play_queue_current(watch_url, _attempt=1):
    global video_media_player, video_status_text, video_current_desc
    inst = _video_get_vlc_instance()
    if inst is None:
        video_status_text = "vlc/yt-dlp not available"
        return False
    stream, headers, title = _video_resolve_stream(watch_url)
    if not stream:
        if _attempt < 3:
            video_status_text = f"resolve failed (attempt {_attempt}/3), retrying: {watch_url}"
            console_log("WARN", f"[video] {video_status_text}")
            def _retry():
                time.sleep(2.5)
                _video_play_queue_current(watch_url, _attempt + 1)
            threading.Thread(target=_retry, daemon=True).start()
            return False
        video_status_text = f"failed to resolve after 3 attempts, skipping: {watch_url}"
        console_log("WARN", f"[video] {video_status_text}")
        notify("Video Error", f"Couldn't resolve after 3 tries: {watch_url}", timeout=5)
        threading.Thread(target=_video_advance_queue, daemon=True).start()
        return False
    winid = _video_ensure_window_sync()
    if not winid:
        video_status_text = "couldn't open the video window"
        console_log("ERROR", f"[video] {video_status_text}")
        return False
    try:
        media = inst.media_new(stream)
        ua = (headers or {}).get("User-Agent", _DEFAULT_UA)
        media.add_option(f":http-user-agent={ua}")
        media.add_option(":http-referrer=https://www.youtube.com/")
        media.add_option(":http-reconnect")
        media.add_option(":network-caching=4000")
        mp = inst.media_player_new()
        mp.set_media(media)
        try:
            plat = platform.system()
            if plat == "Windows": mp.set_hwnd(winid)
            elif plat == "Darwin": mp.set_nsobject(winid)
            else: mp.set_xwindow(winid)
        except Exception as e:
            console_log("ERROR", f'[video] failed to bind video output to window: Python exception: "{traceback.format_exc()}"')
        try: mp.audio_set_volume(int(video_config.get("volume", 90)))
        except Exception: pass
        ev = mp.event_manager()
        ev.event_attach(_vlc.EventType.MediaPlayerEndReached, _video_on_end_reached)
        ev.event_attach(_vlc.EventType.MediaPlayerEncounteredError, _video_on_playback_error)
        mp.play()
        old = video_media_player
        video_media_player = mp
        try:
            if old is not None: old.stop()
        except Exception: pass
        video_current_desc = title or watch_url
        video_status_text = f"playing: {video_current_desc}"
        console_log("INFO", f"[video] {video_status_text}")
        notify("Now Playing (Video)", video_current_desc, timeout=4)
        if _gui_app is not None:
            desc = video_current_desc
            _gui_app.root.after(0, lambda: _gui_app.set_video_window_title(desc))
        return True
    except Exception as e:
        video_status_text = f"playback error: {e}"
        console_log("ERROR", f"[video] {video_status_text}")
        notify("Video Error", str(e), timeout=5)
        return False

def video_play_url(url, shuffle_loop=False):
    """Start playing a single clip, or (if shuffle_loop) a playlist url shuffled+looping."""
    global video_queue, video_queue_index, video_queue_is_playlist, video_queue_source_url, video_status_text
    if not vlc_available or not ytdlp_available:
        video_status_text = "vlc/yt-dlp not available"
        return False
    video_stop_current()
    video_track_naturally_ended.clear()
    with video_lock:
        if shuffle_loop:
            entries = _video_resolve_playlist_entries(url)
            if not entries: entries = [url]
            random.shuffle(entries)
            video_queue = entries
        else:
            video_queue = [url]
        video_queue_index = 0
        video_queue_is_playlist = shuffle_loop
        video_queue_source_url = url
        first = video_queue[0]
    return _video_play_queue_current(first)

def video_skip_track():
    """Manually skip to the next clip in the current queue."""
    threading.Thread(target=_video_advance_queue, daemon=True).start()

def video_stop_current():
    global video_media_player
    try:
        if video_media_player is not None:
            ev = video_media_player.event_manager()
            try:
                ev.event_detach(_vlc.EventType.MediaPlayerEndReached)
                ev.event_detach(_vlc.EventType.MediaPlayerEncounteredError)
            except Exception: pass
            video_media_player.stop()
    except Exception: pass
    video_media_player = None

def video_pause_toggle():
    try:
        if video_media_player is not None:
            video_media_player.pause()
    except Exception: pass

def video_set_volume(vol):
    video_config["volume"] = max(0, min(100, int(vol)))
    save_video_config()
    try:
        if video_media_player is not None: video_media_player.audio_set_volume(video_config["volume"])
    except Exception: pass

def video_player_loop():
    """Advances through the schedule every `change_hours` hours, in order, looping.
    Any pending !vr video requests are played first, ahead of the schedule, at each change."""
    global video_status_text
    idx = 0
    while _gui_app is None:
        time.sleep(1)
    while (not bot_stop_event.is_set()) and not video_stop_event.is_set():
        with video_lock:
            pending = video_requests.pop(0) if video_requests else None
            schedule = list(video_config.get("schedule", []))
            hours = float(video_config.get("change_hours", 1) or 1)

        if pending:
            video_play_url(pending["url"], shuffle_loop=pending["is_playlist"])
            kind = "playlist" if pending["is_playlist"] else "video"
            who = f" (requested by {pending['user']})" if pending.get("user") else ""
            notify("Video Request", f"Now playing requested {kind}{who}.", timeout=5)
            wait_seconds = max(30, hours * 3600)
            waited = 0
            while waited < wait_seconds and not video_stop_event.is_set() and (not bot_stop_event.is_set()):
                if not pending["is_playlist"] and video_track_naturally_ended.is_set():
                    video_track_naturally_ended.clear()
                    break  # single clip -- move on the moment it ends, don't wait out the hour
                if video_stop_event.wait(2): break
                waited += 2
            continue  # request didn't consume a schedule slot -- idx stays put

        if not schedule or not video_config.get("enabled", False):
            video_status_text = "stopped (no schedule / disabled)"
            video_stop_current()
            if video_stop_event.wait(5): break
            continue
        idx = idx % len(schedule)
        item = schedule[idx]
        url, itype = item.get("url", ""), item.get("type", "track")
        if url:
            video_play_url(url, shuffle_loop=(itype == "playlist"))
            notify("Video Schedule", f"Now on schedule slot {idx + 1}/{len(schedule)} ({itype}).", timeout=4)
        else:
            video_track_naturally_ended.clear()
        wait_seconds = max(30, hours * 3600)
        waited = 0
        while waited < wait_seconds and not video_stop_event.is_set() and (not bot_stop_event.is_set()):
            if itype != "playlist" and video_track_naturally_ended.is_set():
                video_track_naturally_ended.clear()
                break  # single clip -- move on the moment it ends, don't wait out the hour
            if video_stop_event.wait(2): break
            waited += 2
        idx += 1
    video_stop_current()
    console_log("INFO", "[video] player loop stopped.")

def start_video_player():
    global video_thread
    video_stop_event.clear()
    if video_thread is None or not video_thread.is_alive():
        video_thread = threading.Thread(target=video_player_loop, daemon=True)
        video_thread.start()

def stop_video_player():
    video_stop_event.set()
    video_stop_current()

# ---------------- Soundboard panel (web search only, python-vlc for playback) ----------------
# !sb <search term> searches myinstants.com, takes the FIRST result, and plays it. No local
# sound files/folders involved -- pygame kept failing to build on newer Python versions (no
# prebuilt wheel + distutils removed), and this reuses python-vlc, which the Music panel already
# needs, so there's no extra dependency to install.
soundboard_config = {"volume": 90}
soundboard_lock = threading.RLock()
soundboard_status_text = "idle"
soundboard_vlc_instance = None     # vlc.Instance, separate from the Music panel's
soundboard_active_players = []     # live vlc.MediaPlayer refs, kept so overlapping sounds don't get GC'd mid-playback

def load_soundboard_config():
    global soundboard_config
    try:
        if os.path.exists(soundboard_config_file):
            with open(soundboard_config_file, "r", encoding="utf-8") as f:
                soundboard_config.update(json.load(f))
    except Exception: pass

def save_soundboard_config():
    safe_json_dump(soundboard_config_file, soundboard_config)

def _soundboard_get_vlc_instance():
    global soundboard_vlc_instance
    if not vlc_available: return None
    if soundboard_vlc_instance is None:
        try: soundboard_vlc_instance = _vlc.Instance("--no-video", "--quiet", "--aout=any")
        except Exception as e:
            console_log("ERROR", f'[soundboard] vlc init failed: Python exception: "{traceback.format_exc()}"')
            return None
    return soundboard_vlc_instance

# ---- !sb web search: searches myinstants.com, grabs the FIRST result, downloads and plays it
# (the "red button" on an instant's page is just the JS play() call -- we pull the mp3 straight
# from that button's onclick instead of literally clicking it in a browser) ----
def _soundboard_cache_dir():
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "soundboard_web_cache")
    try: os.makedirs(d, exist_ok=True)
    except Exception: pass
    return d

def _soundboard_cache_key(query):
    key = re.sub(r"[^a-zA-Z0-9_-]+", "_", (query or "").strip().lower()).strip("_")
    return (key or "sound")[:60]

def _soundboard_web_search_first(query):
    """Searches myinstants.com for `query` and returns (mp3_url, display_name) for the FIRST
    result on the page, or (None, None) if nothing was found."""
    search_url = "https://www.myinstants.com/en/search/?name=" + urllib.parse.quote(query)
    try:
        req = urllib.request.Request(search_url, headers={"User-Agent": _DEFAULT_UA})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        console_log("ERROR", f'[soundboard] myinstants search failed: Python exception: "{traceback.format_exc()}"')
        return None, None
    # Each result button is onclick="play('/media/sounds/<file>.mp3','<id>')" -- the FIRST match
    # on the results page is the first search result (myinstants lists them in relevance order).
    m = re.search(r"onclick=\"play\('([^']+)'", html)
    if not m:
        return None, None
    mp3_path = m.group(1)
    mp3_url = mp3_path if mp3_path.startswith("http") else "https://www.myinstants.com" + mp3_path
    name_m = re.search(r'<a[^>]+href="/en/instant/[^"]+"[^>]*>([^<]+)</a>', html)
    display_name = name_m.group(1).strip() if name_m else query
    return mp3_url, display_name

def _soundboard_web_fetch_by_id(instant_id):
    """Fetches a myinstants.com instant page directly by its slug/id (the part of the URL after
    /en/instant/, e.g. 'mlg-air-horn' from myinstants.com/en/instant/mlg-air-horn/) and returns
    (mp3_url, display_name), or (None, None) if that id doesn't exist. No search/guessing --
    this is the exact sound, unlike !sb which takes the first search RESULT."""
    instant_id = instant_id.strip().strip("/")
    page_url = f"https://www.myinstants.com/en/instant/{urllib.parse.quote(instant_id)}/"
    try:
        req = urllib.request.Request(page_url, headers={"User-Agent": _DEFAULT_UA})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, None
        console_log("ERROR", f"[soundboard] myinstants id lookup failed ({e.code}): {instant_id}")
        return None, None
    except Exception as e:
        console_log("ERROR", f'[soundboard] myinstants id lookup failed: Python exception: "{traceback.format_exc()}"')
        return None, None
    m = re.search(r"onclick=\"play\('([^']+)'", html)
    if not m:
        return None, None
    mp3_path = m.group(1)
    mp3_url = mp3_path if mp3_path.startswith("http") else "https://www.myinstants.com" + mp3_path
    title_m = re.search(r"<h1[^>]*>([^<]+)</h1>", html)
    display_name = title_m.group(1).strip() if title_m else instant_id
    return mp3_url, display_name

def _soundboard_play_file(path, label):
    """Plays a local mp3 file via python-vlc. Each call spawns its own MediaPlayer, so multiple
    soundboard clips (and music) can overlap without stepping on each other."""
    global soundboard_status_text
    inst = _soundboard_get_vlc_instance()
    if inst is None:
        soundboard_status_text = "python-vlc not available"
        return False, "python-vlc is not installed (pip install python-vlc, and install VLC itself)"
    try:
        media = inst.media_new(path)
        mp = inst.media_player_new()
        mp.set_media(media)
        try: mp.audio_set_volume(int(soundboard_config.get("volume", 90)))
        except Exception: pass
        mp.play()
        with soundboard_lock:
            soundboard_active_players.append(mp)
            # periodically drop refs to players that have finished, so the list doesn't grow forever
            soundboard_active_players[:] = [p for p in soundboard_active_players if p is mp or p.is_playing()][-30:]
        soundboard_status_text = f"playing: {label}"
        console_log("INFO", f"[soundboard] {soundboard_status_text}")
        return True, label
    except Exception as e:
        soundboard_status_text = f"playback error: {e}"
        console_log("ERROR", f"[soundboard] {soundboard_status_text}")
        return False, str(e)

def _soundboard_download_and_play(mp3_url, label, save_path):
    global soundboard_status_text
    try:
        req = urllib.request.Request(mp3_url, headers={"User-Agent": _DEFAULT_UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        with open(save_path, "wb") as f:
            f.write(data)
    except Exception as e:
        soundboard_status_text = f"download failed: {e}"
        console_log("ERROR", f"[soundboard] {soundboard_status_text}")
        return False, str(e)
    return _soundboard_play_file(save_path, label)

def soundboard_stop_all():
    global soundboard_status_text
    with soundboard_lock:
        for p in soundboard_active_players:
            try: p.stop()
            except Exception: pass
        soundboard_active_players.clear()
    soundboard_status_text = "stopped all sounds"

def soundboard_set_volume(vol):
    soundboard_config["volume"] = max(0, min(100, int(float(vol))))
    save_soundboard_config()
    with soundboard_lock:
        for p in soundboard_active_players:
            try: p.audio_set_volume(soundboard_config["volume"])
            except Exception: pass

def soundboard_web_search_and_play(query, user=""):
    """The engine behind !sb <name>: searches myinstants.com for `query`, takes the first
    result, and plays it -- pulling the mp3 straight off the result's play button instead of
    literally driving a browser. Repeat searches are served from a local disk cache."""
    global soundboard_status_text
    query = (query or "").strip()
    if not query:
        return False, "no search term given"
    if not vlc_available:
        return False, "python-vlc is not installed (pip install python-vlc, and install VLC itself)"

    cache_path = os.path.join(_soundboard_cache_dir(), _soundboard_cache_key(query) + ".mp3")
    if os.path.exists(cache_path):
        return _soundboard_play_file(cache_path, query)

    soundboard_status_text = f"searching myinstants for '{query}'..."
    console_log("INFO", f"[soundboard] {soundboard_status_text}")
    mp3_url, display_name = _soundboard_web_search_first(query)
    if not mp3_url:
        soundboard_status_text = f"no results for '{query}'"
        return False, f"no soundboard results found for '{query}'"

    soundboard_status_text = f"downloading '{display_name}'..."
    console_log("INFO", f"[soundboard] {soundboard_status_text}")
    return _soundboard_download_and_play(mp3_url, display_name, cache_path)

def soundboard_web_id_and_play(instant_id, user=""):
    """The engine behind !sbid <id>: fetches a myinstants.com instant page directly by its
    exact slug/id (the part of the URL after /en/instant/) and plays it -- no search, no
    'first result' guessing, just that one sound. Cached separately from !sb's cache."""
    global soundboard_status_text
    instant_id = (instant_id or "").strip()
    if not instant_id:
        return False, "no soundboard id given"
    if not vlc_available:
        return False, "python-vlc is not installed (pip install python-vlc, and install VLC itself)"

    cache_path = os.path.join(_soundboard_cache_dir(), "id_" + _soundboard_cache_key(instant_id) + ".mp3")
    if os.path.exists(cache_path):
        return _soundboard_play_file(cache_path, instant_id)

    soundboard_status_text = f"looking up myinstants id '{instant_id}'..."
    console_log("INFO", f"[soundboard] {soundboard_status_text}")
    mp3_url, display_name = _soundboard_web_fetch_by_id(instant_id)
    if not mp3_url:
        soundboard_status_text = f"no soundboard found for id '{instant_id}'"
        return False, f"no soundboard found for id '{instant_id}' (check the id in the myinstants.com URL)"

    soundboard_status_text = f"downloading '{display_name}'..."
    console_log("INFO", f"[soundboard] {soundboard_status_text}")
    return _soundboard_download_and_play(mp3_url, display_name, cache_path)



# ========================= EXTENDED COMMAND LIBRARY =========================
# Backing functions for the full !command reference (mouse/keyboard extras, VM/system
# control, voice, fun/chaos, music/video queue admin, and admin-only utilities).

# ── Chat gate (for !pausechat / !enablechat) ──
CHAT_COMMANDS_PAUSED = False

# ── Google TTS (host speakers) ──
gtts_vlc_instance = None
gtts_lock = threading.RLock()
gtts_active_players = []
gtts_status_text = "idle"

def _gtts_cache_dir():
    d = os.path.join(script_dir(), "gtts_cache")
    try: os.makedirs(d, exist_ok=True)
    except Exception: pass
    return d

def _gtts_cache_key(text):
    key = re.sub(r"[^a-zA-Z0-9_-]+", "_", (text or "").strip().lower()).strip("_")
    return (key or "speech")[:60]

def _gtts_get_vlc_instance():
    global gtts_vlc_instance
    if not vlc_available: return None
    if gtts_vlc_instance is None:
        try: gtts_vlc_instance = _vlc.Instance("--no-video", "--quiet", "--aout=any")
        except Exception as e:
            console_log("ERROR", f'[gtts] vlc init failed: Python exception: "{traceback.format_exc()}"')
            return None
    return gtts_vlc_instance

def gtts_speak(text, lang="en"):
    """Google TTS (!gtts) -- speaks on the HOST's speakers, cached to disk by text.
    Distinct from !tts (SAPI, above) per the command reference."""
    global gtts_status_text
    text = (text or "").strip()
    if not text:
        return False, "no text given"
    if not gtts_available:
        return False, "gTTS is not installed (pip install gTTS)"
    inst = _gtts_get_vlc_instance()
    if inst is None:
        return False, "python-vlc is not installed (pip install python-vlc, and install VLC itself)"
    cache_path = os.path.join(_gtts_cache_dir(), _gtts_cache_key(text) + ".mp3")
    if not os.path.exists(cache_path):
        gtts_status_text = f"synthesizing '{text[:40]}'..."
        console_log("INFO", f"[gtts] {gtts_status_text}")
        try:
            _gTTS(text=text, lang=lang).save(cache_path)
        except Exception as e:
            gtts_status_text = f"synthesis failed: {e}"
            console_log("ERROR", f"[gtts] {gtts_status_text}")
            return False, str(e)
    try:
        media = inst.media_new(cache_path)
        mp = inst.media_player_new()
        mp.set_media(media)
        try: mp.audio_set_volume(int(SOUND_CONFIG.get("tts_volume", 100)))
        except Exception: pass
        mp.play()
        with gtts_lock:
            gtts_active_players.append(mp)
            gtts_active_players[:] = [p for p in gtts_active_players if p is mp or p.is_playing()][-30:]
        gtts_status_text = f"speaking: {text[:60]}"
        console_log("INFO", f"[gtts] {gtts_status_text}")
        return True, text
    except Exception as e:
        gtts_status_text = f"playback error: {e}"
        console_log("ERROR", f"[gtts] {gtts_status_text}")
        return False, str(e)

def beep():
    if winsound_available:
        try:
            _winsound.Beep(880, 200)
            return
        except Exception:
            pass
    if platform.system() == "Darwin":
        try:
            subprocess.run(["osascript", "-e", "beep"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            return
        except Exception:
            pass
    print("\a", end="", flush=True)  # terminal bell fallback

# ── TTS loop control (!ttsloop / !ttsxploop) ──
_tts_loop_stop = threading.Event()

def tts_loop(text, reps=8, interval=4.0, xp_style=False):
    _tts_loop_stop.clear()
    def _run():
        for _ in range(reps):
            if _tts_loop_stop.is_set():
                break
            speak_text(text)
            if _tts_loop_stop.wait(interval):
                break
    threading.Thread(target=_run, daemon=True, name="tts_loop").start()

def stop_tts_loop():
    _tts_loop_stop.set()

# ── Extra VM / system control (uses the same VM_NAME / current_vm_backend
#    and retry_vbox() the rest of the bot already relies on) ──
def vm_shutdown_soft():
    ok, err = retry_vbox(lambda: _checked(vm_stop(VM_NAME, current_vm_backend, hard=False)),
                          source="Cmd/shutdown")
    if ok:
        obs_trigger("vm_shutdown")
    return ok, err

def vm_shutdown_hard_kill():
    ok, err = retry_vbox(lambda: _checked(vm_stop(VM_NAME, current_vm_backend, hard=True)),
                          source="Cmd/killvm")
    if ok:
        obs_trigger("vm_shutdown")
    return ok, err

def vm_pause():
    if current_vm_backend == "vmware":
        return retry_vbox(lambda: subprocess.run([VMRUN_PATH, '-T', VMRUN_TARGET_TYPE, 'pause', VM_NAME], check=True, timeout=20),
                           source="Cmd/pausevm")
    return retry_vbox(lambda: subprocess.run([VBOXMANAGE_PATH, 'controlvm', VM_NAME, 'pause'], check=True),
                       source="Cmd/pausevm")

def vm_unpause():
    if current_vm_backend == "vmware":
        return retry_vbox(lambda: subprocess.run([VMRUN_PATH, '-T', VMRUN_TARGET_TYPE, 'unpause', VM_NAME], check=True, timeout=20),
                           source="Cmd/resumevm")
    return retry_vbox(lambda: subprocess.run([VBOXMANAGE_PATH, 'controlvm', VM_NAME, 'resume'], check=True),
                       source="Cmd/resumevm")

def vm_save_state():
    if current_vm_backend == "vmware":
        return retry_vbox(lambda: subprocess.run([VMRUN_PATH, '-T', VMRUN_TARGET_TYPE, 'suspend', VM_NAME], check=True, timeout=30),
                           source="Cmd/vmsavestate")
    return retry_vbox(lambda: subprocess.run([VBOXMANAGE_PATH, 'controlvm', VM_NAME, 'savestate'], check=True),
                       source="Cmd/vmsavestate")

def vm_make_snapshot(name):
    name = (name or "").strip() or time.strftime("snap_%Y%m%d_%H%M%S")
    return retry_vbox(lambda: _checked(vm_take_snapshot(VM_NAME, name, current_vm_backend)),
                       source="Cmd/makesnapshot")

INTERNET_CONFIG_FILE = "vm_internet_config.json"
INTERNET_CONFIG = {"enabled": True}

def save_internet_config():
    safe_json_dump(INTERNET_CONFIG_FILE, INTERNET_CONFIG)

def vm_set_internet_live(enabled, os_type=None, iface=None):
    """Toggles the CURRENT vm's internet. VBox: unplugs/replugs the virtual network cable
    via VBoxManage controlvm setlinkstate1 -- works on a running VM, no restart needed.
    VMware: starts/stops the host-wide 'VMware NAT Service' instead (matches the
    VMware-flavored script's own mechanism), since vmrun has no equivalent live per-VM
    toggle."""
    if not VM_NAME:
        return False, "No VM selected yet -- start the bot first to select a VM."
    if current_vm_backend == "vmware":
        try:
            result = vmware_toggle_internet(enabled, VMRUN_PATH)
            output = (result.stdout or "") + (result.stderr or "")
            INTERNET_CONFIG["enabled"] = enabled
            save_internet_config()
            return result.returncode == 0, output.strip() or f"net {'start' if enabled else 'stop'} exited {result.returncode}"
        except Exception as e:
            return False, str(e)
    try:
        args = [VBOXMANAGE_PATH, 'controlvm', VM_NAME, 'setlinkstate1', 'on' if enabled else 'off']
        result = subprocess.run(args, capture_output=True, text=True, timeout=20)
        output = (result.stdout or "") + (result.stderr or "")
        INTERNET_CONFIG["enabled"] = enabled
        save_internet_config()
        return result.returncode == 0, output.strip() or f"setlinkstate1 {'on' if enabled else 'off'} exited {result.returncode}"
    except Exception as e:
        return False, str(e)

def run_admin_cmd(command_text):
    """!cmd -- opens Command Prompt inside the VM (via Win+R) and runs `command_text`.
    Elevation depends on the VM's own UAC settings."""
    if not command_text.strip():
        return
    send_combo(['win', 'r'])
    time.sleep(0.4)
    send_keyboard("cmd")
    send_special_enter()
    time.sleep(1.2)
    send_keyboard(command_text)
    send_special_enter()

def run_win_r(command_text):
    send_combo(['win', 'r'])
    time.sleep(0.4)
    send_keyboard(command_text)
    send_special_enter()

def open_folder(path):
    run_win_r(f'explorer "{path}"' if path.strip() else "explorer")

def open_file(path):
    run_win_r(f'"{path}"')

def taskkill_process(name):
    run_admin_cmd(f"taskkill /IM {name} /F")

# ── Fun / chaos mouse & desktop effects ──
# (VirtualBox's mouse API tracks position on the guest side, so unlike the VNC build
# these don't need a host-side cursor tracker -- relative moves accumulate naturally.)
def mouse_shake(duration=1.5, magnitude=25):
    def _run():
        end = time.time() + duration
        while time.time() < end and not bot_stop_event.is_set():
            handle_mouse('move', f"{random.randint(-magnitude, magnitude)} {random.randint(-magnitude, magnitude)}")
            time.sleep(0.04)
    threading.Thread(target=_run, daemon=True, name="mouse_shake").start()

def mouse_jiggle(duration=2.0, magnitude=6):
    mouse_shake(duration=duration, magnitude=magnitude)

def mouse_circle(radius=40, steps=24, loops=1):
    def _run():
        for _ in range(loops):
            for i in range(steps):
                if bot_stop_event.is_set():
                    return
                ang = 2 * math.pi * (i / steps)
                nang = 2 * math.pi * ((i + 1) / steps)
                dx = int(radius * (math.cos(nang) - math.cos(ang)))
                dy = int(radius * (math.sin(nang) - math.sin(ang)))
                handle_mouse('move', f"{dx} {dy}")
                time.sleep(0.03)
    threading.Thread(target=_run, daemon=True, name="mouse_circle").start()

def mouse_spiral(max_radius=80, steps=48):
    def _run():
        prev_x, prev_y = 0.0, 0.0
        for i in range(steps):
            if bot_stop_event.is_set():
                return
            r = max_radius * (i / steps)
            ang = 0.6 * i
            x = r * math.cos(ang)
            y = r * math.sin(ang)
            dx, dy = int(x - prev_x), int(y - prev_y)
            prev_x, prev_y = x, y
            handle_mouse('move', f"{dx} {dy}")
            time.sleep(0.03)
    threading.Thread(target=_run, daemon=True, name="mouse_spiral").start()

def msgbox_in_vm(text):
    """!msgbox -- pops a real message box inside the VM via a one-line PowerShell call."""
    text_escaped = (text or "").replace("'", "''")
    ps = ("powershell -windowstyle hidden -command "
          f"\"Add-Type -AssemblyName PresentationFramework; "
          f"[System.Windows.MessageBox]::Show('{text_escaped}')\"")
    run_win_r(ps)

def spam_text(text, n):
    n = max(1, min(int(n) if str(n).isdigit() else 1, 50))
    def _run():
        for _ in range(n):
            if bot_stop_event.is_set():
                return
            send_keyboard(text)
            send_special_enter()
            time.sleep(0.05)
    threading.Thread(target=_run, daemon=True, name="spam_text").start()

def countdown(start_n=5):
    """!countdown -- posts a countdown to the chat overlay (visible on chat.html /
    the Flask dashboard) once per second."""
    def _run():
        n = max(1, min(int(start_n) if str(start_n).isdigit() else 5, 30))
        for i in range(n, 0, -1):
            update_overlay(author="[system]", message=f"[countdown] {i}...", msg_id=f"cd-{time.time()}")
            print(f"[Countdown] {i}...")
            if bot_stop_event.wait(1):
                return
        update_overlay(author="[system]", message="[countdown] GO!", msg_id=f"cd-{time.time()}")
        print("[Countdown] GO!")
    threading.Thread(target=_run, daemon=True, name="countdown").start()

def matrix_effect(duration=3.0):
    """!matrix -- opens Notepad in the VM and floods it with Matrix-style falling
    characters as a cheap approximation of the classic screen effect."""
    def _run():
        run_win_r("notepad")
        time.sleep(1.0)
        chars = "01ｱｲｳｴｵｶｷｸｹｺABCDEFGHIJKLMNOPQRSTUVWXYZ"
        end = time.time() + duration
        while time.time() < end and not bot_stop_event.is_set():
            line = "".join(random.choice(chars) for _ in range(40))
            send_keyboard(line)
            send_special_enter()
            time.sleep(0.05)
    threading.Thread(target=_run, daemon=True, name="matrix_effect").start()

def randomize_colorscheme():
    """!colorscheme -- randomizes the VM's Windows accent color via PowerShell/registry."""
    color = f"{random.randint(0,255):02X}{random.randint(0,255):02X}{random.randint(0,255):02X}"
    ps = ("powershell -windowstyle hidden -command "
          f"\"Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\DWM' "
          f"-Name AccentColor -Value 0x{color} -Type DWord\"")
    run_win_r(ps)

def rainbow_effect(duration=6.0, interval=0.8):
    def _run():
        end = time.time() + duration
        while time.time() < end and not bot_stop_event.is_set():
            randomize_colorscheme()
            if bot_stop_event.wait(interval):
                return
    threading.Thread(target=_run, daemon=True, name="rainbow_effect").start()

def notepad_flood(count=6):
    count = max(1, min(int(count) if str(count).isdigit() else 6, 15))
    def _run():
        for _ in range(count):
            if bot_stop_event.is_set():
                return
            run_win_r("notepad")
            time.sleep(0.3)
    threading.Thread(target=_run, daemon=True, name="notepad_flood").start()

def exe_flood(count=6):
    count = max(1, min(int(count) if str(count).isdigit() else 6, 15))
    apps = ["calc", "mspaint", "notepad", "explorer"]
    def _run():
        for i in range(count):
            if bot_stop_event.is_set():
                return
            run_win_r(random.choice(apps))
            time.sleep(0.3)
    threading.Thread(target=_run, daemon=True, name="exe_flood").start()

def txt_flood(lines=20):
    lines = max(1, min(int(lines) if str(lines).isdigit() else 20, 100))
    def _run():
        run_win_r("notepad")
        time.sleep(1.0)
        for _ in range(lines):
            if bot_stop_event.is_set():
                return
            send_keyboard("".join(random.choice("abcdefghijklmnopqrstuvwxyz ") for _ in range(50)))
            send_special_enter()
            time.sleep(0.05)
    threading.Thread(target=_run, daemon=True, name="txt_flood").start()

def desktop_flood():
    """!deskflood -- combined chaos: notepad flood + exe flood + a colorscheme change."""
    notepad_flood(4)
    exe_flood(4)
    randomize_colorscheme()

# ── Info / chat commands ──
def post_system_message(text):
    print(text)
    update_overlay(author="[system]", message=text, msg_id=f"sys-{time.time()}")

def cmd_uptime_text():
    start = _stats.get("bot_start_time")
    if not start:
        return "[uptime] bot has not fully started yet"
    sec = int(time.time() - start)
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    return f"[uptime] {d}d {h}h {m}m {s}s"

def cmd_stats_text():
    return (f"[stats] commands: {_stats.get('total_commands', 0)} (this session: "
            f"{_stats.get('session_commands', 0)}) | os switches: {_stats.get('os_switches', 0)} "
            f"| reverts: {_stats.get('reverts', 0)} | restarts: {_stats.get('restarts', 0)}")

def cmd_history_text(n=5):
    try:
        with _event_log_lock:
            recent = list(_event_log)[-n:]
    except Exception:
        recent = []
    if not recent:
        return "[history] no recent events"
    parts = [f"{e.get('type', '?')}:{e.get('user', '?')}" for e in recent]
    return "[history] " + " | ".join(parts)

def cmd_leaderboard_text(top_n=5):
    counts = _stats.get("user_counts", {}) or {}
    if not counts:
        return "[leaderboard] no commands recorded yet"
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    return "[leaderboard] " + " | ".join(f"{u}: {c}" for u, c in top)

def cmd_queue_text():
    n = len(music_song_requests) + len(video_requests)
    return f"[queue] {n} pending request(s) ({len(music_song_requests)} song, {len(video_requests)} video)"

def cmd_status_text():
    running = overlay_data.get("running_command") or "Idle"
    vm_state = "running" if vm_is_running(VM_NAME, current_vm_backend) else "not running"
    return f"[status] bot: {running} | VM: {vm_state}"


class YouTubeChatBot:
    def __init__(self):
        self.video_id = VIDEO_ID
        self.chat = None
        self._reconnect_failures = 0
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
            try: self.chat.terminate()
            except: pass
        try:
            self.chat = pytchat.create(video_id=self.video_id)
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
        global restart_start_time, revert_start_time, revert_in_progress, restart_in_progress, restart_cooldown_until, revert_cooldown_until, os_vote_start_time, CHAT_COMMANDS_PAUSED
        if CHAT_COMMANDS_PAUSED:
            print("[pausechat] chat was left paused from a previous session -- auto-resuming on bot start.")
        CHAT_COMMANDS_PAUSED = False
        last_reconnect   = time.time()
        RECONNECT_INTERVAL = 150
        print("[Bot] Waiting for chat messages...")
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
                for c in self.chat.get().sync_items():
                    if bot_stop_event.is_set():
                        break
                    msg      = c.message.strip()
                    user     = normalize_username(c.author.name)
                    is_owner = getattr(c.author, 'isChatOwner', False)
                    is_mod   = is_owner or getattr(c.author, 'isChatModerator', False) or user == ADMIN_USERNAME.lower()
                    update_overlay(author=user, message=msg, msg_id=c.id)
                    if user in banned_users:
                        if time.time() < banned_users[user]: continue
                        else: del banned_users[user]
                    # Whitelist check: if enabled and user not in list (and not owner), skip
                    if whitelist_users and not is_owner and user not in whitelist_users:
                        continue
                    active_users.add(c.author.name.strip())
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
                        for part in chain_parts:
                            sub_parts = part.split(maxsplit=1)
                            cmd  = sub_parts[0].lower()
                            args = sub_parts[1] if len(sub_parts) > 1 else ""

                            # ── !pausechat gate: block everything except re-enabling it ──
                            if CHAT_COMMANDS_PAUSED and cmd not in ('enablechat',) and not (
                                    is_owner or user == ADMIN_USERNAME.lower()):
                                print(f"[pausechat] blocked '!{cmd}' from {user} (chat commands are paused -- "
                                      f"an admin needs to type !enablechat)")
                                continue

                            _record_command(cmd, user)

                            # ── Custom command check (first priority) ──
                            trigger = "!" + cmd
                            if trigger in custom_commands:
                                threading.Thread(
                                    target=execute_custom_command,
                                    args=(trigger,), daemon=True
                                ).start()
                                continue

                            # ── Per-OS Host Switching commands (e.g. !winwin11, !macmonterey) ──
                            if try_handle_host_switch_command(cmd):
                                continue

                            # ── OS voting commands (e.g. !win7, !win10) ──
                            if OS_VOTING_ENABLED:
                                os_trigger_map = get_os_trigger_map()
                                if cmd in os_trigger_map:
                                    if os_switch_in_progress:
                                        continue
                                    target_entry = os_trigger_map[cmd]
                                    # Mod/owner bypass: switch immediately, no vote needed
                                    if is_mod:
                                        print(f"[OSVoting] Switch bypassed by {'owner' if is_owner else 'mod'}: {user} → {target_entry['name']}")
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

                            # ── Built-in commands ──
                            if cmd in ['wait', 'pause', 'delay', 'w', 'sleep']:
                                try:
                                    delay = float(args)
                                    delay = max(0, min(delay, 5.0))
                                    time.sleep(delay)
                                except: pass
                                continue

                            if cmd in ['type', 'text', 'say', 't', 's']:
                                send_keyboard(args)
                            elif cmd in ['typeenter', 'send', 'sendline']:
                                send_keyboard(args)
                                send_special_enter()
                            elif cmd == 'enter':
                                send_special_enter()
                            elif cmd in ['fullscreen', 'fs']:
                                print("[Bot] Fullscreen hint (manual)")
                            elif cmd in ['move','mouse','mv','abs','cursor','moveabs','m',
                                         'drag','dragrel','dragabs','drag_absolute','d',
                                         'click','lclick','lc','dclick','tripleclick',
                                         'rclick','rightclick','rc',
                                         'mclick','middleclick','scroll','wheel',
                                         'scrollup','scrolldown']:
                                handle_mouse(cmd, args)
                            elif cmd in ['startvm','modlaunch','launchvm','start_mc','startmc']:
                                if time.time() - self.last_start_time > COOLDOWN_START:
                                    start_vm()
                                    self.last_start_time = time.time()
                                else:
                                    print("[Bot] !startvm cooldown active")
                            elif cmd in ['restore','refresh','restore_window','focus','front','bringtofront']:
                                restore_window()
                            elif cmd in ['key', 'press', 'k']:
                                k = args.lower().strip()
                                if k in SCANCODES:
                                    down, up = SCANCODES[k]
                                    send_scancode(down)
                                    time.sleep(0.01)
                                    send_scancode(up)
                                else:
                                    send_keyboard(k)
                            elif cmd in ['keydown', 'hold', 'kd']:
                                k = args.lower().strip()
                                if k in SCANCODES: send_scancode(SCANCODES[k][0])
                            elif cmd in ['keyup', 'release', 'ku']:
                                k = args.lower().strip()
                                if k in SCANCODES: send_scancode(SCANCODES[k][1])
                            elif cmd in ['combo','chord','multi','c']:
                                keys = args.lower().replace('+',' ').split()
                                if keys: send_combo(keys)
                                else: send_keyboard(args)
                            elif cmd == 'winkey':
                                k = args.lower().strip()
                                if k: send_combo(['win'] + k.replace('+', ' ').split())
                            elif cmd == 'run':
                                if args.strip():
                                    run_win_r(args.strip())
                                else:
                                    send_combo(['win','r'])
                            elif cmd == 'cmd':
                                run_admin_cmd(args)
                            elif cmd == 'dir':
                                open_folder(args)
                            elif cmd == 'openfile':
                                open_file(args)
                            elif cmd == 'taskkill':
                                if args.strip(): taskkill_process(args.strip())
                            # ── Music / Video / Soundboard commands (transferred from chatuses.py) ──
                            elif cmd in ('play', 'music', 'songrequest', 'sr'):
                                if args.strip():
                                    threading.Thread(target=queue_song_request, args=(args, user), daemon=True).start()
                                else:
                                    threading.Thread(target=start_music_player, daemon=True).start()
                            elif cmd in ('musicskip', 'skipsong', 'skipmusic'):
                                threading.Thread(target=music_skip_track, daemon=True).start()
                            elif cmd in ('stopmusic', 'musicstop'):
                                threading.Thread(target=music_stop_current, daemon=True).start()
                            elif cmd in ('musicpause', 'pausemusic'):
                                threading.Thread(target=music_pause_toggle, daemon=True).start()
                            elif cmd in ('musicvolume', 'musicvol'):
                                try: music_set_volume(float(args))
                                except Exception: pass
                            elif cmd in ('video', 'videorequest', 'vr'):
                                if args.strip():
                                    threading.Thread(target=queue_video_request, args=(args, user), daemon=True).start()
                                else:
                                    threading.Thread(target=start_video_player, daemon=True).start()
                            elif cmd in ('videoskip', 'skipvideo', 'vskip'):
                                threading.Thread(target=video_skip_track, daemon=True).start()
                            elif cmd in ('stopvideo', 'videostop'):
                                threading.Thread(target=video_stop_current, daemon=True).start()
                            elif cmd in ('videopause', 'pausevideo'):
                                threading.Thread(target=video_pause_toggle, daemon=True).start()
                            elif cmd in ('videovolume', 'videovol'):
                                try: video_set_volume(float(args))
                                except Exception: pass
                            elif cmd in ('sb', 'soundboard'):
                                if args.strip():
                                    threading.Thread(target=soundboard_web_search_and_play, args=(args, user), daemon=True).start()
                            elif cmd == 'sbid':
                                if args.strip():
                                    threading.Thread(target=soundboard_web_id_and_play, args=(args, user), daemon=True).start()
                            elif cmd in ('sbstop', 'soundboardstop'):
                                threading.Thread(target=soundboard_stop_all, daemon=True).start()
                            elif cmd in ('sbvolume', 'sbvol'):
                                try: soundboard_set_volume(float(args))
                                except Exception: pass
                            elif cmd == 'srqueue':
                                threading.Thread(target=post_queue_to_overlay,
                                                  args=("Song Queue", music_song_requests, music_queue),
                                                  daemon=True).start()
                            elif cmd == 'vrqueue':
                                threading.Thread(target=post_queue_to_overlay,
                                                  args=("Video Queue", video_requests, video_queue),
                                                  daemon=True).start()
                            elif cmd in ('findsr',):
                                if args.strip():
                                    def _findsr(q=args, u=user):
                                        vid = find_youtube_video_id(q)
                                        if vid:
                                            queue_song_request(vid, u)
                                        else:
                                            console_log("INFO", f"[findsr] no result for '{q}'")
                                    threading.Thread(target=_findsr, daemon=True).start()
                            elif cmd == 'skipsr':
                                if is_owner or user == ADMIN_USERNAME.lower():
                                    def _skipsr():
                                        music_skip_track()
                                        if music_song_requests:
                                            dropped = music_song_requests.pop(0)
                                            console_log("INFO", f"[skipsr] dropped next queued request: {dropped.get('raw')}")
                                    threading.Thread(target=_skipsr, daemon=True).start()
                            elif cmd == 'clearsr':
                                if is_owner or user == ADMIN_USERNAME.lower():
                                    music_song_requests.clear()
                                    post_system_message("[clearsr] pending song request queue cleared.")
                            elif cmd in ('findvr',):
                                if args.strip():
                                    def _findvr(q=args, u=user):
                                        vid = find_youtube_video_id(q)
                                        if vid:
                                            queue_video_request(vid, u)
                                        else:
                                            console_log("INFO", f"[findvr] no result for '{q}'")
                                    threading.Thread(target=_findvr, daemon=True).start()
                            elif cmd == 'skipvr':
                                if is_owner or user == ADMIN_USERNAME.lower():
                                    def _skipvr():
                                        video_skip_track()
                                        if video_requests:
                                            dropped = video_requests.pop(0)
                                            console_log("INFO", f"[skipvr] dropped next queued request: {dropped.get('raw')}")
                                    threading.Thread(target=_skipvr, daemon=True).start()
                            elif cmd == 'clearvr':
                                if is_owner or user == ADMIN_USERNAME.lower():
                                    video_requests.clear()
                                    post_system_message("[clearvr] pending video request queue cleared.")
                            # ── Voice ──
                            elif cmd == 'tts':
                                speak_text(args)
                            elif cmd == 'ttsloop':
                                if args.strip(): tts_loop(args)
                            elif cmd == 'ttsxp':
                                speak_text(args)  # XP/SAM-style voice depends on installed SAPI voices
                            elif cmd == 'ttsxploop':
                                if args.strip(): tts_loop(args, xp_style=True)
                            elif cmd == 'gtts':
                                if args.strip():
                                    threading.Thread(target=gtts_speak, args=(args,), daemon=True).start()
                            elif cmd == 'beep':
                                threading.Thread(target=beep, daemon=True).start()
                            # ── Extra VM / system control ──
                            elif cmd == 'shutdown':
                                threading.Thread(target=vm_shutdown_soft, daemon=True).start()
                            elif cmd in ('killvm', 'forceshutdown'):
                                threading.Thread(target=vm_shutdown_hard_kill, daemon=True).start()
                            elif cmd == 'forcefixvm':
                                threading.Thread(target=watchdog_restart, daemon=True).start()
                            elif cmd == 'pausevm':
                                threading.Thread(target=vm_pause, daemon=True).start()
                            elif cmd == 'resumevm':
                                threading.Thread(target=vm_unpause, daemon=True).start()
                            elif cmd == 'vmsavestate':
                                threading.Thread(target=vm_save_state, daemon=True).start()
                            elif cmd == 'vmstatus':
                                post_system_message(cmd_status_text())
                            elif cmd in ('makesnapshot', 'snapshot'):
                                threading.Thread(target=vm_make_snapshot, args=(args,), daemon=True).start()
                            elif cmd == 'enableinternet':
                                if is_owner or user == ADMIN_USERNAME.lower():
                                    ok, msg = vm_set_internet_live(True)
                                    post_system_message(f"[enableinternet] {msg}")
                            elif cmd == 'disableinternet':
                                if is_owner or user == ADMIN_USERNAME.lower():
                                    ok, msg = vm_set_internet_live(False)
                                    post_system_message(f"[disableinternet] {msg}")
                            # ── Fun / chaos ──
                            elif cmd == 'roll':
                                post_system_message(f"[roll] {user} rolled {random.randint(1, 100)}")
                            elif cmd == 'coinflip':
                                post_system_message(f"[coinflip] {random.choice(['heads', 'tails'])}")
                            elif cmd == 'shake':
                                mouse_shake()
                            elif cmd == 'jiggle':
                                mouse_jiggle()
                            elif cmd == 'circle':
                                mouse_circle()
                            elif cmd == 'spiral':
                                mouse_spiral()
                            elif cmd == 'msgbox':
                                if args.strip(): msgbox_in_vm(args)
                            elif cmd == 'spam':
                                sp = args.rsplit(maxsplit=1)
                                if len(sp) == 2 and sp[1].isdigit():
                                    spam_text(sp[0], sp[1])
                                elif args.strip():
                                    spam_text(args, 5)
                            elif cmd == 'countdown':
                                countdown(int(args) if args.strip().isdigit() else 5)
                            elif cmd == 'matrix':
                                matrix_effect()
                            elif cmd == 'colorscheme':
                                randomize_colorscheme()
                            elif cmd == 'rainbow':
                                rainbow_effect()
                            elif cmd == 'notepadflood':
                                notepad_flood(int(args) if args.strip().isdigit() else 6)
                            elif cmd == 'exeflood':
                                exe_flood(int(args) if args.strip().isdigit() else 6)
                            elif cmd == 'txtflood':
                                txt_flood(int(args) if args.strip().isdigit() else 20)
                            elif cmd == 'deskflood':
                                desktop_flood()
                            # ── Info / chat ──
                            elif cmd == 'ping':
                                post_system_message("pong!")
                            elif cmd == 'uptime':
                                post_system_message(cmd_uptime_text())
                            elif cmd == 'help':
                                post_system_message(COMMANDS_HELP.strip()[:400])
                            elif cmd == 'stats':
                                post_system_message(cmd_stats_text())
                            elif cmd == 'history':
                                post_system_message(cmd_history_text())
                            elif cmd == 'leaderboard':
                                post_system_message(cmd_leaderboard_text())
                            elif cmd == 'queue':
                                post_system_message(cmd_queue_text())
                            elif cmd == 'status':
                                post_system_message(cmd_status_text())
                            # ── Admin only ──
                            elif cmd in ('pausechat', 'disablechat'):
                                if is_owner or user == ADMIN_USERNAME.lower():
                                    CHAT_COMMANDS_PAUSED = True
                                    post_system_message("[pausechat] chat commands paused.")
                            elif cmd == 'enablechat':
                                if is_owner or user == ADMIN_USERNAME.lower():
                                    CHAT_COMMANDS_PAUSED = False
                                    post_system_message("[enablechat] chat commands resumed.")
                            elif cmd == 'enablecv':
                                if is_owner or user == ADMIN_USERNAME.lower():
                                    post_system_message("[enablecv] no OCR/computer-vision module is present in this build.")
                            elif cmd == 'votestop':
                                if is_owner or user == ADMIN_USERNAME.lower():
                                    vote_restart.clear(); vote_revert.clear(); ban_votes.clear()
                                    post_system_message("[votestop] active vote(s) cancelled.")
                            elif cmd == 'clear':
                                if is_owner or user == ADMIN_USERNAME.lower():
                                    overlay_data["chat"].clear()
                                    seen_message_ids.clear()
                            elif cmd == 'efail':
                                if is_owner or user == ADMIN_USERNAME.lower():
                                    log_error("Cmd/efail", "manual test error", "triggered via !efail")
                                    update_status("ERROR (test)")
                            elif cmd == 'poweroff':
                                if is_owner or user == ADMIN_USERNAME.lower():
                                    post_system_message("[poweroff] shutting down HOST machine...")
                                    threading.Thread(
                                        target=lambda: subprocess.run(["shutdown", "/s", "/t", "5"]),
                                        daemon=True).start()
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
                                    continue
                                # Mod/owner bypass: skip vote, execute immediately
                                if is_mod:
                                    print(f"[Vote] Restart bypassed by {'owner' if is_owner else 'mod'}: {user}")
                                    speak_text("Restarting Virtual Machine...")
                                    vote_restart.clear(); restart_start_time=None; active_users.clear()
                                    restart_in_progress = True
                                    update_status("Restarting...")
                                    update_votes_json("restartvm", required_votes, required_votes, 0)
                                    try:
                                        ok, err = retry_vbox(
                                            lambda: _checked(vm_reset(VM_NAME, current_vm_backend)),
                                            attempts=3, delay=3, source="Vote/restart-owner"
                                        )
                                        if ok:
                                            restart_cooldown_until = time.time() + PERMISSIONS_CONFIG.get("action_cooldown", 60)
                                            update_status("Running"); play_success_sound()
                                            play_event_sound("restart_sound")
                                            _append_event("RESTART", user, "owner bypass")
                                            notify("VM Restarted", "Restart triggered by owner.")
                                        else:
                                            update_status("Restart failed")
                                            log_error("Vote/restart", f"Owner restart failed after retries", str(err))
                                            notify("Restart Failed", str(err), timeout=6)
                                    finally:
                                        update_votes_json("restartvm", 0, required_votes, 0)
                                        restart_in_progress = False
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
                                    update_status("Restarting...")
                                    try:
                                        ok, err = retry_vbox(
                                            lambda: _checked(vm_reset(VM_NAME, current_vm_backend)),
                                            attempts=3, delay=3, source="Vote/restart-chat"
                                        )
                                        if ok:
                                            restart_cooldown_until = time.time() + PERMISSIONS_CONFIG.get("action_cooldown", 60)
                                            update_status("Running"); play_success_sound()
                                            play_event_sound("restart_sound")
                                            _append_event("RESTART", "vote", f"chat vote passed ({current} votes)")
                                            notify("VM Restarted", "Restart vote passed by chat.")
                                            obs_trigger("restart")
                                            _stats["restarts"] += 1
                                        else:
                                            update_status("Restart failed")
                                            log_error("Vote/restart", "Chat restart failed after retries", str(err))
                                            notify("Restart Failed", str(err), timeout=6)
                                    finally:
                                        update_votes_json("restartvm", 0, required_votes, 0)
                                        restart_in_progress = False

                            elif cmd == 'revert':
                                if revert_in_progress: continue
                                if current_time < revert_cooldown_until:
                                    remaining_cd = int(revert_cooldown_until - current_time)
                                    print(f"[Vote] Revert on cooldown ({remaining_cd}s left)")
                                    _append_event("COOLDOWN", user, f"revert blocked — {remaining_cd}s left")
                                    continue
                                # Mod/owner bypass: skip vote, execute immediately
                                if is_mod:
                                    print(f"[Vote] Revert bypassed by {'owner' if is_owner else 'mod'}: {user}")
                                    speak_text("Reverting Virtual Machine...")
                                    vote_revert.clear(); revert_start_time=None; active_users.clear()
                                    revert_in_progress = True
                                    update_status("Reverting...")
                                    update_votes_json("revert", required_votes, required_votes, 0)
                                    try:
                                        ok, err = retry_vbox(
                                            lambda: _checked(vm_stop(VM_NAME, current_vm_backend, hard=True)),
                                            attempts=3, delay=3, source="Vote/revert-owner/poweroff"
                                        )
                                        time.sleep(3)
                                        ok2, err2 = retry_vbox(
                                            lambda: _checked(vm_revert_to_current(VM_NAME, current_vm_backend)),
                                            attempts=3, delay=3, source="Vote/revert-owner/snapshot"
                                        )
                                        time.sleep(3)
                                        ok3, err3 = retry_vbox(
                                            lambda: _checked(vm_start(VM_NAME, current_vm_backend, gui=True)),
                                            attempts=3, delay=4, source="Vote/revert-owner/startvm"
                                        )
                                        if ok2 and ok3:
                                            revert_cooldown_until = time.time() + PERMISSIONS_CONFIG.get("action_cooldown", 60)
                                            update_status("Running"); play_success_sound()
                                            play_event_sound("revert_sound")
                                            _append_event("REVERT", user, "owner bypass")
                                            notify("VM Reverted", "Snapshot restored by owner.")
                                        else:
                                            failed = "snapshot" if not ok2 else "startvm"
                                            update_status("Revert failed")
                                            log_error("Vote/revert", f"Owner revert failed at {failed}", str(err2 or err3))
                                            notify("Revert Failed", f"Failed at {failed} step.", timeout=6)
                                    finally:
                                        update_votes_json("revert", 0, required_votes, 0)
                                        revert_in_progress = False
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
                                    update_status("Reverting...")
                                    obs_trigger("revert_start")
                                    try:
                                        ok, err = retry_vbox(
                                            lambda: _checked(vm_stop(VM_NAME, current_vm_backend, hard=True)),
                                            attempts=3, delay=3, source="Vote/revert-chat/poweroff"
                                        )
                                        time.sleep(3)
                                        ok2, err2 = retry_vbox(
                                            lambda: _checked(vm_revert_to_current(VM_NAME, current_vm_backend)),
                                            attempts=3, delay=3, source="Vote/revert-chat/snapshot"
                                        )
                                        time.sleep(3)
                                        ok3, err3 = retry_vbox(
                                            lambda: _checked(vm_start(VM_NAME, current_vm_backend, gui=True)),
                                            attempts=3, delay=4, source="Vote/revert-chat/startvm"
                                        )
                                        if ok2 and ok3:
                                            revert_cooldown_until = time.time() + PERMISSIONS_CONFIG.get("action_cooldown", 60)
                                            update_status("Running"); play_success_sound()
                                            play_event_sound("revert_sound")
                                            _append_event("REVERT", "vote", f"chat vote passed ({current} votes)")
                                            notify("VM Reverted", "Snapshot restored by chat vote.")
                                            obs_trigger("revert_done")
                                            _stats["reverts"] += 1
                                        else:
                                            failed = "snapshot" if not ok2 else "startvm"
                                            update_status("Revert failed")
                                            log_error("Vote/revert", f"Chat revert failed at {failed}", str(err2 or err3))
                                            notify("Revert Failed", f"Failed at {failed} step.", timeout=6)
                                    finally:
                                        update_votes_json("revert", 0, required_votes, 0)
                                        revert_in_progress = False

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



class YouTubeChatBot:
    def __init__(self):
        self.video_id = VIDEO_ID
        self.chat = None
        self._reconnect_failures = 0
        self._loop_heartbeat = time.time()
        self.reconnect()
        update_overlay()
        update_ban_vote_display(None, 0, get_vote_threshold("ban_votes", 3))
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
        threading.Thread(target=fetch_youtube_stats, daemon=True, name="youtube_stats").start()

    def reconnect(self):
        if self.chat:
            try: self.chat.terminate()
            except: pass
        try:
            self.chat = pytchat.create(video_id=self.video_id)
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
        global restart_start_time, revert_start_time, revert_in_progress, restart_in_progress, restart_cooldown_until, revert_cooldown_until, os_vote_start_time, CHAT_COMMANDS_PAUSED
        if CHAT_COMMANDS_PAUSED:
            print("[pausechat] chat was left paused from a previous session -- auto-resuming on bot start.")
        CHAT_COMMANDS_PAUSED = False
        last_reconnect   = time.time()
        RECONNECT_INTERVAL = 150
        print("[Bot] Waiting for chat messages...")

        # ── Hang watchdog ──
        # self.chat.get().sync_items() below is a BLOCKING pytchat call with no timeout.
        # If it ever hangs internally (bad network moment, stale connection) the whole
        # loop freezes silently -- no exception, no periodic reconnect (that check never
        # gets re-reached since we never return from the blocking call), nothing. This
        # watchdog runs on its own thread and force-terminates the stuck chat object if
        # the main loop hasn't cycled back to its top in way longer than it should have,
        # which unblocks the hung call so the normal reconnect logic can take back over.
        HANG_THRESHOLD = 240  # comfortably longer than RECONNECT_INTERVAL so it won't false-trigger
        def _hang_watchdog():
            while not bot_stop_event.is_set():
                if bot_stop_event.wait(30):
                    break
                stuck_for = time.time() - self._loop_heartbeat
                if stuck_for > HANG_THRESHOLD:
                    print(f"[Bot] Watchdog: chat loop has not cycled in {stuck_for:.0f}s -- "
                          f"forcing the stuck connection closed to unstick it.")
                    _append_event("HANG_WATCHDOG", "system", f"stuck for {stuck_for:.0f}s, forcing reconnect")
                    try:
                        if self.chat:
                            self.chat.terminate()
                    except Exception:
                        pass
                    self._loop_heartbeat = time.time()  # avoid re-triggering every 30s while it recovers
        threading.Thread(target=_hang_watchdog, daemon=True, name="chat_hang_watchdog").start()

        while not bot_stop_event.is_set():
            self._loop_heartbeat = time.time()
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
                for c in self.chat.get().sync_items():
                    if bot_stop_event.is_set():
                        break
                    msg      = c.message.strip()
                    user     = normalize_username(c.author.name)
                    is_owner = getattr(c.author, 'isChatOwner', False)
                    is_mod   = is_owner or getattr(c.author, 'isChatModerator', False) or user == ADMIN_USERNAME.lower()
                    update_overlay(author=user, message=msg, msg_id=c.id)
                    if user in banned_users:
                        if time.time() < banned_users[user]: continue
                        else: del banned_users[user]
                    # Whitelist check: if enabled and user not in list (and not owner), skip
                    if whitelist_users and not is_owner and user not in whitelist_users:
                        continue
                    active_users.add(c.author.name.strip())
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
                        # Normalize alternate chain separators to '!' before splitting into
                        # chained commands -- supports !cmd1!cmd2 (original), !cmd1+!cmd2,
                        # and !cmd1 | cmd2 (or !cmd1 | !cmd2) as equivalent ways to run
                        # multiple commands from one message.
                        normalized_msg = re.sub(r'\+\s*!', '!', msg)
                        if '|' in normalized_msg:
                            pipe_parts = [p.strip() for p in normalized_msg.split('|')]
                            normalized_msg = ' '.join(
                                p if (not p or p.startswith('!')) else ('!' + p)
                                for p in pipe_parts
                            )
                        chain_parts = [p.strip() for p in normalized_msg.split('!') if p.strip()]
                        for part in chain_parts:
                            sub_parts = part.split(maxsplit=1)
                            cmd  = sub_parts[0].lower()
                            args = sub_parts[1] if len(sub_parts) > 1 else ""

                            # ── !pausechat gate: block everything except re-enabling it ──
                            if CHAT_COMMANDS_PAUSED and cmd not in ('enablechat',) and not is_mod:
                                print(f"[pausechat] blocked '!{cmd}' from {user} (chat commands are paused -- "
                                      f"an admin needs to type !enablechat)")
                                continue

                            # ── Global per-user command cooldown (Permissions tab) ──
                            # Applies to every command uniformly, for non-mods only.
                            global_cd = PERMISSIONS_CONFIG.get("global_command_cooldown", 60)
                            if global_cd > 0 and not is_mod:
                                last_cmd_time = _global_command_cooldowns.get(user, 0)
                                elapsed = time.time() - last_cmd_time
                                if elapsed < global_cd:
                                    remaining = int(global_cd - elapsed)
                                    print(f"[cooldown] blocked '!{cmd}' from {user} ({remaining}s left on their command cooldown)")
                                    continue
                                _global_command_cooldowns[user] = time.time()
                                if len(_global_command_cooldowns) > 5000:
                                    cutoff = time.time() - global_cd
                                    for u in [u for u, t in _global_command_cooldowns.items() if t < cutoff]:
                                        del _global_command_cooldowns[u]

                            _record_command(cmd, user)

                            # ── Custom command check (first priority) ──
                            trigger = "!" + cmd
                            if trigger in custom_commands:
                                threading.Thread(
                                    target=execute_custom_command,
                                    args=(trigger,), daemon=True
                                ).start()
                                continue

                            # ── Per-OS Host Switching commands (e.g. !winwin11, !macmonterey) ──
                            if try_handle_host_switch_command(cmd):
                                continue

                            # ── OS voting commands (e.g. !win7, !win10) ──
                            if OS_VOTING_ENABLED:
                                os_trigger_map = get_os_trigger_map()
                                if cmd in os_trigger_map:
                                    if os_switch_in_progress:
                                        continue
                                    target_entry = os_trigger_map[cmd]
                                    # Mod/owner bypass: switch immediately, no vote needed
                                    if is_mod:
                                        print(f"[OSVoting] Switch bypassed by {'owner' if is_owner else 'mod'}: {user} → {target_entry['name']}")
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
                                    os_vote_required_now = get_vote_threshold("os_vote_required", OS_VOTE_REQUIRED)
                                    print(f"[OSVoting] Vote for '{target_entry['name']}': {len(voters)}/{os_vote_required_now}")
                                    if len(voters) >= os_vote_required_now:
                                        print(f"[OSVoting] Threshold reached → switching to {target_entry['name']}")
                                        threading.Thread(target=switch_os, args=(target_entry,), daemon=True).start()
                                    continue

                            # ── Built-in commands ──
                            if cmd in ['wait', 'pause', 'delay']:
                                try:
                                    delay = float(args)
                                    delay = max(0, min(delay, 5.0))
                                    time.sleep(delay)
                                except: pass
                                continue

                            if cmd in ['type', 'text', 'say', 't', 's']:
                                send_keyboard(args)
                            elif cmd in ['typeenter', 'send', 'sendline']:
                                send_keyboard(args)
                                send_special_enter()
                            elif cmd == 'enter':
                                send_special_enter()
                            elif cmd in ['fullscreen', 'fs']:
                                print("[Bot] Fullscreen hint (manual)")
                            elif cmd in ['move','mouse','mv','m','abs','cursor','moveabs',
                                         'drag','dragrel','d','dragabs','drag_absolute',
                                         'click','lclick','lc','dclick','tripleclick',
                                         'rclick','rightclick','rc',
                                         'mclick','middleclick','scroll','wheel',
                                         'scrollup','scrolldown']:
                                handle_mouse(cmd, args)
                            elif cmd in ['startvm','modlaunch','launchvm','start_mc','startmc']:
                                if time.time() - self.last_start_time > COOLDOWN_START:
                                    start_vm()
                                    self.last_start_time = time.time()
                                else:
                                    print("[Bot] !startvm cooldown active")
                            elif cmd in ['restore','refresh','restore_window','focus','front','bringtofront']:
                                restore_window()
                            elif cmd in ['key', 'press', 'k']:
                                k = args.lower().strip()
                                if k in SCANCODES:
                                    send_scancode(SCANCODES[k][0])
                                    time.sleep(0.01)
                                    send_scancode(SCANCODES[k][1])
                                else:
                                    send_keyboard(k)
                            elif cmd in ['keydown', 'hold', 'kd']:
                                k = args.lower().strip()
                                if k in SCANCODES: send_scancode(SCANCODES[k][0])
                            elif cmd in ['keyup', 'release', 'ku']:
                                k = args.lower().strip()
                                if k in SCANCODES: send_scancode(SCANCODES[k][1])
                            elif cmd in ['combo','chord','multi','c']:
                                keys = parse_combo_keys(args)
                                if keys: send_combo(keys)
                                else: send_keyboard(args)
                            elif cmd == 'winkey':
                                k = args.lower().strip()
                                if k: send_combo(['win'] + parse_combo_keys(k))
                            elif cmd == 'run':
                                if args.strip():
                                    run_win_r(args.strip())
                                else:
                                    send_combo(['win','r'])
                            elif cmd == 'cmd':
                                run_admin_cmd(args)
                            elif cmd == 'dir':
                                open_folder(args)
                            elif cmd == 'openfile':
                                open_file(args)
                            elif cmd == 'taskkill':
                                if args.strip(): taskkill_process(args.strip())
                            # ── Music / Video / Soundboard commands (ported from the VMware build) ──
                            elif cmd in ('play', 'music', 'songrequest', 'sr'):
                                if args.strip():
                                    threading.Thread(target=queue_song_request, args=(args, user), daemon=True).start()
                                else:
                                    threading.Thread(target=start_music_player, daemon=True).start()
                            elif cmd in ('musicskip', 'skipsong', 'skipmusic'):
                                threading.Thread(target=music_skip_track, daemon=True).start()
                            elif cmd in ('stopmusic', 'musicstop'):
                                threading.Thread(target=music_stop_current, daemon=True).start()
                            elif cmd in ('musicpause', 'pausemusic'):
                                threading.Thread(target=music_pause_toggle, daemon=True).start()
                            elif cmd in ('musicvolume', 'musicvol'):
                                try: music_set_volume(float(args))
                                except Exception: pass
                            elif cmd in ('video', 'videorequest', 'vr'):
                                if args.strip():
                                    threading.Thread(target=queue_video_request, args=(args, user), daemon=True).start()
                                else:
                                    threading.Thread(target=start_video_player, daemon=True).start()
                            elif cmd in ('videoskip', 'skipvideo', 'vskip'):
                                threading.Thread(target=video_skip_track, daemon=True).start()
                            elif cmd in ('stopvideo', 'videostop'):
                                threading.Thread(target=video_stop_current, daemon=True).start()
                            elif cmd in ('videopause', 'pausevideo'):
                                threading.Thread(target=video_pause_toggle, daemon=True).start()
                            elif cmd in ('videovolume', 'videovol'):
                                try: video_set_volume(float(args))
                                except Exception: pass
                            elif cmd in ('sb', 'soundboard'):
                                if args.strip():
                                    threading.Thread(target=soundboard_web_search_and_play, args=(args, user), daemon=True).start()
                            elif cmd == 'sbid':
                                if args.strip():
                                    threading.Thread(target=soundboard_web_id_and_play, args=(args, user), daemon=True).start()
                            elif cmd in ('sbstop', 'soundboardstop'):
                                threading.Thread(target=soundboard_stop_all, daemon=True).start()
                            elif cmd in ('sbvolume', 'sbvol'):
                                try: soundboard_set_volume(float(args))
                                except Exception: pass
                            elif cmd == 'srqueue':
                                threading.Thread(target=post_queue_to_overlay,
                                                  args=("Song Queue", music_song_requests, music_queue),
                                                  daemon=True).start()
                            elif cmd == 'vrqueue':
                                threading.Thread(target=post_queue_to_overlay,
                                                  args=("Video Queue", video_requests, video_queue),
                                                  daemon=True).start()
                            elif cmd in ('findsr',):
                                if args.strip():
                                    def _findsr(q=args, u=user):
                                        vid = find_youtube_video_id(q)
                                        if vid:
                                            queue_song_request(vid, u)
                                        else:
                                            console_log("INFO", f"[findsr] no result for '{q}'")
                                    threading.Thread(target=_findsr, daemon=True).start()
                            elif cmd == 'skipsr':
                                if is_mod:
                                    def _skipsr():
                                        music_skip_track()
                                        if music_song_requests:
                                            dropped = music_song_requests.pop(0)
                                            post_system_message(f"[skipsr] skipped -- also dropped next queued request: {dropped.get('raw')}")
                                        else:
                                            post_system_message("[skipsr] skipped (no other requests queued).")
                                    threading.Thread(target=_skipsr, daemon=True).start()
                                else:
                                    post_system_message(f"[skipsr] {user}: moderator only.")
                            elif cmd == 'clearsr':
                                if is_mod:
                                    music_song_requests.clear()
                                    post_system_message("[clearsr] pending song request queue cleared.")
                                else:
                                    post_system_message(f"[clearsr] {user}: moderator only.")
                            elif cmd in ('findvr',):
                                if args.strip():
                                    def _findvr(q=args, u=user):
                                        vid = find_youtube_video_id(q)
                                        if vid:
                                            queue_video_request(vid, u)
                                        else:
                                            console_log("INFO", f"[findvr] no result for '{q}'")
                                    threading.Thread(target=_findvr, daemon=True).start()
                            elif cmd == 'skipvr':
                                if is_mod:
                                    def _skipvr():
                                        video_skip_track()
                                        if video_requests:
                                            dropped = video_requests.pop(0)
                                            post_system_message(f"[skipvr] skipped -- also dropped next queued request: {dropped.get('raw')}")
                                        else:
                                            post_system_message("[skipvr] skipped (no other requests queued).")
                                    threading.Thread(target=_skipvr, daemon=True).start()
                                else:
                                    post_system_message(f"[skipvr] {user}: moderator only.")
                            elif cmd == 'clearvr':
                                if is_mod:
                                    video_requests.clear()
                                    post_system_message("[clearvr] pending video request queue cleared.")
                                else:
                                    post_system_message(f"[clearvr] {user}: moderator only.")
                            # ── Voice ──
                            elif cmd == 'tts':
                                speak_text(args)
                            elif cmd == 'ttsloop':
                                if args.strip(): tts_loop(args)
                            elif cmd == 'ttsxp':
                                speak_text(args)
                            elif cmd == 'ttsxploop':
                                if args.strip(): tts_loop(args, xp_style=True)
                            elif cmd == 'gtts':
                                if args.strip():
                                    threading.Thread(target=gtts_speak, args=(args,), daemon=True).start()
                            elif cmd == 'beep':
                                threading.Thread(target=beep, daemon=True).start()
                            # ── Extra VM / system control ──
                            elif cmd == 'shutdown':
                                threading.Thread(target=vm_shutdown_soft, daemon=True).start()
                            elif cmd in ('killvm', 'forceshutdown'):
                                threading.Thread(target=vm_shutdown_hard_kill, daemon=True).start()
                            elif cmd == 'forcefixvm':
                                threading.Thread(target=watchdog_restart, daemon=True).start()
                            elif cmd == 'pausevm':
                                threading.Thread(target=vm_pause, daemon=True).start()
                            elif cmd == 'resumevm':
                                threading.Thread(target=vm_unpause, daemon=True).start()
                            elif cmd == 'vmsavestate':
                                threading.Thread(target=vm_save_state, daemon=True).start()
                            elif cmd == 'vmstatus':
                                post_system_message(cmd_status_text())
                            elif cmd in ('makesnapshot', 'snapshot'):
                                threading.Thread(target=vm_make_snapshot, args=(args,), daemon=True).start()
                            elif cmd == 'enableinternet':
                                if is_mod:
                                    ok, msg = vm_set_internet_live(True)
                                    post_system_message(f"[enableinternet] {msg}")
                                else:
                                    post_system_message(f"[enableinternet] {user}: moderator only.")
                            elif cmd == 'disableinternet':
                                if is_mod:
                                    ok, msg = vm_set_internet_live(False)
                                    post_system_message(f"[disableinternet] {msg}")
                                else:
                                    post_system_message(f"[disableinternet] {user}: moderator only.")
                            # ── Fun / chaos ──
                            elif cmd == 'roll':
                                post_system_message(f"[roll] {user} rolled {random.randint(1, 100)}")
                            elif cmd == 'coinflip':
                                post_system_message(f"[coinflip] {random.choice(['heads', 'tails'])}")
                            elif cmd == 'shake':
                                mouse_shake()
                            elif cmd == 'jiggle':
                                mouse_jiggle()
                            elif cmd == 'circle':
                                mouse_circle()
                            elif cmd == 'spiral':
                                mouse_spiral()
                            elif cmd == 'msgbox':
                                if args.strip(): msgbox_in_vm(args)
                            elif cmd == 'spam':
                                sp = args.rsplit(maxsplit=1)
                                if len(sp) == 2 and sp[1].isdigit():
                                    spam_text(sp[0], sp[1])
                                elif args.strip():
                                    spam_text(args, 5)
                            elif cmd == 'countdown':
                                countdown(int(args) if args.strip().isdigit() else 5)
                            elif cmd == 'matrix':
                                matrix_effect()
                            elif cmd == 'colorscheme':
                                randomize_colorscheme()
                            elif cmd == 'rainbow':
                                rainbow_effect()
                            elif cmd == 'notepadflood':
                                notepad_flood(int(args) if args.strip().isdigit() else 6)
                            elif cmd == 'exeflood':
                                exe_flood(int(args) if args.strip().isdigit() else 6)
                            elif cmd == 'txtflood':
                                txt_flood(int(args) if args.strip().isdigit() else 20)
                            elif cmd == 'deskflood':
                                desktop_flood()
                            # ── Info / chat ──
                            elif cmd == 'ping':
                                post_system_message("pong!")
                            elif cmd == 'uptime':
                                post_system_message(cmd_uptime_text())
                            elif cmd == 'help':
                                post_system_message(COMMANDS_HELP.strip()[:400])
                            elif cmd == 'stats':
                                post_system_message(cmd_stats_text())
                            elif cmd == 'history':
                                post_system_message(cmd_history_text())
                            elif cmd == 'leaderboard':
                                post_system_message(cmd_leaderboard_text())
                            elif cmd == 'queue':
                                post_system_message(cmd_queue_text())
                            elif cmd == 'status':
                                post_system_message(cmd_status_text())
                            # ── Admin only ──
                            elif cmd in ('pausechat', 'disablechat'):
                                if is_mod:
                                    CHAT_COMMANDS_PAUSED = True
                                    post_system_message("[pausechat] chat commands paused.")
                                else:
                                    post_system_message(f"[pausechat] {user}: moderator only.")
                            elif cmd == 'enablechat':
                                if is_mod:
                                    CHAT_COMMANDS_PAUSED = False
                                    post_system_message("[enablechat] chat commands resumed.")
                                else:
                                    post_system_message(f"[enablechat] {user}: moderator only.")
                            elif cmd == 'enablecv':
                                if is_mod:
                                    post_system_message("[enablecv] no OCR/computer-vision module is present in this build.")
                                else:
                                    post_system_message(f"[enablecv] {user}: moderator only.")
                            elif cmd == 'votestop':
                                if is_mod:
                                    vote_restart.clear(); vote_revert.clear(); ban_votes.clear()
                                    post_system_message("[votestop] active vote(s) cancelled.")
                                else:
                                    post_system_message(f"[votestop] {user}: moderator only.")
                            elif cmd == 'clear':
                                if is_mod:
                                    overlay_data["chat"].clear()
                                    seen_message_ids.clear()
                                else:
                                    post_system_message(f"[clear] {user}: moderator only.")
                            elif cmd == 'efail':
                                if is_mod:
                                    log_error("Cmd/efail", "manual test error", "triggered via !efail")
                                    update_status("ERROR (test)")
                                else:
                                    post_system_message(f"[efail] {user}: moderator only.")
                            elif cmd == 'poweroff':
                                if is_mod:
                                    post_system_message("[poweroff] shutting down HOST machine...")
                                    threading.Thread(
                                        target=lambda: subprocess.run(["shutdown", "/s", "/t", "5"]),
                                        daemon=True).start()
                                else:
                                    post_system_message(f"[poweroff] {user}: moderator only.")
                            elif cmd == 'votehelp':
                                update_status("Commands in description!")
                            elif cmd == 'clearvotes':
                                if is_mod:
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
                            # (or from get_vote_threshold()'s percent-of-viewers calc if that's enabled).
                            # NOTE: each vote type computes its OWN threshold below, right before use --
                            # previously this was computed once here from restart_votes and silently
                            # reused for revert too, so revert votes were being compared against the
                            # restart threshold instead of its own revert_votes setting.
                            current_time   = time.time()

                            if cmd in ['restart','restartvm']:
                                required_votes = get_vote_threshold("restart_votes", 2)
                                if user in vip_users:
                                    required_votes = min(required_votes,
                                        vip_users[user].get("votes_needed", required_votes))
                                if restart_in_progress: continue
                                if current_time < restart_cooldown_until:
                                    remaining_cd = int(restart_cooldown_until - current_time)
                                    print(f"[Vote] Restart on cooldown ({remaining_cd}s left)")
                                    _append_event("COOLDOWN", user, f"restart blocked — {remaining_cd}s left")
                                    continue
                                # Mod/owner bypass: skip vote, execute immediately
                                if is_mod:
                                    print(f"[Vote] Restart bypassed by {'owner' if is_owner else 'mod'}: {user}")
                                    speak_text("Restarting Virtual Machine...")
                                    vote_restart.clear(); restart_start_time=None; active_users.clear()
                                    restart_in_progress = True
                                    update_status("Restarting...")
                                    update_votes_json("restartvm", required_votes, required_votes, 0)
                                    try:
                                        ok, err = retry_vbox(
                                            lambda: _checked(vm_reset(VM_NAME, current_vm_backend)),
                                            attempts=3, delay=3, source="Vote/restart-owner"
                                        )
                                        if ok:
                                            restart_cooldown_until = time.time() + PERMISSIONS_CONFIG.get("action_cooldown", 60)
                                            update_status("Running"); play_success_sound()
                                            play_event_sound("restart_sound")
                                            _append_event("RESTART", user, "owner bypass")
                                            notify("VM Restarted", "Restart triggered by owner.")
                                            obs_trigger("restart")
                                            obs_trigger("restart_done")
                                            apply_current_os_scene()
                                        else:
                                            update_status("Restart failed")
                                            log_error("Vote/restart", f"Owner restart failed after retries", str(err))
                                            notify("Restart Failed", str(err), timeout=6)
                                    finally:
                                        update_votes_json("restartvm", 0, required_votes, 0)
                                        restart_in_progress = False
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
                                    update_status("Restarting...")
                                    try:
                                        ok, err = retry_vbox(
                                            lambda: _checked(vm_reset(VM_NAME, current_vm_backend)),
                                            attempts=3, delay=3, source="Vote/restart-chat"
                                        )
                                        if ok:
                                            restart_cooldown_until = time.time() + PERMISSIONS_CONFIG.get("action_cooldown", 60)
                                            update_status("Running"); play_success_sound()
                                            play_event_sound("restart_sound")
                                            _append_event("RESTART", "vote", f"chat vote passed ({current} votes)")
                                            notify("VM Restarted", "Restart vote passed by chat.")
                                            obs_trigger("restart")
                                            obs_trigger("restart_done")
                                            apply_current_os_scene()
                                            _stats["restarts"] += 1
                                        else:
                                            update_status("Restart failed")
                                            log_error("Vote/restart", "Chat restart failed after retries", str(err))
                                            notify("Restart Failed", str(err), timeout=6)
                                    finally:
                                        update_votes_json("restartvm", 0, required_votes, 0)
                                        restart_in_progress = False

                            elif cmd == 'revert':
                                required_votes = get_vote_threshold("revert_votes", 2)
                                if user in vip_users:
                                    required_votes = min(required_votes,
                                        vip_users[user].get("votes_needed", required_votes))
                                if revert_in_progress: continue
                                if current_time < revert_cooldown_until:
                                    remaining_cd = int(revert_cooldown_until - current_time)
                                    print(f"[Vote] Revert on cooldown ({remaining_cd}s left)")
                                    _append_event("COOLDOWN", user, f"revert blocked — {remaining_cd}s left")
                                    continue
                                # Mod/owner bypass: skip vote, execute immediately
                                if is_mod:
                                    print(f"[Vote] Revert bypassed by {'owner' if is_owner else 'mod'}: {user}")
                                    speak_text("Reverting Virtual Machine...")
                                    vote_revert.clear(); revert_start_time=None; active_users.clear()
                                    revert_in_progress = True
                                    update_status("Reverting...")
                                    update_votes_json("revert", required_votes, required_votes, 0)
                                    try:
                                        ok, err = retry_vbox(
                                            lambda: _checked(vm_stop(VM_NAME, current_vm_backend, hard=True)),
                                            attempts=3, delay=3, source="Vote/revert-owner/poweroff"
                                        )
                                        time.sleep(3)
                                        ok2, err2 = retry_vbox(
                                            lambda: _checked(vm_revert_to_current(VM_NAME, current_vm_backend)),
                                            attempts=3, delay=3, source="Vote/revert-owner/snapshot"
                                        )
                                        time.sleep(3)
                                        ok3, err3 = retry_vbox(
                                            lambda: _checked(vm_start(VM_NAME, current_vm_backend, gui=True)),
                                            attempts=3, delay=4, source="Vote/revert-owner/startvm"
                                        )
                                        if ok2 and ok3:
                                            revert_cooldown_until = time.time() + PERMISSIONS_CONFIG.get("action_cooldown", 60)
                                            update_status("Running"); play_success_sound()
                                            play_event_sound("revert_sound")
                                            _append_event("REVERT", user, "owner bypass")
                                            notify("VM Reverted", "Snapshot restored by owner.")
                                            obs_trigger("revert_done")
                                            apply_current_os_scene()
                                        else:
                                            failed = "snapshot" if not ok2 else "startvm"
                                            update_status("Revert failed")
                                            log_error("Vote/revert", f"Owner revert failed at {failed}", str(err2 or err3))
                                            notify("Revert Failed", f"Failed at {failed} step.", timeout=6)
                                    finally:
                                        update_votes_json("revert", 0, required_votes, 0)
                                        revert_in_progress = False
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
                                    update_status("Reverting...")
                                    obs_trigger("revert_start")
                                    try:
                                        ok, err = retry_vbox(
                                            lambda: _checked(vm_stop(VM_NAME, current_vm_backend, hard=True)),
                                            attempts=3, delay=3, source="Vote/revert-chat/poweroff"
                                        )
                                        time.sleep(3)
                                        ok2, err2 = retry_vbox(
                                            lambda: _checked(vm_revert_to_current(VM_NAME, current_vm_backend)),
                                            attempts=3, delay=3, source="Vote/revert-chat/snapshot"
                                        )
                                        time.sleep(3)
                                        ok3, err3 = retry_vbox(
                                            lambda: _checked(vm_start(VM_NAME, current_vm_backend, gui=True)),
                                            attempts=3, delay=4, source="Vote/revert-chat/startvm"
                                        )
                                        if ok2 and ok3:
                                            revert_cooldown_until = time.time() + PERMISSIONS_CONFIG.get("action_cooldown", 60)
                                            update_status("Running"); play_success_sound()
                                            play_event_sound("revert_sound")
                                            _append_event("REVERT", "vote", f"chat vote passed ({current} votes)")
                                            notify("VM Reverted", "Snapshot restored by chat vote.")
                                            obs_trigger("revert_done")
                                            apply_current_os_scene()
                                            _stats["reverts"] += 1
                                        else:
                                            failed = "snapshot" if not ok2 else "startvm"
                                            update_status("Revert failed")
                                            log_error("Vote/revert", f"Chat revert failed at {failed}", str(err2 or err3))
                                            notify("Revert Failed", f"Failed at {failed} step.", timeout=6)
                                    finally:
                                        update_votes_json("revert", 0, required_votes, 0)
                                        revert_in_progress = False

                            elif cmd == 'ban':
                                # Accept both "!ban @user" and "!ban user"
                                raw_arg    = args.strip().lstrip('@').split()[0] if args.strip() else ""
                                if not raw_arg: continue
                                target_raw = raw_arg
                                target     = target_raw.lower()
                                # Prevent self-ban and owner-ban
                                if target == user: continue
                                ban_required = get_vote_threshold("ban_votes", 3)
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
        self._loop_heartbeat = time.time()
        self._reconnect()
        print(f"[MultiStream] Secondary bot initialised: {video_id}")

    def _reconnect(self):
        if self.chat:
            try: self.chat.terminate()
            except: pass
        try:
            self.chat = pytchat.create(video_id=self.video_id)
            return True
        except Exception as e:
            print(f'[MultiStream] Reconnect error ({self.video_id}): Python exception: "{traceback.format_exc()}"')
            return False

    def run(self):
        print(f"[MultiStream] Listening on: {self.video_id}")

        # Same hang watchdog as the primary bot -- self.chat.get().sync_items() below
        # can block forever with no timeout and no exception, silently freezing this
        # listener. See the primary bot's run() for the full explanation.
        HANG_THRESHOLD = 240
        def _hang_watchdog():
            while not bot_stop_event.is_set():
                if bot_stop_event.wait(30):
                    break
                stuck_for = time.time() - self._loop_heartbeat
                if stuck_for > HANG_THRESHOLD:
                    print(f"[MultiStream:{self.video_id}] Watchdog: loop stuck for {stuck_for:.0f}s -- "
                          f"forcing the stuck connection closed to unstick it.")
                    try:
                        if self.chat:
                            self.chat.terminate()
                    except Exception:
                        pass
                    self._loop_heartbeat = time.time()
        threading.Thread(target=_hang_watchdog, daemon=True,
                          name=f"multistream_hang_watchdog_{self.video_id}").start()

        while not bot_stop_event.is_set():
            self._loop_heartbeat = time.time()
            if not self.chat or not self.chat.is_alive():
                if not self._reconnect():
                    if bot_stop_event.wait(10):
                        break
                    continue
            try:
                for c in self.chat.get().sync_items():
                    if bot_stop_event.is_set():
                        break
                    msg  = c.message.strip()
                    user = normalize_username(c.author.name)
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

                        # ── Global per-user command cooldown (Permissions tab) ──
                        global_cd = PERMISSIONS_CONFIG.get("global_command_cooldown", 60)
                        if global_cd > 0 and user != ADMIN_USERNAME.lower():
                            last_cmd_time = _global_command_cooldowns.get(user, 0)
                            elapsed = time.time() - last_cmd_time
                            if elapsed < global_cd:
                                continue
                            _global_command_cooldowns[user] = time.time()

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
                            if cmd in ('type', 'text', 'say', 't', 's'):
                                send_keyboard(args)
                            elif cmd in ('send', 'sendline', 'typeenter'):
                                send_keyboard(args); send_special_enter()
                            elif cmd == 'enter':
                                send_special_enter()
                            elif cmd in ('key', 'press', 'k'):
                                k = args.lower().strip()
                                if k in SCANCODES:
                                    send_scancode(SCANCODES[k][0])
                                    time.sleep(0.01)
                                    send_scancode(SCANCODES[k][1])
                                else:
                                    send_keyboard(k)
                            elif cmd in ('combo', 'chord', 'multi', 'c'):
                                keys = parse_combo_keys(args)
                                if keys: send_combo(keys)
                            elif cmd == 'winkey':
                                k = args.lower().strip()
                                if k: send_combo(['win'] + parse_combo_keys(k))
                            elif cmd in ('click', 'lclick', 'lc', 'dclick', 'tripleclick',
                                         'rclick', 'rightclick', 'rc',
                                         'mclick', 'middleclick', 'move', 'mouse', 'mv', 'm',
                                         'abs', 'cursor', 'moveabs', 'drag', 'dragrel', 'd',
                                         'dragabs', 'drag_absolute', 'scroll', 'wheel',
                                         'scrollup', 'scrolldown'):
                                handle_mouse(cmd, args)
                            elif cmd == 'ping':
                                post_system_message("pong!")
                            elif cmd == 'roll':
                                post_system_message(f"[roll] {user} rolled {random.randint(1, 100)}")
                            elif cmd == 'coinflip':
                                post_system_message(f"[coinflip] {random.choice(['heads', 'tails'])}")
                            elif cmd in ('play', 'music', 'songrequest', 'sr'):
                                if args.strip():
                                    threading.Thread(target=queue_song_request, args=(args, user), daemon=True).start()
                                else:
                                    threading.Thread(target=start_music_player, daemon=True).start()
                            elif cmd in ('musicskip', 'skipsong', 'skipmusic'):
                                threading.Thread(target=music_skip_track, daemon=True).start()
                            elif cmd in ('stopmusic', 'musicstop'):
                                threading.Thread(target=music_stop_current, daemon=True).start()
                            elif cmd in ('video', 'videorequest', 'vr'):
                                if args.strip():
                                    threading.Thread(target=queue_video_request, args=(args, user), daemon=True).start()
                                else:
                                    threading.Thread(target=start_video_player, daemon=True).start()
                            elif cmd in ('videoskip', 'skipvideo', 'vskip'):
                                threading.Thread(target=video_skip_track, daemon=True).start()
                            elif cmd in ('stopvideo', 'videostop'):
                                threading.Thread(target=video_stop_current, daemon=True).start()
                            elif cmd in ('sb', 'soundboard'):
                                if args.strip():
                                    threading.Thread(target=soundboard_web_search_and_play, args=(args, user), daemon=True).start()
                            elif cmd == 'sbid':
                                if args.strip():
                                    threading.Thread(target=soundboard_web_id_and_play, args=(args, user), daemon=True).start()
                            elif cmd in ('sbstop', 'soundboardstop'):
                                threading.Thread(target=soundboard_stop_all, daemon=True).start()
                            elif cmd == 'srqueue':
                                threading.Thread(target=post_queue_to_overlay,
                                                  args=("Song Queue", music_song_requests, music_queue),
                                                  daemon=True).start()
                            elif cmd == 'vrqueue':
                                threading.Thread(target=post_queue_to_overlay,
                                                  args=("Video Queue", video_requests, video_queue),
                                                  daemon=True).start()
                        except Exception as e:
                            print(f'[MultiStream] Command error: Python exception: "{traceback.format_exc()}"')
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
    _overlay_log_counter = 0

    def __init__(self, widget):
        self.widget = widget
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr

    def _mirror_to_overlay(self, msg):
        """Pushes every single console line (errors, successes, fails, warnings --
        literally everything that shows up in the GUI's main log box) into
        overlay_data['chat'] too, so it also shows up live on chat.html."""
        text = msg.strip()
        if not text:
            return
        try:
            ConsoleRedirect._overlay_log_counter += 1
            update_overlay(author="[log]", message=text,
                            msg_id=f"consolelog-{ConsoleRedirect._overlay_log_counter}")
        except Exception:
            pass

    def write(self, msg):
        self._orig_stdout.write(msg)
        self._mirror_to_overlay(msg)
        enqueue_log_line_for_yt_relay(msg)
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
class UltraBotGUI:
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
        self.root.title("🤖 UltraBot Control Panel")
        self.root.configure(bg=self.BG)
        self.root.resizable(True, True)
        # Open maximized (windowed fullscreen — not borderless, still has taskbar/titlebar)
        try:
            self.root.state("zoomed")   # works on Windows and macOS's Aqua Tk build
        except Exception:
            # "zoomed" isn't a valid Tk window state on Linux's X11 Tk build at all --
            # state() there only accepts normal/iconic/withdrawn, so it raises TclError
            # rather than just not maximizing. -zoomed is the X11-native equivalent,
            # honored by virtually all EWMH-compliant window managers (which is to say,
            # nearly all of them).
            try:
                self.root.attributes("-zoomed", True)
            except Exception:
                # Last-resort fallback for the rare window manager that supports neither --
                # just size the window to the full screen manually.
                try:
                    self.root.geometry(f"{self.root.winfo_screenwidth()}x{self.root.winfo_screenheight()}+0+0")
                except Exception:
                    pass   # give up gracefully -- a normal-sized window beats a crash
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
        load_gemini_config()
        load_obs_config()
        load_permissions_config()
        load_sound_config()
        load_multi_stream_config()
        load_scheduler_config()
        load_music_config()
        load_video_config()
        load_soundboard_config()
        load_fun_high_scores()
        load_mrtristinai_config()
        self._build_ui()
        self._setup_konami_code_listener()
        load_custom_commands()
        self._refresh_cmd_list()

        # Restore backend/VM/watchdog/test-mode so a fresh launch (or any relaunch --
        # update or file replacement) doesn't silently lose what was active before.
        # Applies to both the GUI widgets AND the global current_vm_backend/VM_NAME
        # directly, so it's correct immediately, before the user needs to touch
        # anything or click Start Bot first.
        global current_vm_backend, VM_NAME, current_os_vm
        (saved_backend, saved_vm, saved_watchdog, saved_test_mode,
         saved_osv_vm, saved_osv_backend,
         _saved_ai_safety_enabled, _saved_ai_safety_provider,
         _saved_music_playback_enabled, _saved_video_playback_enabled) = load_autostart_everything_config()
        # _saved_ai_safety_enabled/_saved_ai_safety_provider/_saved_music_playback_enabled/
        # _saved_video_playback_enabled are intentionally unused here -- gemini_config.json/
        # music_config.json/video_config.json (all loaded earlier, before _build_ui()) are the
        # authoritative source actually applied to the GUI/behavior. These are only
        # saved in this file for visibility alongside everything else restored here.
        if saved_backend in ("vmware", "vbox"):
            self._vm_backend_var.set(saved_backend)
            current_vm_backend = saved_backend
            self._on_vm_backend_changed()   # repopulates the VM dropdown for this backend
            if saved_vm:
                self._vm_var.set(saved_vm)
                VM_NAME = saved_vm
                current_os_vm = saved_vm
            self._log(f"[AutostartEverything] Restored: backend={saved_backend}, "
                      f"vm={saved_vm or '(none)'}, watchdog={saved_watchdog}, test_mode={saved_test_mode}")

        # If OS Voting is enabled and there's a saved last-active OS Voting VM, restore
        # IT (and its own backend, together) as the higher-priority source of truth --
        # a specific OS Voting entry can be on a different backend than the plain
        # backend/vm fields above, so restoring just the VM name without its matching
        # backend (which is what the older os_voting_config.json mechanism alone does)
        # could otherwise pair the right VM with the wrong tool.
        if OS_VOTING_ENABLED and saved_osv_vm:
            valid_vms = [e.get("vm", "") for e in OS_LIST if e.get("vm")]
            if saved_osv_vm in valid_vms:
                current_os_vm = saved_osv_vm
                VM_NAME = saved_osv_vm
                if saved_osv_backend in ("vmware", "vbox"):
                    current_vm_backend = saved_osv_backend
                self._log(f"[AutostartEverything] Restored OS Voting VM: {saved_osv_vm} "
                          f"(backend: {saved_osv_backend or current_vm_backend})")

        self._auto_start_var.set(bool(saved_watchdog))

        if saved_test_mode and saved_vm:
            # Re-enter Test Mode automatically, same as AutoStart resumes the bot's
            # YouTube connection -- only if a VM was actually restored to target,
            # otherwise _on_test_mode_toggle()'s own validation would just reject it.
            self._test_mode_var.set(True)
            self.root.after(500, self._on_test_mode_toggle)


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

    # ── Main UI ──
    def _build_ui(self):
        # Title bar
        title_bar = tk.Frame(self.root, bg=self.BG2, height=48)
        title_bar.pack(fill="x", side="top")
        title_bar.pack_propagate(False)
        self._title_label = tk.Label(title_bar, text="🤖  UltraBot Control Panel",
                 bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI", 13, "bold"), cursor="hand2")
        self._title_label.pack(side="left", padx=16, pady=8)
        self._title_click_count = 0
        self._title_click_reset_job = None
        self._title_label.bind("<Button-1>", self._on_title_click)
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
                # get total tab width vs visible width
                total = sum(nb.tk.call(nb._w, "identify", "tab", nb.index(t))
                            for t in range(nb.index("end"))) if False else 0
                nb_w  = nb.winfo_width()
                # simpler: show scrollbar only when tabs overflow
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

        tab1_outer, tab1 = self._make_scrollable_tab(nb)
        tab2_outer, tab2 = self._make_scrollable_tab(nb)
        tab3_outer, tab3 = self._make_scrollable_tab(nb)
        tab4 = ttk.Frame(nb)   # already has its own internal Canvas+Scrollbar
        tab5_outer, tab5 = self._make_scrollable_tab(nb)
        tab6 = ttk.Frame(nb)   # already has its own internal Canvas+Scrollbar
        tab7_outer, tab7 = self._make_scrollable_tab(nb)
        tab8_outer, tab8 = self._make_scrollable_tab(nb)
        tab9_outer, tab9 = self._make_scrollable_tab(nb)
        tab10_outer, tab10 = self._make_scrollable_tab(nb)
        tab11_outer, tab11 = self._make_scrollable_tab(nb)
        tab12_outer, tab12 = self._make_scrollable_tab(nb)
        tab13_outer, tab13 = self._make_scrollable_tab(nb)
        tab14 = ttk.Frame(nb)   # already has its own internal Canvas+Scrollbar
        tab15_outer, tab15 = self._make_scrollable_tab(nb)
        tab16_outer, tab16 = self._make_scrollable_tab(nb)
        tab17_outer, tab17 = self._make_scrollable_tab(nb)
        tab18_outer, tab18 = self._make_scrollable_tab(nb)
        tab19_outer, tab19 = self._make_scrollable_tab(nb)
        tab20 = ttk.Frame(nb)   # MrTristinAI chat already has its own internal ScrolledText
        nb.add(tab1_outer, text="▶ Main")
        nb.add(tab2_outer, text="⚙ Cmds")
        nb.add(tab3_outer, text="🖥 VM")
        nb.add(tab4, text="🗳 OS Vote")
        nb.add(tab5_outer, text="🎨 Theme")
        nb.add(tab6, text="📡 OBS")
        nb.add(tab7_outer, text="📊 Stats")
        nb.add(tab8_outer, text="🚫 Users")
        nb.add(tab9_outer, text="📋 Log")
        nb.add(tab10_outer, text="🔒 Perms")
        nb.add(tab11_outer, text="🔊 Sound")
        nb.add(tab12_outer, text="🌐 Streams")
        nb.add(tab13_outer, text="📅 Sched")
        nb.add(tab14, text="🖱 Real PC")
        nb.add(tab15_outer, text="🔄 Reconnect")
        nb.add(tab16_outer, text="🎵 Music")
        nb.add(tab17_outer, text="🎬 Video")
        nb.add(tab18_outer, text="🔉 Soundboard")
        nb.add(tab19_outer, text="🌐 Web")
        nb.add(tab20, text="🤖 MrTristinAI")

        self.nb = nb   # kept for dynamic tab insertion (e.g. the hidden Fun tab easter egg)
        self._fun_tab_anchor = tab15_outer   # Fun tab is inserted right before this one
        self._reveal_fun_tab(celebrate=False)   # always visible now, no unlock requirement

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
        self._build_music_tab(tab16)
        self._build_video_tab(tab17)
        self._build_soundboard_tab(tab18)
        self._build_web_tab(tab19)
        self._build_mrtristinai_tab(tab20)
        self._sync_main_vm_lock()
        self._nb = nb   # store reference for unsaved-changes guard
        self._bind_context_menus()   # attach right-click menus to all Entry/Text widgets
        self._stats_update_job = None
        self.root.after(1000, self._refresh_stats_display)

        # ── Unsaved-changes guard: intercept tab switches ──
        # Tab indices that can have unsaved state (matched by name text prefix):
        # 1=Commands, 3=OS Voting, 5=OBS, 9=Permissions, 10=Sound&TTS,
        # 11=Multi-Stream, 12=Scheduler, 13=Real PC, 14=Reconnect
        def _on_tab_changed(event):
            try:
                new_idx = nb.index(nb.select())
                old_idx = self._current_tab
                if new_idx == old_idx:
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

        nb.bind("<<NotebookTabChanged>>", _on_tab_changed)


    def _make_scrollable_tab(self, notebook):
        """Wraps a new notebook tab in a vertically-scrollable container (Canvas + inner
        Frame + Scrollbar) and returns (outer_frame_for_notebook, inner_frame_to_populate).
        Existing _build_*_tab(parent) methods don't need any changes -- they just receive
        this inner frame as their "parent" and pack/grid into it exactly as before; the
        scrolling is entirely handled by this wrapper, transparent to the tab's own code.

        Mousewheel binding covers all 3 platforms: Windows/macOS fire <MouseWheel> with
        event.delta (positive = up), Linux/X11 fires discrete <Button-4>/<Button-5>
        events instead with no delta at all. Binding is scoped to only fire while the
        mouse is actually over this tab's content (bound/unbound on <Enter>/<Leave> of
        the canvas), so scrolling one tab doesn't scroll a different one, and so it
        doesn't steal wheel events meant for a nested Treeview/Listbox/Text widget that
        already has its own scrolling."""
        outer = ttk.Frame(notebook)
        canvas = tk.Canvas(outer, bg=self.BG, highlightthickness=0)
        vscroll = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)   # ttk, not tk -- so tab-builders can still call parent.configure(style=...) on it, and "TFrame" style already carries the correct dark background (self.BG) by default

        inner_window = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vscroll.set)

        def _on_inner_configure(event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
        inner.bind("<Configure>", _on_inner_configure)

        def _on_canvas_configure(event):
            # Keep the inner frame's width matched to the canvas's visible width so
            # widgets packed with fill="x" actually span the full tab, not just
            # whatever width their own content happens to need.
            canvas.itemconfig(inner_window, width=event.width)
            # Also stretch the inner frame's height to AT LEAST the canvas's own
            # visible height -- without this, expand=True children (like a tab's
            # top-level PanedWindow) have nothing real to expand into, since a canvas
            # window item only ever sizes to its content's own natural height, not
            # "whatever's visible". This is what actually let those children collapse
            # toward zero in the first place. Using max() here, not a flat height,
            # means content that's genuinely TALLER than the visible area still grows
            # past it and scrolls correctly -- this only fills unused space on a tab
            # that's shorter than the window, it never truncates a tab that's taller.
            natural_height = inner.winfo_reqheight()
            canvas.itemconfig(inner_window, height=max(event.height, natural_height))
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            if event.num == 4:      # Linux/X11 scroll up
                canvas.yview_scroll(-1, "units")
            elif event.num == 5:    # Linux/X11 scroll down
                canvas.yview_scroll(1, "units")
            elif getattr(event, "delta", 0):   # Windows/macOS
                canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

        def _bind_wheel(event=None):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)
            canvas.bind_all("<Button-4>", _on_mousewheel)
            canvas.bind_all("<Button-5>", _on_mousewheel)

        def _unbind_wheel(event=None):
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        canvas.bind("<Enter>", _bind_wheel)
        canvas.bind("<Leave>", _unbind_wheel)

        canvas.pack(side="left", fill="both", expand=True)
        vscroll.pack(side="right", fill="y")

        return outer, inner

    # ──────────────── TAB 1 : MAIN ────────────────
    def _build_main_tab(self, parent):
        parent.configure(style="TFrame")

        # Chat-commands pause indicator (fixes the "silent block" issue --
        # !pausechat used to have zero visible feedback anywhere)
        pause_bar = tk.Frame(parent, bg=self.BG)
        pause_bar.pack(fill="x", padx=12, pady=(10, 0))
        self._pausechat_lbl = tk.Label(pause_bar, text="", bg=self.BG,
                                        font=("Segoe UI", 9, "bold"))
        self._pausechat_lbl.pack(side="left")
        ttk.Button(pause_bar, text="Toggle Chat Commands",
                   style="Dim.TButton", command=self._toggle_pausechat).pack(side="right")
        ttk.Button(pause_bar, text="🔄 Restart Bot",
                   style="Dim.TButton", command=self._on_restart_bot_clicked).pack(side="right", padx=(0, 8))
        self._pausechat_poll()

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

        # Backend selector -- picks which tool/identifier the VM field below means
        tk.Label(card, text="Backend", bg=self.BG2,
                 fg=self.TEXTDIM, font=("Segoe UI",9,"bold")).grid(
                 row=1, column=0, sticky="w", padx=(0,8), pady=(10,0))
        self._vm_backend_var = tk.StringVar(value="vbox")
        backend_radio_frame = tk.Frame(card, bg=self.BG2)
        backend_radio_frame.grid(row=1, column=1, sticky="w", pady=(10,0))
        ttk.Radiobutton(backend_radio_frame, text="VBox", variable=self._vm_backend_var,
                        value="vbox", command=lambda: self._on_vm_backend_changed()).pack(side="left", padx=(0,12))
        ttk.Radiobutton(backend_radio_frame, text="VMware", variable=self._vm_backend_var,
                        value="vmware", command=lambda: self._on_vm_backend_changed()).pack(side="left")

        # VM selector
        self._vm_field_label = tk.Label(card, text="VirtualBox VM", bg=self.BG2,
                 fg=self.TEXTDIM, font=("Segoe UI",9,"bold"))
        self._vm_field_label.grid(row=2, column=0, sticky="w", padx=(0,8), pady=(10,0))
        self._vm_var = tk.StringVar()
        self._vm_combo = ttk.Combobox(card, textvariable=self._vm_var,
                                      state="readonly", width=30,
                                      font=("Segoe UI",10))
        self._vm_combo.bind("<<ComboboxSelected>>",
                             lambda e: save_autostart_everything_config(backend=current_vm_backend, vm=self._vm_var.get().strip()))
        self._vm_combo.grid(row=2, column=1, sticky="ew", padx=(0,12),
                            pady=(10,0), ipady=3)
        ttk.Button(card, text="🔄 Refresh", style="Dim.TButton",
                   command=self._refresh_vm_list).grid(
                   row=2, column=2, pady=(10,0))
        self._vm_select_note = tk.Label(card, text="", bg=self.BG2,
                 fg=self.YELLOW, font=("Segoe UI", 8, "italic"))
        self._vm_select_note.grid(row=3, column=0, columnspan=3, sticky="w", pady=(2,0))

        # VMware VMs aren't auto-listable the way VBoxManage lists VBox VMs -- browse
        # for a .vmx directly and register it, only shown when VMware backend is picked.
        self._vmx_browse_row = tk.Frame(card, bg=self.BG2)
        self._vmx_browse_row.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        tk.Label(self._vmx_browse_row, text="Register .vmx:", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 8)).pack(side="left")
        self._reg_vmx_var = tk.StringVar()
        ttk.Entry(self._vmx_browse_row, textvariable=self._reg_vmx_var, width=40,
                  font=("Segoe UI Mono", 9)).pack(side="left", padx=(4, 8))
        ttk.Button(self._vmx_browse_row, text="＋ Add", style="Green.TButton",
                   command=self._add_vmware_vmx_entry).pack(side="left")
        self._vmx_browse_row.grid_remove()  # hidden until VMware backend is picked

        self._on_vm_backend_changed()  # populate the combo for the initial "vbox" selection

        # Auto-start watchdog toggle
        tk.Label(card, text="Auto-Start Watchdog", bg=self.BG2,
                 fg=self.TEXTDIM, font=("Segoe UI",9,"bold")).grid(
                 row=5, column=0, sticky="w", padx=(0,8), pady=(10,0))
        self._auto_start_var = tk.BooleanVar(value=AUTO_START_ENABLED)
        auto_chk = tk.Checkbutton(card,
            text="Auto-restart the VM if it's found powered off",
            variable=self._auto_start_var, bg=self.BG2, fg=self.TEXT,
            selectcolor=self.BG3, activebackground=self.BG2,
            activeforeground=self.TEXT, font=("Segoe UI", 9),
            command=self._on_auto_start_toggle)
        auto_chk.grid(row=5, column=1, columnspan=2, sticky="w", pady=(10,0))

        # Push this machine's VM name to the other Per-OS Host Switching machine
        # (see the "Per-OS Host Switching (EXPERIMENTAL)" panel on the OS Voting tab)
        # whenever the watchdog restarts it, so both sides agree on the current VM.
        tk.Label(card, text="Host Switch Sync", bg=self.BG2,
                 fg=self.TEXTDIM, font=("Segoe UI",9,"bold")).grid(
                 row=6, column=0, sticky="w", padx=(0,8), pady=(6,0))
        self._sync_vm_name_var = tk.BooleanVar(value=HOST_SWITCH_CONFIG.get("sync_vm_name", False))
        sync_vm_chk = tk.Checkbutton(card,
            text="Sync this VM name to the other Host-Switch Receiver/Sender",
            variable=self._sync_vm_name_var, bg=self.BG2, fg=self.TEXT,
            selectcolor=self.BG3, activebackground=self.BG2,
            activeforeground=self.TEXT, font=("Segoe UI", 9),
            command=self._on_sync_vm_name_toggle)
        sync_vm_chk.grid(row=6, column=1, columnspan=2, sticky="w", pady=(6,0))

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

        # ── VM Internet panel ──
        net_card = ttk.Frame(parent, style="Card.TFrame", padding=16)
        net_card.pack(padx=60, pady=(0, 24), fill="x")
        tk.Label(net_card, text="VM Internet", bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(net_card,
                 text="Connects or disconnects the VM's internet LIVE by unplugging/replugging "
                      "its virtual network cable (VBoxManage setlinkstate1) -- works on a running "
                      "VM, no restart or power-off required.",
                 bg=self.BG2, fg=self.TEXTDIM, font=("Segoe UI", 8),
                 wraplength=420, justify="left").grid(row=1, column=0, sticky="w", pady=(4, 12))

        ttk.Button(net_card, text="🌐 Toggle Internet", style="Accent.TButton",
                   command=self._vm_toggle_internet).grid(row=2, column=0, sticky="w")

        self._internet_status_lbl = tk.Label(net_card, text="", bg=self.BG2, fg=self.TEXTDIM,
                                              font=("Segoe UI", 8, "italic"))
        self._internet_status_lbl.grid(row=3, column=0, sticky="w", pady=(10, 0))
        self._vm_refresh_internet_status()

    def _vm_refresh_internet_status(self):
        try:
            state = INTERNET_CONFIG.get("enabled", True)
            self._internet_status_lbl.configure(
                text=f"Adapter 1 link: {'UP (internet enabled)' if state else 'DOWN (internet disabled)'}.")
        except Exception:
            pass

    def _vm_toggle_internet(self):
        if not VM_NAME:
            messagebox.showerror("No VM", "Start the bot first to select a VM.")
            return
        new_state = not INTERNET_CONFIG.get("enabled", True)

        def _run():
            ok, msg = vm_set_internet_live(new_state)
            self.root.after(0, lambda: self._log(
                f"[VM Internet] setlinkstate1 {'on' if new_state else 'off'}: {msg}"))
            self.root.after(0, self._vm_refresh_internet_status)
        threading.Thread(target=_run, daemon=True).start()

    def _pausechat_poll(self):
        try:
            if CHAT_COMMANDS_PAUSED:
                self._pausechat_lbl.configure(text="⏸ Chat commands are PAUSED (non-admins blocked)", fg=self.RED)
            else:
                self._pausechat_lbl.configure(text="▶ Chat commands are live", fg=self.GREEN)
        except Exception:
            pass
        self.root.after(2000, self._pausechat_poll)

    def _toggle_pausechat(self):
        global CHAT_COMMANDS_PAUSED
        CHAT_COMMANDS_PAUSED = not CHAT_COMMANDS_PAUSED
        state = "paused" if CHAT_COMMANDS_PAUSED else "resumed"
        self._log(f"[pausechat] chat commands {state} (via GUI toggle).")
        self._pausechat_poll()

    def _on_restart_bot_clicked(self):
        """Restart Bot button -- goes through trigger_relaunch_pipeline() directly, the
        exact same function used both by the automatic "check for updates on start" flow
        and by the on-disk file-watcher. Not a separate/duplicate restart mechanism --
        this really is "manually trigger the same relaunch everything else already
        triggers automatically", writing the *autostarteverything.py copy and relaunching
        through it, same as those paths do."""
        if not messagebox.askyesno("Restart Bot",
                "This will restart the bot now (same relaunch used for updates).\n\n"
                "Continue?"):
            return
        self._log("[Restart] Manual restart requested via GUI button.")
        threading.Thread(
            target=trigger_relaunch_pipeline,
            args=("Manual restart requested via GUI button",),
            daemon=True,
        ).start()

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

        tk.Label(col_hdr, text="OS Host",      bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 9, "bold"), width=9, anchor="w").grid(row=0, column=5, padx=4)

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
        self._os_backend_vars = []
        self._os_host_vars    = []
        self._os_voting_rows_frame = inner
        self._os_voting_wheel_fn   = _on_mousewheel

        existing = OS_LIST + [{}] * (OS_VOTE_SLOTS - len(OS_LIST))
        for i in range(OS_VOTE_SLOTS):
            entry = existing[i] if i < len(existing) else {}
            self._add_os_voting_row(entry)

        btn_row = tk.Frame(parent, bg=self.BG)
        btn_row.pack(fill="x", padx=16, pady=(0, 14))
        ttk.Button(btn_row, text="🔄 Refresh VM List", style="Dim.TButton",
                   command=self._refresh_os_vm_lists).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="💾 Save OS Voting Config", style="Green.TButton",
                   command=self._save_os_voting_config).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="＋ Add VM", style="Dim.TButton",
                   command=self._add_os_voting_row_blank).pack(side="left")

        # ── Per-OS Host Switching (EXPERIMENTAL) ──
        hs_hdr = tk.Frame(parent, bg=self.BG)
        hs_hdr.pack(fill="x", padx=16, pady=(18, 6))
        tk.Label(hs_hdr, text="🌐  Per-OS Host Switching (EXPERIMENTAL)",
                 bg=self.BG, fg=self.ACCENT,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w")
        tk.Label(hs_hdr,
                 text=("If you have macOS, Windows, and Linux, you can do Per-OS host "
                       "switching between VM software with commands. Helpful if you're on "
                       "Linux and don't have Hyper-V -- a Windows 10/11 desktop/laptop/VPS "
                       "with Hyper-V can run it for you with a command like !winhypervwin11. "
                       "On this computer: it switches the OBS scene, stops the OBS stream "
                       "via websocket, stops the bot, and saves the current VM -- then on "
                       "the other computer it starts the VM assigned in current_vm.json and "
                       "starts the bot. This machine defaults to Sender; if it detects a "
                       "Sender already running elsewhere at startup, it defaults to Receiver."),
                 bg=self.BG, fg=self.TEXTDIM, font=("Segoe UI", 9),
                 wraplength=760, justify="left").pack(anchor="w", pady=(2, 0))

        hs_card = ttk.Frame(parent, style="Card.TFrame", padding=20)
        hs_card.pack(fill="x", padx=16, pady=(8, 8))

        def _hs_row(label_text, widget_factory):
            row = tk.Frame(hs_card, bg=self.BG2)
            row.pack(anchor="w", pady=(4, 0), fill="x")
            tk.Label(row, text=label_text, bg=self.BG2, fg=self.TEXT,
                     font=("Segoe UI", 9), width=16, anchor="w").pack(side="left", padx=(0, 8))
            return widget_factory(row)

        self._hs_role_var = tk.StringVar(value=HOST_SWITCH_CONFIG.get("role", "Sender"))
        def _mk_role(row):
            c = ttk.Combobox(row, textvariable=self._hs_role_var, width=12, state="readonly",
                              values=["Sender", "Receiver"], font=("Segoe UI", 9))
            c.pack(side="left")
            return c
        _hs_row("Server type?:", _mk_role)

        self._hs_obs_ws_var = tk.StringVar(value=HOST_SWITCH_CONFIG.get("obs_ws_address", ""))
        def _mk_ws(row):
            e = ttk.Entry(row, textvariable=self._hs_obs_ws_var, width=34, font=("Segoe UI Mono", 9))
            e.pack(side="left")
            return e
        _hs_row("OBS WS Address:", _mk_ws)

        self._hs_scene_var = tk.StringVar(value=HOST_SWITCH_CONFIG.get("switching_scene", ""))
        def _mk_scene(row):
            e = ttk.Entry(row, textvariable=self._hs_scene_var, width=34, font=("Segoe UI", 9))
            e.pack(side="left")
            return e
        _hs_row("Switching Scene:", _mk_scene)

        self._hs_migration_var = tk.StringVar(value=HOST_SWITCH_CONFIG.get("migration_software", "None"))
        def _mk_migration(row):
            c = ttk.Combobox(row, textvariable=self._hs_migration_var, width=18, state="readonly",
                              values=["None", "Hyper-V", "UTM", "Parallels Desktop"],
                              font=("Segoe UI", 9))
            c.pack(side="left")
            return c
        _hs_row("Migration Software:", _mk_migration)

        self._hs_port_var = tk.StringVar(value=str(HOST_SWITCH_CONFIG.get("local_port", 8765)))
        def _mk_port(row):
            e = ttk.Entry(row, textvariable=self._hs_port_var, width=10, font=("Segoe UI Mono", 9))
            e.pack(side="left")
            return e
        _hs_row("Local Port:", _mk_port)

        tk.Label(hs_card,
                 text=(f"Sender URL: {HOST_SWITCH_SENDER_URL}   |   Receiver URL: {HOST_SWITCH_RECEIVER_URL}\n"
                       f"Tunnel this machine's local port with localtunnel, matching whichever "
                       f"role you pick above."),
                 bg=self.BG2, fg=self.TEXTDIM, font=("Segoe UI", 7, "italic"),
                 justify="left").pack(anchor="w", pady=(10, 2))

        hs_btn_row = tk.Frame(hs_card, bg=self.BG2)
        hs_btn_row.pack(anchor="w", pady=(10, 0))
        ttk.Button(hs_btn_row, text="🔌 Test Connection Now",
                   command=self._hs_test_connection).pack(side="left", padx=(0, 8))
        ttk.Button(hs_btn_row, text="💾 Save Host Switching",
                   command=self._save_host_switch_config).pack(side="left")

        self._hs_status = tk.Label(hs_card, text="", bg=self.BG2, fg=self.GREEN, font=("Segoe UI", 9))
        self._hs_status.pack(anchor="w", pady=(8, 0))

        self._refresh_os_vm_lists()
        self._set_os_rows_enabled(OS_VOTING_ENABLED)
        # Track unsaved changes (tab index 3)
        self._trace_dirty(3, self._os_voting_var,
                          *self._os_name_vars, *self._os_trigger_vars, *self._os_vm_vars,
                          *self._os_host_vars, self._hs_role_var, self._hs_obs_ws_var,
                          self._hs_scene_var, self._hs_migration_var, self._hs_port_var)

    def _hs_test_connection(self):
        threading.Thread(target=host_switch_test_connection_and_handshake, daemon=True).start()
        other_role = "Receiver" if self._hs_role_var.get() == "Sender" else "Sender"
        self._hs_status.configure(text=f"Testing connection to the {other_role}... check the log.",
                                   fg=self.ACCENT)

    def _save_host_switch_config(self):
        HOST_SWITCH_CONFIG["role"] = self._hs_role_var.get()
        HOST_SWITCH_CONFIG["obs_ws_address"] = self._hs_obs_ws_var.get().strip()
        HOST_SWITCH_CONFIG["switching_scene"] = self._hs_scene_var.get().strip()
        HOST_SWITCH_CONFIG["migration_software"] = self._hs_migration_var.get()
        try:
            HOST_SWITCH_CONFIG["local_port"] = int(self._hs_port_var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid Port", "Local Port must be a number.")
            return
        save_host_switch_config()
        if _host_switch_server is None:
            start_host_switch_server()
        self._hs_status.configure(text="Host switching config saved.", fg=self.GREEN)
        self._log(f"[HostSwitch] Saved. role={HOST_SWITCH_CONFIG['role']}, "
                   f"migration={HOST_SWITCH_CONFIG['migration_software']}")

    def _add_os_voting_row(self, entry=None):
        """Builds one OS-voting row (index label, name, trigger, VM dropdown) and
        appends its vars to the shared lists that Save/Refresh already iterate over."""
        entry = entry or {}
        i = len(self._os_name_vars)
        row = tk.Frame(self._os_voting_rows_frame, bg=self.BG2)
        row.pack(fill="x", pady=3)
        row.bind("<MouseWheel>", self._os_voting_wheel_fn)

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

        backend_var = tk.StringVar(value=entry.get("backend", "vbox"))
        backend_combo = ttk.Combobox(row, textvariable=backend_var, width=8, state="readonly",
                                      values=["vbox", "vmware"], font=("Segoe UI", 9))
        backend_combo.grid(row=0, column=3, padx=4, ipady=3)
        self._os_backend_vars.append(backend_var)

        vm_var = tk.StringVar(value=entry.get("vm", ""))
        vm_combo = ttk.Combobox(row, textvariable=vm_var, width=24,
                                 state="readonly" if OS_VOTING_ENABLED else "disabled",
                                 font=("Segoe UI", 9))
        vm_combo.grid(row=0, column=4, padx=4, ipady=3)
        vm_combo.bind("<MouseWheel>", self._os_voting_wheel_fn)
        vm_combo['values'] = get_vm_list() if backend_var.get() == "vbox" else get_all_vmware_vms()

        def _on_row_backend_changed(event=None, backend_var=backend_var, vm_combo=vm_combo):
            new_vms = get_vm_list() if backend_var.get() == "vbox" else get_all_vmware_vms()
            vm_combo['values'] = new_vms
            if new_vms: vm_combo.set(new_vms[0])
        backend_combo.bind("<<ComboboxSelected>>", _on_row_backend_changed)

        self._os_vm_vars.append(vm_var)
        self._os_vm_combos.append(vm_combo)

        host_var = tk.StringVar(value=entry.get("os_host", "Current"))
        host_combo = ttk.Combobox(row, textvariable=host_var, width=9, state="readonly",
                                   values=["Current", "macOS", "Windows", "Linux"],
                                   font=("Segoe UI", 9))
        host_combo.grid(row=0, column=5, padx=4, ipady=3)
        host_combo.bind("<MouseWheel>", self._os_voting_wheel_fn)
        self._os_host_vars.append(host_var)

        return name_var, trig_var, vm_var, backend_var, host_var

    def _add_os_voting_row_blank(self):
        """+ Add VM button: adds a brand-new blank lane, exactly like the rows already
        built above -- not a value merged into the existing dropdowns."""
        name_var, trig_var, vm_var, backend_var, host_var = self._add_os_voting_row()
        self._trace_dirty(3, name_var, trig_var, vm_var, backend_var, host_var)
        self._mark_dirty(3)
        self._log("[OSVoting] Added a new VM row.")

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
        self._build_ui()

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
                      "Event key examples:  bot_start  bot_stop  restart  restart_done  revert_start  "
                      "revert_done  os_switch  ban  scheduler  vm_starting  start_done  vm_shutdown  "
                      "error_occurred_with_script  — or any custom key you call via obs_trigger().",
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
                      "Chat Trigger must match the trigger set in the OS Voting tab (e.g. win7, win10).\n"
                      "Switching Scene (optional) shows while THAT OS is booting, before its own scene takes over.\n"
                      "Receiver Scene (optional) is used instead of Switching Scene, but only on the machine "
                      "that RECEIVES a Per-OS Host Switching handoff for that OS.",
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
                 font=("Segoe UI", 8, "bold"), width=24, anchor="w").pack(side="left", padx=(0, 8))
        tk.Label(hdr, text="Switching Scene", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 8, "bold"), width=24, anchor="w").pack(side="left", padx=(0, 8))
        tk.Label(hdr, text="Receiver Scene", bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 8, "bold"), width=24, anchor="w").pack(side="left")

        self._obs_os_rows = []
        self._obs_os_rows_frame = tk.Frame(os_scene_card, bg=self.BG2)
        self._obs_os_rows_frame.pack(fill="x")
        self._obs_os_rows_frame.bind("<MouseWheel>", _on_wheel)
        self._obs_wheel_fn = _on_wheel   # store for _add_obs_os_row

        saved_os_scenes = OBS_CONFIG.get("os_scenes", {})
        saved_switching_scenes = OBS_CONFIG.get("switching_scenes", {})
        saved_recv_switching_scenes = OBS_CONFIG.get("recv_switching_scenes", {})
        prefill = []
        for entry in OS_LIST:
            t = (entry.get("trigger") or "").strip().lower().lstrip("!")
            n = entry.get("name", "")
            if t:
                prefill.append((n, t, saved_os_scenes.get(t, ""), saved_switching_scenes.get(t, ""),
                                 saved_recv_switching_scenes.get(t, "")))
        for trig, scene in saved_os_scenes.items():
            if not any(p[1] == trig for p in prefill):
                prefill.append(("", trig, scene, saved_switching_scenes.get(trig, ""),
                                 saved_recv_switching_scenes.get(trig, "")))
        while len(prefill) < 5:
            prefill.append(("", "", "", "", ""))
        for name, trig, scene, sw_scene, recv_scene in prefill:
            self._add_obs_os_row(name, trig, scene, sw_scene, recv_scene)

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
            "restart_done",
            "revert_start",
            "revert_done",
            "os_switch",
            "ban",
            "scheduler",
            "vm_starting",
            "start_done",
            "vm_shutdown",
            "error_occurred_with_script",
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

    def _add_obs_os_row(self, name="", trigger="", scene="", switching_scene="", recv_switching_scene=""):
        row = tk.Frame(self._obs_os_rows_frame, bg=self.BG2)
        row.pack(fill="x", pady=2)
        if hasattr(self, '_obs_wheel_fn'):
            row.bind("<MouseWheel>", self._obs_wheel_fn)
        name_var  = tk.StringVar(value=name)
        trig_var  = tk.StringVar(value=trigger)
        scene_var = tk.StringVar(value=scene)
        sw_var    = tk.StringVar(value=switching_scene)
        recv_var  = tk.StringVar(value=recv_switching_scene)
        ttk.Entry(row, textvariable=name_var,  width=18,
                  font=("Segoe UI", 9)).pack(side="left", padx=(0, 8), ipady=2)
        ttk.Entry(row, textvariable=trig_var,  width=14,
                  font=("Segoe UI Mono", 9)).pack(side="left", padx=(0, 8), ipady=2)
        ttk.Entry(row, textvariable=scene_var, width=24,
                  font=("Segoe UI", 9)).pack(side="left", padx=(0, 8), ipady=2)
        ttk.Entry(row, textvariable=sw_var, width=24,
                  font=("Segoe UI", 9)).pack(side="left", padx=(0, 8), ipady=2)
        ttk.Entry(row, textvariable=recv_var, width=24,
                  font=("Segoe UI", 9)).pack(side="left", ipady=2)
        ttk.Button(row, text="✕", style="Dim.TButton", width=2,
                   command=lambda r=row, t=(name_var, trig_var, scene_var, sw_var, recv_var): (
                       r.destroy(),
                       self._obs_os_rows.remove(t) if t in self._obs_os_rows else None
                   )).pack(side="left", padx=(6, 0))
        self._obs_os_rows.append((name_var, trig_var, scene_var, sw_var, recv_var))

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
        # Save per-OS scenes (and each row's own switching / receiver-switching scene)
        os_scenes = {}
        switching_scenes = {}
        recv_switching_scenes = {}
        for name_var, trig_var, scene_var, sw_var, recv_var in self._obs_os_rows:
            trig  = trig_var.get().strip().lower().lstrip("!")
            scene = scene_var.get().strip()
            sw_scene = sw_var.get().strip()
            recv_scene = recv_var.get().strip()
            if trig and scene:
                os_scenes[trig] = scene
            if trig and sw_scene:
                switching_scenes[trig] = sw_scene
            if trig and recv_scene:
                recv_switching_scenes[trig] = recv_scene
        OBS_CONFIG["os_scenes"] = os_scenes
        OBS_CONFIG["switching_scenes"] = switching_scenes
        OBS_CONFIG["recv_switching_scenes"] = recv_switching_scenes
        save_obs_config()
        self._clear_dirty(5)
        messagebox.showinfo("Saved", "OBS settings saved.")

    def _on_auto_start_toggle(self):
        global AUTO_START_ENABLED
        AUTO_START_ENABLED = self._auto_start_var.get()
        save_auto_start_config()
        self._log(f"[AutoStart] Watchdog {'enabled' if AUTO_START_ENABLED else 'disabled'} by user.")

    def _on_sync_vm_name_toggle(self):
        HOST_SWITCH_CONFIG["sync_vm_name"] = self._sync_vm_name_var.get()
        save_host_switch_config()
        self._log(f"[HostSwitch] Sync VM name to other host "
                   f"{'enabled' if HOST_SWITCH_CONFIG['sync_vm_name'] else 'disabled'} by user.")

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
            self._vm_select_note.configure(text="")

    def _on_os_voting_toggle(self):
        self._set_os_rows_enabled(self._os_voting_var.get())

    def _save_os_voting_config(self):
        global OS_VOTING_ENABLED, OS_LIST
        enabled = self._os_voting_var.get()
        new_list = []
        for i in range(len(self._os_name_vars)):
            name = self._os_name_vars[i].get().strip()
            trig = self._os_trigger_vars[i].get().strip().lower().lstrip("!")
            vm   = self._os_vm_vars[i].get().strip()
            backend = self._os_backend_vars[i].get().strip() or "vbox"
            os_host = self._os_host_vars[i].get().strip() or "Current" if i < len(self._os_host_vars) else "Current"
            if name or trig or vm:
                new_list.append({"name": name, "trigger": trig, "vm": vm, "backend": backend, "os_host": os_host})

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
                obs_trigger("vm_starting")
                start_vm()
                self.root.after(0, lambda: self._vm_set_last("Started ✔", self.GREEN))
            except Exception as e:
                err_msg = f"Error: {e}"
                self.root.after(0, lambda msg=err_msg: self._vm_set_last(msg, self.RED))
                print(f'[VM] Start error: Python exception: "{traceback.format_exc()}"')
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
                _checked(vm_reset(VM_NAME, current_vm_backend))
                update_status("Running")
                play_success_sound()
                obs_trigger("restart")
                obs_trigger("restart_done")
                apply_current_os_scene()
                self.root.after(0, lambda: self._vm_set_last("Restarted ✔", self.GREEN))
            except Exception as e:
                err_msg = f"Error: {e}"
                self.root.after(0, lambda msg=err_msg: self._vm_set_last(msg, self.RED))
                print(f'[VM] Restart error: Python exception: "{traceback.format_exc()}"')
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
                _checked(vm_stop(VM_NAME, current_vm_backend, hard=True))
                time.sleep(3)
                _checked(vm_revert_to_current(VM_NAME, current_vm_backend))
                time.sleep(3)
                obs_trigger("vm_starting")
                _checked(vm_start(VM_NAME, current_vm_backend, gui=True))
                update_status("Running")
                play_success_sound()
                obs_trigger("revert_done")
                apply_current_os_scene()
                vote_revert.clear()
                update_votes_json("revert", 0, 2, 0)
                self.root.after(0, lambda: self._vm_set_last("Reverted ✔", self.GREEN))
            except Exception as e:
                update_status("Revert failed")
                err_msg = f"Error: {e}"
                self.root.after(0, lambda msg=err_msg: self._vm_set_last(msg, self.RED))
                print(f'[VM] Revert error: Python exception: "{traceback.format_exc()}"')
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
                _checked(vm_stop(VM_NAME, current_vm_backend, hard=True))
                update_status("Stopped")
                obs_trigger("vm_shutdown")
                self.root.after(0, lambda: self._vm_set_last("Powered off ✔", self.TEXTDIM))
            except Exception as e:
                err_msg = f"Error: {e}"
                self.root.after(0, lambda msg=err_msg: self._vm_set_last(msg, self.RED))
                print(f'[VM] Shutdown error: Python exception: "{traceback.format_exc()}"')
        threading.Thread(target=run, daemon=True).start()

    # ──────────────── Helpers ────────────────
    @staticmethod
    def _font_exists(name):
        import tkinter.font as tkfont
        return name in tkfont.families()

    def _log(self, msg):
        if threading.current_thread() is not threading.main_thread():
            # macOS requires ALL Tk widget touches to happen on the main thread --
            # unlike Windows/Linux, which tolerate cross-thread widget access most of
            # the time. This is called from many background threads throughout the
            # codebase (watchdogs, test mode, OS vote timers, etc.), so rather than
            # audit every call site individually, this one central choke point
            # re-dispatches itself onto the main thread via root.after() whenever it's
            # not already there.
            try:
                self.root.after(0, lambda: self._log(msg))
            except Exception:
                pass
            return
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
        if threading.current_thread() is not threading.main_thread():
            try:
                self.root.after(0, lambda: self._set_status(text, color))
            except Exception:
                pass
            return
        self._status_dot.configure(text=f"⬤  {text}", fg=color)

    # ──────────────── VM List ────────────────
    def _on_vm_backend_changed(self):
        """Swaps the VM field's label, the .vmx registration row's visibility, and
        populates the combo from the right source for whichever backend is selected.
        Also saves the selection to autostarteverything.json so it's remembered on
        the next launch/relaunch instead of silently defaulting back to vbox every
        time."""
        global current_vm_backend
        backend = self._vm_backend_var.get()
        current_vm_backend = backend
        if backend == "vmware":
            self._vm_field_label.configure(text="VMware .vmx Path")
            self._vmx_browse_row.grid()
            vms = get_all_vmware_vms()
        else:
            self._vm_field_label.configure(text="VirtualBox VM")
            self._vmx_browse_row.grid_remove()
            vms = get_vm_list()
        self._vm_combo['values'] = vms
        if vms:
            self._vm_combo.current(0)
        save_autostart_everything_config(backend=current_vm_backend, vm=self._vm_var.get().strip())

    def _add_vmware_vmx_entry(self):
        vmx = self._reg_vmx_var.get().strip().strip('"').strip("'")
        if not vmx:
            return
        register_vmware_vm(vmx)
        self._on_vm_backend_changed()
        self._vm_var.set(vmx)
        self._log(f"[VMware] Registered: {vmx}")

    def _refresh_vm_list(self):
        backend = self._vm_backend_var.get() if hasattr(self, "_vm_backend_var") else "vbox"
        vms = get_all_vmware_vms() if backend == "vmware" else get_vm_list()
        self._vm_combo['values'] = vms
        if vms:
            self._vm_combo.current(0)
            self._log(f"{backend}: {len(vms)} VM(s) found.")
        else:
            self._log("⚠️ No VMs found (VirtualBox installed?)")

    # ──────────────── Bot Start / Stop ────────────────
    def _test_mode_poll_stdin(self):
        """macOS-safe alternative to running input() on a background thread. That
        combination -- blocking input() on a thread while Tkinter's mainloop() is
        active on the main thread -- is a known problematic pattern on macOS
        specifically: Python's stdin/readline handling can contend with Tcl's own
        event notifier across threads and corrupt it, surfacing as
        "Tcl_WaitForEvent: Notifier not initialized" and a hard process abort. This
        avoids the whole problem by never touching stdin from a background thread at
        all -- it polls non-blockingly (select with a 0 timeout, so this returns
        instantly whether or not a line is ready) from right here on the main thread,
        rescheduling itself via root.after() the same way any other periodic GUI
        update does."""
        global TEST_MODE_ENABLED
        if not TEST_MODE_ENABLED:
            return
        try:
            if select.select([sys.stdin], [], [], 0)[0]:
                line = sys.stdin.readline()
                if line == "":
                    # stdin closed (EOF) -- stop cleanly rather than spin forever.
                    print("[TestMode] stdin closed. Stopping test mode.")
                    bot_stop_event.set()
                    self._test_mode_var.set(False)
                    TEST_MODE_ENABLED = False
                    self._set_status("Stopped", self.RED)
                    self._log("[TestMode] Stopped (stdin closed).")
                    return
                print(f"[TestMode] > {line.strip()}")
                if not _process_test_mode_line(line):
                    self._test_mode_var.set(False)
                    TEST_MODE_ENABLED = False
                    self._set_status("Stopped", self.RED)
                    self._log("[TestMode] Stopped.")
                    return
        except Exception as e:
            print(f'[TestMode] poll error: Python exception: "{traceback.format_exc()}"')
        if TEST_MODE_ENABLED:
            self.root.after(150, self._test_mode_poll_stdin)

    def _on_test_mode_toggle(self):
        global TEST_MODE_ENABLED, VM_NAME, current_os_vm, current_vm_backend
        enabled = self._test_mode_var.get()
        TEST_MODE_ENABLED = enabled

        if enabled:
            vm = self._vm_var.get().strip()
            if not vm and not (OS_VOTING_ENABLED and OS_LIST):
                messagebox.showerror("Missing VM",
                    "Please select a VM before enabling Test Mode.")
                self._test_mode_var.set(False)
                TEST_MODE_ENABLED = False
                return
            if self._bot_running:
                messagebox.showwarning("Bot Running",
                    "Stop the bot first before starting Test Mode.")
                self._test_mode_var.set(False)
                TEST_MODE_ENABLED = False
                return
            # Set VM target AND backend -- current_vm_backend was never set here at
            # all before, so regardless of what the user picked in the GUI, it
            # silently stayed at whatever it was before, meaning every VM command in
            # Test Mode could dispatch to the wrong tool entirely.
            if OS_VOTING_ENABLED:
                valid = [e for e in OS_LIST if e.get("vm")]
                if valid:
                    VM_NAME = valid[0]["vm"]
                    current_os_vm = VM_NAME
                    current_vm_backend = valid[0].get("backend", "vbox")
            else:
                VM_NAME = vm
                current_os_vm = vm
                current_vm_backend = self._vm_backend_var.get() if hasattr(self, "_vm_backend_var") else "vbox"
            # Start background threads needed for VM control
            bot_stop_event.clear()
            threading.Thread(target=watchdog_restart,       daemon=True).start()
            threading.Thread(target=os_vote_timeout_checker, daemon=True).start()
            print("[TestMode] Started. Type commands (e.g. '!type hello', '!click', '!win7'). Type '!quit' to stop.")
            print("[TestMode] All normal bot commands are supported.")
            if platform.system() == "Darwin":
                # See _test_mode_poll_stdin's docstring for why macOS needs a
                # different approach here than just starting run_test_mode() on a
                # background thread the way Windows/Linux do below.
                self.root.after(150, self._test_mode_poll_stdin)
            else:
                threading.Thread(target=run_test_mode, daemon=True).start()
            self._set_status("Test Mode", self.YELLOW)
            self._log(f"[TestMode] Started. VM: {VM_NAME} (backend: {current_vm_backend}). Type commands in the console.")
            notify("Test Mode Active", f"VM: {VM_NAME}\nType commands in the console window.")
            save_autostart_everything_config(backend=current_vm_backend, vm=VM_NAME, test_mode=True)
        else:
            bot_stop_event.set()
            self._set_status("Stopped", self.RED)
            self._log("[TestMode] Stopped.")
            notify("Test Mode Stopped", "Test mode has been disabled.")
            save_autostart_everything_config(test_mode=False)

    def _start_bot(self):
        global VIDEO_ID, VM_NAME, current_os_vm, current_vm_backend
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
                start_entry = next(e for e in valid_entries if e["vm"] == current_os_vm)
                start_name = start_entry["name"]
                self._log(f"[OSVoting] Resuming with last active OS: '{start_name}'.")
            else:
                start_entry = valid_entries[0]
                start_vm_name = start_entry["vm"]
                start_name    = start_entry["name"]
                self._log(f"[OSVoting] No saved OS found — starting with first entry: '{start_name}'.")
            VM_NAME = start_vm_name
            current_os_vm = start_vm_name
            current_vm_backend = start_entry.get("backend", "vbox")
        else:
            if not vm:
                messagebox.showerror("Missing Input", "Please select a VM.")
                return
            VM_NAME = vm
            current_os_vm = vm
            current_vm_backend = self._vm_backend_var.get() if hasattr(self, "_vm_backend_var") else "vbox"

        VIDEO_ID = yt
        self._bot_running = True
        bot_stop_event.clear()
        self._set_status("Running", self.GREEN)

        # Redirect stdout → console
        self._console_redir = ConsoleRedirect(self._console)
        self._console_redir.start()

        self._log(f"Starting bot → YT: {VIDEO_ID}  |  VM: {VM_NAME}")
        notify("Bot Started", f"Listening on: {VIDEO_ID}\nVM: {VM_NAME}")
        obs_trigger("bot_start")
        _reset_session_stats()
        _append_event("BOT_START", "system", f"video_id={VIDEO_ID} vm={VM_NAME}")
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
                            print(f'[MultiStream] Error for {vid}: Python exception: "{traceback.format_exc()}"')
                    threading.Thread(target=_run_extra, daemon=True).start()
                    print(f"[MultiStream] Started listener for extra stream: {extra_vid}")
            if bot.chat and bot.chat.is_alive():
                bot.run()
            else:
                print("[Bot] Chat connection failed at startup.")
        except Exception as e:
            print(f'[Bot] Fatal error: Python exception: "{traceback.format_exc()}"')
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
                print(f'[Bot] Error terminating chat connection: Python exception: "{traceback.format_exc()}"')
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
        global revert_in_progress, revert_start_time
        cmd = self._admin_var.get().strip()
        if not cmd: return
        self._admin_var.set("")
        self._log(f"[AdminCMD] {cmd}")

        def run():
            c = cmd.lower()
            if c == '!startvm':
                speak_text("Starting Virtual Machine...")
                update_status("Starting...")
                obs_trigger("vm_starting")
                start_vm()
            elif c == '!restart':
                speak_text("Restarting Virtual Machine...")
                update_status("Restarting...")
                try:
                    _checked(vm_reset(VM_NAME, current_vm_backend))
                    update_status("Running")
                    play_success_sound()
                    obs_trigger("restart")
                    obs_trigger("restart_done")
                    apply_current_os_scene()
                except Exception as e:
                    update_status("Restart failed")
                    print(f'[Admin] Restart error: Python exception: "{traceback.format_exc()}"')
            elif c.startswith('!speak '):
                speak_text(cmd[7:].strip())
            elif c == '!revert':
                global revert_in_progress, revert_start_time
                speak_text("Reverting Virtual Machine...")
                revert_in_progress = True
                update_status("Reverting...")
                try:
                    _checked(vm_stop(VM_NAME, current_vm_backend, hard=True))
                    time.sleep(3)
                    _checked(vm_revert_to_current(VM_NAME, current_vm_backend))
                    time.sleep(3)
                    _checked(vm_start(VM_NAME, current_vm_backend, gui=True))
                    update_status("Running")
                    play_success_sound()
                    obs_trigger("revert_done")
                    apply_current_os_scene()
                    vote_revert.clear()
                    update_votes_json("revert", 0, 2, 0)
                except Exception as e:
                    update_status("Revert failed")
                    print(f'[Admin] Revert error: Python exception: "{traceback.format_exc()}"')
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
            elif c == '!enableinternet':
                ok, msg = vm_set_internet_live(True)
                print(f"[Admin] enableinternet: {msg}")
            elif c == '!disableinternet':
                ok, msg = vm_set_internet_live(False)
                print(f"[Admin] disableinternet: {msg}")
            elif c == '!shutdown':
                ok, msg = vm_shutdown_soft()
                print(f"[Admin] shutdown: {msg}")
            elif c in ('!killvm', '!forceshutdown'):
                ok, msg = vm_shutdown_hard_kill()
                print(f"[Admin] killvm: {msg}")
            elif c == '!pausevm':
                ok, msg = vm_pause()
                print(f"[Admin] pausevm: {msg}")
            elif c == '!resumevm':
                ok, msg = vm_unpause()
                print(f"[Admin] resumevm: {msg}")
            elif c == '!vmsavestate':
                ok, msg = vm_save_state()
                print(f"[Admin] vmsavestate: {msg}")
            elif c.startswith('!makesnapshot') or c.startswith('!snapshot'):
                name = cmd.split(maxsplit=1)[1].strip() if len(cmd.split(maxsplit=1)) > 1 else ""
                ok, msg = vm_make_snapshot(name)
                print(f"[Admin] makesnapshot: {msg}")
            elif c == '!vmstatus':
                print(f"[Admin] {cmd_status_text()}")
            elif c == '!pausechat':
                global CHAT_COMMANDS_PAUSED
                CHAT_COMMANDS_PAUSED = True
                print("[Admin] Chat commands paused")
            elif c == '!enablechat':
                CHAT_COMMANDS_PAUSED = False
                print("[Admin] Chat commands resumed")
            else:
                # Not one of the admin-only commands above -- fall back to the same
                # general bot-command processor test mode's console uses, so !send,
                # !type, !click, !combo, !key, etc. all work from this box too.
                ok, message = run_single_bot_command(cmd)
                self.root.after(0, lambda m=message: self._log(f"[Admin] {m}"))

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
            self._stats_update_job = self.root.after(2000, self._refresh_stats_display)
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
        self._ban_refresh_job = self.root.after(5000, self._refresh_ban_list)

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
        self.root.after(3000, self._elog_auto_refresh)

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
            ("global_command_cooldown", "🕒  Command cooldown (seconds, every command)",
             "Seconds a non-mod must wait between ANY two commands. 0 = disabled. Mods/owner are exempt."),
        ]

        self._perm_vars = {}
        for row_i, (key, label, hint) in enumerate(PERM_ROWS):
            tk.Label(card, text=label, bg=self.BG2, fg=self.TEXT,
                     font=("Segoe UI", 10, "bold")).grid(
                     row=row_i * 2, column=0, sticky="w", pady=(12 if row_i else 0, 0))
            tk.Label(card, text=hint, bg=self.BG2, fg=self.TEXTDIM,
                     font=("Segoe UI", 8)).grid(
                     row=row_i * 2 + 1, column=0, sticky="w", padx=(16, 0))

            var = tk.IntVar(value=PERMISSIONS_CONFIG.get(key, 2 if key not in ("action_cooldown", "global_command_cooldown") else 60))
            self._perm_vars[key] = var

            spin_to = 3600 if key in ("action_cooldown", "global_command_cooldown") else 99
            spin_from = 0  if key in ("action_cooldown", "global_command_cooldown") else 1
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

        # ── Vote Threshold by % of Viewers ──
        pct_card = ttk.Frame(parent, style="Card.TFrame", padding=20)
        pct_card.pack(fill="x", padx=12, pady=(12, 0))
        tk.Label(pct_card, text="🗳️  Vote Threshold by % of Viewers", bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w")
        tk.Label(pct_card,
                 text="When enabled, EVERY vote command (restart, revert, ban, OS voting) needs this % "
                      "of current live viewers instead of a fixed vote count. Requires a YouTube Data API "
                      "v3 key below to know the live viewer count -- falls back to the fixed counts above "
                      "if no live number is available yet.",
                 bg=self.BG2, fg=self.TEXTDIM, font=("Segoe UI", 8),
                 wraplength=560, justify="left").pack(anchor="w", pady=(4, 10))

        self._vote_pct_enabled_var = tk.BooleanVar(value=PERMISSIONS_CONFIG.get("vote_threshold_percent_enabled", False))
        ttk.Checkbutton(pct_card, text="Enable % of viewers threshold for every vote command",
                        variable=self._vote_pct_enabled_var,
                        style="Toggle.TCheckbutton").pack(anchor="w")

        pct_row = tk.Frame(pct_card, bg=self.BG2)
        pct_row.pack(anchor="w", pady=(8, 0))
        tk.Label(pct_row, text="Percent of viewers required:", bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI", 9)).pack(side="left", padx=(0, 8))
        self._vote_pct_var = tk.IntVar(value=PERMISSIONS_CONFIG.get("vote_threshold_percent", 30))
        tk.Spinbox(pct_row, textvariable=self._vote_pct_var, from_=1, to=100, width=5,
                  bg=self.BG3, fg=self.TEXT, insertbackground=self.TEXT,
                  buttonbackground=self.BG3, font=("Segoe UI", 11, "bold"),
                  relief="flat", bd=1).pack(side="left")
        tk.Label(pct_row, text="%", bg=self.BG2, fg=self.TEXT, font=("Segoe UI", 9)).pack(side="left", padx=(4, 0))

        api_row = tk.Frame(pct_card, bg=self.BG2)
        api_row.pack(anchor="w", pady=(12, 0), fill="x")
        tk.Label(api_row, text="YouTube Data API v3 key:", bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI", 9)).pack(side="left", padx=(0, 8))
        self._youtube_api_key_var = tk.StringVar(value=YOUTUBE_API_KEY)
        ttk.Entry(api_row, textvariable=self._youtube_api_key_var, width=40,
                  show="•", font=("Segoe UI Mono", 9)).pack(side="left")
        tk.Label(pct_card,
                 text="Free from console.cloud.google.com -- enable the \"YouTube Data API v3\" and create an API key.",
                 bg=self.BG2, fg=self.TEXTDIM, font=("Segoe UI", 7, "italic")).pack(anchor="w", pady=(4, 0))

        # ── AI Pre-Execution Safety/Copyright Screening (Gemini or Groq) ──
        gemini_card = ttk.Frame(parent, style="Card.TFrame", padding=20)
        gemini_card.pack(fill="x", padx=12, pady=(12, 0))
        tk.Label(gemini_card, text="🛡️  AI Copyright/Safety Screening", bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w")
        tk.Label(gemini_card,
                 text="When enabled, checks !sr/!vr requests and typed text (!type/!send/!sendline/"
                      "!typeenter) for obvious copyright risk BEFORE it plays or displays live, blocking it "
                      "if flagged. This is a best-effort safety net for obvious cases, not a guarantee -- it "
                      "fails open (allows the command) on any error, timeout, or missing API key, so a "
                      "problem with this check can never itself take your commands offline.",
                 bg=self.BG2, fg=self.TEXTDIM, font=("Segoe UI", 8),
                 wraplength=560, justify="left").pack(anchor="w", pady=(4, 10))

        self._gemini_enabled_var = tk.BooleanVar(value=gemini_config.get("enabled", False))
        ttk.Checkbutton(gemini_card, text="Enable AI pre-execution screening",
                        variable=self._gemini_enabled_var,
                        style="Toggle.TCheckbutton").pack(anchor="w")

        provider_row = tk.Frame(gemini_card, bg=self.BG2)
        provider_row.pack(anchor="w", pady=(12, 0), fill="x")
        tk.Label(provider_row, text="Provider:", bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI", 9)).pack(side="left", padx=(0, 8))
        self._ai_provider_var = tk.StringVar(value=gemini_config.get("provider", "gemini"))
        ttk.Radiobutton(provider_row, text="Gemini", variable=self._ai_provider_var,
                        value="gemini").pack(side="left", padx=(0, 16))
        ttk.Radiobutton(provider_row, text="Groq", variable=self._ai_provider_var,
                        value="groq").pack(side="left")

        gemini_api_row = tk.Frame(gemini_card, bg=self.BG2)
        gemini_api_row.pack(anchor="w", pady=(12, 0), fill="x")
        tk.Label(gemini_api_row, text="Gemini API key:", bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI", 9), width=14, anchor="w").pack(side="left", padx=(0, 8))
        self._gemini_api_key_var = tk.StringVar(value=gemini_config.get("gemini_api_key", ""))
        ttk.Entry(gemini_api_row, textvariable=self._gemini_api_key_var, width=40,
                  show="•", font=("Segoe UI Mono", 9)).pack(side="left")
        tk.Label(gemini_card,
                 text="Free from aistudio.google.com -- click \"Get API key\"."
                      + ("" if gemini_available else "  ⚠ pip install google-genai is required for this to work."),
                 bg=self.BG2, fg=(self.TEXTDIM if gemini_available else self.RED),
                 font=("Segoe UI", 7, "italic")).pack(anchor="w", pady=(4, 8))

        groq_api_row = tk.Frame(gemini_card, bg=self.BG2)
        groq_api_row.pack(anchor="w", pady=(4, 0), fill="x")
        tk.Label(groq_api_row, text="Groq API key:", bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI", 9), width=14, anchor="w").pack(side="left", padx=(0, 8))
        self._groq_api_key_var = tk.StringVar(value=gemini_config.get("groq_api_key", ""))
        ttk.Entry(groq_api_row, textvariable=self._groq_api_key_var, width=40,
                  show="•", font=("Segoe UI Mono", 9)).pack(side="left")
        tk.Label(gemini_card,
                 text="Free from console.groq.com -- click \"API Keys\" → \"Create API Key\"."
                      + ("" if groq_available else "  ⚠ pip install openai is required for this to work."),
                 bg=self.BG2, fg=(self.TEXTDIM if groq_available else self.RED),
                 font=("Segoe UI", 7, "italic")).pack(anchor="w", pady=(4, 0))

        # ── YT Chat Log Relay panel ──
        relay_hdr = tk.Frame(parent, bg=self.BG)
        relay_hdr.pack(fill="x", padx=16, pady=(18, 6))
        tk.Label(relay_hdr, text="📡  YT Chat Log Relay",
                 bg=self.BG, fg=self.ACCENT,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w")
        tk.Label(relay_hdr, text="Mirrors every line of this app's console log out to the YouTube Live Chat.",
                 bg=self.BG, fg=self.TEXTDIM, font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))

        relay_card = ttk.Frame(parent, style="Card.TFrame", padding=20)
        relay_card.pack(fill="x", padx=12, pady=(8, 0))

        self._relay_enabled_var = tk.BooleanVar(value=YT_LOG_RELAY_CONFIG.get("enabled", False))
        ttk.Checkbutton(relay_card, text="Enable relay (console log → YT chat)",
                        variable=self._relay_enabled_var,
                        style="Toggle.TCheckbutton").pack(anchor="w", pady=(0, 10))

        def _relay_row(parent_frame, label_text, config_key, secret=False):
            row = tk.Frame(parent_frame, bg=self.BG2)
            row.pack(anchor="w", pady=(4, 0), fill="x")
            tk.Label(row, text=label_text, bg=self.BG2, fg=self.TEXT,
                     font=("Segoe UI", 9), width=16, anchor="w").pack(side="left", padx=(0, 8))
            var = tk.StringVar(value=YT_LOG_RELAY_CONFIG.get(config_key, ""))
            entry_kwargs = {"show": "•"} if secret else {}
            ttk.Entry(row, textvariable=var, width=46,
                      font=("Segoe UI Mono", 9), **entry_kwargs).pack(side="left")
            return var

        self._relay_client_id_var = _relay_row(relay_card, "Client ID:", "client_id")
        self._relay_client_secret_var = _relay_row(relay_card, "Client Secret:", "client_secret", secret=True)
        self._relay_live_chat_id_var = _relay_row(relay_card, "Live Chat ID:", "live_chat_id")

        tk.Label(relay_card, text="One-time setup -- paste a fresh auth code below and click Exchange,"
                                   " or paste an access/refresh token pair you already have.",
                 bg=self.BG2, fg=self.TEXTDIM, font=("Segoe UI", 7, "italic")).pack(anchor="w", pady=(10, 2))

        self._relay_auth_code_var = _relay_row(relay_card, "Auth Code:", "auth_code")
        self._relay_access_token_var = _relay_row(relay_card, "Access Token:", "access_token", secret=True)
        self._relay_refresh_token_var = _relay_row(relay_card, "Refresh Token:", "refresh_token", secret=True)

        relay_btn_row = tk.Frame(relay_card, bg=self.BG2)
        relay_btn_row.pack(anchor="w", pady=(12, 0))
        ttk.Button(relay_btn_row, text="🔐 Exchange Auth Code",
                   command=self._relay_exchange_auth_code).pack(side="left", padx=(0, 8))
        ttk.Button(relay_btn_row, text="🔄 Refresh Token Now",
                   command=self._relay_refresh_token).pack(side="left")

        self._relay_status = tk.Label(relay_card, text="", bg=self.BG2, fg=self.GREEN,
                                       font=("Segoe UI", 9))
        self._relay_status.pack(anchor="w", pady=(8, 0))

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
        self._trace_dirty(9, *self._perm_vars.values(),
                          self._vote_pct_enabled_var, self._vote_pct_var, self._youtube_api_key_var,
                          self._gemini_enabled_var, self._gemini_api_key_var,
                          self._ai_provider_var, self._groq_api_key_var,
                          self._relay_enabled_var, self._relay_client_id_var, self._relay_client_secret_var,
                          self._relay_live_chat_id_var, self._relay_auth_code_var,
                          self._relay_access_token_var, self._relay_refresh_token_var)

    def _relay_exchange_auth_code(self):
        """Pulls the 3 fields from the panel, saves them, and exchanges the
        auth code for a fresh access_token/refresh_token pair."""
        YT_LOG_RELAY_CONFIG["client_id"] = self._relay_client_id_var.get().strip()
        YT_LOG_RELAY_CONFIG["client_secret"] = self._relay_client_secret_var.get().strip()
        YT_LOG_RELAY_CONFIG["live_chat_id"] = self._relay_live_chat_id_var.get().strip()
        YT_LOG_RELAY_CONFIG["auth_code"] = self._relay_auth_code_var.get().strip()
        ok = yt_relay_exchange_auth_code()
        self._relay_access_token_var.set(YT_LOG_RELAY_CONFIG.get("access_token", ""))
        self._relay_refresh_token_var.set(YT_LOG_RELAY_CONFIG.get("refresh_token", ""))
        self._relay_auth_code_var.set("")
        self._relay_status.configure(
            text="Tokens obtained." if ok else "Exchange failed -- check the log.",
            fg=self.GREEN if ok else self.RED)

    def _relay_refresh_token(self):
        """Uses whatever refresh_token is currently on the panel to mint a new
        access_token, without needing a fresh auth code."""
        YT_LOG_RELAY_CONFIG["client_id"] = self._relay_client_id_var.get().strip()
        YT_LOG_RELAY_CONFIG["client_secret"] = self._relay_client_secret_var.get().strip()
        YT_LOG_RELAY_CONFIG["refresh_token"] = self._relay_refresh_token_var.get().strip()
        new_token = yt_relay_refresh_access_token()
        if new_token:
            self._relay_access_token_var.set(new_token)
        self._relay_status.configure(
            text="Access token refreshed." if new_token else "Refresh failed -- check the log.",
            fg=self.GREEN if new_token else self.RED)

    def _save_permissions(self):
        global YOUTUBE_API_KEY
        YT_LOG_RELAY_CONFIG["enabled"] = self._relay_enabled_var.get()
        YT_LOG_RELAY_CONFIG["client_id"] = self._relay_client_id_var.get().strip()
        YT_LOG_RELAY_CONFIG["client_secret"] = self._relay_client_secret_var.get().strip()
        YT_LOG_RELAY_CONFIG["live_chat_id"] = self._relay_live_chat_id_var.get().strip()
        YT_LOG_RELAY_CONFIG["access_token"] = self._relay_access_token_var.get().strip()
        YT_LOG_RELAY_CONFIG["refresh_token"] = self._relay_refresh_token_var.get().strip()
        if self._relay_auth_code_var.get().strip():
            YT_LOG_RELAY_CONFIG["auth_code"] = self._relay_auth_code_var.get().strip()
            yt_relay_exchange_auth_code()
            self._relay_access_token_var.set(YT_LOG_RELAY_CONFIG.get("access_token", ""))
            self._relay_refresh_token_var.set(YT_LOG_RELAY_CONFIG.get("refresh_token", ""))
            self._relay_auth_code_var.set("")
        save_yt_log_relay_config()
        if YT_LOG_RELAY_CONFIG["enabled"]:
            start_yt_log_relay_worker()
        for key, var in self._perm_vars.items():
            try:
                val = int(var.get())
                PERMISSIONS_CONFIG[key] = max(0, val) if key in ("action_cooldown", "global_command_cooldown") else max(1, val)
            except ValueError:
                pass
        PERMISSIONS_CONFIG["vote_threshold_percent_enabled"] = self._vote_pct_enabled_var.get()
        try:
            PERMISSIONS_CONFIG["vote_threshold_percent"] = max(1, min(100, int(self._vote_pct_var.get())))
        except ValueError:
            pass
        YOUTUBE_API_KEY = self._youtube_api_key_var.get().strip()
        save_permissions_config()

        global _gemini_client, _groq_client
        new_gemini_key = self._gemini_api_key_var.get().strip()
        new_groq_key = self._groq_api_key_var.get().strip()
        if new_gemini_key != gemini_config.get("gemini_api_key", ""):
            _gemini_client = None   # force re-init with the new key next time it's used
        if new_groq_key != gemini_config.get("groq_api_key", ""):
            _groq_client = None
        gemini_config["enabled"] = self._gemini_enabled_var.get()
        gemini_config["provider"] = self._ai_provider_var.get()
        gemini_config["gemini_api_key"] = new_gemini_key
        gemini_config["groq_api_key"] = new_groq_key
        save_gemini_config()
        save_autostart_everything_config(ai_safety_enabled=gemini_config["enabled"],
                                          ai_safety_provider=gemini_config["provider"])

        self._clear_dirty(9)
        pct_note = (f"vote-by-%:{PERMISSIONS_CONFIG['vote_threshold_percent']}% "
                    if PERMISSIONS_CONFIG['vote_threshold_percent_enabled'] else "vote-by-%:off ")
        self._perm_status.configure(
            text=f"Saved — restart:{PERMISSIONS_CONFIG['restart_votes']}  "
                 f"revert:{PERMISSIONS_CONFIG['revert_votes']}  "
                 f"ban:{PERMISSIONS_CONFIG['ban_votes']}  "
                 f"cooldown:{PERMISSIONS_CONFIG['action_cooldown']}s  "
                 f"cmd-cooldown:{PERMISSIONS_CONFIG['global_command_cooldown']}s  "
                 f"{pct_note}")
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
            value=REALPC_CONFIG.get("failsafe", True))
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

    def _root_after_reconnect_poll(self):
        """Poll the bot's reconnect failure count and update the status label."""
        def _poll():
            try:
                from threading import enumerate as _tenum
                bot_threads = [t for t in _tenum() if t.name == "bot_main"]
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

    # ==================== MEDIA TABS + WEB DASHBOARD (ported from VMware build) ====================
    # ==================== MEDIA TABS: MUSIC / VIDEO / SOUNDBOARD (from chatuses.py) ====================
    def _build_music_tab(self, parent):
        try:
            wrapper = tk.Frame(parent, bg="#09090B")
            wrapper.pack(fill="both", expand=True, padx=20, pady=15)

            avail = []
            if not ytdlp_available: avail.append("yt-dlp not installed (pip install yt-dlp)")
            if not vlc_available: avail.append("python-vlc not installed (pip install python-vlc, and install VLC itself)")
            if avail:
                tk.Label(wrapper, text=" / ".join(avail), font=("Segoe UI", 9, "bold"), bg="#09090B", fg="#EF4444").pack(anchor="w", pady=(0, 8))

            # ---- top bar: title (left) + change-hours box (top right corner) ----
            top_bar = tk.Frame(wrapper, bg="#09090B")
            top_bar.pack(fill="x", pady=(0, 12))
            tk.Label(top_bar, text="MUSIC PANEL", font=("Segoe UI", 14, "bold"), bg="#09090B", fg=self.ACCENT).pack(side="left")

            def _music_apply_json(data):
                if isinstance(data, dict):
                    music_config.update(data)
                    save_music_config()
            hours_card = tk.Frame(top_bar, bg="#18181B", padx=12, pady=8, highlightthickness=1, highlightbackground="#27272A")
            hours_card.pack(side="right")
            tk.Label(hours_card, text="Music/Playlist Change Hours", font=("Segoe UI", 9, "bold"), bg="#18181B", fg="#D4D4D8").pack(side="left", padx=(0, 8))
            self.music_hours_entry = tk.Entry(hours_card, width=6, font=("Consolas", 11), bg="#09090B", fg="white", insertbackground="white", bd=0, highlightthickness=1, highlightbackground="#27272A", justify="center")
            self.music_hours_entry.pack(side="left", ipady=4, padx=(0, 8))
            self.music_hours_entry.insert(0, str(music_config.get("change_hours", 1)))
            def save_hours():
                try:
                    hrs = float(self.music_hours_entry.get())
                    if hrs <= 0: raise ValueError
                except Exception:
                    self._log("[err] change hours must be a positive number.")
                    return
                music_config["change_hours"] = hrs
                save_music_config()
                self._log(f"[info] music schedule will now advance every {hrs} hour(s).")
            tk.Button(hours_card, text="Save", font=("Segoe UI", 9, "bold"), bg="#10B981", fg="black", bd=0, cursor="hand2", command=save_hours).pack(side="left", ipady=4, ipadx=10)

            enable_row = tk.Frame(wrapper, bg="#09090B")
            enable_row.pack(fill="x", pady=(0, 12))
            self.var_music_enabled = tk.BooleanVar(value=music_config.get("enabled", False))
            def toggle_music_enabled():
                music_config["enabled"] = self.var_music_enabled.get()
                save_music_config()
                save_autostart_everything_config(music_playback_enabled=music_config["enabled"])
                if music_config["enabled"]:
                    start_music_player()
                    self._log("[info] music player enabled.")
                else:
                    stop_music_player()
                    self._log("[info] music player disabled.")
            ttk.Checkbutton(enable_row, text="Enable automatic music playback", variable=self.var_music_enabled, style="Toggle.TCheckbutton", command=toggle_music_enabled).pack(side="left")
            self.music_now_playing_lbl = tk.Label(enable_row, text=f"now playing: {music_current_desc or '(nothing)'}", font=("Segoe UI", 9), bg="#09090B", fg="#A1A1AA")
            self.music_now_playing_lbl.pack(side="right")

            controls_row = tk.Frame(wrapper, bg="#18181B", highlightthickness=1, highlightbackground="#27272A")
            controls_row.pack(fill="x", pady=(0, 12))
            tk.Label(controls_row, text="PLAYBACK CONTROLS", font=("Segoe UI", 9, "bold"), bg="#18181B", fg="#A1A1AA").pack(side="left", padx=10, pady=8)
            tk.Button(controls_row, text="▶ Play Selected Schedule", font=("Segoe UI", 9, "bold"), bg="#10B981", fg="black", bd=0, cursor="hand2",
                      command=lambda: self._music_play_selected_schedule()).pack(side="left", padx=4, ipady=5, ipadx=10)
            tk.Button(controls_row, text="⏭ Skip Track", font=("Segoe UI", 9, "bold"), bg="#27272A", fg="white", bd=0, cursor="hand2",
                      command=lambda: (music_skip_track(), self._log("[info] skipped to next track."))).pack(side="left", padx=4, ipady=5, ipadx=10)
            tk.Button(controls_row, text="⏸ Pause/Resume", font=("Segoe UI", 9, "bold"), bg="#27272A", fg="white", bd=0, cursor="hand2",
                      command=lambda: music_pause_toggle()).pack(side="left", padx=4, ipady=5, ipadx=10)
            tk.Button(controls_row, text="⏹ Stop", font=("Segoe UI", 9, "bold"), bg="#EF4444", fg="white", bd=0, cursor="hand2",
                      command=lambda: (stop_music_player(), self._log("[info] music stopped."))).pack(side="left", padx=4, ipady=5, ipadx=10)
            tk.Label(controls_row, text="Volume", font=("Segoe UI", 9, "bold"), bg="#18181B", fg="#D4D4D8").pack(side="left", padx=(20, 4))
            self.music_volume_scale = tk.Scale(controls_row, from_=0, to=100, orient="horizontal", length=140, bg="#18181B", fg="white",
                                                troughcolor="#09090B", highlightthickness=0, bd=0, showvalue=True,
                                                command=lambda v: music_set_volume(v))
            self.music_volume_scale.set(int(music_config.get("volume", 90)))
            self.music_volume_scale.pack(side="left", padx=(0, 10))

            # ---- main area: left = schedule column, right = 2 big boxes horizontally ----
            main_area = tk.Frame(wrapper, bg="#09090B")
            main_area.pack(fill="both", expand=True)

            # -- LEFT: schedule column (upper + bottom boxes) --
            left_col = tk.Frame(main_area, bg="#18181B", width=300, highlightthickness=1, highlightbackground="#27272A")
            left_col.pack(side="left", fill="y", padx=(0, 15))
            left_col.pack_propagate(False)

            tk.Label(left_col, text="MUSIC SCHEDULE (ORDER)", font=("Segoe UI", 10, "bold"), bg="#18181B", fg="#8B5CF6").pack(anchor="w", padx=10, pady=(10, 4))
            tk.Button(left_col, text="+ Add New Music Schedule", font=("Segoe UI", 9, "bold"), bg="#8B5CF6", fg="white", bd=0, cursor="hand2",
                      command=lambda: self._music_open_add_schedule_dialog()).pack(fill="x", padx=10, pady=(0, 8), ipady=6)

            # upper box: the ordered schedule list
            sched_upper_frame = tk.Frame(left_col, bg="#09090B", highlightthickness=1, highlightbackground="#27272A")
            sched_upper_frame.pack(fill="both", expand=True, padx=10, pady=(0, 6))
            self.music_schedule_listbox = tk.Listbox(sched_upper_frame, font=("Consolas", 9), bg="#09090B", fg=self.ACCENT, bd=0, highlightthickness=0, selectbackground="#27272A")
            self.music_schedule_listbox.pack(fill="both", expand=True, padx=4, pady=4)

            # bottom box: status / now-playing log
            tk.Label(left_col, text="STATUS / HISTORY", font=("Segoe UI", 9, "bold"), bg="#18181B", fg="#A1A1AA").pack(anchor="w", padx=10, pady=(4, 2))
            sched_lower_frame = tk.Frame(left_col, bg="#09090B", highlightthickness=1, highlightbackground="#27272A")
            sched_lower_frame.pack(fill="both", expand=True, padx=10, pady=(0, 6))
            self.music_status_listbox = tk.Listbox(sched_lower_frame, font=("Consolas", 9), bg="#09090B", fg="#A1A1AA", bd=0, highlightthickness=0)
            self.music_status_listbox.pack(fill="both", expand=True, padx=4, pady=4)

            sched_btn_row = tk.Frame(left_col, bg="#18181B")
            sched_btn_row.pack(fill="x", padx=10, pady=(0, 10))
            tk.Button(sched_btn_row, text="Save", font=("Segoe UI", 9, "bold"), bg="#10B981", fg="black", bd=0, cursor="hand2",
                      command=lambda: self._music_save_schedule()).pack(side="left", expand=True, fill="x", padx=(0, 4), ipady=6)
            tk.Button(sched_btn_row, text="Remove", font=("Segoe UI", 9, "bold"), bg="#EF4444", fg="white", bd=0, cursor="hand2",
                      command=lambda: self._music_remove_schedule_entry()).pack(side="left", expand=True, fill="x", padx=(4, 0), ipady=6)

            # -- RIGHT: two big boxes side by side horizontally (Musics / Playlists) --
            right_area = tk.Frame(main_area, bg="#09090B")
            right_area.pack(side="left", fill="both", expand=True)

            musics_box = tk.Frame(right_area, bg="#18181B", highlightthickness=1, highlightbackground="#27272A")
            musics_box.pack(side="left", fill="both", expand=True, padx=(0, 8))
            playlists_box = tk.Frame(right_area, bg="#18181B", highlightthickness=1, highlightbackground="#27272A")
            playlists_box.pack(side="left", fill="both", expand=True, padx=(8, 0))

            # Musics box
            tk.Label(musics_box, text="MUSICS (SINGLE TRACKS)", font=("Segoe UI", 10, "bold"), bg="#18181B", fg=self.ACCENT).pack(anchor="w", padx=10, pady=(10, 4))
            m_list_frame = tk.Frame(musics_box, bg="#09090B", highlightthickness=1, highlightbackground="#27272A")
            m_list_frame.pack(fill="both", expand=True, padx=10, pady=(0, 6))
            self.music_tracks_listbox = tk.Listbox(m_list_frame, font=("Consolas", 9), bg="#09090B", fg="white", bd=0, highlightthickness=0, selectbackground="#27272A")
            self.music_tracks_listbox.pack(fill="both", expand=True, padx=4, pady=4)
            m_btn_row = tk.Frame(musics_box, bg="#18181B")
            m_btn_row.pack(fill="x", padx=10, pady=(0, 10), anchor="w")
            tk.Button(m_btn_row, text="+ Add", font=("Segoe UI", 9, "bold"), bg="#10B981", fg="black", bd=0, cursor="hand2",
                      command=lambda: self._music_add_url("tracks")).pack(side="left", ipady=5, ipadx=14, padx=(0, 6))
            tk.Button(m_btn_row, text="✕ Remove Music", font=("Segoe UI", 9, "bold"), bg="#EF4444", fg="white", bd=0, cursor="hand2",
                      command=lambda: self._music_remove_url("tracks")).pack(side="left", ipady=5, ipadx=14)

            # Playlists box
            tk.Label(playlists_box, text="PLAYLISTS (SHUFFLE + LOOP)", font=("Segoe UI", 10, "bold"), bg="#18181B", fg="#F59E0B").pack(anchor="w", padx=10, pady=(10, 4))
            p_list_frame = tk.Frame(playlists_box, bg="#09090B", highlightthickness=1, highlightbackground="#27272A")
            p_list_frame.pack(fill="both", expand=True, padx=10, pady=(0, 6))
            self.music_playlists_listbox = tk.Listbox(p_list_frame, font=("Consolas", 9), bg="#09090B", fg="white", bd=0, highlightthickness=0, selectbackground="#27272A")
            self.music_playlists_listbox.pack(fill="both", expand=True, padx=4, pady=4)
            p_btn_row = tk.Frame(playlists_box, bg="#18181B")
            p_btn_row.pack(fill="x", padx=10, pady=(0, 10), anchor="w")
            tk.Button(p_btn_row, text="+ Add", font=("Segoe UI", 9, "bold"), bg="#10B981", fg="black", bd=0, cursor="hand2",
                      command=lambda: self._music_add_url("playlists")).pack(side="left", ipady=5, ipadx=14, padx=(0, 6))
            tk.Button(p_btn_row, text="✕ Remove Music", font=("Segoe UI", 9, "bold"), bg="#EF4444", fg="white", bd=0, cursor="hand2",
                      command=lambda: self._music_remove_url("playlists")).pack(side="left", ipady=5, ipadx=14)

            self._music_refresh_all_lists()
            self._music_poll_status()
        except Exception as e:
            self._log(f'[err] music tab build error: Python exception: "{traceback.format_exc()}"')

    def _music_play_selected_schedule(self):
        sel = self.music_schedule_listbox.curselection()
        sched = music_config.get("schedule", [])
        if not sched:
            messagebox.showinfo("music", "add a schedule entry first.")
            return
        item = sched[sel[0]] if sel else sched[0]
        if not music_config.get("enabled", False):
            self.var_music_enabled.set(True)
            music_config["enabled"] = True
            save_music_config()
            start_music_player()
        threading.Thread(target=lambda: music_play_url(item.get("url", ""), shuffle_loop=(item.get("type") == "playlist")), daemon=True).start()
        self._log(f"[info] manually playing schedule entry: {item.get('url')}")

    def _music_refresh_all_lists(self):
        self.music_tracks_listbox.delete(0, "end")
        for u in music_config.get("tracks", []): self.music_tracks_listbox.insert("end", u)
        self.music_playlists_listbox.delete(0, "end")
        for u in music_config.get("playlists", []): self.music_playlists_listbox.insert("end", u)
        self.music_schedule_listbox.delete(0, "end")
        for i, item in enumerate(music_config.get("schedule", []), 1):
            self.music_schedule_listbox.insert("end", f"{i}. [{item.get('type')}] {item.get('url')}")

    def _music_add_url(self, kind):
        url = _simpledialog.askstring("Add YouTube URL", f"Paste the YouTube {'video' if kind == 'tracks' else 'playlist'} URL:", parent=self.root)
        if not url or not url.strip(): return
        music_config.setdefault(kind, []).append(url.strip())
        save_music_config()
        self._music_refresh_all_lists()
        self._log(f"[info] added {kind[:-1]}: {url.strip()}")

    def _music_remove_url(self, kind):
        lb = self.music_tracks_listbox if kind == "tracks" else self.music_playlists_listbox
        sel = lb.curselection()
        if not sel: return
        items = music_config.get(kind, [])
        if sel[0] < len(items):
            removed = items.pop(sel[0])
            save_music_config()
            self._music_refresh_all_lists()
            self._log(f"[info] removed {kind[:-1]}: {removed}")

    def _music_open_add_schedule_dialog(self):
        if len(music_config.get("schedule", [])) >= MUSIC_SCHEDULE_MAX:
            messagebox.showinfo("music schedule", f"maximum of {MUSIC_SCHEDULE_MAX} schedule entries reached.")
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("Add New Music Schedule")
        dlg.configure(bg="#18181B")
        dlg.geometry("420x180")
        dlg.transient(self.root)
        tk.Label(dlg, text="Type", bg="#18181B", fg="#D4D4D8", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=15, pady=(15, 4))
        type_var = tk.StringVar(value="track")
        trow = tk.Frame(dlg, bg="#18181B"); trow.pack(anchor="w", padx=15)
        tk.Radiobutton(trow, text="Music (single track)", variable=type_var, value="track", bg="#18181B", fg="white", selectcolor="#09090B", activebackground="#18181B").pack(side="left", padx=(0, 10))
        tk.Radiobutton(trow, text="Playlist (shuffle+loop)", variable=type_var, value="playlist", bg="#18181B", fg="white", selectcolor="#09090B", activebackground="#18181B").pack(side="left")
        tk.Label(dlg, text="URL", bg="#18181B", fg="#D4D4D8", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=15, pady=(15, 4))
        url_cb = ttk.Combobox(dlg, width=45, font=("Consolas", 10))
        url_cb.pack(padx=15, fill="x")
        def refresh_choices(*_):
            src = music_config.get("tracks", []) if type_var.get() == "track" else music_config.get("playlists", [])
            url_cb["values"] = src
            if src: url_cb.set(src[0])
            else: url_cb.set("")
        type_var.trace_add("write", refresh_choices)
        refresh_choices()
        def confirm():
            url = url_cb.get().strip()
            if not url:
                messagebox.showwarning("music schedule", "pick or type a URL first (add it in the Musics/Playlists box below if it's not listed).")
                return
            music_config.setdefault("schedule", []).append({"type": type_var.get(), "url": url})
            save_music_config()
            self._music_refresh_all_lists()
            dlg.destroy()
        btnrow = tk.Frame(dlg, bg="#18181B"); btnrow.pack(pady=15)
        tk.Button(btnrow, text="Add to Schedule", font=("Segoe UI", 10, "bold"), bg="#8B5CF6", fg="white", bd=0, cursor="hand2", command=confirm).pack(side="left", ipady=5, ipadx=14, padx=(0, 8))
        tk.Button(btnrow, text="Cancel", font=("Segoe UI", 10, "bold"), bg="#27272A", fg="white", bd=0, cursor="hand2", command=dlg.destroy).pack(side="left", ipady=5, ipadx=14)

    def _music_remove_schedule_entry(self):
        sel = self.music_schedule_listbox.curselection()
        if not sel: return
        sched = music_config.get("schedule", [])
        if sel[0] < len(sched):
            removed = sched.pop(sel[0])
            save_music_config()
            self._music_refresh_all_lists()
            self._log(f"[info] removed schedule entry: {removed.get('url')}")

    def _music_save_schedule(self):
        # persists the current schedule order/hours (list itself is edited via add/remove)
        try:
            hrs = float(self.music_hours_entry.get())
            if hrs > 0: music_config["change_hours"] = hrs
        except Exception: pass
        save_music_config()
        self._log("[info] music schedule saved.")

    def _music_poll_status(self):
        try:
            if hasattr(self, "music_now_playing_lbl"):
                self.music_now_playing_lbl.config(text=f"now playing: {music_current_desc or '(nothing)'} — {music_status_text}")
            if hasattr(self, "music_status_listbox"):
                last = self.music_status_listbox.get(0) if self.music_status_listbox.size() else None
                if music_status_text and music_status_text != last:
                    self.music_status_listbox.insert(0, f"[{time.strftime('%H:%M:%S')}] {music_status_text}")
                    while self.music_status_listbox.size() > 50:
                        self.music_status_listbox.delete("end")
        except Exception: pass
        if (not bot_stop_event.is_set()): self.root.after(3000, self._music_poll_status)

    # ---------------- Video tab (yt-dlp + python-vlc, rendered into a movable window) ----------------
    def _build_video_tab(self, parent):
        try:
            wrapper = tk.Frame(parent, bg="#09090B")
            wrapper.pack(fill="both", expand=True, padx=20, pady=15)

            avail = []
            if not ytdlp_available: avail.append("yt-dlp not installed (pip install yt-dlp)")
            if not vlc_available: avail.append("python-vlc not installed (pip install python-vlc, and install VLC itself)")
            if avail:
                tk.Label(wrapper, text=" / ".join(avail), font=("Segoe UI", 9, "bold"), bg="#09090B", fg="#EF4444").pack(anchor="w", pady=(0, 8))

            # ---- top bar: title (left) + change-hours box (top right corner) ----
            top_bar = tk.Frame(wrapper, bg="#09090B")
            top_bar.pack(fill="x", pady=(0, 12))
            tk.Label(top_bar, text="VIDEO PANEL", font=("Segoe UI", 14, "bold"), bg="#09090B", fg=self.ACCENT).pack(side="left")

            def _video_apply_json(data):
                if isinstance(data, dict):
                    video_config.update(data)
                    save_video_config()
            hours_card = tk.Frame(top_bar, bg="#18181B", padx=12, pady=8, highlightthickness=1, highlightbackground="#27272A")
            hours_card.pack(side="right")
            tk.Label(hours_card, text="Video/Playlist Change Hours", font=("Segoe UI", 9, "bold"), bg="#18181B", fg="#D4D4D8").pack(side="left", padx=(0, 8))
            self.video_hours_entry = tk.Entry(hours_card, width=6, font=("Consolas", 11), bg="#09090B", fg="white", insertbackground="white", bd=0, highlightthickness=1, highlightbackground="#27272A", justify="center")
            self.video_hours_entry.pack(side="left", ipady=4, padx=(0, 8))
            self.video_hours_entry.insert(0, str(video_config.get("change_hours", 1)))
            def save_hours():
                try:
                    hrs = float(self.video_hours_entry.get())
                    if hrs <= 0: raise ValueError
                except Exception:
                    self._log("[err] change hours must be a positive number.")
                    return
                video_config["change_hours"] = hrs
                save_video_config()
                self._log(f"[info] video schedule will now advance every {hrs} hour(s).")
            tk.Button(hours_card, text="Save", font=("Segoe UI", 9, "bold"), bg="#10B981", fg="black", bd=0, cursor="hand2", command=save_hours).pack(side="left", ipady=4, ipadx=10)

            enable_row = tk.Frame(wrapper, bg="#09090B")
            enable_row.pack(fill="x", pady=(0, 12))
            self.var_video_enabled = tk.BooleanVar(value=video_config.get("enabled", False))
            def toggle_video_enabled():
                video_config["enabled"] = self.var_video_enabled.get()
                save_video_config()
                save_autostart_everything_config(video_playback_enabled=video_config["enabled"])
                if video_config["enabled"]:
                    start_video_player()
                    self._log("[info] video player enabled.")
                else:
                    stop_video_player()
                    self._log("[info] video player disabled.")
            ttk.Checkbutton(enable_row, text="Enable automatic video playback", variable=self.var_video_enabled, style="Toggle.TCheckbutton", command=toggle_video_enabled).pack(side="left")
            self.video_now_playing_lbl = tk.Label(enable_row, text=f"now playing: {video_current_desc or '(nothing)'}", font=("Segoe UI", 9), bg="#09090B", fg="#A1A1AA")
            self.video_now_playing_lbl.pack(side="right")

            controls_row = tk.Frame(wrapper, bg="#18181B", highlightthickness=1, highlightbackground="#27272A")
            controls_row.pack(fill="x", pady=(0, 12))
            tk.Label(controls_row, text="PLAYBACK CONTROLS", font=("Segoe UI", 9, "bold"), bg="#18181B", fg="#A1A1AA").pack(side="left", padx=10, pady=8)
            tk.Button(controls_row, text="▶ Play Selected Schedule", font=("Segoe UI", 9, "bold"), bg="#10B981", fg="black", bd=0, cursor="hand2",
                      command=lambda: self._video_play_selected_schedule()).pack(side="left", padx=4, ipady=5, ipadx=10)
            tk.Button(controls_row, text="⏭ Skip Clip", font=("Segoe UI", 9, "bold"), bg="#27272A", fg="white", bd=0, cursor="hand2",
                      command=lambda: (video_skip_track(), self._log("[info] skipped to next clip."))).pack(side="left", padx=4, ipady=5, ipadx=10)
            tk.Button(controls_row, text="⏸ Pause/Resume", font=("Segoe UI", 9, "bold"), bg="#27272A", fg="white", bd=0, cursor="hand2",
                      command=lambda: video_pause_toggle()).pack(side="left", padx=4, ipady=5, ipadx=10)
            tk.Button(controls_row, text="⏹ Stop", font=("Segoe UI", 9, "bold"), bg="#EF4444", fg="white", bd=0, cursor="hand2",
                      command=lambda: (stop_video_player(), self._log("[info] video stopped."))).pack(side="left", padx=4, ipady=5, ipadx=10)
            tk.Button(controls_row, text="🗗 Show Window", font=("Segoe UI", 9, "bold"), bg="#27272A", fg="white", bd=0, cursor="hand2",
                      command=lambda: self.ensure_video_window()).pack(side="left", padx=4, ipady=5, ipadx=10)
            self.var_video_ontop = tk.BooleanVar(value=video_config.get("always_on_top", False))
            def toggle_video_ontop():
                video_config["always_on_top"] = self.var_video_ontop.get()
                save_video_config()
                try:
                    if getattr(self, "video_toplevel", None) and self.video_toplevel.winfo_exists():
                        self.video_toplevel.attributes("-topmost", video_config["always_on_top"])
                except Exception: pass
            ttk.Checkbutton(controls_row, text="Always on top", variable=self.var_video_ontop, style="Toggle.TCheckbutton", command=toggle_video_ontop).pack(side="left", padx=(10, 4))
            tk.Label(controls_row, text="Volume", font=("Segoe UI", 9, "bold"), bg="#18181B", fg="#D4D4D8").pack(side="left", padx=(20, 4))
            self.video_volume_scale = tk.Scale(controls_row, from_=0, to=100, orient="horizontal", length=140, bg="#18181B", fg="white",
                                                troughcolor="#09090B", highlightthickness=0, bd=0, showvalue=True,
                                                command=lambda v: video_set_volume(v))
            self.video_volume_scale.set(int(video_config.get("volume", 90)))
            self.video_volume_scale.pack(side="left", padx=(0, 10))

            # ---- main area: left = schedule column, right = 2 big boxes horizontally ----
            main_area = tk.Frame(wrapper, bg="#09090B")
            main_area.pack(fill="both", expand=True)

            # -- LEFT: schedule column (upper + bottom boxes) --
            left_col = tk.Frame(main_area, bg="#18181B", width=300, highlightthickness=1, highlightbackground="#27272A")
            left_col.pack(side="left", fill="y", padx=(0, 15))
            left_col.pack_propagate(False)

            tk.Label(left_col, text="VIDEO SCHEDULE (ORDER)", font=("Segoe UI", 10, "bold"), bg="#18181B", fg="#8B5CF6").pack(anchor="w", padx=10, pady=(10, 4))
            tk.Button(left_col, text="+ Add New Video Schedule", font=("Segoe UI", 9, "bold"), bg="#8B5CF6", fg="white", bd=0, cursor="hand2",
                      command=lambda: self._video_open_add_schedule_dialog()).pack(fill="x", padx=10, pady=(0, 8), ipady=6)

            # upper box: the ordered schedule list
            sched_upper_frame = tk.Frame(left_col, bg="#09090B", highlightthickness=1, highlightbackground="#27272A")
            sched_upper_frame.pack(fill="both", expand=True, padx=10, pady=(0, 6))
            self.video_schedule_listbox = tk.Listbox(sched_upper_frame, font=("Consolas", 9), bg="#09090B", fg=self.ACCENT, bd=0, highlightthickness=0, selectbackground="#27272A")
            self.video_schedule_listbox.pack(fill="both", expand=True, padx=4, pady=4)

            # bottom box: status / now-playing log
            tk.Label(left_col, text="STATUS / HISTORY", font=("Segoe UI", 9, "bold"), bg="#18181B", fg="#A1A1AA").pack(anchor="w", padx=10, pady=(4, 2))
            sched_lower_frame = tk.Frame(left_col, bg="#09090B", highlightthickness=1, highlightbackground="#27272A")
            sched_lower_frame.pack(fill="both", expand=True, padx=10, pady=(0, 6))
            self.video_status_listbox = tk.Listbox(sched_lower_frame, font=("Consolas", 9), bg="#09090B", fg="#A1A1AA", bd=0, highlightthickness=0)
            self.video_status_listbox.pack(fill="both", expand=True, padx=4, pady=4)

            sched_btn_row = tk.Frame(left_col, bg="#18181B")
            sched_btn_row.pack(fill="x", padx=10, pady=(0, 10))
            tk.Button(sched_btn_row, text="Save", font=("Segoe UI", 9, "bold"), bg="#10B981", fg="black", bd=0, cursor="hand2",
                      command=lambda: self._video_save_schedule()).pack(side="left", expand=True, fill="x", padx=(0, 4), ipady=6)
            tk.Button(sched_btn_row, text="Remove", font=("Segoe UI", 9, "bold"), bg="#EF4444", fg="white", bd=0, cursor="hand2",
                      command=lambda: self._video_remove_schedule_entry()).pack(side="left", expand=True, fill="x", padx=(4, 0), ipady=6)

            # -- RIGHT: two big boxes side by side horizontally (Videos / Playlists) --
            right_area = tk.Frame(main_area, bg="#09090B")
            right_area.pack(side="left", fill="both", expand=True)

            videos_box = tk.Frame(right_area, bg="#18181B", highlightthickness=1, highlightbackground="#27272A")
            videos_box.pack(side="left", fill="both", expand=True, padx=(0, 8))
            playlists_box = tk.Frame(right_area, bg="#18181B", highlightthickness=1, highlightbackground="#27272A")
            playlists_box.pack(side="left", fill="both", expand=True, padx=(8, 0))

            # Videos box
            tk.Label(videos_box, text="VIDEOS (SINGLE CLIPS)", font=("Segoe UI", 10, "bold"), bg="#18181B", fg=self.ACCENT).pack(anchor="w", padx=10, pady=(10, 4))
            v_list_frame = tk.Frame(videos_box, bg="#09090B", highlightthickness=1, highlightbackground="#27272A")
            v_list_frame.pack(fill="both", expand=True, padx=10, pady=(0, 6))
            self.video_tracks_listbox = tk.Listbox(v_list_frame, font=("Consolas", 9), bg="#09090B", fg="white", bd=0, highlightthickness=0, selectbackground="#27272A")
            self.video_tracks_listbox.pack(fill="both", expand=True, padx=4, pady=4)
            v_btn_row = tk.Frame(videos_box, bg="#18181B")
            v_btn_row.pack(fill="x", padx=10, pady=(0, 10), anchor="w")
            tk.Button(v_btn_row, text="+ Add", font=("Segoe UI", 9, "bold"), bg="#10B981", fg="black", bd=0, cursor="hand2",
                      command=lambda: self._video_add_url("tracks")).pack(side="left", ipady=5, ipadx=14, padx=(0, 6))
            tk.Button(v_btn_row, text="✕ Remove Video", font=("Segoe UI", 9, "bold"), bg="#EF4444", fg="white", bd=0, cursor="hand2",
                      command=lambda: self._video_remove_url("tracks")).pack(side="left", ipady=5, ipadx=14)

            # Playlists box
            tk.Label(playlists_box, text="PLAYLISTS (SHUFFLE + LOOP)", font=("Segoe UI", 10, "bold"), bg="#18181B", fg="#F59E0B").pack(anchor="w", padx=10, pady=(10, 4))
            p_list_frame = tk.Frame(playlists_box, bg="#09090B", highlightthickness=1, highlightbackground="#27272A")
            p_list_frame.pack(fill="both", expand=True, padx=10, pady=(0, 6))
            self.video_playlists_listbox = tk.Listbox(p_list_frame, font=("Consolas", 9), bg="#09090B", fg="white", bd=0, highlightthickness=0, selectbackground="#27272A")
            self.video_playlists_listbox.pack(fill="both", expand=True, padx=4, pady=4)
            p_btn_row = tk.Frame(playlists_box, bg="#18181B")
            p_btn_row.pack(fill="x", padx=10, pady=(0, 10), anchor="w")
            tk.Button(p_btn_row, text="+ Add", font=("Segoe UI", 9, "bold"), bg="#10B981", fg="black", bd=0, cursor="hand2",
                      command=lambda: self._video_add_url("playlists")).pack(side="left", ipady=5, ipadx=14, padx=(0, 6))
            tk.Button(p_btn_row, text="✕ Remove Video", font=("Segoe UI", 9, "bold"), bg="#EF4444", fg="white", bd=0, cursor="hand2",
                      command=lambda: self._video_remove_url("playlists")).pack(side="left", ipady=5, ipadx=14)

            self._video_refresh_all_lists()
            self._video_poll_status()
        except Exception as e:
            self._log(f'[err] video tab build error: Python exception: "{traceback.format_exc()}"')

    # ---- the actual movable window the video is rendered into ----
    def ensure_video_window(self):
        try:
            if getattr(self, "video_toplevel", None) is not None and self.video_toplevel.winfo_exists():
                self.video_toplevel.deiconify()
                self.video_toplevel.lift()
                return
            win = tk.Toplevel(self.root)
            win.title(f"Video Panel - {video_current_desc}" if video_current_desc else "Video Panel")
            w = int(video_config.get("window_w", 640) or 640)
            h = int(video_config.get("window_h", 360) or 360)
            x, y = video_config.get("window_x"), video_config.get("window_y")
            win.geometry(f"{w}x{h}+{int(x)}+{int(y)}" if x is not None and y is not None else f"{w}x{h}")
            win.configure(bg="black")
            win.minsize(160, 90)
            try: win.attributes("-topmost", bool(video_config.get("always_on_top", False)))
            except Exception: pass
            canvas = tk.Frame(win, bg="black")
            canvas.pack(fill="both", expand=True)
            self.video_toplevel = win
            self.video_canvas = canvas
            win.bind("<Configure>", lambda e: self._video_save_geometry_debounced() if e.widget is win else None)
            win.protocol("WM_DELETE_WINDOW", self._on_video_window_close)
        except Exception as e:
            self._log(f"[err] couldn't open video window: Python exception: \"{traceback.format_exc()}\"")

    def set_video_window_title(self, desc):
        try:
            if getattr(self, "video_toplevel", None) and self.video_toplevel.winfo_exists():
                self.video_toplevel.title(f"Video Panel - {desc}" if desc else "Video Panel")
        except Exception: pass

    def _video_save_geometry_debounced(self):
        if getattr(self, "_video_geom_after_id", None):
            try: self.root.after_cancel(self._video_geom_after_id)
            except Exception: pass
        self._video_geom_after_id = self.root.after(500, self._video_save_geometry_now)

    def _video_save_geometry_now(self):
        try:
            if getattr(self, "video_toplevel", None) and self.video_toplevel.winfo_exists():
                video_config["window_x"] = self.video_toplevel.winfo_x()
                video_config["window_y"] = self.video_toplevel.winfo_y()
                video_config["window_w"] = self.video_toplevel.winfo_width()
                video_config["window_h"] = self.video_toplevel.winfo_height()
                save_video_config()
        except Exception: pass

    def _on_video_window_close(self):
        # closing the window stops the clip -- a video with nowhere to render into makes no
        # sense, unlike Music which is happy to keep playing audio-only in the background.
        try: self._video_save_geometry_now()
        except Exception: pass
        try: self.video_toplevel.destroy()
        except Exception: pass
        self.video_toplevel = None
        self.video_canvas = None
        threading.Thread(target=video_stop_current, daemon=True).start()
        self._log("[info] video window closed, playback stopped.")

    def _video_play_selected_schedule(self):
        sel = self.video_schedule_listbox.curselection()
        sched = video_config.get("schedule", [])
        if not sched:
            messagebox.showinfo("video", "add a schedule entry first.")
            return
        item = sched[sel[0]] if sel else sched[0]
        if not video_config.get("enabled", False):
            self.var_video_enabled.set(True)
            video_config["enabled"] = True
            save_video_config()
            start_video_player()
        threading.Thread(target=lambda: video_play_url(item.get("url", ""), shuffle_loop=(item.get("type") == "playlist")), daemon=True).start()
        self._log(f"[info] manually playing schedule entry: {item.get('url')}")

    def _video_refresh_all_lists(self):
        self.video_tracks_listbox.delete(0, "end")
        for u in video_config.get("tracks", []): self.video_tracks_listbox.insert("end", u)
        self.video_playlists_listbox.delete(0, "end")
        for u in video_config.get("playlists", []): self.video_playlists_listbox.insert("end", u)
        self.video_schedule_listbox.delete(0, "end")
        for i, item in enumerate(video_config.get("schedule", []), 1):
            self.video_schedule_listbox.insert("end", f"{i}. [{item.get('type')}] {item.get('url')}")

    def _video_add_url(self, kind):
        url = _simpledialog.askstring("Add YouTube URL", f"Paste the YouTube {'video' if kind == 'tracks' else 'playlist'} URL:", parent=self.root)
        if not url or not url.strip(): return
        video_config.setdefault(kind, []).append(url.strip())
        save_video_config()
        self._video_refresh_all_lists()
        self._log(f"[info] added {kind[:-1]}: {url.strip()}")

    def _video_remove_url(self, kind):
        lb = self.video_tracks_listbox if kind == "tracks" else self.video_playlists_listbox
        sel = lb.curselection()
        if not sel: return
        items = video_config.get(kind, [])
        if sel[0] < len(items):
            removed = items.pop(sel[0])
            save_video_config()
            self._video_refresh_all_lists()
            self._log(f"[info] removed {kind[:-1]}: {removed}")

    def _video_open_add_schedule_dialog(self):
        if len(video_config.get("schedule", [])) >= VIDEO_SCHEDULE_MAX:
            messagebox.showinfo("video schedule", f"maximum of {VIDEO_SCHEDULE_MAX} schedule entries reached.")
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("Add New Video Schedule")
        dlg.configure(bg="#18181B")
        dlg.geometry("420x180")
        dlg.transient(self.root)
        tk.Label(dlg, text="Type", bg="#18181B", fg="#D4D4D8", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=15, pady=(15, 4))
        type_var = tk.StringVar(value="track")
        trow = tk.Frame(dlg, bg="#18181B"); trow.pack(anchor="w", padx=15)
        tk.Radiobutton(trow, text="Video (single clip)", variable=type_var, value="track", bg="#18181B", fg="white", selectcolor="#09090B", activebackground="#18181B").pack(side="left", padx=(0, 10))
        tk.Radiobutton(trow, text="Playlist (shuffle+loop)", variable=type_var, value="playlist", bg="#18181B", fg="white", selectcolor="#09090B", activebackground="#18181B").pack(side="left")
        tk.Label(dlg, text="URL", bg="#18181B", fg="#D4D4D8", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=15, pady=(15, 4))
        url_cb = ttk.Combobox(dlg, width=45, font=("Consolas", 10))
        url_cb.pack(padx=15, fill="x")
        def refresh_choices(*_):
            src = video_config.get("tracks", []) if type_var.get() == "track" else video_config.get("playlists", [])
            url_cb["values"] = src
            if src: url_cb.set(src[0])
            else: url_cb.set("")
        type_var.trace_add("write", refresh_choices)
        refresh_choices()
        def confirm():
            url = url_cb.get().strip()
            if not url:
                messagebox.showwarning("video schedule", "pick or type a URL first (add it in the Videos/Playlists box below if it's not listed).")
                return
            video_config.setdefault("schedule", []).append({"type": type_var.get(), "url": url})
            save_video_config()
            self._video_refresh_all_lists()
            dlg.destroy()
        btnrow = tk.Frame(dlg, bg="#18181B"); btnrow.pack(pady=15)
        tk.Button(btnrow, text="Add to Schedule", font=("Segoe UI", 10, "bold"), bg="#8B5CF6", fg="white", bd=0, cursor="hand2", command=confirm).pack(side="left", ipady=5, ipadx=14, padx=(0, 8))
        tk.Button(btnrow, text="Cancel", font=("Segoe UI", 10, "bold"), bg="#27272A", fg="white", bd=0, cursor="hand2", command=dlg.destroy).pack(side="left", ipady=5, ipadx=14)

    def _video_remove_schedule_entry(self):
        sel = self.video_schedule_listbox.curselection()
        if not sel: return
        sched = video_config.get("schedule", [])
        if sel[0] < len(sched):
            removed = sched.pop(sel[0])
            save_video_config()
            self._video_refresh_all_lists()
            self._log(f"[info] removed schedule entry: {removed.get('url')}")

    def _video_save_schedule(self):
        # persists the current schedule order/hours (list itself is edited via add/remove)
        try:
            hrs = float(self.video_hours_entry.get())
            if hrs > 0: video_config["change_hours"] = hrs
        except Exception: pass
        save_video_config()
        self._log("[info] video schedule saved.")

    def _video_poll_status(self):
        try:
            if hasattr(self, "video_now_playing_lbl"):
                self.video_now_playing_lbl.config(text=f"now playing: {video_current_desc or '(nothing)'} — {video_status_text}")
            if hasattr(self, "video_status_listbox"):
                last = self.video_status_listbox.get(0) if self.video_status_listbox.size() else None
                if video_status_text and video_status_text != last:
                    self.video_status_listbox.insert(0, f"[{time.strftime('%H:%M:%S')}] {video_status_text}")
                    while self.video_status_listbox.size() > 50:
                        self.video_status_listbox.delete("end")
        except Exception: pass
        if (not bot_stop_event.is_set()): self.root.after(3000, self._video_poll_status)

    # ---------------- Soundboard tab (web search only via python-vlc) ----------------
    def _build_soundboard_tab(self, parent):
        try:
            wrapper = tk.Frame(parent, bg="#09090B")
            wrapper.pack(fill="both", expand=True, padx=20, pady=15)

            if not vlc_available:
                tk.Label(wrapper, text="python-vlc not installed (pip install python-vlc, and install VLC itself)", font=("Segoe UI", 9, "bold"), bg="#09090B", fg="#EF4444").pack(anchor="w", pady=(0, 8))

            top_bar = tk.Frame(wrapper, bg="#09090B")
            top_bar.pack(fill="x", pady=(0, 12))
            tk.Label(top_bar, text="SOUNDBOARD PANEL", font=("Segoe UI", 14, "bold"), bg="#09090B", fg=self.ACCENT).pack(side="left")
            tk.Label(top_bar, text="Web search only (myinstants.com) -- no local files.", font=("Segoe UI", 9), bg="#09090B", fg="#71717A").pack(side="left", padx=(12, 0))

            def _sb_apply_json(data):
                if isinstance(data, dict):
                    soundboard_config.update(data)
                    save_soundboard_config()
            self.sb_status_lbl = tk.Label(wrapper, text=f"status: {soundboard_status_text}", font=("Segoe UI", 9), bg="#09090B", fg="#A1A1AA")
            self.sb_status_lbl.pack(anchor="w", pady=(0, 12))

            web_row = tk.Frame(wrapper, bg="#18181B", highlightthickness=1, highlightbackground="#27272A")
            web_row.pack(fill="x", pady=(0, 12))
            tk.Label(web_row, text="WEB SEARCH (!sb)", font=("Segoe UI", 9, "bold"), bg="#18181B", fg="#F59E0B").pack(side="left", padx=10, pady=8)
            self.sb_web_search_entry = tk.Entry(web_row, width=30, font=("Consolas", 10), bg="#09090B", fg="white", insertbackground="white", bd=0, highlightthickness=1, highlightbackground="#27272A")
            self.sb_web_search_entry.pack(side="left", ipady=5, padx=(0, 8))
            def do_web_search_test():
                term = self.sb_web_search_entry.get().strip()
                if not term: return
                self._log(f"[info] searching myinstants for '{term}'...")
                def _run():
                    ok, info = soundboard_web_search_and_play(term)
                    if ok: self._log(f"[info] played web result: {info}")
                    else: self._log(f"[err] web search failed: {info}")
                threading.Thread(target=_run, daemon=True).start()
            self.sb_web_search_entry.bind("<Return>", lambda e: do_web_search_test())
            tk.Button(web_row, text="Search & Play 1st Result", font=("Segoe UI", 9, "bold"), bg="#F59E0B", fg="black", bd=0, cursor="hand2", command=do_web_search_test).pack(side="left", ipady=5, ipadx=10)
            tk.Label(web_row, text="Same lookup chat's !sb <term> uses -- results are cached to soundboard_web_cache/.", font=("Segoe UI", 8), bg="#18181B", fg="#71717A").pack(side="left", padx=(12, 0))

            controls_row = tk.Frame(wrapper, bg="#18181B", highlightthickness=1, highlightbackground="#27272A")
            controls_row.pack(fill="x", pady=(0, 12))
            tk.Label(controls_row, text="PLAYBACK CONTROLS", font=("Segoe UI", 9, "bold"), bg="#18181B", fg="#A1A1AA").pack(side="left", padx=10, pady=8)
            tk.Button(controls_row, text="⏹ Stop All", font=("Segoe UI", 9, "bold"), bg="#EF4444", fg="white", bd=0, cursor="hand2",
                      command=lambda: (soundboard_stop_all(), self._log("[info] stopped all soundboard clips."))).pack(side="left", padx=4, ipady=5, ipadx=10)
            tk.Label(controls_row, text="Volume", font=("Segoe UI", 9, "bold"), bg="#18181B", fg="#D4D4D8").pack(side="left", padx=(20, 4))
            self.sb_volume_scale = tk.Scale(controls_row, from_=0, to=100, orient="horizontal", length=140, bg="#18181B", fg="white",
                                             troughcolor="#09090B", highlightthickness=0, bd=0, showvalue=True,
                                             command=lambda v: soundboard_set_volume(v))
            self.sb_volume_scale.set(int(soundboard_config.get("volume", 90)))
            self.sb_volume_scale.pack(side="left", padx=(0, 10))

            status_box = tk.Frame(wrapper, bg="#18181B", highlightthickness=1, highlightbackground="#27272A")
            status_box.pack(fill="both", expand=True)
            tk.Label(status_box, text="STATUS / HISTORY", font=("Segoe UI", 9, "bold"), bg="#18181B", fg="#A1A1AA").pack(anchor="w", padx=10, pady=(10, 4))
            st_list_frame = tk.Frame(status_box, bg="#09090B", highlightthickness=1, highlightbackground="#27272A")
            st_list_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
            self.sb_status_listbox = tk.Listbox(st_list_frame, font=("Consolas", 9), bg="#09090B", fg="#A1A1AA", bd=0, highlightthickness=0)
            self.sb_status_listbox.pack(fill="both", expand=True, padx=4, pady=4)

            self._sb_poll_status()
        except Exception as e:
            self._log(f'[err] soundboard tab build error: Python exception: "{traceback.format_exc()}"')

    def _sb_poll_status(self):
        try:
            if hasattr(self, "sb_status_lbl"):
                self.sb_status_lbl.config(text=f"status: {soundboard_status_text}")
            if hasattr(self, "sb_status_listbox"):
                last = self.sb_status_listbox.get(0) if self.sb_status_listbox.size() else None
                if soundboard_status_text and soundboard_status_text != last:
                    self.sb_status_listbox.insert(0, f"[{time.strftime('%H:%M:%S')}] {soundboard_status_text}")
                    while self.sb_status_listbox.size() > 50:
                        self.sb_status_listbox.delete("end")
        except Exception: pass
        if (not bot_stop_event.is_set()): self.root.after(2000, self._sb_poll_status)



    def _build_web_tab(self, parent):
        parent.configure(style="TFrame")

        hdr = tk.Frame(parent, bg=self.BG)
        hdr.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(hdr, text="\U0001F310  Multistream Web Dashboard",
                 bg=self.BG, fg=self.ACCENT,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w")
        tk.Label(hdr,
                 text="Runs the web dashboard (all the OBS/browser overlay pages, mixed in from "
                      "the VMware build, on one port) -- chat overlay, Now Playing, stats, etc.",
                 bg=self.BG, fg=self.TEXTDIM, font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))

        # ── Web / Multistream dashboard card ──
        web_card = ttk.Frame(parent, style="Card.TFrame", padding=14)
        web_card.pack(fill="x", padx=12, pady=(8, 8))
        tk.Label(web_card, text="Multistream Web Dashboard", bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        tk.Label(web_card,
                 text="Serves every OBS/browser overlay page on one port.",
                 bg=self.BG2, fg=self.TEXTDIM, font=("Segoe UI", 8)).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 8))

        tk.Label(web_card, text="Flask Port (5900-5999):", bg=self.BG2, fg=self.TEXTDIM,
                  font=("Segoe UI", 9)).grid(row=2, column=0, sticky="w", pady=4)
        self._flask_port_var = tk.StringVar(value=str(FLASK_CONFIG.get("port", 5900)))
        ttk.Entry(web_card, textvariable=self._flask_port_var, width=10,
                   font=("Segoe UI Mono", 10)).grid(row=2, column=1, sticky="w", padx=(8, 0), ipady=3)

        web_btn_row = tk.Frame(web_card, bg=self.BG2)
        web_btn_row.grid(row=3, column=0, columnspan=3, sticky="w", pady=(10, 0))
        ttk.Button(web_btn_row, text="\u25b6 Start", style="Green.TButton",
                   command=self._flask_start_clicked).pack(side="left", padx=(0, 8))
        ttk.Button(web_btn_row, text="\u23f9 Stop", style="Red.TButton",
                   command=self._flask_stop_clicked).pack(side="left", padx=(0, 8))
        ttk.Button(web_btn_row, text="\U0001F310 Open", style="Dim.TButton",
                   command=self._flask_open_clicked).pack(side="left")

        self._flask_status_lbl = tk.Label(web_card, text="", bg=self.BG2, fg=self.TEXTDIM,
                                          font=("Segoe UI", 8, "italic"))
        self._flask_status_lbl.grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self._flask_refresh_status()

    def _flask_refresh_status(self):
        try:
            procs = getattr(self, "_flask_spawned_procs", {})
            alive = {p: proc for p, proc in procs.items() if proc.poll() is None}
            self._flask_spawned_procs = alive
            if alive:
                ports = ", ".join(str(p) for p in sorted(alive))
                self._flask_status_lbl.configure(text=f"Running (spawned instance) on port(s): {ports}.")
            else:
                self._flask_status_lbl.configure(text="Stopped.")
        except Exception:
            pass

    def _flask_start_clicked(self):
        try:
            port = int(self._flask_port_var.get().strip())
        except Exception:
            messagebox.showerror("Web Dashboard", "Port must be a number.")
            return
        if not (5900 <= port <= 5999):
            messagebox.showerror("Web Dashboard", "Port must be between 5900 and 5999.")
            return
        FLASK_CONFIG["port"] = port
        save_flask_config()
        self._flask_status_lbl.configure(text=f"Launching new instance on port {port}...")

        def _do_spawn():
            ok, result = spawn_flask_multistream(port)
            if ok:
                if not hasattr(self, "_flask_spawned_procs"):
                    self._flask_spawned_procs = {}
                self._flask_spawned_procs[port] = result
                self.root.after(0, lambda: self._log(
                    f"[WebDashboard] Spawned new instance on port {port} "
                    f"(a new script window will open and auto-launch the dashboard)."))
            else:
                self.root.after(0, lambda: messagebox.showerror("Web Dashboard", str(result)))
            self.root.after(1500, self._flask_refresh_status)

        threading.Thread(target=_do_spawn, daemon=True).start()

    def _flask_stop_clicked(self):
        try:
            port = int(self._flask_port_var.get().strip())
        except Exception:
            port = None
        procs = getattr(self, "_flask_spawned_procs", {})
        if port is not None and port in procs:
            try:
                procs[port].terminate()
                self._log(f"[WebDashboard] Stopped spawned instance on port {port}.")
            except Exception as e:
                self._log(f"[WebDashboard] Couldn't stop port {port}: Python exception: \"{traceback.format_exc()}\"")
            procs.pop(port, None)
        else:
            self._log("[WebDashboard] No tracked spawned instance on that port "
                       "(close its window/process directly).")
        self._flask_refresh_status()

    def _flask_open_clicked(self):
        try:
            port = int(self._flask_port_var.get().strip())
        except Exception:
            port = FLASK_CONFIG.get("port", 5900)
        open_flask_dashboard(port)
        self._log(f"[WebDashboard] Opened http://localhost:{port}/")



    def show_welcome_guide(self, force=False):
        if not force and os.path.exists(self.GUIDE_FLAG_FILE):
            return

        W, H = 800, 560
        dlg = tk.Toplevel(self.root)
        dlg.title("📖  UltraBot — User Guide")
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
        tk.Label(hdr, text="📖  UltraBot Control Panel — User Guide",
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
                ("body", "Welcome to UltraBot! This guide explains every feature so you can hit the ground running."),
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
            ("🎵  Music / Video / Soundboard", [
                ("h1",   "🎵  Music / Video / Soundboard"),
                ("body", "A full VLC + yt-dlp powered media engine, independent of the VM -- plays through the host's speakers/screen, not inside the guest."),
                ("h2",   "Music (song requests)"),
                ("code", "  !sr <url or search>   →  queue a song (also: !play, !music, !songrequest)"),
                ("code", "  !findsr <search term> →  searches YouTube and queues the 1st result"),
                ("code", "  !musicskip            →  skip the current track (also: !skipsong, !skipmusic)"),
                ("code", "  !stopmusic            →  stop playback entirely"),
                ("code", "  !musicpause           →  pause / resume"),
                ("code", "  !musicvolume 80       →  set volume 0-100"),
                ("code", "  !srqueue              →  posts the pending song queue to the overlay"),
                ("code", "  !skipsr   (mod only)  →  skip AND drop the next queued request"),
                ("code", "  !clearsr  (mod only)  →  wipe the entire pending song queue"),
                ("h2",   "Video requests"),
                ("body", "Same pattern as music, but opens a movable on-screen video window instead of playing audio only."),
                ("code", "  !vr <url or search>   →  queue a video (also: !video, !videorequest)"),
                ("code", "  !findvr <search term> →  searches YouTube and queues the 1st result"),
                ("code", "  !videoskip            →  skip current clip (also: !skipvideo, !vskip)"),
                ("code", "  !stopvideo / !videopause / !videovolume 80"),
                ("code", "  !vrqueue              →  posts the pending video queue to the overlay"),
                ("code", "  !skipvr / !clearvr    →  (mod only) same as the music equivalents"),
                ("h2",   "Soundboard"),
                ("body", "Web-search based -- no local sound files needed. Searches myinstants.com and plays the result, cached on disk for instant repeats."),
                ("code", "  !sb <search term>     →  search & play (also: !soundboard)"),
                ("code", "  !sbid <myinstants id> →  play an exact sound by its myinstants.com ID"),
                ("code", "  !sbstop               →  stop all currently playing sounds"),
                ("code", "  !sbvolume 90          →  set soundboard volume 0-100"),
                ("h2",   "Setup"),
                ("body", "Enable each player and set its schedule/config from the  🎵 Music,  🎬 Video, and  🔉 Soundboard  tabs. Requires  python-vlc  (+ VLC itself installed) and  yt-dlp."),
                ("tip",  "Tip: requests are queued, not interrupting -- the current track finishes (or gets skipped) before the next one plays."),
            ]),
            ("🖥️  Now Playing Overlay", [
                ("h1",   "🖥️  Now Playing Overlay"),
                ("body", "A bottom-left OBS overlay showing the current song's title and artist, sourced from the Music engine above."),
                ("code", "  http://localhost:<port>/nowplaying         →  the live overlay"),
                ("code", "  http://localhost:<port>/nowplaying?test=1  →  preview mode (fake sample text, for positioning in OBS)"),
                ("h2",   "Styling"),
                ("body", "Font is Avenir (falls back to Avenir Next / Segoe UI). Text is uppercased; the song title is bold, the artist line is regular weight underneath. Fades in/out automatically as tracks start/stop."),
                ("h2",   "How the artist is detected"),
                ("body", "Best-effort split of the YouTube video title on common separators ( - / – / — / | ), e.g. 'Artist - Song Title'. Videos without a separator show only the title."),
                ("tip",  "Tip: add it as an OBS Browser Source -- the background is transparent, no chroma key needed."),
            ]),
            ("🌐  Web Dashboard", [
                ("h1",   "🌐  Web Dashboard"),
                ("body", "A Flask-powered multistream dashboard bundling every chat overlay style into one running instance."),
                ("h2",   "Starting it"),
                ("body", "Go to the  🌐 Web  tab, pick a port between 5900-5999, and click  ▶ Start."),
                ("body", "This spawns a full copy of the bot as its own process on that port -- the new window opens the dashboard in your browser automatically once it's ready. Click  🌐 Open  any time to relaunch the browser tab, or  ⏹ Stop  to end that spawned instance."),
                ("h2",   "Pages available from  http://localhost:<port>/"),
                ("code", "  /            →  link picker page listing every overlay below"),
                ("code", "  /obs         →  Legacy chat overlay"),
                ("code", "  /obs2        →  Liquid Glass style overlay"),
                ("code", "  /obsnew      →  Classic Dark overlay"),
                ("code", "  /oldobsnew   →  an older dark variant"),
                ("code", "  /debugchat   →  raw chat + debug info overlay"),
                ("code", "  /ultradebug  →  core system status & queues"),
                ("code", "  /stats       →  viewers / likes / uptime widget"),
                ("code", "  /nowplaying  →  the Now Playing song overlay (see previous chapter)"),
                ("h2",   "Why a whole new process?"),
                ("body", "Each dashboard instance is a full, independent copy of the bot bound to one port -- so you can run multiple dashboards on different ports simultaneously (e.g. one per stream) without them fighting over the same port."),
                ("tip",  "Tip: requires  flask  (and optionally  flask-cors)  installed. The port is remembered in  flask_dashboard_config.json."),
            ]),
            ("🛡️  Moderators & Chat Pause", [
                ("h1",   "🛡️  Moderators & Chat Pause"),
                ("h2",   "Who counts as a moderator"),
                ("body", "Any of the following can use moderator-only commands:"),
                ("code", "  • The stream owner  (YouTube's isChatOwner flag)"),
                ("code", "  • A real YouTube channel moderator  (isChatModerator -- set on YouTube itself, not in this app)"),
                ("code", "  • The configured  ADMIN_USERNAME  account"),
                ("body", "Non-moderators get a clear rejection message instead of the command silently doing nothing, e.g.  '[disableinternet] someuser: moderator only.'"),
                ("h2",   "Pausing chat commands"),
                ("code", "  !pausechat  (or !disablechat)  →  moderator only: blocks all commands from non-mods"),
                ("code", "  !enablechat                    →  moderator only: resumes normal command processing"),
                ("body", "The Main tab shows a live  ▶ Chat commands are live  /  ⏸ Chat commands are PAUSED  indicator, with a manual toggle button. Pausing always auto-resets to unpaused the next time the bot is (re)started, so it can never linger forgotten into a new session."),
                ("tip",  "Tip: moderators can still use every command while chat is paused -- only non-mods are blocked."),
            ]),
            ("🎉  Extended Commands", [
                ("h1",   "🎉  Extended Commands"),
                ("body", "A large library of additional chat commands beyond the core VM/keyboard/mouse set."),
                ("h2",   "Short aliases"),
                ("code", "  !t / !s          →  alias of !type"),
                ("code", "  !k               →  alias of !key"),
                ("code", "  !c               →  alias of !combo"),
                ("code", "  !kd / !ku        →  alias of !keydown / !keyup"),
                ("code", "  !w               →  alias of !wait"),
                ("code", "  !lc / !rc        →  alias of !click / !rclick"),
                ("code", "  !m / !d          →  alias of !move / !drag"),
                ("code", "  !winkey <key>    →  Windows key + another key, e.g. !winkey e"),
                ("h2",   "Mouse extras"),
                ("code", "  !dclick / !tripleclick   →  double / triple left-click"),
                ("code", "  !scrollup / !scrolldown  →  scroll a fixed direction"),
                ("code", "  !move down 100  or  !move 100 down   →  either order works"),
                ("h2",   "System / shell"),
                ("code", "  !cmd <command>       →  opens Command Prompt and runs it"),
                ("code", "  !run <command>       →  types + runs a command via Win+R"),
                ("code", "  !dir <path>          →  opens a folder in Explorer"),
                ("code", "  !openfile <path>     →  opens a file with its default app"),
                ("code", "  !taskkill <process>  →  force-kills a process by name"),
                ("h2",   "Voice"),
                ("code", "  !tts <text>       →  speaks once (SAPI, host voice)"),
                ("code", "  !ttsloop <text>   →  repeats every few seconds"),
                ("code", "  !ttsxp <text>     →  XP/SAM-style voice (depends on installed SAPI voices)"),
                ("code", "  !gtts <text>      →  Google TTS, a different (online) voice engine"),
                ("code", "  !beep             →  plays a system beep"),
                ("h2",   "VM / system control"),
                ("code", "  !shutdown / !killvm (!forceshutdown)    →  soft / hard power off"),
                ("code", "  !pausevm / !resumevm                    →  pause / resume the VM"),
                ("code", "  !vmsavestate                            →  save state and stop"),
                ("code", "  !vmstatus                                →  report bot + VM status"),
                ("code", "  !makesnapshot <name>  (also !snapshot)  →  take a new snapshot"),
                ("code", "  !enableinternet / !disableinternet  (mod only)  →  toggle the VM's internet, live, no restart"),
                ("h2",   "Fun / chaos"),
                ("code", "  !roll                →  random number 1-100"),
                ("code", "  !coinflip            →  heads or tails"),
                ("code", "  !shake / !jiggle     →  small random mouse jitter"),
                ("code", "  !circle / !spiral    →  mouse moves in a pattern"),
                ("code", "  !msgbox <text>       →  pops a real message box inside the VM"),
                ("code", "  !spam <text> <n>     →  types text repeatedly (capped at 50)"),
                ("code", "  !countdown <n>       →  posts a countdown to the overlay, once per second"),
                ("code", "  !matrix              →  floods Notepad with falling-code style characters"),
                ("code", "  !colorscheme         →  randomizes the VM's accent color"),
                ("code", "  !rainbow             →  cycles the accent color for a few seconds"),
                ("code", "  !notepadflood / !exeflood / !txtflood / !deskflood  →  desktop chaos floods"),
                ("h2",   "Info / chat"),
                ("code", "  !ping        →  replies pong!"),
                ("code", "  !uptime      →  bot uptime"),
                ("code", "  !help        →  short in-chat help summary"),
                ("code", "  !stats       →  session command/vote stats"),
                ("code", "  !history     →  last few recorded events"),
                ("code", "  !leaderboard →  top command users"),
                ("code", "  !queue       →  pending song + video request count"),
                ("code", "  !status      →  current bot/VM status"),
                ("h2",   "Moderator only"),
                ("code", "  !enablecv            →  placeholder (no OCR/CV module in this build)"),
                ("code", "  !votestop            →  cancels any active vote"),
                ("code", "  !clear               →  clears the chat overlay"),
                ("code", "  !efail               →  forces a test error-state (for testing alerts)"),
                ("code", "  !poweroff            →  shuts down the HOST machine -- use with real caution"),
                ("tip",  "Tip: moderator-gated commands now give a clear rejection message if a non-mod tries them, instead of silently doing nothing -- see the Moderators chapter."),
            ]),
            ("🌍  VM Internet", [
                ("h1",   "🌍  VM Internet"),
                ("body", "Cuts or restores the VM's internet access LIVE by unplugging/replugging its virtual network cable -- no VM restart or power-off required."),
                ("h2",   "How it works"),
                ("body", "Runs  VBoxManage controlvm <vm> setlinkstate1 off / on  -- this only affects the currently selected VM's first network adapter, unlike a host-wide service toggle."),
                ("h2",   "Using it"),
                ("body", "Go to the  🖥 VM  tab and click  🌐 Toggle Internet,  or use the chat commands (moderator only):"),
                ("code", "  !enableinternet"),
                ("code", "  !disableinternet"),
                ("tip",  "Tip: since this is per-adapter, it works even if the VM uses NAT, Bridged, or Host-Only networking."),
            ]),
        ]

        _chapter_btns = []

        def _show_chapter(idx):
            _, sections = CHAPTERS[idx]
            txt.configure(state="normal")
            txt.delete("1.0", "end")
            for tag, content in sections:
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

    def _update_fun_best(self, key, value, higher_is_better=True, extra=None):
        """Updates fun_high_scores[key] in memory (NOT saved to disk yet -- that only
        happens when the green Save button is clicked) if value is a new best, and
        refreshes the live scores display if it exists. extra is an optional dict of
        additional keys to set alongside (e.g. accuracy alongside wpm) whenever this
        IS a new best for `key` specifically."""
        current = fun_high_scores.get(key)
        is_new_best = current is None or (
            value > current if higher_is_better else value < current)
        if is_new_best:
            fun_high_scores[key] = value
            if extra:
                fun_high_scores.update(extra)
            if hasattr(self, "_fun_scores_label") and self._fun_scores_label.winfo_exists():
                self._refresh_fun_scores_label()
        return is_new_best

    def _refresh_fun_scores_label(self):
        wpm = fun_high_scores.get("wpm") or 0
        cps = fun_high_scores.get("cps") or 0
        reaction = fun_high_scores.get("reaction_ms")
        snake = fun_high_scores.get("snake_score") or 0
        reaction_str = f"{reaction:.0f}ms" if reaction is not None else "—"
        self._fun_scores_label.configure(
            text=f"🏆 Best: {wpm:.0f} WPM  •  {cps:.2f} CPS  •  {reaction_str} reaction  •  {snake} Snake")

    def _build_fun_tab(self, parent):
        """
        Builds the Fun tab as its own small notebook of just-for-fun
        tools: skill tests (typing speed + CPS), a reaction time test, a
        Snake mini-game, and a random tools panel (dice/coin flip/name
        picker). Best-ever results across all of these persist to disk,
        but only when the Save button here is explicitly clicked --
        nothing auto-saves.
        """
        outer = tk.Frame(parent, bg=self.BG)
        outer.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(outer, text="🎉 Just for Fun",
                 bg=self.BG, fg=self.TEXT,
                 font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(0, 12))

        scores_row = tk.Frame(outer, bg=self.BG)
        scores_row.pack(fill="x", pady=(0, 12))
        self._fun_scores_label = tk.Label(scores_row, text="", bg=self.BG,
                                           fg=self.TEXTDIM, font=("Segoe UI", 9))
        self._fun_scores_label.pack(side="left")
        self._refresh_fun_scores_label()

        def _save_fun_scores():
            save_fun_high_scores()
            save_status.configure(text="✔ Saved!", fg=self.GREEN)
            self.root.after(2500, lambda: save_status.configure(text=""))

        ttk.Button(scores_row, text="💾 Save High Scores", style="Green.TButton",
                   command=_save_fun_scores).pack(side="right")
        save_status = tk.Label(scores_row, text="", bg=self.BG, fg=self.GREEN,
                                font=("Segoe UI", 9, "bold"))
        save_status.pack(side="right", padx=(0, 10))

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
            self._update_fun_best("wpm", wpm, higher_is_better=True, extra={"accuracy": accuracy})
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
                self._update_fun_best("cps", cps, higher_is_better=True)
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

        state = {"phase": "idle", "wait_job": None, "start_time": 0.0,
                 "best_ms": fun_high_scores.get("reaction_ms")}

        box = tk.Label(wrap, text="Click to start", bg=self.BG3, fg=self.TEXT,
                        font=("Segoe UI", 14, "bold"), width=32, height=8,
                        cursor="hand2")
        box.pack(pady=(0, 12))

        _initial_reaction_best = fun_high_scores.get("reaction_ms")
        _initial_reaction_text = (f"Best: {_initial_reaction_best:.0f} ms"
                                   if _initial_reaction_best is not None else "Best: —")
        result_label = tk.Label(wrap, text=_initial_reaction_text, bg=self.BG, fg=self.ACCENT2,
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
                    self._update_fun_best("reaction_ms", elapsed_ms, higher_is_better=False)
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
        best_label = tk.Label(top_row, text=f"Best: {fun_high_scores.get('snake_score', 0)}", bg=self.BG, fg=self.TEXTDIM,
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
            "best": fun_high_scores.get("snake_score", 0),
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
                    self._update_fun_best("snake_score", state["score"], higher_is_better=True)
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

    def _build_mrtristinai_tab(self, parent):
        """
        MrTristinAI tab — chat with Groq-hosted LLMs directly from the app.
        The Groq API key is entered once, saved to mrtristinai_config.json, and
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

        self._mrtristinai_key_var = tk.StringVar(value=MRTRISTINAI_CONFIG.get("groq_api_key", ""))
        self._mrtristinai_key_entry = ttk.Entry(
            setup_card, textvariable=self._mrtristinai_key_var,
            width=44, font=("Segoe UI", 9), show="•")
        self._mrtristinai_key_entry.grid(row=1, column=0, columnspan=2, sticky="ew",
                                     padx=(0, 6), ipady=3)

        self._mrtristinai_key_visible = False

        def _toggle_key_visibility():
            self._mrtristinai_key_visible = not self._mrtristinai_key_visible
            self._mrtristinai_key_entry.configure(show="" if self._mrtristinai_key_visible else "•")
            show_btn.configure(text="🙈 Hide" if self._mrtristinai_key_visible else "👁 Show")

        show_btn = ttk.Button(setup_card, text="👁 Show", style="Dim.TButton",
                               command=_toggle_key_visibility)
        show_btn.grid(row=1, column=2, padx=(0, 6))

        ttk.Button(setup_card, text="💾 Save Key", style="Green.TButton",
                   command=self._mrtristinai_save_key).grid(row=1, column=3)

        tk.Label(setup_card,
                 text="Saved locally in mrtristinai_config.json — entered once, reused on every launch. "
                      "Get a free key at console.groq.com/keys",
                 bg=self.BG2, fg=self.TEXTDIM,
                 font=("Segoe UI", 8), justify="left").grid(
                 row=2, column=0, columnspan=4, sticky="w", pady=(4, 10))

        tk.Label(setup_card, text="Model:", bg=self.BG2, fg=self.TEXT,
                 font=("Segoe UI", 9)).grid(row=3, column=0, sticky="w", padx=(0, 8))

        self._mrtristinai_model_var = tk.StringVar(value=MRTRISTINAI_CONFIG.get("model", MRTRISTINAI_FALLBACK_MODELS[0]))
        self._mrtristinai_model_combo = ttk.Combobox(
            setup_card, textvariable=self._mrtristinai_model_var,
            values=MRTRISTINAI_FALLBACK_MODELS, width=32,
            font=("Segoe UI", 9), state="readonly")
        self._mrtristinai_model_combo.grid(row=3, column=1, sticky="w")
        self._mrtristinai_model_combo.bind("<<ComboboxSelected>>",
                                       lambda e: self._mrtristinai_save_model())

        ttk.Button(setup_card, text="🔄 Refresh Models", style="Dim.TButton",
                   command=self._mrtristinai_refresh_models).grid(row=3, column=2, padx=(6, 0))

        self._mrtristinai_model_status = tk.Label(setup_card, text="", bg=self.BG2,
                                              fg=self.TEXTDIM, font=("Segoe UI", 8))
        self._mrtristinai_model_status.grid(row=4, column=0, columnspan=4, sticky="w", pady=(4, 0))

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

        self._mrtristinai_input_var = tk.StringVar()
        mrtristinai_entry = ttk.Entry(input_row, textvariable=self._mrtristinai_input_var,
                                  font=("Segoe UI", 10))
        mrtristinai_entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 6))
        mrtristinai_entry.bind("<Return>", lambda e: self._mrtristinai_send())

        self._mrtristinai_send_btn = ttk.Button(input_row, text="Send ➤", style="Accent.TButton",
                                            command=self._mrtristinai_send)
        self._mrtristinai_send_btn.pack(side="left", padx=(0, 6))

        ttk.Button(input_row, text="🗑 Clear Chat", style="Dim.TButton",
                   command=self._mrtristinai_clear_chat).pack(side="left")

        chat_frame = tk.Frame(chat_card, bg=self.BORDER, bd=1)
        chat_frame.pack(fill="both", expand=True)
        self._mrtristinai_chat_view = scrolledtext.ScrolledText(
            chat_frame,
            bg=self.CONSOLE, fg=self.TEXT,
            font=("Segoe UI", 10),
            insertbackground=self.TEXT,
            selectbackground=self.ACCENT,
            relief="flat", bd=0, state="disabled", wrap="word")
        self._mrtristinai_chat_view.pack(fill="both", expand=True, padx=1, pady=1)
        self._mrtristinai_chat_view.tag_config("user_tag", foreground=self.ACCENT2, font=("Segoe UI", 10, "bold"))
        self._mrtristinai_chat_view.tag_config("ai_tag", foreground=self.GREEN, font=("Segoe UI", 10, "bold"))
        self._mrtristinai_chat_view.tag_config("err_tag", foreground=self.RED)

        self._mrtristinai_history = []   # list of {"role":.., "content":..} sent to Groq for context
        self._mrtristinai_busy = False


        # If a key is already saved, quietly refresh the model list in the
        # background so the dropdown reflects what's actually available.
        if MRTRISTINAI_CONFIG.get("groq_api_key"):
            self._mrtristinai_refresh_models(silent=True)

    def _mrtristinai_safe_after(self, callback):
        """
        Like self.root.after(0, callback), but tolerates the app having
        already closed. Background MrTristinAI requests run in daemon threads
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

    def _mrtristinai_append_chat(self, who: str, text: str, tag: str):
        self._mrtristinai_chat_view.configure(state="normal")
        self._mrtristinai_chat_view.insert("end", f"{who}: ", tag)
        self._mrtristinai_chat_view.insert("end", f"{text}\n\n")
        self._mrtristinai_chat_view.configure(state="disabled")
        self._mrtristinai_chat_view.see("end")

    def _mrtristinai_clear_chat(self):
        self._mrtristinai_history = []
        self._mrtristinai_chat_view.configure(state="normal")
        self._mrtristinai_chat_view.delete("1.0", "end")
        self._mrtristinai_chat_view.configure(state="disabled")

    def _mrtristinai_save_key(self):
        key = self._mrtristinai_key_var.get().strip()
        MRTRISTINAI_CONFIG["groq_api_key"] = key
        save_mrtristinai_config()
        if key:
            messagebox.showinfo("MrTristinAI", "Groq API key saved. It will be reused automatically next time you open the app.")
            self._mrtristinai_refresh_models(silent=True)
        else:
            messagebox.showinfo("MrTristinAI", "API key cleared.")

    def _mrtristinai_save_model(self):
        MRTRISTINAI_CONFIG["model"] = self._mrtristinai_model_var.get().strip()
        save_mrtristinai_config()

    def _mrtristinai_refresh_models(self, silent: bool = False):
        key = self._mrtristinai_key_var.get().strip()
        if not silent:
            self._mrtristinai_model_status.configure(text="Fetching model list...", fg=self.TEXTDIM)

        def _work():
            models = groq_list_models(key)

            def _apply():
                current = self._mrtristinai_model_var.get()
                self._mrtristinai_model_combo.configure(values=models)
                if current not in models and models:
                    self._mrtristinai_model_var.set(models[0])
                    MRTRISTINAI_CONFIG["model"] = models[0]
                    save_mrtristinai_config()
                if not silent:
                    self._mrtristinai_model_status.configure(
                        text=f"{len(models)} model(s) available.", fg=self.GREEN)
            self._mrtristinai_safe_after(_apply)

        threading.Thread(target=_work, daemon=True).start()

    def _mrtristinai_send(self):
        if self._mrtristinai_busy:
            return
        text = self._mrtristinai_input_var.get().strip()
        if not text:
            return

        key = self._mrtristinai_key_var.get().strip()
        if not key:
            messagebox.showwarning("MrTristinAI", "Enter and save your Groq API key first.")
            return

        model = self._mrtristinai_model_var.get().strip() or MRTRISTINAI_FALLBACK_MODELS[0]

        self._mrtristinai_input_var.set("")
        self._mrtristinai_append_chat("You", text, "user_tag")
        self._mrtristinai_history.append({"role": "user", "content": text})

        self._mrtristinai_busy = True
        self._mrtristinai_send_btn.configure(state="disabled")

        def _work():
            try:
                messages = [{"role": "system", "content": MRTRISTINAI_CONFIG.get("system_prompt", MRTRISTINAI_CONFIG_DEFAULT_PROMPT)}]
                messages.extend(self._mrtristinai_history[-20:])   # keep last 20 turns of context
                reply = groq_chat_completion(key, model, messages)
            except Exception as e:
                reply = None
                error = str(e)
            else:
                error = None

            def _apply():
                self._mrtristinai_busy = False
                self._mrtristinai_send_btn.configure(state="normal")
                if error:
                    self._mrtristinai_append_chat("Error", error, "err_tag")
                else:
                    self._mrtristinai_history.append({"role": "assistant", "content": reply})
                    self._mrtristinai_append_chat("MrTristinAI", reply, "ai_tag")
            self._mrtristinai_safe_after(_apply)

        threading.Thread(target=_work, daemon=True).start()



# ========================= MAIN =========================
if __name__ == '__main__':
    load_custom_commands()
    load_user_mgmt()
    load_event_log()
    load_permissions_config()
    load_yt_log_relay_config()
    if YT_LOG_RELAY_CONFIG.get("enabled"):
        start_yt_log_relay_worker()
    load_host_switch_config()
    host_switch_autodetect_role()
    start_host_switch_server()
    threading.Thread(target=host_switch_test_connection_and_handshake, daemon=True).start()
    load_sound_config()
    load_multi_stream_config()
    load_scheduler_config()
    load_realpc_config()
    load_reconnect_config()
    _update_splash(97, "Building interface...")

    # Reuse the hidden host root that was created alongside the splash.
    # Never call tk.Tk() a second time — that would reset all ttk styles.
    root = _host_root
    _gui_root = root
    app  = UltraBotGUI(root)   # builds GUI while root is still hidden

    _update_splash(100, "Ready!")
    time.sleep(0.25)    # let the user see 100% for a moment
    _close_splash()     # destroy splash Toplevel
    root.deiconify()    # NOW show the fully-built main window

    app.show_welcome_guide()   # show user guide on first launch

    # ── If this instance was spawned by the Web Dashboard's Start button
    #    (sys.argv had --flaskport=NNNN), auto-start Flask on that port and
    #    open the browser -- no need to click Start again in the new window. ──
    if _LAUNCH_FLASK_PORT is not None:
        def _auto_start_flask():
            ok, msg = start_flask_server(_LAUNCH_FLASK_PORT)
            print(f"[WebDashboard] auto-start on port {_LAUNCH_FLASK_PORT}: {msg}")
            if ok:
                time.sleep(1.0)
                open_flask_dashboard(_LAUNCH_FLASK_PORT)
        threading.Thread(target=_auto_start_flask, daemon=True).start()

    # ── If this instance was launched by the auto-update/hot-reload relaunch
    #    pipeline (--autostart-everything), self-start the bot from video_id.json
    #    with no one at the keyboard. Extra streams resume automatically as part
    #    of that (they read their own already-persisted config files).
    #    Real PC Control deliberately does NOT auto-resume -- see the note below. ──
    if _AUTOSTART_EVERYTHING:
        def _auto_start_everything():
            time.sleep(1.0)
            try:
                vid_path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "video_id.json")
                with open(vid_path, "r", encoding="utf-8") as f:
                    vid = json.load(f).get("video_id", "")
                if vid:
                    app._yt_var.set(vid)
                    app._start_bot()
                    print(f"[AutoStart] Self-started bot on video ID {vid} from video_id.json.")
                else:
                    print("[AutoStart] video_id.json had no video_id -- start the bot manually.")
            except Exception as e:
                print(f'[AutoStart] Could not self-start from video_id.json: Python exception: "{traceback.format_exc()}"')
            if REALPC_CONFIG.get("enabled"):
                print("[AutoStart] NOTE: Real PC Control was enabled before this restart. "
                      "For safety it does NOT auto-resume -- go to the Real PC Control "
                      "tab and click Start to re-confirm and resume it.")
        threading.Thread(target=_auto_start_everything, daemon=True).start()

    # ── Continuous auto-update watcher + file-edit hot-reload watchdog.
    #    Both run for the lifetime of the process, whether this is the main GUI
    #    instance or one spawned just for the web dashboard. ──
    threading.Thread(target=_autoupdate_watcher, daemon=True, name="autoupdate_watcher").start()
    threading.Thread(target=_file_edit_watchdog, daemon=True, name="file_edit_watchdog").start()

    start_tray_icon()

    def _on_close():
        answer = messagebox.askyesnocancel(
            "Close",
            "Minimize to system tray instead of closing?\n\n"
            "Yes  → minimize to tray (bot keeps running)\n"
            "No   → exit completely\n"
            "Cancel → go back"
        )
        if answer is True:
            root.withdraw()
            notify("Running in Tray", "Bot is still running. Right-click the tray icon to exit.")
        elif answer is False:
            bot_stop_event.set()
            stop_realpc_bot()
            stop_tray_icon()
            root.destroy()
            os._exit(0)

    root.protocol("WM_DELETE_WINDOW", _on_close)
    root.mainloop()
    stop_tray_icon()
