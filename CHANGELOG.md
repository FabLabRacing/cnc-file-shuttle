# Changelog

## Unreleased

- Keep the remote browser's selected destination aligned with its visible folder
  when opening, going up, or listing a newly created folder fails.
- Handle Linux/X11 and macOS mouse wheels, preserve small wheel deltas, and leave
  nested lists, text boxes, and dialogs in control of their own scrolling.
- Remove unused `program_waiting` state handling; interpreter waiting continues
  to report as running and retains active-program protection.
- Refresh installation/release links and document the availability, exact-path,
  and timing limits of active-program overwrite protection.

## 1.0.1 — 2026-09-18

- Added **New Folder...** to the LinuxCNC SFTP destination browser, including
  name validation, remote creation, automatic navigation, and error reporting.

## 1.0.0 — 2026-09-07

- First production release, with a packaged Windows x64 build and source support
  for Windows, macOS, and Linux.
- Includes local/SFTP transfers, machine profiles, queue reuse, destination
  browsing, overwrite policies, SSH-key setup, read-only LinuxCNC status, and
  active-program checks for SFTP overwrites.

## 0.6.0-dev6

- SFTP profiles now start read-only machine-status monitoring automatically
  when loaded, including the initial profile at application launch.
- Manual Disconnect still stops monitoring until the user reconnects or loads
  another SFTP profile.

## 0.5.0-dev5

- Added **Requeue Finished** to resend completed, skipped, or failed queue items
  without removing and adding the source files again.
- Added a destination **Browse...** button for local and SFTP profiles.
- Local browsing is constrained to the configured profile root folder.
- Added an SFTP folder browser that navigates directories beneath the configured
  remote root using the existing trusted SSH connection.

## 0.4.0-dev4

- Added a per-profile **If file exists** setting.
- Added **Ask each time**, **Always overwrite**, and **Skip existing** modes.
- Kept the active LinuxCNC program overwrite block in force for every mode.
- Added the selected overwrite policy to the activity log when a queue starts.
- Existing profiles and unknown saved values safely default to **Ask each time**.

## 0.3.0-dev3

- Added a read-only Machine Status panel for SFTP profiles.
- Added separate controller-online and LinuxCNC-state indicators.
- Added current program filename and executing-line display.
- Added two-second status polling over the existing trusted SSH transport.
- Added automatic installation/update of a small read-only LinuxCNC status helper.
- Added Connect / Monitor and Disconnect controls.
- Added explicit states for LinuxCNC not running, E-stop, machine off, ready,
  running, paused, busy, and unavailable.
- Added protection against overwriting the program currently active in LinuxCNC.
- Kept unrelated file transfers available while LinuxCNC is machining.

## 0.2.0-dev2

- Added Paramiko SFTP backend.
- Added local/SFTP dynamic profile fields.
- Added Ed25519 key-pair generation.
- Added guided one-time public-key installation using the LinuxCNC password.
- Added explicit SSH host-key fingerprint trust and changed-key lockout.
- Added password and private-key authentication modes without saved secrets.
- Added remote folder creation and write testing.
- Added SFTP overwrite detection and remote file-size verification.
- Added transfer-progress status.

## 0.1.0-dev1

- Initial queue-based Tkinter interface.
- Added profiles and local/mounted-folder copying.
- Added overwrite handling, path validation, and failure-only logs.
