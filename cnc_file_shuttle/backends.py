from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shlex
import shutil
import socket
import stat
from abc import ABC, abstractmethod
from pathlib import Path, PurePosixPath
from typing import Callable

try:
    import paramiko
except ImportError:  # Local-folder mode deliberately works without Paramiko.
    paramiko = None  # type: ignore[assignment]


ProgressCallback = Callable[[int, int], None]
TargetPath = Path | PurePosixPath


def safe_subfolder_parts(subfolder: str) -> tuple[str, ...]:
    normalized = subfolder.strip().replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise BackendError("Target subfolder must be relative to the profile root folder.")
    parts = tuple(part for part in normalized.split("/") if part)
    if any(part == ".." for part in parts):
        raise BackendError("Target subfolder cannot contain '..'.")
    return parts


class BackendError(RuntimeError):
    pass


class DependencyError(BackendError):
    pass


class UnknownHostKeyError(BackendError):
    pass


class AuthenticationError(BackendError):
    pass


class TransferBackend(ABC):
    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def test_target(self, subfolder: str = "") -> tuple[bool, str]: ...

    @abstractmethod
    def destination_for(self, filename: str, subfolder: str = "") -> TargetPath: ...

    @abstractmethod
    def exists(self, destination: TargetPath) -> bool: ...

    @abstractmethod
    def copy_file(self, source: Path, destination: TargetPath, progress: ProgressCallback | None = None) -> None: ...


class LocalFolderBackend(TransferBackend):
    def __init__(self, root_folder: str) -> None:
        self.root = Path(root_folder).expanduser()

    def connect(self) -> None:
        return

    def close(self) -> None:
        return

    def folder_for(self, subfolder: str = "") -> Path:
        return self.root.joinpath(*safe_subfolder_parts(subfolder))

    def destination_for(self, filename: str, subfolder: str = "") -> Path:
        return self.folder_for(subfolder) / filename

    def test_target(self, subfolder: str = "") -> tuple[bool, str]:
        folder = self.folder_for(subfolder)
        if not self.root.exists():
            return False, f"Root folder does not exist: {self.root}"
        if not self.root.is_dir():
            return False, f"Root target is not a folder: {self.root}"
        if folder.exists() and not folder.is_dir():
            return False, f"Target exists but is not a folder: {folder}"
        return True, f"Target ready: {folder}"

    def exists(self, destination: TargetPath) -> bool:
        return Path(destination).exists()

    def copy_file(self, source: Path, destination: TargetPath, progress: ProgressCallback | None = None) -> None:
        destination = Path(destination)
        if not source.is_file():
            raise BackendError(f"Source file is unavailable: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.cnc-file-shuttle-upload")
        try:
            shutil.copy2(source, temporary)
            if temporary.stat().st_size != source.stat().st_size:
                raise BackendError("Copied file size does not match the source file.")
            os.replace(temporary, destination)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise BackendError(str(exc)) from exc
        if progress:
            progress(source.stat().st_size, source.stat().st_size)


def require_paramiko() -> None:
    if paramiko is None:
        raise DependencyError(
            "SFTP support requires Paramiko. Install it with 'python -m pip install paramiko', "
            "or use a packaged CNC File Shuttle release."
        )


def private_key_requires_passphrase(path: str) -> bool:
    require_paramiko()
    try:
        paramiko.PKey.from_path(Path(path).expanduser())
        return False
    except paramiko.PasswordRequiredException:
        return True
    except (OSError, ValueError, paramiko.SSHException) as exc:
        raise BackendError(f"The selected SSH private key could not be read: {exc}") from exc


