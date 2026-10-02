"""
PnP-Charakterbogen – Einzeldatei-Version für die Online-Playground (stlite)
https://edit.share.stlite.net/

Alles in einer Datei: Datenbank (SQLite), Beispieldaten und Oberfläche.
Hinweis: In der Playground liegt die Datenbank nur im Arbeitsspeicher des Browsers.
Beim Neuladen der Seite ist sie leer -> Backup über "Spielleiter" herunterladen/einspielen.
(Das Backup enthält auch alle hochgeladenen Handouts.)

AUFBAU DER DATEI
  1. Einstellungen
  2. Datenbank        (Grundlagen · Charaktere · Handouts · Beispieldaten)
  3. Gemeinsame UI-Helfer (von Spielern UND Spielleiter genutzt)
  4. Spieler-Bereich      (Charakterbogen · Handouts ansehen)
  5. Spielleiter-Bereich  (Charaktere · Handouts verwalten · Backup)
  6. Sidebar & Navigation
  7. Start
"""
import base64
import json
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
ATTRIBUTE = ["Stärke", "Geschick", "Konstitution", "Intelligenz", "Weisheit", "Charisma"]
INVENTAR_SPALTEN = ["Gegenstand", "Anzahl", "Notiz"]
NEU = "➕ Neuer Charakter"
DB_PATH = Path("charaktere.db")

# Menüpunkte für Spieler
AKTION_NEU = "Neuen Charakter erstellen"
AKTION_LADEN = "Charakter aus der Datenbank auswählen"
AKTION_HANDOUTS = "Handouts ansehen"
SPIELER_AKTIONEN = [AKTION_NEU, AKTION_LADEN, AKTION_HANDOUTS]

# Menüpunkte für den Spielleiter (nur nach Login sichtbar)
AKTION_GM_CHARAKTERE = "🔒 Spielleiter: Charaktere"
AKTION_GM_HANDOUTS = "🔒 Spielleiter: Handouts verwalten"
AKTION_GM_BACKUP = "🔒 Spielleiter: Backup"
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
                klasse       TEXT,
                stufe        INTEGER DEFAULT 1,
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
            """
        )


# ----- 2b. Charaktere
def charakter_speichern(spieler_name, bogen):
    jetzt = datetime.now().isoformat(timespec="seconds")
    with verbindung() as conn:
        conn.execute("INSERT OR IGNORE INTO spieler (name) VALUES (?)", (spieler_name,))
        spieler_id = conn.execute(
            "SELECT id FROM spieler WHERE name = ?", (spieler_name,)
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO charaktere (spieler_id, name, klasse, stufe, daten, erstellt_am, geaendert_am)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (spieler_id, name) DO UPDATE SET
                klasse = excluded.klasse, stufe = excluded.stufe,
                daten = excluded.daten, geaendert_am = excluded.geaendert_am
            """,
            (spieler_id, bogen["name"], bogen.get("klasse"), bogen.get("stufe", 1),
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
            """SELECT s.name AS spieler, c.name, c.klasse, c.stufe, c.geaendert_am
               FROM charaktere c JOIN spieler s ON s.id = c.spieler_id
               ORDER BY s.name, c.name"""
        ).fetchall()
        return [dict(r) for r in rows]


# ----- 2c. Handouts
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


