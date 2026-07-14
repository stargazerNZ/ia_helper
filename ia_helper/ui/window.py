from gi.repository import Adw, Gio, Gtk

from .. import APP_ID, APP_NAME, PROJECT_URL, __version__
from ..core import account
from ..core.api import create_session
from ..core.bulk import BulkManager
from ..core.scrape import ScrapeClient
from ..core.config import load_config
from ..core.downloads import DownloadManager
from ..core.items import ItemClient, ItemDetails
from ..core.search import SearchClient, SearchResult
from ..core.thumbnails import ThumbnailLoader
from .bulk_dialog import BulkDownloadDialog
from .downloads_view import DownloadsView
from .item_view import ItemView
from .search_view import SearchView
from .settings import PreferencesDialog
from .worker import run_in_thread


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(
            application=app,
            title=APP_NAME,
            default_width=920,
            default_height=680,
        )

        # One session for the whole app: connection pooling, User-Agent and
        # stored account credentials are configured once in core.api.
        self._session = create_session()
        self._config = load_config()
        self._account: account.AccountInfo | None = None
        self._search_client = SearchClient(self._session)
        self._item_client = ItemClient(self._session)
        self._thumbs = ThumbnailLoader(self._session)
        self._manager = DownloadManager(self._session, self._config)
        self._scrape_client = ScrapeClient(self._session)
        self._bulk_manager = BulkManager(
            self._scrape_client, self._item_client, self._manager
        )

        self._navigation = Adw.NavigationView()

        self._search_view = SearchView(
            client=self._search_client,
            thumbs=self._thumbs,
            on_error=self.show_error,
            on_item_activated=self.open_item,
            on_bulk_requested=self.open_bulk_dialog,
        )
        self._downloads_view = DownloadsView(
            manager=self._manager,
            bulk_manager=self._bulk_manager,
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
        menu = Gio.Menu()
        account_section = Gio.Menu()
        account_section.append("My favorites", "win.my-favorites")
        account_section.append("My uploads", "win.my-uploads")
        menu.append_section(None, account_section)
        app_section = Gio.Menu()
        app_section.append("Preferences", "win.preferences")
        app_section.append(f"About {APP_NAME}", "win.about")
        menu.append_section(None, app_section)
        header.pack_end(
            Gtk.MenuButton(
                icon_name="open-menu-symbolic",
                menu_model=menu,
                tooltip_text="Main menu",
            )
        )

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
        self._install_actions()
        self._search_view.grab_search_focus()

        # Resolve stored credentials (if any) to an account; no network
        # happens when no keys are configured.
        run_in_thread(
            lambda: account.fetch_user_info(self._session),
            self._set_account,
            lambda exc: None,  # offline at startup: stay signed out
        )

    def _install_actions(self):
        actions = [
            ("preferences", lambda *_: self._on_settings_clicked(None)),
            ("about", lambda *_: self._show_about()),
            ("focus-search", lambda *_: self._focus_search()),
            ("show-search", lambda *_: self._show_view("search")),
            ("show-downloads", lambda *_: self.show_downloads()),
        ]
        for name, handler in actions:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)

        self._favorites_action = Gio.SimpleAction.new("my-favorites", None)
        self._favorites_action.connect("activate", self._on_my_favorites)
        self._favorites_action.set_enabled(False)
        self.add_action(self._favorites_action)

        self._uploads_action = Gio.SimpleAction.new("my-uploads", None)
        self._uploads_action.connect("activate", self._on_my_uploads)
        self._uploads_action.set_enabled(False)
        self.add_action(self._uploads_action)

    # -- navigation -------------------------------------------------------

    def _show_view(self, name: str) -> None:
        self._navigation.pop_to_tag("root")
        self._view_stack.set_visible_child_name(name)

    def _focus_search(self) -> None:
        self._show_view("search")
        self._search_view.grab_search_focus()

    def _show_about(self) -> None:
        about = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon=APP_ID,
            version=__version__,
            website=PROJECT_URL,
            issue_url=f"{PROJECT_URL}/issues",
            developer_name="Joe Hallmark",
            copyright="© 2026 Joe Hallmark",
            comments=(
                "Search and download from the Internet Archive, operating "
                "within its usage guidelines."
            ),
        )
        about.present(self)

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
        (collection:…, simplelists__…, uploader:…, fav-…)."""
        self._show_view("search")
        self._search_view.run_query_text(query_text)

    def show_downloads(self) -> None:
        self._show_view("downloads")

    # -- downloads -----------------------------------------------------------

    def open_bulk_dialog(self, query: str, label: str) -> None:
        dialog = BulkDownloadDialog(
            query=query,
            label=label,
            scrape_client=self._scrape_client,
            download_dir=self._config.download_dir,
            on_confirm=self._start_bulk,
        )
        dialog.present(self)

    def _start_bulk(self, query: str, label: str, original_only: bool,
                    total_items: int) -> None:
        self._bulk_manager.start(query, label, original_only, total_items)
        toast = Adw.Toast(title=f"Bulk download started: {label}")
        toast.set_button_label("View")
        toast.connect("button-clicked", lambda *_: self.show_downloads())
        self._toast_overlay.add_toast(toast)

    def enqueue_download(self, details: ItemDetails, entries) -> None:
        created = self._manager.enqueue(
            details.identifier, entries, item_title=details.title
        )
        toast = Adw.Toast(
            title=f"Queued {len(created)} file{'s' if len(created) != 1 else ''}"
        )
        toast.set_button_label("View")
        toast.connect("button-clicked", lambda *_: self.show_downloads())
        self._toast_overlay.add_toast(toast)

    # -- account ------------------------------------------------------------

    def _set_account(self, info) -> None:
        self._account = info
        self._favorites_action.set_enabled(
            info is not None and bool(info.favorites_query)
        )
        self._uploads_action.set_enabled(info is not None)

    def _adopt_session(self, session) -> None:
        """Swap the shared session (after sign-in/out) on every holder."""
        self._session = session
        self._search_client.session = session
        self._item_client.session = session
        self._thumbs.session = session
        self._manager.session = session
        self._scrape_client.session = session

    def sign_in(self, email: str, password: str, on_done) -> None:
        """Async sign-in for the preferences dialog: exchanges the password
        for stored keys, adopts an authenticated session, resolves the
        account. on_done(info, exc) runs on the main loop."""

        def work():
            account.login(email, password)
            session = create_session()  # re-read config, now with keys
            return session, account.fetch_user_info(session)

        def ok(result):
            session, info = result
            self._adopt_session(session)
            self._set_account(info)
            if info is not None:
                self.show_error(f"Signed in as {info.display_name}")
            on_done(info, None)

        run_in_thread(work, ok, lambda exc: on_done(None, exc))

    def sign_out(self) -> None:
        account.logout()
        self._adopt_session(create_session())
        self._set_account(None)

    def _on_my_favorites(self, *_args):
        if self._account is not None and self._account.favorites_query:
            self.browse_query(self._account.favorites_query)

    def _on_my_uploads(self, *_args):
        if self._account is not None:
            self.browse_query(self._account.uploads_query)

    def _on_settings_clicked(self, _button):
        dialog = PreferencesDialog(
            self._config,
            on_concurrency_changed=self._manager.set_max_concurrent,
            account=self._account,
            on_sign_in=self.sign_in,
            on_sign_out=self.sign_out,
        )
        dialog.present(self)

    def _on_close_request(self, _window):
        self._bulk_manager.shutdown()  # stop feeding before the queue stops
        self._manager.shutdown()
        self._thumbs.shutdown()
        return False  # allow the window to close

    def show_error(self, message: str) -> None:
        self._toast_overlay.add_toast(Adw.Toast(title=message))
