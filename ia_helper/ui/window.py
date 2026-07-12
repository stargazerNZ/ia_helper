from gi.repository import Adw, Gtk

from .. import APP_NAME
from ..core.api import create_session
from ..core.items import ItemClient
from ..core.search import SearchClient, SearchResult
from ..core.thumbnails import ThumbnailLoader
from .item_view import ItemView
from .search_view import SearchView


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
        self._search_client = SearchClient(session)
        self._item_client = ItemClient(session)
        self._thumbs = ThumbnailLoader(session)

        self._navigation = Adw.NavigationView()

        self._search_view = SearchView(
            client=self._search_client,
            thumbs=self._thumbs,
            on_error=self.show_error,
            on_item_activated=self.open_item,
        )
        search_toolbar = Adw.ToolbarView()
        search_toolbar.add_top_bar(Adw.HeaderBar())
        search_toolbar.set_content(self._search_view)
        self._navigation.add(
            Adw.NavigationPage(child=search_toolbar, title=APP_NAME, tag="search")
        )

        self._toast_overlay = Adw.ToastOverlay()
        self._toast_overlay.set_child(self._navigation)
        self.set_content(self._toast_overlay)

    def open_item(self, result: SearchResult) -> None:
        page = ItemView(
            result,
            item_client=self._item_client,
            thumbs=self._thumbs,
            on_error=self.show_error,
            on_browse_query=self.browse_query,
        )
        self._navigation.push(page)

    def browse_query(self, query_text: str) -> None:
        """Jump back to the search page and run a grouping query
        (collection:…, simplelists__…, fav-…)."""
        self._navigation.pop_to_tag("search")
        self._search_view.run_query_text(query_text)

    def show_error(self, message: str) -> None:
        self._toast_overlay.add_toast(Adw.Toast(title=message))
