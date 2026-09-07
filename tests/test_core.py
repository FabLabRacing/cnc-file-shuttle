import contextlib
import io
import json
import stat
import sys
import tempfile
import types
import unittest
from unittest import mock
from pathlib import Path, PurePosixPath

from cnc_file_shuttle.backends import BackendError, LocalFolderBackend, SftpBackend, generate_ed25519_keypair
from cnc_file_shuttle.models import (
    MachineProfile,
    QueueItem,
    QueueStatus,
    overwrite_mode_label,
    overwrite_mode_value,
    overwrite_session_for_mode,
    requeue_finished,
)
from cnc_file_shuttle.storage import ProfileStore
from cnc_file_shuttle.status import LinuxCncStatus, status_helper_source
from cnc_file_shuttle.remote import linuxcnc_status_helper
from cnc_file_shuttle.validation import filename_warnings, validate_subfolder


class CoreTests(unittest.TestCase):
    def test_profile_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ProfileStore(Path(temp) / "profiles.json")
            expected = MachineProfile(name="Plasma", root_folder=temp, target_subfolder="CustomerA")
            store.save([expected])
            self.assertEqual(store.load(), [expected])

    def test_sftp_profile_round_trip_without_secret(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ProfileStore(Path(temp) / "profiles.json")
            expected = MachineProfile(
                name="Shop Plasma",
                backend="sftp",
                remote_root="/home/cnc/linuxcnc/nc_files",
                host="192.168.1.60",
                username="cnc",
                auth_mode="ssh_key",
                key_path="/keys/cnc_file_shuttle_ed25519",
            )
            store.save([expected])
            loaded = store.load()[0]
            self.assertEqual(loaded, expected)
            self.assertNotIn("password", store.path.read_text(encoding="utf-8").lower())

    def test_profile_round_trip_preserves_overwrite_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ProfileStore(Path(temp) / "profiles.json")
            expected = MachineProfile(
                name="Router",
                root_folder=temp,
                overwrite_mode="always",
            )
            store.save([expected])
            self.assertEqual(store.load()[0].overwrite_mode, "always")

    def test_overwrite_mode_mapping_and_safe_fallback(self):
        self.assertEqual(overwrite_mode_label("always"), "Always overwrite")
        self.assertEqual(overwrite_mode_value("Skip existing"), "skip")
        self.assertEqual(overwrite_session_for_mode("ask"), None)
        self.assertEqual(overwrite_session_for_mode("always"), "overwrite_all")
        self.assertEqual(overwrite_session_for_mode("skip"), "skip_all")
        self.assertEqual(overwrite_mode_label("unexpected"), "Ask each time")
        self.assertEqual(overwrite_mode_value("unexpected"), "ask")
        self.assertEqual(
            MachineProfile.from_dict({"name": "Old profile", "overwrite_mode": "unexpected"}).overwrite_mode,
            "ask",
        )

    def test_requeue_finished_items(self):
        items = [
            QueueItem(Path("done.ngc"), "old", QueueStatus.DONE, "Copied", "/old/done.ngc"),
            QueueItem(Path("skipped.ngc"), "old", QueueStatus.SKIPPED, "Exists", "/old/skipped.ngc"),
            QueueItem(Path("failed.ngc"), "old", QueueStatus.FAILED, "Network error", "/old/failed.ngc"),
            QueueItem(Path("pending.ngc"), "old", QueueStatus.PENDING),
        ]
        self.assertEqual(requeue_finished(items, "new/job"), 3)
        self.assertEqual([item.status for item in items], [QueueStatus.PENDING] * 4)
        self.assertEqual([item.target_subfolder for item in items[:3]], ["new/job"] * 3)
        self.assertTrue(all(not item.detail and not item.target_display for item in items[:3]))

    def test_sftp_directory_listing_returns_folders_only(self):
        backend = object.__new__(SftpBackend)
        backend.remote_root = PurePosixPath("/nc_files")
        backend.sftp = types.SimpleNamespace(
            listdir_attr=lambda _path: [
                types.SimpleNamespace(filename="Zulu", st_mode=stat.S_IFDIR),
                types.SimpleNamespace(filename="program.ngc", st_mode=stat.S_IFREG),
                types.SimpleNamespace(filename="alpha", st_mode=stat.S_IFDIR),
            ]
        )
        self.assertEqual(backend.list_directories(""), ("alpha", "Zulu"))

    def test_local_copy_and_size_check(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.ngc"
            source.write_text("G0 X0 Y0\n", encoding="ascii")
            backend = LocalFolderBackend(str(root / "machine"))
            (root / "machine").mkdir()
            destination = backend.destination_for(source.name, "jobs/today")
            backend.copy_file(source, destination)
            self.assertEqual(destination.read_bytes(), source.read_bytes())

    def test_subfolder_rejects_escape_and_absolute_paths(self):
        self.assertIsNotNone(validate_subfolder("../outside"))
        self.assertIsNotNone(validate_subfolder("/absolute"))
        self.assertIsNotNone(validate_subfolder("C:\\absolute"))
        self.assertIsNone(validate_subfolder("Customer A/Job-12"))
        with tempfile.TemporaryDirectory() as temp:
            backend = LocalFolderBackend(temp)
            with self.assertRaises(BackendError):
                backend.destination_for("part.ngc", "../outside")

    def test_filename_warnings(self):
        self.assertEqual(filename_warnings(Path("Bracket Left.ngc")), [])
        self.assertTrue(filename_warnings(Path("café.ngc")))
        self.assertTrue(filename_warnings(Path("part.stl")))

    def test_ed25519_key_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            private_path = Path(temp) / "shuttle_key"
            private_key, public_key, fingerprint = generate_ed25519_keypair(
                private_path, "", "cnc-file-shuttle@test"
            )
            self.assertTrue(private_key.exists())
            self.assertTrue(public_key.exists())
            self.assertTrue(fingerprint.startswith("SHA256:"))
            self.assertTrue(public_key.read_text(encoding="ascii").startswith("ssh-ed25519 "))
            with self.assertRaises(BackendError):
                generate_ed25519_keypair(private_path)

    def test_linuxcnc_status_display_and_active_file(self):
        status = LinuxCncStatus.from_payload({
            "linuxcnc": "running",
            "state": "program_running",
            "filename": "Bracket-Left.ngc",
            "file_path": "/home/cnc/linuxcnc/nc_files/Bracket-Left.ngc",
            "current_line": 428,
        })
        self.assertEqual(status.display_state, "Program Running")
        self.assertEqual(status.display_detail, "Bracket-Left.ngc — line 428")
        self.assertTrue(status.is_active_path("/home/cnc/linuxcnc/nc_files/Bracket-Left.ngc"))
        self.assertFalse(status.is_active_path("/home/cnc/linuxcnc/nc_files/Other.ngc"))

    def test_status_helper_is_packaged_and_compiles(self):
        source = status_helper_source()
        self.assertTrue(source.startswith(b"#!/usr/bin/env python3"))
        compile(source, "linuxcnc_status_helper.py", "exec")

    def test_status_helper_reports_running_program(self):
        class FakeStat:
            task_state = 3
            interp_state = 11
            paused = False
            task_paused = False
            state = 20
            file = "/home/cnc/linuxcnc/nc_files/Test.ngc"
            motion_line = 17
            current_line = 18

            def poll(self):
                return None

        fake_linuxcnc = types.SimpleNamespace(
            STATE_ESTOP=1,
            STATE_ESTOP_RESET=2,
            STATE_ON=3,
            STATE_OFF=4,
            INTERP_IDLE=10,
            INTERP_READING=11,
            INTERP_PAUSED=12,
            INTERP_WAITING=13,
            RCS_ERROR=21,
            stat=FakeStat,
        )
        output = io.StringIO()
        with mock.patch.dict(sys.modules, {"linuxcnc": fake_linuxcnc}):
            with contextlib.redirect_stdout(output):
                linuxcnc_status_helper.main()
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["state"], "program_running")
        self.assertEqual(payload["filename"], "Test.ngc")
        self.assertEqual(payload["current_line"], 17)


if __name__ == "__main__":
    unittest.main()