def generate_ed25519_keypair(
    private_path: Path,
    passphrase: str = "",
    comment: str = "cnc-file-shuttle",
) -> tuple[Path, Path, str]:
    """Generate a standard OpenSSH Ed25519 private/public key pair."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.exceptions import UnsupportedAlgorithm

    private_path = private_path.expanduser()
    public_path = private_path.with_name(private_path.name + ".pub")
    if private_path.exists() or public_path.exists():
        raise BackendError("That key filename is already in use. Choose another filename.")
    private_path.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    encryption = (
        serialization.BestAvailableEncryption(passphrase.encode("utf-8"))
        if passphrase
        else serialization.NoEncryption()
    )
    try:
        private_bytes = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.OpenSSH,
            encryption_algorithm=encryption,
        )
    except UnsupportedAlgorithm as exc:
        raise DependencyError(
            "Encrypted OpenSSH keys require the bcrypt component installed with Paramiko."
        ) from exc
    public_bytes = key.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    )
    try:
        private_path.write_bytes(private_bytes)
        os.chmod(private_path, stat.S_IRUSR | stat.S_IWUSR)
        public_line = public_bytes.decode("ascii") + f" {comment}\n"
        public_path.write_text(public_line, encoding="ascii")
    except Exception:
        private_path.unlink(missing_ok=True)
        public_path.unlink(missing_ok=True)
        raise
    fingerprint = "SHA256:" + base64.b64encode(
        hashlib.sha256(base64.b64decode(public_bytes.split()[1])).digest()
    ).decode("ascii").rstrip("=")
    return private_path, public_path, fingerprint


class SftpBackend(TransferBackend):
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        remote_root: str,
        known_hosts_path: Path,
        *,
        auth_mode: str = "ssh_key",
        key_path: str = "",
        secret: str = "",
        timeout: float = 10.0,
    ) -> None:
        require_paramiko()
        self.host = host.strip()
        self.port = int(port)
        self.username = username.strip()
        self.remote_root = PurePosixPath(remote_root.strip() or "/")
        if not self.remote_root.is_absolute() or ".." in self.remote_root.parts:
            raise BackendError("Remote root must be an absolute Linux path without '..'.")
        self.known_hosts_path = known_hosts_path
        self.auth_mode = auth_mode
        self.key_path = str(Path(key_path).expanduser()) if key_path.strip() else ""
        self.secret = secret
        self.timeout = timeout
        self.client = None
        self.sftp = None

    @property
    def host_key_name(self) -> str:
        return self.host if self.port == 22 else f"[{self.host}]:{self.port}"

    @staticmethod
    def probe_host_key(host: str, port: int = 22, timeout: float = 10.0):
        require_paramiko()
        sock = socket.create_connection((host, int(port)), timeout=timeout)
        transport = paramiko.Transport(sock)
        try:
            transport.start_client(timeout=timeout)
            return transport.get_remote_server_key()
        finally:
            transport.close()
            sock.close()

    @staticmethod
    def fingerprint(key) -> str:
        return "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode("ascii").rstrip("=")

    def trusted_host_key(self):
        keys = paramiko.HostKeys()
        if self.known_hosts_path.exists():
            keys.load(str(self.known_hosts_path))
        return keys.lookup(self.host_key_name)

    def trust_host_key(self, key) -> None:
        self.known_hosts_path.parent.mkdir(parents=True, exist_ok=True)
        keys = paramiko.HostKeys()
        if self.known_hosts_path.exists():
            keys.load(str(self.known_hosts_path))
        keys.add(self.host_key_name, key.get_name(), key)
        keys.save(str(self.known_hosts_path))
        os.chmod(self.known_hosts_path, stat.S_IRUSR | stat.S_IWUSR)

    def forget_host_key(self) -> bool:
        if not self.known_hosts_path.exists():
            return False
        keys = paramiko.HostKeys()
        keys.load(str(self.known_hosts_path))
        if self.host_key_name not in keys:
            return False
        keys.pop(self.host_key_name)
        keys.save(str(self.known_hosts_path))
        return True

    def verify_or_raise_host_key(self) -> None:
        remote = self.probe_host_key(self.host, self.port, self.timeout)
        known = self.trusted_host_key()
        if not known:
            raise UnknownHostKeyError(
                f"This computer has not been trusted yet. Fingerprint: {self.fingerprint(remote)}"
            )
        expected = known.get(remote.get_name())
        if expected is None or expected != remote:
            raise UnknownHostKeyError(
                "The SSH identity at this address has changed. Do not connect until you verify the machine."
            )

    def connect(self) -> None:
        if not self.host or not self.username:
            raise BackendError("Host/IP and username are required for SFTP.")
        if not self.trusted_host_key():
            raise UnknownHostKeyError("This LinuxCNC computer has not been trusted yet.")
        client = paramiko.SSHClient()
        client.load_host_keys(str(self.known_hosts_path))
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        kwargs = dict(
            hostname=self.host,
            port=self.port,
            username=self.username,
            timeout=self.timeout,
            banner_timeout=self.timeout,
            auth_timeout=self.timeout,
        )
        if self.auth_mode == "password":
            kwargs.update(password=self.secret, allow_agent=False, look_for_keys=False)
        else:
            kwargs.update(
                key_filename=self.key_path or None,
                passphrase=self.secret or None,
                allow_agent=True,
                look_for_keys=not bool(self.key_path),
            )
        try:
            client.connect(**kwargs)
            self.client = client
            self.sftp = client.open_sftp()
        except paramiko.BadHostKeyException as exc:
            client.close()
            raise UnknownHostKeyError(
                "The SSH identity at this address has changed. Do not connect until you verify the machine."
            ) from exc
        except paramiko.AuthenticationException as exc:
            client.close()
            raise AuthenticationError("The SSH key, username, or password was rejected.") from exc
        except (OSError, paramiko.SSHException) as exc:
            client.close()
            raise BackendError(str(exc)) from exc
        finally:
            self.secret = ""

    def close(self) -> None:
        if self.sftp is not None:
            self.sftp.close()
            self.sftp = None
        if self.client is not None:
            self.client.close()
            self.client = None

    def folder_for(self, subfolder: str = "") -> PurePosixPath:
        return self.remote_root.joinpath(*safe_subfolder_parts(subfolder))

    def destination_for(self, filename: str, subfolder: str = "") -> PurePosixPath:
        return self.folder_for(subfolder) / filename

    def list_directories(self, subfolder: str = "") -> tuple[str, ...]:
        folder = self.folder_for(subfolder)
        try:
            entries = self._require_sftp().listdir_attr(str(folder))
        except OSError as exc:
            raise BackendError(f"Could not list remote folder {folder}: {exc}") from exc
        return tuple(sorted(
            (
                entry.filename
                for entry in entries
                if entry.filename not in {".", ".."}
                and entry.st_mode is not None
                and stat.S_ISDIR(entry.st_mode)
            ),
            key=str.casefold,
        ))

    def _require_sftp(self):
        if self.sftp is None:
            raise BackendError("The SFTP connection is not open.")
        return self.sftp

    def _require_client(self):
        if self.client is None:
            raise BackendError("The SSH connection is not open.")
        return self.client

    def _mkdir_p(self, folder: PurePosixPath) -> None:
        sftp = self._require_sftp()
        current = PurePosixPath("/") if folder.is_absolute() else PurePosixPath(".")
        for part in folder.parts:
            if part in {"/", ".", ""}:
                continue
            current /= part
            try:
                attrs = sftp.stat(str(current))
                if not stat.S_ISDIR(attrs.st_mode):
                    raise BackendError(f"Remote path is not a folder: {current}")
            except FileNotFoundError:
                sftp.mkdir(str(current))

    def test_target(self, subfolder: str = "") -> tuple[bool, str]:
        folder = self.folder_for(subfolder)
        try:
            self._mkdir_p(folder)
            marker = folder / ".cnc_file_shuttle_write_test"
            with self._require_sftp().file(str(marker), "wb") as handle:
                handle.write(b"")
            self._require_sftp().remove(str(marker))
        except Exception as exc:
            return False, f"Remote program folder is not writable: {exc}"
        return True, f"SFTP target ready: {folder}"

    def exists(self, destination: TargetPath) -> bool:
        try:
            self._require_sftp().stat(str(destination))
            return True
        except FileNotFoundError:
            return False

    def copy_file(self, source: Path, destination: TargetPath, progress: ProgressCallback | None = None) -> None:
        if not source.is_file():
            raise BackendError(f"Source file is unavailable: {source}")
        destination = PurePosixPath(str(destination))
        self._mkdir_p(destination.parent)
        temporary = destination.with_name(f".{destination.name}.cnc-file-shuttle-upload")
        try:
            if self.exists(temporary):
                self._require_sftp().remove(str(temporary))
            self._require_sftp().put(str(source), str(temporary), callback=progress, confirm=True)
            remote_size = self._require_sftp().stat(str(temporary)).st_size
            if remote_size != source.stat().st_size:
                raise BackendError("Uploaded file size does not match the source file.")
            try:
                self._require_sftp().posix_rename(str(temporary), str(destination))
            except (AttributeError, OSError):
                if self.exists(destination):
                    self._require_sftp().remove(str(destination))
                self._require_sftp().rename(str(temporary), str(destination))
        except Exception as exc:
            try:
                if self.exists(temporary):
                    self._require_sftp().remove(str(temporary))
            except Exception:
                pass
            raise BackendError(str(exc)) from exc

    def install_public_key(self, public_key_line: str) -> None:
        """Install a public key using the currently authenticated SFTP session."""
        sftp = self._require_sftp()
        home = PurePosixPath(sftp.normalize("."))
        ssh_dir = home / ".ssh"
        authorized = ssh_dir / "authorized_keys"
        self._mkdir_p(ssh_dir)
        try:
            sftp.chmod(str(ssh_dir), 0o700)
            with sftp.file(str(authorized), "rb") as handle:
                existing = handle.read().decode("utf-8", errors="replace")
        except FileNotFoundError:
            existing = ""
        key_parts = public_key_line.strip().split()
        identity = " ".join(key_parts[:2])
        existing_identities = {" ".join(line.strip().split()[:2]) for line in existing.splitlines() if line.strip()}
        if identity not in existing_identities:
            content = existing.rstrip("\n")
            if content:
                content += "\n"
            content += public_key_line.strip() + "\n"
            with sftp.file(str(authorized), "wb") as handle:
                handle.write(content.encode("utf-8"))
        sftp.chmod(str(authorized), 0o600)

    def install_status_helper(self, helper_source: bytes) -> PurePosixPath:
        """Install/update the read-only LinuxCNC status helper through SFTP."""
        sftp = self._require_sftp()
        home = PurePosixPath(sftp.normalize("."))
        helper_dir = home / ".local" / "share" / "cnc-file-shuttle"
        helper_path = helper_dir / "linuxcnc_status_helper.py"
        temporary = helper_dir / ".linuxcnc_status_helper.py.upload"
        self._mkdir_p(helper_dir)
        try:
            with sftp.file(str(helper_path), "rb") as handle:
                if handle.read() == helper_source:
                    sftp.chmod(str(helper_path), 0o700)
                    return helper_path
        except FileNotFoundError:
            pass
        try:
            with sftp.file(str(temporary), "wb") as handle:
                handle.write(helper_source)
            sftp.chmod(str(temporary), 0o700)
            try:
                sftp.posix_rename(str(temporary), str(helper_path))
            except (AttributeError, OSError):
                if self.exists(helper_path):
                    sftp.remove(str(helper_path))
                sftp.rename(str(temporary), str(helper_path))
        except Exception as exc:
            try:
                if self.exists(temporary):
                    sftp.remove(str(temporary))
            except Exception:
                pass
            raise BackendError(f"Could not install the LinuxCNC status helper: {exc}") from exc
        return helper_path

    def query_linuxcnc_status(self, helper_path: PurePosixPath) -> dict:
        """Run one helper snapshot over the authenticated SSH connection."""
        command = f"python3 {shlex.quote(str(helper_path))}"
        try:
            stdin, stdout, stderr = self._require_client().exec_command(command, timeout=self.timeout)
            stdin.close()
            stdout.channel.settimeout(self.timeout)
            output = stdout.read().decode("utf-8", errors="replace")
            error_output = stderr.read().decode("utf-8", errors="replace").strip()
            exit_status = stdout.channel.recv_exit_status()
        except (OSError, socket.timeout, paramiko.SSHException) as exc:
            raise BackendError(f"LinuxCNC status query failed: {exc}") from exc
        if exit_status != 0:
            raise BackendError(error_output or f"LinuxCNC status helper exited with code {exit_status}.")
        lines = [line for line in output.splitlines() if line.strip()]
        if not lines:
            raise BackendError("LinuxCNC status helper returned no data.")
        try:
            payload = json.loads(lines[-1])
        except (TypeError, ValueError) as exc:
            raise BackendError("LinuxCNC status helper returned invalid data.") from exc
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise BackendError("LinuxCNC status helper returned an unsupported response.")
        return payload
