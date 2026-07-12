"""Bridge between blocking core/ calls and the GTK main loop."""

import threading

from gi.repository import GLib


def run_in_thread(func, on_success, on_error):
    """Run ``func()`` on a daemon thread; deliver the result to the main loop.

    ``on_success(result)`` or ``on_error(exception)`` is invoked via
    GLib.idle_add, so both are safe to touch widgets from.
    """

    def target():
        try:
            result = func()
        except Exception as exc:  # noqa: BLE001 — boundary: report all failures to UI
            GLib.idle_add(on_error, exc)
        else:
            GLib.idle_add(on_success, result)

    threading.Thread(target=target, daemon=True).start()
