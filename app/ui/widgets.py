"""Shared UI helpers for PhoneLink Ubuntu."""

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

try:
    gi.require_version("Adw", "1")
    from gi.repository import Adw
    HAS_ADW = True
except (ValueError, RuntimeError):
    HAS_ADW = False


def show_dialog(parent: Gtk.Window, title: str, body: str, error: bool = False) -> None:
    """
    Show a modal information or error dialog.
    Uses Adw.AlertDialog when available, falls back to a plain Gtk.Window.
    """
    if HAS_ADW:
        try:
            dialog = Adw.AlertDialog(heading=title, body=body)
            dialog.add_response("ok", "OK")
            dialog.set_default_response("ok")
            dialog.connect("response", lambda d, _r: d.close())
            dialog.present(parent)
            return
        except Exception:
            pass  # Fall through to GTK fallback

    # GTK4 fallback (works on any GTK4 version)
    win = Gtk.Window(title=title, transient_for=parent, modal=True)
    win.set_default_size(400, -1)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
    box.set_margin_top(24)
    box.set_margin_bottom(24)
    box.set_margin_start(24)
    box.set_margin_end(24)

    lbl = Gtk.Label(label=body)
    lbl.set_wrap(True)
    lbl.set_selectable(True)
    lbl.set_halign(Gtk.Align.START)
    if error:
        lbl.add_css_class("error")
    box.append(lbl)

    btn = Gtk.Button(label="OK")
    btn.set_halign(Gtk.Align.CENTER)
    btn.connect("clicked", lambda _: win.destroy())
    if error:
        btn.add_css_class("destructive-action")
    box.append(btn)

    win.set_child(box)
    win.present()
