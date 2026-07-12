"""Downloads view: live queue with per-task progress and controls.

DownloadManager listeners fire on worker threads; every event is
trampolined onto the GTK main loop before touching widgets.
"""

from gi.repository import Adw, Gio, GLib, GObject, Gtk, Pango

from ..core.downloads import DownloadState, DownloadTask
from .format import format_size

STATE_LABELS = {
    DownloadState.QUEUED: "Queued",
    DownloadState.RUNNING: "Downloading",
    DownloadState.PAUSED: "Paused",
    DownloadState.COMPLETED: "Completed",
    DownloadState.FAILED: "Failed",
    DownloadState.CANCELLED: "Cancelled",
}


class TaskItem(GObject.Object):
    """Wraps a DownloadTask; ``rev`` bumps to trigger bound-row refreshes."""

    rev = GObject.Property(type=int, default=0)

    def __init__(self, task: DownloadTask):
        super().__init__()
        self.task = task

    def bump(self):
        self.rev += 1


class DownloadsView(Gtk.Box):
    def __init__(self, manager, on_error):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._manager = manager
        self._on_error = on_error
        self._items: dict[str, TaskItem] = {}

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

        self._store = Gio.ListStore(item_type=TaskItem)
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_row_setup)
        factory.connect("bind", self._on_row_bind)
        factory.connect("unbind", self._on_row_unbind)

        list_view = Gtk.ListView(
            model=Gtk.NoSelection(model=self._store),
            factory=factory,
        )

        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_child(list_view)

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
            self._ensure_item(task)
        self._refresh_chrome()

        manager.add_listener(self._on_task_event_threaded)

    # -- manager events ----------------------------------------------------

    def _on_task_event_threaded(self, task: DownloadTask):
        GLib.idle_add(self._on_task_event, task)

    def _on_task_event(self, task: DownloadTask):
        self._ensure_item(task).bump()
        self._refresh_chrome()

    def _ensure_item(self, task: DownloadTask) -> TaskItem:
        item = self._items.get(task.id)
        if item is None:
            item = TaskItem(task)
            self._items[task.id] = item
            self._store.append(item)
        return item

    def _refresh_chrome(self):
        count = self._store.get_n_items()
        self._stack.set_visible_child_name("list" if count else "empty")
        tasks = [self._store.get_item(i).task for i in range(count)]
        active = sum(
            1 for t in tasks
            if t.state in (DownloadState.RUNNING, DownloadState.QUEUED)
        )
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

    def _clear_finished(self):
        self._manager.clear_finished()
        keep = {t.id for t in self._manager.tasks()}
        self._items = {tid: item for tid, item in self._items.items() if tid in keep}
        self._store.remove_all()
        for task in self._manager.tasks():
            self._items[task.id] = self._items.get(task.id) or TaskItem(task)
            self._store.append(self._items[task.id])
        self._refresh_chrome()

    # -- rows ----------------------------------------------------------------

    def _on_row_setup(self, _factory, list_item):
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=4,
            margin_top=8,
            margin_bottom=8,
            margin_start=12,
            margin_end=12,
        )

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        name = Gtk.Label(xalign=0.0, hexpand=True, ellipsize=Pango.EllipsizeMode.MIDDLE)
        name.add_css_class("heading")
        state = Gtk.Label(xalign=1.0)
        state.add_css_class("dim-label")
        top.append(name)
        top.append(state)
        box.append(top)

        progress = Gtk.ProgressBar()
        box.append(progress)

        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        detail = Gtk.Label(xalign=0.0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
        detail.add_css_class("caption")
        detail.add_css_class("dim-label")
        bottom.append(detail)

        toggle = Gtk.Button()
        toggle.add_css_class("flat")
        toggle.connect("clicked", lambda *_: self._toggle(list_item))
        bottom.append(toggle)

        cancel = Gtk.Button(icon_name="process-stop-symbolic", tooltip_text="Cancel")
        cancel.add_css_class("flat")
        cancel.connect("clicked", lambda *_: self._cancel(list_item))
        bottom.append(cancel)

        folder = Gtk.Button(
            icon_name="folder-open-symbolic", tooltip_text="Open containing folder"
        )
        folder.add_css_class("flat")
        folder.connect("clicked", lambda *_: self._open_folder(list_item))
        bottom.append(folder)

        box.append(bottom)

        box.name_label = name
        box.state_label = state
        box.progress = progress
        box.detail_label = detail
        box.toggle_button = toggle
        box.cancel_button = cancel
        box.folder_button = folder
        list_item.set_child(box)

    def _on_row_bind(self, _factory, list_item):
        item: TaskItem = list_item.get_item()
        handler = item.connect(
            "notify::rev", lambda *_: self._update_row(list_item.get_child(), item.task)
        )
        list_item.rev_handler = handler
        self._update_row(list_item.get_child(), item.task)

    def _on_row_unbind(self, _factory, list_item):
        handler = getattr(list_item, "rev_handler", None)
        if handler is not None:
            list_item.get_item().disconnect(handler)
            list_item.rev_handler = None

    def _update_row(self, row, task: DownloadTask):
        row.name_label.set_label(f"{task.identifier} / {task.file_name}")

        state_text = STATE_LABELS[task.state]
        if task.state == DownloadState.FAILED and task.error:
            state_text = f"Failed — {task.error}"
        row.state_label.set_label(state_text)

        row.progress.set_fraction(
            1.0 if task.state == DownloadState.COMPLETED else task.progress
        )

        bits = []
        if task.size:
            bits.append(f"{format_size(task.downloaded)} of {format_size(task.size)}")
        elif task.downloaded:
            bits.append(format_size(task.downloaded))
        if task.state == DownloadState.RUNNING and task.speed_bps > 0:
            bits.append(f"{format_size(int(task.speed_bps))}/s")
        row.detail_label.set_label(" · ".join(bits))

        if task.state in (DownloadState.RUNNING, DownloadState.QUEUED):
            row.toggle_button.set_icon_name("media-playback-pause-symbolic")
            row.toggle_button.set_tooltip_text("Pause")
            row.toggle_button.set_visible(True)
        elif task.state == DownloadState.PAUSED:
            row.toggle_button.set_icon_name("media-playback-start-symbolic")
            row.toggle_button.set_tooltip_text("Resume")
            row.toggle_button.set_visible(True)
        elif task.state == DownloadState.FAILED:
            row.toggle_button.set_icon_name("view-refresh-symbolic")
            row.toggle_button.set_tooltip_text("Retry")
            row.toggle_button.set_visible(True)
        else:
            row.toggle_button.set_visible(False)

        row.cancel_button.set_visible(
            task.state not in (DownloadState.COMPLETED, DownloadState.CANCELLED)
        )
        row.folder_button.set_visible(task.state == DownloadState.COMPLETED)

    # -- row actions -----------------------------------------------------------

    def _toggle(self, list_item):
        task = list_item.get_item().task
        if task.state in (DownloadState.RUNNING, DownloadState.QUEUED):
            self._manager.pause(task)
        else:
            self._manager.resume(task)

    def _cancel(self, list_item):
        self._manager.cancel(list_item.get_item().task)

    def _open_folder(self, list_item):
        task = list_item.get_item().task
        launcher = Gtk.FileLauncher(file=Gio.File.new_for_path(str(task.dest)))
        launcher.open_containing_folder(self.get_root(), None, None)
