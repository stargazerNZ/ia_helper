"""Preferences dialog: downloads and Internet Archive account."""

from pathlib import Path

from gi.repository import Adw, Gtk

from ..core.account import AccountInfo
from ..core.config import MAX_CONCURRENT_LIMIT, Config, save_config


class PreferencesDialog(Adw.PreferencesDialog):
    def __init__(self, config: Config, on_concurrency_changed, on_bandwidth_changed,
                 account: AccountInfo | None, on_sign_in, on_sign_out):
        """``on_sign_in(email, password, on_done)`` performs the sign-in off
        the main loop and calls ``on_done(info, exc)`` back on it;
        ``on_sign_out()`` clears stored credentials synchronously."""
        super().__init__(title="Preferences")
        self._config = config
        self._on_concurrency_changed = on_concurrency_changed
        self._on_bandwidth_changed = on_bandwidth_changed
        self._account = account
        self._on_sign_in = on_sign_in
        self._on_sign_out = on_sign_out

        page = Adw.PreferencesPage()
        page.add(self._build_downloads_group())
        self._account_group = Adw.PreferencesGroup(
            title="Internet Archive account",
            description=(
                "Signing in stores API keys in the standard ia config file; "
                "your password is used once and never saved."
            ),
        )
        self._account_rows: list[Gtk.Widget] = []
        self._populate_account_rows()
        page.add(self._account_group)
        self.add(page)

    # -- downloads --------------------------------------------------------

    def _build_downloads_group(self):
        group = Adw.PreferencesGroup(title="Downloads")

        self._dir_row = Adw.ActionRow(
            title="Download folder",
            subtitle=str(self._config.download_dir),
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
                value=self._config.max_concurrent_downloads,
            ),
        )
        spin.connect("notify::value", self._on_concurrency_spun)
        group.add(spin)

        bandwidth = Adw.SpinRow(
            title="Bandwidth limit",
            subtitle="Kilobytes per second, shared across all downloads · 0 = unlimited",
            adjustment=Gtk.Adjustment(
                lower=0,
                upper=1_000_000,
                step_increment=64,
                page_increment=1024,
                value=self._config.bandwidth_limit_kbps,
            ),
        )
        bandwidth.connect("notify::value", self._on_bandwidth_spun)
        group.add(bandwidth)
        return group

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

    def _on_bandwidth_spun(self, row, _param):
        value = int(row.get_value())
        if value != self._config.bandwidth_limit_kbps:
            self._config.bandwidth_limit_kbps = value
            save_config(self._config)
            self._on_bandwidth_changed(value)

    # -- account ------------------------------------------------------------

    def _populate_account_rows(self):
        for row in self._account_rows:
            self._account_group.remove(row)
        self._account_rows = []

        if self._account is not None:
            self._add_signed_in_rows()
        else:
            self._add_sign_in_rows()

    def _add_account_row(self, row):
        self._account_group.add(row)
        self._account_rows.append(row)

    def _add_signed_in_rows(self):
        row = Adw.ActionRow(
            title=f"Signed in as {self._account.display_name}",
            subtitle=self._account.email,
        )
        sign_out = Gtk.Button(label="Sign out", valign=Gtk.Align.CENTER)
        sign_out.add_css_class("destructive-action")
        sign_out.connect("clicked", self._on_sign_out_clicked)
        row.add_suffix(sign_out)
        self._add_account_row(row)

    def _add_sign_in_rows(self):
        self._email_row = Adw.EntryRow(title="Email")
        self._add_account_row(self._email_row)

        self._password_row = Adw.PasswordEntryRow(title="Password")
        self._add_account_row(self._password_row)

        action_row = Adw.ActionRow()
        self._sign_in_spinner = Gtk.Spinner(valign=Gtk.Align.CENTER)
        action_row.add_prefix(self._sign_in_spinner)
        self._sign_in_button = Gtk.Button(label="Sign in", valign=Gtk.Align.CENTER)
        self._sign_in_button.add_css_class("suggested-action")
        self._sign_in_button.connect("clicked", self._on_sign_in_clicked)
        action_row.add_suffix(self._sign_in_button)
        self._add_account_row(action_row)

    def _on_sign_in_clicked(self, _button):
        email = self._email_row.get_text().strip()
        password = self._password_row.get_text()
        if not email or not password:
            self.add_toast(Adw.Toast(title="Enter your email and password"))
            return
        self._sign_in_button.set_sensitive(False)
        self._sign_in_spinner.start()
        self._on_sign_in(email, password, self._on_sign_in_done)

    def _on_sign_in_done(self, info, exc):
        # Runs on the main loop (window trampolines). The password row is
        # discarded with the rebuilt rows either way.
        if exc is not None or info is None:
            self._sign_in_spinner.stop()
            self._sign_in_button.set_sensitive(True)
            self._password_row.set_text("")
            message = str(exc) if exc is not None else "Could not verify the account"
            self.add_toast(Adw.Toast(title=f"Sign-in failed: {message}"))
            return
        self._account = info
        self._populate_account_rows()

    def _on_sign_out_clicked(self, _button):
        self._on_sign_out()
        self._account = None
        self._populate_account_rows()
