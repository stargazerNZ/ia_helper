from gi.repository import Adw

from .. import APP_NAME
from .search_view import SearchView


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(
            application=app,
            title=APP_NAME,
            default_width=920,
            default_height=680,
        )

        self._toast_overlay = Adw.ToastOverlay()
        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())

        self._search_view = SearchView(on_error=self.show_error)
        toolbar_view.set_content(self._search_view)

        self._toast_overlay.set_child(toolbar_view)
        self.set_content(self._toast_overlay)

    def show_error(self, message: str) -> None:
        self._toast_overlay.add_toast(Adw.Toast(title=message))
