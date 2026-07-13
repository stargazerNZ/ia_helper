import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio  # noqa: E402

from . import APP_ID, APP_NAME, __version__  # noqa: E402
from .ui.window import MainWindow  # noqa: E402


class IAHelperApplication(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", self._on_quit)
        self.add_action(quit_action)

        self.set_accels_for_action("app.quit", ["<primary>q"])
        self.set_accels_for_action("win.preferences", ["<primary>comma"])
        self.set_accels_for_action("win.focus-search", ["<primary>f"])
        self.set_accels_for_action("win.show-search", ["<primary>1"])
        self.set_accels_for_action("win.show-downloads", ["<primary>2"])

    def do_activate(self):
        window = self.props.active_window or MainWindow(self)
        window.present()

    def _on_quit(self, _action, _param):
        # Close the window rather than bare quit() so close-request runs
        # (persists the download queue, stops workers).
        window = self.props.active_window
        if window is not None:
            window.close()
        else:
            self.quit()


def main(argv=None):
    argv = sys.argv if argv is None else argv
    if "--version" in argv:
        print(f"{APP_NAME} {__version__}")
        return 0
    app = IAHelperApplication()
    return app.run(argv)
