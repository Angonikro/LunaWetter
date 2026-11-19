from __future__ import annotations
import sys
import threading
import re
from PySide6.QtCore import QTimer, Qt, QObject, Signal, QSettings
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,
    QLabel,QLineEdit,QPushButton,QFrame,QScrollArea,QMessageBox,QSizePolicy
)
from .providers import fetch_all, PROVIDERS
from . import __version__
from .tray import GtkStatusTray

APP_STYLE = """
QMainWindow,QDialog,QWidget { background:#171923; color:#f2f2f8; font-family:'Noto Sans'; }
QLabel { color:#f2f2f8; background:transparent; }
QLabel#metricCaption { color:#aeb5ca; font-size:9pt; }
QLabel#metricValue { color:#f5f2ff; font-size:11pt; font-weight:750; }
QFrame#metricCard { background:#252c3e; border:1px solid #3f4964; border-radius:8px; }
QFrame#forecastMore { background:#252b3b; border:1px dashed #626b86; border-radius:11px; }
QLabel#emptyForecastTitle { color:#e8d8ff; font-size:15px; font-weight:800; }
QLabel#emptyForecastText { color:#b7bdd0; font-size:10pt; }
QLabel#forecastTemp { color:#ffb0a6; font-size:13px; font-weight:850; }
QLabel#forecastCondition { color:#e8eaf2; font-size:10pt; font-weight:650; }
QLineEdit { background:#242838; border:1px solid #515873; border-radius:8px; padding:8px 11px; color:#fff; }
QPushButton { background:#713bd1; color:#fff; border:1px solid #8b55e6; border-radius:8px; padding:7px 11px; font-weight:700; }
QPushButton:hover { background:#8754e6; }
QPushButton:disabled { background:#484657; color:#aaa; }
QPushButton#provider { background:#222637; border:1px solid #69718d; border-radius:10px; padding:7px 8px; text-align:left; }
QPushButton#provider:hover { border:1px solid #b17aff; }
QPushButton#provider[selected="true"] { background:#392457; border:2px solid #b45cff; }
QPushButton#secondary { background:#282d40; border:1px solid #69718d; }
QFrame#panel { background:#202536; border:1px solid #505a76; border-radius:12px; }
QFrame#warningPanel { background:#38251f; border:1px solid #d34c4c; border-radius:12px; }
QFrame#forecastToday { background:#382454; border:2px solid #b65cff; border-radius:11px; }
QFrame#forecastDay { background:#202536; border:1px solid #69718d; border-radius:11px; }
QLabel#muted { color:#b4b8c8; }
QLabel#sectionTitle { color:#f0e3ff; font-size:16px; font-weight:800; }
QLabel#heroTemp { color:#d7b3ff; font-size:39px; font-weight:850; }
QLabel#warningText { color:#ffe0a3; }
"""

class FetchSignals(QObject):
    done=Signal(object)

def panel(name="panel"):
    f=QFrame(); f.setObjectName(name); return f

def wx_icon(description):
    s=(description or "").casefold()
    if any(x in s for x in ("gewitter","thunder","blitz")): return "⛈️"
    if any(x in s for x in ("schnee","snow","schneeregen","sleet","graupel")): return "🌨️"
    if any(x in s for x in ("regen","schauer","rain","niesel")): return "🌧"
    if any(x in s for x in ("nebel","fog")): return "🌫"
    if any(x in s for x in ("sonn","heiter","sunny","clear")): return "☀"
    if any(x in s for x in ("wolk","cloud","bedeckt","bewölkt")): return "☁️"
    return "🌤"

