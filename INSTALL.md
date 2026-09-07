# Installing CNC File Shuttle

CNC File Shuttle runs on Windows, macOS, and Linux. A packaged Windows build is
the easiest installation. macOS and Linux currently run from source with
Python 3.10 or newer.

## Windows — packaged release

The packaged release does not require Python.

1. Download `CNC-File-Shuttle-v1.0.0-Windows-x64.zip` from the latest GitHub
   release.
2. Right-click the downloaded ZIP file and select **Extract All...**.
3. Keep the entire extracted `CNC File Shuttle` folder together. The supporting
   files beside the executable are required.
4. Open the extracted folder and run `CNC File Shuttle.exe`.

Windows Defender or SmartScreen may briefly inspect a new unsigned build the
first time it runs. Obtain releases from this project's GitHub repository. A
short first-run scan is normal; an explicit malware detection or quarantine
warning is not.

To uninstall the packaged build, close the application and delete its extracted
folder. User profiles and diagnostic logs are stored separately under:

```text
%APPDATA%\CNC File Shuttle
```

Delete that folder as well only if you also want to remove saved profiles,
trusted-host records, and logs.

## Windows — run from source

1. Install Python 3.10 or newer from [python.org](https://www.python.org/downloads/windows/).
2. Download or clone the CNC File Shuttle repository.
3. Open PowerShell in the repository folder—the folder containing
   `cnc_file_shuttle.py` and `requirements.txt`.
4. Create an isolated Python environment and install the dependency:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install --upgrade pip
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

5. Start the application:

   ```powershell
   .\.venv\Scripts\pythonw.exe cnc_file_shuttle.py
   ```

Use `python.exe` instead of `pythonw.exe` when troubleshooting and you want to
see console output.

## macOS — run from source

1. Install Python 3.10 or newer from [python.org](https://www.python.org/downloads/macos/).
   The official macOS installer includes a macOS-native Tk, which CNC File
   Shuttle uses for its interface.
2. Download or clone the repository and open Terminal in its folder.
3. Optionally verify Tkinter before continuing. A small test window should open:

   ```bash
   python3 -m tkinter
   ```

4. Create a virtual environment and install the dependency:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```

5. Start CNC File Shuttle:

   ```bash
   python cnc_file_shuttle.py
   ```

Saved profiles and diagnostic logs are stored under:

```text
~/Library/Application Support/CNC File Shuttle
```

## Linux — run from source

Python is commonly already installed, but Tkinter and virtual-environment
support may be separate packages.

### Debian, Ubuntu, Linux Mint, and LinuxCNC Debian installations

```bash
sudo apt update
sudo apt install python3 python3-venv python3-tk
```

### Fedora

```bash
sudo dnf install python3 python3-tkinter
```

### Arch Linux

```bash
sudo pacman -S python tk
```

After installing the operating-system packages:

1. Download or clone the repository and open a terminal in its folder.
2. Create a virtual environment and install the dependency:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```

3. Start CNC File Shuttle:

   ```bash
   python cnc_file_shuttle.py
   ```

Saved profiles and diagnostic logs are stored under:

```text
${XDG_CONFIG_HOME:-~/.config}/cnc-file-shuttle
```

## LinuxCNC computer preparation for SFTP

Local-folder mode requires no network service. SFTP mode requires the LinuxCNC
computer to run an OpenSSH server and the selected Linux user to have write
permission to the configured G-code directory.

On a Debian-based LinuxCNC computer, install and enable OpenSSH if it is not
already running:

```bash
sudo apt update
sudo apt install openssh-server
sudo systemctl enable --now ssh
```

To find the LinuxCNC computer's IP address:

```bash
hostname -I
```

From the computer running CNC File Shuttle, an ordinary SSH login should be able
to reach the same account:

```bash
ssh username@linuxcnc-ip
```

No custom receiver service or LinuxCNC configuration change is required.

## First SFTP profile and SSH-key setup

1. Start CNC File Shuttle and create a machine profile.
2. Select **SFTP / SSH** as the backend.
3. Enter the LinuxCNC computer's host name or IP address, SSH port, Linux user,
   and absolute remote program root.
4. Select **Set Up SSH Key...**.
5. Verify and accept the displayed SSH host-key fingerprint.
6. Enter the Linux account password once so CNC File Shuttle can install its
   public key.
7. Save the profile and select **Test Target**.

The password and any private-key passphrase are not saved in the profile. The
application stores only the private-key path. Read-only LinuxCNC status
monitoring starts automatically when an SFTP profile is loaded.

The LinuxCNC status helper is installed automatically under the remote user's:

```text
~/.local/share/cnc-file-shuttle
```

It reads `linuxcnc.stat()` only. It cannot start programs, jog or home axes,
reset E-stop, change machine power, or issue MDI commands.

## Updating

### Packaged Windows build

1. Close CNC File Shuttle.
2. Download and extract the newer release into a new folder.
3. Run the new executable.
4. After confirming it works, delete the old application folder.

Saved profiles normally carry forward because they are stored outside the
application folder.

### Source installation

Replace or update the source files, then refresh the virtual environment:

```bash
python -m pip install --upgrade -r requirements.txt
```

## Troubleshooting

### The GUI does not open and Python reports a Tkinter error

- On Debian or Ubuntu, install `python3-tk`.
- On Fedora, install `python3-tkinter`.
- On macOS, use the current installer from python.org or verify the Tk support
  supplied by your chosen Python distribution.

Test Tkinter with:

```bash
python3 -m tkinter
```

### SFTP support says Paramiko is unavailable

Activate the project's virtual environment and run:

```bash
python -m pip install -r requirements.txt
```

### The LinuxCNC computer is online but SSH is refused

Confirm that the SSH service is running on LinuxCNC:

```bash
systemctl status ssh
```

Also confirm the host/IP, port, username, network connectivity, and firewall
settings.

### The SSH host identity changed warning appears

Do not automatically accept an unexpected identity change. Confirm whether the
LinuxCNC computer was reinstalled, replaced, or assigned a different IP
address. After independently verifying the new fingerprint, use **Forget Host
Trust...** and reconnect.

### The application opens but LinuxCNC status is unavailable

File transfer can still work when LinuxCNC itself is closed. Status reporting
requires LinuxCNC's Python module to be available to the logged-in Linux user.
Review the Machine Status panel and Activity Log for the specific error.

## Additional references

- [Python on Windows](https://docs.python.org/3/using/windows.html)
- [Python on macOS](https://docs.python.org/3/using/mac.html)
- [OpenSSH manual pages](https://www.openssh.com/manual.html)

