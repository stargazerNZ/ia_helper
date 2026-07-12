from gi.repository import Adw, Gtk

from .. import APP_NAME
from ..core.api import create_session
from ..core.config import load_config
from ..core.downloads import DownloadManager
from ..core.items import ItemClient, ItemDetails
from ..core.search import SearchClient, SearchResult
from ..core.thumbnails import ThumbnailLoader
from .downloads_view import DownloadsView
from .item_view import ItemView
from .search_view import SearchView
from .settings import PreferencesDialog


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(
            application=app,
            title=APP_NAME,
            default_width=920,
            default_height=680,
        )

        # One session for the whole app: connection pooling, User-Agent and
        # (later) credentials are configured once in core.api.
        session = create_session()
        self._config = load_config()
        self._search_client = SearchClient(session)
        self._item_client = ItemClient(session)
        self._thumbs = ThumbnailLoader(session)
        self._manager = DownloadManager(session, self._config)

        self._navigation = Adw.NavigationView()

        self._search_view = SearchView(
            client=self._search_client,
            thumbs=self._thumbs,
            on_error=self.show_error,
            on_item_activated=self.open_item,
        )
        self._downloads_view = DownloadsView(
            manager=self._manager,
            on_error=self.show_error,
        )

        self._view_stack = Adw.ViewStack()
        self._view_stack.add_titled_with_icon(
            self._search_view, "search", "Search", "system-search-symbolic"
        )
        self._view_stack.add_titled_with_icon(
            self._downloads_view, "downloads", "Downloads", "folder-download-symbolic"
        )

        header = Adw.HeaderBar()
        header.set_title_widget(
            Adw.ViewSwitcher(
                stack=self._view_stack, policy=Adw.ViewSwitcherPolicy.WIDE
            )
        )
        settings_button = Gtk.Button(
            icon_name="emblem-system-symbolic", tooltip_text="Preferences"
        )
        settings_button.connect("clicked", self._on_settings_clicked)
        header.pack_end(settings_button)

        root_toolbar = Adw.ToolbarView()
        root_toolbar.add_top_bar(header)
        root_toolbar.set_content(self._view_stack)
        self._navigation.add(
            Adw.NavigationPage(child=root_toolbar, title=APP_NAME, tag="root")
        )

        self._toast_overlay = Adw.ToastOverlay()
        self._toast_overlay.set_child(self._navigation)
        self.set_content(self._toast_overlay)

        self.connect("close-request", self._on_close_request)

    # -- navigation -------------------------------------------------------

    def open_item(self, result: SearchResult) -> None:
        page = ItemView(
            result,
            item_client=self._item_client,
            thumbs=self._thumbs,
            on_error=self.show_error,
            on_browse_query=self.browse_query,
            on_download=self.enqueue_download,
        )
        self._navigation.push(page)

    def browse_query(self, query_text: str) -> None:
        """Jump back to the search page and run a grouping query
        (collection:…, simplelists__…, fav-…)."""
        self._navigation.pop_to_tag("root")
        self._view_stack.set_visible_child_name("search")
        self._search_view.run_query_text(query_text)

    def show_downloads(self) -> None:
        self._navigation.pop_to_tag("root")
        self._view_stack.set_visible_child_name("downloads")

    # -- downloads -----------------------------------------------------------

    def enqueue_download(self, details: ItemDetails, entries) -> None:
        created = self._manager.enqueue(details.identifier, entries)
        toast = Adw.Toast(
            title=f"Queued {len(created)} file{'s' if len(created) != 1 else ''}"
        )
        toast.set_button_label("View")
        toast.connect("button-clicked", lambda *_: self.show_downloads())
        self._toast_overlay.add_toast(toast)

    def _on_settings_clicked(self, _button):
        dialog = PreferencesDialog(
            self._config, on_concurrency_changed=self._manager.set_max_concurrent
        )
        dialog.present(self)

    def _on_close_request(self, _window):
        self._manager.shutdown()
        self._thumbs.shutdown()
        return False  # allow the window to close

    def show_error(self, message: str) -> None:
        self._toast_overlay.add_toast(Adw.Toast(title=message))