class LunaWetter(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings=QSettings("Goldisoft","LunaWetter")
        self.setWindowTitle(f"LunaWetter {__version__} – Wettervorhersage")
        self.resize(1600,930); self.setMinimumSize(1050,700)
        self.results={}; self.selected_provider="wetter.com"
        self.fetching=False; self.fetching_place=""; self.fetch_signals=None
        self._closing=False; self.warning_count=0; self.warning_expanded=True
        central=QWidget(); self.setCentralWidget(central)
        outer=QVBoxLayout(central); outer.setContentsMargins(12,8,12,8); outer.setSpacing(8)

        # Header bar matching the approved mockup.
        header=QHBoxLayout(); header.setSpacing(9)
        logo=QLabel("☁️")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setMinimumSize(38,38)
        logo.setContentsMargins(2,3,2,5)
        logo.setStyleSheet("font-size:27px;color:#b78aff;padding:3px;")
        brand=QLabel("LunaWetter"); brand.setFont(QFont("Noto Sans",19,QFont.Weight.Bold))
        header.addWidget(logo); header.addWidget(brand); header.addSpacing(12)
        header.addWidget(QLabel("Ort:"))
        self.place=QLineEdit(self.settings.value("place","")); self.place.setPlaceholderText("Bad Driburg, Deutschland")
        self.place.setMinimumWidth(210); self.place.setMaximumWidth(360); self.place.returnPressed.connect(self.refresh)
        header.addWidget(self.place,1)
        self.search_btn=QPushButton("⌕"); self.search_btn.setFixedWidth(44); self.search_btn.clicked.connect(self.refresh); header.addWidget(self.search_btn)
        header.addSpacing(12)
        header.addWidget(QLabel("Automatische Aktualisierung:"))
        self.auto_state=QLabel("● Aktiv · 15 Min."); self.auto_state.setStyleSheet("color:#8fe5a8;font-weight:800;")
        header.addWidget(self.auto_state)
        self.refresh_btn=QPushButton("↻  Jetzt aktualisieren"); self.refresh_btn.clicked.connect(self.refresh); header.addWidget(self.refresh_btn)
        self.warning_toggle=QPushButton("⚠  0 Warnungen  ▾"); self.warning_toggle.setObjectName("secondary")
        self.warning_toggle.clicked.connect(self.toggle_warnings); self.warning_toggle.hide(); header.addWidget(self.warning_toggle)
        outer.addLayout(header)

        # Six compact horizontal provider selector cards.
        self.provider_row=QHBoxLayout(); self.provider_row.setSpacing(8); self.provider_buttons={}
        for name,country,_desc in PROVIDERS:
            b=QPushButton()
            b.setObjectName("provider"); b.setMinimumHeight(76); b.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
            b.setText(f"🌤  {name}\n—   ·   {country}")
            b.clicked.connect(lambda checked=False,n=name:self.select_provider(n))
            self.provider_row.addWidget(b,1); self.provider_buttons[name]=b
        outer.addLayout(self.provider_row)

        # Heading line with back-to-overview action.
        heading=QHBoxLayout()
        self.back_btn=QPushButton("←  Zurück zur Übersicht"); self.back_btn.setObjectName("secondary")
        self.back_btn.clicked.connect(self.show_overview); heading.addWidget(self.back_btn)
        self.provider_heading=QLabel("wetter.com"); self.provider_heading.setFont(QFont("Noto Sans",19,QFont.Weight.Bold))
        heading.addWidget(self.provider_heading); heading.addStretch()
        outer.addLayout(heading)

        # Main detail area: balanced current-weather hero and clear warning panel.
        upper=QHBoxLayout(); upper.setSpacing(10)
        current=panel(); cv=QVBoxLayout(current); cv.setContentsMargins(14,11,14,11); cv.setSpacing(8)
        section=QLabel("AKTUELLES WETTER"); section.setObjectName("sectionTitle"); cv.addWidget(section)
        hero=QHBoxLayout(); hero.setSpacing(16)
        icon_col=QVBoxLayout(); icon_col.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.current_icon=QLabel("🌤"); self.current_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.current_icon.setStyleSheet("font-family:'Noto Color Emoji','Noto Sans'; font-size:58px; color:#ffd34e;")
        icon_col.addWidget(self.current_icon)
        hero.addLayout(icon_col)
        tempcol=QVBoxLayout(); tempcol.setSpacing(2)
        self.current_temp=QLabel("—"); self.current_temp.setObjectName("heroTemp")
        self.current_desc=QLabel("Wetterdaten werden geladen"); self.current_desc.setFont(QFont("Noto Sans",12,QFont.Weight.Bold))
        self.current_desc.setWordWrap(True)
        tempcol.addWidget(self.current_temp); tempcol.addWidget(self.current_desc)
        hero.addLayout(tempcol,2)
        self.metrics=QGridLayout(); self.metrics.setSpacing(7); self.metric_labels={}
        for idx,(key,label) in enumerate([
            ("feels","Gefühlt"),("rain","Regen"),("wind","Wind"),
            ("gust","Böen"),("humidity","Luftfeuchte"),("pressure","Luftdruck")
        ]):
            metric=panel("metricCard")
            mv=QVBoxLayout(metric); mv.setContentsMargins(9,6,9,6); mv.setSpacing(2)
            cap=QLabel(label); cap.setObjectName("metricCaption")
            val=QLabel("—"); val.setObjectName("metricValue"); val.setWordWrap(True)
            mv.addWidget(cap); mv.addWidget(val)
            self.metrics.addWidget(metric,idx//3,idx%3)
            self.metric_labels[key]=val
        hero.addLayout(self.metrics,5)
        cv.addLayout(hero)
        self.current_detail=QLabel("Weitere Angaben des ausgewählten Wetteranbieters")
        self.current_detail.setObjectName("muted"); self.current_detail.setWordWrap(True); cv.addWidget(self.current_detail)
        self.location_line=QLabel("📍  Standort: —"); self.location_line.setObjectName("muted"); cv.addWidget(self.location_line)
        upper.addWidget(current,7)

        self.warning_panel=panel("warningPanel"); wv=QVBoxLayout(self.warning_panel)
        wv.setContentsMargins(12,10,12,10); wv.setSpacing(8)
        warnhead=QHBoxLayout()
        self.warning_title=QLabel("⚠ Wetterwarnungen"); self.warning_title.setFont(QFont("Noto Sans",14,QFont.Weight.Bold)); self.warning_title.setObjectName("warningText")
        warnhead.addWidget(self.warning_title); warnhead.addStretch()
        self.warning_collapse=QPushButton("⌃"); self.warning_collapse.setObjectName("secondary"); self.warning_collapse.setFixedWidth(34)
        self.warning_collapse.clicked.connect(self.toggle_provider_warning); warnhead.addWidget(self.warning_collapse)
        wv.addLayout(warnhead)
        self.warning_text=QLabel("Für diesen Anbieter liegen keine Warnungen vor.")
        self.warning_text.setWordWrap(True); self.warning_text.setObjectName("warningText")
        self.warning_text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        wv.addWidget(self.warning_text,1)
        upper.addWidget(self.warning_panel,3)
        current.setMinimumHeight(205); current.setMaximumHeight(255)
        self.warning_panel.setMinimumHeight(205); self.warning_panel.setMaximumHeight(255)
        outer.addLayout(upper)

        # Seven-day forecast: actual days fill the width; unavailable days are
        # represented explicitly instead of leaving a large empty area.
        forecast_head=QHBoxLayout()
        self.forecast_caption=QLabel("▦  7-Tage-Vorhersage"); self.forecast_caption.setObjectName("sectionTitle")
        forecast_head.addWidget(self.forecast_caption); forecast_head.addStretch()
        self.forecast_place=QLabel("für den ausgewählten Ort"); self.forecast_place.setObjectName("muted"); forecast_head.addWidget(self.forecast_place)
        outer.addLayout(forecast_head)
        self.forecast_scroll=QScrollArea(); self.forecast_scroll.setWidgetResizable(True); self.forecast_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.forecast_content=QWidget(); self.forecast_row=QHBoxLayout(self.forecast_content)
        self.forecast_row.setContentsMargins(0,0,0,0); self.forecast_row.setSpacing(8)
        self.forecast_scroll.setWidget(self.forecast_content); self.forecast_scroll.setMinimumHeight(235); self.forecast_scroll.setMaximumHeight(300)
        outer.addWidget(self.forecast_scroll,1)
        self.forecast_message=QLabel("Warte auf Vorhersagedaten …"); self.forecast_message.setObjectName("muted")
        self.forecast_message.hide(); outer.addWidget(self.forecast_message)

        # Warnings dropdown is a full-width detail below the provider row only when toggled.
        self.global_warning_panel=panel("warningPanel"); gw=QVBoxLayout(self.global_warning_panel)
        self.global_warning_text=QLabel(""); self.global_warning_text.setWordWrap(True); self.global_warning_text.setObjectName("warningText"); gw.addWidget(self.global_warning_text)
        self.global_warning_panel.hide(); outer.addWidget(self.global_warning_panel)

        footer=QHBoxLayout()
        self.footer_status=QLabel(f"Goldisoft 2026 · LunaWetter {__version__}"); self.footer_status.setObjectName("muted")
        footer.addWidget(self.footer_status); footer.addStretch()
        self.average_label=QLabel("Ø Temperatur (6 Anbieter): —"); self.average_label.setObjectName("muted"); footer.addWidget(self.average_label)
        self.tray_btn=QPushButton("Ins Tray minimieren"); self.tray_btn.clicked.connect(self.hide); footer.addWidget(self.tray_btn)
        outer.addLayout(footer)

        self.tray=None
        self.auto_refresh_timer=QTimer(self); self.auto_refresh_timer.setSingleShot(True); self.auto_refresh_timer.setInterval(1100); self.auto_refresh_timer.timeout.connect(self.refresh)
        self.periodic_refresh_timer=QTimer(self); self.periodic_refresh_timer.setInterval(15*60*1000); self.periodic_refresh_timer.timeout.connect(self.refresh)
        self.place.textChanged.connect(self.schedule_auto_refresh)
        try: self.tray=GtkStatusTray(self.show_from_tray,self.quit_from_tray,language="de")
        except Exception: self.tray=None
        self.restoreGeometry(self.settings.value("geometry",b""))
        self.select_provider(self.selected_provider)
        if self.place.text().strip(): self.auto_refresh_timer.start(500)

    def select_provider(self,name):
        self.selected_provider=name
        self.provider_heading.setText(name)
        for provider,button in self.provider_buttons.items():
            data=self.results.get(provider,{})
            if data and "error" not in data:
                temp=data.get("temperature")
                unit=data.get("temperature_unit","°C")
                temp_text=f"{temp:g} {unit}" if temp is not None else "—"
                desc=data.get("description") or ""
                short_desc = self.short_condition(desc)
                button.setText(f"{wx_icon(desc)}  {provider}\n{temp_text}   {short_desc}")
            else:
                country=next((c for n,c,_ in PROVIDERS if n==provider),"")
                button.setText(f"🌤  {provider}\n—   ·   {country}")
            button.setProperty("selected",provider==name)
            button.style().unpolish(button); button.style().polish(button)
        self.show_provider(name)

    @staticmethod
    def short_condition(description):
        text = re.sub(r"\s+", " ", str(description or "")).strip()
        text = re.split(r"[.!?]", text, maxsplit=1)[0]
        replacements = (
            ("Leichter Regen möglich", "Leichter Regen"),
            ("Stark bewölkt", "Stark bewölkt"),
            ("Stationsmessung in der Nähe", "Stationsmessung"),
            ("Einzelne Regenschauer", "Regenschauer"),
            ("Cloudy", "Bewölkt"),
            ("Rain", "Regen"),
        )
        for source, target in replacements:
            if source.casefold() in text.casefold():
                return target
        return text[:20] + ("…" if len(text) > 20 else "")

    def show_provider(self,name):
        data=self.results.get(name)
        self.forecast_place.setText(f"für {self.place.text().strip() or 'den ausgewählten Ort'}")
        if not data:
            self.current_temp.setText("—"); self.current_desc.setText("Noch keine Daten")
            self.current_icon.setText("🌤"); self.current_detail.setText("Bitte einen Ort eingeben und Wetter abrufen.")
            for val in self.metric_labels.values(): val.setText("—")
            self.location_line.setText("📍  Standort: "+(self.place.text().strip() or "—"))
            self.warning_panel.hide()
            self.forecast_caption.setText("▦  7-Tage-Vorhersage")
            self.render_forecast([])
            return
        if "error" in data:
            self.current_temp.setText("—"); self.current_desc.setText("Anbieter nicht verfügbar")
            self.current_icon.setText("⚠"); self.current_detail.setText(str(data["error"]))
            for val in self.metric_labels.values(): val.setText("—")
            self.warning_panel.hide(); self.forecast_caption.setText("▦  7-Tage-Vorhersage")
            self.render_forecast([])
            return
        t=data.get("temperature"); unit=data.get("temperature_unit","°C")
        self.current_temp.setText(f"{t:g} {unit}" if t is not None else "—")
        desc=data.get("description") or "Keine Beschreibung verfügbar"
        self.current_desc.setText(desc); self.current_icon.setText(wx_icon(desc))
        symbol = wx_icon(desc)
        if symbol == "⛈️":
            self.current_icon.setStyleSheet("font-family:'Noto Color Emoji','Noto Sans'; font-size:58px; color:#ffd34e;")
        elif symbol == "🌨️":
            self.current_icon.setStyleSheet("font-family:'Noto Color Emoji','Noto Sans'; font-size:58px; color:#ccecff;")
        else:
            self.current_icon.setStyleSheet("font-family:'Noto Color Emoji','Noto Sans'; font-size:58px;")
        self.current_detail.setText(data.get("detail") or "Keine weiteren Angaben vom Anbieter")
        detail=(data.get("detail") or "")
        self.metric_labels["feels"].setText(self.find_metric(detail,("Gefühlt","Feels like")))
        self.metric_labels["rain"].setText(f"{data['rain']} %" if data.get("rain") is not None else "—")
        self.metric_labels["wind"].setText(str(data.get("wind") or "—"))
        self.metric_labels["gust"].setText(self.find_metric(detail,("Böen","gust")))
        self.metric_labels["humidity"].setText(self.find_metric(detail,("Luftfeuchte","humidity")))
        self.metric_labels["pressure"].setText(self.find_metric(detail,("Luftdruck","pressure")))
        self.location_line.setText("📍  "+self.place.text().strip()+"  ·  "+name)
        warnings=data.get("warnings") or []
        if warnings:
            self.warning_title.setText(f"⚠ Wetterwarnungen ({len(warnings)})")
            clean_warnings = list(dict.fromkeys(str(w).strip() for w in warnings if str(w).strip()))
            self.warning_text.setText("\n".join("• " + w for w in clean_warnings))
            self.warning_text.show()
            self.warning_collapse.setText("⌃")
            self.warning_panel.show()
        else:
            self.warning_panel.hide()
        forecast_days = data.get("forecast") or []
        fallback_count = int(data.get("forecast_fallback_days") or 0)
        source_note = f" · {fallback_count} Tage Open-Meteo-Zusatzmodell" if fallback_count else ""
        self.forecast_caption.setText(
            f"▦  7-Tage-Vorhersage · {min(len(forecast_days), 7)} von 7 Tagen{source_note}"
        )
        self.render_forecast(forecast_days)

    @staticmethod
    def find_metric(text,labels):
        import re
        for label in labels:
            m=re.search(re.escape(label)+r"\s*:?\s*([^·|]{1,28})",text,re.I)
            if m: return m.group(1).strip()
        return "—"

    def render_forecast(self,forecast):
        while self.forecast_row.count():
            item=self.forecast_row.takeAt(0)
            widget=item.widget()
            if widget: widget.deleteLater()

        days = [d for d in (forecast or [])[:7] if isinstance(d, dict)]
        self.forecast_message.hide()

        if not days:
            info=panel("forecastMore")
            info.setMinimumHeight(210)
            iv=QVBoxLayout(info); iv.setContentsMargins(18,14,18,14); iv.setSpacing(8)
            icon=QLabel("☁"); icon.setAlignment(Qt.AlignmentFlag.AlignCenter); icon.setStyleSheet("font-size:34px;color:#c5a4ff;")
            title=QLabel("Keine 7-Tage-Daten verfügbar"); title.setObjectName("emptyForecastTitle"); title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            message=QLabel("Dieser Anbieter veröffentlicht auf seiner öffentlichen Seite derzeit keine zuverlässig auslesbare Tagesvorhersage. Die aktuellen Wetterdaten bleiben verfügbar.")
            message.setObjectName("emptyForecastText"); message.setWordWrap(True); message.setAlignment(Qt.AlignmentFlag.AlignCenter)
            iv.addStretch(); iv.addWidget(icon); iv.addWidget(title); iv.addWidget(message); iv.addStretch()
            self.forecast_row.addWidget(info,1)
            return

        for idx,day in enumerate(days):
            card=panel("forecastToday" if idx==0 else "forecastDay")
            card.setMinimumWidth(120); card.setMinimumHeight(220)
            card.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
            v=QVBoxLayout(card); v.setContentsMargins(9,9,9,9); v.setSpacing(6)
            d=QLabel(str(day.get("day","Tag"))); d.setAlignment(Qt.AlignmentFlag.AlignCenter)
            d.setFont(QFont("Noto Sans",11,QFont.Weight.Bold)); v.addWidget(d)
            tag=QLabel("Heute" if idx==0 else ("Morgen" if idx==1 else ""))
            tag.setAlignment(Qt.AlignmentFlag.AlignCenter); tag.setObjectName("muted"); v.addWidget(tag)
            ico=QLabel(wx_icon(day.get("condition"))); ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
            # Reserve a little extra line-height for the emoji glyph. Some
            # Qt/font combinations clip the upper/lower edge at the nominal
            # font size, most visibly on the cloud symbol.
            ico.setMinimumHeight(50)
            ico.setContentsMargins(0,4,0,4)
            symbol = wx_icon(day.get("condition"))
            if symbol == "⛈️":
                ico.setStyleSheet("font-family:'Noto Color Emoji','Noto Sans'; font-size:35px; padding:2px 0px; color:#ffd34e;")
            elif symbol == "🌨️":
                ico.setStyleSheet("font-family:'Noto Color Emoji','Noto Sans'; font-size:35px; padding:2px 0px; color:#ccecff;")
            else:
                ico.setStyleSheet("font-size:35px; padding:2px 0px;")
            v.addWidget(ico)
            cond=QLabel(str(day.get("condition") or "Keine Beschreibung"))
            cond.setObjectName("forecastCondition"); cond.setWordWrap(True); cond.setAlignment(Qt.AlignmentFlag.AlignCenter); v.addWidget(cond)
            source_label=QLabel("Open-Meteo · Zusatzmodell" if day.get("forecast_source") == "Open-Meteo-Zusatzmodell" else "Anbieterdaten")
            source_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            source_label.setStyleSheet("color:#d7b3ff;font-size:9px;font-weight:700;" if day.get("forecast_source") == "Open-Meteo-Zusatzmodell" else "color:#9da7bf;font-size:9px;")
            v.addWidget(source_label)
            high=day.get("high"); low=day.get("low")
            high_text=f"{high:g}" if isinstance(high,(int,float)) else "—"
            low_text=f"{low:g}" if isinstance(low,(int,float)) else "—"
            temps=QLabel(f"↑ {high_text} °C    ↓ {low_text} °C")
            temps.setObjectName("forecastTemp"); temps.setAlignment(Qt.AlignmentFlag.AlignCenter); v.addWidget(temps)
            line=QFrame(); line.setFrameShape(QFrame.Shape.HLine); v.addWidget(line)
            for text in (
                f"💧 Regen: {day.get('rain')} %" if day.get("rain") is not None else "💧 Regen: keine Angabe",
                f"Menge: {day.get('amount')} mm" if day.get("amount") is not None else "Menge: keine Angabe",
                f"➤ Wind: {day.get('wind')} km/h" if day.get("wind") is not None else "➤ Wind: keine Angabe",
            ):
                label=QLabel(text); label.setObjectName("muted"); label.setWordWrap(True); v.addWidget(label)
            if day.get("warning"):
                warning=QLabel("⚠ "+str(day["warning"])); warning.setStyleSheet("color:#ffd05c;font-weight:700;")
                warning.setWordWrap(True); v.addWidget(warning)
            v.addStretch()
            self.forecast_row.addWidget(card,1)

        missing = 7 - len(days)
        if missing:
            more=panel("forecastMore"); more.setMinimumWidth(145); more.setMinimumHeight(220)
            more.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
            mv=QVBoxLayout(more); mv.setContentsMargins(12,12,12,12); mv.setSpacing(8)
            ico=QLabel("…"); ico.setAlignment(Qt.AlignmentFlag.AlignCenter); ico.setStyleSheet("font-size:34px;color:#c5a4ff;")
            title=QLabel(f"{missing} weitere Tage"); title.setObjectName("emptyForecastTitle"); title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            text=QLabel("Für diese Tage stellt der Anbieter keine auswertbaren Werte bereit. Es werden keine Temperaturen oder Wetterlagen ergänzt.")
            text.setObjectName("emptyForecastText"); text.setWordWrap(True); text.setAlignment(Qt.AlignmentFlag.AlignCenter)
            mv.addStretch(); mv.addWidget(ico); mv.addWidget(title); mv.addWidget(text); mv.addStretch()
            self.forecast_row.addWidget(more,max(1,missing))

    def show_overview(self):
        # The approved main screen is the detailed weather dashboard. The button
        # returns to a compact all-provider comparison state without leaving the app.
        self.provider_heading.setText("Wettervergleich – Anbieterübersicht")
        self.current_desc.setText("Wähle oben einen Anbieter für dessen Wetterdetailseite.")
        self.current_temp.setText("—"); self.current_icon.setText("🌤")
        self.current_detail.setText("Die Anbieter bleiben jederzeit oben auswählbar.")
        self.warning_panel.hide(); self.render_forecast([])
        self.forecast_message.setText("Bitte oben einen Wetteranbieter auswählen.")
        for val in self.metric_labels.values(): val.setText("—")

    def schedule_auto_refresh(self,_text=""):
        if self.place.text().strip(): self.auto_refresh_timer.start()
        else: self.auto_refresh_timer.stop(); self.periodic_refresh_timer.stop()

    def toggle_provider_warning(self):
        visible = self.warning_text.isVisible()
        self.warning_text.setVisible(not visible)
        self.warning_collapse.setText("⌄" if visible else "⌃")

    def toggle_warnings(self):
        if self.global_warning_panel.isVisible():
            self.global_warning_panel.hide(); self.warning_toggle.setText(f"⚠  {self.warning_count} Warnungen  ▾")
        else:
            self.global_warning_panel.show(); self.warning_toggle.setText(f"⚠  {self.warning_count} Warnungen  ▴")

    def refresh(self):
        place_text=self.place.text().strip()
        if not place_text:
            QMessageBox.information(self,"LunaWetter","Bitte zuerst einen Ort eingeben."); return
        if self.fetching:
            self.fetch_signals_pending=True; return
        self.settings.setValue("place",place_text); self.fetching=True; self.fetching_place=place_text
        self.refresh_btn.setEnabled(False); self.footer_status.setText(f"Wetterdaten für {place_text} werden geladen …")
        self.periodic_refresh_timer.start()
        self.fetch_signals=FetchSignals(self); self.fetch_signals.done.connect(self.show_results)
        self.worker_thread=threading.Thread(target=self._fetch_in_background,args=(place_text,self.fetch_signals),daemon=True)
        self.worker_thread.start()

    @staticmethod
    def _fetch_in_background(place_text,signals):
        try: results=fetch_all(place_text)
        except Exception as exc: results=[(name,{"error":str(exc)}) for name,_,_ in PROVIDERS]
        try: signals.done.emit(results)
        except RuntimeError: pass

    def show_results(self,results):
        if self._closing: return
        self.results={n:d for n,d in results}
        warnings=[]; valid=[]
        for name,data in results:
            if "error" not in data:
                for w in data.get("warnings") or []: warnings.append((name,str(w)))
                t=data.get("temperature")
                if t is not None:
                    try:
                        val=float(t); unit=str(data.get("temperature_unit","°C")).upper().replace(" ","")
                        if unit in ("F","°F"): val=(val-32)*5/9
                        valid.append(val)
                    except (TypeError,ValueError): pass
        self.warning_count=len(warnings)
        if warnings:
            self.warning_toggle.setText(f"⚠  {len(warnings)} Warnungen  ▾"); self.warning_toggle.show()
            self.global_warning_text.setText("\n".join(f"• {name}: {warning}" for name,warning in warnings))
        else:
            self.warning_toggle.hide(); self.global_warning_panel.hide()
        average=sum(valid)/len(valid) if valid else None
        self.average_label.setText(f"Ø Temperatur ({len(valid)}/{len(PROVIDERS)}): {average:.1f} °C" if average is not None else "Ø Temperatur: —")
        if self.tray: self.tray.set_average(average,len(valid),len(PROVIDERS),self.warning_count)
        self.select_provider(self.selected_provider)
        self.refresh_btn.setEnabled(True)
        self.footer_status.setText(f"Letzte Aktualisierung: {self.fetching_place} · Automatisch alle 15 Minuten")
        completed=self.fetching_place; self.fetching=False
        if self.place.text().strip() and self.place.text().strip()!=completed: self.auto_refresh_timer.start(250)

    def show_from_tray(self):
        self.showNormal(); self.raise_(); self.activateWindow()
    def quit_from_tray(self): self.close()
    def closeEvent(self,event):
        self._closing=True; self.settings.setValue("geometry",self.saveGeometry())
        self.auto_refresh_timer.stop(); self.periodic_refresh_timer.stop()
        if self.tray: self.tray.stop()
        event.accept()

def main():
    app=QApplication(sys.argv); app.setApplicationName("LunaWetter"); app.setStyle("Fusion"); app.setStyleSheet(APP_STYLE)
    win=LunaWetter(); win.show(); return app.exec()
