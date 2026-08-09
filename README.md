# VBox Script

**Download and install VirtualBox SDK for VBox script: https://download.virtualbox.org/virtualbox/7.2.10/VirtualBoxSDK-7.2.10-174163.zip**

**Download VirtualBox: https://www.virtualbox.org/wiki/Downloads**

# VMware Script

**pip install vncdotool pytchat**

----------------------------------------------------------------------------
## ⚠️ Why does my antivirus / a sandbox scanner flag this?

This project is a **YouTube live-chat controlled automation bot** — it lets
viewers in your stream chat send commands that control a VirtualBox/VMware
virtual machine (keyboard input, mouse input, power actions, screen
interaction). That's the whole point of the project: chat-controlled remote
automation.

The problem is that **"chat-controlled remote automation" and "Remote
Access Trojan (RAT)" look identical to antivirus engines and sandbox
analysis tools at the code-behavior level.** Both:

- inject synthetic keyboard/mouse input into a system,
- can be triggered/controlled by input arriving from outside the machine
  (in this case, YouTube chat — in malware's case, a C2 server),
- check for admin privileges (`IsUserAnAdmin`),
- gather basic system/process info (`psutil`) to decide what to do,
- may register themselves to auto-start (so the bot survives a reboot
  during a long stream),
- fetch a version number from a remote URL to check for updates.

None of this is hidden or obfuscated — every one of these behaviors is
plainly visible in the source code, with comments, and serves the stated
purpose of the project (running a stream bot). There is no code here that
exfiltrates data, encrypts files, disables security software, or
communicates with an attacker-controlled server. **The flags are a
consequence of what this category of tool inherently looks like to
automated analysis, not evidence of malicious behavior.**

If you want to verify this yourself rather than take my word for it:
- The full source is in this repo — read it, it's one file, `Ctrl+F`
  whatever you're worried about.
- Run it in a VM/sandbox of your own and watch what it actually does
  (chat comes in → keyboard/mouse events go to the VirtualBox VM you
  configured — nothing else).
- Compare the flagged behaviors above against the corresponding lines in
  the code.

If you'd still rather not run a `.py` script directly, that's a completely
reasonable position — feel free to inspect and run it in an isolated VM.

### A note on the startup dependency installer

On launch, the script checks for a handful of optional pip packages it
needs for certain features (`pytchat`, `pywin32`, `plyer`, `pystray`,
`pillow`, `pyautogui`, `pygame`, `psutil`). If any are missing, it shows a
dialog listing exactly which ones and asks **Yes/No** before installing
anything — nothing is installed silently. If you decline, the script keeps
running with the corresponding features disabled, same as if the packages
were never checked at all.

This is also, unfortunately, exactly the shape of behavior sandboxes and
antivirus engines flag as a "dropper" pattern: a process that spawns `pip`,
reaches the network, installs packages, and (in this case) restarts
itself so the newly installed packages take effect. The difference is
consent and transparency — every package it can install is a well-known,
publicly documented PyPI library used for a specific, visible feature in
this bot (chat reading, text-to-speech, tray icon, mouse/keyboard
automation, sound playback, system stats), not an arbitrary or
attacker-controlled payload. You can decline the prompt entirely and run
the bot with reduced functionality, or just `pip install` the packages
yourself ahead of time so the prompt never appears.

