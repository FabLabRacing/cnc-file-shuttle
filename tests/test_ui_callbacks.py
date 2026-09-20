"""Exercise real UI callbacks with stand-in widgets; no display or SSH needed."""

from contextlib import ExitStack
from pathlib import PurePosixPath
from types import SimpleNamespace
import unittest
from unittest import mock

from cnc_file_shuttle import app
from cnc_file_shuttle.backends import BackendError


class UiCallbackTests(unittest.TestCase):
    def run_browser(self, listing, scenario, start=""):
        backend = mock.Mock()
        backend.remote_root = PurePosixPath("/nc_files")
        backend.folder_for.side_effect = lambda path: backend.remote_root / path
        backend.list_directories.side_effect = listing
        window = mock.Mock()
        window.target_subfolder.get.return_value = start
        folder_list = mock.Mock()
        visible = []
        folder_list.delete.side_effect = lambda *_: visible.clear()
        folder_list.insert.side_effect = lambda _, name: visible.append(name)
        folder_list.curselection.return_value = (0,)
        folder_list.get.side_effect = lambda index: visible[index]
        path_text = mock.Mock()
        buttons = {}

        def button(*args, **kwargs):
            buttons[kwargs["text"]] = kwargs["command"]
            return mock.Mock()

        with ExitStack() as stack:
            for name in ("Toplevel", "Frame"):
                stack.enter_context(mock.patch.object(app.tk, name))
            stack.enter_context(mock.patch.object(app.tk, "Listbox", return_value=folder_list))
            stack.enter_context(mock.patch.object(app.tk, "StringVar", return_value=path_text))
            for name in ("Label", "Scrollbar"):
                stack.enter_context(mock.patch.object(app.ttk, name))
            stack.enter_context(mock.patch.object(app.ttk, "Button", side_effect=button))
            error = stack.enter_context(mock.patch.object(app.messagebox, "showerror"))
            stack.enter_context(mock.patch.object(app.simpledialog, "askstring", return_value="new"))
            window.wait_window.side_effect = lambda _: scenario(buttons, visible, path_text, error)
            selected = app.CNCFileShuttleApp._show_remote_folder_browser(window, backend)
        return selected, backend

    def test_failed_open_keeps_visible_and_selected_folder(self):
        for reason in ("Permission denied", "No such file"):
            with self.subTest(reason=reason):
                def scenario(buttons, visible, path, error):
                    buttons["Open"]()
                    error.assert_called_once()
                    self.assertEqual(visible, ["unavailable"])
                    self.assertEqual(path.set.call_args.args[0], "/nc_files")
                    buttons["Select This Folder"]()

                selected, _ = self.run_browser(
                    [("unavailable",), BackendError(reason)], scenario
                )
                self.assertEqual(selected, "")

    def test_failed_up_keeps_child_selected(self):
        def scenario(buttons, visible, path, error):
            buttons["Up"]()
            error.assert_called_once()
            self.assertEqual(path.set.call_args.args[0], "/nc_files/jobs")
            buttons["Select This Folder"]()

        selected, _ = self.run_browser([(), BackendError("Permission denied")], scenario, "jobs")
        self.assertEqual(selected, "jobs")

    def test_created_folder_listing_failure_preserves_previous_selection(self):
        def scenario(buttons, visible, path, error):
            buttons["New Folder..."]()
            error.assert_called_once()
            self.assertEqual(visible, ["existing"])
            self.assertEqual(path.set.call_args.args[0], "/nc_files/jobs")
            buttons["Select This Folder"]()

        selected, backend = self.run_browser(
            [("existing",), BackendError("Permission denied")], scenario, "jobs"
        )
        backend.create_directory.assert_called_once_with("jobs/new")
        self.assertEqual(selected, "jobs")

    def test_successful_open_up_and_create_select_new_folder(self):
        def scenario(buttons, visible, path, error):
            buttons["Open"]()
            self.assertEqual(path.set.call_args.args[0], "/nc_files/jobs")
            buttons["Up"]()
            self.assertEqual(path.set.call_args.args[0], "/nc_files")
            buttons["New Folder..."]()
            self.assertEqual(path.set.call_args.args[0], "/nc_files/new")
            error.assert_not_called()
            buttons["Select This Folder"]()

        selected, backend = self.run_browser([("jobs",), (), ("jobs",), ()], scenario)
        backend.create_directory.assert_called_once_with("new")
        self.assertEqual(selected, "new")

    def wheel_callback(self, system):
        window = mock.Mock()
        window.tk.call.return_value = system
        with ExitStack() as stack:
            for name in ("Frame", "Label"):
                stack.enter_context(mock.patch.object(app.tk, name))
            canvas = stack.enter_context(mock.patch.object(app.tk, "Canvas")).return_value
            for name in ("Label", "Scrollbar"):
                stack.enter_context(mock.patch.object(app.ttk, name))
            app.CNCFileShuttleApp._build_scrollable_ui(window)
        bindings = {call.args[0]: call.args[1] for call in window.bind.call_args_list}
        widget = mock.Mock()
        widget.master = window
        widget.winfo_toplevel.return_value = window
        widget.winfo_class.return_value = "Label"
        return bindings, canvas, widget

    def test_platform_wheel_events(self):
        for system, delta in (("win32", -120), ("aqua", -1), ("x11", -120)):
            with self.subTest(system=system):
                bindings, canvas, widget = self.wheel_callback(system)
                bindings["<MouseWheel>"](SimpleNamespace(widget=widget, num="??", delta=delta))
                canvas.yview_scroll.assert_called_once_with(1, "units")
                if system == "x11":
                    bindings["<Button-4>"](SimpleNamespace(widget=widget, num=4))
                    canvas.yview_scroll.assert_called_with(-1, "units")
                    bindings["<Button-5>"](SimpleNamespace(widget=widget, num=5))
                    canvas.yview_scroll.assert_called_with(1, "units")

    def test_small_windows_deltas_accumulate(self):
        bindings, canvas, widget = self.wheel_callback("win32")
        event = SimpleNamespace(widget=widget, num="??", delta=-30)
        for _ in range(3):
            bindings["<MouseWheel>"](event)
        canvas.yview_scroll.assert_not_called()
        bindings["<MouseWheel>"](event)
        canvas.yview_scroll.assert_called_once_with(1, "units")

    def test_nested_controls_and_other_windows_do_not_scroll_main(self):
        bindings, canvas, widget = self.wheel_callback("win32")
        event = SimpleNamespace(widget=widget, num="??", delta=-120)
        for widget_class in ("Listbox", "Text", "Treeview", "TCombobox", "Scrollbar", "TScrollbar"):
            widget.winfo_class.return_value = widget_class
            bindings["<MouseWheel>"](event)
        widget.winfo_class.return_value = "Label"
        widget.winfo_toplevel.return_value = mock.Mock()
        bindings["<MouseWheel>"](event)
        canvas.yview_scroll.assert_not_called()


if __name__ == "__main__":
    unittest.main()
