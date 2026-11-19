"""API-key-free readers for publicly accessible weather pages and RSS feeds.

No API credentials, private endpoints, account sessions, CAPTCHA workarounds,
or access-control bypasses are used. A provider that blocks automated access is
reported as unavailable instead of being scraped through a workaround.
"""
from __future__ import annotations

import html
import json
import queue
import threading
import time
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

TIMEOUT = 18
UA = "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36 LunaWetter/0.1.24"


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []
    def handle_data(self, data):
        value = " ".join(data.split())
        if value: self.parts.append(value)


def get_text(url: str) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def page_text(source: str) -> str:
    parser = TextExtractor(); parser.feed(source)
    return re.sub(r"\s+", " ", " ".join(parser.parts))


def number(pattern: str, text: str, flags=re.I):
    match = re.search(pattern, text, flags)
    return float(match.group(1).replace(",", ".")) if match else None


def _links(source: str):
    return re.findall(r'''href=["']([^"']+)["']''', source, re.I)


# These are the fixed comparison providers. Meteologix and meteoCORE remain
# listed, but only public pages are read; no paid/private API is called.
PROVIDERS = [
    ("Foreca", "Finnland", "Öffentliche Wetterseite"),
    ("MET Norway", "Norwegen", "Offizielle weltweite Locationforecast-API, bis zu 9 Tage"),
    ("DWD ICON", "Deutschland", "DWD-ICON-Wettermodell, 7 Tage"),
    ("Wetterblick", "Deutschland", "Eigene Modellprognose, DWD- und private Stationsmessungen"),
    ("Wetterkompass", "Deutschland", "DWD-Modellvorhersage – öffentliche Ortsseite"),
    ("weather.com", "USA", "The Weather Channel – öffentliche Ortswetterseite"),
]


def _norm(value: str) -> str:
    value = value.casefold().replace("ä", "a").replace("ö", "o").replace("ü", "u").replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", "", value)


def _foreca_location_url(place: str) -> str:
    q = urllib.parse.quote(place)
    candidates = [f"https://www.foreca.de/search?query={q}", f"https://www.foreca.com/search?query={q}"]
    wanted = _norm(place)
    for search_url in candidates:
        try: source = get_text(search_url)
        except Exception: continue
        found = []
        for href in _links(source):
            href = html.unescape(href)
            if re.search(r"/weather/[^\"'?#]+-\d{6,}(?:[/?#]|$)", href, re.I):
                full = urllib.parse.urljoin(search_url, href)
                slug = _norm(urllib.parse.unquote(full.rsplit("/", 1)[-1]))
                if wanted in slug:
                    found.append(full)
        if found:
            return min(found, key=len)

    # Foreca's public German city URL uses the GeoNames identifier prefixed by
    # 10. This is an ordinary public forecast page, not an API endpoint.
    if wanted == "baddriburg":
        return "https://www.foreca.de/weather/Germany/North-Rhine-Westphalia/Bad-Driburg-102953525"
    raise RuntimeError("Foreca: Keine passende öffentliche Ortsseite gefunden.")




def extract_week_forecast(visible_text: str) -> list[dict]:
    """Extract only clearly labelled daily forecast entries from public page text."""
    text = re.sub(r"\s+", " ", visible_text or "")
    if not text:
        return []
    day_pattern = r"(?:Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mo|Di|Mi|Do|Fr|Sa|So|Mon|Tue|Wed|Thu|Fri|Sat|Sun)"
    matches = list(re.finditer(rf"\b{day_pattern}\b", text, re.I))
    results = []
    seen = set()
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index+1].start() if index+1 < len(matches) else min(len(text), match.end()+260)
        section = text[match.end():min(end, match.end()+260)]
        # Require a high/low pair, not arbitrary temperatures from nearby page chrome.
        pair = re.search(
            r"(?:max(?:imal)?\.?\s*)?(-?\d{1,2})\s*°\s*C?\s*(?:/|bis|,)\s*"
            r"(?:min(?:imal)?\.?\s*)?(-?\d{1,2})\s*°\s*C?",
            section, re.I
        )
        if not pair:
            pair = re.search(
                r"(?:max(?:imal)?|high)\s+(-?\d{1,2})\s*°\s*C?.{0,120}?(?:min(?:imal)?|low)\s+(-?\d{1,2})\s*°\s*C?",
                section, re.I
            )
        if not pair:
            continue
        high, low = map(int, pair.groups())
        if high < low:
            high, low = low, high
        day_label = match.group(0)
        key = (day_label.casefold(), high, low)
        if key in seen:
            continue
        seen.add(key)
        condition_match = re.search(
            r"\b(sonnig|heiter|wolkig|bewölkt|bedeckt|regen|regenschauer|schauer|"
            r"gewitter|schnee|schneeregen|nebel|trocken|cloudy|rain|snow|sunny)\w*\b",
            section, re.I
        )
        rain_match = re.search(r"(\d{1,3})\s*%\s*(?:Regen|Niederschlag|precipitation)?", section, re.I)
        wind_match = re.search(r"(\d{1,3})\s*km/h", section, re.I)
        results.append({
            "day": day_label,
            "high": high,
            "low": low,
            "condition": condition_match.group(0) if condition_match else "Keine Beschreibung verfügbar",
            "rain": int(rain_match.group(1)) if rain_match else None,
            "wind": int(wind_match.group(1)) if wind_match else None,
        })
        if len(results) >= 7:
            break
    return results


def extract_page_warnings(source: str, visible_text: str) -> list[str]:
    """Return concise warnings only when the page explicitly announces an alert."""
    text = re.sub(r"\s+", " ", visible_text or "")
    text_low = text.casefold()
    alert_terms = (
        "unwetterwarnung", "wetterwarnung", "warnung vor", "warnstufe",
        "amtliche warnung", "sturmwarnung", "gewitterwarnung", "hitzewarnung",
        "hochwasserwarnung", "schneewarnung", "frostwarnung", "nebelwarnung",
        "weather warning", "severe weather alert",
        "weather advisory", "weather alert", "official warning",
    )
    hazard_map = [
        ("Gewitter", ("gewitter", "thunderstorm", "lightning")),
        ("Sturm/Orkan", ("orkan", "hurrikan", "hurricane", "orkanböen", "sturm", "storm", "windböen", "sturmböen")),
        ("Starkregen", ("starkregen", "dauerregen", "heavy rain", "flash flood", "sturzflut")),
        ("Hochwasser/Überschwemmung", ("hochwasser", "überschwemm", "flood")),
        ("Schnee/Schneefall", ("schneefall", "schneeverweh", "snowfall", "blizzard")),
        ("Glätte/Eis", ("glätte", "eisregen", "black ice", "freezing rain")),
        ("Frost", ("frost", "strenger frost", "frostgefahr")),
        ("Hitze", ("hitzewarnung", "hitzebelastung", "extreme heat", "heat alert")),
        ("Nebel", ("nebelwarnung", "dichter nebel", "dense fog")),
        ("Waldbrandgefahr", ("waldbrandgefahr", "forest fire")),
    ]
    severity_map = [
        ("Warnstufe 4 – Violett", ("warnstufe 4", "stufe 4", "violett", "extreme danger")),
        ("Warnstufe 3 – Rot", ("warnstufe 3", "stufe 3", "rot", "severe danger")),
        ("Warnstufe 2 – Orange", ("warnstufe 2", "stufe 2", "orange", "moderate danger")),
        ("Warnstufe 1 – Gelb", ("warnstufe 1", "stufe 1", "gelb", "minor danger")),
    ]

    found = []
    search_from = 0
    while True:
        positions = [(text_low.find(term, search_from), term) for term in alert_terms]
        positions = [(pos, term) for pos, term in positions if pos >= 0]
        if not positions:
            break
        pos, alert_term = min(positions)
        search_from = pos + len(alert_term)
        left, right = max(0, pos - 110), min(len(text), pos + 260)
        context = text[left:right]
        context_low = context.casefold()

        # A warning label without an identified hazard is just a page heading,
        # not a useful warning message. Do not display it.
        hazards = [label for label, words in hazard_map if any(word in context_low for word in words)]
        if not hazards:
            continue

        severity = next((label for label, words in severity_map if any(word in context_low for word in words)), None)
        region = None
        region_match = re.search(r"\b(?:für|in)\s+([A-ZÄÖÜ][\wÄÖÜäöüß .-]{2,55}?)(?=\s+(?:Stand|gültig|bis|ab|von|Warnstufe|Stufe)\b|[,.|]|$)", context)
        if region_match:
            candidate = region_match.group(1).strip()
            if not re.search(r"^(?:vor|Warnung|Wetterwarnung|Unwetterwarnung)$", candidate, re.I):
                region = candidate
        validity = None
        valid_match = re.search(r"\b(?:gültig\s+)?(?:bis|until)\s+(\d{1,2}[.:]\d{2}(?:\s*Uhr)?|\d{1,2}\.\d{1,2}\.\d{4}(?:\s+\d{1,2}[.:]\d{2})?)", context, re.I)
        if valid_match:
            validity = "bis " + valid_match.group(1).strip()
        elif re.search(r"\b(?:jetzt|aktuell|currently|now)\b", context, re.I):
            validity = "aktuell gemeldet"

        for hazard in hazards:
            parts = [f"Warnung vor {hazard}"]
            if severity:
                parts.append(severity)
            if region:
                parts.append(f"Region: {region}")
            if validity:
                parts.append(validity)
            message = " · ".join(parts)
            if message not in found:
                found.append(message)
    return found[:5]


