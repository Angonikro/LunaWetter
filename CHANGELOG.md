### Korrektur innerhalb 0.1.23 – Wintersymbole
- Schneefall, Schneeschauer, Schneeregen und Graupel erhalten ein eigenes Schneewolken-Symbol (🌨️).
- Schneesymbole werden in aktueller Wetteranzeige und 7-Tage-Karten mit winterlich hellblauem Akzent und Emoji-Schrift dargestellt.
- Gewitterdarstellung bleibt mit gelbem Blitz erhalten; Versionsnummer bleibt 0.1.23.

### Korrektur innerhalb 0.1.23 – Gewittersymbole
- Gewitterbedingungen erkennen nun auch „Blitz“ und erzwingen Emoji-Darstellung (⛈️) statt Textdarstellung.
- Das Gewittersymbol erhält eine gelbe Akzentfarbe und wird sowohl in der aktuellen Wetteranzeige als auch in den 7-Tage-Karten hervorgehoben.
- Versionsnummer bleibt 0.1.23.

## 0.1.23 – Logo-Wolkensymbol korrigiert
- Das Wolkensymbol neben „LunaWetter“ in der Kopfzeile verwendet jetzt dieselbe vollständige Emoji-Darstellung und erhält feste Abmessungen sowie Innenabstand.
- Versionsnummer bleibt bei 0.1.23.

## 0.1.23 – Symbolanzeige korrigiert
- Bewölkt-Symbol verwendet jetzt die Emoji-Darstellung (☁️), damit die Wolkenform vollständig gerendert wird.
- Wetter-Icons in den Tageskarten erhalten mehr vertikalen Platz und Innenabstand, damit Qt-/Schriftmetriken die Symbole nicht abschneiden.
- Versionsnummer bleibt auf ausdrücklichen Wunsch bei 0.1.23.

## 0.1.23
- Ergänzt fehlende Tage kurzer Anbieter-Vorhersagen mit einer klar gekennzeichneten Open-Meteo-Zusatzprognose (API ohne Schlüssel, Geocoding + 7 Tageswerte).
- Originale Tageswerte der jeweiligen Wetterseite bleiben unverändert und werden zuerst angezeigt; ergänzte Tage sind pro Karte als „Open-Meteo · Zusatzmodell“ markiert.
- Temperatur-Maximum/Minimum, Wettercode, Regenwahrscheinlichkeit, Niederschlagsmenge und maximaler Wind werden getrennt übernommen.
- Die Kopfzeile der 7-Tage-Vorhersage zeigt die Anzahl ergänzter Tage und macht die Datenherkunft transparent.

# Änderungsprotokoll

## 0.1.15
- Wetterdienst.de aus dem aktiven Vergleich entfernt und durch den US-amerikanischen Anbieter AccuWeather ersetzt. AccuWeather wird über die öffentliche Ortssuche und Wetterseite ohne API-Schlüssel abgefragt.
- wetter.com: Unterste Kartenzeile verbessert. Wenn die öffentliche Seite Stundenwerte liefert, werden Niederschlagswahrscheinlichkeit, Niederschlagsmenge, Windrichtung/-geschwindigkeit und Böen aus dem ersten Stundenblock mit eindeutiger Vorhersage-Kennzeichnung angezeigt. Der bisherige allgemeine Platzhaltertext entfällt.
- Beenden wartet nicht mehr auf laufende Wetterabfragen; das Fenster und die Anwendung können sofort schließen.
- Wetterabrufe laufen in daemonisierten Hintergrundthreads, einschließlich der sechs parallelen Anbieterabrufe. Noch laufende öffentliche HTTP-Aufrufe halten den Programmprozess beim Beenden nicht mehr auf.
- Tray-Menüpunkt „Beenden“ verwendet denselben regulären Schließpfad wie das Fensterschließen.
- HTTP-Timeout wieder auf 18 Sekunden zurückgesetzt, damit Foreca bei langsamen Antworten nicht vorzeitig ausfällt.
- Die sechs Anbieter bleiben erhalten; AccuWeather ersetzt Wetterdienst.de in der aktiven Abrufliste.

## 0.1.14
- Aktive Anbieterliste auf die sechs beim Nutzer bestätigten Datenlieferanten reduziert: Foreca, wetter.com, Wetterdienst.de, Wetterblick, Wetterkompass und weather.com.
- Weathernews und meteoblue vollständig aus der aktiven Oberfläche und dem Abruf entfernt.
- Die sechs Anbieter werden parallel statt nacheinander abgefragt.
- HTTP-Timeout pro öffentlichem Seitenaufruf von 18 auf 3 Sekunden reduziert.
- Beim Beenden wird auf den laufenden Worker höchstens 10 Sekunden gewartet; der Worker wird vor dem Abbau des Fensters sauber auslaufen gelassen.
- Bestehende Oberfläche, Tray-Funktion und Datenparser der sechs erfolgreichen Anbieter unverändert gelassen.

## 0.1.13
- WetterKontor durch Wetterkompass ersetzt; weiterhin genau acht Anbieter.
- Neuer Parser liest die öffentliche Wetterkompass-Ortsseite ohne API oder API-Schlüssel.
- Wetterkompass-Daten werden ausdrücklich als DWD-Modellvorhersage, nicht als Stationsmessung gekennzeichnet.

## 0.1.12
- Weathernews, WetterKontor, weather.com und meteoblue als Kandidaten ergänzt.
- Vier beim Nutzer funktionierende Anbieter Foreca, wetter.com, Wetterdienst.de und Wetterblick beibehalten.

## 0.1.11
- Öffentliche Seitenparser für Meteologix und wetter.net überarbeitet.

## 0.1.10
- Aktive Vergleichsliste auf acht Anbieter reduziert.

## 0.1.9
- Wetterblick, wetter.net und Wetter-Germany als öffentliche Wetterseiten ergänzt.

## 0.1.8
- Wetterdienst.de als achten Anbieter ergänzt.

## 0.1.7
- Kachelmannwetter als siebten Anbieter ergänzt.

## 0.1.6
- Foreca-Temperaturerkennung verbessert.

## 0.1.5
- Foreca-Ortsseite und BBC-Ortssuche verbessert.

## 0.1.4
- Öffentliche Seitenabfragen verbessert; Meteologix und meteoCORE aufgenommen.

## 0.1.3
- Erste Version mit sechs Wetteranbieter-Kacheln und GTK-System-Tray.
