import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio  # noqa: E402

from . import APP_ID  # noqa: E402
from .ui.window import MainWindow  # noqa: E402


class IAHelperApplication(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )

    def do_activate(self):
        window = self.props.active_window or MainWindow(self)
        window.present()


def main(argv=None):
    app = IAHelperApplication()
    return app.run(sys.argv if argv is None else argv)
