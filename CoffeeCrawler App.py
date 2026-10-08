"""
PnP-Charakterbogen – Einzeldatei-Version mit mehreren Regelwerken
Datenbank (SQLite), Spieler-Bereich und Spielleiter-Bereich in einer Datei.

Regelwerke (pro Charakter wählbar):
  • Standard (Coffeecrawler)  – der große Bogen mit Tabs
  • Miniregelwerk             – der kleine Bogen mit Zeichenfeld und Würfel-Attributen

Hinweis: In der stlite-Playground (https://edit.share.stlite.net/) liegt die Datenbank
nur im Arbeitsspeicher des Browsers -> Backup über "Spielleiter" herunterladen/einspielen.
Das Portrait-Zeichenfeld (beide Regelwerke) braucht keine eigene Streamlit-Komponente und
läuft damit auch in der Playground.

AUFBAU DER DATEI
  1. Einstellungen
  2. Datenbank
  3. Gemeinsame Helfer
  4. Regelwerk „Standard“ (Coffeecrawler)
  5. Regelwerk „Miniregelwerk“   (enthält auch das gemeinsame Portrait-Zeichenfeld)
  6. Regelwerk-Register         <- hier wird ein neues Regelwerk eingetragen
  7. Spieler-Bereich            (Neu · Laden · Charakter bearbeiten · Handouts)
  8. Spielleiter-Bereich        (Charaktere · Handouts verwalten · Backup)
  9. Sidebar & Navigation
 10. Start
"""
import base64
import copy
import hashlib
import html
import io
import json
import random
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# Muss der erste Streamlit-Aufruf sein
_ICON = Path("CoffeCrawler.jpg")
st.set_page_config(
    layout="wide", page_title="PnP-Charakterbogen",
    page_icon=str(_ICON) if _ICON.exists() else "🎲",
)

# =============================================================================
# 1. EINSTELLUNGEN
# =============================================================================
GM_PASSWORT = "asdf"  # <- ändern
DB_PATH = Path("charaktere.db")
NEU = "➕ Neuer Charakter"
PNG_PREFIX = "data:image/png;base64,"

# Regelwerke (Kürzel, so stehen sie auch in der Datenbank)
STANDARD = "standard"
MINI = "mini"

# Menüpunkte für Spieler
AKTION_NEU = "Neuen Charakter erstellen"
AKTION_LADEN = "Charakter laden"
AKTION_BEARBEITEN = "Charakter bearbeiten"
AKTION_HANDOUTS = "Handouts ansehen"
SPIELER_AKTIONEN = [AKTION_NEU, AKTION_LADEN, AKTION_BEARBEITEN, AKTION_HANDOUTS]
BOGEN_AKTIONEN = [AKTION_BEARBEITEN]  # Seiten, auf denen der Bogen angezeigt wird

# Menüpunkte für den Spielleiter (nur nach Login sichtbar)
AKTION_GM_CHARAKTERE = "Charaktere"
AKTION_GM_HANDOUTS = "Handouts verwalten"
AKTION_GM_BACKUP = "Backup"
GM_AKTIONEN = [AKTION_GM_CHARAKTERE, AKTION_GM_HANDOUTS, AKTION_GM_BACKUP]

# Dateitypen, die sich im Browser anzeigen lassen, ohne dass ein Download nötig ist
HANDOUT_TYPEN = {
    "png": "bild", "jpg": "bild", "jpeg": "bild", "gif": "bild", "webp": "bild",
    "pdf": "pdf", "txt": "text", "md": "text",
}


# =============================================================================
# 2. DATENBANK
# =============================================================================