def fetch_foreca(place: str) -> dict:
    url = _foreca_location_url(place)
    source = get_text(url)
    text = page_text(source)
    # Foreca may place navigation/cookie text before the current observation.
    # Search the complete visible text first, then the raw HTML (some builds
    # keep the observation in embedded markup rather than visible text nodes).
    top = text[:12000]
    temp = number(r"(?:^|\s)([+\-]?\d{1,2}(?:[.,]\d)?)\s*°", top)
    if temp is None:
        raw = html.unescape(source).replace("\\u00b0", "°").replace("&deg;", "°")
        raw = raw[:120000]
        temp = number(r"(?<![\d])([+\-]?\d{1,2}(?:[.,]\d)?)\s*°", raw)
    feels = number(r"Gefühlt\s*([+\-]?\d{1,2}(?:[.,]\d)?)\s*°", top)
    wind = number(r"\b(\d{1,3}(?:[.,]\d)?)\s*km/h", top)
    rain = number(r"\b(\d{1,3})\s*%", top)
    desc = ""
    for phrase in ("Bedeckt", "Regenschauer", "Regen", "Wolkig", "Heiter", "Sonnig", "Schnee", "Gewitter"):
        if phrase.lower() in top.lower(): desc = phrase; break
    if temp is None:
        raise RuntimeError("Foreca: Seite erreichbar, aktuelle Temperatur im Seiteninhalt nicht erkannt.")
    return {"provider":"Foreca", "temperature":temp, "description":desc or "Wetterdaten von Foreca",
            "minimum":None, "rain":rain, "wind":f"{wind:g} km/h" if wind is not None else None,
            "detail":f"Gefühlt {feels:g} °C" if feels is not None else "", "warnings": extract_page_warnings(source, text),
            "forecast": extract_week_forecast(text),
            "source_url":url}


def lookup_bbc_geonames_id(place: str) -> str:
    query = urllib.parse.urlencode({"q": place, "maxRows": 20, "country": "DE", "featureClass": "PPL", "style": "SHORT"})
    source = get_text("https://www.geonames.org/search.html?" + query)
    wanted = _norm(place)
    # GeoNames lists both the municipality (ADM4) and the populated place.
    # BBC needs the populated-place ID; this avoids selecting the ADM4 ID.
    known_populated_places = {"baddriburg": "2953525"}
    if wanted in known_populated_places:
        return known_populated_places[wanted]
    matches = []
    for href, _ident, label in re.findall(r'''href=[\"'](/([0-9]{5,})/[^\"']+\.html)[\"'][^>]*>(.*?)</a>''', source, re.I | re.S):
        label_text = page_text(label)
        if _norm(label_text) == wanted:
            matches.append(href)
    if not matches:
        # GeoNames can return a slightly decorated place name; only accept a
        # close textual match, never the first unrelated search result.
        for href, _ident, label in re.findall(r'''href=[\"'](/([0-9]{5,})/[^\"']+\.html)[\"'][^>]*>(.*?)</a>''', source, re.I | re.S):
            label_norm = _norm(page_text(label))
            if wanted and (wanted in label_norm or label_norm in wanted):
                matches.append(href)
    if not matches:
        raise RuntimeError("BBC Weather: GeoNames hat keinen exakt passenden Ort geliefert.")
    return re.search(r"/([0-9]{5,})/", matches[0]).group(1)


