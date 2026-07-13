"""Downloads view: the queue grouped by item.

One Adw.ExpanderRow per item with aggregate progress and group actions
(pause/resume/cancel all, open folder); one row per file inside. Grouping
is purely presentational — the DownloadManager's queue stays flat.

Rows are permanent per task (a ListBox, not a recycled ListView — download
queues are tens of rows, not thousands), which keeps updates simple:
manager events are trampolined onto the main loop and patch widgets
directly. Queues are rebuilt wholesale only on "Clear finished".
"""

from gi.repository import Adw, Gio, GLib, Gtk

from ..core.downloads import (
    FINISHED_STATES,
    DownloadState,
    DownloadTask,
)
from .format import format_size

STATE_LABELS = {
    DownloadState.QUEUED: "Queued",
    DownloadState.RUNNING: "Downloading",
    DownloadState.PAUSED: "Paused",
    DownloadState.COMPLETED: "Completed",
    DownloadState.FAILED: "Failed",
    DownloadState.CANCELLED: "Cancelled",
}

ACTIVE_STATES = (DownloadState.RUNNING, DownloadState.QUEUED)
RESUMABLE_STATES = (DownloadState.PAUSED, DownloadState.FAILED)


class DownloadsView(Gtk.Box):
    def __init__(self, manager, on_error):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._manager = manager
        self._on_error = on_error
        # identifier -> {"row", "tasks": {task.id: task}, buttons...}
        self._groups: dict[str, dict] = {}
        # task.id -> {"task", "row", "progress", "toggle", "cancel", "folder"}
        self._file_rows: dict[str, dict] = {}

        toolbar = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6,
            margin_top=12,
            margin_bottom=6,
            margin_start=12,
            margin_end=12,
        )
        self._summary_label = Gtk.Label(xalign=0.0, hexpand=True)
        self._summary_label.add_css_class("dim-label")
        toolbar.append(self._summary_label)

        clear_button = Gtk.Button(label="Clear finished")
        clear_button.connect("clicked", lambda *_: self._clear_finished())
        toolbar.append(clear_button)
        self.append(toolbar)

        self._list_box = Gtk.ListBox(
            selection_mode=Gtk.SelectionMode.NONE,
            valign=Gtk.Align.START,
            margin_top=6,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )
        self._list_box.add_css_class("boxed-list")

        clamp = Adw.Clamp(maximum_size=900, child=self._list_box)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_child(clamp)

        self._empty_page = Adw.StatusPage(
            title="No downloads",
            description="Select files on an item page and press “Download selected”.",
            icon_name="folder-download-symbolic",
            vexpand=True,
        )

        self._stack = Gtk.Stack(vexpand=True)
        self._stack.add_named(self._empty_page, "empty")
        self._stack.add_named(scroller, "list")
        self.append(self._stack)

        for task in manager.tasks():
            self._attach_task(task)
        self._refresh_everything()

        manager.add_listener(self._on_task_event_threaded)

    # -- manager events ----------------------------------------------------

    def _on_task_event_threaded(self, task: DownloadTask):
        GLib.idle_add(self._on_task_event, task)

    def _on_task_event(self, task: DownloadTask):
        if task.id not in self._file_rows:
            self._attach_task(task)
        self._update_file_row(self._file_rows[task.id])
        self._update_group(task.identifier)
        self._refresh_chrome()

    # -- construction ----------------------------------------------------------

    def _attach_task(self, task: DownloadTask):
        group = self._groups.get(task.identifier)
        if group is None:
            group = self._create_group(task)
        record = self._create_file_row(task)
        group["tasks"][task.id] = task
        group["row"].add_row(record["row"])

    def _create_group(self, task: DownloadTask) -> dict:
        row = Adw.ExpanderRow(title=task.item_title or task.identifier)
        row.set_tooltip_text(task.identifier)

        pause = Gtk.Button(
            icon_name="media-playback-pause-symbolic",
            tooltip_text="Pause all",
            valign=Gtk.Align.CENTER,
        )
        pause.add_css_class("flat")
        resume = Gtk.Button(
            icon_name="media-playback-start-symbolic",
            tooltip_text="Resume all",
            valign=Gtk.Align.CENTER,
        )
        resume.add_css_class("flat")
        cancel = Gtk.Button(
            icon_name="process-stop-symbolic",
            tooltip_text="Cancel all",
            valign=Gtk.Align.CENTER,
        )
        cancel.add_css_class("flat")
        folder = Gtk.Button(
            icon_name="folder-open-symbolic",
            tooltip_text="Open item folder",
            valign=Gtk.Align.CENTER,
        )
        folder.add_css_class("flat")

        identifier = task.identifier
        pause.connect("clicked", lambda *_: self._group_action(identifier, "pause"))
        resume.connect("clicked", lambda *_: self._group_action(identifier, "resume"))
        cancel.connect("clicked", lambda *_: self._group_action(identifier, "cancel"))
        folder.connect("clicked", lambda *_: self._open_folder(identifier))

        for button in (pause, resume, cancel, folder):
            row.add_suffix(button)

        group = {
            "row": row,
            "tasks": {},
            "pause": pause,
            "resume": resume,
            "cancel": cancel,
            "folder": folder,
        }
        self._groups[identifier] = group
        self._list_box.append(row)
        return group

    def _create_file_row(self, task: DownloadTask) -> dict:
        row = Adw.ActionRow(title=task.file_name)
        row.set_title_lines(1)
        row.set_subtitle_lines(1)

        progress = Gtk.ProgressBar(valign=Gtk.Align.CENTER)
        progress.set_size_request(110, -1)
        row.add_suffix(progress)

        toggle = Gtk.Button(valign=Gtk.Align.CENTER)
        toggle.add_css_class("flat")
        toggle.connect("clicked", lambda *_: self._toggle_task(task))
        row.add_suffix(toggle)

        cancel = Gtk.Button(
            icon_name="process-stop-symbolic",
            tooltip_text="Cancel",
            valign=Gtk.Align.CENTER,
        )
        cancel.add_css_class("flat")
        cancel.connect("clicked", lambda *_: self._manager.cancel(task))
        row.add_suffix(cancel)

        folder = Gtk.Button(
            icon_name="folder-open-symbolic",
            tooltip_text="Open containing folder",
            valign=Gtk.Align.CENTER,
        )
        folder.add_css_class("flat")
        folder.connect("clicked", lambda *_: self._open_file_folder(task))
        row.add_suffix(folder)

        record = {
            "task": task,
            "row": row,
            "progress": progress,
            "toggle": toggle,
            "cancel": cancel,
            "folder": folder,
        }
        self._file_rows[task.id] = record
        self._update_file_row(record)
        return record

    # -- updates -------------------------------------------------------------

    def _update_file_row(self, record: dict):
        task: DownloadTask = record["task"]

        bits = [STATE_LABELS[task.state]]
        if task.state == DownloadState.FAILED and task.error:
            bits = [f"Failed — {task.error}"]
        if task.size:
            bits.append(f"{format_size(task.downloaded)} of {format_size(task.size)}")
        elif task.downloaded:
            bits.append(format_size(task.downloaded))
        if task.state == DownloadState.RUNNING and task.speed_bps > 0:
            bits.append(f"{format_size(int(task.speed_bps))}/s")
        record["row"].set_subtitle(" · ".join(bits))

        record["progress"].set_fraction(
            1.0 if task.state == DownloadState.COMPLETED else task.progress
        )
        record["progress"].set_visible(task.state != DownloadState.CANCELLED)

        toggle = record["toggle"]
        if task.state in ACTIVE_STATES:
            toggle.set_icon_name("media-playback-pause-symbolic")
            toggle.set_tooltip_text("Pause")
            toggle.set_visible(True)
        elif task.state == DownloadState.PAUSED:
            toggle.set_icon_name("media-playback-start-symbolic")
            toggle.set_tooltip_text("Resume")
            toggle.set_visible(True)
        elif task.state == DownloadState.FAILED:
            toggle.set_icon_name("view-refresh-symbolic")
            toggle.set_tooltip_text("Retry")
            toggle.set_visible(True)
        else:
            toggle.set_visible(False)

        record["cancel"].set_visible(task.state not in FINISHED_STATES)
        record["folder"].set_visible(task.state == DownloadState.COMPLETED)

    def _update_group(self, identifier: str):
        group = self._groups.get(identifier)
        if group is None:
            return
        tasks = list(group["tasks"].values())

        done = sum(1 for t in tasks if t.state == DownloadState.COMPLETED)
        failed = sum(1 for t in tasks if t.state == DownloadState.FAILED)
        active = sum(1 for t in tasks if t.state in ACTIVE_STATES)
        paused = sum(1 for t in tasks if t.state == DownloadState.PAUSED)

        bits = [f"{done} of {len(tasks)} files"]
        total_size = sum(t.size for t in tasks)
        if total_size:
            downloaded = sum(
                t.size if t.state == DownloadState.COMPLETED else t.downloaded
                for t in tasks
            )
            bits.append(f"{format_size(downloaded)} of {format_size(total_size)}")
        if active:
            bits.append("downloading")
        elif paused:
            bits.append("paused")
        if failed:
            bits.append(f"{failed} failed")
        group["row"].set_subtitle(" · ".join(bits))

        group["pause"].set_visible(active > 0)
        group["resume"].set_visible(paused + failed > 0)
        group["cancel"].set_visible(any(t.state not in FINISHED_STATES for t in tasks))
        group["folder"].set_visible(done > 0)

    def _refresh_chrome(self):
        tasks = self._manager.tasks()
        self._stack.set_visible_child_name("list" if tasks else "empty")
        active = sum(1 for t in tasks if t.state in ACTIVE_STATES)
        done = sum(1 for t in tasks if t.state == DownloadState.COMPLETED)
        failed = sum(1 for t in tasks if t.state == DownloadState.FAILED)
        bits = []
        if active:
            bits.append(f"{active} active")
        if done:
            bits.append(f"{done} completed")
        if failed:
            bits.append(f"{failed} failed")
        self._summary_label.set_label(" · ".join(bits))

    def _refresh_everything(self):
        for identifier in self._groups:
            self._update_group(identifier)
        self._refresh_chrome()

    # -- actions --------------------------------------------------------------

    def _toggle_task(self, task: DownloadTask):
        if task.state in ACTIVE_STATES:
            self._manager.pause(task)
        else:
            self._manager.resume(task)

    def _group_action(self, identifier: str, action: str):
        for task in list(self._groups[identifier]["tasks"].values()):
            if action == "pause" and task.state in ACTIVE_STATES:
                self._manager.pause(task)
            elif action == "resume" and task.state in RESUMABLE_STATES:
                self._manager.resume(task)
            elif action == "cancel" and task.state not in FINISHED_STATES:
                self._manager.cancel(task)

    def _clear_finished(self):
        self._manager.clear_finished()
        self._list_box.remove_all()
        self._groups.clear()
        self._file_rows.clear()
        for task in self._manager.tasks():
            self._attach_task(task)
        self._refresh_everything()

    def _open_folder(self, identifier: str):
        tasks = self._groups[identifier]["tasks"].values()
        first = next(iter(tasks), None)
        if first is not None:
            launcher = Gtk.FileLauncher(
                file=Gio.File.new_for_path(str(first.item_dir))
            )
            launcher.launch(self.get_root(), None, None)

    def _open_file_folder(self, task: DownloadTask):
        launcher = Gtk.FileLauncher(file=Gio.File.new_for_path(str(task.dest)))
        launcher.open_containing_folder(self.get_root(), None, None)
