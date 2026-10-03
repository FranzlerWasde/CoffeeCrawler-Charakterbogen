"""
PnP-Charakterbogen (Miniregelwerk) – Einzeldatei-Version
Datenbank (SQLite), Spieler-Bereich und Spielleiter-Bereich in einer Datei.

Hinweis: In der stlite-Playground (https://edit.share.stlite.net/) liegt die Datenbank
nur im Arbeitsspeicher des Browsers -> Backup über "Spielleiter" herunterladen/einspielen.
Das Portrait-Zeichenfeld ist eine eigene Streamlit-Komponente und läuft vermutlich nur
lokal (streamlit run), nicht in der Playground.

AUFBAU DER DATEI
  1. Einstellungen
  2. Datenbank            (Grundlagen · Charaktere · Entwürfe · Handouts)
  3. Gemeinsame UI-Helfer (von Spielern UND Spielleiter genutzt)
  4. Spieler-Bereich      (Neu · Laden · Charakter bearbeiten · Handouts ansehen)
  5. Spielleiter-Bereich  (Charaktere · Handouts verwalten · Backup)
  6. Sidebar & Navigation
  7. Start
"""
import base64
import hashlib
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

# =============================================================================
# 1. EINSTELLUNGEN
# =============================================================================
GM_PASSWORT = "asdf"  # <- ändern
DB_PATH = Path("charaktere.db")
NEU = "➕ Neuer Charakter"

# Regelwerk
WUERFEL = ["W4", "W6", "W8", "W10", "W12"]
ATTRIBUTE = ["Stärke", "Geschicklichkeit", "Konstitution", "Intelligenz",
             "Weisheit", "Wahrnehmung", "Erscheinung", "Charisma", "Manipulation"]
ANZAHL_TALENTE = 3
MAX_HISTORIE = 50
PNG_PREFIX = "data:image/png;base64,"

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
    # Der komplette Bogen (Name, Alter, Portrait, Attribute, HP, Ressource, Talente)
    # liegt als JSON in der Spalte "daten". Nur der Name steht zusätzlich als eigene
    # Spalte, damit man Charaktere auflisten und eindeutig adressieren kann.
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
        # Ältere Datenbanken: Spalte "setting" nachrüsten
        spalten = [r["name"] for r in conn.execute("PRAGMA table_info(charaktere)")]
        if "setting" not in spalten:
            conn.execute("ALTER TABLE charaktere ADD COLUMN setting TEXT NOT NULL DEFAULT ''")


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
            INSERT INTO charaktere (spieler_id, name, setting, daten, erstellt_am, geaendert_am)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (spieler_id, name) DO UPDATE SET
                setting = excluded.setting,
                daten = excluded.daten, geaendert_am = excluded.geaendert_am
            """,
            (spieler_id, charakter_name, bogen.get("charakter", {}).get("setting", ""),
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
            """SELECT s.name AS spieler, c.name, c.setting, c.geaendert_am
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
# 3. GEMEINSAME UI-HELFER (Spieler + Spielleiter)
# =============================================================================

# ----- Bestätigungsdialog
def bestaetigen(frage, schluessel):
    """Zeigt Ja/Nein-Buttons. Gibt True (Ja), False (Nein) oder None (noch keine Antwort) zurück."""
    st.warning(frage)
    ja, nein, _ = st.columns([1, 1, 6])
    if ja.button("✅ Ja", key=f"ja_{schluessel}"):
        st.session_state.pop("bestaetigung", None)
        return True
    if nein.button("❌ Nein", key=f"nein_{schluessel}"):
        st.session_state.pop("bestaetigung", None)
        st.rerun()
    return None


# ----- Portrait (als PNG-Data-URL gespeichert)
def portrait_zu_bytes(portrait):
    if isinstance(portrait, str) and portrait.startswith(PNG_PREFIX):
        return base64.b64decode(portrait[len(PNG_PREFIX):])
    return None


# ----- Backup
def backup_dateiname():
    return f"charaktere_backup_{datetime.now():%Y-%m-%d_%H-%M}.db"


