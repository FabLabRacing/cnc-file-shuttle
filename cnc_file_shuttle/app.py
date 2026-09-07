from __future__ import annotations

import datetime as dt
import socket
import queue
import threading
import traceback
import tkinter as tk
from pathlib import Path, PurePosixPath
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import __version__
from .backends import (
    AuthenticationError,
    BackendError,
    DependencyError,
    LocalFolderBackend,
    SftpBackend,
    TransferBackend,
    UnknownHostKeyError,
    generate_ed25519_keypair,
    private_key_requires_passphrase,
)
from .models import (
    OVERWRITE_MODE_LABELS,
    MachineProfile,
    QueueItem,
    QueueStatus,
    human_size,
    overwrite_mode_label,
    overwrite_mode_value,
    overwrite_session_for_mode,
    requeue_finished,
)
from .status import LinuxCncStatus, status_helper_source
from .storage import ProfileStore, app_data_dir
from .validation import filename_warnings, validate_subfolder


BG = "#171a1f"
PANEL = "#22262d"
ENTRY = "#111418"
TEXT = "#edf1f5"
MUTED = "#aeb7c2"
ACCENT = "#3f91d1"
GOOD = "#58b879"
WARN = "#e2ae49"
BAD = "#df6262"


class CNCFileShuttleApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"CNC File Shuttle {__version__}")
        self.geometry("1080x780")
        self.minsize(860, 650)
        self.configure(bg=BG)

        self.store = ProfileStore()
        self.profiles = self.store.load()
        self.items: list[QueueItem] = []
        self.events: queue.Queue[tuple] = queue.Queue()
        self.copy_thread: threading.Thread | None = None
        self.cancel_requested = False
        self.overwrite_session: str | None = None
        self.decision_events: dict[int, threading.Event] = {}
        self.decision_values: dict[int, str] = {}
        self.monitor_thread: threading.Thread | None = None
        self.monitor_stop = threading.Event()
        self.monitor_generation = 0
        self.auto_connect_job: str | None = None
        self.last_machine_status: LinuxCncStatus | None = None

        self.profile_name = tk.StringVar()
        self.backend_type = tk.StringVar(value="Local / mounted folder")
        self.root_folder = tk.StringVar()
        self.host = tk.StringVar()
        self.port = tk.StringVar(value="22")
        self.username = tk.StringVar()
        self.remote_root = tk.StringVar(value="/home/cnc/linuxcnc/nc_files")
        self.auth_mode = tk.StringVar(value="SSH key")
        self.key_path = tk.StringVar()
        self.target_subfolder = tk.StringVar()
        self.overwrite_mode = tk.StringVar(value=overwrite_mode_label("ask"))
        self.status_text = tk.StringVar(value="Ready")
        self.target_preview = tk.StringVar(value="Add a file to preview its exact destination.")
        self.validation_text = tk.StringVar(value="Select or create a machine profile.")
        self.auto_clear = tk.BooleanVar(value=False)
        self.controller_status = tk.StringVar(value="Not Connected")
        self.linuxcnc_status = tk.StringVar(value="LinuxCNC Not Checked")
        self.machine_detail = tk.StringVar(value="Select an SFTP profile, then connect to monitor.")
        self.status_updated = tk.StringVar(value="")

        self._configure_styles()
        self._build_scrollable_ui()
        self.target_subfolder.trace_add("write", self._target_changed)
        self.root_folder.trace_add("write", self._target_changed)
        self.remote_root.trace_add("write", self._target_changed)
        self.backend_type.trace_add("write", self._backend_changed)
        self.after(100, self._poll_events)
        self._refresh_profiles(select_first=True)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=TEXT, font=("TkDefaultFont", 10))
        style.configure("Panel.TLabelframe", background=PANEL, foreground=TEXT, bordercolor="#3a414c")
        style.configure("Panel.TLabelframe.Label", background=PANEL, foreground=TEXT, font=("TkDefaultFont", 10, "bold"))
        style.configure("TLabel", background=PANEL, foreground=TEXT)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Status.TLabel", background=BG, foreground=GOOD, font=("TkDefaultFont", 10, "bold"))
        style.configure("TButton", padding=(10, 6), background="#353b45", foreground=TEXT)
        style.map("TButton", background=[("active", "#46505d"), ("disabled", "#2b3037")])
        style.configure("Accent.TButton", background=ACCENT, foreground="white", font=("TkDefaultFont", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#55a4df")])
        style.configure("TEntry", fieldbackground=ENTRY, foreground=TEXT, insertcolor=TEXT)
        style.configure("TCombobox", fieldbackground=ENTRY, foreground=TEXT, arrowcolor=TEXT)
        style.map("TCombobox", fieldbackground=[("readonly", ENTRY)], foreground=[("readonly", TEXT)])
        style.configure("Treeview", background=ENTRY, fieldbackground=ENTRY, foreground=TEXT, rowheight=27, borderwidth=0)
        style.configure("Treeview.Heading", background="#303640", foreground=TEXT, font=("TkDefaultFont", 9, "bold"))
        style.map("Treeview", background=[("selected", ACCENT)])
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT)

    def _build_scrollable_ui(self) -> None:
        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        self.content = tk.Frame(canvas, bg=BG)
        window_id = canvas.create_window((0, 0), window=self.content, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.content.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window_id, width=e.width))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))

        body = tk.Frame(self.content, bg=BG, padx=18, pady=16)
        body.pack(fill="both", expand=True)

        header = tk.Frame(body, bg=BG)
        header.pack(fill="x", pady=(0, 12))
        tk.Label(header, text="CNC FILE SHUTTLE", bg=BG, fg=TEXT, font=("TkDefaultFont", 20, "bold")).pack(side="left")
        tk.Label(header, text=f"v{__version__}", bg=BG, fg=MUTED, font=("TkDefaultFont", 10)).pack(side="left", padx=10, pady=(8, 0))
        ttk.Label(header, textvariable=self.status_text, style="Status.TLabel").pack(side="right", pady=(8, 0))

        self._build_profile_panel(body)
        self._build_machine_status_panel(body)
        self._build_target_panel(body)
        self._build_queue_panel(body)
        self._build_log_panel(body)

    def _panel(self, parent: tk.Widget, title: str) -> ttk.LabelFrame:
        panel = ttk.LabelFrame(parent, text=title, style="Panel.TLabelframe", padding=12)
        panel.pack(fill="x", pady=(0, 12))
        return panel

    def _build_profile_panel(self, parent: tk.Widget) -> None:
        panel = self._panel(parent, "Machine Profile")
        panel.columnconfigure(1, weight=1)
        panel.columnconfigure(3, weight=1)
        ttk.Label(panel, text="Profile").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        self.profile_combo = ttk.Combobox(panel, textvariable=self.profile_name)
        self.profile_combo.grid(row=0, column=1, sticky="ew", pady=4)
        self.profile_combo.bind("<<ComboboxSelected>>", self._load_selected_profile)
        ttk.Label(panel, text="Backend").grid(row=0, column=2, sticky="w", padx=(16, 8), pady=4)
        ttk.Combobox(panel, textvariable=self.backend_type, values=("Local / mounted folder", "SFTP / SSH"), state="readonly").grid(row=0, column=3, sticky="ew", pady=4)

        self.local_fields = tk.Frame(panel, bg=PANEL)
        self.local_fields.grid(row=1, column=0, columnspan=4, sticky="ew")
        self.local_fields.columnconfigure(1, weight=1)
        ttk.Label(self.local_fields, text="Root folder").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(self.local_fields, textvariable=self.root_folder).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Button(self.local_fields, text="Browse...", command=self._browse_root).grid(row=0, column=2, sticky="w", padx=(8, 0), pady=4)

        self.sftp_fields = tk.Frame(panel, bg=PANEL)
        self.sftp_fields.columnconfigure(1, weight=1)
        self.sftp_fields.columnconfigure(3, weight=1)
        ttk.Label(self.sftp_fields, text="Host / IP").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(self.sftp_fields, textvariable=self.host).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Label(self.sftp_fields, text="Port").grid(row=0, column=2, sticky="w", padx=(16, 8), pady=4)
        ttk.Entry(self.sftp_fields, textvariable=self.port, width=8).grid(row=0, column=3, sticky="w", pady=4)
        ttk.Label(self.sftp_fields, text="Username").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(self.sftp_fields, textvariable=self.username).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Label(self.sftp_fields, text="Remote root").grid(row=1, column=2, sticky="w", padx=(16, 8), pady=4)
        ttk.Entry(self.sftp_fields, textvariable=self.remote_root).grid(row=1, column=3, sticky="ew", pady=4)
        ttk.Label(self.sftp_fields, text="Authentication").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Combobox(self.sftp_fields, textvariable=self.auth_mode, values=("SSH key", "Password"), state="readonly").grid(row=2, column=1, sticky="ew", pady=4)
        ttk.Label(self.sftp_fields, text="Private key").grid(row=2, column=2, sticky="w", padx=(16, 8), pady=4)
        key_row = tk.Frame(self.sftp_fields, bg=PANEL)
        key_row.grid(row=2, column=3, sticky="ew", pady=4)
        key_row.columnconfigure(0, weight=1)
        ttk.Entry(key_row, textvariable=self.key_path).grid(row=0, column=0, sticky="ew")
        ttk.Button(key_row, text="Browse...", command=self._browse_key).grid(row=0, column=1, padx=(6, 0))

        buttons = tk.Frame(panel, bg=PANEL)
        buttons.grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))
        ttk.Button(buttons, text="New Profile", command=self._new_profile).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Save / Update", command=self._save_profile).pack(side="left", padx=6)
        ttk.Button(buttons, text="Delete", command=self._delete_profile).pack(side="left", padx=6)
        ttk.Button(buttons, text="Test Target", command=self._test_target).pack(side="left", padx=6)
        self.setup_key_button = ttk.Button(buttons, text="Set Up SSH Key...", command=self._setup_ssh_key)
        self.setup_key_button.pack(side="left", padx=6)
        self.forget_host_button = ttk.Button(buttons, text="Forget Host Trust...", command=self._forget_host_trust)
        self.forget_host_button.pack(side="left", padx=6)
        self._backend_changed()

    def _build_target_panel(self, parent: tk.Widget) -> None:
        panel = self._panel(parent, "Destination")
        panel.columnconfigure(1, weight=1)
        ttk.Label(panel, text="Target subfolder").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        target_row = tk.Frame(panel, bg=PANEL)
        target_row.grid(row=0, column=1, sticky="ew", pady=4)
        target_row.columnconfigure(0, weight=1)
        ttk.Entry(target_row, textvariable=self.target_subfolder).grid(row=0, column=0, sticky="ew")
        ttk.Button(target_row, text="Browse...", command=self._browse_target_subfolder).grid(
            row=0, column=1, padx=(6, 0)
        )
        ttk.Label(panel, text="If file exists").grid(row=0, column=2, sticky="w", padx=(16, 8), pady=4)
        ttk.Combobox(
            panel,
            textvariable=self.overwrite_mode,
            values=tuple(OVERWRITE_MODE_LABELS.values()),
            state="readonly",
            width=18,
        ).grid(row=0, column=3, sticky="ew", pady=4)
        ttk.Label(panel, text="Exact target preview").grid(row=1, column=0, sticky="nw", padx=(0, 8), pady=4)
        ttk.Label(panel, textvariable=self.target_preview, style="Muted.TLabel", wraplength=780).grid(row=1, column=1, columnspan=3, sticky="w", pady=4)
        self.validation_label = ttk.Label(panel, textvariable=self.validation_text, style="Muted.TLabel", wraplength=780)
        self.validation_label.grid(row=2, column=1, columnspan=3, sticky="w", pady=(2, 0))

    def _build_machine_status_panel(self, parent: tk.Widget) -> None:
        panel = self._panel(parent, "Machine Status — Read Only")
        panel.columnconfigure(1, weight=1)
        self.controller_status_label = tk.Label(
            panel, textvariable=self.controller_status, bg=PANEL, fg=MUTED,
            font=("TkDefaultFont", 11, "bold"), anchor="w"
        )
        self.controller_status_label.grid(row=0, column=0, sticky="w", padx=(0, 24))
        self.linuxcnc_status_label = tk.Label(
            panel, textvariable=self.linuxcnc_status, bg=PANEL, fg=MUTED,
            font=("TkDefaultFont", 11, "bold"), anchor="w"
        )
        self.linuxcnc_status_label.grid(row=0, column=1, sticky="w")
        ttk.Label(panel, textvariable=self.machine_detail, style="Muted.TLabel", wraplength=700).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(5, 0)
        )
        ttk.Label(panel, textvariable=self.status_updated, style="Muted.TLabel").grid(
            row=0, column=2, sticky="e", padx=(12, 8)
        )
        buttons = tk.Frame(panel, bg=PANEL)
        buttons.grid(row=0, column=3, rowspan=2, sticky="e")
        self.connect_status_button = ttk.Button(buttons, text="Connect / Monitor", command=self._connect_status_monitor)
        self.connect_status_button.pack(side="left", padx=(0, 6))
        self.disconnect_status_button = ttk.Button(buttons, text="Disconnect", command=self._disconnect_status_monitor)
        self.disconnect_status_button.pack(side="left")
        self._update_status_button_states()

    def _build_queue_panel(self, parent: tk.Widget) -> None:
        panel = self._panel(parent, "File Queue")
        tree_frame = tk.Frame(panel, bg=PANEL)
        tree_frame.pack(fill="both", expand=True)
        columns = ("order", "filename", "size", "target", "status")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=10, selectmode="extended")
        widths = {"order": 55, "filename": 230, "size": 90, "target": 500, "status": 90}
        labels = {"order": "Order", "filename": "Filename", "size": "Size", "target": "Target path", "status": "Status"}
        for column in columns:
            self.tree.heading(column, text=labels[column])
            self.tree.column(column, width=widths[column], stretch=column in {"filename", "target"})
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._update_preview())

        controls = tk.Frame(panel, bg=PANEL)
        controls.pack(fill="x", pady=(10, 0))
        self.send_button = ttk.Button(controls, text="Send Queue", style="Accent.TButton", command=self._start_queue)
        self.send_button.pack(side="right")
        ttk.Button(controls, text="Add Files...", command=self._add_files).pack(side="left", padx=(0, 5))
        ttk.Button(controls, text="Remove Selected", command=self._remove_selected).pack(side="left", padx=5)
        ttk.Button(controls, text="Clear Queue", command=self._clear_queue).pack(side="left", padx=5)
        ttk.Button(controls, text="Requeue Finished", command=self._requeue_finished).pack(side="left", padx=5)
        ttk.Button(controls, text="Move Up", command=lambda: self._move_selected(-1)).pack(side="left", padx=5)
        ttk.Button(controls, text="Move Down", command=lambda: self._move_selected(1)).pack(side="left", padx=5)
        options = tk.Frame(panel, bg=PANEL)
        options.pack(fill="x", pady=(5, 0))
        ttk.Checkbutton(options, text="Auto-clear completed queue", variable=self.auto_clear).pack(side="left")

    def _build_log_panel(self, parent: tk.Widget) -> None:
        panel = self._panel(parent, "Activity Log")
        self.log_box = tk.Text(panel, height=9, bg=ENTRY, fg=TEXT, insertbackground=TEXT, relief="flat", state="disabled", wrap="word")
        self.log_box.pack(fill="both", expand=True)
        self._log("CNC File Shuttle ready. Local-folder and SFTP development build.")

    def _log(self, message: str) -> None:
        stamp = dt.datetime.now().strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{stamp}] {message}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _browse_root(self) -> None:
        selected = filedialog.askdirectory(title="Select CNC program root folder")
        if selected:
            self.root_folder.set(selected)

    def _browse_key(self) -> None:
        selected = filedialog.askopenfilename(title="Select SSH private key", initialdir=str(Path.home() / ".ssh"))
        if selected:
            self.key_path.set(selected)

    def _browse_target_subfolder(self) -> None:
        if self.copy_thread and self.copy_thread.is_alive():
            messagebox.showinfo("Queue active", "Wait for the current copy to finish before changing its destination.")
            return
        if not self.backend_type.get().startswith("SFTP"):
            self._browse_local_target_subfolder()
            return
        self._browse_sftp_target_subfolder()

    def _browse_local_target_subfolder(self) -> None:
        root_text = self.root_folder.get().strip()
        if not root_text:
            messagebox.showwarning("Root folder required", "Select the machine's root destination folder first.")
            return
        root = Path(root_text).expanduser()
        if not root.is_dir():
            messagebox.showwarning("Root folder unavailable", f"The profile root folder is not available:\n\n{root}")
            return
        current_subfolder = self.target_subfolder.get()
        initial = root
        if validate_subfolder(current_subfolder) is None:
            initial = root.joinpath(*filter(None, current_subfolder.replace("\\", "/").split("/")))
        while initial != root and not initial.is_dir():
            initial = initial.parent
        selected = filedialog.askdirectory(
            title="Select destination folder",
            initialdir=str(initial if initial.is_dir() else root),
            mustexist=True,
            parent=self,
        )
        if not selected:
            return
        try:
            relative = Path(selected).resolve().relative_to(root.resolve())
        except ValueError:
            messagebox.showwarning(
                "Folder outside profile root",
                "Choose the root folder itself or one of its subfolders.",
            )
            return
        self.target_subfolder.set("" if relative == Path(".") else relative.as_posix())

    def _browse_sftp_target_subfolder(self) -> None:
        try:
            backend = self._backend(prompt_secret=True)
        except BackendError as exc:
            messagebox.showerror("SFTP unavailable", self._friendly_connection_error(exc))
            return
        if not isinstance(backend, SftpBackend):
            messagebox.showwarning("SFTP profile incomplete", self._validate_sftp_fields() or "Complete the SFTP profile.")
            return
        try:
            if not self._ensure_host_trusted(backend):
                return
            backend.connect()
            selected = self._show_remote_folder_browser(backend)
        except Exception as exc:
            messagebox.showerror("Remote folder browser", self._friendly_connection_error(exc))
            return
        finally:
            backend.close()
        if selected is not None:
            self.target_subfolder.set(selected)

    def _show_remote_folder_browser(self, backend: SftpBackend) -> str | None:
        current_subfolder = self.target_subfolder.get()
        if validate_subfolder(current_subfolder) is not None:
            current_subfolder = ""
        current_parts = list(backend.folder_for(current_subfolder).relative_to(backend.remote_root).parts)
        current = "/".join(current_parts)
        try:
            directories = backend.list_directories(current)
        except BackendError:
            current_parts = []
            directories = backend.list_directories("")

        dialog = tk.Toplevel(self)
        dialog.title("Select LinuxCNC destination folder")
        dialog.geometry("600x430")
        dialog.minsize(450, 320)
        dialog.configure(bg=PANEL)
        dialog.transient(self)
        dialog.grab_set()
        selected_value: dict[str, str | None] = {"value": None}
        path_text = tk.StringVar()

        ttk.Label(dialog, text="Folder under profile root", style="Muted.TLabel").pack(
            anchor="w", padx=16, pady=(14, 3)
        )
        ttk.Label(dialog, textvariable=path_text, wraplength=550).pack(anchor="w", padx=16, pady=(0, 8))
        list_frame = tk.Frame(dialog, bg=PANEL)
        list_frame.pack(fill="both", expand=True, padx=16)
        folder_list = tk.Listbox(
            list_frame,
            bg=ENTRY,
            fg=TEXT,
            selectbackground=ACCENT,
            selectforeground="white",
            relief="flat",
            activestyle="none",
            exportselection=False,
        )
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=folder_list.yview)
        folder_list.configure(yscrollcommand=scrollbar.set)
        folder_list.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def refresh(entries: tuple[str, ...] | None = None) -> None:
            nonlocal directories
            relative = "/".join(current_parts)
            if entries is None:
                try:
                    directories = backend.list_directories(relative)
                except BackendError as exc:
                    messagebox.showerror("Could not open folder", str(exc), parent=dialog)
                    return
            path_text.set(str(backend.folder_for(relative)))
            folder_list.delete(0, "end")
            for name in directories:
                folder_list.insert("end", name)

        def open_selected(_event=None) -> None:
            selection = folder_list.curselection()
            if not selection:
                return
            current_parts.append(folder_list.get(selection[0]))
            refresh()

        def go_up() -> None:
            if current_parts:
                current_parts.pop()
                refresh()

        def choose() -> None:
            selected_value["value"] = "/".join(current_parts)
            dialog.destroy()

        folder_list.bind("<Double-1>", open_selected)
        folder_list.bind("<Return>", open_selected)
        buttons = tk.Frame(dialog, bg=PANEL)
        buttons.pack(fill="x", padx=12, pady=12)
        ttk.Button(buttons, text="Up", command=go_up).pack(side="left", padx=4)
        ttk.Button(buttons, text="Open", command=open_selected).pack(side="left", padx=4)
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="right", padx=4)
        ttk.Button(buttons, text="Select This Folder", command=choose, style="Accent.TButton").pack(
            side="right", padx=4
        )
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        refresh(directories)
        folder_list.focus_set()
        self.wait_window(dialog)
        return selected_value["value"]

    def _backend_changed(self, *_args) -> None:
        if not hasattr(self, "local_fields"):
            return
        if hasattr(self, "connect_status_button") and self.monitor_thread is not None:
            self._disconnect_status_monitor(log=False)
        if self.backend_type.get().startswith("SFTP"):
            self.local_fields.grid_remove()
            self.sftp_fields.grid(row=1, column=0, columnspan=4, sticky="ew")
            self.setup_key_button.configure(state="normal")
            self.forget_host_button.configure(state="normal")
        else:
            self.sftp_fields.grid_remove()
            self.local_fields.grid(row=1, column=0, columnspan=4, sticky="ew")
            self.setup_key_button.configure(state="disabled")
            self.forget_host_button.configure(state="disabled")
        if hasattr(self, "tree"):
            self._target_changed()
        if hasattr(self, "connect_status_button"):
            self._update_status_button_states()

    def _update_status_button_states(self) -> None:
        if not hasattr(self, "connect_status_button"):
            return
        is_sftp = self.backend_type.get().startswith("SFTP")
        monitoring = self.monitor_thread is not None and self.monitor_thread.is_alive()
        self.connect_status_button.configure(state="normal" if is_sftp and not monitoring else "disabled")
        self.disconnect_status_button.configure(state="normal" if monitoring else "disabled")
        if not is_sftp:
            self.controller_status.set("Local Folder Mode")
            self.linuxcnc_status.set("LinuxCNC Not Monitored")
            self.machine_detail.set("Machine status monitoring is available with SFTP profiles.")
            self.controller_status_label.configure(fg=MUTED)
            self.linuxcnc_status_label.configure(fg=MUTED)

    def _connect_status_monitor(self) -> None:
        if not self.backend_type.get().startswith("SFTP"):
            return
        try:
            backend = self._backend(prompt_secret=True)
            if not isinstance(backend, SftpBackend):
                messagebox.showerror("SFTP profile incomplete", self._validate_sftp_fields() or "Complete the SFTP profile.")
                return
            if not self._ensure_host_trusted(backend):
                return
            helper_source = status_helper_source()
        except Exception as exc:
            messagebox.showerror("Could not start monitoring", self._friendly_connection_error(exc))
            return
        self._disconnect_status_monitor(log=False)
        self.monitor_generation += 1
        generation = self.monitor_generation
        stop_event = threading.Event()
        self.monitor_stop = stop_event
        self.controller_status.set("Connecting...")
        self.linuxcnc_status.set("LinuxCNC Not Checked")
        self.machine_detail.set(f"Connecting to {backend.host}:{backend.port}...")
        self.status_updated.set("")
        self.controller_status_label.configure(fg=WARN)
        self.linuxcnc_status_label.configure(fg=MUTED)
        self.monitor_thread = threading.Thread(
            target=self._status_worker,
            args=(backend, helper_source, stop_event, generation),
            daemon=True,
        )
        self.monitor_thread.start()
        self._update_status_button_states()

    def _schedule_auto_connect(self) -> None:
        self._cancel_scheduled_auto_connect()
        if self.backend_type.get().startswith("SFTP"):
            self.auto_connect_job = self.after(500, self._auto_connect_status_monitor)

    def _cancel_scheduled_auto_connect(self) -> None:
        if self.auto_connect_job is None:
            return
        try:
            self.after_cancel(self.auto_connect_job)
        except tk.TclError:
            pass
        self.auto_connect_job = None

    def _auto_connect_status_monitor(self) -> None:
        self.auto_connect_job = None
        if not self.backend_type.get().startswith("SFTP"):
            return
        if self.monitor_thread is not None and self.monitor_thread.is_alive():
            return
        self._log("Starting machine status monitoring automatically.")
        self._connect_status_monitor()

    def _status_worker(
        self,
        backend: SftpBackend,
        helper_source: bytes,
        stop_event: threading.Event,
        generation: int,
    ) -> None:
        try:
            backend.connect()
            helper_path = backend.install_status_helper(helper_source)
            self.events.put(("monitor_connected", generation, backend.host))
            while not stop_event.is_set():
                payload = backend.query_linuxcnc_status(helper_path)
                self.events.put(("machine_status", generation, payload))
                if stop_event.wait(2.0):
                    break
        except Exception as exc:
            if not stop_event.is_set():
                self.events.put(("monitor_error", generation, self._friendly_connection_error(exc)))
        finally:
            backend.close()

    def _disconnect_status_monitor(self, *, log: bool = True) -> None:
        self._cancel_scheduled_auto_connect()
        was_monitoring = self.monitor_thread is not None
        self.monitor_generation += 1
        self.monitor_stop.set()
        self.monitor_thread = None
        self.last_machine_status = None
        self.status_updated.set("")
        if self.backend_type.get().startswith("SFTP"):
            self.controller_status.set("Not Connected")
            self.linuxcnc_status.set("LinuxCNC Not Checked")
            self.machine_detail.set("Press Connect / Monitor to read machine status.")
            if hasattr(self, "controller_status_label"):
                self.controller_status_label.configure(fg=MUTED)
                self.linuxcnc_status_label.configure(fg=MUTED)
        if was_monitoring and log and hasattr(self, "log_box"):
            self._log("Machine status monitoring disconnected.")
        self._update_status_button_states()

    def _display_machine_status(self, status: LinuxCncStatus) -> None:
        self.last_machine_status = status
        self.controller_status.set("● Controller Online")
        self.controller_status_label.configure(fg=GOOD)
        self.linuxcnc_status.set("● " + status.display_state)
        color = {
            "estop": BAD,
            "error": BAD,
            "machine_off": WARN,
            "program_paused": WARN,
            "program_waiting": WARN,
            "program_running": ACCENT,
            "ready": GOOD,
        }.get(status.state, MUTED)
        if status.linuxcnc != "running":
            color = MUTED
        self.linuxcnc_status_label.configure(fg=color)
        self.machine_detail.set(status.display_detail or "Read-only LinuxCNC status is available.")
        self.status_updated.set("Updated " + dt.datetime.now().strftime("%H:%M:%S"))

    def _refresh_profiles(self, select_first: bool = False) -> None:
        names = [profile.name for profile in self.profiles]
        self.profile_combo.configure(values=names)
        if select_first and names:
            self.profile_name.set(names[0])
            self._load_selected_profile()

    def _load_selected_profile(self, _event=None) -> None:
        profile = next((item for item in self.profiles if item.name == self.profile_name.get()), None)
        if not profile:
            return
        self._cancel_scheduled_auto_connect()
        self._disconnect_status_monitor(log=False)
        self.backend_type.set("Local / mounted folder" if profile.backend == "local" else "SFTP / SSH")
        self.root_folder.set(profile.root_folder)
        self.host.set(profile.host)
        self.port.set(str(profile.port))
        self.username.set(profile.username)
        self.remote_root.set((profile.remote_root or profile.root_folder) if profile.backend == "sftp" else "/home/cnc/linuxcnc/nc_files")
        self.auth_mode.set("SSH key" if profile.auth_mode == "ssh_key" else "Password")
        self.key_path.set(profile.key_path)
        self.target_subfolder.set(profile.target_subfolder)
        self.overwrite_mode.set(overwrite_mode_label(profile.overwrite_mode))
        self._log(f"Profile loaded: {profile.name}")
        self._schedule_auto_connect()

    def _new_profile(self) -> None:
        self._cancel_scheduled_auto_connect()
        self._disconnect_status_monitor(log=False)
        self.profile_name.set("")
        self.backend_type.set("Local / mounted folder")
        self.root_folder.set("")
        self.host.set("")
        self.port.set("22")
        self.username.set("")
        self.remote_root.set("/home/cnc/linuxcnc/nc_files")
        self.auth_mode.set("SSH key")
        self.key_path.set("")
        self.target_subfolder.set("")
        self.overwrite_mode.set(overwrite_mode_label("ask"))
        self.profile_combo.focus_set()

    def _save_profile(self) -> None:
        name = self.profile_name.get().strip()
        if not name:
            messagebox.showwarning("Profile name required", "Enter a name for this machine profile.")
            return
        is_sftp = self.backend_type.get().startswith("SFTP")
        if is_sftp:
            error = self._validate_sftp_fields()
            if error:
                messagebox.showwarning("SFTP profile incomplete", error)
                return
        elif not self.root_folder.get().strip():
            messagebox.showwarning("Root folder required", "Select the machine's root destination folder.")
            return
        profile = MachineProfile(
            name=name,
            backend="sftp" if is_sftp else "local",
            root_folder=self.root_folder.get().strip() if not is_sftp else "",
            remote_root=self.remote_root.get().strip() if is_sftp else "",
            target_subfolder=self.target_subfolder.get().strip(),
            host=self.host.get().strip(),
            port=int(self.port.get() or 22),
            username=self.username.get().strip(),
            auth_mode="ssh_key" if self.auth_mode.get() == "SSH key" else "password",
            key_path=self.key_path.get().strip(),
            overwrite_mode=overwrite_mode_value(self.overwrite_mode.get()),
        )
        existing = next((index for index, item in enumerate(self.profiles) if item.name == name), None)
        if existing is None:
            self.profiles.append(profile)
        else:
            self.profiles[existing] = profile
        try:
            self.store.save(self.profiles)
        except OSError as exc:
            messagebox.showerror("Profile save failed", str(exc))
            return
        self._refresh_profiles()
        self._log(f"Profile saved: {name}")

    def _delete_profile(self) -> None:
        name = self.profile_name.get().strip()
        if not name or not any(item.name == name for item in self.profiles):
            return
        if not messagebox.askyesno("Delete profile", f"Delete the profile '{name}'?"):
            return
        self.profiles = [item for item in self.profiles if item.name != name]
        self.store.save(self.profiles)
        self._new_profile()
        self._refresh_profiles()
        self._log(f"Profile deleted: {name}")

    def _validate_sftp_fields(self) -> str | None:
        if not self.host.get().strip():
            return "Enter the LinuxCNC computer's host name or IP address."
        if not self.username.get().strip():
            return "Enter the LinuxCNC account username."
        try:
            port = int(self.port.get())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            return "SSH port must be a number from 1 through 65535."
        root = self.remote_root.get().strip()
        if not root.startswith("/"):
            return "The remote root folder must be an absolute Linux path beginning with '/'."
        if ".." in PurePosixPath(root).parts:
            return "The remote root folder cannot contain '..'."
        return None

    def _backend(self, *, prompt_secret: bool = False) -> TransferBackend | None:
        if not self.backend_type.get().startswith("SFTP"):
            return LocalFolderBackend(self.root_folder.get().strip()) if self.root_folder.get().strip() else None
        error = self._validate_sftp_fields()
        if error:
            return None
        auth_mode = "ssh_key" if self.auth_mode.get() == "SSH key" else "password"
        secret = ""
        if prompt_secret and auth_mode == "password":
            value = simpledialog.askstring("LinuxCNC password", "Enter the LinuxCNC account password:", show="*", parent=self)
            if value is None:
                raise BackendError("Connection cancelled.")
            secret = value
        elif (
            prompt_secret
            and self.key_path.get().strip()
            and private_key_requires_passphrase(self.key_path.get().strip())
        ):
            value = simpledialog.askstring(
                "SSH key passphrase",
                "Enter the passphrase for this SSH private key:",
                show="*",
                parent=self,
            )
            if value is None:
                raise BackendError("Connection cancelled.")
            secret = value
        return SftpBackend(
            self.host.get(),
            int(self.port.get()),
            self.username.get(),
            self.remote_root.get(),
            app_data_dir() / "known_hosts",
            auth_mode=auth_mode,
            key_path=self.key_path.get(),
            secret=secret,
        )

    def _ensure_host_trusted(self, backend: SftpBackend) -> bool:
        known = backend.trusted_host_key()
        if known:
            return True
        remote_key = backend.probe_host_key(backend.host, backend.port)
        fingerprint = backend.fingerprint(remote_key)
        trusted = messagebox.askyesno(
            "Trust this LinuxCNC computer?",
            f"First connection to {backend.host}:{backend.port}.\n\n"
            f"SSH key type: {remote_key.get_name()}\n"
            f"Fingerprint: {fingerprint}\n\n"
            "Verify this fingerprint when possible. Trust this computer and continue?",
        )
        if trusted:
            backend.trust_host_key(remote_key)
            self._log(f"Trusted SSH host key for {backend.host}: {fingerprint}")
        return trusted

    def _test_target(self) -> None:
        error = validate_subfolder(self.target_subfolder.get())
        if error:
            self.validation_text.set(error)
            return
        try:
            backend = self._backend(prompt_secret=True)
        except BackendError as exc:
            message = self._friendly_connection_error(exc)
            self.validation_text.set(message)
            self._log(message)
            return
        if backend is None:
            message = self._validate_sftp_fields() if self.backend_type.get().startswith("SFTP") else "Select a root folder for this machine profile."
            self.validation_text.set(message)
            return
        try:
            if isinstance(backend, SftpBackend):
                if not self._ensure_host_trusted(backend):
                    return
                backend.connect()
                self._log(f"Connected to {backend.host} using {self.auth_mode.get().lower()} authentication.")
            ok, message = backend.test_target(self.target_subfolder.get())
        except (BackendError, OSError) as exc:
            ok, message = False, self._friendly_connection_error(exc)
        finally:
            backend.close()
        self.validation_text.set(message)
        self.status_text.set("Target Ready" if ok else "Target Error")
        self._log(message)

    @staticmethod
    def _friendly_connection_error(exc: Exception) -> str:
        if isinstance(exc, DependencyError):
            return str(exc)
        if isinstance(exc, AuthenticationError):
            return "The LinuxCNC computer rejected the username, password, or SSH key."
        if isinstance(exc, UnknownHostKeyError):
            return str(exc)
        if isinstance(exc, (TimeoutError, socket.timeout)):
            return "The LinuxCNC computer did not respond before the connection timed out."
        if isinstance(exc, ConnectionRefusedError):
            return "The computer responded, but its SSH/SFTP service refused the connection."
        return f"Could not connect to the LinuxCNC computer: {exc}"

    def _setup_ssh_key(self) -> None:
        error = self._validate_sftp_fields()
        if error:
            messagebox.showwarning("SFTP profile incomplete", error)
            return
        default_path = Path.home() / ".ssh" / "cnc_file_shuttle_ed25519"
        selected = filedialog.asksaveasfilename(
            title="Save CNC File Shuttle private key",
            initialdir=str(default_path.parent),
            initialfile=default_path.name,
            defaultextension="",
        )
        if not selected:
            return
        passphrase = simpledialog.askstring(
            "Optional key passphrase",
            "Enter a passphrase to protect the key, or leave blank for unattended shop use:",
            show="*",
            parent=self,
        )
        if passphrase is None:
            return
        if passphrase:
            confirmation = simpledialog.askstring("Confirm passphrase", "Enter the key passphrase again:", show="*", parent=self)
            if confirmation != passphrase:
                messagebox.showerror("Passphrases do not match", "The SSH key was not created.")
                return
        try:
            password_backend = SftpBackend(
                self.host.get(), int(self.port.get()), self.username.get(), self.remote_root.get(),
                app_data_dir() / "known_hosts", auth_mode="password"
            )
            if not self._ensure_host_trusted(password_backend):
                return
            password = simpledialog.askstring(
                "One-time LinuxCNC password",
                "Enter the LinuxCNC account password. It will be used once to install the public key and will not be saved:",
                show="*", parent=self,
            )
            if password is None:
                return
            password_backend.secret = password
            password_backend.connect()
            try:
                private_path, public_path, key_fingerprint = generate_ed25519_keypair(
                    Path(selected), passphrase, f"cnc-file-shuttle@{socket.gethostname()}"
                )
                password_backend.install_public_key(public_path.read_text(encoding="ascii"))
            finally:
                password_backend.close()
            verify_backend = SftpBackend(
                self.host.get(), int(self.port.get()), self.username.get(), self.remote_root.get(),
                app_data_dir() / "known_hosts", auth_mode="ssh_key", key_path=str(private_path), secret=passphrase
            )
            verify_backend.connect()
            verify_backend.close()
        except Exception as exc:
            messagebox.showerror(
                "SSH key setup did not finish",
                self._friendly_connection_error(exc) + "\n\nIf the key was already generated, it has been left in place so it is not lost.",
            )
            self._log(f"SSH key setup failed: {exc}")
            return
        self.auth_mode.set("SSH key")
        self.key_path.set(str(private_path))
        self._log(f"SSH key installed and verified: {key_fingerprint}")
        messagebox.showinfo(
            "SSH key setup complete",
            f"CNC File Shuttle connected without a password.\n\nPrivate key: {private_path}\nPublic key: {public_path}",
        )

    def _forget_host_trust(self) -> None:
        error = self._validate_sftp_fields()
        if error:
            messagebox.showwarning("SFTP profile incomplete", error)
            return
        if not messagebox.askyesno(
            "Forget trusted SSH identity?",
            f"Forget the saved SSH identity for {self.host.get()}:{self.port.get()}?\n\n"
            "Only do this when the LinuxCNC computer was intentionally replaced or its SSH keys were regenerated.",
        ):
            return
        try:
            backend = SftpBackend(
                self.host.get(), int(self.port.get()), self.username.get(), self.remote_root.get(),
                app_data_dir() / "known_hosts"
            )
            removed = backend.forget_host_key()
        except BackendError as exc:
            messagebox.showerror("Could not update host trust", self._friendly_connection_error(exc))
            return
        self._log(f"Forgot trusted SSH identity for {self.host.get()}:{self.port.get()}.")
        messagebox.showinfo(
            "Host trust updated",
            "The saved SSH identity was removed." if removed else "There was no saved SSH identity for this address.",
        )

    def _add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Add CNC files",
            filetypes=(("CNC / G-code files", "*.ngc *.nc *.tap *.cnc *.gcode *.txt"), ("All files", "*.*")),
        )
        if not paths:
            return
        added = 0
        warning_lines: list[str] = []
        existing = {item.source.resolve() for item in self.items}
        for raw_path in paths:
            path = Path(raw_path)
            if path.resolve() in existing:
                continue
            warnings = filename_warnings(path)
            if warnings:
                warning_lines.append(f"{path.name}: " + " ".join(warnings))
            self.items.append(QueueItem(path, self.target_subfolder.get().strip()))
            existing.add(path.resolve())
            added += 1
        self._refresh_queue()
        self._log(f"Added {added} file{'s' if added != 1 else ''} to queue.")
        if warning_lines:
            messagebox.showwarning("Filename warning", "\n\n".join(warning_lines[:8]) + ("\n\nAdditional warnings omitted." if len(warning_lines) > 8 else ""))

    def _remove_selected(self) -> None:
        indices = sorted((int(item_id) for item_id in self.tree.selection()), reverse=True)
        for index in indices:
            if self.items[index].status != QueueStatus.COPYING:
                del self.items[index]
        self._refresh_queue()

    def _clear_queue(self) -> None:
        if self.copy_thread and self.copy_thread.is_alive():
            messagebox.showinfo("Queue active", "Wait for the current copy to finish before clearing the queue.")
            return
        self.items.clear()
        self._refresh_queue()

    def _requeue_finished(self) -> None:
        if self.copy_thread and self.copy_thread.is_alive():
            messagebox.showinfo("Queue active", "Wait for the current copy to finish before requeueing files.")
            return
        count = requeue_finished(self.items, self.target_subfolder.get().strip())
        self._refresh_queue()
        if count:
            self._log(f"Requeued {count} finished file{'s' if count != 1 else ''}.")
        else:
            messagebox.showinfo("Nothing to requeue", "There are no completed, skipped, or failed files to requeue.")

    def _move_selected(self, direction: int) -> None:
        if len(self.tree.selection()) != 1:
            return
        index = int(self.tree.selection()[0])
        new_index = index + direction
        if not 0 <= new_index < len(self.items):
            return
        if self.items[index].status == QueueStatus.COPYING:
            return
        self.items[index], self.items[new_index] = self.items[new_index], self.items[index]
        self._refresh_queue(select_index=new_index)

    def _target_changed(self, *_args) -> None:
        new_target = self.target_subfolder.get().strip()
        for item in self.items:
            if item.status in {QueueStatus.PENDING, QueueStatus.FAILED}:
                item.target_subfolder = new_target
                item.target_display = ""
        self._refresh_queue()
        self._update_preview()

    def _destination_text(self, item: QueueItem) -> str:
        if item.target_display and item.status in {QueueStatus.COPYING, QueueStatus.DONE, QueueStatus.SKIPPED}:
            return item.target_display
        if self.backend_type.get().startswith("SFTP"):
            normalized = item.target_subfolder.strip().replace("\\", "/").strip("/")
            root = PurePosixPath(self.remote_root.get().strip() or "/")
            destination = root.joinpath(*filter(None, normalized.split("/"))) / item.filename
            return f"SFTP: {destination}"
        backend = self._backend()
        if backend is None:
            return f"<select root folder>/{item.target_subfolder}/{item.filename}"
        return str(backend.destination_for(item.filename, item.target_subfolder))

    def _refresh_queue(self, select_index: int | None = None) -> None:
        previous = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for index, item in enumerate(self.items):
            self.tree.insert("", "end", iid=str(index), values=(index + 1, item.filename, human_size(item.size), self._destination_text(item), item.status.value))
        if select_index is not None and self.tree.exists(str(select_index)):
            self.tree.selection_set(str(select_index))
        elif previous:
            valid = [iid for iid in previous if self.tree.exists(iid)]
            if valid:
                self.tree.selection_set(valid)
        self._update_preview()

    def _update_preview(self) -> None:
        selection = self.tree.selection() if hasattr(self, "tree") else ()
        item = self.items[int(selection[0])] if selection else (self.items[0] if self.items else None)
        self.target_preview.set(self._destination_text(item) if item else "Add a file to preview its exact destination.")
        error = validate_subfolder(self.target_subfolder.get())
        self.validation_text.set(error or "Destination path format is valid.")

    def _start_queue(self) -> None:
        if self.copy_thread and self.copy_thread.is_alive():
            return
        if not self.items or not any(item.status in {QueueStatus.PENDING, QueueStatus.FAILED} for item in self.items):
            messagebox.showinfo("Queue is empty", "Add files or retry failed items before sending.")
            return
        error = validate_subfolder(self.target_subfolder.get())
        if error:
            messagebox.showerror("Invalid target", error)
            return
        try:
            backend = self._backend(prompt_secret=True)
        except BackendError as exc:
            messagebox.showerror("SFTP unavailable", self._friendly_connection_error(exc))
            return
        if backend is None:
            if self.backend_type.get().startswith("SFTP"):
                messagebox.showerror("SFTP profile incomplete", self._validate_sftp_fields() or "Complete the SFTP profile.")
            else:
                messagebox.showerror("Root folder required", "Select the machine's root destination folder before sending files.")
            return
        try:
            if isinstance(backend, SftpBackend):
                if not self._ensure_host_trusted(backend):
                    return
        except Exception as exc:
            messagebox.showerror("Connection failed", self._friendly_connection_error(exc))
            return
        for item in self.items:
            if item.status == QueueStatus.FAILED:
                item.status = QueueStatus.PENDING
                item.detail = ""
                item.target_display = ""
        overwrite_mode = overwrite_mode_value(self.overwrite_mode.get())
        self.overwrite_session = overwrite_session_for_mode(overwrite_mode)
        self.cancel_requested = False
        self.send_button.configure(state="disabled")
        self.status_text.set("Connecting" if isinstance(backend, SftpBackend) else "Preparing")
        overwrite_description = overwrite_mode_label(overwrite_mode)
        self._log(
            f"Queue started. Existing files: {overwrite_description}."
            if not isinstance(backend, SftpBackend)
            else f"Connecting to {backend.host}... Existing files: {overwrite_description}."
        )
        target_subfolder = self.target_subfolder.get()
        helper_source = None
        if isinstance(backend, SftpBackend):
            try:
                helper_source = status_helper_source()
            except Exception as exc:
                self._log(f"LinuxCNC status helper unavailable; transfer will continue without active-file protection: {exc}")
        self.copy_thread = threading.Thread(
            target=self._copy_worker,
            args=(backend, target_subfolder, helper_source),
            daemon=True,
        )
        self.copy_thread.start()

    def _copy_worker(
        self,
        backend: TransferBackend,
        target_subfolder: str,
        helper_source: bytes | None,
    ) -> None:
        try:
            backend.connect()
            ok, message = backend.test_target(target_subfolder)
            if not ok:
                raise BackendError(message)
            self.events.put(("log", message))
            helper_path = None
            if isinstance(backend, SftpBackend) and helper_source is not None:
                try:
                    helper_path = backend.install_status_helper(helper_source)
                except Exception as exc:
                    self.events.put(("log", f"Active-program check unavailable; file transfer remains enabled: {exc}"))
            for index, item in enumerate(self.items):
                if self.cancel_requested or item.status != QueueStatus.PENDING:
                    continue
                try:
                    destination = backend.destination_for(item.filename, item.target_subfolder)
                    item.target_display = str(destination)
                    if backend.exists(destination):
                        if isinstance(backend, SftpBackend) and helper_path is not None:
                            try:
                                machine_status = LinuxCncStatus.from_payload(
                                    backend.query_linuxcnc_status(helper_path)
                                )
                                if machine_status.is_active_path(destination):
                                    raise BackendError(
                                        f"Blocked overwrite: {item.filename} is the program currently active in LinuxCNC."
                                    )
                            except BackendError as exc:
                                if str(exc).startswith("Blocked overwrite:"):
                                    raise
                                self.events.put(("log", f"Could not confirm the active LinuxCNC program: {exc}"))
                                helper_path = None
                        decision_event = threading.Event()
                        self.decision_events[index] = decision_event
                        self.events.put(("overwrite", index, str(destination)))
                        decision_event.wait()
                        decision = self.decision_values.pop(index, "cancel")
                        self.decision_events.pop(index, None)
                        if decision == "cancel":
                            self.cancel_requested = True
                            break
                        if decision == "skip":
                            self.events.put(("status", index, QueueStatus.SKIPPED, "Destination already exists."))
                            continue
                    self.events.put(("status", index, QueueStatus.COPYING, ""))
                    backend.copy_file(
                        item.source,
                        destination,
                        progress=lambda sent, total, i=index: self.events.put(("progress", i, sent, total)),
                    )
                except Exception as exc:
                    self.events.put(("failure", index, str(exc), traceback.format_exc()))
                else:
                    self.events.put(("status", index, QueueStatus.DONE, ""))
        except Exception as exc:
            pending_index = next(
                (index for index, item in enumerate(self.items) if item.status == QueueStatus.PENDING),
                None,
            )
            if pending_index is not None:
                self.events.put(("failure", pending_index, self._friendly_connection_error(exc), traceback.format_exc()))
        finally:
            try:
                backend.close()
            finally:
                self.events.put(("complete",))

    def _poll_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "overwrite":
                    self._ask_overwrite(event[1], event[2])
                elif kind == "log":
                    self._log(event[1])
                elif kind == "monitor_connected":
                    generation, host = event[1:]
                    if generation == self.monitor_generation:
                        self.controller_status.set("● Controller Online")
                        self.controller_status_label.configure(fg=GOOD)
                        self.machine_detail.set("Reading LinuxCNC status...")
                        self._log(f"Machine status monitor connected to {host}.")
                elif kind == "machine_status":
                    generation, payload = event[1:]
                    if generation == self.monitor_generation:
                        self._display_machine_status(LinuxCncStatus.from_payload(payload))
                elif kind == "monitor_error":
                    generation, message = event[1:]
                    if generation == self.monitor_generation:
                        self.monitor_thread = None
                        self.last_machine_status = None
                        self.controller_status.set("● Controller Offline")
                        self.linuxcnc_status.set("LinuxCNC Status Unavailable")
                        self.machine_detail.set(message)
                        self.status_updated.set("Updated " + dt.datetime.now().strftime("%H:%M:%S"))
                        self.controller_status_label.configure(fg=BAD)
                        self.linuxcnc_status_label.configure(fg=MUTED)
                        self._log(f"Machine status monitor stopped: {message}")
                        self._update_status_button_states()
                elif kind == "progress":
                    index, sent, total = event[1:]
                    percent = int(sent * 100 / total) if total else 100
                    self.status_text.set(f"Copying {self.items[index].filename} — {percent}%")
                elif kind == "status":
                    index, status, detail = event[1:]
                    self.items[index].status = status
                    self.items[index].detail = detail
                    self._log(f"{status.value}: {self.items[index].filename}" + (f" — {detail}" if detail else ""))
                    self._refresh_queue()
                elif kind == "failure":
                    index, error, trace = event[1:]
                    self.items[index].status = QueueStatus.FAILED
                    self.items[index].detail = error
                    log_path = self._write_failure_log(self.items[index], error, trace)
                    self._log(f"Failed: {self.items[index].filename} — {error}")
                    self._log(f"Diagnostic log saved: {log_path}")
                    self._refresh_queue()
                elif kind == "complete":
                    self.send_button.configure(state="normal")
                    failed = any(item.status == QueueStatus.FAILED for item in self.items)
                    self.status_text.set("Completed with errors" if failed else "Queue Complete")
                    self._log("Queue complete." if not failed else "Queue finished with one or more failures.")
                    if self.auto_clear.get() and not failed:
                        self.items.clear()
                        self._refresh_queue()
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _ask_overwrite(self, index: int, destination: str) -> None:
        item = self.items[index]
        if self.overwrite_session == "overwrite_all":
            decision = "overwrite"
        elif self.overwrite_session == "skip_all":
            decision = "skip"
        else:
            dialog = tk.Toplevel(self)
            dialog.title("File already exists")
            dialog.configure(bg=PANEL)
            dialog.transient(self)
            dialog.grab_set()
            tk.Label(dialog, text="Destination file already exists:", bg=PANEL, fg=TEXT, font=("TkDefaultFont", 11, "bold")).pack(anchor="w", padx=18, pady=(16, 4))
            tk.Label(dialog, text=destination, bg=PANEL, fg=MUTED, wraplength=620, justify="left").pack(anchor="w", padx=18, pady=(0, 14))
            result = {"value": "cancel"}
            buttons = tk.Frame(dialog, bg=PANEL)
            buttons.pack(fill="x", padx=14, pady=(0, 14))
            choices = (("Overwrite", "overwrite"), ("Overwrite All", "overwrite_all"), ("Skip", "skip"), ("Skip All", "skip_all"), ("Cancel Queue", "cancel"))
            for label, value in choices:
                ttk.Button(buttons, text=label, command=lambda v=value: (result.update(value=v), dialog.destroy())).pack(side="left", padx=4)
            self.wait_window(dialog)
            chosen = result["value"]
            if chosen in {"overwrite_all", "skip_all"}:
                self.overwrite_session = chosen
            decision = "overwrite" if chosen == "overwrite_all" else "skip" if chosen == "skip_all" else chosen
        self.decision_values[index] = decision
        self.decision_events[index].set()

    def _write_failure_log(self, item: QueueItem, error: str, trace: str) -> Path:
        folder = app_data_dir() / "CNCFileShuttle_FailureLogs"
        folder.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(char if char.isalnum() or char in "-_." else "_" for char in item.filename)
        stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        path = folder / f"CNCFileShuttle_failure_{stamp}_{safe_name}.txt"
        attempted_target = item.target_display or self._destination_text(item)
        path.write_text(
            f"CNC File Shuttle {__version__}\nTime: {dt.datetime.now().isoformat()}\n"
            f"Source: {item.source}\nTarget: {attempted_target}\nError: {error}\n\n{trace}",
            encoding="utf-8",
        )
        return path

    def _on_close(self) -> None:
        self.monitor_stop.set()
        self.destroy()


def main() -> None:
    app = CNCFileShuttleApp()
    app.mainloop()
