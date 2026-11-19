"""GTK 3 StatusIcon tray implementation copied in principle from LunaSecurity 0.4.37."""
from __future__ import annotations
import threading

class GtkStatusTray:
    """GTK StatusIcon in its own GLib thread; same reliable method as LunaSecurity."""
    def __init__(self, on_show, on_quit, on_error=None, language="de"):
        self.language, self.on_show, self.on_quit, self.on_error = language, on_show, on_quit, on_error
        self.icon = self.menu = self.average_item = self.warning_item = None
        self.Gtk = self.GLib = None
        self.ready = threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self._run, daemon=True, name="LunaWetter-GTK-Tray")
        self.thread.start()
        self.ready.wait(timeout=4)
        if self.error:
            raise RuntimeError(self.error)
        if self.icon is None:
            raise RuntimeError("GTK-System-Tray konnte nicht initialisiert werden")

    def _run(self):
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            from gi.repository import Gtk, GLib
            self.Gtk, self.GLib = Gtk, GLib
            ok, _argv = Gtk.init_check([])
            if not ok:
                raise RuntimeError("Keine GTK-Tray-Sitzung verfügbar")
            icon = Gtk.StatusIcon()
            icon.set_from_icon_name("weather-clear")
            icon.set_tooltip_text("LunaWetter – Wetterübersicht")
            icon.set_visible(True)
            icon.connect("activate", lambda *_: self.on_show())
            menu = Gtk.Menu()
            self.average_item = Gtk.MenuItem(label="Durchschnitt: noch keine Daten")
            self.average_item.set_sensitive(False)
            menu.append(self.average_item)
            self.warning_item = Gtk.MenuItem(label="⚠ Keine Wetterwarnungen")
            self.warning_item.set_sensitive(False)
            menu.append(self.warning_item)
            menu.append(Gtk.SeparatorMenuItem())
            show_item = Gtk.MenuItem(label="LunaWetter anzeigen")
            show_item.connect("activate", lambda *_: self.on_show())
            menu.append(show_item)
            menu.append(Gtk.SeparatorMenuItem())
            quit_item = Gtk.MenuItem(label="LunaWetter beenden")
            quit_item.connect("activate", lambda *_: self.on_quit())
            menu.append(quit_item)
            menu.show_all()
            icon.connect("popup-menu", lambda _icon, button, activate_time:
                menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, activate_time))
            self.icon, self.menu = icon, menu
            self.ready.set()
            Gtk.main()
        except Exception as exc:
            self.error = str(exc)
            self.ready.set()
            if self.on_error:
                self.on_error(self.error)

    def set_status(self, status="normal"):
        if self.GLib and self.icon:
            names = {"normal":"weather-clear", "warning":"weather-showers", "critical":"dialog-error"}
            name = names.get(status, names["normal"])
            def update():
                if self.icon:
                    self.icon.set_from_icon_name(name)
                return False
            self.GLib.idle_add(update)


    def set_average(self, average=None, received=0, total=6, warning_count=0):
        """Update tray tooltip and menu with the mean of available providers."""
        if not (self.GLib and self.icon):
            return
        if average is None:
            label = f"Durchschnitt: keine Temperaturdaten ({received}/{total})"
            tooltip = "LunaWetter – noch keine Temperaturdaten"
        else:
            label = f"Ø {average:.1f} °C · {received}/{total} Anbieter"
            tooltip = f"LunaWetter · Durchschnitt {average:.1f} °C ({received}/{total} Anbieter)"
        if warning_count:
            warning_label = f"⚠ {warning_count} Wetterwarnung(en) – LunaWetter öffnen"
            tooltip += f" · {warning_count} Wetterwarnung(en)"
        else:
            warning_label = "✓ Keine Wetterwarnungen"
        def update():
            if self.icon:
                self.icon.set_tooltip_text(tooltip)
                self.icon.set_from_icon_name("weather-storm" if warning_count else "weather-clear")
            if self.average_item:
                self.average_item.set_label(label)
            if self.warning_item:
                self.warning_item.set_label(warning_label)
                self.warning_item.set_sensitive(bool(warning_count))
                if warning_count:
                    self.warning_item.connect("activate", lambda *_: self.on_show())
            return False
        self.GLib.idle_add(update)

    def stop(self):
        if self.GLib and self.Gtk:
            def quit_tray():
                try:
                    if self.icon:
                        self.icon.set_visible(False)
                finally:
                    self.Gtk.main_quit()
                return False
            self.GLib.idle_add(quit_tray)
        if self.thread and self.thread.is_alive() and threading.current_thread() is not self.thread:
            self.thread.join(timeout=2.0)