# ----- 2d. Beispieldaten
BEISPIELE = {
    "Anna": [{
        "name": "Thorin Eisenfaust", "klasse": "Krieger", "rasse": "Zwerg", "stufe": 3,
        "attribute": {"Stärke": 16, "Geschick": 10, "Konstitution": 15,
                      "Intelligenz": 9, "Weisheit": 11, "Charisma": 8},
        "lp_max": 34, "lp_aktuell": 28,
        "inventar": [{"Gegenstand": "Streitaxt", "Anzahl": 1, "Notiz": "1W8+3"},
                     {"Gegenstand": "Heiltrank", "Anzahl": 2, "Notiz": ""}],
        "notizen": "Sucht den verlorenen Hammer seines Clans.",
    }],
    "Ben": [{
        "name": "Lyra Nachtwind", "klasse": "Magierin", "rasse": "Elfe", "stufe": 2,
        "attribute": {"Stärke": 8, "Geschick": 14, "Konstitution": 10,
                      "Intelligenz": 17, "Weisheit": 12, "Charisma": 13},
        "lp_max": 14, "lp_aktuell": 14,
        "inventar": [{"Gegenstand": "Zauberstab", "Anzahl": 1, "Notiz": ""},
                     {"Gegenstand": "Schriftrolle Feuerball", "Anzahl": 1, "Notiz": "einmalig"}],
        "notizen": "Misstraut der Magiergilde.",
    }, {
        "name": "Pip Fingerfix", "klasse": "Schurke", "rasse": "Halbling", "stufe": 1,
        "attribute": {"Stärke": 7, "Geschick": 17, "Konstitution": 11,
                      "Intelligenz": 12, "Weisheit": 10, "Charisma": 14},
        "lp_max": 9, "lp_aktuell": 9,
        "inventar": [{"Gegenstand": "Dietriche", "Anzahl": 1, "Notiz": ""}],
        "notizen": "",
    }],
}


def beispieldaten_laden():
    for spieler, charaktere in BEISPIELE.items():
        for bogen in charaktere:
            charakter_speichern(spieler, bogen)


# =============================================================================
# 3. GEMEINSAME UI-HELFER (Spieler + Spielleiter)
# =============================================================================

# ----- Charakter-Daten
def leerer_bogen():
    return {
        "name": "", "klasse": "", "rasse": "", "stufe": 1,
        "attribute": {a: 10 for a in ATTRIBUTE},
        "lp_max": 10, "lp_aktuell": 10, "inventar": [], "notizen": "",
    }


def inventar_zu_df(inventar):
    df = pd.DataFrame(inventar, columns=INVENTAR_SPALTEN)
    df["Gegenstand"] = df["Gegenstand"].astype(str)
    df["Anzahl"] = pd.to_numeric(df["Anzahl"], errors="coerce").fillna(1).astype(int)
    df["Notiz"] = df["Notiz"].astype(str)
    return df


def df_zu_inventar(df):
    eintraege = []
    for _, zeile in df.iterrows():
        gegenstand = str(zeile["Gegenstand"]).strip() if pd.notna(zeile["Gegenstand"]) else ""
        if not gegenstand or gegenstand == "None":
            continue
        anzahl = int(zeile["Anzahl"]) if pd.notna(zeile["Anzahl"]) else 1
        notiz = str(zeile["Notiz"]) if pd.notna(zeile["Notiz"]) else ""
        eintraege.append({"Gegenstand": gegenstand, "Anzahl": anzahl,
                          "Notiz": "" if notiz == "None" else notiz})
    return eintraege


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

