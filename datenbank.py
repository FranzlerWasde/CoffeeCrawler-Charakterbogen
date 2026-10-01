"""
PnP-Charakterbogen (Miniregelwerk) mit SQLite-Datenbank und Spielleiter-Bereich.

Start lokal mit:  streamlit run charakterbogen_komplett.py
Die Datenbank liegt in "charaktere.db" neben dem Skript. Über die Sidebar kann eine
bestehende Datenbank hochgeladen werden, im Bereich "Spielleiter" gibt es das Backup.
"""

import base64
import binascii
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

# =============================================================== EINSTELLUNGEN

GM_PASSWORT = "spielleiter"  # <- ändern
NEU = "➕ Neuer Charakter"
DB_PATH = Path("charaktere.db")

OPTIONS = ["W4", "W6", "W8", "W10", "W12"]
ATTRIBUTE = ["Stärke", "Geschicklichkeit", "Konstitution", "Intelligenz",
             "Weisheit", "Wahrnehmung", "Erscheinung", "Charisma", "Manipulation"]
ANZAHL_TALENTE = 3
MAX_HISTORIE = 50
PNG_PREFIX = "data:image/png;base64,"

st.markdown(
    """
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
    """,
    unsafe_allow_html=True,
)


# =============================================================== DATENBANK

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
    with verbindung() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS spieler (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS charaktere (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spieler_id INTEGER NOT NULL REFERENCES spieler(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                daten TEXT NOT NULL,
                erstellt_am TEXT NOT NULL,
                geaendert_am TEXT NOT NULL,
                UNIQUE (spieler_id, name)
            );
            """
        )


def charakter_speichern(spieler_name, name, bogen):
    jetzt = datetime.now().isoformat(timespec="seconds")
    with verbindung() as conn:
        conn.execute("INSERT OR IGNORE INTO spieler (name) VALUES (?)", (spieler_name,))
        spieler_id = conn.execute(
            "SELECT id FROM spieler WHERE name = ?", (spieler_name,)
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO charaktere (spieler_id, name, daten, erstellt_am, geaendert_am)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (spieler_id, name) DO UPDATE SET
                daten = excluded.daten, geaendert_am = excluded.geaendert_am
            """,
            (spieler_id, name, json.dumps(bogen, ensure_ascii=False), jetzt, jetzt),
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
            """SELECT s.name AS spieler, c.name, c.geaendert_am
               FROM charaktere c JOIN spieler s ON s.id = c.spieler_id
               ORDER BY s.name, c.name"""
        ).fetchall()
    return [dict(r) for r in rows]


def datenbank_einspielen(inhalt: bytes):
    """Ersetzt die Datenbank durch hochgeladene Bytes. Gibt (ok, meldung) zurück."""
    if not inhalt.startswith(b"SQLite format 3"):
        return False, "Das ist keine gültige SQLite-Datei."
    alt = DB_PATH.read_bytes() if DB_PATH.exists() else None
    DB_PATH.write_bytes(inhalt)
    try:
        init_db()
        alle_charaktere()  # prüft, ob die Tabellen zur App passen
    except sqlite3.Error:
        if alt is not None:
            DB_PATH.write_bytes(alt)
        else:
            DB_PATH.unlink(missing_ok=True)
        return False, "Die Datenbank hat nicht die erwartete Struktur."
    return True, "Datenbank geladen."


# =============================================================== PORTRAIT-KOMPONENTE

PORTRAIT_INDEX = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body { margin: 0; }
  #wrap { font-family: sans-serif; font-size: 14px; }
  details {
    border: 1px solid #888;
    border-radius: 8px;
    padding: 4px 10px;
    margin-bottom: 6px;
  }
  summary { cursor: pointer; padding: 2px 0; }
  .row {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
    padding: 6px 0 4px 0;
  }
  canvas {
    display: block;
    border: 1px solid #888;
    background: #fff;
    touch-action: none;
    max-width: 100%;
  }
</style>
</head>
<body>
<div id="wrap">
  <details id="tools" open>
    <summary>🛠 Werkzeuge</summary>
    <div class="row">
      <input type="color" id="farbe" value="#000000" title="Farbe">
      <input type="range" id="breite" min="1" max="20" value="3" title="Strichbreite">
      <button id="undo">↶ Zurück</button>
      <button id="clear">🗑 Leeren</button>
      <button id="save">💾 PNG</button>
    </div>
  </details>
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
const tools = document.getElementById('tools');
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

tools.addEventListener('toggle', setzeHoehe);

// --- Nachrichten von Streamlit ---
window.addEventListener('message', e => {
  if (!e.data || e.data.type !== 'streamlit:render') return;
  if (e.data.theme && e.data.theme.textColor) {
    document.body.style.color = e.data.theme.textColor;
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

PORTRAIT_DIR = Path(__file__).parent / "portrait_component"
PORTRAIT_DIR.mkdir(exist_ok=True)
_index = PORTRAIT_DIR / "index.html"
if not _index.exists() or _index.read_text(encoding="utf-8") != PORTRAIT_INDEX:
    _index.write_text(PORTRAIT_INDEX, encoding="utf-8")

portrait_komponente = components.declare_component(
    "charakter_portrait", path=str(PORTRAIT_DIR)
)


# =============================================================== HILFSFUNKTIONEN

def leerer_bogen():
    return {
        "charakter": {"name": "", "alter": None, "aussehen": ""},
        "portrait": None,
        "attribute": {a: "W4" for a in ATTRIBUTE},
        "hp": {"aktuell": None, "maximum": None},
        "mana": {"name": "", "prozent": 100},
        "talente": [],
    }


def wuerfel_ok(wert):
    return wert if wert in OPTIONS else None


def bogen_in_state(daten, fallback_name=""):
    """Schreibt einen Charakterbogen (Dict) in die Widget-Werte (session_state).
    Muss aufgerufen werden, BEVOR die Widgets erzeugt werden."""
    char = daten.get("charakter", {})
    if not isinstance(char, dict):
        char = {}
    st.session_state["char_name"] = char.get("name") or fallback_name
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
    if not isinstance(attr, dict):
        attr = {}
    for a in ATTRIBUTE:
        st.session_state[f"attr_{a}"] = wuerfel_ok(attr.get(a))

    # HP
    hp = daten.get("hp", {})
    if not isinstance(hp, dict):
        hp = {}
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

    # Mana
    mana = daten.get("mana", {})
    if not isinstance(mana, dict):
        mana = {}
    st.session_state["mana_name"] = mana.get("name", "")
    prozent = mana.get("prozent")
    st.session_state["mana_wert"] = (
        max(0, min(prozent, 100)) if isinstance(prozent, int) else 100
    )

    # Talente
    talente = daten.get("talente", [])
    if not isinstance(talente, list):
        talente = []
    for i in range(ANZAHL_TALENTE):
        eintrag = talente[i] if i < len(talente) and isinstance(talente[i], dict) else {}
        st.session_state[f"talent_name_{i}"] = eintrag.get("name", "")
        st.session_state[f"talent_wuerfel_{i}"] = wuerfel_ok(eintrag.get("wuerfel"))


def portrait_bytes(portrait):
    if isinstance(portrait, str) and portrait.startswith(PNG_PREFIX):
        try:
            return base64.b64decode(portrait[len(PNG_PREFIX):])
        except (binascii.Error, ValueError):
            return None
    return None


# --- Callbacks ---
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
    seiten = int(wuerfel[1:])           # "W8" -> 8
    stufe = OPTIONS.index(wuerfel) + 1  # W4 = 1, W6 = 2, ... W12 = 5
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
    bogen_in_state(daten)
    st.session_state["lade_status"] = ("success", "Charakterbogen geladen.")


# =============================================================== SIDEBAR

def sidebar_datenbank_upload():
    st.sidebar.divider()
    st.sidebar.subheader("Datenbank")
    datei = st.sidebar.file_uploader("Bestehende Datenbank laden (.db)", type=["db"],
                                     key="db_upload")
    if datei is not None and st.sidebar.button("📂 Datenbank laden"):
        ok, meldung = datenbank_einspielen(datei.getvalue())
        if ok:
            st.session_state["geladen_fuer"] = None  # Bogen neu aus der DB laden
            st.session_state["meldung"] = meldung
            st.rerun()
        else:
            st.sidebar.error(meldung)


# =============================================================== SEITE: CHARAKTERBOGEN

def seite_charakterbogen():
    # Startwerte (nur beim ersten Aufruf)
    for a in ATTRIBUTE:
        st.session_state.setdefault(f"attr_{a}", "W4")
    st.session_state.setdefault("mana_wert", 100)
    st.session_state.setdefault("historie", [])
    st.session_state.setdefault("portrait_data", None)
    st.session_state.setdefault("portrait_version", 0)

    st.title("Charakterbogen")
    st.markdown("**Miniregelwerk**")

    # --- Spieler & Charakterauswahl (Sidebar) ---
    spieler = st.sidebar.text_input("Dein Spielername", key="spieler").strip()
    if not spieler:
        st.info("Gib links deinen Spielernamen ein.")
        return

    optionen = [NEU] + charaktere_von_spieler(spieler)
    if "auswahl_naechste" in st.session_state:
        st.session_state["auswahl"] = st.session_state.pop("auswahl_naechste")
    if st.session_state.get("auswahl") not in optionen:
        st.session_state["auswahl"] = NEU
    auswahl = st.sidebar.selectbox("Charakter", optionen, key="auswahl")

    # Bei Wechsel von Spieler/Charakter den Bogen in die Widgets laden
    ziel = (spieler, auswahl)
    if st.session_state.get("geladen_fuer") != ziel:
        if auswahl == NEU:
            bogen_in_state(leerer_bogen())
        else:
            bogen_in_state(charakter_laden(spieler, auswahl) or leerer_bogen(),
                           fallback_name=auswahl)
        st.session_state["geladen_fuer"] = ziel

    # --- Charakter ---
    links, rechts = st.columns([3, 1], vertical_alignment="center")
    with links:
        char_name = st.text_input(
            "Name", key="char_name", placeholder="Name", label_visibility="collapsed"
        )
    with rechts:
        char_alter = st.number_input(
            "Alter",
            min_value=0,
            max_value=999,
            step=1,
            value=None,
            key="char_alter",
            placeholder="Alter",
            label_visibility="collapsed",
        )
    char_aussehen = st.text_input(
        "Aussehen", key="char_aussehen", placeholder="Aussehen", label_visibility="collapsed"
    )

    # --- Charakterportrait (Canvas) ---
    with st.expander("Charakterportrait", expanded=True):
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
            "Aktuelle HP",
            min_value=0,
            max_value=hp_max,
            key="hp_aktuell",
        )

    # --- Mana / Ressource ---
    st.header("Ressource")

    links, rechts = st.columns([1, 2], vertical_alignment="center")
    with links:
        mana_name = st.text_input(
            "Name der Ressource",
            key="mana_name",
            placeholder="z. B. Mana",
            label_visibility="collapsed",
        )
    with rechts:
        mana_wert = st.slider(
            mana_name or "Ressource",
            min_value=0,
            max_value=100,
            key="mana_wert",
            format="%d%%",
            label_visibility="collapsed",
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
                attribut,
                options=OPTIONS,
                key=f"attr_{attribut}",
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
            talent_name = st.text_input(
                f"Name {i + 1}",
                key=f"talent_name_{i}",
                placeholder="Talent",
                label_visibility="collapsed",
            )
        with mitte:
            talent_wuerfel = st.segmented_control(
                f"Würfel {i + 1}",
                options=OPTIONS,
                key=f"talent_wuerfel_{i}",
                label_visibility="collapsed",
            )
        with rechts:
            st.button(
                "🎲",
                key=f"wurf_talent_{i}",
                on_click=wuerfeln,
                args=(talent_name or f"Talent {i + 1}", talent_wuerfel),
                disabled=talent_wuerfel is None,
            )
        talente_werte.append({"name": talent_name, "wuerfel": talent_wuerfel})

    # --- Speichern / Laden ---
    st.header("Speichern / Laden")

    daten = {
        "charakter": {
            "name": char_name.strip(),
            "alter": char_alter,
            "aussehen": char_aussehen,
        },
        "portrait": portrait_data,
        "attribute": attribute_werte,
        "hp": {"aktuell": hp_aktuell, "maximum": hp_max},
        "mana": {"name": mana_name, "prozent": mana_wert},
        "talente": talente_werte,
    }

    b1, b2, _ = st.columns([1, 1, 2])

    if b1.button("💾 In Datenbank speichern", type="primary"):
        neuer_name = daten["charakter"]["name"]
        vorhandene = charaktere_von_spieler(spieler)
        if not neuer_name:
            st.error("Bitte gib dem Charakter einen Namen.")
        elif neuer_name in vorhandene and neuer_name != auswahl:
            st.error(f"Du hast bereits einen Charakter namens „{neuer_name}“.")
        else:
            charakter_speichern(spieler, neuer_name, daten)
            # Beim Umbenennen den alten Eintrag entfernen
            if auswahl != NEU and neuer_name != auswahl:
                charakter_loeschen(spieler, auswahl)
            st.session_state["auswahl_naechste"] = neuer_name
            st.session_state["geladen_fuer"] = (spieler, neuer_name)  # Widgets sind schon aktuell
            st.session_state["meldung"] = f"„{neuer_name}“ wurde gespeichert."
            st.rerun()

    if auswahl != NEU and b2.button("🗑️ Löschen"):
        charakter_loeschen(spieler, auswahl)
        st.session_state["meldung"] = f"„{auswahl}“ wurde gelöscht."
        st.rerun()

    # Dateiname aus dem Charakternamen (unerlaubte Zeichen entfernen)
    dateiname = re.sub(r'[\\/:*?"<>|]', "", char_name or "").strip()[:50]
    if not dateiname:
        dateiname = "charakterbogen"

    st.download_button(
        label="Charakterbogen als JSON herunterladen",
        data=json.dumps(daten, ensure_ascii=False, indent=2),
        file_name=f"{dateiname}.json",
        mime="application/json",
    )

    with st.expander("Charakterbogen aus JSON laden"):
        st.file_uploader(
            "JSON-Datei auswählen",
            type="json",
            key="json_upload",
            on_change=json_laden,
        )
        status = st.session_state.get("lade_status")
        if status:
            getattr(st, status[0])(status[1])


# =============================================================== SEITE: SPIELLEITER

def seite_spielleiter():
    st.title("🧙 Spielleiter-Übersicht")

    pw = st.sidebar.text_input("Spielleiter-Passwort", type="password")
    if pw != GM_PASSWORT:
        st.info("Bitte links das Spielleiter-Passwort eingeben.")
        return

    alle = alle_charaktere()
    if not alle:
        st.warning("Noch keine Charaktere gespeichert.")
    else:
        st.dataframe(pd.DataFrame(alle), hide_index=True)

        st.subheader("Einzelnen Charakter ansehen")
        namen = [f"{c['spieler']} – {c['name']}" for c in alle]
        wahl = st.selectbox("Charakter", namen)
        eintrag = alle[namen.index(wahl)]
        bogen = charakter_laden(eintrag["spieler"], eintrag["name"])
        if bogen:
            char = bogen.get("charakter", {}) if isinstance(bogen.get("charakter"), dict) else {}
            hp = bogen.get("hp", {}) if isinstance(bogen.get("hp"), dict) else {}
            mana = bogen.get("mana", {}) if isinstance(bogen.get("mana"), dict) else {}

            a, b = st.columns(2)
            with a:
                titel = f"**{char.get('name') or eintrag['name']}**"
                if char.get("alter") is not None:
                    titel += f" · {char['alter']} Jahre"
                st.markdown(titel)
                if char.get("aussehen"):
                    st.write(char["aussehen"])
                if hp.get("maximum") is not None:
                    st.metric("HP", f"{hp.get('aktuell', hp['maximum'])} / {hp['maximum']}")
                st.write(f"**{mana.get('name') or 'Ressource'}:** {mana.get('prozent', 100)} %")
            with b:
                bild = portrait_bytes(bogen.get("portrait"))
                if bild:
                    st.image(bild, width=220)

            st.write("**Attribute**")
            attr = bogen.get("attribute", {})
            st.dataframe(
                pd.DataFrame([{k: (v or "–") for k, v in attr.items()}]),
                hide_index=True,
            )

            st.write("**Talente**")
            talente = [t for t in bogen.get("talente", [])
                       if isinstance(t, dict) and t.get("name")]
            if talente:
                st.dataframe(pd.DataFrame(talente), hide_index=True)
            else:
                st.write("–")

    st.divider()
    st.subheader("Backup")
    if DB_PATH.exists():
        st.download_button("⬇️ Datenbank herunterladen", data=DB_PATH.read_bytes(),
                           file_name="charaktere_backup.db")


# =============================================================== START

init_db()

seite = st.sidebar.radio("Bereich", ["Charakterbogen", "Spielleiter"])

if "meldung" in st.session_state:
    st.success(st.session_state.pop("meldung"))

if seite == "Charakterbogen":
    seite_charakterbogen()
else:
    seite_spielleiter()

sidebar_datenbank_upload()