# ----- Handout-Anzeige
def pdf_anzeigen(daten):
    b64 = base64.b64encode(daten).decode()
    components.html(
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
        height=800,
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
# 4. SPIELER-BEREICH
# =============================================================================

# ----- 4a. Portrait-Komponente (Canvas mit Rückgabe an Python)
PORTRAIT_INDEX = """<!DOCTYPE html>
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
// --- Streamlit-Komponenten-Protokoll ---
function senden(type, daten) {
  window.parent.postMessage(
    Object.assign({ isStreamlitMessage: true, type: type }, daten), "*"
  );
}
function setzeHoehe() {
  senden("streamlit:setFrameHeight",
         { height: document.getElementById('wrap').offsetHeight + 4 });
}
function sendeWert(wert) {
  senden("streamlit:setComponentValue", { value: wert, dataType: "json" });
}

// --- Canvas ---
const c = document.getElementById('c');
const ctx = c.getContext('2d');
const farbe = document.getElementById('farbe');
const breite = document.getElementById('breite');
const verlauf = [];
let zeichnet = false;
let geladen = false;

function weiss() {
  ctx.fillStyle = '#fff';
  ctx.fillRect(0, 0, c.width, c.height);
}
weiss();
ctx.lineCap = 'round';
ctx.lineJoin = 'round';

function zeichneBild(src) {
  const img = new Image();
  img.onload = () => {
    weiss();
    ctx.drawImage(img, 0, 0, c.width, c.height);
  };
  img.src = src;
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
  ctx.strokeStyle = farbe.value;
  ctx.lineWidth = breite.value;
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
  sendeWert(c.toDataURL('image/png'));
});

document.getElementById('undo').onclick = () => {
  const s = verlauf.pop();
  if (s) {
    ctx.putImageData(s, 0, 0);
    sendeWert(c.toDataURL('image/png'));
  }
};
document.getElementById('clear').onclick = () => {
  schritt();
  weiss();
  sendeWert("");  // leerer String = Portrait ist leer
};
document.getElementById('save').onclick = () => {
  const a = document.createElement('a');
  a.href = c.toDataURL('image/png');
  a.download = 'charakterportrait.png';
  a.click();
};

// --- Nachrichten von Streamlit (Theme übernehmen) ---
window.addEventListener('message', e => {
  if (!e.data || e.data.type !== 'streamlit:render') return;
  const t = e.data.theme;
  if (t) {
    const root = document.documentElement.style;
    if (t.textColor) {
      root.setProperty('--text', t.textColor);
      root.setProperty('--border', 'color-mix(in srgb, ' + t.textColor + ' 20%, transparent)');
    }
    if (t.primaryColor) root.setProperty('--primary', t.primaryColor);
    if (t.font) document.body.style.fontFamily = t.font;
  }
  if (!geladen) {
    geladen = true;
    const start = e.data.args && e.data.args.initial;
    if (start) zeichneBild(start);
  }
  setzeHoehe();
});

senden("streamlit:componentReady", { apiVersion: 1 });
setzeHoehe();
</script>
</body>
</html>
"""

# Falls die Umgebung keine eigenen Komponenten erlaubt, läuft der Bogen ohne Zeichenfeld.
portrait_komponente = None
try:
    PORTRAIT_DIR = Path(__file__).parent / "portrait_component"
    PORTRAIT_DIR.mkdir(exist_ok=True)
    _index = PORTRAIT_DIR / "index.html"
    if not _index.exists() or _index.read_text(encoding="utf-8") != PORTRAIT_INDEX:
        _index.write_text(PORTRAIT_INDEX, encoding="utf-8")
    portrait_komponente = components.declare_component(
        "charakter_portrait", path=str(PORTRAIT_DIR)
    )
except Exception:
    portrait_komponente = None


# ----- 4b. Bogen-Daten <-> Session-State
def leerer_bogen():
    return {
        "charakter": {"setting": "", "name": "", "alter": None, "aussehen": ""},
        "portrait": None,
        "attribute": {a: "W4" for a in ATTRIBUTE},
        "hp": {"aktuell": None, "maximum": None},
        "mana": {"name": "", "prozent": 100},
        "talente": [],
        "inventar": "",
        "notizen": "",
    }


def wuerfel_ok(wert):
    return wert if wert in WUERFEL else None


def bogen_in_session(daten):
    """Schreibt einen Bogen (aus Datenbank oder JSON-Datei) in die Eingabefelder."""
    # Charakter
    char = daten.get("charakter", {})
    setting = char.get("setting", "")
    st.session_state["char_setting"] = setting if isinstance(setting, str) else ""
    st.session_state["char_name"] = char.get("name", "")
    alter = char.get("alter")
    st.session_state["char_alter"] = alter if isinstance(alter, int) else None
    aussehen = char.get("aussehen", "")
    st.session_state["char_aussehen"] = aussehen if isinstance(aussehen, str) else ""

    # Portrait: neuer Key erzeugt das Canvas neu und lädt die Zeichnung hinein
    portrait = daten.get("portrait")
    st.session_state["portrait_data"] = (
        portrait if isinstance(portrait, str) and portrait.startswith(PNG_PREFIX) else None
    )
    st.session_state["portrait_version"] += 1

    # Attribute
    attr = daten.get("attribute", {})
    for a in ATTRIBUTE:
        st.session_state[f"attr_{a}"] = wuerfel_ok(attr.get(a))

    # HP
    hp = daten.get("hp", {})
    maximum = hp.get("maximum")
    if isinstance(maximum, int):
        aktuell = hp.get("aktuell")
        if not isinstance(aktuell, int):
            aktuell = maximum
        st.session_state["hp_max"] = maximum
        st.session_state["hp_aktuell"] = max(0, min(aktuell, maximum))
        st.session_state["hp_info"] = "aus Datei geladen"
    else:
        st.session_state["hp_max"] = None
        st.session_state.pop("hp_aktuell", None)
        st.session_state.pop("hp_info", None)

    # Mana / Ressource
    mana = daten.get("mana", {})
    st.session_state["mana_name"] = mana.get("name", "")
    prozent = mana.get("prozent")
    st.session_state["mana_wert"] = (
        max(0, min(prozent, 100)) if isinstance(prozent, int) else 100
    )

    # Talente
    talente = daten.get("talente", [])
    for i in range(ANZAHL_TALENTE):
        eintrag = talente[i] if i < len(talente) and isinstance(talente[i], dict) else {}
        st.session_state[f"talent_name_{i}"] = eintrag.get("name", "")
        st.session_state[f"talent_wuerfel_{i}"] = wuerfel_ok(eintrag.get("wuerfel"))

    # Inventar und Spielernotizen (Freitext)
    for feld, key in (("inventar", "inventar_text"), ("notizen", "notizen_text")):
        text = daten.get(feld, "")
        st.session_state[key] = text if isinstance(text, str) else ""


def bogen_state_vorbereiten():
    """Startwerte (nur beim ersten Aufruf)."""
    st.session_state.setdefault("historie", [])
    st.session_state.setdefault("portrait_data", None)
    st.session_state.setdefault("portrait_version", 0)
    st.session_state.setdefault("mana_wert", 100)
    for a in ATTRIBUTE:
        st.session_state.setdefault(f"attr_{a}", "W4")


# ----- 4c. Callbacks (Würfel, HP, JSON-Import)
def in_historie(name, wuerfel, ergebnis):
    historie = st.session_state["historie"]
    historie.append({
        "zeit": datetime.now().strftime("%H:%M:%S"),
        "name": name,
        "wuerfel": wuerfel,
        "ergebnis": ergebnis,
    })
    del historie[:-MAX_HISTORIE]


def wuerfeln(name, wuerfel):
    ergebnis = random.randint(1, int(wuerfel[1:]))
    in_historie(name, wuerfel, ergebnis)
    st.toast(f"{name} ({wuerfel}): {ergebnis}", icon="🎲")


def historie_leeren():
    st.session_state["historie"] = []


def hp_wuerfeln():
    wuerfel = st.session_state.get("attr_Konstitution")
    if wuerfel is None:
        return
    seiten = int(wuerfel[1:])             # "W8" -> 8
    stufe = WUERFEL.index(wuerfel) + 1    # W4 = 1, W6 = 2, ... W12 = 5
    wurf = random.randint(1, seiten)
    maximum = wurf + stufe
    st.session_state["hp_max"] = maximum
    st.session_state["hp_aktuell"] = maximum
    st.session_state["hp_info"] = f"{wuerfel}: gewürfelt {wurf} + Stufe {stufe}"
    in_historie("HP-Maximum", wuerfel, wurf)


def hp_zuruecksetzen():
    st.session_state["hp_max"] = None
    st.session_state.pop("hp_aktuell", None)
    st.session_state.pop("hp_info", None)


def json_laden():
    datei = st.session_state.get("json_upload")
    if datei is None:
        return
    try:
        daten = json.load(datei)
    except (json.JSONDecodeError, UnicodeDecodeError):
        st.session_state["lade_status"] = ("error", "Die Datei ist kein gültiges JSON.")
        return
    if not isinstance(daten, dict):
        st.session_state["lade_status"] = ("error", "Unerwartetes Dateiformat.")
        return
    bogen_in_session(daten)
    st.session_state["lade_status"] = ("success", "Charakterbogen geladen.")


# ----- 4d. Entwurf: Zwischenspeicher des Bogens
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
    name = bogen["charakter"]["name"].strip()
    besitzer = e["besitzer"] or st.session_state.get("spieler", "").strip()
    if not besitzer:
        return "Gib links deinen Spielernamen ein, um den Charakter zu speichern."
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
    entwurf_setzen(e["besitzer"], e["auswahl"], bogen or leerer_bogen())


def charakter_neu_starten():
    entwurf_setzen(None, NEU, leerer_bogen())
    st.session_state["springe_nach"] = AKTION_BEARBEITEN
    st.rerun()


def charakter_oeffnen(besitzer, name):
    entwurf_setzen(besitzer, name, charakter_laden(besitzer, name) or leerer_bogen())
    st.session_state["springe_nach"] = AKTION_BEARBEITEN
    st.rerun()


# ----- 4e. Seiten: Neu erstellen / Laden (führen beide zum Bereich "Charakter bearbeiten")
def seite_neu(spieler):
    st.title("Neuen Charakter erstellen")
    if not spieler:
        st.info("Gib links deinen Spielernamen ein, um einen neuen Charakter zu erstellen.")
        return

    st.write("Du bekommst einen leeren Bogen und füllst ihn im Bereich "
             "„Charakter bearbeiten“ aus.")
    if st.button("➕ Neuen Charakter erstellen", type="primary"):
        if entwurf_dirty():
            st.session_state["bestaetigung"] = ("neu", "neu")
        else:
            charakter_neu_starten()
    if st.session_state.get("bestaetigung") == ("neu", "neu"):
        if bestaetigen("Der aktuelle Entwurf hat ungespeicherte Änderungen. "
                       "Wirklich verwerfen und neu beginnen?", "neu"):
            charakter_neu_starten()


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
    st.caption("Der Charakter wird im Bereich „Charakter bearbeiten“ geöffnet.")

    if c2.button("📂 Laden"):
        if entwurf_dirty():
            st.session_state["bestaetigung"] = ("laden", wahl)
        else:
            charakter_oeffnen(eintrag["spieler"], eintrag["name"])
    if st.session_state.get("bestaetigung") == ("laden", wahl):
        if bestaetigen("Der aktuelle Entwurf hat ungespeicherte Änderungen. "
                       "Wirklich ersetzen?", "laden"):
            charakter_oeffnen(eintrag["spieler"], eintrag["name"])


# ----- 4f. Seite: Charakter bearbeiten
BOGEN_CSS = """
<style>
div[data-testid="stHorizontalBlock"] {
    flex-wrap: nowrap !important;
}
div[data-testid="stColumn"] {
    min-width: 0 !important;
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
    st.markdown(BOGEN_CSS, unsafe_allow_html=True)
    bogen_state_vorbereiten()

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

    # Eingabefelder aus dem Entwurf befüllen (beim Öffnen und nach jedem Seitenwechsel)
    if "bogen_quelle" not in st.session_state:
        bogen_in_session(entwurf["bogen"])
        st.session_state["bogen_quelle"] = True

    status = st.empty()
    bogen = bogen_formular()

    # Entwurf aktuell halten und Änderungen erkennen
    entwurf["bogen"] = bogen
    aktuell = bogen_hash(bogen)
    if entwurf.get("basis") is None:
        entwurf["basis"] = aktuell
    dirty = aktuell != entwurf["basis"]

    if entwurf["auswahl"] == NEU:
        status.caption("**Neuer Charakter** · 🟠 noch nicht in der Datenbank gespeichert")
    else:
        stand = "🟠 ungespeicherte Änderungen" if dirty else "🟢 gespeichert"
        status.caption(f"**{entwurf['besitzer']} – {entwurf['auswahl']}** · {stand}")

    bogen_aktionen(bogen, entwurf, dirty)


def bogen_formular():
    """Die Eingabefelder des Charakterbogens. Gibt den aktuellen Bogen als Dictionary zurück."""
    # --- Setting (Titel des One Shots) und Charakter ---
    char_setting = st.text_input(
        "Setting", key="char_setting", placeholder="Setting (Titel des One Shots)",
        label_visibility="collapsed",
    )
    links, rechts = st.columns([3, 1], vertical_alignment="center")
    with links:
        char_name = st.text_input(
            "Name", key="char_name", placeholder="Name", label_visibility="collapsed"
        )
    with rechts:
        char_alter = st.number_input(
            "Alter", min_value=0, max_value=999, step=1, value=None,
            key="char_alter", placeholder="Alter", label_visibility="collapsed",
        )
    char_aussehen = st.text_input(
        "Aussehen", key="char_aussehen", placeholder="Aussehen", label_visibility="collapsed"
    )

    # --- Charakterportrait (Canvas) ---
    with st.expander("Charakterportrait", expanded=True):
        if portrait_komponente is None:
            st.info("Das Zeichenfeld ist in dieser Umgebung nicht verfügbar.")
            bild = portrait_zu_bytes(st.session_state["portrait_data"])
            if bild:
                st.image(bild)
            portrait_neu = None
        else:
            portrait_neu = portrait_komponente(
                initial=st.session_state["portrait_data"],
                key=f"portrait_{st.session_state['portrait_version']}",
                default=None,
            )

    if portrait_neu is not None:
        st.session_state["portrait_data"] = portrait_neu or None  # "" = leer
    portrait_data = st.session_state["portrait_data"]

    # --- HP ---
    st.header("HP")

    konstitution = st.session_state.get("attr_Konstitution")
    hp_max = st.session_state.get("hp_max")

    with st.container(key="hp_button"):
        c1, c2, _ = st.columns([1, 1, 1], vertical_alignment="center")
        with c1:
            st.button(
                "🎲 HP würfeln",
                on_click=hp_wuerfeln,
                disabled=konstitution is None or hp_max is not None,
            )
        with c2:
            if hp_max is not None:
                st.button("↺ Zurücksetzen", on_click=hp_zuruecksetzen)

    if konstitution is None and hp_max is None:
        st.caption("Wähle zuerst einen Würfel für Konstitution.")

    if hp_max is None:
        hp_aktuell = None
    else:
        st.caption(st.session_state.get("hp_info", "") + f" = {hp_max} HP maximal")
        hp_aktuell = st.slider(
            "Aktuelle HP", min_value=0, max_value=hp_max, key="hp_aktuell",
        )

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

    # --- Würfelhistorie ---
    st.header("Würfelhistorie")

    historie = st.session_state["historie"]
    with st.container(height=150, border=True):
        if not historie:
            st.caption("Noch nicht gewürfelt.")
        for eintrag in reversed(historie):
            st.write(
                f"`{eintrag.get('zeit', '--:--:--')}` · "
                f"**{eintrag['ergebnis']}** · {eintrag['name']} ({eintrag['wuerfel']})"
            )

    with st.container(key="hist_button"):
        st.button("Historie leeren", on_click=historie_leeren, disabled=not historie)

    # --- Attribute ---
    st.header("Attribute")

    attribute_werte = {}

    for i, attribut in enumerate(ATTRIBUTE):
        links, mitte, rechts = st.columns([2, 5, 1], vertical_alignment="center")
        with links:
            st.write(attribut)
        with mitte:
            attribute_werte[attribut] = st.segmented_control(
                attribut, options=WUERFEL, key=f"attr_{attribut}",
                label_visibility="collapsed",
            )
        with rechts:
            st.button(
                "🎲",
                key=f"wurf_attr_{i}",
                on_click=wuerfeln,
                args=(attribut, attribute_werte[attribut]),
                disabled=attribute_werte[attribut] is None,
            )

    # --- Talente ---
    st.header("Talente")

    talente_werte = []

    for i in range(ANZAHL_TALENTE):
        links, mitte, rechts = st.columns([2, 5, 1], vertical_alignment="center")
        with links:
            name = st.text_input(
                f"Name {i + 1}", key=f"talent_name_{i}", placeholder="Talent",
                label_visibility="collapsed",
            )
        with mitte:
            wuerfel = st.segmented_control(
                f"Würfel {i + 1}", options=WUERFEL, key=f"talent_wuerfel_{i}",
                label_visibility="collapsed",
            )
        with rechts:
            st.button(
                "🎲",
                key=f"wurf_talent_{i}",
                on_click=wuerfeln,
                args=(name or f"Talent {i + 1}", wuerfel),
                disabled=wuerfel is None,
            )
        talente_werte.append({"name": name, "wuerfel": wuerfel})

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
        "charakter": {
            "setting": char_setting.strip(),
            "name": char_name.strip(),
            "alter": char_alter,
            "aussehen": char_aussehen,
        },
        "portrait": portrait_data,
        "attribute": attribute_werte,
        "hp": {"aktuell": hp_aktuell, "maximum": hp_max},
        "mana": {"name": mana_name, "prozent": mana_wert},
        "talente": talente_werte,
        "inventar": inventar,
        "notizen": notizen,
    }


def bogen_aktionen(bogen, entwurf, dirty):
    """Speichern, Verwerfen, Löschen sowie JSON-/PNG-Export und JSON-Import."""
    st.header("Speichern / Laden")
    auswahl = entwurf["auswahl"]
    name = bogen["charakter"]["name"]

    b1, b2, b3 = st.columns([2, 2, 1], vertical_alignment="center")
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

    # Dateiname aus dem Charakternamen (unerlaubte Zeichen entfernen)
    dateiname = re.sub(r'[\\/:*?"<>|]', "", name or "").strip()[:50]
    if not dateiname:
        dateiname = "charakterbogen"

    st.download_button(
        label="Charakterbogen als JSON herunterladen",
        data=json.dumps(bogen, ensure_ascii=False, indent=2),
        file_name=f"{dateiname}.json",
        mime="application/json",
    )

    portrait_png = portrait_zu_bytes(bogen["portrait"])
    if portrait_png:
        st.download_button(
            label="Portrait als PNG herunterladen",
            data=portrait_png,
            file_name=f"{dateiname}_portrait.png",
            mime="image/png",
        )

    with st.expander("Charakterbogen aus JSON-Datei laden"):
        st.file_uploader(
            "JSON-Datei auswählen", type="json", key="json_upload", on_change=json_laden,
        )
        status = st.session_state.get("lade_status")
        if status:
            getattr(st, status[0])(status[1])


# ----- 4g. Seite: Handouts ansehen (nur freigegebene)
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
# 5. SPIELLEITER-BEREICH (nur nach Login erreichbar)
# =============================================================================

# ----- 5a. Seite: Charaktere aller Spieler
def seite_gm_charaktere():
    st.title("🧙 Spielleiter: Charaktere")

    alle = alle_charaktere()
    if not alle:
        st.warning("Noch keine Charaktere gespeichert.")
        return

    st.dataframe(
        pd.DataFrame(alle).rename(columns={
            "spieler": "Spieler", "name": "Charakter",
            "setting": "Setting", "geaendert_am": "Geändert am",
        }),
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

    char = bogen.get("charakter", {})
    hp = bogen.get("hp", {})
    mana = bogen.get("mana", {})
    attribute = bogen.get("attribute", {})
    talente = [t for t in bogen.get("talente", []) if t.get("name")]

    a, b = st.columns(2)
    with a:
        alter = char.get("alter")
        st.markdown(f"**{char.get('name', '')}** · Alter: {alter if alter is not None else '–'}")
        st.caption(f"Setting: {char.get('setting') or '–'}")
        st.write(char.get("aussehen") or "–")
        if hp.get("maximum") is not None:
            st.metric("HP", f"{hp.get('aktuell')} / {hp.get('maximum')}")
        else:
            st.metric("HP", "–")
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
                 disabled=True, key=f"gm_inventar_{wahl}")
    st.text_area("Spielernotizen", value=bogen.get("notizen") or "", height=200,
                 disabled=True, key=f"gm_notizen_{wahl}")


# ----- 5b. Seite: Handouts hochladen, freigeben, löschen
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


# ----- 5c. Seite: Backup
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
# 6. SIDEBAR & NAVIGATION
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
# 7. START
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
