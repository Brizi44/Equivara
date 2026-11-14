# Equivara

**Equivara** ist eine rundenbasierte Wirtschafts- und Umweltsimulation im Stil von System Dynamics.
Du führst ein kleines Land über 60 Jahre (12 Zyklen à 5 Jahre) und verteilst Nahrung, Güter, Energie,
Handel und Investitionen. Bevölkerung, Produktion, Umwelt und Schulden reagieren mit Verzögerungen und
Rückkopplungen aufeinander. Ziel ist ein stabiles Gleichgewicht statt kurzfristigem Wachstum.

## Funktionen

- **Live-Anzeige:** Budgetbalken, Prognose für den nächsten Zyklus und Warnungen, während du tippst
- **Diagramme:** Verlauf aller wichtigen Kennzahlen, Kapitalstöcke, Kennlinien mit aktuellem Arbeitspunkt
- **Wirkungsgefüge:** die Rückkopplungsschleifen des Modells, hervorgehoben nach aktuellem Zustand
- **Szenarien und Ereignisse:** verschiedene Startlagen, zufällige Ereignisse (abschaltbar, mit Seed reproduzierbar)
- **Berater:** schlägt eine durchgerechnete Strategie mit Begründung vor
- **Bericht:** Verlaufstabelle, CSV-Export, HTML-Bericht (im Browser als PDF speicherbar)
- **Bestenliste, Speichern/Laden, Rückgängig, Tutorial**

## Starten

Benötigt Python 3.10+ (tkinter ist in der Standardinstallation enthalten). Keine weiteren Pakete nötig.

```bash
python equivara.py
```

Optional: `pillow` für den PNG-Export von Diagrammen, `pytest` für die Tests.

```bash
python -m pip install pytest
python -m pytest tests -q
```

## Projektaufbau

| Datei | Inhalt |
|---|---|
| `equivara.py` | Starter |
| `equivara_engine.py` | Simulationsmodell (ohne GUI, testbar) |
| `equivara_gui.py` | Oberfläche (Tkinter) |
| `equivara_widgets.py` | Diagramme und UI-Bausteine |
| `equivara_views.py` | Kennlinien, Wirkungsgefüge, Vergleich, Bestenliste, Tutorial |
| `equivara_export.py` | HTML-/PDF-Bericht |
| `equivara_store.py` | Bestenliste und Einstellungen (`~/.equivara/`) |
| `tests/` | pytest-Tests |

## Herkunft und Hinweis

Equivara ist ein eigenständiges Hobby- und Lernprojekt. Das Grundmodell ist inspiriert vom Lernspiel
*STRATAGEM-1* (Dennis L. Meadows et al., System Dynamics) und lehnt sich an dessen veröffentlichte
Modellstruktur an. Die Kennlinien sind eigene Näherungen. Equivara steht in keiner Verbindung zu den
Autoren oder Rechteinhabern von STRATAGEM und wird von ihnen weder unterstützt noch geprüft.

## Lizenz

[MIT](LICENSE) © 2026 Brizi44