def fetch_bbc(place: str) -> dict:
    geonames_id = lookup_bbc_geonames_id(place)
    url = f"https://weather-broker-cdn.api.bbci.co.uk/en/forecast/rss/3day/{geonames_id}"
    try:
        feed_source = get_text(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError(
                f"BBC Weather: Für {place} ist kein öffentlicher BBC-RSS-Ortsfeed vorhanden (HTTP 404)."
            ) from exc
        raise
    root = ET.fromstring(feed_source)
    items = root.findall(".//item")
    if not items:
        raise RuntimeError("BBC Weather: Der öffentliche RSS-Feed enthält keine Vorhersage.")
    item = items[0]
    title = item.findtext("title", "BBC Weather")
    desc = html.unescape(item.findtext("description", ""))
    high = number(r"(?:Maximum Temperature|High):?\s*([+\-]?\d+(?:[.,]\d+)?)\s*°?C", desc)
    low = number(r"(?:Minimum Temperature|Low):?\s*([+\-]?\d+(?:[.,]\d+)?)\s*°?C", desc)
    return {"provider":"BBC Weather", "temperature":high, "minimum":low, "description":title,
            "rain":None, "wind":None, "detail":re.sub(r"\s+", " ", desc)[:220], "source_url":url}


def _wettercom_location_url(place: str) -> str:
    q = urllib.parse.quote(place)
    candidates = [f"https://www.wetter.com/suche/?q={q}", f"https://www.wetter.com/suche/{q}/"]
    for search_url in candidates:
        try: source = get_text(search_url)
        except Exception: continue
        found = []
        for href in _links(source):
            href = html.unescape(href)
            if (re.search(r"/wetter_aktuell/wettervorhersage/[^\"'?#]+\.html", href, re.I)
                    or re.search(r"/deutschland/[^\"'?#]+/DE[0-9]+\.html", href, re.I)):
                found.append(urllib.parse.urljoin("https://www.wetter.com", href))
        if found:
            wanted = re.sub(r"[^a-z0-9]+", "", place.lower())
            found.sort(key=lambda u: (wanted not in re.sub(r"[^a-z0-9]+", "", urllib.parse.unquote(u).lower()), len(u)))
            return found[0]
    raise RuntimeError("wetter.com: Keine passende öffentliche Ortsseite gefunden.")


def fetch_wettercom(place: str) -> dict:
    url = _wettercom_location_url(place)
    source = get_text(url)
    text = page_text(source)
    # wetter.com currently labels the live observation explicitly.
    current = re.search(r"Aktuelles Wetter in\s+.*?(\d{1,2})\s*°C\s+([^.!?]{2,70})", text, re.I)
    if not current:
        current = re.search(r"(?:^|\s)(\d{1,2})\s*°C\s+(Regen|Regnerisch|Wolkig|Bedeckt|Stark bewölkt|Leicht bewölkt|Sonnig|Schnee)\b", text[:2500], re.I)
    if current:
        temp = float(current.group(1)); desc = current.group(2).strip()
    else:
        # The same observation is repeated in the current-weather section.
        match = re.search(r"\b(\d{1,2})\s*°C\s+(Stark bewölkt|Überwiegend bewölkt|Leicht bewölkt|Wolkig|Bedeckt|Sonnig|Klar|Regen|Schnee)", text, re.I)
        temp = float(match.group(1)) if match else None
        desc = match.group(2).strip() if match else ""
    if temp is None:
        raise RuntimeError("wetter.com: Seite erreichbar, aktuelle Temperatur nicht erkannt.")
    # The current-observation panel often contains only temperature and a
    # short condition label. Read the first upcoming hourly forecast block
    # separately so the detail row contains useful, explicitly forecast data
    # instead of a generic placeholder. Keep forecast values labelled as such.
    hourly = ""
    marker = re.search(r"Stündliche Vorhersage", text, re.I)
    if marker:
        hourly = text[marker.end():marker.end()+5000]
    hourly_match = re.search(
        r"(\d{1,2})\s*-\s*(\d{1,2})\s*Uhr\s+.{0,220}?"
        r"(-?\d{1,2})\s*°\s+(\d{1,3})\s*%\s*"
        r"([\d.,]+)\s*l/m²\s+([NSEOW]{1,2})\s+"
        r"(\d{1,3})\s*km/h(?:\s+Böen\s*(\d{1,3})\s*km/h)?",
        hourly, re.I | re.S
    ) if hourly else None
    detail_parts = []
    rain = None
    wind = None
    if hourly_match:
        start_hour, end_hour, _hour_temp, probability, amount, direction, speed, gust = hourly_match.groups()
        rain = float(probability)
        wind = f"{speed} km/h {direction.upper()}"
        detail_parts.append(
            f"Nächste Stunde ({start_hour}–{end_hour} Uhr): Regen {probability} % · "
            f"{amount.replace(',', '.')} mm · Wind {wind}"
        )
        if gust:
            detail_parts.append(f"Böen {gust} km/h")
    if not detail_parts:
        # Fallback: extract any safely identifiable values from the current
        # page, but never show the old generic text as if it were a measurement.
        rain = number(r"\b(\d{1,3})\s*%", text[:6000])
        wind_speed = number(r"\b(\d{1,3}(?:[.,]\d)?)\s*km/h", text[:6000])
        if wind_speed is not None:
            wind = f"{wind_speed:g} km/h"
        if rain is not None:
            detail_parts.append(f"Niederschlagswahrscheinlichkeit {rain:g} %")
        if wind:
            detail_parts.append(f"Wind {wind}")
    detail = " · ".join(detail_parts) if detail_parts else "Keine zusätzlichen Wetterwerte auf der öffentlichen Seite erkannt"
    return {"provider":"wetter.com", "temperature":temp, "description":desc or "Wetterdaten von wetter.com",
            "minimum":None, "rain":rain, "wind":wind,
            "detail":detail, "warnings": extract_page_warnings(source, text),
            "forecast": extract_week_forecast(text),
            "source_url":url}


def _accuweather_location_url(place: str) -> str:
    q = urllib.parse.quote(place)
    search_url = f"https://www.accuweather.com/de/de/search-locations?query={q}"
    source = get_text(search_url)
    found = []
    for href in _links(source):
        href = html.unescape(href)
        if re.search(r"/de/de/.+/(?:10-day-weather-forecast|current-weather)/\d+", href, re.I):
            found.append(urllib.parse.urljoin("https://www.accuweather.com", href))
    if not found:
        raise RuntimeError("AccuWeather: Öffentliche Ortssuche lieferte keine Wetterseite.")
    return found[0]


def fetch_accuweather(place: str) -> dict:
    url = _accuweather_location_url(place)
    text = page_text(get_text(url))
    temp = number(r"(?:RealFeel[^\d]{0,20})?([+\-]?\d{1,2})\s*°", text[:2500])
    if temp is None:
        temp = number(r"\b([+\-]?\d{1,2})\s*°\s*(?:C|F)", text[:2500])
    if temp is None:
        raise RuntimeError("AccuWeather: Wetterseite erreichbar, Temperatur nicht erkannt.")
    unit_match = re.search(r"°\s*([FC])\b", text[:3000], re.I)
    if not unit_match:
        raise RuntimeError("AccuWeather: Die öffentliche Seite nennt im auslesbaren Inhalt keine eindeutige Temperatureinheit.")
    unit = "°" + unit_match.group(1).upper()
    forecast = extract_week_forecast(text)
    return {"provider":"AccuWeather", "temperature":temp, "temperature_unit":unit,
            "description":"Öffentliche AccuWeather-Vorhersage", "minimum":None,
            "rain":number(r"\\b(\\d{1,3})\\s*%", text[:4000]), "wind":None,
            "detail":"Temperatur direkt von der öffentlichen Wetterseite",
            "forecast":forecast, "warnings":extract_page_warnings("", text),
            "source_url":url}




def fetch_weather_forecast(place: str) -> dict:
    """Read the public 12-day forecast and nearby live-station reports."""
    slug = "-".join(part.capitalize() for part in _city_slug(place).split("-"))
    url = f"https://de.weather-forecast.com/locations/{slug}/forecasts/latest"
    source = get_text(url)
    text = page_text(source)
    if not re.search(rf"\b{re.escape(place)}\b", text[:5000], re.I):
        raise RuntimeError("Weather-Forecast.com: Die geladene Seite gehört nicht zum gesuchten Ort.")

    # The opening summary describes the next three days and explicitly labels
    # maximum/minimum temperatures; it is a forecast, not a current reading.
    summary_start = re.search(r"Heutiges Wetter in\s+" + re.escape(place), text, re.I)
    summary = text[summary_start.end():summary_start.end()+900] if summary_start else text[:1800]
    summary_temp = re.search(
        r"maximal\s+(-?\d{1,2}(?:[.,]\d+)?)\s*°C.*?min\s+(-?\d{1,2}(?:[.,]\d+)?)\s*°C",
        summary, re.I
    )
    rain_match = re.search(r"gesamt\s+([\d.,]+)\s*mm", summary, re.I)
    condition_match = re.search(
        r"([A-Za-zÄÖÜäöüß -]{4,90}?(?:Regen|Schauer|Schneefall|Schnee|trocken|bewölkt|Wolken)[A-Za-zÄÖÜäöüß ,()-]{0,70})",
        summary, re.I
    )
    description = condition_match.group(1).strip(" .") if condition_match else "Öffentliche Ortsvorhersage"

    # Prefer the nearest live station when the public page includes one.
    station_temp = None
    station_wind = None
    live_marker = re.search(r"Live Wetterstationen nahe\s+" + re.escape(place), text, re.I)
    if live_marker:
        live = text[live_marker.end():live_marker.end()+2200]
        station_match = re.search(
            r"Vor\s+\d+\s+(?:minuten?|stunden?)\s+(-?\d{1,2}(?:[.,]\d+)?)\s*°\s*C"
            r".{0,100}?(\d{1,3})\s*km/h",
            live, re.I
        )
        if station_match:
            station_temp = float(station_match.group(1).replace(",", "."))
            station_wind = f"{station_match.group(2)} km/h"

    if station_temp is not None:
        temperature = station_temp
        detail_parts = ["Messwert der nächstgelegenen verfügbaren Wetterstation"]
        if station_wind:
            detail_parts.append(f"Wind {station_wind}")
        if summary_temp:
            detail_parts.append(
                f"3-Tage-Prognose {summary_temp.group(2).replace(',', '.')}–"
                f"{summary_temp.group(1).replace(',', '.')} °C"
            )
        if rain_match:
            detail_parts.append(f"Regenmenge im Prognoseblock {rain_match.group(1).replace(',', '.')} mm")
        detail = " · ".join(detail_parts)
        wind = station_wind
        description = "Stationsmessung in der Nähe"
        minimum = None
    elif summary_temp:
        # A forecast value is still useful if the page has no live station,
        # but it is deliberately labelled so it cannot be mistaken for now.
        temperature = float(summary_temp.group(1).replace(",", "."))
        minimum = float(summary_temp.group(2).replace(",", "."))
        wind = None
        detail = "3-Tage-Vorhersage (Tiefst-/Höchstwert); keine aktuelle Stationsmessung"
        if rain_match:
            detail += f" · Regenmenge {rain_match.group(1).replace(',', '.')} mm"
        description = "Vorhersage: " + description
    else:
        raise RuntimeError("Weather-Forecast.com: Weder Stationsmessung noch auswertbarer Vorhersageblock gefunden.")

    return {
        "provider": "Weather-Forecast.com",
        "temperature": temperature,
        "description": description,
        "minimum": minimum,
        "rain": float(rain_match.group(1).replace(",", ".")) if rain_match else None,
        "wind": wind,
        "detail": detail,
        "warnings": extract_page_warnings(source, text),
            "forecast": extract_week_forecast(text),
            "source_url": url,
    }


def fetch_meteologix(place: str) -> dict:
    """Read the calculated temperature shown on Meteologix's public city page.

    The page labels this as a calculated value and gives its calculation time.
    It is deliberately not described as a station observation. Only the
    ordinary public HTML page is read; no subscription data or API is used.
    """
    geonames_id = lookup_bbc_geonames_id(place)
    slug = _city_slug(place)
    # Meteologix serves country-specific public portal paths. Try the German
    # portal first, then the known public regional portal path as fallback.
    candidates = [
        f"https://meteologix.com/de/weather/{geonames_id}-{slug}",
        f"https://meteologix.com/bw/weather/{geonames_id}-{slug}",
    ]
    last_error = None
    for url in candidates:
        try:
            source = get_text(url)
        except Exception as exc:
            last_error = exc
            continue
        text = page_text(source)
        # Verify the returned page is really for the requested town before
        # accepting any temperature from it.
        if _norm(place) not in _norm(text[:5000]):
            last_error = RuntimeError("Meteologix: Die öffentliche Seite gehört nicht zum gesuchten Ort.")
            continue
        current = re.search(
            r"(-?\d{1,2}(?:[.,]\d)?)\s*°\s*(?:calculated\s+for|berechnet\s+für)\s*"
            r"(\d{1,2}:\d{2})\s*(am|pm)?\s*(?:Uhr)?",
            text, re.I
        )
        if not current:
            raw = html.unescape(source).replace("\\u00b0", "°").replace("&deg;", "°")
            current = re.search(
                r"(-?\d{1,2}(?:[.,]\d)?)\s*°\s*(?:calculated\s+for|berechnet\s+für)\s*"
                r"(\d{1,2}:\d{2})\s*(am|pm)?\s*(?:Uhr)?",
                raw, re.I
            )
        if not current:
            last_error = RuntimeError("Meteologix: Öffentliche Ortsseite erreichbar, berechnete Temperatur mit Zeitangabe nicht erkannt.")
            continue
        temp, clock, ampm = current.groups()
        hour, minute = map(int, clock.split(':'))
        if ampm:
            if ampm.casefold() == 'pm' and hour != 12: hour += 12
            if ampm.casefold() == 'am' and hour == 12: hour = 0
        calculated_time = f"{hour:02d}:{minute:02d}"
        return {
            "provider": "Meteologix",
            "temperature": float(temp.replace(",", ".")),
            "temperature_unit": "°C",
            "description": "Öffentliche Modellberechnung",
            "minimum": None,
            "rain": None,
            "wind": None,
            "detail": f"Berechnet für {calculated_time} Uhr · Modellwert, keine Stationsmessung",
            "forecast": extract_week_forecast(text),
            "warnings": extract_page_warnings(source, text),
            "source_url": url,
        }
    raise RuntimeError(f"Meteologix: Öffentliche Ortsseite nicht auslesbar ({last_error}).")


def fetch_meteocore(place: str) -> dict:
    # The provider's public site describes its platform/API; no public city
    # forecast page is exposed for anonymous page reading.
    raise RuntimeError("meteoCORE: Keine öffentliche Orts-Wetterseite verfügbar; eine API-Anbindung wird nicht verwendet.")



def fetch_kachelmannwetter(place: str) -> dict:
    """Read the publicly visible temperature from Kachelmannwetter's city page.

    This is ordinary public HTML, not an API or a private data endpoint. The
    value is explicitly labelled as calculated by the website; it is not
    presented as a station observation.
    """
    geonames_id = lookup_bbc_geonames_id(place)
    slug = place.casefold().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    url = f"https://kachelmannwetter.com/de/wetter/{geonames_id}-{slug}"
    source = get_text(url)
    text = page_text(source)

    # The public page prints the calculated value directly beside its
    # timestamp. Matching this pair avoids unrelated temperatures elsewhere
    # in navigation or model descriptions.
    current = re.search(
        r"(-?\d{1,2}(?:[.,]\d)?)\s*°\s*berechnet\s+für\s+(\d{1,2}:\d{2})\s*Uhr",
        text, re.I
    )
    if current:
        temp = float(current.group(1).replace(",", "."))
        calculated_time = current.group(2)
    else:
        # Some page variants encode the degree sign in embedded HTML.
        raw = html.unescape(source).replace("\\u00b0", "°").replace("&deg;", "°")
        current = re.search(
            r"(-?\d{1,2}(?:[.,]\d)?)\s*°\s*berechnet\s+für\s+(\d{1,2}:\d{2})\s*Uhr",
            raw, re.I
        )
        if not current:
            raise RuntimeError("Kachelmannwetter: Seite erreichbar, berechnete Temperatur mit Zeitangabe nicht erkannt.")
        temp = float(current.group(1).replace(",", "."))
        calculated_time = current.group(2)

    detail = f"Temperatur aus der öffentlichen Wetterübersicht · berechnet für {calculated_time} Uhr"
    return {
        "provider": "Kachelmannwetter",
        "temperature": temp,
        "description": "Öffentliche Wetterübersicht",
        "minimum": None,
        "rain": None,
        "wind": None,
        "detail": detail,
        "source_url": url,
    }



def _wetterdienst_location_urls(place: str) -> list[str]:
    """Build the public city-page variants used by Wetterdienst.de."""
    slug = place.strip().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    slug = re.sub(r"[^A-Za-z0-9]+", "_", slug).strip("_")
    if not slug:
        raise RuntimeError("Wetterdienst.de: Ungültiger Ortsname.")
    return [
        f"https://www.wetterdienst.de/Deutschlandwetter/{slug}_{slug}/",
        f"https://www.wetterdienst.de/Deutschlandwetter/{slug}/",
    ]


def fetch_wetterdienst(place: str) -> dict:
    """Read the first published daily forecast from the public HTML page."""
    last_error = None
    source = None
    url = None
    for candidate in _wetterdienst_location_urls(place):
        try:
            source = get_text(candidate)
            url = candidate
            break
        except Exception as exc:
            last_error = exc
    if source is None:
        raise RuntimeError(f"Wetterdienst.de: Öffentliche Ortsseite nicht erreichbar ({last_error}).")

    text = page_text(source)
    start = re.search(r"Vorhersage\s+für\s+[^.]{0,80}", text, re.I)
    if not start:
        raise RuntimeError("Wetterdienst.de: Keine öffentliche Tagesvorhersage auf der Ortsseite gefunden.")
    section = text[start.start():start.start()+2600]

    # The first day part after the date is the next available forecast block.
    condition = re.search(
        r"\b(Regenschauer|kräftiger Regen|leichter Regen|Regen|Schnee|Schneeregen|"
        r"Nebel oder Dunst|Nebel|bewölkt|teils wolkig|leicht bewölkt|heiter|sonnig|"
        r"wechselhaft|Gewitter)\b",
        section, re.I
    )
    temp_range = re.search(r"(-?\d{1,2})\s*°\s*/\s*(-?\d{1,2})\s*°", section)
    if not temp_range:
        raise RuntimeError("Wetterdienst.de: Temperaturbereich der ersten Tagesvorhersage nicht erkannt.")

    low = float(temp_range.group(1))
    high = float(temp_range.group(2))
    desc = condition.group(1) if condition else "Tagesvorhersage"
    rain_match = re.search(r"Niederschlag:\s*(?:>\s*)?(\d{1,3})\s*%", section, re.I)
    wind_match = re.search(r"\b(\d{1,3}(?:[.,]\d)?)\s*km/h\s*([NSEOW]{1,2})?", section, re.I)
    rain = float(rain_match.group(1)) if rain_match else None
    wind = f"{wind_match.group(1)} km/h" if wind_match else None

    return {
        "provider": "Wetterdienst.de",
        "temperature": high,
        "description": desc,
        "minimum": low,
        "rain": rain,
        "wind": wind,
        "detail": "Tagesvorhersage (Tiefst-/Höchstwert); keine aktuelle Stationsmessung",
        "source_url": url,
    }



def _city_slug(place: str) -> str:
    value = place.strip().casefold()
    value = value.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


def fetch_wetterblick(place: str) -> dict:
    """Read the public city forecast page (no API or private endpoint)."""
    slug = _city_slug(place)
    url = f"https://www.wetterblick.com/vorhersage/{slug}"
    source = get_text(url)
    text = page_text(source)
    updated = re.search(r"Vorhersage aktualisiert:\s*(\d{2}\.\d{2}\.\d{4},\s*\d{2}:\d{2}\s*Uhr)", text, re.I)
    if not re.search(rf"Wetter in\s+{re.escape(place)}\b", text, re.I):
        raise RuntimeError("Wetterblick: Die geladene Seite gehört nicht zum gesuchten Ort.")
    block_start = updated.end() if updated else 0
    section = text[block_start:block_start+1800]
    match = re.search(
        r"(-?\d{1,2}(?:[.,]\d)?)°\s+Gefühlt\s+(-?\d{1,2}(?:[.,]\d)?)°C"
        r".*?(-?\d{1,2})°\s*/\s*(-?\d{1,2})°"
        r".*?(\d{1,3})%\s*([\d.,]+)\s*mm"
        r".*?bis\s*(\d{1,3})\s*km/h",
        section, re.I | re.S
    )
    if not match:
        raise RuntimeError("Wetterblick: Öffentliche Ortsseite erreichbar, Wetterwerte im Seiteninhalt nicht erkannt.")
    temp, feels, low, high, rain, amount, gust = match.groups()
    description = "Öffentliche Ortsvorhersage"
    labels = re.findall(r"(?:alt|title)=[\"']([^\"']{3,70})[\"']", source, re.I)
    for label in labels:
        if re.search(r"Regen|bewölkt|Wolken|sonnig|Schnee|Gewitter|Nebel", label, re.I):
            description = html.unescape(label)
            break
    detail = f"Gefühlt {feels} °C · Tagesbereich {low}–{high} °C · {amount} mm erwartet · Böen bis {gust} km/h"
    if updated:
        detail += f" · aktualisiert {updated.group(1).strip()}"
    return {
        "provider": "Wetterblick", "temperature": float(temp.replace(",", ".")),
        "description": description, "minimum": float(low), "rain": float(rain),
        "wind": f"Böen bis {gust} km/h", "detail": detail, "warnings": extract_page_warnings(source, text),
            "forecast": extract_week_forecast(text),
            "source_url": url,
    }


def fetch_wetternet(place: str) -> dict:
    """Read the current observation block from wetter.net's public HTML page."""
    slug = _city_slug(place).replace("-", "_")
    url = f"https://www.wetter.net/wetter/deutschland/{slug}"
    source = get_text(url)
    text = page_text(source)

    # Current page structure: "Wetter <town> (Deutschland)" followed by the
    # time label, temperature, condition and feels-like temperature. Avoid
    # matching the many later hourly forecast temperatures on the same page.
    city_heading = re.search(
        rf"Wetter\s+{re.escape(place)}\s*\(Deutschland\)", text, re.I
    )
    if not city_heading:
        # Some page versions omit the country suffix from the visible heading.
        city_heading = re.search(rf"Wetter\s+{re.escape(place)}\b", text, re.I)
    if not city_heading:
        raise RuntimeError("wetter.net: Keine passende öffentliche Ortsseite gefunden.")
    section = text[city_heading.end():city_heading.end()+4200]

    match = re.search(
        r"(-?\d{1,2}(?:[.,]\d)?)\s*°C\s+([^,]{2,70}),\s*gefühlt\s+(-?\d{1,2}(?:[.,]\d)?)\s*°C",
        section, re.I
    )
    if not match:
        # Fallback for pages where the introductory heading is repeated before
        # the current card. Search only the first visible weather panel area.
        panel = re.search(r"Wetter\s+vorlesen", section, re.I)
        if panel:
            match = re.search(
                r"(-?\d{1,2}(?:[.,]\d)?)\s*°C\s+([^,]{2,70}),\s*gefühlt\s+(-?\d{1,2}(?:[.,]\d)?)\s*°C",
                section[panel.end():panel.end()+1800], re.I
            )
    if not match:
        raise RuntimeError("wetter.net: Aktuelle Temperatur im öffentlichen Wetterblock nicht erkannt.")

    temp, condition, feels = match.groups()
    humidity = re.search(r"Luftfeuchtigkeit\s+(\d{1,3})\s*%", section, re.I)
    pressure = re.search(r"Luftdruck\s*\(NN\)\s+(\d{3,4})\s*hPa", section, re.I)
    precipitation = re.search(r"Niederschlag\s+([\d.,]+)\s*L/m²", section, re.I)
    wind = re.search(r"Wind\s+([NSEOW]{1,3})\s+Richtung\s+(\d{1,3})\s*km/h", section, re.I)
    gust = re.search(r"Windböen\s+(\d{1,3})\s*km/h", section, re.I)

    extras = [f"Gefühlt {feels} °C"]
    if humidity: extras.append(f"Luftfeuchtigkeit {humidity.group(1)} %")
    if pressure: extras.append(f"Luftdruck {pressure.group(1)} hPa")
    if precipitation: extras.append(f"Niederschlag {precipitation.group(1)} L/m²")
    if gust: extras.append(f"Böen {gust.group(1)} km/h")
    wind_value = f"{wind.group(2)} km/h {wind.group(1).upper()}" if wind else None
    return {
        "provider": "wetter.net",
        "temperature": float(temp.replace(",", ".")),
        "description": condition.strip(),
        "minimum": None,
        "rain": None,
        "wind": wind_value,
        "detail": " · ".join(extras) + " · Öffentliche Q.met-Ortsseite",
        "source_url": url,
    }


def fetch_wetter_germany(place: str) -> dict:
    """Read the DWD station observation published in Wetter-Germany's HTML page."""
    slug = _city_slug(place)
    url = f"https://wetter-germany.de/de/orte/{slug}.html"
    source = get_text(url)
    text = page_text(source)
    marker = text.find(f"Aktuelle Messung des Deutschen Wetterdienstes bei {place}")
    if marker < 0:
        raise RuntimeError("Wetter-Germany: Keine DWD-Messwerttabelle für diesen Ort gefunden.")
    section = text[marker:marker+1800]
    station = re.search(
        r"Letzte Messung:\s*gemessen an\s+(.+?)\s+\((\d+)\s*km entfernt\),\s*(.+?)\.",
        text[:marker+200], re.I
    )
    measured_at = re.search(r"Messzeit\s+(.+?)\s+Temperatur", section, re.I)
    temp = re.search(r"Temperatur\s+(-?\d{1,2}(?:[.,]\d)?)\s*°C", section, re.I)
    wind = re.search(r"Wind\s+(\d{1,3}(?:[.,]\d)?)\s*km/h\s*([NSEOW]{1,2})", section, re.I)
    gust = re.search(r"Böen\s+(\d{1,3}(?:[.,]\d)?)\s*km/h", section, re.I)
    humidity = re.search(r"Luftfeuchtigkeit\s+(\d{1,3})\s*%", section, re.I)
    rain = re.search(r"Niederschlag, letzte Stunde\s+([\d.,]+)\s*mm", section, re.I)
    if not temp:
        raise RuntimeError("Wetter-Germany: DWD-Temperatur im öffentlichen Seiteninhalt nicht erkannt.")
    detail_parts = ["DWD-Stationsmessung, keine Vorhersage"]
    if station: detail_parts.append(f"Station {station.group(1).strip()} ({station.group(2)} km entfernt)")
    if measured_at: detail_parts.append(f"Messzeit {measured_at.group(1).strip()}")
    if humidity: detail_parts.append(f"Luftfeuchte {humidity.group(1)} %")
    if gust: detail_parts.append(f"Böen {gust.group(1)} km/h")
    if rain: detail_parts.append(f"Niederschlag letzte Stunde {rain.group(1)} mm")
    return {
        "provider": "Wetter-Germany", "temperature": float(temp.group(1).replace(",", ".")),
        "description": "DWD-Stationsmessung", "minimum": None,
        "rain": None,
        "wind": f"{wind.group(1)} km/h {wind.group(2)}" if wind else None,
        "detail": " · ".join(detail_parts), "source_url": url,
    }



# Unused provider candidates are intentionally not part of the active build.

def fetch_wetterkontor(place: str) -> dict:
    slug = _city_slug(place)
    url = f"https://www.wetterkontor.de/wetter-vorhersage/deutschland/{slug}"
    text = page_text(get_text(url))
    if not re.search(rf"Wetter\s+{re.escape(place)}\b", text, re.I):
        raise RuntimeError("WetterKontor: Keine passende öffentliche Ortsseite gefunden.")
    start = re.search(r"Detaillierte Vorhersage für die nächsten 3 Tage", text, re.I)
    section = text[start.end():start.end()+2400] if start else text[:5000]
    match = re.search(
        r"Heute\s+Nachmittag\s+([A-Za-zÄÖÜäöüß /-]{2,50}?)\s+(-?\d{1,2})\s*°C\s*"
        r"\((-?\d{1,2})\s*°C\)\s*(\d{1,3})\s*%\s*([\d.,]+)\s*mm"
        r".*?(\d{1,3})\s*km/h.*?Böen\s*(\d{1,3})\s*km/h",
        section, re.I | re.S
    )
    if not match:
        raise RuntimeError("WetterKontor: Tagesprognose im öffentlichen Seiteninhalt nicht erkannt.")
    condition, high, feels, probability, amount, wind, gust = match.groups()
    return {
        "provider": "WetterKontor", "temperature": float(high),
        "description": condition.strip(), "minimum": float(feels),
        "rain": float(probability), "wind": f"{wind} km/h, Böen {gust} km/h",
        "detail": f"Nachmittagsprognose · Niederschlagsmenge {amount.replace(',', '.')} mm · keine aktuelle Stationsmessung",
        "source_url": url,
    }


def fetch_wetterkompass(place: str) -> dict:
    """Read the public Wetterkompass city page (DWD model data, no API).

    Wetterkompass explicitly attributes its local forecast to current DWD
    model data. The value is therefore labelled as a model forecast, not a
    station observation. Only the public HTML page is fetched.
    """
    slug = place.strip().casefold()
    slug = slug.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    url = f"https://www.wetterkompass.com/wetter/{slug}/"
    source = get_text(url)
    text = page_text(source)
    if not re.search(rf"Wetter\s+in\s+{re.escape(place)}\b", text, re.I):
        raise RuntimeError("Wetterkompass: Die geladene Seite gehört nicht zum gesuchten Ort.")

    # Current block: temperature + condition + validity timestamp.
    current = re.search(
        r"(-?\d{1,2}(?:[.,]\d)?)\s*°C\s+(.{2,60}?)\s+Gültig:\s*"
        r"(\d{2}\.\d{2}\.\d{4})\s*[·|,]\s*(\d{1,2}:\d{2})\s*Uhr",
        text, re.I
    )
    if not current:
        raise RuntimeError("Wetterkompass: Aktueller DWD-Modellwert im öffentlichen Seiteninhalt nicht erkannt.")
    temp, condition, valid_date, valid_time = current.groups()

    # Restrict secondary values to the summary panel after the validity stamp.
    section = text[current.end():current.end()+700]
    minimum = re.search(r"Min\s+(-?\d{1,2}(?:[.,]\d)?)\s*°C", section, re.I)
    maximum = re.search(r"Max\s+(-?\d{1,2}(?:[.,]\d)?)\s*°C", section, re.I)
    rain = re.search(r"Niederschlag\s+([\d.,]+)\s*mm", section, re.I)
    wind = re.search(r"Wind\s+([A-ZÄÖÜ]{1,4})\s+(\d{1,3}(?:[.,]\d+)?)\s*km/h", section, re.I)
    pressure = re.search(r"Luftdruck\s+([\d.,]+)\s*hPa", section, re.I)
    details = [f"DWD-Modellwert gültig {valid_date} {valid_time} Uhr", "keine Stationsmessung"]
    if minimum and maximum:
        details.append(f"Tagesbereich {minimum.group(1)}–{maximum.group(1)} °C")
    if pressure:
        details.append(f"Luftdruck {pressure.group(1)} hPa")
    return {
        "provider": "Wetterkompass",
        "temperature": float(temp.replace(",", ".")),
        "temperature_unit": "°C",
        "description": condition.strip(),
        "minimum": float(minimum.group(1).replace(",", ".")) if minimum else None,
        "rain": float(rain.group(1).replace(",", ".")) if rain else None,
        "wind": f"{wind.group(1)} {wind.group(2)} km/h" if wind else None,
        "detail": " · ".join(details),
        "warnings": extract_page_warnings(source, text),
            "forecast": extract_week_forecast(text),
            "source_url": url,
    }


def fetch_weather_com(place: str) -> dict:
    # Public city page identifier for Bad Driburg; for other towns use the
    # provider's public city search and accept only an exact place-name match.
    if _norm(place) == "baddriburg":
        url = "https://weather.com/de-DE/wetter/heute/l/6354f980ad84b9d338dc047575a6581f68c84002d40cb91cb0a128843a917089"
    else:
        q = urllib.parse.quote(place)
        search_url = f"https://weather.com/de-DE/suche/{q}"
        source = get_text(search_url)
        candidates = []
        for href in _links(source):
            href = html.unescape(href)
            if re.search(r"/de-DE/wetter/heute/l/", href, re.I):
                full = urllib.parse.urljoin("https://weather.com", href)
                if _norm(place) in _norm(urllib.parse.unquote(full)):
                    candidates.append(full)
        if not candidates:
            raise RuntimeError("weather.com: Keine passende öffentliche Ortsseite gefunden.")
        url = candidates[0]
    source = get_text(url)
    text = page_text(source)
    if not re.search(rf"{re.escape(place)}", text, re.I):
        raise RuntimeError("weather.com: Die geladene Seite gehört nicht zum gesuchten Ort.")
    current = re.search(
        r"Stand\s+\d{1,2}:\d{2}\s+(?:CET|CEST)\s+(-?\d{1,2})\s*°\s+(.{2,70}?)\s+Tagsüber",
        text, re.I
    )
    if not current:
        raise RuntimeError("weather.com: Aktuelle Temperatur im öffentlichen Seiteninhalt nicht erkannt.")
    temp, condition = current.groups()
    feels = number(r"Gefühlte\s+(-?\d{1,2})\s*°", text)
    wind = number(r"Wind\s+(\d{1,3}(?:[.,]\d+)?)\s*km/h", text)
    humidity = number(r"Luftfeuchte\s+(\d{1,3})\s*%", text)
    pressure = number(r"Luftdruck\s+(\d{3,4}(?:[.,]\d+)?)\s*mb", text)
    extras = []
    if feels is not None: extras.append(f"Gefühlt {feels:g} °C")
    if humidity is not None: extras.append(f"Luftfeuchte {humidity:g} %")
    if pressure is not None: extras.append(f"Luftdruck {pressure:g} mb")
    return {
        "provider": "weather.com", "temperature": float(temp),
        "description": condition.strip(), "minimum": None, "rain": None,
        "wind": f"{wind:g} km/h" if wind is not None else None,
        "detail": " · ".join(extras) or "Aktuelle Beobachtung der öffentlichen Wetterseite",
        "warnings": extract_page_warnings(source, text),
            "forecast": extract_week_forecast(text),
            "source_url": url,
    }



def _open_meteo_json(url: str) -> dict:
    """Fetch a public Open-Meteo JSON response without credentials."""
    request = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
    })
    with urllib.request.urlopen(request, timeout=12) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Open-Meteo lieferte kein gültiges JSON-Objekt.")
    return payload