# ----- 2a. Grundlagen
@contextmanager
def verbindung():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    # Der komplette Bogen liegt als JSON in der Spalte "daten" (je nach Regelwerk anders
    # aufgebaut). Zusätzlich stehen Name, Regelwerk und Setting als eigene Spalten da,
    # damit man Charaktere auflisten und eindeutig adressieren kann.
    with verbindung() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS spieler (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS charaktere (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                spieler_id   INTEGER NOT NULL REFERENCES spieler(id) ON DELETE CASCADE,
                name         TEXT NOT NULL,
                regelwerk    TEXT NOT NULL DEFAULT 'mini',
                setting      TEXT NOT NULL DEFAULT '',
                daten        TEXT NOT NULL,
                erstellt_am  TEXT NOT NULL,
                geaendert_am TEXT NOT NULL,
                UNIQUE (spieler_id, name)
            );
            CREATE TABLE IF NOT EXISTS handouts (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                titel        TEXT NOT NULL,
                dateiname    TEXT NOT NULL,
                typ          TEXT NOT NULL,
                daten        BLOB NOT NULL,
                sichtbar     INTEGER NOT NULL DEFAULT 0,
                erstellt_am  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS entwuerfe (
                spieler      TEXT PRIMARY KEY,
                daten        TEXT NOT NULL,
                geaendert_am TEXT NOT NULL
            );
            """
        )
        # Ältere Datenbanken nachrüsten (bestehende Charaktere sind Miniregelwerk-Bögen)
        spalten = [r["name"] for r in conn.execute("PRAGMA table_info(charaktere)")]
        if "setting" not in spalten:
            conn.execute("ALTER TABLE charaktere ADD COLUMN setting TEXT NOT NULL DEFAULT ''")
        if "regelwerk" not in spalten:
            conn.execute("ALTER TABLE charaktere ADD COLUMN regelwerk TEXT NOT NULL DEFAULT 'mini'")


# ----- 2b. Charaktere
def charakter_speichern(spieler_name, charakter_name, bogen):
    jetzt = datetime.now().isoformat(timespec="seconds")
    with verbindung() as conn:
        conn.execute("INSERT OR IGNORE INTO spieler (name) VALUES (?)", (spieler_name,))
        spieler_id = conn.execute(
            "SELECT id FROM spieler WHERE name = ?", (spieler_name,)
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO charaktere
                (spieler_id, name, regelwerk, setting, daten, erstellt_am, geaendert_am)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (spieler_id, name) DO UPDATE SET
                regelwerk = excluded.regelwerk, setting = excluded.setting,
                daten = excluded.daten, geaendert_am = excluded.geaendert_am
            """,
            (spieler_id, charakter_name, regelwerk_von(bogen), bogen_setting(bogen),
             json.dumps(bogen, ensure_ascii=False), jetzt, jetzt),
        )


def charaktere_von_spieler(spieler_name):
    with verbindung() as conn:
        rows = conn.execute(
            """SELECT c.name FROM charaktere c JOIN spieler s ON s.id = c.spieler_id
               WHERE s.name = ? ORDER BY c.name""",
            (spieler_name,),
        ).fetchall()
        return [r["name"] for r in rows]


def charakter_laden(spieler_name, charakter_name):
    with verbindung() as conn:
        row = conn.execute(
            """SELECT c.daten FROM charaktere c JOIN spieler s ON s.id = c.spieler_id
               WHERE s.name = ? AND c.name = ?""",
            (spieler_name, charakter_name),
        ).fetchone()
        return json.loads(row["daten"]) if row else None


def charakter_loeschen(spieler_name, charakter_name):
    with verbindung() as conn:
        conn.execute(
            """DELETE FROM charaktere
               WHERE name = ? AND spieler_id = (SELECT id FROM spieler WHERE name = ?)""",
            (charakter_name, spieler_name),
        )


def alle_charaktere():
    with verbindung() as conn:
        rows = conn.execute(
            """SELECT s.name AS spieler, c.name, c.regelwerk, c.setting, c.geaendert_am
               FROM charaktere c JOIN spieler s ON s.id = c.spieler_id
               ORDER BY s.name, c.name"""
        ).fetchall()
        return [dict(r) for r in rows]


# ----- 2c. Entwürfe (Zwischenspeicher des Charakterbogens, ein Eintrag pro Spielername)
def entwurf_db_speichern(schluessel, text):
    jetzt = datetime.now().isoformat(timespec="seconds")
    with verbindung() as conn:
        conn.execute(
            """INSERT INTO entwuerfe (spieler, daten, geaendert_am) VALUES (?, ?, ?)
               ON CONFLICT (spieler) DO UPDATE SET
                   daten = excluded.daten, geaendert_am = excluded.geaendert_am""",
            (schluessel, text, jetzt),
        )


def entwurf_db_laden(schluessel):
    with verbindung() as conn:
        row = conn.execute(
            "SELECT daten FROM entwuerfe WHERE spieler = ?", (schluessel,)
        ).fetchone()
        return row["daten"] if row else None


def entwurf_db_loeschen(schluessel):
    with verbindung() as conn:
        conn.execute("DELETE FROM entwuerfe WHERE spieler = ?", (schluessel,))


# ----- 2d. Handouts
def handout_speichern(titel, dateiname, typ, daten, sichtbar):
    jetzt = datetime.now().isoformat(timespec="seconds")
    with verbindung() as conn:
        conn.execute(
            """INSERT INTO handouts (titel, dateiname, typ, daten, sichtbar, erstellt_am)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (titel, dateiname, typ, daten, int(sichtbar), jetzt),
        )


def handouts_liste(nur_sichtbar=True):
    sql = "SELECT id, titel, dateiname, typ, sichtbar, erstellt_am FROM handouts"
    if nur_sichtbar:
        sql += " WHERE sichtbar = 1"
    sql += " ORDER BY erstellt_am DESC, id DESC"
    with verbindung() as conn:
        return [dict(r) for r in conn.execute(sql).fetchall()]


def handout_laden(handout_id):
    with verbindung() as conn:
        row = conn.execute("SELECT * FROM handouts WHERE id = ?", (handout_id,)).fetchone()
        return dict(row) if row else None


def handout_sichtbarkeit(handout_id, sichtbar):
    with verbindung() as conn:
        conn.execute("UPDATE handouts SET sichtbar = ? WHERE id = ?", (int(sichtbar), handout_id))


def handout_loeschen(handout_id):
    with verbindung() as conn:
        conn.execute("DELETE FROM handouts WHERE id = ?", (handout_id,))


# =============================================================================
# 3. GEMEINSAME HELFER (für alle Regelwerke, Spieler und Spielleiter)
# =============================================================================

# ----- Zugriff auf einen Bogen, egal welches Regelwerk
def regelwerk_von(bogen):
    """Regelwerk-Kürzel eines Bogens (ältere Bögen ohne Angabe sind Miniregelwerk-Bögen)."""
    return bogen.get("regelwerk") or MINI


def bogen_name(bogen):
    if regelwerk_von(bogen) == STANDARD:
        name = bogen.get("werte", {}).get("char_name", "")
    else:
        name = bogen.get("charakter", {}).get("name", "")
    return str(name or "").strip()


def bogen_setting(bogen):
    if regelwerk_von(bogen) == STANDARD:
        setting = bogen.get("werte", {}).get("Setting", "")
    else:
        setting = bogen.get("charakter", {}).get("setting", "")
    return str(setting or "").strip()


def regelwerk_name(kuerzel):
    return REGELWERKE.get(kuerzel, {}).get("name", kuerzel)


# ----- Bestätigungsdialog
def bestaetigen(frage, schluessel):
    """Zeigt Ja/Nein-Buttons. Gibt True (Ja), False (Nein) oder None (noch keine Antwort) zurück."""
    st.warning(frage)
    ja, nein, _ = st.columns([1, 1, 4])
    if ja.button("✅", key=f"ja_{schluessel}"):
        st.session_state.pop("bestaetigung", None)
        return True
    if nein.button("❌", key=f"nein_{schluessel}"):
        st.session_state.pop("bestaetigung", None)
        st.rerun()
    return None


# ----- Kleine Anzeige-Helfer
def absatz(text, klasse="st-key-Talentwerte"):
    """Ein Textabsatz (HTML-sicher, auch für Nutzereingaben)."""
    st.html(f'<p class="{klasse}">{html.escape(str(text))}</p>')


def html_text(text):
    return html.escape(str(text))


def portrait_zu_bytes(portrait):
    """PNG-Data-URL (Miniregelwerk-Zeichenfeld) -> Bytes."""
    if isinstance(portrait, str) and portrait.startswith(PNG_PREFIX):
        return base64.b64decode(portrait[len(PNG_PREFIX):])
    return None


def html_einbetten(html_text, hoehe):
    """Bettet eine HTML-Seite ein (st.iframe in neueren Streamlit-Versionen, sonst components.html)."""
    if hasattr(st, "iframe"):
        st.iframe(html_text, height=hoehe)
    else:
        components.html(html_text, height=hoehe)


def backup_dateiname():
    return f"charaktere_backup_{datetime.now():%Y-%m-%d_%H-%M}.db"


# ----- Handout-Anzeige
def pdf_anzeigen(daten):
    b64 = base64.b64encode(daten).decode()
    html_einbetten(
        f"""
        <iframe id="pdf" style="width:100%;height:780px;border:0"></iframe>
        <script>
        const bin = atob("{b64}");
        const bytes = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
        const url = URL.createObjectURL(new Blob([bytes], {{type: "application/pdf"}}));
        document.getElementById("pdf").src = url + "#toolbar=0&navpanes=0";
        </script>
        """,
        800,
    )


def handout_anzeigen(h, titel_zeigen=False):
    if titel_zeigen:
        st.subheader(h["titel"])
    if h["typ"] == "bild":
        st.image(bytes(h["daten"]), use_container_width=True)
    elif h["typ"] == "pdf":
        pdf_anzeigen(bytes(h["daten"]))
    else:
        text = bytes(h["daten"]).decode("utf-8", errors="replace")
        if h["dateiname"].lower().endswith(".md"):
            st.markdown(text)
        else:
            st.text(text)


# =============================================================================
# 4. REGELWERK „STANDARD“ (Coffeecrawler)
#    Alle Funktionen und Keys dieses Regelwerks beginnen mit cc_ bzw. stehen hier.
#    Ein Bogen sieht so aus: {"regelwerk": "standard", "werte": {<alle Keys unten>}}
# =============================================================================

# ----- 4a. Konfiguration
CC_ATTRIBUTE = ["Charisma", "Manipulation", "Erscheinung", "Intelligenz",
                "Weisheit", "Wahrnehmung", "Stärke", "Geschick", "Konstitution"]
CC_ANZAHL_TALENTE = 10
CC_ANZAHL_ITEMS = 15
CC_HISTORIE_MAX = 20
CC_WUERFEL = {"": 0, "W4": 4, "W6": 6, "W8": 8, "W10": 10, "W12": 12, "W20": 20, "W100": 100}
CC_SCHADENSWUERFEL = ["1W4", "1W8", "2W6"]
CC_HAENDE = {"HH": "Haupthand", "ZH": "Zweihändig", "NH": "Nebenhand"}

# Kampftalente und Tricks haben dieselbe Tabellenstruktur (Name · Probe · Reichweite · Schaden)
CC_KAMPF = {
    "titel": "Attacke", "anzahl": 6,
    "name": "Attacke {i}", "probe": "Probe_Kampf {i}",
    "rw": "Reichweite {i}", "schaden": "Schaden {i}",
}
CC_TRICKS = {
    "titel": "Trick", "anzahl": 6,
    "name": "Trick {i}", "probe": "Probe_Trick {i}",
    "rw": "Reichweite_Trick {i}", "schaden": "Schaden_Trick {i}",
}
CC_TABELLEN = [CC_KAMPF, CC_TRICKS]

# Verstecktes Übergabefeld des Zeichenfelds (siehe Abschnitt 5b).
# position: fixed verhindert, dass die Seite beim Fokussieren des Feldes springt.
CC_CSS = """
<style>
.st-key-cc_portrait_box {
    position: fixed;
    top: 0;
    left: 0;
    width: 1px;
    height: 1px;
    opacity: 0;
    overflow: hidden;
    pointer-events: none;
}
</style>
"""

# Grundwerte (einzelne Felder)
CC_BASIS = {
    # Charakter
    "char_name": "", "Setting": "", "Volksangehörigkeit": "", "Geschlecht": "",
    "Aussehen": "", "Erster Eindruck": "", "bild_base64": "",
    # Hintergrund
    "Beruf": "", "Erlernte Fähigkeiten": "", "Hintergrund": "", "Ziele": "",
    # Persönlichkeit
    "Charaktereigenschaften": "", "Ideale": "", "Bindung": "", "Makel": "", "Ängste": "",
    # Level, Attribute, Lebenspunkte
    "Level": 1, "Lebenspunkte": 43, "Steigerungspunkte": 40,
    **{attribut: 40 for attribut in CC_ATTRIBUTE},
    # Skills
    "skill1": "", "skill_1_kosten": 0, "skill_1_aktiv": False,
    "skill2": "", "skill_2_kosten": 0, "skill_2_aktiv": False,
    "Skillenergie": 20, "max_Skillenergie": 20,
    # Sonstiges
    "Hotslots": 2, "zähler1": 0, "zähler2": 0, "zähler3": 0,
    "Diredare": 0, "Diredare ausgegeben/verdient": "",
    "Notizen": "",
}


def cc_bild_data_url(b64):
    """Gespeichertes Bild (Base64 ohne Prefix, PNG oder altes JPEG) -> Data-URL für das Zeichenfeld."""
    if not b64:
        return None
    mime = "image/jpeg" if b64.startswith("/9j/") else "image/png"
    return f"data:{mime};base64,{b64}"


def cc_standardwerte():
    """Alle Felder eines leeren Bogens (ohne Hotslot-Auswahl, die hängt von 'Hotslots' ab)."""
    werte = dict(CC_BASIS)
    for i in range(1, CC_ANZAHL_TALENTE + 1):
        werte[f"Talent {i}"] = ""
        werte[f"TalentWert {i}"] = 0
    for i in range(1, CC_ANZAHL_ITEMS + 1):
        werte[f"item {i}"] = ""
        werte[f"itemmenge {i}"] = 0
    for spec in CC_TABELLEN:
        for i in range(1, spec["anzahl"] + 1):
            for feld in ("name", "probe", "rw", "schaden"):
                werte[spec[feld].format(i=i)] = ""
    for kuerzel in CC_HAENDE:
        werte[f"{kuerzel}_Nahkampf"] = ""
        werte[f"{kuerzel}_Fernkampf"] = ""
        werte[f"{kuerzel}_Schadenswert"] = CC_SCHADENSWUERFEL[0]
    return werte


def cc_werte_ergaenzen(daten):
    """Gespeicherte Werte + Standardwerte für alles, was fehlt (auch bei älteren Dateien)."""
    werte = cc_standardwerte()
    werte.update({k: v for k, v in daten.items() if k in werte})
    anzahl = werte["Hotslots"] if isinstance(werte["Hotslots"], int) else 0
    for i in range(anzahl):
        werte[f"hotslot_auswahl_{i}"] = daten.get(f"hotslot_auswahl_{i}", "")
    return werte


def cc_speicher_keys():
    """Alle Keys, die zum Charakter gehören (inkl. der aktuell vorhandenen Hotslots)."""
    keys = list(cc_standardwerte())
    keys += [f"hotslot_auswahl_{i}" for i in range(st.session_state.get("Hotslots", 0))]
    return keys


def cc_max_lebenspunkte(werte=None):
    """Maximale Lebenspunkte: Konstitution + 3x Level."""
    werte = st.session_state if werte is None else werte
    return werte["Konstitution"] + 3 * werte["Level"]


# ----- 4b. Daten <-> Session-State
def cc_leer():
    return {"regelwerk": STANDARD, "werte": cc_werte_ergaenzen({})}


def cc_in_session(bogen):
    """Schreibt einen Bogen (aus Datenbank oder JSON-Datei) in die Eingabefelder."""
    for key, wert in cc_werte_ergaenzen(bogen.get("werte", {})).items():
        st.session_state[key] = wert
    st.session_state.pop("letzte_probe", None)
    # Zeichenfeld mit dem gespeicherten Porträt neu aufbauen
    st.session_state["cc_portrait_start"] = cc_bild_data_url(st.session_state["bild_base64"])
    st.session_state["cc_portrait_version"] = st.session_state.get("cc_portrait_version", 0) + 1
    st.session_state["cc_portrait_transport"] = ""


def cc_bereit():
    """Wird bei jedem Durchlauf vor dem Zeichnen des Bogens aufgerufen."""
    for key, wert in cc_standardwerte().items():
        st.session_state.setdefault(key, wert)
    for i in range(st.session_state["Hotslots"]):
        st.session_state.setdefault(f"hotslot_auswahl_{i}", "")
    st.session_state.setdefault("wuerfel_historie", [])
    st.session_state.setdefault("cc_portrait_start", cc_bild_data_url(st.session_state["bild_base64"]))
    st.session_state.setdefault("cc_portrait_version", 0)

    # Vorherige Werte von Level und Attributen merken: die on_change-Callbacks brauchen sie,
    # um die Differenz für die Steigerungspunkte zu berechnen
    for key in ["Level"] + CC_ATTRIBUTE:
        st.session_state[f"_alt_{key}"] = st.session_state[key]

    # Lebenspunkte und Skillenergie bleiben im Bereich ihrer Slider
    st.session_state["Lebenspunkte"] = max(0, min(st.session_state["Lebenspunkte"], cc_max_lebenspunkte()))
    st.session_state["Skillenergie"] = max(0, min(st.session_state["Skillenergie"],
                                                  st.session_state["max_Skillenergie"]))


# ----- 4c. Callbacks
def cc_bild_verarbeiten():
    """Bild hochgeladen: auf die Zeichenfläche (300x380) setzen und als Porträt übernehmen."""
    datei = st.session_state.get("neues_bild_uploader")
    if datei is None:
        return
    try:
        from PIL import Image
        bild = Image.open(io.BytesIO(datei.getvalue())).convert("RGB")
        bild.thumbnail((300, 380))
        flaeche = Image.new("RGB", (300, 380), "white")
        flaeche.paste(bild, ((300 - bild.width) // 2, (380 - bild.height) // 2))
        puffer = io.BytesIO()
        flaeche.save(puffer, format="PNG")
    except Exception:
        st.toast("Das Bild konnte nicht gelesen werden.", icon="⚠️")
        return
    b64 = base64.b64encode(puffer.getvalue()).decode("ascii")
    st.session_state["bild_base64"] = b64
    st.session_state["cc_portrait_start"] = PNG_PREFIX + b64
    st.session_state["cc_portrait_version"] += 1
    st.session_state["cc_portrait_transport"] = ""


def cc_portrait_uebernehmen():
    """Übernimmt das, was das Zeichenfeld gemeldet hat, in 'bild_base64'."""
    uebergabe = st.session_state.get("cc_portrait_transport", "")
    if uebergabe.startswith("img|" + PNG_PREFIX):
        st.session_state["bild_base64"] = uebergabe[len("img|" + PNG_PREFIX):]
    elif uebergabe == "clear|":
        st.session_state["bild_base64"] = ""


def cc_attribut_geaendert(attribut):
    """Passt die Steigerungspunkte an, wenn ein Attribut geändert wurde."""
    delta = st.session_state[attribut] - st.session_state[f"_alt_{attribut}"]
    st.session_state["Steigerungspunkte"] -= 2 * delta


def cc_level_geaendert():
    """Passt Steigerungspunkte und Lebenspunkte an, wenn das Level geändert wurde."""
    delta = st.session_state["Level"] - st.session_state["_alt_Level"]
    st.session_state["Steigerungspunkte"] += 4 * delta
    st.session_state["Lebenspunkte"] += 3 * delta


def cc_lp_rechnen():
    """Rechnet die Eingabe auf den aktuellen Lebenspunktestand.
    Erlaubt sind Summen aus ganzen Zahlen, z.B. '10' / '+10' (addieren), '-5' (abziehen), '10-3+2'."""
    eingabe = st.session_state["lp_eingabe"].replace(" ", "")
    st.session_state["lp_eingabe"] = ""
    if not eingabe:
        return
    if not re.fullmatch(r"[+-]?\d+([+-]\d+)*", eingabe):
        st.toast("Bitte eine gültige Rechnung eingeben (z.B. +10, -5, 10-3)", icon="⚠️")
        return
    st.session_state["Lebenspunkte"] += sum(int(zahl) for zahl in re.findall(r"[+-]?\d+", eingabe))


def cc_diredare_aendern():
    """'50' setzt den Wert, '+10' / '-5' rechnen auf den aktuellen Wert."""
    eingabe = st.session_state["diredare_eingabe"].strip()
    st.session_state["diredare_eingabe"] = ""
    if not eingabe:
        return
    try:
        if eingabe[0] in "+-":
            st.session_state["Diredare"] += int(eingabe)
        else:
            st.session_state["Diredare"] = int(eingabe)
    except ValueError:
        st.toast("Bitte eine gültige Zahl eingeben (z.B. 50, +10, -5)", icon="⚠️")


def cc_skillenergie_plus():
    st.session_state["Skillenergie"] += 1


def cc_skillenergie_minus():
    st.session_state["Skillenergie"] -= 1


def cc_max_skillenergie_plus():
    st.session_state["max_Skillenergie"] += 1


def cc_skill_aktivieren(nr):
    """Zieht die Kosten von der Skillenergie ab; reicht sie nicht, zahlt man mit Lebenspunkten."""
    kosten = st.session_state[f"skill_{nr}_kosten"]
    st.session_state["Skillenergie"] -= kosten
    if st.session_state["Skillenergie"] <= -1:
        st.session_state["Lebenspunkte"] -= kosten


# ----- 4d. Würfel, Probenwurf, Würfelhistorie (Sidebar)
def cc_historie_eintragen(art, beschreibung, ergebnis):
    """Fügt einen Wurf oben in die Würfelhistorie ein (neueste zuerst)."""
    historie = st.session_state.setdefault("wuerfel_historie", [])
    historie.insert(0, {
        "zeit": datetime.now().strftime("%H:%M:%S"),
        "art": art, "beschreibung": beschreibung, "ergebnis": ergebnis,
    })
    del historie[CC_HISTORIE_MAX:]


def cc_historie_leeren():
    st.session_state["wuerfel_historie"] = []


def cc_probe_auswerten(zielwert, wurf):
    """W100-Probe (Unterwürfeln). Reihenfolge ist wichtig:
    Kritischer Misserfolg > Kritischer Erfolg > Erfolg > Misserfolg."""
    if wurf == 100:
        return "💀 Kritischer Misserfolg"
    if wurf < zielwert * 0.05:
        return "🌟 Kritischer Erfolg"
    if wurf <= zielwert:
        return "✅ Erfolg"
    return "❌ Misserfolg"


def cc_talent_optionen():
    """0 = kein Talent, sonst die Nummern aller Talente, die einen Namen haben."""
    return [0] + [i for i in range(1, CC_ANZAHL_TALENTE + 1)
                  if st.session_state.get(f"Talent {i}", "").strip()]


def cc_talent_anzeigename(i):
    if i == 0:
        return "– kein Talent –"
    return f"{st.session_state[f'Talent {i}']} (+{st.session_state[f'TalentWert {i}']})"


def cc_probe_callback():
    """Berechnet den Zielwert, würfelt 1W100 und speichert das Ergebnis."""
    attribut = st.session_state["probe_attribut"]
    talent_nr = st.session_state["probe_talent"]
    zielwert = st.session_state[attribut] + st.session_state["probe_modifikator"]
    talent_text = ""
    if talent_nr != 0:
        zielwert += st.session_state[f"TalentWert {talent_nr}"]
        talent_text = f" + {st.session_state[f'Talent {talent_nr}']}"

    wurf = random.randint(1, 100)
    probe = {
        "beschreibung": f"{attribut}{talent_text}",
        "zielwert": zielwert, "wurf": wurf,
        "ergebnis": cc_probe_auswerten(zielwert, wurf),
    }
    st.session_state["letzte_probe"] = probe
    cc_historie_eintragen("Probe", f"{probe['beschreibung']} (Ziel {zielwert})",
                          f"{wurf} → {probe['ergebnis']}")


def cc_sidebar():
    """Würfel, Probenwurf und Würfelhistorie in der Sidebar."""
    with st.sidebar:
        st.divider()
        st.subheader("🎲 Würfel")
        typ = st.selectbox("Würfel", list(CC_WUERFEL), key="cc_wuerfel_typ")
        seiten = CC_WUERFEL[typ]
        anzahl = st.slider("Anzahl", min_value=1, max_value=10, key="cc_wuerfel_anzahl")
        if st.button(f"Würfeln ({anzahl}{typ})", key="cc_wuerfel_btn"):
            if seiten == 0:
                st.warning("Bitte zuerst einen Würfel auswählen.")
            else:
                einzelwuerfe = [random.randint(1, seiten) for _ in range(anzahl)]
                gesamt = sum(einzelwuerfe)
                st.success(f"Ergebnis: {gesamt}")
                detail = f" ({' + '.join(map(str, einzelwuerfe))})" if anzahl > 1 else ""
                cc_historie_eintragen("Würfel", f"{anzahl}{typ}", f"{gesamt}{detail}")

        st.divider()
        st.subheader("🎯 Probenwurf (W100)")
        st.selectbox("Attribut", CC_ATTRIBUTE, key="probe_attribut",
                     format_func=lambda a: f"{a} ({st.session_state[a]})")
        optionen = cc_talent_optionen()
        if st.session_state.get("probe_talent") not in optionen:
            st.session_state["probe_talent"] = 0
        st.selectbox("Talent (optional)", optionen, key="probe_talent",
                     format_func=cc_talent_anzeigename)
        st.number_input("Modifikator (+/-)", value=0, step=5, key="probe_modifikator")
        st.button("Probe würfeln", on_click=cc_probe_callback, use_container_width=True)

        probe = st.session_state.get("letzte_probe")
        if probe:
            st.markdown(
                f"**{probe['beschreibung']}**  \n"
                f"Zielwert: **{probe['zielwert']}** · Wurf: **{probe['wurf']}**  \n"
                f"### {probe['ergebnis']}"
            )

        st.divider()
        with st.expander("📜 Würfelhistorie"):
            historie = st.session_state.get("wuerfel_historie", [])
            if not historie:
                st.caption("Noch nichts gewürfelt.")
            else:
                for eintrag in historie:
                    st.markdown(
                        f"`{eintrag['zeit']}` **{eintrag['art']}** · {eintrag['beschreibung']}  \n"
                        f"→ {eintrag['ergebnis']}"
                    )
                st.button("Historie leeren", on_click=cc_historie_leeren, use_container_width=True)


# ----- 4e. Wiederverwendete Tabellen (Kampf und Tricks)
def cc_aktionen_anzeigen(spec):
    """Nur-Lesen-Ansicht einer Tabelle (Name · Probe · RW · Schaden)."""
    spalten = st.columns([4, 2, 1, 2])
    felder = [("name", spec["titel"]), ("probe", "Probe"), ("rw", "RW"), ("schaden", "Schaden")]
    for spalte, (feld, titel) in zip(spalten, felder):
        with spalte:
            absatz(titel)
            for i in range(1, spec["anzahl"] + 1):
                absatz(st.session_state.get(spec[feld].format(i=i), ""))


def cc_aktionen_editor(spec):
    """Eingabe-Ansicht einer Tabelle (Name · Probe · Reichweite · Schaden)."""
    spalten = st.columns([3, 2, 1, 2], vertical_alignment="center")
    kopf = "st-key-Handverteilung"
    with spalten[0]:
        absatz(spec["titel"], kopf)
        for i in range(1, spec["anzahl"] + 1):
            key = spec["name"].format(i=i)
            st.text_input(f"{key}:", key=key, label_visibility="collapsed")
    with spalten[1]:
        absatz("Probe", kopf)
        for i in range(1, spec["anzahl"] + 1):
            key = spec["probe"].format(i=i)
            st.selectbox(f"{key}:", options=list(CC_WUERFEL), key=key, label_visibility="collapsed")
    with spalten[2]:
        absatz("Reichweite", kopf)
        for i in range(1, spec["anzahl"] + 1):
            key = spec["rw"].format(i=i)
            st.text_input(f"{key}:", key=key, label_visibility="collapsed")
    with spalten[3]:
        absatz("Schaden", kopf)
        for i in range(1, spec["anzahl"] + 1):
            key = spec["schaden"].format(i=i)
            st.selectbox(f"{key}:", options=list(CC_WUERFEL), key=key, label_visibility="collapsed")


def cc_felder_anzeigen(felder):
    """Zeigt Paare aus (Beschriftung, Key) als 'Beschriftung: Wert'."""
    for label, key in felder:
        st.html(f"{label}:&emsp; {html_text(st.session_state[key])}")


# ----- 4f. Tab „Übersicht“
def cc_tab_uebersicht():
    col_charakter, col_werte, col_kampf, col_status = st.columns(4)
    with col_charakter:
        cc_uebersicht_charakter()
    with col_werte:
        cc_uebersicht_werte()
    with col_kampf:
        cc_uebersicht_kampf()
    with col_status:
        cc_uebersicht_status()


def cc_uebersicht_charakter():
    s = st.session_state
    with st.expander("Charakter"):
        st.html(f"🏷️Charaktername:&emsp; {html_text(s['char_name'])}")
        st.html(f"🎬Setting:&emsp; {html_text(s['Setting'])}")

    with st.expander("👤 Porträt"):
        if s["bild_base64"]:
            st.image(base64.b64decode(s["bild_base64"]), use_container_width=True)
            st.caption(f"Name: {s['char_name'] or 'Der namenlos geborene von irgendwoher'}")
        else:
            st.info("Dein Held hat noch kein Gesicht.")

    with st.expander("Stammdaten"):
        cc_felder_anzeigen([("Volksangehörigkeit", "Volksangehörigkeit"),
                            ("Geschlecht", "Geschlecht"), ("Aussehen", "Aussehen"),
                            ("Erster Eindruck", "Erster Eindruck")])
    with st.expander("Hintergrund"):
        cc_felder_anzeigen([("Beruf", "Beruf"), ("Erlernte Fähigkeiten", "Erlernte Fähigkeiten"),
                            ("Hintergrund", "Hintergrund"), ("Ziele", "Ziele")])
    with st.expander("Persönliches"):
        cc_felder_anzeigen([("Charaktereigenschaften", "Charaktereigenschaften"),
                            ("Ideale", "Ideale"), ("Bindung", "Bindung"),
                            ("Makel", "Makel"), ("Ängste", "Ängste")])


def cc_uebersicht_werte():
    s = st.session_state
    with st.container(border=True):
        with st.expander("Lebenspunkte"):
            st.subheader("Lebenspunkte")
            maximum = cc_max_lebenspunkte()
            st.header(f"{s['Lebenspunkte']} / {maximum}")
            st.slider("Lebenspunkte", min_value=0, max_value=maximum, key="Lebenspunkte",
                  label_visibility="collapsed")
            st.text_input("Lebenspunkte rechnen", key="lp_eingabe", on_change=cc_lp_rechnen,
                      placeholder="LP ändern: +10 / -5", label_visibility="collapsed")
        with st.expander("📊 Attribute"):
            st.html(f"Level: {s['Level']}")
            st.divider()
            for attribut in CC_ATTRIBUTE:
                st.html(f"<b>{attribut}</b>: <b>{s[attribut]}</b>")

        with st.expander("Talente"):
            col_wert, col_name = st.columns([1, 10])
            with col_wert:
                for i in range(1, CC_ANZAHL_TALENTE + 1):
                    wert = s[f"TalentWert {i}"]
                    absatz(wert if wert >= 1 else "")
            with col_name:
                for i in range(1, CC_ANZAHL_TALENTE + 1):
                    absatz(s[f"Talent {i}"])


def cc_uebersicht_kampf():
    s = st.session_state
    with st.expander("Kampf"):
        cc_aktionen_anzeigen(CC_KAMPF)

    with st.expander("Skills"):
        st.slider("Skillenergie", min_value=0, max_value=s["max_Skillenergie"], key="Skillenergie")
        minus, plus, _ = st.columns([1, 1, 3])
        with minus:
            st.button("-1", on_click=cc_skillenergie_minus, disabled=s["Skillenergie"] <= 0)
        with plus:
            st.button("+1", on_click=cc_skillenergie_plus,
                      disabled=s["Skillenergie"] >= s["max_Skillenergie"])
        for nr in (1, 2):
            absatz(s[f"skill{nr}"])
            st.button(f"Skill {nr} aktivieren", on_click=cc_skill_aktivieren, args=(nr,),
                      key=f"skill_aktivieren_{nr}")

    with st.expander("Tricks"):
        cc_aktionen_anzeigen(CC_TRICKS)


def cc_uebersicht_status():
    s = st.session_state        
    with st.container(border=True):
        st.subheader("Zähler")
        for spalte, nr in zip(st.columns(3), (1, 2, 3)):
            with spalte:
                st.number_input(f"Zähler {nr}", min_value=0, max_value=10, step=1,
                                key=f"zähler{nr}", label_visibility="collapsed")

    with st.expander("Inventar"):
        col_menge, col_item = st.columns([1, 100])
        with col_menge:
            for i in range(1, CC_ANZAHL_ITEMS + 1):
                menge = s[f"itemmenge {i}"]
                absatz(menge if menge >= 1 else "")
        with col_item:
            for i in range(1, CC_ANZAHL_ITEMS + 1):
                absatz(s[f"item {i}"])
        st.divider()
        st.subheader("🤑 Diredare")
        st.write(f"Aktuell: {s['Diredare']}")
        st.text_input("Diredare ändern (z.B. 50 = setzen, +10 / -5 = verrechnen)",
                      key="diredare_eingabe", on_change=cc_diredare_aendern,
                      label_visibility="collapsed")

    with st.container(border=True, key="Hotslots_Übersicht"):
        st.subheader("Hotslots")
        optionen = [""] + [s[f"item {i}"] for i in range(1, CC_ANZAHL_ITEMS + 1)
                           if s[f"item {i}"].strip()]
        for i in range(s["Hotslots"]):
            key = f"hotslot_auswahl_{i}"
            if s[key] not in optionen:  # Gegenstand wurde umbenannt oder entfernt
                s[key] = ""
            st.selectbox(f"Hotslot {i}", options=optionen, key=key, label_visibility="collapsed")


# ----- 4g. Tab „Charakter Details“
def cc_tab_charakter():
    col_stamm, col_hintergrund, col_person, col_portrait = st.columns(4)

    with col_stamm:
        st.header("📝 Stammdaten")
        st.text_input("Charakter-Name", key="char_name")
        st.text_input("Setting (Titel des One Shots)", key="Setting")
        st.text_input("Volksangehörigkeit:", key="Volksangehörigkeit")
        st.text_input("Geschlecht:", key="Geschlecht")
        st.text_area("Aussehen:", key="Aussehen", height=150)
        st.text_area("Erster Eindruck:", key="Erster Eindruck", height=150)

    with col_hintergrund:
        st.header("Hintergrund")
        st.text_input("Beruf:", key="Beruf")
        st.text_area("Erlernte Fähigkeiten:", key="Erlernte Fähigkeiten", height=150)
        st.text_area("Hintergrund:", key="Hintergrund", height=150)
        st.text_area("Ziele:", key="Ziele", height=150)

    with col_person:
        st.header("Persönlichkeit")
        for feld in ("Charaktereigenschaften", "Ideale", "Bindung", "Makel", "Ängste"):
            st.text_input(feld, key=feld)

    with col_portrait:
        st.subheader("Porträt zeichnen")
        html_einbetten(
            f"<!-- v{st.session_state['cc_portrait_version']} -->"
            + portrait_html(st.session_state["cc_portrait_start"], "cc_portrait_box"),
            620,
        )
        st.file_uploader("Oder ein Bild hochladen", type=["png", "jpg", "jpeg"],
                         key="neues_bild_uploader", on_change=cc_bild_verarbeiten)
        # Verstecktes Übergabefeld: das Zeichenfeld schreibt hier hinein
        with st.container(key="cc_portrait_box"):
            st.text_area("Portrait-Übergabe", key="cc_portrait_transport",
                         label_visibility="collapsed")


# ----- 4h. Tab „Attribute und Talente“
def cc_tab_attribute():
    col_attribute, col_talente, col_kampf = st.columns(3)
    with col_attribute:
        cc_spalte_attribute()
    with col_talente:
        cc_spalte_talente()
    with col_kampf:
        cc_spalte_kampf()


def cc_spalte_attribute():
    with st.container(key="Attributswerte2"):
        st.subheader("Level")
        st.number_input("Level", key="Level", min_value=1, step=1,
                        on_change=cc_level_geaendert, label_visibility="collapsed")
        st.divider()
        st.subheader("Attribute")
        for attribut in CC_ATTRIBUTE:
            st.number_input(attribut, key=attribut, min_value=0, step=1,
                            on_change=cc_attribut_geaendert, args=(attribut,))
        # Die Steigerungspunkte werden im Hintergrund mitgezählt:
        # st.html(f"Steigerungspunkte: {st.session_state['Steigerungspunkte']}")


def cc_spalte_talente():
    st.subheader("Talente")
    with st.container(key="Talente"):
        with st.container(key="Talentzeilen"):
            col_wert, col_name = st.columns([3, 15], vertical_alignment="center")
            with col_wert:
                for i in range(1, CC_ANZAHL_TALENTE + 1):
                    st.number_input(f"TalentWert {i}:", key=f"TalentWert {i}",
                                    min_value=0, step=1, label_visibility="collapsed")
            with col_name:
                for i in range(1, CC_ANZAHL_TALENTE + 1):
                    st.text_input(f"Talent {i}:", key=f"Talent {i}", label_visibility="collapsed")

        st.subheader("Maximale Hotslots")
        st.number_input("Maximale Hotslots", key="Hotslots", min_value=0, step=1,
                        label_visibility="collapsed")

        col_energie, col_knopf = st.columns(2)
        with col_energie:
            absatz(f"Maximale Skillenergie: {st.session_state['max_Skillenergie']}")
        with col_knopf:
            st.button("Max Skillenergie +1", on_click=cc_max_skillenergie_plus)


def cc_spalte_kampf():
    with st.container(key="Handverteilung"):
        st.subheader("Kampftalente")
        for spalte, (kuerzel, titel) in zip(st.columns(3), CC_HAENDE.items()):
            with spalte:
                absatz(titel, "st-key-Handverteilung")
                st.text_input("Nahkampf", key=f"{kuerzel}_Nahkampf")
                st.text_input("Fernkampf", key=f"{kuerzel}_Fernkampf")
                st.selectbox("Schadenswert", CC_SCHADENSWUERFEL, key=f"{kuerzel}_Schadenswert")
    with st.container(key="Angriffe"):
        cc_aktionen_editor(CC_KAMPF)


# ----- 4i. Tabs „Skills und Tricks“, „Inventar“, „Notizen“, „Sessionstate“
def cc_tab_skills():
    col_skills, col_kosten, _ = st.columns([2, 1, 2])
    with col_skills:
        st.text_area("Skill 1", key="skill1")
        st.write("")
        st.text_area("Skill 2", key="skill2")
    with col_kosten:
        st.number_input("Skillenergie-Kosten", key="skill_1_kosten", min_value=0)
        st.toggle("Skill 1 passiv", key="skill_1_aktiv")
        st.write("")
        st.number_input("Skillenergie-Kosten ", key="skill_2_kosten", min_value=0)
        st.toggle("Skill 2 passiv", key="skill_2_aktiv")

    st.subheader("Tricks")
    cc_aktionen_editor(CC_TRICKS)


def cc_tab_inventar():
    col_menge, col_item, _, col_diredare = st.columns([1, 5, 1, 1])
    with col_menge:
        for i in range(1, CC_ANZAHL_ITEMS + 1):
            st.number_input(f"itemmenge {i}:", key=f"itemmenge {i}", min_value=0,
                            label_visibility="collapsed")
    with col_item:
        for i in range(1, CC_ANZAHL_ITEMS + 1):
            st.text_input(f"item {i}:", key=f"item {i}", label_visibility="collapsed")
    with col_diredare:
        st.header("🤑 Diredare")
        st.number_input("Diredare", key="Diredare", step=1, label_visibility="collapsed")


def cc_tab_notizen():
    st.header("Notizen")
    st.text_area("Notizen", key="Notizen", label_visibility="collapsed", height=850)


def cc_tab_debug():
    """Nur für den Spielleiter: alle Werte der Eingabefelder (lange Texte gekürzt)."""
    daten = {}
    for key in sorted(st.session_state.keys()):
        wert = st.session_state[key]
        if isinstance(wert, str) and len(wert) > 200:
            wert = f"({len(wert)} Zeichen)"
        daten[key] = wert
    st.json(daten, expanded=False)


# ----- 4j. Der Bogen als Ganzes
def cc_formular():
    """Zeichnet den Bogen und gibt ihn als Dictionary zurück."""
    # Porträt aus dem Zeichenfeld übernehmen, bevor die Tabs gezeichnet werden
    # (sonst würde die Übersicht erst einen Durchlauf später das neue Bild zeigen)
    cc_portrait_uebernehmen()

    # TODO: Rüstungsklasse und Trefferchance; Talente: Probe und Schaden als Festwert + Würfelbutton
    tab_namen = ["Übersicht", "Charakter Details", "Attribute und Talente",
                 "Skills und Tricks", "Inventar", "Notizen"]
    ist_gm = bool(st.session_state.get("gm_ok"))
    if ist_gm:
        tab_namen.append("Sessionstate")

    tabs = st.tabs(tab_namen, key="grosse_tabs")
    with tabs[0]:
        cc_tab_uebersicht()
    with tabs[1]:
        cc_tab_charakter()
    with tabs[2]:
        cc_tab_attribute()
    with tabs[3]:
        cc_tab_skills()
    with tabs[4]:
        cc_tab_inventar()
    with tabs[5]:
        cc_tab_notizen()
    if ist_gm:
        with tabs[6]:
            cc_tab_debug()

    return {"regelwerk": STANDARD,
            "werte": {key: st.session_state[key] for key in cc_speicher_keys()}}


# ----- 4k. Ansicht für den Spielleiter (nur lesen)
def cc_gm_ansicht(bogen, schluessel):
    w = cc_werte_ergaenzen(bogen.get("werte", {}))
    links, rechts = st.columns(2)
    with links:
        st.markdown(f"**{w['char_name']}** · Level {w['Level']}")
        st.caption(f"Setting: {w['Setting'] or '–'}")
        st.write(f"{w['Volksangehörigkeit'] or '–'} · {w['Geschlecht'] or '–'}")
        st.metric("Lebenspunkte", f"{w['Lebenspunkte']} / {cc_max_lebenspunkte(w)}")
        st.metric("Diredare", w["Diredare"])
        if w["bild_base64"]:
            st.image(base64.b64decode(w["bild_base64"]))
    with rechts:
        st.write("**Attribute**")
        st.dataframe(pd.DataFrame([(a, w[a]) for a in CC_ATTRIBUTE], columns=["Attribut", "Wert"]),
                     hide_index=True)
        talente = [(w[f"Talent {i}"], w[f"TalentWert {i}"]) for i in range(1, CC_ANZAHL_TALENTE + 1)
                   if w[f"Talent {i}"].strip()]
        st.write("**Talente**")
        if talente:
            st.dataframe(pd.DataFrame(talente, columns=["Talent", "Wert"]), hide_index=True)
        else:
            st.write("–")

    for spec, titel in ((CC_KAMPF, "Kampf"), (CC_TRICKS, "Tricks")):
        zeilen = []
        for i in range(1, spec["anzahl"] + 1):
            name = w[spec["name"].format(i=i)]
            if name.strip():
                zeilen.append((name, w[spec["probe"].format(i=i)] or "–",
                               w[spec["rw"].format(i=i)] or "–",
                               w[spec["schaden"].format(i=i)] or "–"))
        if zeilen:
            st.write(f"**{titel}**")
            st.dataframe(pd.DataFrame(zeilen, columns=[spec["titel"], "Probe", "Reichweite", "Schaden"]),
                         hide_index=True)

    skills = [(w["skill1"], w["skill_1_kosten"]), (w["skill2"], w["skill_2_kosten"])]
    skills = [(text, kosten) for text, kosten in skills if text.strip()]
    if skills:
        st.write("**Skills**")
        st.dataframe(pd.DataFrame(skills, columns=["Skill", "Kosten"]), hide_index=True)

    items = [(w[f"itemmenge {i}"], w[f"item {i}"]) for i in range(1, CC_ANZAHL_ITEMS + 1)
             if w[f"item {i}"].strip()]
    if items:
        st.write("**Inventar**")
        st.dataframe(pd.DataFrame(items, columns=["Menge", "Gegenstand"]), hide_index=True)

    with st.expander("Beschreibung"):
        for label in ("Aussehen", "Erster Eindruck", "Beruf", "Erlernte Fähigkeiten", "Hintergrund",
                      "Ziele", "Charaktereigenschaften", "Ideale", "Bindung", "Makel", "Ängste"):
            st.markdown(f"**{label}:** {w[label] or '–'}")
    st.text_area("Notizen", value=w["Notizen"], height=200, disabled=True,
                 key=f"gm_notizen_{schluessel}")


# =============================================================================
# 5. REGELWERK „MINIREGELWERK“
#    Funktionen dieses Regelwerks beginnen mit mini_.
#    Ein Bogen sieht so aus: {"regelwerk": "mini", "charakter": {...}, "attribute": {...}, ...}
# =============================================================================

# ----- 5a. Konfiguration
MINI_WUERFEL = ["W4", "W6", "W8", "W10", "W12"]
MINI_ATTRIBUTE = ["Erscheinung", "Charisma", "Manipulation", "Intelligenz",
                  "Weisheit", "Wahrnehmung", "Stärke", "Geschicklichkeit", "Konstitution"]
MINI_ANZAHL_TALENTE = 3
MINI_MAX_HISTORIE = 20

MINI_CSS = """
<style>
/* Der kleine Bogen bleibt schmal, auch wenn die App breit ist */
div[data-testid="stMainBlockContainer"] {
    max-width: 900px;
    margin: 0 auto;
}
div[data-testid="stHorizontalBlock"] {
    flex-wrap: nowrap !important;
}
div[data-testid="stColumn"] {
    min-width: 0 !important;
}
/* Übergabefeld für das Zeichenfeld: unsichtbar, aber im Dokument vorhanden.
   position: fixed verhindert, dass die Seite beim Fokussieren des Feldes springt. */
.st-key-portrait_transport {
    position: fixed;
    top: 0;
    left: 0;
    width: 1px;
    height: 1px;
    opacity: 0;
    overflow: hidden;
    pointer-events: none;
}
.st-key-hp_button button,
.st-key-hist_button button,
[class*="st-key-wurf_"] button {
    padding: 0.1rem 0.6rem;
    min-height: 0;
    font-size: 0.85rem;
}
</style>
"""


# ----- 5b. Portrait-Zeichenfeld (wird von beiden Regelwerken benutzt)
# Das Zeichenfeld ist eine normale HTML-Seite (st.iframe / components.html) und braucht keine eigene
# Streamlit-Komponente, läuft also auch dort, wo keine Komponenten ausgeliefert werden
# (z. B. stlite-Playground). Das Bild kommt über ein verstecktes Textfeld zu Python zurück:
# JavaScript schreibt "img|<PNG>" bzw. "clear|" in das Textfeld im Container mit dem Key __KEY__
# (Miniregelwerk: "portrait_transport", Standard: "cc_portrait_box").
PORTRAIT_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  :root {
    --text: #31333F;
    --primary: #FF4B4B;
    --border: rgba(49, 51, 63, 0.2);
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: "Source Sans Pro", "Source Sans", sans-serif;
    font-size: 16px;
    color: var(--text);
    background: transparent;
  }
  #wrap { padding: 2px; }

  /* Werkzeugleiste im Look der Streamlit-Widgets */
  .toolbar {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: 0.75rem 1rem;
    margin-bottom: 0.75rem;
  }
  .feld { display: flex; flex-direction: column; gap: 0.25rem; }
  .feld > span { font-size: 14px; }
  .btns { display: flex; flex-wrap: wrap; gap: 0.5rem; }

  input[type=color] {
    width: 2.5rem;
    height: 2.5rem;
    padding: 3px;
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    background: transparent;
    cursor: pointer;
  }
  input[type=color]:hover { border-color: var(--primary); }
  input[type=range] {
    width: 140px;
    height: 2.5rem;
    margin: 0;
    accent-color: var(--primary);
    cursor: pointer;
  }

  button {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    height: 2.5rem;
    padding: 0 0.75rem;
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    background: transparent;
    color: inherit;
    font: inherit;
    cursor: pointer;
    transition: border-color 0.15s, color 0.15s, background 0.15s;
  }
  button:hover { border-color: var(--primary); color: var(--primary); }
  button:active { background: var(--primary); border-color: var(--primary); color: #fff; }
  button.aktiv { border-color: var(--primary); color: var(--primary); }
  button:focus-visible {
    outline: 2px solid color-mix(in srgb, var(--primary) 50%, transparent);
    outline-offset: 1px;
  }
  button svg {
    width: 16px;
    height: 16px;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }

  /* Zeichenfläche */
  canvas {
    display: block;
    max-width: 100%;
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    background: #fff;
    touch-action: none;
    cursor: crosshair;
  }
</style>
</head>
<body>
<div id="wrap">
  <div class="toolbar">
    <label class="feld"><span>Farbe</span>
      <input type="color" id="farbe" value="#000000">
    </label>
    <label class="feld"><span>Strichstärke</span>
      <input type="range" id="breite" min="1" max="20" value="3">
    </label>
    <div class="btns">
      <button id="stift" type="button" class="aktiv">
        <svg viewBox="0 0 24 24"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>
        Stift
      </button>
      <button id="radierer" type="button">
        <svg viewBox="0 0 24 24"><path d="m7 21-4.3-4.3c-1-1-1-2.5 0-3.4l9.6-9.6c1-1 2.5-1 3.4 0l5.6 5.6c1 1 1 2.5 0 3.4L13 21"/><path d="M22 21H7"/><path d="m5 11 9 9"/></svg>
        Radierer
      </button>
      <button id="undo" type="button">
        <svg viewBox="0 0 24 24"><path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5a5.5 5.5 0 0 1-5.5 5.5H11"/></svg>
        Zurück
      </button>
      <button id="clear" type="button">
        <svg viewBox="0 0 24 24"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>
        Leeren
      </button>
      <button id="save" type="button">
        <svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/></svg>
        PNG
      </button>
    </div>
  </div>
  <canvas id="c" width="300" height="380"></canvas>
</div>

<script>
const START = __START__;
const KEY = __KEY__;
let radierer = false;

// --- Rückgabe an Python: schreibt in das versteckte Textfeld der App ---
function sende(wert) {
  try {
    const p = window.parent;
    const el = p.document.querySelector('.st-key-' + KEY + ' textarea');
    if (!el) return;

    // Scroll-Positionen merken (Seite und Streamlit-Hauptbereich)
    const haupt = p.document.querySelector('section.main, [data-testid="stMain"]');
    const scrollY = p.scrollY;
    const hauptY = haupt ? haupt.scrollTop : 0;

    const setter = Object.getOwnPropertyDescriptor(p.HTMLTextAreaElement.prototype, 'value').set;
    el.focus({ preventScroll: true });
    setter.call(el, wert);
    el.dispatchEvent(new p.Event('input', { bubbles: true }));
    el.blur();  // Streamlit übernimmt den Wert beim Verlassen des Feldes

    // Falls der Browser trotzdem gescrollt hat: zurücksetzen
    p.scrollTo(0, scrollY);
    if (haupt) haupt.scrollTop = hauptY;
  } catch (err) {
    console.error('Portrait konnte nicht übertragen werden', err);
  }
}

// --- Farben und Schrift der App übernehmen ---
function uebernehmeTheme() {
  try {
    const p = window.parent;
    const app = p.document.querySelector('.stApp') || p.document.body;
    const stil = p.getComputedStyle(app);
    const root = document.documentElement.style;
    if (stil.color) {
      root.setProperty('--text', stil.color);
      root.setProperty('--border', 'color-mix(in srgb, ' + stil.color + ' 20%, transparent)');
    }
    if (stil.fontFamily) document.body.style.fontFamily = stil.fontFamily;
    const primaer = p.document.querySelector('[data-testid="stBaseButton-primary"]');
    if (primaer) {
      const farbe = p.getComputedStyle(primaer).backgroundColor;
      if (farbe) root.setProperty('--primary', farbe);
    }
  } catch (err) { /* Standardfarben bleiben */ }
}
uebernehmeTheme();

// --- Canvas ---
const c = document.getElementById('c');
const ctx = c.getContext('2d');
const farbe = document.getElementById('farbe');
const breite = document.getElementById('breite');
const verlauf = [];
let zeichnet = false;

function weiss() {
  ctx.fillStyle = '#fff';
  ctx.fillRect(0, 0, c.width, c.height);
}
weiss();
ctx.lineCap = 'round';
ctx.lineJoin = 'round';

if (START) {
  const img = new Image();
  img.onload = () => { weiss(); ctx.drawImage(img, 0, 0, c.width, c.height); };
  img.src = START;
}

function pos(e) {
  const r = c.getBoundingClientRect();
  return [(e.clientX - r.left) * c.width / r.width,
          (e.clientY - r.top) * c.height / r.height];
}
function schritt() {
  verlauf.push(ctx.getImageData(0, 0, c.width, c.height));
  if (verlauf.length > 20) verlauf.shift();
}

c.addEventListener('pointerdown', e => {
  schritt();
  zeichnet = true;
  ctx.strokeStyle = radierer ? '#ffffff' : farbe.value;
  ctx.lineWidth = radierer ? breite.value * 3 : breite.value;
  const [x, y] = pos(e);
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(x + 0.01, y);
  ctx.stroke();
  c.setPointerCapture(e.pointerId);
});
c.addEventListener('pointermove', e => {
  if (!zeichnet) return;
  const [x, y] = pos(e);
  ctx.lineTo(x, y);
  ctx.stroke();
});
c.addEventListener('pointerup', () => {
  if (!zeichnet) return;
  zeichnet = false;
  sende('img|' + c.toDataURL('image/png'));
});

// --- Werkzeug: Stift oder Radierer ---
const btnStift = document.getElementById('stift');
const btnRadierer = document.getElementById('radierer');
function werkzeug(r) {
  radierer = r;
  btnStift.classList.toggle('aktiv', !r);
  btnRadierer.classList.toggle('aktiv', r);
  c.style.cursor = r ? 'cell' : 'crosshair';
}
btnStift.onclick = () => werkzeug(false);
btnRadierer.onclick = () => werkzeug(true);
farbe.addEventListener('input', () => werkzeug(false));  // Farbwahl schaltet zurück auf Stift

document.getElementById('undo').onclick = () => {
  const s = verlauf.pop();
  if (s) {
    ctx.putImageData(s, 0, 0);
    sende('img|' + c.toDataURL('image/png'));
  }
};
document.getElementById('clear').onclick = () => {
  schritt();
  weiss();
  sende('clear|');
};
document.getElementById('save').onclick = () => {
  const a = document.createElement('a');
  a.href = c.toDataURL('image/png');
  a.download = 'charakterportrait.png';
  a.click();
};
</script>
</body>
</html>
"""


def portrait_html(start, key="portrait_transport"):
    """Die Zeichenfläche als HTML; 'start' ist ein vorhandenes Bild (PNG-Data-URL) oder None.
    'key' ist der Container-Key des versteckten Übergabefelds."""
    start_js = json.dumps(start or "").replace("</", "<\\/")
    return (PORTRAIT_HTML.replace("__START__", start_js)
            .replace("__KEY__", json.dumps(key)))


def mini_bild_hochladen():
    """Alternative zum Zeichnen: ein Bild hochladen (wird auf die Zeichenfläche gesetzt)."""
    datei = st.session_state.get("mini_portrait_upload")
    if datei is None:
        return
    try:
        from PIL import Image
        bild = Image.open(io.BytesIO(datei.getvalue())).convert("RGB")
        bild.thumbnail((300, 380))
        flaeche = Image.new("RGB", (300, 380), "white")
        flaeche.paste(bild, ((300 - bild.width) // 2, (380 - bild.height) // 2))
        puffer = io.BytesIO()
        flaeche.save(puffer, format="PNG")
    except Exception:
        st.toast("Das Bild konnte nicht gelesen werden.", icon="⚠️")
        return
    daten = PNG_PREFIX + base64.b64encode(puffer.getvalue()).decode("ascii")
    st.session_state["portrait_data"] = daten
    st.session_state["portrait_start"] = daten
    st.session_state["portrait_version"] += 1
    st.session_state["mini_portrait_transport"] = ""


# ----- 5c. Daten <-> Session-State
def mini_leer():
    return {
        "regelwerk": MINI,
        "charakter": {"setting": "", "name": "", "alter": None, "aussehen": ""},
        "portrait": None,
        "attribute": {a: "W4" for a in MINI_ATTRIBUTE},
        "hp": mini_hp_normalisieren({}),
        "mana": {"name": "", "prozent": 100},
        "talente": [],
        "inventar": "",
        "notizen": "",
    }


def mini_wuerfel_ok(wert):
    return wert if wert in MINI_WUERFEL else None


def mini_bereit():
    """Startwerte (nur beim ersten Aufruf)."""
    st.session_state.setdefault("mini_historie", [])
    st.session_state.setdefault("portrait_data", None)
    st.session_state.setdefault("portrait_start", None)
    st.session_state.setdefault("portrait_version", 0)
    st.session_state.setdefault("mana_wert", 100)
    if "mini_hp_speicher" not in st.session_state:
        mini_hp_in_session({})
    for a in MINI_ATTRIBUTE:
        st.session_state.setdefault(f"attr_{a}", "W4")


def mini_in_session(daten):
    """Schreibt einen Bogen (aus Datenbank oder JSON-Datei) in die Eingabefelder."""
    mini_bereit()

    # Charakter
    char = daten.get("charakter", {})
    setting = char.get("setting", "")
    st.session_state["mini_setting"] = setting if isinstance(setting, str) else ""
    st.session_state["mini_name"] = char.get("name", "")
    alter = char.get("alter")
    st.session_state["mini_alter"] = alter if isinstance(alter, int) else None
    aussehen = char.get("aussehen", "")
    st.session_state["mini_aussehen"] = aussehen if isinstance(aussehen, str) else ""

    # Portrait: "portrait_start" ist das Bild, mit dem die Zeichenfläche (neu) beginnt
    portrait = daten.get("portrait")
    portrait = portrait if isinstance(portrait, str) and portrait.startswith(PNG_PREFIX) else None
    st.session_state["portrait_data"] = portrait
    st.session_state["portrait_start"] = portrait
    st.session_state["portrait_version"] += 1
    st.session_state["mini_portrait_transport"] = ""

    # Attribute
    attr = daten.get("attribute", {})
    for a in MINI_ATTRIBUTE:
        st.session_state[f"attr_{a}"] = mini_wuerfel_ok(attr.get(a))

    # HP (drei Modi)
    mini_hp_in_session(daten.get("hp", {}))

    # Mana / Ressource
    mana = daten.get("mana", {})
    st.session_state["mana_name"] = mana.get("name", "")
    prozent = mana.get("prozent")
    st.session_state["mana_wert"] = (
        max(0, min(prozent, 100)) if isinstance(prozent, int) else 100
    )

    # Talente
    talente = daten.get("talente", [])
    for i in range(MINI_ANZAHL_TALENTE):
        eintrag = talente[i] if i < len(talente) and isinstance(talente[i], dict) else {}
        st.session_state[f"talent_name_{i}"] = eintrag.get("name", "")
        st.session_state[f"talent_wuerfel_{i}"] = mini_wuerfel_ok(eintrag.get("wuerfel"))

    # Inventar und Spielernotizen (Freitext)
    for feld, key in (("inventar", "inventar_text"), ("notizen", "notizen_text")):
        text = daten.get(feld, "")
        st.session_state[key] = text if isinstance(text, str) else ""


# ----- 5d. Callbacks (Würfel, HP)
def mini_in_historie(name, wuerfel, ergebnis):
    historie = st.session_state["mini_historie"]
    historie.append({
        "zeit": datetime.now().strftime("%H:%M:%S"),
        "name": name,
        "wuerfel": wuerfel,
        "ergebnis": ergebnis,
    })
    del historie[:-MINI_MAX_HISTORIE]


def mini_wuerfeln(name, wuerfel):
    ergebnis = random.randint(1, int(wuerfel[1:]))
    mini_in_historie(name, wuerfel, ergebnis)
    st.toast(f"{name} ({wuerfel}): {ergebnis}", icon="🎲")


def mini_historie_leeren():
    st.session_state["mini_historie"] = []


def mini_hp_wuerfeln():
    wuerfel = st.session_state.get("attr_Konstitution")
    if wuerfel is None:
        return
    seiten = int(wuerfel[1:])                  # "W8" -> 8
    stufe = MINI_WUERFEL.index(wuerfel) + 1    # W4 = 1, W6 = 2, ... W12 = 5
    wurf = random.randint(1, seiten)
    maximum = wurf + stufe
    st.session_state["hp_max"] = maximum
    st.session_state["hp_aktuell"] = maximum
    st.session_state["hp_info"] = f"{wuerfel}: gewürfelt {wurf} + Stufe {stufe}"
    mini_in_historie("HP-Maximum", wuerfel, wurf)


def mini_hp_zuruecksetzen():
    st.session_state["hp_max"] = None
    st.session_state.pop("hp_aktuell", None)
    st.session_state.pop("hp_info", None)


# ----- 5e. Lebenspunkte (drei Modi, per st.pills wählbar)
#   zufall   Maximum wird mit dem Konstitutions-Würfel ausgewürfelt, aktuelle HP per Slider
#   fest     festes Maximum, aktuelle LP über ein +/- Feld verrechnen (gedeckelt am Maximum)
#   treffer  Trefferpunkte als Kästchen: angekreuzt = noch vorhanden
# Gespeichert wird alles im Bogen unter "hp":
#   {"modus": ..., "zufall": {...}, "fest": {...}, "treffer": {...}}  – jeder Modus behält
#   seine Werte, auch wenn man zwischendurch den Modus wechselt.
MINI_HP_MODI = ["zufall", "fest", "treffer"]
MINI_HP_NAMEN = {"zufall": "Zufällige Lebenspunkte", "fest": "Feste Lebenspunkte",
                 "treffer": "Trefferpunkte"}
MINI_TREFFER_MAX = 30
MINI_TREFFER_STANDARD = 10
MINI_FEST_STANDARD = 100


def mini_zahl(wert, standard=None):
    """Ganze Zahl (kein Wahrheitswert) oder der Standardwert."""
    return wert if isinstance(wert, int) and not isinstance(wert, bool) else standard


def mini_hp_normalisieren(hp):
    """Bringt hp-Daten in die aktuelle Form (ältere Bögen kennen nur 'maximum'/'aktuell',
    das entspricht den zufälligen Lebenspunkten)."""
    hp = hp if isinstance(hp, dict) else {}
    modus = hp.get("modus") if hp.get("modus") in MINI_HP_MODI else "zufall"

    zufall = hp.get("zufall") if isinstance(hp.get("zufall"), dict) else hp
    z_max = mini_zahl(zufall.get("maximum"))
    z_aktuell = None
    if z_max is not None:
        z_aktuell = max(0, min(mini_zahl(zufall.get("aktuell"), z_max), z_max))
    z_info = zufall.get("info") if isinstance(zufall.get("info"), str) else ""

    fest = hp.get("fest") if isinstance(hp.get("fest"), dict) else {}
    f_max = max(1, mini_zahl(fest.get("maximum"), MINI_FEST_STANDARD))
    f_aktuell = max(0, min(mini_zahl(fest.get("aktuell"), f_max), f_max))

    treffer = hp.get("treffer") if isinstance(hp.get("treffer"), dict) else {}
    t_max = max(1, min(mini_zahl(treffer.get("maximum"), MINI_TREFFER_STANDARD), MINI_TREFFER_MAX))
    markiert = treffer.get("uebrig") if isinstance(treffer.get("uebrig"), list) else []
    t_uebrig = [bool(markiert[i]) if i < len(markiert) else True for i in range(t_max)]

    return {
        "modus": modus,
        "zufall": {"maximum": z_max, "aktuell": z_aktuell, "info": z_info if z_max is not None else ""},
        "fest": {"maximum": f_max, "aktuell": f_aktuell},
        "treffer": {"maximum": t_max, "uebrig": t_uebrig},
    }


def mini_hp_in_session(hp):
    """Merkt sich die Lebenspunkte eines Bogens; die Felder werden beim Zeichnen geladen."""
    hp = mini_hp_normalisieren(hp)
    st.session_state["mini_hp_speicher"] = hp
    st.session_state["mini_hp_modus"] = hp["modus"]
    st.session_state["mini_hp_modus_merk"] = hp["modus"]
    st.session_state.pop("mini_hp_zuletzt", None)  # -> Felder neu laden


def mini_hp_felder_laden(modus, daten):
    """Schreibt die gespeicherten Werte eines Modus in seine Eingabefelder. Das passiert bei
    jedem Betreten des Modus, denn Streamlit verwirft die Felder nicht angezeigter Modi
    (oder behält veraltete Werte)."""
    if modus == "zufall":
        st.session_state["hp_max"] = daten["maximum"]
        if daten["maximum"] is not None:
            st.session_state["hp_aktuell"] = daten["aktuell"]
            st.session_state["hp_info"] = daten["info"] or "aus Datei geladen"
        else:
            st.session_state.pop("hp_aktuell", None)
            st.session_state.pop("hp_info", None)
    elif modus == "fest":
        st.session_state["hp_fest_max"] = daten["maximum"]
        st.session_state["hp_fest_max_alt"] = daten["maximum"]
        st.session_state["hp_fest_aktuell"] = daten["aktuell"]
    else:
        st.session_state["hp_treffer_max"] = daten["maximum"]
        for i in range(MINI_TREFFER_MAX):
            if i < daten["maximum"]:
                st.session_state[f"hp_treffer_{i}"] = daten["uebrig"][i]
            else:
                st.session_state.pop(f"hp_treffer_{i}", None)


# --- Callbacks
def mini_hp_modus_geaendert():
    """Die Auswahl in st.pills lässt sich abwählen – das nehmen wir zurück."""
    neu = st.session_state.get("mini_hp_modus")
    if neu is None:
        st.session_state["mini_hp_modus"] = st.session_state.get("mini_hp_modus_merk", "zufall")
    else:
        st.session_state["mini_hp_modus_merk"] = neu


def mini_hp_fest_max_geaendert():
    """Steigt das Maximum, steigen die aktuellen LP um denselben Betrag; sinkt es, wird gedeckelt."""
    neu = st.session_state["hp_fest_max"]
    delta = neu - st.session_state["hp_fest_max_alt"]
    aktuell = st.session_state["hp_fest_aktuell"] + max(delta, 0)
    st.session_state["hp_fest_aktuell"] = max(0, min(aktuell, neu))


def mini_hp_fest_rechnen():
    """Rechnet die Eingabe auf die aktuellen LP, z. B. '+5', '-3' oder '10-3+2'."""
    eingabe = st.session_state["hp_fest_eingabe"].replace(" ", "")
    st.session_state["hp_fest_eingabe"] = ""
    if not eingabe:
        return
    if not re.fullmatch(r"[+-]?\d+([+-]\d+)*", eingabe):
        st.toast("Bitte eine gültige Rechnung eingeben (z.B. +5, -3, 10-3)", icon="⚠️")
        return
    summe = sum(int(zahl) for zahl in re.findall(r"[+-]?\d+", eingabe))
    maximum = st.session_state["hp_fest_max"]
    st.session_state["hp_fest_aktuell"] = max(0, min(st.session_state["hp_fest_aktuell"] + summe, maximum))


# --- Die drei Modi
def mini_hp_zufall(daten):
    """Zufällige Lebenspunkte: Würfel aus Konstitution, aktuelle HP per Slider."""
    hp_max = st.session_state["hp_max"]
    konstitution = st.session_state.get("attr_Konstitution")

    with st.container(key="hp_button"):
        c1, c2, _ = st.columns([1, 1, 1], vertical_alignment="center")
        with c1:
            st.button(
                "🎲 HP würfeln",
                on_click=mini_hp_wuerfeln,
                disabled=konstitution is None or hp_max is not None,
            )
        if hp_max is None:
          st.info("steigere erst noch deine Konstitution")
        with c2:
            if hp_max is not None:
                st.button("↺ Zurücksetzen", on_click=mini_hp_zuruecksetzen)

    if konstitution is None and hp_max is None:
        st.caption("Wähle zuerst einen Würfel für Konstitution.")

    if hp_max is None:
        return {"maximum": None, "aktuell": None, "info": ""}
    info = st.session_state.get("hp_info", "")
    st.caption(info + f" = {hp_max} HP maximal")
    aktuell = st.slider("Aktuelle HP", min_value=0, max_value=hp_max, key="hp_aktuell")
    return {"maximum": hp_max, "aktuell": aktuell, "info": info}


def mini_hp_fest(daten):
    """Feste Lebenspunkte: Maximum festlegen, aktuelle LP mit +/- verrechnen."""
    # Vorheriges Maximum merken (der Callback braucht die Differenz) und LP im Rahmen halten
    st.session_state["hp_fest_max_alt"] = st.session_state["hp_fest_max"]
    st.session_state["hp_fest_aktuell"] = max(
        0, min(st.session_state["hp_fest_aktuell"], st.session_state["hp_fest_max"]))

    maximum = st.number_input("Maximale Lebenspunkte", min_value=1, step=1, key="hp_fest_max",
                              on_change=mini_hp_fest_max_geaendert)
    aktuell = st.session_state["hp_fest_aktuell"]
    st.markdown(f"### {aktuell} / {maximum}")
    st.progress(aktuell / maximum)
    st.text_input("LP ändern", key="hp_fest_eingabe", on_change=mini_hp_fest_rechnen,
                  placeholder="LP ändern: +5 / -3", label_visibility="collapsed")
    return {"maximum": maximum, "aktuell": aktuell}


def mini_hp_treffer(daten):
    """Trefferpunkte: Anzahl festlegen, Kästchen ankreuzen (angekreuzt = noch vorhanden)."""
    maximum = st.number_input("Trefferpunkte (Maximum)", min_value=1, max_value=MINI_TREFFER_MAX,
                              step=1, key="hp_treffer_max")
    for i in range(maximum):  # neue Kästchen starten angekreuzt
        st.session_state.setdefault(
            f"hp_treffer_{i}", daten["uebrig"][i] if i < len(daten["uebrig"]) else True)

    uebrig = []
    for start in range(0, maximum, 10):
        spalten = st.columns(10)
        for i in range(start, min(start + 10, maximum)):
            with spalten[i - start]:
                uebrig.append(st.checkbox(str(i + 1), key=f"hp_treffer_{i}"))
    st.caption(f"Übrig: {sum(uebrig)} / {maximum}")
    return {"maximum": maximum, "uebrig": uebrig}


def mini_hp_bereich():
    """Der HP-Abschnitt mit Moduswahl. Gibt das hp-Dictionary für den Bogen zurück."""
    st.header("HP")
    speicher = st.session_state["mini_hp_speicher"]

    st.pills("Art der Lebenspunkte", MINI_HP_MODI, key="mini_hp_modus",
             format_func=MINI_HP_NAMEN.get, on_change=mini_hp_modus_geaendert,
             label_visibility="collapsed")
    modus = st.session_state.get("mini_hp_modus") or st.session_state.get("mini_hp_modus_merk", "zufall")

    if st.session_state.get("mini_hp_zuletzt") != modus:  # Modus gerade betreten
        mini_hp_felder_laden(modus, speicher[modus])
    st.session_state["mini_hp_zuletzt"] = modus

    darstellung = {"zufall": mini_hp_zufall, "fest": mini_hp_fest, "treffer": mini_hp_treffer}
    neu = darstellung[modus](speicher[modus])

    # Die anderen Modi behalten ihre zuletzt gespeicherten Werte
    speicher = copy.deepcopy(speicher)
    speicher["modus"] = modus
    speicher[modus] = neu
    st.session_state["mini_hp_speicher"] = speicher
    return copy.deepcopy(speicher)


# ----- 5f. Der Bogen als Ganzes
def mini_formular():
    """Zeichnet den Bogen und gibt ihn als Dictionary zurück."""
    # --- Setting (Titel des One Shots) und Charakter ---
    setting = st.text_input(
        "Setting", key="mini_setting", placeholder="Setting (Titel des One Shots)",
        label_visibility="collapsed",
    )
    links, rechts = st.columns([3, 1], vertical_alignment="center")
    with links:
        name = st.text_input(
            "Name", key="mini_name", placeholder="Name", label_visibility="collapsed"
        )
    with rechts:
        alter = st.number_input(
            "Alter", min_value=0, max_value=999, step=1, value=None,
            key="mini_alter", placeholder="Alter", label_visibility="collapsed",
        )
    aussehen = st.text_input(
        "Aussehen", key="mini_aussehen", placeholder="Aussehen", label_visibility="collapsed"
    )

    # --- Charakterportrait (Canvas) ---
    with st.expander("Charakterportrait", expanded=True):
        # <!-- Version --> sorgt dafür, dass die Fläche beim Laden eines Bogens neu aufgebaut wird
        html_einbetten(
            f"<!-- v{st.session_state['portrait_version']} -->"
            + portrait_html(st.session_state["portrait_start"]),
            500,
        )
        st.file_uploader("Oder ein Bild hochladen", type=["png", "jpg", "jpeg"],
                         key="mini_portrait_upload", on_change=mini_bild_hochladen)

    # Verstecktes Übergabefeld: das Zeichenfeld schreibt hier hinein
    with st.container(key="portrait_transport"):
        uebergabe = st.text_area("Portrait-Übergabe", key="mini_portrait_transport",
                                 label_visibility="collapsed")
    if uebergabe.startswith("img|"):
        st.session_state["portrait_data"] = uebergabe[len("img|"):]
    elif uebergabe == "clear|":
        st.session_state["portrait_data"] = None
    portrait_data = st.session_state["portrait_data"]

    st.divider()

    # --- HP (drei Modi) ---
    hp = mini_hp_bereich()

    st.divider()

    # --- Mana / Ressource ---
    st.header("Ressource")

    links, rechts = st.columns([1, 2], vertical_alignment="center")
    with links:
        mana_name = st.text_input(
            "Name der Ressource", key="mana_name", placeholder="z. B. Mana",
            label_visibility="collapsed",
        )
    with rechts:
        mana_wert = st.slider(
            mana_name or "Ressource", min_value=0, max_value=100, key="mana_wert",
            format="%d%%", label_visibility="collapsed",
        )

    st.divider()

    # --- Attribute ---
    st.header("Attribute")

    attribute_werte = {}

    for i, attribut in enumerate(MINI_ATTRIBUTE):
        links, mitte, rechts = st.columns([2, 5, 1], vertical_alignment="center")
        with links:
            st.write(attribut)
        with mitte:
            attribute_werte[attribut] = st.segmented_control(
                attribut, options=MINI_WUERFEL, key=f"attr_{attribut}",
                label_visibility="collapsed",
            )
        with rechts:
            st.button(
                "🎲",
                key=f"wurf_attr_{i}",
                on_click=mini_wuerfeln,
                args=(attribut, attribute_werte[attribut]),
                disabled=attribute_werte[attribut] is None,
            )

    # --- Talente ---
    st.header("Talente")

    talente_werte = []

    for i in range(MINI_ANZAHL_TALENTE):
        links, mitte, rechts = st.columns([2, 5, 1], vertical_alignment="center")
        with links:
            talent_name = st.text_input(
                f"Name {i + 1}", key=f"talent_name_{i}", placeholder="Talent",
                label_visibility="collapsed",
            )
        with mitte:
            wuerfel = st.segmented_control(
                f"Würfel {i + 1}", options=MINI_WUERFEL, key=f"talent_wuerfel_{i}",
                label_visibility="collapsed",
            )
        with rechts:
            st.button(
                "🎲",
                key=f"wurf_talent_{i}",
                on_click=mini_wuerfeln,
                args=(talent_name or f"Talent {i + 1}", wuerfel),
                disabled=wuerfel is None,
            )
        talente_werte.append({"name": talent_name, "wuerfel": wuerfel})

    # --- Würfelhistorie ---
    st.header("Würfelhistorie")

    historie = st.session_state["mini_historie"]
    with st.container(height=150, border=True):
        if not historie:
            st.caption("Noch nicht gewürfelt.")
        for eintrag in reversed(historie):
            st.write(
                f"`{eintrag.get('zeit', '--:--:--')}` · "
                f"**{eintrag['ergebnis']}** · {eintrag['name']} ({eintrag['wuerfel']})"
            )

    with st.container(key="hist_button"):
        st.button("Historie leeren", on_click=mini_historie_leeren, disabled=not historie)
        
    # --- Inventar ---
    st.header("Inventar")
    inventar = st.text_area(
        "Inventar", key="inventar_text", height=150,
        placeholder="Gegenstände, Ausrüstung, Geld …", label_visibility="collapsed",
    )

    # --- Spielernotizen ---
    st.header("Spielernotizen")
    notizen = st.text_area(
        "Spielernotizen", key="notizen_text", height=200,
        placeholder="Hintergrund, Ziele, Notizen zur Runde …", label_visibility="collapsed",
    )

    return {
        "regelwerk": MINI,
        "charakter": {
            "setting": setting.strip(),
            "name": name.strip(),
            "alter": alter,
            "aussehen": aussehen,
        },
        "portrait": portrait_data,
        "attribute": attribute_werte,
        "hp": hp,
        "mana": {"name": mana_name, "prozent": mana_wert},
        "talente": talente_werte,
        "inventar": inventar,
        "notizen": notizen,
    }


# ----- 5g. Ansicht für den Spielleiter (nur lesen)
def mini_gm_ansicht(bogen, schluessel):
    char = bogen.get("charakter", {})
    hp = mini_hp_normalisieren(bogen.get("hp", {}))
    mana = bogen.get("mana", {})
    attribute = bogen.get("attribute", {})
    talente = [t for t in bogen.get("talente", []) if t.get("name")]

    a, b = st.columns(2)
    with a:
        alter = char.get("alter")
        st.markdown(f"**{char.get('name', '')}** · Alter: {alter if alter is not None else '–'}")
        st.caption(f"Setting: {char.get('setting') or '–'}")
        st.write(char.get("aussehen") or "–")
        modus = hp["modus"]
        daten = hp[modus]
        if modus == "treffer":
            wert = f"{sum(daten['uebrig'])} / {daten['maximum']}"
        elif daten["maximum"] is not None:
            wert = f"{daten['aktuell']} / {daten['maximum']}"
        else:
            wert = "–"
        st.metric(MINI_HP_NAMEN[modus], wert)
        st.metric(mana.get("name") or "Ressource", f"{mana.get('prozent', 100)} %")
        bild = portrait_zu_bytes(bogen.get("portrait"))
        if bild:
            st.image(bild)
    with b:
        st.write("**Attribute**")
        st.dataframe(
            pd.DataFrame([(n, w or "–") for n, w in attribute.items()],
                         columns=["Attribut", "Würfel"]),
            hide_index=True,
        )
        st.write("**Talente**")
        if talente:
            st.dataframe(
                pd.DataFrame([(t["name"], t.get("wuerfel") or "–") for t in talente],
                             columns=["Talent", "Würfel"]),
                hide_index=True,
            )
        else:
            st.write("–")

    st.text_area("Inventar", value=bogen.get("inventar") or "", height=150,
                 disabled=True, key=f"gm_inventar_{schluessel}")
    st.text_area("Spielernotizen", value=bogen.get("notizen") or "", height=200,
                 disabled=True, key=f"gm_notizen_{schluessel}")


# =============================================================================
# 6. REGELWERK-REGISTER
#    Hier steht, was jedes Regelwerk dem Rest der App bereitstellt.
#    Ein neues Regelwerk braucht genau diese Bausteine:
#      name        Anzeigename
#      leer        () -> leerer Bogen (Dictionary mit "regelwerk": <Kürzel>)
#      in_session  (bogen) -> schreibt den Bogen in die Eingabefelder
#      bereit      () -> Startwerte; läuft bei jedem Durchlauf vor dem Bogen
#      formular    () -> zeichnet den Bogen und gibt ihn als Dictionary zurück
#      gm_ansicht  (bogen, schluessel) -> Nur-Lesen-Ansicht für den Spielleiter
#      sidebar     Optional: Werkzeuge in der Sidebar (z. B. Würfel)
#      css         Optional: zusätzliches CSS für die Seite
#      portrait_png  Optional: (bogen) -> PNG-Bytes für den Portrait-Download
# =============================================================================
REGELWERKE = {
    STANDARD: {
        "name": "Standard (Coffeecrawler)",
        "leer": cc_leer,
        "in_session": cc_in_session,
        "bereit": cc_bereit,
        "formular": cc_formular,
        "gm_ansicht": cc_gm_ansicht,
        "sidebar": cc_sidebar,
        "css": CC_CSS,
        "portrait_png": None,
    },
    MINI: {
        "name": "Miniregelwerk",
        "leer": mini_leer,
        "in_session": mini_in_session,
        "bereit": mini_bereit,
        "formular": mini_formular,
        "gm_ansicht": mini_gm_ansicht,
        "sidebar": None,
        "css": MINI_CSS,
        "portrait_png": lambda bogen: portrait_zu_bytes(bogen.get("portrait")),
    },
}


def regelwerk_modul(bogen):
    """Das Regelwerk-Modul zu einem Bogen (unbekannte Kürzel fallen auf das Miniregelwerk zurück)."""
    return REGELWERKE.get(regelwerk_von(bogen), REGELWERKE[MINI])


# =============================================================================
# 7. SPIELER-BEREICH (arbeitet mit jedem Regelwerk über das Register oben)
# =============================================================================

# ----- 7a. Entwurf: Zwischenspeicher des Bogens
# Der Bogen, an dem gerade gearbeitet wird, liegt als "Entwurf" in st.session_state["entwurf"]
# und wird bei jeder Änderung zusätzlich in der Datenbank (Tabelle "entwuerfe") abgelegt.
# So gehen Eingaben weder beim Seitenwechsel noch beim Neuladen der Seite verloren.
#   Aufbau: {"besitzer": str | None, "auswahl": NEU | Charaktername, "bogen": {...}, "basis": Hash}
#   "basis" = Hash des zuletzt gespeicherten/geladenen Stands -> daran erkennt man Änderungen.
def text_hash(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def bogen_hash(bogen):
    return text_hash(json.dumps(bogen, sort_keys=True, ensure_ascii=False, default=str))


def entwurf_schluessel():
    """Unter diesem Namen liegt der Entwurf in der Datenbank (= Spielername aus der Sidebar)."""
    return st.session_state.get("spieler", "").strip() or "(ohne Name)"


def entwurf_dirty():
    """True, wenn der Entwurf Änderungen gegenüber dem gespeicherten Stand enthält."""
    e = st.session_state.get("entwurf")
    return bool(e) and e.get("basis") is not None and bogen_hash(e["bogen"]) != e["basis"]


def entwurf_setzen(besitzer, auswahl, bogen):
    """Macht einen Bogen zum aktuellen Entwurf (Eingabefelder werden beim Öffnen neu befüllt)."""
    st.session_state["entwurf"] = {
        "besitzer": besitzer, "auswahl": auswahl, "bogen": bogen, "basis": None,
    }
    st.session_state.pop("bogen_quelle", None)
    st.session_state.pop("verlassen_ziel", None)


def entwurf_verwerfen():
    """Entfernt den Entwurf komplett (Session und Datenbank)."""
    st.session_state.pop("entwurf", None)
    st.session_state.pop("bogen_quelle", None)
    st.session_state.pop("verlassen_ziel", None)
    alt = st.session_state.pop("entwurf_db", None)
    entwurf_db_loeschen(alt[0] if alt else entwurf_schluessel())


def entwurf_zwischenspeichern():
    """Schreibt den Entwurf in die Datenbank, sobald er sich geändert hat."""
    entwurf = st.session_state.get("entwurf")
    if not entwurf:
        return
    schluessel = entwurf_schluessel()
    text = json.dumps(entwurf, ensure_ascii=False)
    stand = (schluessel, text_hash(text))
    alt = st.session_state.get("entwurf_db")
    if alt == stand:
        return
    if alt and alt[0] != schluessel:  # Spielername wurde geändert
        entwurf_db_loeschen(alt[0])
    entwurf_db_speichern(schluessel, text)
    st.session_state["entwurf_db"] = stand


def entwurf_wiederherstellen():
    """Holt nach einem Neuladen der Seite den letzten Entwurf aus der Datenbank."""
    schluessel = entwurf_schluessel()
    if st.session_state.get("entwurf_geprueft") == schluessel:
        return
    st.session_state["entwurf_geprueft"] = schluessel
    if "entwurf" in st.session_state:
        return
    text = entwurf_db_laden(schluessel)
    if not text:
        return
    try:
        entwurf = json.loads(text)
    except ValueError:
        return
    if not isinstance(entwurf, dict) or "bogen" not in entwurf:
        return
    st.session_state["entwurf"] = entwurf
    st.session_state["entwurf_db"] = (schluessel, text_hash(text))
    st.session_state.setdefault("aktion", AKTION_BEARBEITEN)  # direkt zurück zum Bogen


def entwurf_in_db_speichern():
    """Speichert den Entwurf als Charakter. Gibt eine Fehlermeldung zurück oder None."""
    e = st.session_state["entwurf"]
    bogen = e["bogen"]
    name = bogen_name(bogen)
    besitzer = e["besitzer"] or st.session_state.get("spieler", "").strip()
    if not besitzer:
        return "Gib links in der Sidebar deinen Spielernamen ein, um den Charakter zu speichern."
    if not name:
        return "Bitte gib dem Charakter einen Namen."
    charakter_speichern(besitzer, name, bogen)
    e["besitzer"] = besitzer
    e["auswahl"] = name
    e["basis"] = bogen_hash(bogen)
    return None


def entwurf_zuruecksetzen():
    """Verwirft Änderungen: zurück zum gespeicherten Stand (bzw. leerer Bogen bei neuen Charakteren)."""
    e = st.session_state["entwurf"]
    bogen = None
    if e["besitzer"] and e["auswahl"] != NEU:
        bogen = charakter_laden(e["besitzer"], e["auswahl"])
    entwurf_setzen(e["besitzer"], e["auswahl"], bogen or regelwerk_modul(e["bogen"])["leer"]())


def charakter_neu_starten(regelwerk):
    entwurf_setzen(None, NEU, REGELWERKE[regelwerk]["leer"]())
    st.session_state["springe_nach"] = AKTION_BEARBEITEN
    st.rerun()


def charakter_oeffnen(besitzer, name):
    bogen = charakter_laden(besitzer, name) or REGELWERKE[MINI]["leer"]()
    entwurf_setzen(besitzer, name, bogen)
    st.session_state["springe_nach"] = AKTION_BEARBEITEN
    st.rerun()


# ----- 7b. JSON-Import (für beide Regelwerke, auch ältere Dateien)
def bogen_normalisieren(daten):
    """Erkennt das Regelwerk einer JSON-Datei (auch ältere Dateien ohne Angabe)."""
    if "regelwerk" in daten:
        return daten
    if "char_name" in daten or "Level" in daten:  # alter Standard-Bogen (flache Key-Liste)
        return {"regelwerk": STANDARD, "werte": daten}
    return {**daten, "regelwerk": MINI}


def json_laden():
    datei = st.session_state.get("json_upload")
    entwurf = st.session_state.get("entwurf")
    if datei is None or not entwurf:
        return
    try:
        daten = json.load(datei)
    except (json.JSONDecodeError, UnicodeDecodeError):
        st.session_state["lade_status"] = ("error", "Die Datei ist kein gültiges JSON.")
        return
    if not isinstance(daten, dict):
        st.session_state["lade_status"] = ("error", "Unerwartetes Dateiformat.")
        return

    daten = bogen_normalisieren(daten)
    ziel = regelwerk_von(entwurf["bogen"])
    if regelwerk_von(daten) != ziel:
        st.session_state["lade_status"] = (
            "error",
            f"Die Datei gehört zum Regelwerk „{regelwerk_name(regelwerk_von(daten))}“, "
            f"dieser Charakter nutzt „{regelwerk_name(ziel)}“.",
        )
        return
    REGELWERKE[ziel]["in_session"](daten)
    st.session_state["lade_status"] = ("success", "Charakterbogen geladen.")


# ----- 7c. Seiten: Neu erstellen / Laden (führen beide zum Bereich "Charakter bearbeiten")
def seite_neu(spieler):
    st.title("Neuen Charakter erstellen")
    if not spieler:
        st.info("Gib links in der Sidebar deinen Spielernamen ein, um einen neuen Charakter zu erstellen.")
        return

    st.selectbox("Regelwerk", list(REGELWERKE), format_func=regelwerk_name, key="neu_regelwerk")
    st.write("Du bekommst einen leeren Bogen und füllst ihn im Bereich "
             "„Charakter bearbeiten“ aus.")
    if st.button("➕ Neuen Charakter erstellen", type="primary"):
        if entwurf_dirty():
            st.session_state["bestaetigung"] = ("neu", "neu")
        else:
            charakter_neu_starten(st.session_state["neu_regelwerk"])
    if st.session_state.get("bestaetigung") == ("neu", "neu"):
        if bestaetigen("Der aktuelle Entwurf hat ungespeicherte Änderungen. "
                       "Wirklich verwerfen und neu beginnen?", "neu"):
            charakter_neu_starten(st.session_state["neu_regelwerk"])


def seite_laden():
    st.title("Charakter laden")
    if "meldung" in st.session_state:
        st.success(st.session_state.pop("meldung"))

    alle = alle_charaktere()
    if not alle:
        st.warning("Die Datenbank ist leer – es gibt noch keine gespeicherten Charaktere.")
        return

    labels = [f"{c['spieler']} – {c['name']}" for c in alle]
    if st.session_state.get("auswahl_db") not in labels:
        st.session_state["auswahl_db"] = labels[0]
    c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
    wahl = c1.selectbox("Charakter suchen (Tippen zum Filtern)", labels, key="auswahl_db")
    eintrag = alle[labels.index(wahl)]
    st.caption(f"Regelwerk: {regelwerk_name(eintrag['regelwerk'])} · "
               f"Setting: {eintrag['setting'] or '–'} · "
               "wird im Bereich „Charakter bearbeiten“ geöffnet")

    if c2.button("📂 Laden"):
        if entwurf_dirty():
            st.session_state["bestaetigung"] = ("laden", wahl)
        else:
            charakter_oeffnen(eintrag["spieler"], eintrag["name"])
    if st.session_state.get("bestaetigung") == ("laden", wahl):
        if bestaetigen("Der aktuelle Entwurf hat ungespeicherte Änderungen. "
                       "Wirklich ersetzen?", "laden"):
            charakter_oeffnen(eintrag["spieler"], eintrag["name"])


# ----- 7d. Seite: Charakter bearbeiten
def verlassen_ausfuehren(modus):
    """Callback der Abfrage beim Verlassen des Bereichs ('speichern', 'verlassen', 'bleiben')."""
    ziel = st.session_state.get("verlassen_ziel")
    if modus == "bleiben" or not ziel:
        st.session_state.pop("verlassen_ziel", None)
        return
    if modus == "speichern":
        fehler = entwurf_in_db_speichern()
        if fehler:
            st.session_state["verlassen_fehler"] = fehler
            return
    st.session_state.pop("verlassen_ziel", None)
    st.session_state["verlassen_frei"] = True  # die Abfrage nicht erneut auslösen
    if ziel in GM_AKTIONEN:
        st.session_state["gm_aktion"] = ziel
        st.session_state["aktion"] = None
    else:
        st.session_state["aktion"] = ziel
        st.session_state["gm_aktion"] = None


def verlassen_dialog():
    st.warning("Du hast ungespeicherte Änderungen. Vor dem Verlassen in der Datenbank speichern? "
               "(Ohne Speichern bleibt der Entwurf als Zwischenspeicher erhalten.)")
    if "verlassen_fehler" in st.session_state:
        st.error(st.session_state.pop("verlassen_fehler"))
    c1, c2, c3 = st.columns(3)
    c1.button("💾 Speichern", type="primary", on_click=verlassen_ausfuehren, args=("speichern",))
    c2.button("Ohne Speichern", on_click=verlassen_ausfuehren, args=("verlassen",))
    c3.button("Abbrechen", on_click=verlassen_ausfuehren, args=("bleiben",))


def seite_bearbeiten():
    st.title("Charakter bearbeiten")
    if "meldung" in st.session_state:
        st.success(st.session_state.pop("meldung"))

    entwurf = st.session_state.get("entwurf")
    if not entwurf:
        st.session_state.pop("bogen_quelle", None)
        st.info("Es ist noch kein Charakter in Bearbeitung. Erstelle einen neuen Charakter "
                "oder lade einen aus der Datenbank.")
        return

    if "verlassen_ziel" in st.session_state:
        verlassen_dialog()

    modul = regelwerk_modul(entwurf["bogen"])
    if modul["css"]:
        st.markdown(modul["css"], unsafe_allow_html=True)

    # Eingabefelder aus dem Entwurf befüllen (beim Öffnen und nach jedem Seitenwechsel)
    if "bogen_quelle" not in st.session_state:
        modul["in_session"](entwurf["bogen"])
        st.session_state["bogen_quelle"] = True
    modul["bereit"]()
    if modul["sidebar"]:
        modul["sidebar"]()

    kopf = st.container()           # wird unten gefüllt, steht aber über dem Bogen
    bogen = modul["formular"]()

    # Entwurf aktuell halten und Änderungen erkennen
    entwurf["bogen"] = bogen
    aktuell = bogen_hash(bogen)
    if entwurf.get("basis") is None:
        entwurf["basis"] = aktuell
    dirty = aktuell != entwurf["basis"]

    kopfzeile(kopf, modul, bogen, entwurf, dirty)


def kopfzeile(kopf, modul, bogen, entwurf, dirty):
    """Status, Speichern/Verwerfen/Löschen und Export/Import – steht über dem Bogen."""
    auswahl = entwurf["auswahl"]
    name = bogen_name(bogen)

    with kopf:
        if auswahl == NEU:
            titel, stand = "Neuer Charakter", "🟠 noch nicht in der Datenbank gespeichert"
        else:
            titel = f"{entwurf['besitzer']} – {auswahl}"
            stand = "🟠 ungespeicherte Änderungen" if dirty else "🟢 gespeichert"
        st.caption(f"**{titel}** · {modul['name']} · {stand}")

        b1, b2, b3, = st.columns([3, 3, 1], vertical_alignment="center")
        if b1.button("💾 In Datenbank speichern", type="primary"):
            if not name:
                st.error("Bitte gib dem Charakter einen Namen.")
            else:
                st.session_state["bestaetigung"] = ("speichern", auswahl)
        if dirty and b2.button("↺ Änderungen verwerfen"):
            st.session_state["bestaetigung"] = ("verwerfen", auswahl)
        if auswahl != NEU and b3.button("🗑️", help="Charakter aus der Datenbank löschen"):
            st.session_state["bestaetigung"] = ("loeschen", auswahl)

        frage = st.session_state.get("bestaetigung")
        if frage == ("speichern", auswahl):
            if bestaetigen(f"„{name}“ wirklich speichern?", "speichern"):
                fehler = entwurf_in_db_speichern()
                if fehler:
                    st.error(fehler)
                else:
                    st.session_state["meldung"] = f"„{name}“ wurde gespeichert."
                    st.rerun()
        elif frage == ("verwerfen", auswahl):
            if bestaetigen("Alle ungespeicherten Änderungen verwerfen?", "verwerfen"):
                entwurf_zuruecksetzen()
                st.rerun()
        elif frage == ("loeschen", auswahl):
            if bestaetigen(f"„{auswahl}“ wirklich löschen? Das lässt sich nicht rückgängig machen.",
                           "loeschen"):
                charakter_loeschen(entwurf["besitzer"], auswahl)
                entwurf_verwerfen()
                st.session_state["meldung"] = f"„{auswahl}“ wurde gelöscht."
                st.session_state["springe_nach"] = AKTION_LADEN
                st.rerun()

        with st.expander("📁 Export / Import"):
            # Dateiname aus dem Charakternamen (unerlaubte Zeichen entfernen)
            dateiname = re.sub(r'[\\/:*?"<>|]', "", name or "").strip()[:50] or "charakterbogen"
            st.download_button(
                label="Charakterbogen als JSON herunterladen",
                data=json.dumps(bogen, ensure_ascii=False, indent=2),
                file_name=f"{dateiname}.json",
                mime="application/json",
            )
            if modul["portrait_png"]:
                portrait_png = modul["portrait_png"](bogen)
                if portrait_png:
                    st.download_button(
                        label="Portrait als PNG herunterladen",
                        data=portrait_png,
                        file_name=f"{dateiname}_portrait.png",
                        mime="image/png",
                    )
            st.file_uploader(
                "Charakterbogen aus JSON-Datei laden", type="json",
                key="json_upload", on_change=json_laden,
            )
            status = st.session_state.get("lade_status")
            if status:
                getattr(st, status[0])(status[1])


# ----- 7e. Seite: Handouts ansehen (nur freigegebene)
def seite_handouts():
    st.title("📜 Handouts")
    handouts = handouts_liste(nur_sichtbar=True)
    if not handouts:
        st.info("Der Spielleiter hat noch keine Handouts freigegeben.")
        return

    namen = {h["id"]: h["titel"] for h in handouts}
    if st.session_state.get("handout_wahl") not in namen:
        st.session_state.pop("handout_wahl", None)
    wahl = st.sidebar.selectbox("Handout", list(namen), format_func=namen.get,
                                key="handout_wahl")
    h = handout_laden(wahl)
    if h:
        handout_anzeigen(h)


# =============================================================================
# 8. SPIELLEITER-BEREICH (nur nach Login erreichbar)
# =============================================================================

# ----- 8a. Seite: Charaktere aller Spieler
def seite_gm_charaktere():
    st.title("🧙 Spielleiter: Charaktere")

    alle = alle_charaktere()
    if not alle:
        st.warning("Noch keine Charaktere gespeichert.")
        return

    st.dataframe(
        pd.DataFrame([{
            "Spieler": c["spieler"], "Charakter": c["name"],
            "Regelwerk": regelwerk_name(c["regelwerk"]), "Setting": c["setting"],
            "Geändert am": c["geaendert_am"],
        } for c in alle]),
        hide_index=True,
    )

    st.subheader("Einzelnen Charakter ansehen")
    namen = [f"{c['spieler']} – {c['name']}" for c in alle]
    wahl = st.selectbox("Charakter", namen)
    eintrag = alle[namen.index(wahl)]
    bogen = charakter_laden(eintrag["spieler"], eintrag["name"])
    if not bogen:
        return

    if st.button("✏️ Zum Bearbeiten öffnen"):
        if entwurf_dirty():
            st.session_state["bestaetigung"] = ("gm_oeffnen", wahl)
        else:
            charakter_oeffnen(eintrag["spieler"], eintrag["name"])
    if st.session_state.get("bestaetigung") == ("gm_oeffnen", wahl):
        if bestaetigen("Der aktuelle Entwurf hat ungespeicherte Änderungen. "
                       "Wirklich ersetzen?", "gm_oeffnen"):
            charakter_oeffnen(eintrag["spieler"], eintrag["name"])

    regelwerk_modul(bogen)["gm_ansicht"](bogen, wahl)


# ----- 8b. Seite: Handouts hochladen, freigeben, löschen
def seite_gm_handouts():
    st.title("🧙 Spielleiter: Handouts verwalten")

    if "meldung" in st.session_state:
        st.success(st.session_state.pop("meldung"))

    zaehler = st.session_state.get("hd_zaehler", 0)
    dateien = st.file_uploader(
        "Dateien hochladen (Bilder, PDF, TXT, MD)",
        type=list(HANDOUT_TYPEN), accept_multiple_files=True, key=f"hd_upload_{zaehler}",
    )
    sofort = st.checkbox("Sofort für Spieler sichtbar", value=False, key="hd_sofort")
    if dateien and st.button("📤 Hochladen"):
        for d in dateien:
            endung = d.name.rsplit(".", 1)[-1].lower()
            handout_speichern(Path(d.name).stem, d.name, HANDOUT_TYPEN[endung],
                              d.getvalue(), sofort)
        st.session_state["hd_zaehler"] = zaehler + 1  # leert den Uploader
        st.session_state["meldung"] = f"{len(dateien)} Datei(en) hochgeladen."
        st.rerun()

    for h in handouts_liste(nur_sichtbar=False):
        c1, c2, c3, c4 = st.columns([4, 2, 2, 1])
        c1.write(f"**{h['titel']}** · {h['dateiname']}")
        sichtbar = c2.toggle("Sichtbar", value=bool(h["sichtbar"]), key=f"hd_sicht_{h['id']}")
        if sichtbar != bool(h["sichtbar"]):
            handout_sichtbarkeit(h["id"], sichtbar)
            st.rerun()
        vorschau = c3.checkbox("Vorschau", key=f"hd_vor_{h['id']}")
        if c4.button("🗑️", key=f"hd_del_{h['id']}"):
            handout_loeschen(h["id"])
            st.rerun()
        if vorschau:
            vollstaendig = handout_laden(h["id"])
            if vollstaendig:
                handout_anzeigen(vollstaendig, titel_zeigen=True)


# ----- 8c. Seite: Backup
def seite_gm_backup():
    st.title("🧙 Spielleiter: Backup")
    if DB_PATH.exists():
        st.download_button("⬇️ Datenbank herunterladen", data=DB_PATH.read_bytes(),
                           file_name=backup_dateiname())
    hochgeladen = st.file_uploader("Backup einspielen (.db)", type=["db"])
    if hochgeladen is not None and st.button("Backup wiederherstellen"):
        inhalt = hochgeladen.getvalue()
        if inhalt.startswith(b"SQLite format 3"):
            DB_PATH.write_bytes(inhalt)
            init_db()
            st.success("Backup eingespielt.")
            st.rerun()
        else:
            st.error("Das ist keine gültige SQLite-Datei.")


# =============================================================================
# 9. SIDEBAR & NAVIGATION
# =============================================================================
def gm_abmelden():
    st.session_state["gm_ok"] = False
    st.session_state.pop("gm_pw", None)
    st.session_state.pop("gm_aktion", None)


def sidebar_spielername():
    st.sidebar.title("🎲 PnP-Runde")
    # Der Spielername steht in der URL (?spieler=...), damit er ein Neuladen übersteht.
    if "spieler" not in st.session_state:
        st.session_state["spieler"] = st.query_params.get("spieler", "")
    name = st.sidebar.text_input("Dein Spielername", key="spieler").strip()
    if name:
        if st.query_params.get("spieler", "") != name:
            st.query_params["spieler"] = name
    elif "spieler" in st.query_params:
        del st.query_params["spieler"]
    return name


def spieler_aktion_gewaehlt():
    """Spieler-Menü benutzt -> Spielleiter-Menü leeren (es ist immer nur eine Seite aktiv)."""
    st.session_state["gm_aktion"] = None


def gm_aktion_gewaehlt():
    """Spielleiter-Menü benutzt -> Spieler-Menü leeren."""
    if st.session_state.get("gm_aktion"):
        st.session_state["aktion"] = None


def sprung_verarbeiten():
    """Springt zu einer Seite, die per st.session_state["springe_nach"] angefordert wurde."""
    ziel = st.session_state.pop("springe_nach", None)
    if ziel:
        st.session_state["gm_aktion"] = None
        st.session_state["aktion"] = ziel


def sidebar_navigation(gm_ok):
    """Zwei Menüs: Spieler (immer) und Spielleiter (erst nach Login). Gibt die aktive Seite zurück."""
    gm_aktion = st.session_state.get("gm_aktion") if gm_ok else None
    gm_aktiv = gm_aktion in GM_AKTIONEN

    if not gm_aktiv and st.session_state.get("aktion") not in SPIELER_AKTIONEN:
        st.session_state["aktion"] = AKTION_NEU
    gewuenscht = gm_aktion if gm_aktiv else st.session_state["aktion"]

    # Verlassen des Bearbeiten-Bereichs mit ungespeicherten Änderungen abfangen:
    # zurück zum Bogen und dort nachfragen (muss vor dem Erzeugen der Menüs passieren).
    frei = st.session_state.pop("verlassen_frei", False)
    if (st.session_state.get("letzte_aktion") == AKTION_BEARBEITEN
            and gewuenscht != AKTION_BEARBEITEN and not frei and entwurf_dirty()):
        st.session_state["verlassen_ziel"] = gewuenscht
        st.session_state["gm_aktion"] = None
        st.session_state["aktion"] = AKTION_BEARBEITEN
        gm_aktiv = False
        gewuenscht = AKTION_BEARBEITEN

    st.sidebar.selectbox(
        "Was möchtest du tun?", SPIELER_AKTIONEN, index=None,
        placeholder="Seite wählen", key="aktion", on_change=spieler_aktion_gewaehlt,
    )
    if gm_ok:
        st.sidebar.selectbox(
            "Spielleiter-Bereich", GM_AKTIONEN, index=None,
            placeholder="Seite wählen", key="gm_aktion", on_change=gm_aktion_gewaehlt,
        )
    return gewuenscht


def sidebar_gm_login():
    """Login-Box für den Spielleiter (steht ganz unten in der Sidebar)."""
    with st.sidebar.expander("🔒 Spielleiter-Login"):
        if st.session_state.get("gm_ok"):
            st.success("Angemeldet")
            st.button("Abmelden", on_click=gm_abmelden)
        else:
            pw = st.text_input("Passwort", type="password", key="gm_pw")
            if pw and pw == GM_PASSWORT:
                st.session_state["gm_ok"] = True
                st.rerun()
            elif pw:
                st.error("Falsches Passwort.")


# =============================================================================
# 10. START
# =============================================================================
GM_SEITEN = {
    AKTION_GM_CHARAKTERE: seite_gm_charaktere,
    AKTION_GM_HANDOUTS: seite_gm_handouts,
    AKTION_GM_BACKUP: seite_gm_backup,
}


def main():
    init_db()

    # Sidebar oben: Spielername und Menüs
    spieler = sidebar_spielername()
    gm_ok = bool(st.session_state.get("gm_ok"))
    entwurf_wiederherstellen()
    sprung_verarbeiten()
    aktion = sidebar_navigation(gm_ok)

    # Verlässt man den Bogen, werden seine Eingabefelder von Streamlit verworfen:
    # beim Zurückkommen werden sie aus dem Entwurf neu befüllt.
    if aktion not in BOGEN_AKTIONEN:
        st.session_state.pop("bogen_quelle", None)

    # Seite anzeigen
    if aktion in GM_SEITEN:
        GM_SEITEN[aktion]()
    elif aktion == AKTION_NEU:
        seite_neu(spieler)
    elif aktion == AKTION_LADEN:
        seite_laden()
    elif aktion == AKTION_BEARBEITEN:
        seite_bearbeiten()
    elif aktion == AKTION_HANDOUTS:
        seite_handouts()

    st.session_state["letzte_aktion"] = aktion
    entwurf_zwischenspeichern()

    # Sidebar ganz unten: Datenbank sichern (Spielleiter) und Spielleiter-Login
    st.sidebar.divider()
    if gm_ok and DB_PATH.exists():
        st.sidebar.download_button(
            "💾 Datenbank sichern", data=DB_PATH.read_bytes(),
            file_name=backup_dateiname(), mime="application/octet-stream", key="sb_backup",
        )
    sidebar_gm_login()


main()