# ----- 4a. Seite: Charakterbogen (neu erstellen / aus Datenbank laden)
def seite_charakterbogen(aktion, spieler):
    st.title("🎲 Charakterbogen")
    if "meldung" in st.session_state:
        st.success(st.session_state.pop("meldung"))
    zaehler = st.session_state.get("lade_zaehler", 0)

    if aktion == AKTION_NEU:
        if not spieler:
            st.info("Gib links deinen Spielernamen ein, um einen neuen Charakter zu erstellen.")
            return
        besitzer, auswahl = spieler, NEU
        bogen = leerer_bogen()
    else:
        alle = alle_charaktere()
        if not alle:
            st.warning("Die Datenbank ist leer – es gibt noch keine gespeicherten Charaktere.")
            return
        labels = [f"{c['spieler']} – {c['name']}" for c in alle]
        if st.session_state.get("auswahl_db") not in labels:
            st.session_state["auswahl_db"] = labels[0]
        wahl = st.sidebar.selectbox("Charakter suchen (Tippen zum Filtern)",
                                    labels, key="auswahl_db")
        if st.sidebar.button("📂 Laden"):
            st.session_state["bestaetigung"] = ("laden", wahl)
        if st.session_state.get("bestaetigung") == ("laden", wahl):
            with st.sidebar:
                antwort = bestaetigen(
                    f"„{wahl}“ wirklich laden? Nicht gespeicherte Änderungen gehen verloren.",
                    "laden")
            if antwort:
                st.session_state["geladen"] = wahl
                st.session_state["lade_zaehler"] = zaehler + 1
                st.rerun()

        geladen = st.session_state.get("geladen")
        if geladen not in labels:
            st.info("Wähle links einen Charakter aus und klicke auf „Laden“.")
            return
        eintrag = alle[labels.index(geladen)]
        besitzer, auswahl = eintrag["spieler"], eintrag["name"]
        bogen = charakter_laden(besitzer, auswahl) or leerer_bogen()

    k = f"{besitzer}|{auswahl}|{zaehler}"

    st.subheader("Grunddaten")
    c1, c2, c3, c4 = st.columns([3, 2, 2, 1])
    name = c1.text_input("Name", value=bogen["name"], key=f"name_{k}")
    klasse = c2.text_input("Klasse / Beruf", value=bogen.get("klasse", ""), key=f"klasse_{k}")
    rasse = c3.text_input("Rasse / Herkunft", value=bogen.get("rasse", ""), key=f"rasse_{k}")
    stufe = c4.number_input("Stufe", 1, 30, int(bogen.get("stufe", 1)), key=f"stufe_{k}")

    st.subheader("Attribute")
    attribute = {}
    for spalte, attr in zip(st.columns(len(ATTRIBUTE)), ATTRIBUTE):
        attribute[attr] = spalte.number_input(
            attr, 1, 30, int(bogen.get("attribute", {}).get(attr, 10)), key=f"attr_{attr}_{k}")

    st.subheader("Lebenspunkte")
    l1, l2, _ = st.columns([1, 1, 4])
    lp_max = l1.number_input("LP max", 1, 999, int(bogen.get("lp_max", 10)), key=f"lpmax_{k}")
    lp_aktuell = l2.number_input("LP aktuell", 0, 999, int(bogen.get("lp_aktuell", 10)), key=f"lp_{k}")
    st.progress(min(lp_aktuell / lp_max, 1.0))

    st.subheader("Inventar")
    inv_df = st.data_editor(
        inventar_zu_df(bogen.get("inventar", [])),
        num_rows="dynamic", key=f"inv_{k}",
        column_config={"Anzahl": st.column_config.NumberColumn("Anzahl", min_value=0, step=1)},
    )

    st.subheader("Notizen")
    notizen = st.text_area("Hintergrund, Ausrüstung, Ziele …", value=bogen.get("notizen", ""),
                           height=150, key=f"notizen_{k}")

    aktueller_bogen = {
        "name": name.strip(), "klasse": klasse.strip(), "rasse": rasse.strip(),
        "stufe": int(stufe), "attribute": attribute,
        "lp_max": int(lp_max), "lp_aktuell": int(lp_aktuell),
        "inventar": df_zu_inventar(inv_df), "notizen": notizen,
    }

    b1, b2, b3, _ = st.columns([1, 1, 1, 4])
    if b1.button("💾 Speichern", type="primary"):
        if not aktueller_bogen["name"]:
            st.error("Bitte gib dem Charakter einen Namen.")
        else:
            st.session_state["bestaetigung"] = ("speichern", k)
    if auswahl != NEU and b2.button("🗑️ Löschen"):
        st.session_state["bestaetigung"] = ("loeschen", k)

    b3.download_button("⬇️ Als JSON",
                       data=json.dumps(aktueller_bogen, ensure_ascii=False, indent=2),
                       file_name=f"{aktueller_bogen['name'] or 'charakter'}.json",
                       mime="application/json")

    frage = st.session_state.get("bestaetigung")
    if frage == ("speichern", k):
        antwort = bestaetigen(
            f"„{aktueller_bogen['name']}“ wirklich speichern?", "speichern")
        if antwort and aktueller_bogen["name"]:
            charakter_speichern(besitzer, aktueller_bogen)
            # nach dem Speichern direkt in die Datenbank-Ansicht springen
            st.session_state["springe_zu"] = f"{besitzer} – {aktueller_bogen['name']}"
            st.session_state["meldung"] = f"„{aktueller_bogen['name']}“ wurde gespeichert."
            st.rerun()
    elif frage == ("loeschen", k):
        antwort = bestaetigen(f"„{auswahl}“ wirklich löschen? Das lässt sich nicht rückgängig machen.",
                              "loeschen")
        if antwort:
            charakter_loeschen(besitzer, auswahl)
            st.session_state.pop("geladen", None)
            st.session_state["meldung"] = f"„{auswahl}“ wurde gelöscht."
            st.rerun()