def _open_meteo_geocode(place: str) -> dict:
    """Resolve the entered town using Open-Meteo's public geocoding service."""
    params = urllib.parse.urlencode({
        "name": place,
        "count": 10,
        "language": "de",
        "format": "json",
    })
    payload = _open_meteo_json("https://geocoding-api.open-meteo.com/v1/search?" + params)
    candidates = payload.get("results") or []
    if not candidates:
        raise RuntimeError(f"Open-Meteo: Ort '{place}' wurde nicht gefunden.")
    wanted = _norm(place)
    candidates.sort(key=lambda item: (
        0 if _norm(str(item.get("name", ""))) == wanted else 1,
        0 if str(item.get("country_code", "")).upper() == "DE" else 1,
        0 if item.get("feature_code") == "PPL" else 1,
    ))
    chosen = candidates[0]
    if chosen.get("latitude") is None or chosen.get("longitude") is None:
        raise RuntimeError("Open-Meteo: Für den gefundenen Ort fehlen Koordinaten.")
    return chosen


def _wmo_description(code: int | None) -> str:
    descriptions = {
        0: "Klar", 1: "Überwiegend klar", 2: "Teilweise bewölkt", 3: "Bedeckt",
        45: "Nebel", 48: "Gefrierender Nebel",
        51: "Leichter Nieselregen", 53: "Nieselregen", 55: "Starker Nieselregen",
        56: "Gefrierender Nieselregen", 57: "Starker gefrierender Nieselregen",
        61: "Leichter Regen", 63: "Regen", 65: "Starker Regen",
        66: "Gefrierender Regen", 67: "Starker gefrierender Regen",
        71: "Leichter Schneefall", 73: "Schneefall", 75: "Starker Schneefall",
        77: "Schneegriesel", 80: "Leichte Regenschauer", 81: "Regenschauer",
        82: "Starke Regenschauer", 85: "Schneeschauer", 86: "Starke Schneeschauer",
        95: "Gewitter", 96: "Gewitter mit leichtem Hagel", 99: "Gewitter mit starkem Hagel",
    }
    try:
        return descriptions.get(int(code), "Wetterlage nicht näher beschrieben")
    except (TypeError, ValueError):
        return "Wetterlage nicht näher beschrieben"


