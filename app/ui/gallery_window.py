"""Internal photo gallery for PhoneLink Ubuntu."""

import threading
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib

from app.core import photos as photos_core
from app.ui.widgets import show_dialog
from app.utils.logger import get_logger

logger = get_logger(__name__)

THUMB_SIZE = 160


class GalleryWindow(Gtk.Window):
    """Browse and open photos already imported into the local folder."""

    def __init__(self, parent: Gtk.Window):
        super().__init__(transient_for=parent, modal=False)
        self.set_title("Galerie photos")
        self.set_default_size(640, 560)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(outer)

        header = Gtk.HeaderBar()
        header.set_show_title_buttons(True)
        open_folder_btn = Gtk.Button(icon_name="folder-pictures-symbolic")
        open_folder_btn.set_tooltip_text("Ouvrir le dossier externe")
        open_folder_btn.connect("clicked", self._on_open_folder)
        header.pack_end(open_folder_btn)
        outer.append(header)

        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_vexpand(True)
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        outer.append(self._scroll)

        self._populate()

    def _populate(self) -> None:
        photos = photos_core.list_photos()
        if not photos:
            self._scroll.set_child(self._empty_state())
            return

        flow = Gtk.FlowBox()
        flow.set_valign(Gtk.Align.START)
        flow.set_max_children_per_line(8)
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_activate_on_single_click(True)
        flow.set_homogeneous(True)
        flow.set_row_spacing(12)
        flow.set_column_spacing(12)
        flow.set_margin_top(12)
        flow.set_margin_bottom(12)
        flow.set_margin_start(12)
        flow.set_margin_end(12)
        flow.connect("child-activated", self._on_child_activated)
        self._scroll.set_child(flow)

        pictures: list[tuple[Path, Gtk.Picture]] = []
        for path in photos:
            child, picture = self._build_tile(path)
            flow.append(child)
            pictures.append((path, picture))

        threading.Thread(
            target=self._load_thumbnails, args=(pictures,), daemon=True
        ).start()

    def _empty_state(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_valign(Gtk.Align.CENTER)
        box.set_vexpand(True)
        icon = Gtk.Image.new_from_icon_name("image-x-generic-symbolic")
        icon.set_pixel_size(64)
        icon.add_css_class("dim-label")
        box.append(icon)
        lbl = Gtk.Label(
            label="Aucune photo importée.\nUtilisez « Importer photos » d'abord."
        )
        lbl.set_justify(Gtk.Justification.CENTER)
        lbl.add_css_class("dim-label")
        box.append(lbl)
        return box

    def _build_tile(self, path: Path) -> tuple[Gtk.FlowBoxChild, Gtk.Picture]:
        tile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        tile.set_size_request(THUMB_SIZE, -1)

        picture = Gtk.Picture()
        picture.set_size_request(THUMB_SIZE, THUMB_SIZE)
        picture.set_content_fit(Gtk.ContentFit.COVER)
        picture.set_can_shrink(True)
        # Placeholder until the thumbnail loads.
        picture.set_paintable(None)
        tile.append(picture)

        name = Gtk.Label(label=path.name)
        name.set_ellipsize(3)  # Pango.EllipsizeMode.END
        name.set_max_width_chars(20)
        name.add_css_class("caption")
        tile.append(name)

        child = Gtk.FlowBoxChild()
        child.set_child(tile)
        child._photo_path = path  # used by child-activated handler
        return child, picture

    def _load_thumbnails(self, pictures: list[tuple[Path, Gtk.Picture]]) -> None:
        for path, picture in pictures:
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    str(path), THUMB_SIZE, THUMB_SIZE, True
                )
            except GLib.Error as exc:
                logger.debug("Thumbnail failed for %s: %s", path, exc)
                continue
            texture = Gdk.Texture.new_for_pixbuf(pixbuf)
            GLib.idle_add(picture.set_paintable, texture)

    def _on_child_activated(self, _flow: Gtk.FlowBox, child: Gtk.FlowBoxChild) -> None:
        path = getattr(child, "_photo_path", None)
        if path is None:
            return
        ok, msg = photos_core.open_photo(path)
        if not ok:
            show_dialog(self, "Erreur", msg, error=True)

    def _on_open_folder(self, _btn: Gtk.Button) -> None:
        ok, msg = photos_core.open_local_folder()
        if not ok:
            show_dialog(self, "Erreur", msg, error=True)