# ----- 4b. Seite: Handouts ansehen (nur freigegebene)
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

    st.dataframe(pd.DataFrame(alle), hide_index=True)

    st.subheader("Einzelnen Charakter ansehen")
    namen = [f"{c['spieler']} – {c['name']}" for c in alle]
    wahl = st.selectbox("Charakter", namen)
    eintrag = alle[namen.index(wahl)]
    bogen = charakter_laden(eintrag["spieler"], eintrag["name"])
    if bogen:
        if st.button("✏️ Im Charakterbogen öffnen"):
            st.session_state["springe_zu"] = wahl
            st.rerun()
        a, b = st.columns(2)
        with a:
            st.markdown(f"**{bogen['name']}** · {bogen.get('rasse', '')} {bogen.get('klasse', '')} "
                        f"· Stufe {bogen.get('stufe', 1)}")
            st.metric("Lebenspunkte", f"{bogen.get('lp_aktuell', 0)} / {bogen.get('lp_max', 0)}")
            st.write("**Attribute**")
            st.dataframe(pd.DataFrame([bogen.get("attribute", {})]), hide_index=True)
        with b:
            st.write("**Inventar**")
            st.dataframe(inventar_zu_df(bogen.get("inventar", [])), hide_index=True)
            st.write("**Notizen**")
            st.write(bogen.get("notizen") or "–")


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
                           file_name="charaktere_backup.db")
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


def sidebar_spielername():
    st.sidebar.title("🎲 PnP-Runde")
    return st.sidebar.text_input("Dein Spielername", key="spieler").strip()


def sidebar_gm_login():
    """Login-Box für den Spielleiter. Gibt zurück, ob er angemeldet ist."""
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
    return bool(st.session_state.get("gm_ok"))


def sprung_verarbeiten():
    """Nach dem Speichern bzw. aus der Spielleiter-Ansicht zum Charakter springen."""
    if "springe_zu" in st.session_state:
        ziel = st.session_state.pop("springe_zu")
        st.session_state["aktion"] = AKTION_LADEN
        st.session_state["auswahl_db"] = ziel
        st.session_state["geladen"] = ziel
        st.session_state["lade_zaehler"] = st.session_state.get("lade_zaehler", 0) + 1


def sidebar_navigation(gm_ok):
    """Menü: Spieler-Punkte immer, Spielleiter-Punkte nur nach Login."""
    optionen = SPIELER_AKTIONEN + (GM_AKTIONEN if gm_ok else [])
    if st.session_state.get("aktion") not in optionen:
        st.session_state["aktion"] = AKTION_NEU
    return st.sidebar.selectbox("Was möchtest du tun?", optionen, key="aktion")


def sidebar_beispieldaten():
    if not alle_charaktere():
        if st.sidebar.button("🧪 Beispieldaten laden"):
            beispieldaten_laden()
            st.rerun()


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

    # Sidebar
    spieler = sidebar_spielername()
    gm_ok = sidebar_gm_login()
    sprung_verarbeiten()
    aktion = sidebar_navigation(gm_ok)
    sidebar_beispieldaten()
    st.sidebar.divider()

    # Spielleiter-Seiten ohne Login sperren
    if aktion in GM_AKTIONEN and not gm_ok:
        st.stop()

    # Seite anzeigen
    if aktion in GM_SEITEN:
        GM_SEITEN[aktion]()
    elif aktion == AKTION_HANDOUTS:
        seite_handouts()
    else:
        seite_charakterbogen(aktion, spieler)


main()