def fetch_open_meteo_week(place: str) -> tuple[list[dict], str]:
    """Return seven daily values from Open-Meteo, explicitly as a fallback model.

    Open-Meteo is not presented as one of the six comparison providers. These
    values are only used to complete days missing from a provider's own page.
    """
    location = _open_meteo_geocode(place)
    params = urllib.parse.urlencode({
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "daily": ",".join((
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_probability_max",
            "precipitation_sum",
            "wind_speed_10m_max",
        )),
        "forecast_days": 7,
        "timezone": "auto",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
        "temperature_unit": "celsius",
    })
    payload = _open_meteo_json("https://api.open-meteo.com/v1/forecast?" + params)
    daily = payload.get("daily") or {}
    dates = daily.get("time") or []
    if not dates:
        raise RuntimeError("Open-Meteo: Die 7-Tage-Vorhersage enthält keine Tagesdaten.")
    keys = (
        "weather_code", "temperature_2m_max", "temperature_2m_min",
        "precipitation_probability_max", "precipitation_sum", "wind_speed_10m_max",
    )
    days = []
    weekday_names = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
    from datetime import date
    for index, iso_date in enumerate(dates[:7]):
        def value(key):
            values = daily.get(key) or []
            return values[index] if index < len(values) else None
        try:
            parsed_date = date.fromisoformat(iso_date)
            day_name = weekday_names[parsed_date.weekday()]
        except (TypeError, ValueError):
            day_name = f"Tag {index + 1}"
        code = value("weather_code")
        days.append({
            "day": day_name,
            "date": iso_date,
            "high": round(float(value("temperature_2m_max")), 1) if value("temperature_2m_max") is not None else None,
            "low": round(float(value("temperature_2m_min")), 1) if value("temperature_2m_min") is not None else None,
            "condition": _wmo_description(code),
            "rain": value("precipitation_probability_max"),
            "amount": round(float(value("precipitation_sum")), 1) if value("precipitation_sum") is not None else None,
            "wind": round(float(value("wind_speed_10m_max")), 1) if value("wind_speed_10m_max") is not None else None,
            "forecast_source": "Open-Meteo-Zusatzmodell",
        })
    return days, str(location.get("name") or place)


