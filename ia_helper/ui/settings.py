"""Preferences dialog: download directory and concurrency."""

from pathlib import Path

from gi.repository import Adw, Gio, Gtk

from ..core.config import MAX_CONCURRENT_LIMIT, Config, save_config


class PreferencesDialog(Adw.PreferencesDialog):
    def __init__(self, config: Config, on_concurrency_changed):
        super().__init__(title="Preferences")
        self._config = config
        self._on_concurrency_changed = on_concurrency_changed

        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title="Downloads")

        self._dir_row = Adw.ActionRow(
            title="Download folder",
            subtitle=str(config.download_dir),
        )
        choose = Gtk.Button(
            icon_name="folder-open-symbolic",
            valign=Gtk.Align.CENTER,
            tooltip_text="Choose folder",
        )
        choose.connect("clicked", self._on_choose_folder)
        self._dir_row.add_suffix(choose)
        group.add(self._dir_row)

        spin = Adw.SpinRow(
            title="Concurrent downloads",
            subtitle="Kept low out of politeness to archive.org",
            adjustment=Gtk.Adjustment(
                lower=1,
                upper=MAX_CONCURRENT_LIMIT,
                step_increment=1,
                value=config.max_concurrent_downloads,
            ),
        )
        spin.connect("notify::value", self._on_concurrency_spun)
        group.add(spin)

        page.add(group)
        self.add(page)

    def _on_choose_folder(self, _button):
        dialog = Gtk.FileDialog(title="Choose download folder")
        dialog.select_folder(self.get_root(), None, self._on_folder_chosen)

    def _on_folder_chosen(self, dialog, result):
        try:
            folder = dialog.select_folder_finish(result)
        except Exception:  # noqa: BLE001 — user dismissed the dialog
            return
        if folder is None:
            return
        self._config.download_dir = Path(folder.get_path())
        self._dir_row.set_subtitle(str(self._config.download_dir))
        save_config(self._config)

    def _on_concurrency_spun(self, row, _param):
        value = int(row.get_value())
        if value != self._config.max_concurrent_downloads:
            self._config.max_concurrent_downloads = value
            save_config(self._config)
            self._on_concurrency_changed(value)
