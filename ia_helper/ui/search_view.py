"""Search view: query entry, mediatype filter, results list, paging."""

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango

from ..core.search import MEDIATYPES, SearchQuery, SearchResult
from .format import format_size
from .worker import run_in_thread

THUMB_SIZE = 64


class ResultItem(GObject.Object):
    """GObject wrapper so SearchResult dataclasses can live in a ListStore."""

    def __init__(self, result: SearchResult):
        super().__init__()
        self.result = result


class SearchView(Gtk.Box):
    def __init__(self, client, thumbs, on_error, on_item_activated):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._on_error = on_error
        self._on_item_activated = on_item_activated

        self._client = client
        self._thumbs = thumbs

        # Monotonic token: results from a superseded search are dropped.
        self._search_token = 0
        self._current_query: SearchQuery | None = None
        self._current_page = None

        self._build_controls()
        self._build_results_list()
        self._build_footer()

    # -- construction -------------------------------------------------

    def _build_controls(self):
        controls = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6,
            margin_top=12,
            margin_bottom=6,
            margin_start=12,
            margin_end=12,
        )

        self._entry = Gtk.SearchEntry(hexpand=True)
        self._entry.set_placeholder_text("Search the Internet Archive…")
        self._entry.connect("activate", lambda *_: self._start_search())
        controls.append(self._entry)

        self._mediatype_dropdown = Gtk.DropDown.new_from_strings(
            [label for label, _ in MEDIATYPES]
        )
        self._mediatype_dropdown.set_tooltip_text("Media type")
        controls.append(self._mediatype_dropdown)

        search_button = Gtk.Button(label="Search")
        search_button.add_css_class("suggested-action")
        search_button.connect("clicked", lambda *_: self._start_search())
        controls.append(search_button)

        self.append(controls)

        self._status_label = Gtk.Label(
            xalign=0.0,
            margin_start=12,
            margin_end=12,
            margin_bottom=6,
        )
        self._status_label.add_css_class("dim-label")
        self.append(self._status_label)

    def _build_results_list(self):
        self._store = Gio.ListStore(item_type=ResultItem)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_row_setup)
        factory.connect("bind", self._on_row_bind)
        factory.connect("unbind", self._on_row_unbind)

        self._list_view = Gtk.ListView(
            model=Gtk.NoSelection(model=self._store),
            factory=factory,
            single_click_activate=True,
        )
        self._list_view.add_css_class("navigation-sidebar")
        self._list_view.connect("activate", self._on_row_activated)

        self._empty_page = Adw.StatusPage(
            title="Search the Internet Archive",
            description="Enter a query above to find items, texts, media and collections.",
            icon_name="system-search-symbolic",
            vexpand=True,
        )

        self._scroller = Gtk.ScrolledWindow(vexpand=True)
        self._scroller.set_child(self._list_view)

        self._content_stack = Gtk.Stack(vexpand=True)
        self._content_stack.add_named(self._empty_page, "empty")
        self._content_stack.add_named(self._scroller, "results")
        self._content_stack.set_visible_child_name("empty")
        self.append(self._content_stack)

    def _build_footer(self):
        footer = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            halign=Gtk.Align.CENTER,
            margin_top=6,
            margin_bottom=12,
            spacing=6,
        )

        self._spinner = Gtk.Spinner()
        footer.append(self._spinner)

        self._load_more_button = Gtk.Button(label="Load more", visible=False)
        self._load_more_button.connect("clicked", lambda *_: self._load_next_page())
        footer.append(self._load_more_button)

        self.append(footer)

    # -- row factory ---------------------------------------------------

    def _on_row_setup(self, _factory, list_item):
        row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            margin_top=6,
            margin_bottom=6,
            margin_start=6,
            margin_end=6,
        )

        picture = Gtk.Picture(
            width_request=THUMB_SIZE,
            height_request=THUMB_SIZE,
            content_fit=Gtk.ContentFit.COVER,
        )
        picture.add_css_class("card")
        row.append(picture)

        text_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=2,
            valign=Gtk.Align.CENTER,
            hexpand=True,
        )
        title = Gtk.Label(xalign=0.0, ellipsize=Pango.EllipsizeMode.END)
        title.add_css_class("heading")
        subtitle = Gtk.Label(xalign=0.0, ellipsize=Pango.EllipsizeMode.END)
        detail = Gtk.Label(xalign=0.0, ellipsize=Pango.EllipsizeMode.END)
        detail.add_css_class("dim-label")
        detail.add_css_class("caption")
        text_box.append(title)
        text_box.append(subtitle)
        text_box.append(detail)
        row.append(text_box)

        # Stash child references on the row for bind-time access.
        row.picture = picture
        row.title = title
        row.subtitle = subtitle
        row.detail = detail
        row.identifier = None
        list_item.set_child(row)

    def _on_row_bind(self, _factory, list_item):
        row = list_item.get_child()
        result: SearchResult = list_item.get_item().result

        row.title.set_label(result.title)
        subtitle_bits = [b for b in (result.creator, result.date) if b]
        row.subtitle.set_label(" · ".join(subtitle_bits))
        row.subtitle.set_visible(bool(subtitle_bits))

        detail_bits = [result.mediatype, result.identifier]
        if result.item_size:
            detail_bits.append(format_size(result.item_size))
        if result.access_restricted:
            detail_bits.append("access-restricted")
        row.detail.set_label(" · ".join(b for b in detail_bits if b))

        # Rows are recycled: tag with the identifier so a slow thumbnail for
        # a previous occupant can't land on the wrong row, and cancel the
        # previous occupant's fetch so scrolling a large result set doesn't
        # build a queue of thumbnails nobody is looking at.
        row.identifier = result.identifier
        row.picture.set_paintable(None)
        self._cancel_row_fetch(row)
        row.thumb_future = self._thumbs.fetch(
            result.identifier,
            lambda ident, data: GLib.idle_add(self._apply_thumbnail, row, ident, data),
        )

    def _on_row_unbind(self, _factory, list_item):
        self._cancel_row_fetch(list_item.get_child())

    @staticmethod
    def _cancel_row_fetch(row):
        future = getattr(row, "thumb_future", None)
        if future is not None:
            future.cancel()  # no-op if already running or done
            row.thumb_future = None

    def _apply_thumbnail(self, row, identifier, data):
        if data is None or row.identifier != identifier:
            return
        try:
            texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
        except GLib.Error:
            return
        row.picture.set_paintable(texture)

    # -- searching -----------------------------------------------------

    def _on_row_activated(self, _list_view, position):
        item = self._store.get_item(position)
        if item is not None:
            self._on_item_activated(item.result)

    def run_query_text(self, query_text: str):
        """Run a raw Lucene query (used for collection/list browsing).

        The query is placed in the entry so the user can see and refine it.
        """
        self._entry.set_text(query_text)
        self._mediatype_dropdown.set_selected(0)
        self._start_search()

    def _selected_mediatype(self):
        return MEDIATYPES[self._mediatype_dropdown.get_selected()][1]

    def _start_search(self):
        text = self._entry.get_text().strip()
        mediatype = self._selected_mediatype()
        if not text and not mediatype:
            return

        self._current_query = SearchQuery(text=text, mediatype=mediatype)
        # Drop thumbnail fetches still queued for the previous result set,
        # or the new results' thumbnails wait in line behind them.
        self._thumbs.cancel_pending()
        self._store.remove_all()
        self._current_page = None
        self._status_label.set_label("")
        self._content_stack.set_visible_child_name("results")
        self._fetch_page(1)

    def _load_next_page(self):
        if self._current_page is not None and self._current_page.has_more:
            self._fetch_page(self._current_page.page + 1)

    def _fetch_page(self, page_number: int):
        self._search_token += 1
        token = self._search_token
        query = self._current_query

        self._spinner.start()
        self._load_more_button.set_sensitive(False)

        run_in_thread(
            lambda: self._client.search(query, page=page_number),
            lambda page: self._on_page_loaded(token, page),
            lambda exc: self._on_search_failed(token, exc),
        )

    def _on_page_loaded(self, token, page):
        if token != self._search_token:
            return
        self._spinner.stop()
        self._load_more_button.set_sensitive(True)

        self._current_page = page
        for result in page.results:
            self._store.append(ResultItem(result))

        shown = self._store.get_n_items()
        if page.total == 0:
            self._status_label.set_label("No results.")
        else:
            self._status_label.set_label(f"Showing {shown:,} of {page.total:,} results")
        self._load_more_button.set_visible(page.has_more)

    def _on_search_failed(self, token, exc):
        if token != self._search_token:
            return
        self._spinner.stop()
        self._load_more_button.set_sensitive(True)
        self._on_error(f"Search failed: {exc}")
