# Core module: all Internet Archive access lives here.
#
# Nothing in this package may import GTK/GLib/PyGObject. This keeps the
# archive.org logic portable (future Windows port, CLI use) and unit-testable
# without a display server.