def complete_provider_forecasts(place: str, results: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    """Complete short provider forecasts with clearly attributed model days."""
    try:
        model_days, resolved_name = fetch_open_meteo_week(place)
    except Exception as exc:
        # Keep the original provider data untouched if the independent fallback
        # source is temporarily unavailable.
        for _name, data in results:
            if isinstance(data, dict) and "error" not in data:
                data.setdefault("forecast_note", f"Zusatzmodell derzeit nicht erreichbar: {exc}")
        return results

    completed = []
    for name, original in results:
        if not isinstance(original, dict) or "error" in original:
            completed.append((name, original))
            continue
        provider_days = [dict(day) for day in (original.get("forecast") or [])[:7] if isinstance(day, dict)]
        # Provider days are kept first and never overwritten. Only the
        # remaining positions are filled with separately labelled model data.
        missing = max(0, 7 - len(provider_days))
        combined = provider_days + [dict(day) for day in model_days[len(provider_days):len(provider_days) + missing]]
        original["forecast"] = combined[:7]
        original["forecast_provider_days"] = len(provider_days)
        original["forecast_fallback_days"] = min(missing, len(model_days[len(provider_days):]))
        original["forecast_fallback_name"] = "Open-Meteo"
        original["forecast_location"] = resolved_name
        if original["forecast_fallback_days"]:
            original["forecast_note"] = (
                f"{original['forecast_provider_days']} Tage direkt vom Anbieter · "
                f"{original['forecast_fallback_days']} fehlende Tage als separates Open-Meteo-Zusatzmodell"
            )
        completed.append((name, original))
    return completed


# MET Norway Locationforecast cache. For locations outside the Nordic area the
# provider asks clients not to repeat identical requests more often than every
# three hours. The application refreshes more frequently, so cache by rounded
# coordinates and honour that interval.
_METNO_CACHE = {}
_METNO_CACHE_LOCK = threading.Lock()
_METNO_CACHE_SECONDS = 3 * 60 * 60


def _metno_weather_text(symbol: str | None) -> str:
    if not symbol:
        return "Wetterlage nicht näher beschrieben"
    key = symbol.split("_")[0].casefold()
    labels = {
        "clearsky": "Klar", "fair": "Heiter", "partlycloudy": "Teilweise bewölkt",
        "cloudy": "Bewölkt", "fog": "Nebel", "lightrain": "Leichter Regen",
        "rain": "Regen", "heavyrain": "Starker Regen",
        "lightrainshowers": "Leichte Regenschauer", "rainshowers": "Regenschauer",
        "heavyrainshowers": "Starke Regenschauer", "lightsleet": "Leichter Schneeregen",
        "sleet": "Schneeregen", "heavysleet": "Starker Schneeregen",
        "lightsnow": "Leichter Schneefall", "snow": "Schneefall",
        "heavysnow": "Starker Schneefall", "lightsnowshowers": "Leichte Schneeschauer",
        "snowshowers": "Schneeschauer", "heavysnowshowers": "Starke Schneeschauer",
        "thunderstorm": "Gewitter", "lightrainandthunder": "Leichter Regen mit Gewitter",
        "rainandthunder": "Regen mit Gewitter", "heavyrainandthunder": "Starker Regen mit Gewitter",
    }
    return labels.get(key, key.replace("and", " und ").replace("showers", "Schauer").capitalize())


def fetch_met_norway(place: str) -> dict:
    """Fetch MET Norway's official global Locationforecast 2.0 data."""
    location = _open_meteo_geocode(place)
    lat = round(float(location["latitude"]), 4)
    lon = round(float(location["longitude"]), 4)
    cache_key = (lat, lon)
    now_epoch = time.time()
    with _METNO_CACHE_LOCK:
        cached = _METNO_CACHE.get(cache_key)
        if cached and now_epoch - cached[0] < _METNO_CACHE_SECONDS:
            payload = cached[1]
        else:
            query = urllib.parse.urlencode({"lat": f"{lat:.4f}", "lon": f"{lon:.4f}"})
            url = "https://api.met.no/weatherapi/locationforecast/2.0/compact?" + query
            request = urllib.request.Request(url, headers={
                "User-Agent": "LunaWetter/0.1.24 (+https://github.com/Angonikro/LunaWetter)",
                "Accept": "application/json",
            })
            with urllib.request.urlopen(request, timeout=18) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict) or not payload.get("properties", {}).get("timeseries"):
                raise RuntimeError("MET Norway: Die Locationforecast-API lieferte keine Zeitreihen.")
            _METNO_CACHE[cache_key] = (now_epoch, payload)

    timezone_name = location.get("timezone") or "Europe/Berlin"
    try:
        local_tz = ZoneInfo(timezone_name)
    except Exception:
        local_tz = datetime.now().astimezone().tzinfo or timezone.utc

    series = payload["properties"]["timeseries"]
    daily = {}
    parsed = []
    for entry in series:
        try:
            stamp = datetime.fromisoformat(entry["time"].replace("Z", "+00:00"))
            local_stamp = stamp.astimezone(local_tz)
        except (KeyError, TypeError, ValueError):
            continue
        data = entry.get("data", {})
        instant = data.get("instant", {}).get("details", {})
        temp = instant.get("air_temperature")
        if temp is None:
            continue
        next1 = data.get("next_1_hours") or {}
        next6 = data.get("next_6_hours") or {}
        next12 = data.get("next_12_hours") or {}
        summary = next1.get("summary") or next6.get("summary") or next12.get("summary") or {}
        details = next1.get("details") or next6.get("details") or next12.get("details") or {}
        symbol = summary.get("symbol_code")
        row = {
            "time": local_stamp, "temp": float(temp),
            "wind": instant.get("wind_speed"),
            "humidity": instant.get("relative_humidity"),
            "pressure": instant.get("air_pressure_at_sea_level"),
            "symbol": symbol,
            "rain_probability": details.get("probability_of_precipitation"),
            "rain_amount": details.get("precipitation_amount"),
        }
        parsed.append(row)
        key = local_stamp.date().isoformat()
        day = daily.setdefault(key, {"temps": [], "winds": [], "rain": [], "amount": [], "symbols": []})
        day["temps"].append(float(temp))
        if row["wind"] is not None: day["winds"].append(float(row["wind"]))
        if row["rain_probability"] is not None: day["rain"].append(float(row["rain_probability"]))
        if row["rain_amount"] is not None: day["amount"].append(float(row["rain_amount"]))
        if symbol: day["symbols"].append(symbol)

    if not parsed:
        raise RuntimeError("MET Norway: Keine verwertbaren Temperaturwerte in der Vorhersage.")
    current = min(parsed, key=lambda item: abs((item["time"] - datetime.now(local_tz)).total_seconds()))
    forecast = []
    weekday = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
    for date_key, values in list(sorted(daily.items()))[:7]:
        day_date = datetime.fromisoformat(date_key).date()
        # Use the most common daytime symbol rather than an arbitrary first symbol.
        symbols = values["symbols"]
        symbol = max(set(symbols), key=symbols.count) if symbols else None
        forecast.append({
            "day": weekday[day_date.weekday()], "date": date_key,
            "high": round(max(values["temps"]), 1), "low": round(min(values["temps"]), 1),
            "condition": _metno_weather_text(symbol),
            "rain": round(max(values["rain"])) if values["rain"] else None,
            "amount": round(sum(values["amount"]), 1) if values["amount"] else None,
            "wind": round(max(values["winds"]), 1) if values["winds"] else None,
        })
    detail_parts = []
    if current.get("humidity") is not None: detail_parts.append(f"Luftfeuchte {current['humidity']:.0f} %")
    if current.get("pressure") is not None: detail_parts.append(f"Luftdruck {current['pressure']:.0f} hPa")
    return {
        "provider": "MET Norway", "temperature": current["temp"], "temperature_unit": "°C",
        "description": _metno_weather_text(current.get("symbol")),
        "minimum": None, "rain": current.get("rain_probability"),
        "wind": f"{current['wind']:.1f} m/s" if current.get("wind") is not None else None,
        "detail": " · ".join(detail_parts) or "Offizielle MET Norway Locationforecast 2.0",
        "forecast": forecast, "source_url": "https://api.met.no/weatherapi/locationforecast/2.0/",
    }


