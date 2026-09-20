# CNC File Shuttle

A simple cross-platform CNC file sender for moving G-code to shop machines.

The application provides the queue-based Tkinter interface, machine
profiles, target preview, filename validation, local or mounted-folder copying,
and direct SFTP transfers to a LinuxCNC computer.

Download the packaged Windows build from [the latest release](https://github.com/FabLabRacing/cnc-file-shuttle/releases/latest).
See [INSTALL.md](INSTALL.md) for Windows installation and macOS/Linux source setup.

## Run from source

Python 3.10 or newer is recommended. Tkinter is included with the standard
Windows and macOS Python installers. On some Linux distributions it is a
separate package, commonly named `python3-tk`.

```bash
python cnc_file_shuttle.py
```

Install the SFTP dependency with:

```bash
python -m pip install -r requirements.txt
```

Local-folder copying continues to work without Paramiko installed.

## Current features

- Dark, shop-friendly, scrollable Tkinter interface
- Named machine profiles stored in the user's application-data directory
- Local folders, mapped drives, mounted SMB/NFS shares, and USB destinations
- Multi-file queue with remove, clear, move-up, and move-down controls
- One-click requeue of finished, skipped, or failed files
- Exact destination preview before copying
- Local and remote destination-folder browsing within the profile root
- Pending and failed queue paths follow target-folder changes
- Completed items preserve the destination actually used
- Filename and extension warnings
- Per-profile overwrite policy: ask each time, always overwrite, or skip existing
- Live activity log
- Automatic failure-only diagnostic logs
- Background queue copies so the window stays responsive
- Built-in SFTP transfers using Paramiko
- Ed25519 key generation and one-time password-assisted key installation
- Explicit first-connection SSH host-key trust with SHA-256 fingerprint
- Password and encrypted-key secrets kept only for the current operation
- Remote folder creation, upload progress, and remote file-size verification
- Read-only controller and LinuxCNC status monitoring over SSH
- Automatic status connection when an SFTP profile is loaded
- Current G-code filename and executing-line display
- Active-program overwrite protection without blocking unrelated transfers

## Safety scope

CNC File Shuttle only copies files. It does not start programs, jog machines,
home axes, reset E-stops, or issue LinuxCNC commands.

## Data locations

Profiles and failure logs are stored outside the program directory so packaged
applications remain writable:

- Windows: `%APPDATA%\\CNC File Shuttle`
- macOS: `~/Library/Application Support/CNC File Shuttle`
- Linux: `${XDG_CONFIG_HOME:-~/.config}/cnc-file-shuttle`

## SFTP setup

1. Create an SFTP profile and enter the LinuxCNC host/IP, username, and remote
   program root.
2. Select **Set Up SSH Key...**.
3. Confirm the LinuxCNC computer's SSH fingerprint.
4. Enter the LinuxCNC account password once.
5. CNC File Shuttle generates an app-specific Ed25519 key, installs its public
   half, and verifies a password-free connection.

The account password and optional key passphrase are never written to the
profile. The profile stores only the private-key path.

## Machine status

SFTP profiles automatically connect the read-only status monitor when loaded,
including at application launch. The panel shows whether the controller PC is
reachable and whether LinuxCNC is stopped, ready, running, paused, in E-stop,
or powered off. When available, it also shows the loaded G-code filename and
current executing line. **Disconnect** stops monitoring until **Connect /
Monitor** is selected or another SFTP profile is loaded.

CNC File Shuttle installs a small helper under the remote user's
`~/.local/share/cnc-file-shuttle` directory. The helper uses only
`linuxcnc.stat()` and does not create a LinuxCNC command channel. It cannot
start a cycle, jog, home, change machine power, reset E-stop, or issue MDI.

Status monitoring does not impose a blanket transfer lockout while machining.
Unrelated files may still be sent. Before an SFTP overwrite, a successful status
check blocks the exact program path reported as running or paused. Interpreter
waiting is treated as running.

This protection depends on the status helper being available and returning usable
status. If the helper cannot be loaded or installed, or a status query fails,
transfers remain enabled; errors are recorded in the Activity Log. A query failure
disables further active-program checks for that queue. An unavailable status
response also cannot identify an active file. Local-folder copies do not perform
this check.

The check compares normalized path strings, not symlink aliases, and describes
the state at check time. It is not a lock: the active program can change after
the check, including while an overwrite prompt is open.

## Existing-file behavior

Each machine profile stores an **If file exists** setting:

- **Ask each time** displays the existing overwrite/skip dialog. Its Overwrite
  All and Skip All choices apply to the remainder of that queue.
- **Always overwrite** replaces existing destination files without prompting.
- **Skip existing** leaves existing destination files unchanged without
  prompting.

When the status check identifies the destination as the active program, its
overwrite block takes priority over all three settings, including **Always
overwrite**. The availability and timing limits above still apply.

## Reusing a queue and browsing destinations

After a transfer, **Requeue Finished** changes every Done, Skipped, or Failed
item back to Pending. The same files can then be sent again without clearing and
rebuilding the queue. Requeued items use the destination currently shown in the
Destination panel.

The Destination **Browse...** button opens the normal folder picker for local
profiles. For SFTP profiles it connects to the LinuxCNC computer and presents a
small remote-folder browser. Both browsers stay beneath the root folder saved in
the profile; selecting the root itself leaves Target subfolder blank.
In the SFTP browser, **New Folder...** creates a single folder beneath the current
folder and opens it for selection. If opening or listing a folder fails, the
browser keeps the last successfully displayed destination selected.
