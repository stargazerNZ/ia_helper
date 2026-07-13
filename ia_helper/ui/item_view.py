"""Item view: metadata, groupings ("Member of"), and the file list.

Pushed onto the window's NavigationView when a search result is activated.
Fetches the full metadata record on entry; simple-list memberships are
fetched lazily afterwards (they are a separate endpoint and usually empty).
"""

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango

from ..core.items import ItemDetails, SimpleListMembership
from ..core.search import SearchResult
from .format import format_size
from .worker import run_in_thread

FILE_FILTERS = [
    ("All files", None),
    ("Original files only", "original"),
]


class FileRow(GObject.Object):
    """Wraps a core FileEntry; ``selected`` drives the checkbox column."""

    selected = GObject.Property(type=bool, default=False)

    def __init__(self, entry):
        super().__init__()
        self.entry = entry


class ItemView(Adw.NavigationPage):
    def __init__(self, result: SearchResult, item_client, thumbs, on_error,
                 on_browse_query, on_download):
        super().__init__(title=result.title or result.identifier)
        self._identifier = result.identifier
        self._client = item_client
        self._thumbs = thumbs
        self._on_error = on_error
        self._on_browse_query = on_browse_query
        self._on_download = on_download
        self._details: ItemDetails | None = None
        self._all_rows: list[FileRow] = []

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())

        self._stack = Gtk.Stack()
        self._stack.add_named(self._build_loading_page(), "loading")
        self._stack.add_named(self._build_content_page(), "content")
        self._error_page = Adw.StatusPage(icon_name="dialog-error-symbolic")
        self._stack.add_named(self._error_page, "error")
        self._stack.set_visible_child_name("loading")

        toolbar_view.set_content(self._stack)
        self.set_child(toolbar_view)

        run_in_thread(
            lambda: self._client.get_item(self._identifier),
            self._on_loaded,
            self._on_failed,
        )

    # -- construction -------------------------------------------------

    def _build_loading_page(self):
        spinner = Gtk.Spinner(spinning=True, width_request=32, height_request=32)
        box = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        box.append(spinner)
        return box

    def _build_content_page(self):
        self._content_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=18,
            margin_top=18,
            margin_bottom=18,
            margin_start=18,
            margin_end=18,
        )

        self._build_header()
        self._build_description()
        self._build_member_of()
        self._build_files_section()

        clamp = Adw.Clamp(maximum_size=900, child=self._content_box)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_child(clamp)

        self._restricted_banner = Adw.Banner(
            title="Access-restricted item — its content files can only be "
                  "borrowed on archive.org, not downloaded."
        )
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page.append(self._restricted_banner)
        page.append(scroller)
        return page

    def _build_header(self):
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)

        self._picture = Gtk.Picture(
            width_request=96,
            height_request=96,
            content_fit=Gtk.ContentFit.COVER,
            valign=Gtk.Align.START,
        )
        self._picture.add_css_class("card")
        header.append(self._picture)

        text_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=4,
            valign=Gtk.Align.CENTER,
            hexpand=True,
        )
        self._title_label = Gtk.Label(xalign=0.0, wrap=True, selectable=True)
        self._title_label.add_css_class("title-2")
        self._byline_label = Gtk.Label(xalign=0.0, wrap=True)
        self._detail_label = Gtk.Label(xalign=0.0, wrap=True, selectable=True)
        self._detail_label.add_css_class("dim-label")
        self._detail_label.add_css_class("caption")
        text_box.append(self._title_label)
        text_box.append(self._byline_label)
        text_box.append(self._detail_label)

        self._uploader_button = Gtk.Button(halign=Gtk.Align.START, visible=False)
        self._uploader_button.add_css_class("flat")
        self._uploader_button.set_tooltip_text("Show all items from this uploader")
        self._uploader_button.connect("clicked", self._on_uploader_clicked)
        text_box.append(self._uploader_button)

        self._browse_collection_button = Gtk.Button(
            label="Browse this collection",
            halign=Gtk.Align.START,
            margin_top=6,
            visible=False,
        )
        self._browse_collection_button.add_css_class("suggested-action")
        self._browse_collection_button.connect(
            "clicked", lambda *_: self._on_browse_query(f"collection:{self._identifier}")
        )
        text_box.append(self._browse_collection_button)

        header.append(text_box)
        self._content_box.append(header)

    def _build_description(self):
        self._description_label = Gtk.Label(
            xalign=0.0,
            wrap=True,
            wrap_mode=Pango.WrapMode.WORD_CHAR,
            selectable=True,
            visible=False,
        )
        self._content_box.append(self._description_label)

    def _build_member_of(self):
        self._member_of_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=6, visible=False
        )
        heading = Gtk.Label(label="Member of", xalign=0.0)
        heading.add_css_class("heading")
        self._member_of_box.append(heading)

        self._chip_flow = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            column_spacing=6,
            row_spacing=6,
            max_children_per_line=30,
        )
        self._member_of_box.append(self._chip_flow)
        self._content_box.append(self._member_of_box)

    def _add_chip(self, label: str, query: str, dim: bool = False):
        button = Gtk.Button(label=label)
        button.add_css_class("pill")
        if dim:
            button.add_css_class("flat")
        button.connect("clicked", lambda *_: self._on_browse_query(query))
        self._chip_flow.append(button)
        self._member_of_box.set_visible(True)

    def _build_files_section(self):
        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        heading = Gtk.Label(label="Files", xalign=0.0, hexpand=True)
        heading.add_css_class("heading")
        toolbar.append(heading)

        self._filter_dropdown = Gtk.DropDown.new_from_strings(
            [label for label, _ in FILE_FILTERS]
        )
        self._filter_dropdown.connect("notify::selected", lambda *_: self._refill_files())
        toolbar.append(self._filter_dropdown)

        select_all = Gtk.Button(label="Select all")
        select_all.connect("clicked", lambda *_: self._set_all_selected(True))
        toolbar.append(select_all)
        select_none = Gtk.Button(label="Select none")
        select_none.connect("clicked", lambda *_: self._set_all_selected(False))
        toolbar.append(select_none)
        section.append(toolbar)

        self._file_store = Gio.ListStore(item_type=FileRow)
        column_view = Gtk.ColumnView(
            model=Gtk.NoSelection(model=self._file_store),
            reorderable=False,
        )
        column_view.add_css_class("data-table")
        column_view.append_column(self._make_check_column())
        column_view.append_column(self._make_text_column("Name", self._bind_name, expand=True))
        column_view.append_column(self._make_text_column("Format", self._bind_format))
        column_view.append_column(self._make_text_column("Size", self._bind_size))

        file_scroller = Gtk.ScrolledWindow(
            propagate_natural_height=True,
            max_content_height=420,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
        )
        file_scroller.set_child(column_view)
        file_scroller.add_css_class("card")
        section.append(file_scroller)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._selection_label = Gtk.Label(xalign=0.0, hexpand=True)
        self._selection_label.add_css_class("dim-label")
        footer.append(self._selection_label)

        self._download_button = Gtk.Button(label="Download selected", sensitive=False)
        self._download_button.add_css_class("suggested-action")
        self._download_button.set_tooltip_text("Select files to download")
        self._download_button.connect("clicked", self._on_download_clicked)
        footer.append(self._download_button)
        section.append(footer)

        self._content_box.append(section)

    # -- file list columns ---------------------------------------------

    def _make_check_column(self):
        factory = Gtk.SignalListItemFactory()

        def setup(_factory, list_item):
            check = Gtk.CheckButton()
            list_item.set_child(check)

        def bind(_factory, list_item):
            check = list_item.get_child()
            row: FileRow = list_item.get_item()
            check.set_sensitive(not row.entry.private)
            check.set_tooltip_text(
                "This file is access-restricted and cannot be downloaded"
                if row.entry.private
                else None
            )
            binding = row.bind_property(
                "selected",
                check,
                "active",
                GObject.BindingFlags.SYNC_CREATE | GObject.BindingFlags.BIDIRECTIONAL,
            )
            list_item.binding = binding

        def unbind(_factory, list_item):
            binding = getattr(list_item, "binding", None)
            if binding is not None:
                binding.unbind()
                list_item.binding = None

        factory.connect("setup", setup)
        factory.connect("bind", bind)
        factory.connect("unbind", unbind)
        return Gtk.ColumnViewColumn(factory=factory)

    def _make_text_column(self, title, bind_func, expand=False):
        factory = Gtk.SignalListItemFactory()

        def setup(_factory, list_item):
            label = Gtk.Label(xalign=0.0, ellipsize=Pango.EllipsizeMode.MIDDLE)
            list_item.set_child(label)

        def bind(_factory, list_item):
            bind_func(list_item.get_child(), list_item.get_item())

        factory.connect("setup", setup)
        factory.connect("bind", bind)
        return Gtk.ColumnViewColumn(title=title, factory=factory, expand=expand)

    def _bind_name(self, label, row: FileRow):
        label.set_label(row.entry.name)
        # Rows are recycled: state must be set both ways on every bind.
        if row.entry.private:
            label.add_css_class("dim-label")
            label.set_tooltip_text(f"{row.entry.name} (access-restricted)")
        else:
            label.remove_css_class("dim-label")
            label.set_tooltip_text(row.entry.name)

    def _bind_format(self, label, row: FileRow):
        entry = row.entry
        # Rows are recycled: label and tooltip must be set on every bind.
        if entry.private:
            label.set_label(f"{entry.format} · restricted")
            label.set_tooltip_text(None)
        elif entry.drm:
            label.set_label(f"{entry.format} · DRM")
            label.set_tooltip_text(
                "DRM-protected — requires an active archive.org loan and a "
                "compatible reader (e.g. Adobe Digital Editions) to open"
            )
        else:
            label.set_label(entry.format)
            label.set_tooltip_text(None)

    def _bind_size(self, label, row: FileRow):
        label.set_label(format_size(row.entry.size) if row.entry.size else "")

    # -- data loading ----------------------------------------------------

    def _on_loaded(self, details: ItemDetails):
        self._details = details

        if details.is_dark:
            self._error_page.set_title("Item unavailable")
            self._error_page.set_description(
                "This item is dark (access-restricted) and its content cannot be viewed."
            )
            self._stack.set_visible_child_name("error")
            return

        self.set_title(details.title)
        self._title_label.set_label(details.title)

        byline_bits = [b for b in (details.creator, details.date) if b]
        self._byline_label.set_label(" · ".join(byline_bits))
        self._byline_label.set_visible(bool(byline_bits))

        detail_bits = [details.mediatype, details.identifier]
        if details.item_size:
            detail_bits.append(format_size(details.item_size))
        detail_bits.append(f"{details.files_count or len(details.files)} files")
        self._detail_label.set_label(" · ".join(b for b in detail_bits if b))

        if details.uploader:
            self._uploader_button.set_label(f"Uploaded by {details.uploader}")
            self._uploader_button.set_visible(True)

        if details.description:
            self._description_label.set_label(details.description)
            self._description_label.set_visible(True)

        self._browse_collection_button.set_visible(details.is_collection)
        self._restricted_banner.set_revealed(details.access_restricted)

        for collection in details.collections:
            self._add_chip(collection, f"collection:{collection}")

        self._all_rows = []
        for entry in details.files:
            row = FileRow(entry)
            row.connect("notify::selected", lambda *_: self._update_selection_summary())
            self._all_rows.append(row)
        self._refill_files()

        self._stack.set_visible_child_name("content")

        self._thumbs.fetch(
            details.identifier,
            lambda ident, data: GLib.idle_add(self._apply_thumbnail, data),
        )
        run_in_thread(
            lambda: self._client.get_simplelists(details.identifier),
            self._on_simplelists_loaded,
            lambda exc: None,  # memberships are optional decoration
        )

    def _on_uploader_clicked(self, _button):
        if self._details is not None and self._details.uploader:
            self._on_browse_query(f'uploader:"{self._details.uploader}"')

    def _on_failed(self, exc):
        self._error_page.set_title("Couldn't load item")
        self._error_page.set_description(str(exc))
        self._stack.set_visible_child_name("error")
        self._on_error(f"Failed to load {self._identifier}: {exc}")

    def _on_simplelists_loaded(self, memberships: list[SimpleListMembership]):
        for membership in memberships:
            self._add_chip(membership.label, membership.to_query(), dim=True)

    def _apply_thumbnail(self, data):
        if data is None:
            return
        try:
            texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
        except GLib.Error:
            return
        self._picture.set_paintable(texture)

    # -- file selection ----------------------------------------------------

    def _visible_rows(self):
        wanted = FILE_FILTERS[self._filter_dropdown.get_selected()][1]
        if wanted is None:
            return self._all_rows
        return [r for r in self._all_rows if r.entry.source == wanted]

    def _refill_files(self):
        self._file_store.remove_all()
        for row in self._visible_rows():
            self._file_store.append(row)
        self._update_selection_summary()

    def _set_all_selected(self, selected: bool):
        for row in self._visible_rows():
            # Select all skips restricted files (never selectable) and DRM
            # containers (selectable, but only by an explicit individual
            # tick). Select none clears everything, including DRM files.
            if selected and (row.entry.private or row.entry.drm):
                continue
            row.selected = selected

    def _update_selection_summary(self):
        chosen = [r for r in self._all_rows if r.selected]
        if not chosen:
            self._selection_label.set_label("No files selected")
        else:
            total = sum(r.entry.size for r in chosen)
            self._selection_label.set_label(
                f"{len(chosen)} file{'s' if len(chosen) != 1 else ''} selected · {format_size(total)}"
            )
        self._download_button.set_sensitive(bool(chosen) and self._details is not None)

    def _on_download_clicked(self, _button):
        entries = [r.entry for r in self._all_rows if r.selected]
        if entries and self._details is not None:
            self._on_download(self._details, entries)