def fetch_dwd_icon(place: str) -> dict:
    """Fetch the dedicated DWD ICON forecast endpoint (7-day global ICON model)."""
    location = _open_meteo_geocode(place)
    params = urllib.parse.urlencode({
        "latitude": location["latitude"], "longitude": location["longitude"],
        "daily": ",".join((
            "weather_code", "temperature_2m_max", "temperature_2m_min",
            "precipitation_sum", "wind_speed_10m_max",
        )),
        "hourly": ",".join(("temperature_2m", "weather_code", "precipitation_probability", "wind_speed_10m")),
        "forecast_days": 7, "timezone": "auto", "wind_speed_unit": "kmh",
        "precipitation_unit": "mm", "temperature_unit": "celsius",
    })
    url = "https://api.open-meteo.com/v1/dwd-icon?" + params
    request = urllib.request.Request(url, headers={
        "User-Agent": "LunaWetter/0.1.24 (+https://github.com/Angonikro/LunaWetter)",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(request, timeout=18) as response:
        payload = json.loads(response.read().decode("utf-8"))
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        raise RuntimeError("DWD ICON: Die Schnittstelle lieferte keine Stundenwerte.")
    now_local = datetime.now().strftime("%Y-%m-%dT%H:00")
    index = min(range(len(times)), key=lambda i: abs(
        (datetime.fromisoformat(times[i]) - datetime.fromisoformat(now_local)).total_seconds()
    ))
    def at(key):
        values = hourly.get(key) or []
        return values[index] if index < len(values) else None
    daily = payload.get("daily") or {}
    dates = daily.get("time") or []
    forecast = []
    weekday = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
    for i, date_text in enumerate(dates[:7]):
        def dval(key):
            values = daily.get(key) or []
            return values[i] if i < len(values) else None
        day_date = datetime.fromisoformat(date_text).date()
        code = dval("weather_code")
        forecast.append({
            "day": weekday[day_date.weekday()], "date": date_text,
            "high": dval("temperature_2m_max"), "low": dval("temperature_2m_min"),
            "condition": _wmo_description(code),
            "rain": None, "amount": dval("precipitation_sum"),
            "wind": dval("wind_speed_10m_max"),
        })
    code = at("weather_code")
    description = _wmo_description(code)
    wind = at("wind_speed_10m")
    return {
        "provider": "DWD ICON", "temperature": at("temperature_2m"),
        "temperature_unit": "°C", "description": description,
        "minimum": None, "rain": at("precipitation_probability"),
        "wind": f"{wind:g} km/h" if wind is not None else None,
        "detail": "DWD ICON Global · 7-Tage-Modellvorhersage über die öffentliche DWD-ICON-Schnittstelle",
        "forecast": forecast, "source_url": "https://open-meteo.com/en/docs/dwd-api",
    }


def fetch_all(place: str):
    """Fetch the six confirmed providers concurrently using daemon threads.

    The daemon workers keep network I/O from delaying application shutdown.
    Every provider retains the normal 18-second per-request timeout so a slow
    source such as Foreca is not made unreliable by an aggressive timeout.
    """
    providers = [
        ("Foreca", fetch_foreca),
        ("MET Norway", fetch_met_norway),
        ("DWD ICON", fetch_dwd_icon),
        ("Wetterblick", fetch_wetterblick),
        ("Wetterkompass", fetch_wetterkompass),
        ("weather.com", fetch_weather_com),
    ]
    completed = queue.Queue()

    def run_provider(name, func):
        try:
            data = func(place)
        except Exception as exc:
            data = {"error": str(exc)}
        completed.put((name, data))

    workers = []
    for name, func in providers:
        worker = threading.Thread(
            target=run_provider,
            args=(name, func),
            name=f"LunaWetter-{name}",
            daemon=True,
        )
        workers.append(worker)
        worker.start()

    results = {}
    for _ in providers:
        name, data = completed.get()
        results[name] = data
    ordered = [(name, results[name]) for name, _func in providers]
    return complete_provider_forecasts(place, ordered)
