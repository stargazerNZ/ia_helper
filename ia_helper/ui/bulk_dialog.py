"""Bulk download dialog: survey the query, then require explicit confirmation.

Nothing is queued until the user has seen the item count and total size —
IA collections routinely run to terabytes (collection:dvdtray measures
~130 TB), so the size line is the whole point of this dialog.
"""

from gi.repository import Adw, Gtk

from ..core.scrape import MAX_BULK_ITEMS, NOISE_FORMATS, Survey
from .format import format_size
from .worker import run_in_thread

FILE_MODES = ["All files", "Original files only", "Specific formats…"]
MODE_ALL, MODE_ORIGINALS, MODE_FORMATS = range(3)


class BulkDownloadDialog(Adw.Dialog):
    def __init__(self, query: str, label: str, scrape_client, download_dir,
                 on_confirm):
        """``on_confirm(query, label, original_only, formats, total_items)``
        runs when the user explicitly queues the job."""
        super().__init__(title="Bulk download", content_width=460)
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

        self._mode_row = Adw.ComboRow(
            title="Files",
            subtitle="Originals skip Archive-generated derivatives",
            model=Gtk.StringList.new(FILE_MODES),
            selected=MODE_ORIGINALS,
        )
        self._mode_row.connect("notify::selected", lambda *_: self._on_mode_changed())
        group.append(self._mode_row)

        dest_row = Adw.ActionRow(
            title="Destination",
            subtitle=str(download_dir),
        )
        group.append(dest_row)
        box.append(group)

        # Format checklist, populated from the survey; shown only in
        # "Specific formats…" mode.
        self._formats_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._formats_list.add_css_class("boxed-list")
        formats_scroller = Gtk.ScrolledWindow(
            # Without a minimum, the dialog's height negotiation collapses
            # the scroller to a single row; propagate_natural_height alone
            # doesn't survive the Revealer/Dialog measurement chain.
            min_content_height=240,
            max_content_height=320,
            propagate_natural_height=True,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            child=self._formats_list,
        )
        self._formats_revealer = Gtk.Revealer(
            child=formats_scroller, reveal_child=False
        )
        box.append(self._formats_revealer)
        self._format_switches: dict[str, Adw.SwitchRow] = {}

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
        self._populate_formats(survey)
        self._stack.set_visible_child_name("confirm")

    def _populate_formats(self, survey: Survey):
        content = sorted(
            ((fmt, n) for fmt, n in survey.formats.items()
             if fmt not in NOISE_FORMATS),
            key=lambda pair: (-pair[1], pair[0]),
        )
        noise = sorted(
            ((fmt, n) for fmt, n in survey.formats.items()
             if fmt in NOISE_FORMATS),
            key=lambda pair: (-pair[1], pair[0]),
        )

        def make_switch(fmt, count):
            row = Adw.SwitchRow(
                title=fmt,
                subtitle=f"{count:,} of {survey.items:,} items",
            )
            row.connect(
                "notify::active", lambda *_: self._update_confirm_sensitivity()
            )
            self._format_switches[fmt] = row
            return row

        for fmt, count in content:
            self._formats_list.append(make_switch(fmt, count))
        if noise:
            expander = Adw.ExpanderRow(
                title="Technical formats",
                subtitle="Metadata, OCR, torrents and other machinery",
            )
            for fmt, count in noise:
                expander.add_row(make_switch(fmt, count))
            self._formats_list.append(expander)

    def _on_survey_failed(self, exc):
        self._status_page.set_title("Couldn't measure the query")
        self._status_page.set_description(str(exc))
        self._stack.set_visible_child_name("status")

    def _on_mode_changed(self):
        self._formats_revealer.set_reveal_child(
            self._mode_row.get_selected() == MODE_FORMATS
        )
        self._update_confirm_sensitivity()

    def _selected_formats(self) -> list[str]:
        return [
            fmt for fmt, row in self._format_switches.items() if row.get_active()
        ]

    def _update_confirm_sensitivity(self):
        if self._mode_row.get_selected() == MODE_FORMATS:
            self._confirm_button.set_sensitive(bool(self._selected_formats()))
        else:
            self._confirm_button.set_sensitive(True)

    def _on_confirm_clicked(self, _button):
        mode = self._mode_row.get_selected()
        self._on_confirm(
            self._query,
            self._label,
            mode == MODE_ORIGINALS,
            self._selected_formats() if mode == MODE_FORMATS else [],
            self._survey.items,
        )
        self.close()
