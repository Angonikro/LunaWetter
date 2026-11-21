"""Native Qt system tray for LunaWetter; no GTK dependency."""
from __future__ import annotations
from PySide6.QtCore import QObject
from PySide6.QtGui import QIcon, QAction
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QStyle

class QtStatusTray(QObject):
    """Qt system tray with temperature average and weather-warning status."""
    def __init__(self, on_show, on_quit, on_error=None, language="de"):
        super().__init__()
        self.on_show, self.on_quit, self.language = on_show, on_quit, language
        self.tray = QSystemTrayIcon(self)
        style = QApplication.style()
        self.icons = {
            "normal": QIcon.fromTheme("weather-clear", style.standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)),
            "warning": QIcon.fromTheme("weather-showers", style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)),
            "critical": style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxCritical),
        }
        self.menu = QMenu()
        self.average_action = QAction("Durchschnitt: noch keine Daten", self.menu)
        self.average_action.setEnabled(False); self.menu.addAction(self.average_action)
        self.warning_action = QAction("✓ Keine Wetterwarnungen", self.menu)
        self.warning_action.setEnabled(False); self.menu.addAction(self.warning_action)
        self.menu.addSeparator()
        show_text = "LunaWetter anzeigen" if language == "de" else "Show LunaWetter"
        quit_text = "LunaWetter beenden" if language == "de" else "Quit LunaWetter"
        show_action = QAction(show_text, self.menu); show_action.triggered.connect(self.on_show)
        self.menu.addAction(show_action); self.menu.addSeparator()
        quit_action = QAction(quit_text, self.menu); quit_action.triggered.connect(self.on_quit)
        self.menu.addAction(quit_action)
        self.tray.setContextMenu(self.menu); self.tray.activated.connect(self._activated)
        self.set_status("normal"); self.tray.show()
        if not QSystemTrayIcon.isSystemTrayAvailable() and on_error:
            on_error("Qt meldet momentan kein verfügbares System-Tray.")

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.on_show()

    def set_status(self, status="normal"):
        status = status if status in self.icons else "normal"
        tips = {"normal":"LunaWetter – Keine offenen Wetterwarnungen",
                "warning":"LunaWetter – Wetterwarnung vorhanden",
                "critical":"LunaWetter – Kritische Wetterwarnung"}
        self.tray.setIcon(self.icons[status]); self.tray.setToolTip(tips[status])

    def set_average(self, average=None, received=0, total=6, warning_count=0):
        if average is None:
            label = f"Durchschnitt: keine Temperaturdaten ({received}/{total})"
        else:
            label = f"Ø {average:.1f} °C · {received}/{total} Anbieter"
        self.average_action.setText(label)
        self.warning_action.setText(f"⚠ {warning_count} Wetterwarnung(en) – LunaWetter öffnen"
                                    if warning_count else "✓ Keine Wetterwarnungen")
        self.warning_action.setEnabled(bool(warning_count))
        try: self.warning_action.triggered.disconnect()
        except Exception: pass
        if warning_count: self.warning_action.triggered.connect(self.on_show)
        self.set_status("warning" if warning_count else "normal")
        tooltip = label if average is not None else "LunaWetter – noch keine Temperaturdaten"
        if warning_count: tooltip += f" · {warning_count} Wetterwarnung(en)"
        self.tray.setToolTip(tooltip)

    def isVisible(self): return self.tray.isVisible()
    def showMessage(self, *args, **kwargs): return self.tray.showMessage(*args, **kwargs)
    def hide(self): self.tray.hide()
    def stop(self):
        self.tray.hide()
        self.menu.deleteLater()
