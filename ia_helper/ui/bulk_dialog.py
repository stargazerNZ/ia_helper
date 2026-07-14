"""Bulk download dialog: survey the query, then require explicit confirmation.

Nothing is queued until the user has seen the item count and total size —
IA collections routinely run to terabytes (collection:dvdtray measures
~130 TB), so the size line is the whole point of this dialog.
"""

from gi.repository import Adw, Gtk

from ..core.scrape import MAX_BULK_ITEMS, Survey
from .format import format_size
from .worker import run_in_thread


class BulkDownloadDialog(Adw.Dialog):
    def __init__(self, query: str, label: str, scrape_client, download_dir,
                 on_confirm):
        """``on_confirm(query, label, original_only, total_items)`` runs when
        the user explicitly queues the job."""
        super().__init__(title="Bulk download", content_width=440)
        self._query = query
        self._label = label
        self._scrape = scrape_client
        self._on_confirm = on_confirm
        self._survey: Survey | None = None

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())

        self._stack = Gtk.Stack(
            margin_top=6, margin_bottom=18, margin_start=18, margin_end=18
        )
        self._stack.add_named(self._build_measuring_page(), "measuring")
        self._stack.add_named(self._build_confirm_page(download_dir), "confirm")
        self._status_page = Adw.StatusPage(icon_name="dialog-warning-symbolic")
        self._stack.add_named(self._status_page, "status")
        self._stack.set_visible_child_name("measuring")

        toolbar.set_content(self._stack)
        self.set_child(toolbar)

        run_in_thread(
            lambda: self._scrape.survey(self._query),
            self._on_survey_done,
            self._on_survey_failed,
        )

    # -- pages -----------------------------------------------------------

    def _build_measuring_page(self):
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            valign=Gtk.Align.CENTER,
            halign=Gtk.Align.CENTER,
        )
        box.append(Gtk.Spinner(spinning=True, width_request=32, height_request=32))
        label = Gtk.Label(label=f"Measuring “{self._label}”…")
        label.add_css_class("dim-label")
        box.append(label)
        return box

    def _build_confirm_page(self, download_dir):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        self._summary_label = Gtk.Label(xalign=0.0, wrap=True)
        self._summary_label.add_css_class("title-4")
        box.append(self._summary_label)

        self._detail_label = Gtk.Label(xalign=0.0, wrap=True)
        self._detail_label.add_css_class("dim-label")
        box.append(self._detail_label)

        group = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        group.add_css_class("boxed-list")

        self._original_switch = Adw.SwitchRow(
            title="Original files only",
            subtitle="Skip derivative files the Archive generated "
                     "(smaller and usually what you want)",
            active=True,
        )
        group.append(self._original_switch)

        dest_row = Adw.ActionRow(
            title="Destination",
            subtitle=str(download_dir),
        )
        group.append(dest_row)
        box.append(group)

        note = Gtk.Label(
            xalign=0.0,
            wrap=True,
            label="Items download one at a time as the queue drains. "
                  "Restricted items and DRM lending files are skipped. "
                  "The job can be paused or cancelled from the Downloads view.",
        )
        note.add_css_class("caption")
        note.add_css_class("dim-label")
        box.append(note)

        self._confirm_button = Gtk.Button(
            label="Queue bulk download",
            halign=Gtk.Align.END,
            margin_top=6,
        )
        self._confirm_button.add_css_class("suggested-action")
        self._confirm_button.connect("clicked", self._on_confirm_clicked)
        box.append(self._confirm_button)
        return box

    # -- survey results ----------------------------------------------------

    def _on_survey_done(self, survey: Survey):
        self._survey = survey
        if survey.truncated:
            self._status_page.set_title("Query too broad")
            self._status_page.set_description(
                f"More than {MAX_BULK_ITEMS:,} items match. Refine the query "
                "(e.g. add a mediatype or date filter) and try again."
            )
            self._stack.set_visible_child_name("status")
            return
        if survey.items == 0:
            self._status_page.set_title("Nothing to download")
            self._status_page.set_description("The query matched no items.")
            self._stack.set_visible_child_name("status")
            return

        self._summary_label.set_label(
            f"{survey.items:,} items · up to {format_size(survey.total_bytes)}"
        )
        bits = [f"Query: {self._label}"]
        if survey.restricted:
            bits.append(
                f"{survey.restricted:,} access-restricted item"
                f"{'s' if survey.restricted != 1 else ''} will be skipped"
            )
        self._detail_label.set_label("\n".join(bits))
        self._stack.set_visible_child_name("confirm")

    def _on_survey_failed(self, exc):
        self._status_page.set_title("Couldn't measure the query")
        self._status_page.set_description(str(exc))
        self._stack.set_visible_child_name("status")

    def _on_confirm_clicked(self, _button):
        self._on_confirm(
            self._query,
            self._label,
            self._original_switch.get_active(),
            self._survey.items,
        )
        self.close()
