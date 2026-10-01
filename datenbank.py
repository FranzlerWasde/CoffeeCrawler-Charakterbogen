"""

PnP-Charakterbogen – Einzeldatei-Version für die Online-Playground (stlite)

https://edit.share.stlite.net/

Alles in einer Datei: Datenbank (SQLite), Beispieldaten und Oberfläche.

Hinweis: In der Playground liegt die Datenbank nur im Arbeitsspeicher des Browsers.

Beim Neuladen der Seite ist sie leer -> Backup über "Spielleiter" herunterladen/einspielen.

"""

import json

import sqlite3

from contextlib import contextmanager

from datetime import datetime

from pathlib import Path

import pandas as pd

import streamlit as st

# =============================================================== EINSTELLUNGEN

GM_PASSWORT = "" # <- ändern

ATTRIBUTE = ["Stärke", "Geschick", "Konstitution", "Intelligenz", "Weisheit", "Charisma"]

INVENTAR_SPALTEN = ["Gegenstand", "Anzahl", "Notiz"]

NEU = "➕ Neuer Charakter"

DB_PATH = Path("charaktere.db")

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

klasse TEXT,

stufe INTEGER DEFAULT 1,

daten TEXT NOT NULL,

erstellt_am TEXT NOT NULL,

geaendert_am TEXT NOT NULL,

UNIQUE (spieler_id, name)

);

"""

)

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

# =============================================================== HILFSFUNKTIONEN UI

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

# =============================================================== SEITE: CHARAKTERBOGEN

def seite_charakterbogen():

st.title("🎲 Charakterbogen")

spieler = st.sidebar.text_input("Dein Spielername", key="spieler").strip()

if not spieler:

st.info("Gib links deinen Spielernamen ein (z. B. „Anna“ oder „Ben“ nach dem Laden der Beispieldaten).")

return

optionen = [NEU] + charaktere_von_spieler(spieler)

if "auswahl_naechste" in st.session_state:

st.session_state["auswahl"] = st.session_state.pop("auswahl_naechste")

if st.session_state.get("auswahl") not in optionen:

st.session_state["auswahl"] = NEU

auswahl = st.sidebar.selectbox("Charakter", optionen, key="auswahl")

bogen = leerer_bogen() if auswahl == NEU else (charakter_laden(spieler, auswahl) or leerer_bogen())

k = f"{spieler}|{auswahl}"

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

charakter_speichern(spieler, aktueller_bogen)

st.session_state["auswahl_naechste"] = aktueller_bogen["name"]

st.session_state["meldung"] = f"„{aktueller_bogen['name']}“ wurde gespeichert."

st.rerun()

if auswahl != NEU and b2.button("🗑️ Löschen"):

charakter_loeschen(spieler, auswahl)

st.session_state["meldung"] = f"„{auswahl}“ wurde gelöscht."

st.rerun()

b3.download_button("⬇️ Als JSON",

data=json.dumps(aktueller_bogen, ensure_ascii=False, indent=2),

file_name=f"{aktueller_bogen['name'] or 'charakter'}.json",

mime="application/json")

if "meldung" in st.session_state:

st.success(st.session_state.pop("meldung"))

# =============================================================== SEITE: SPIELLEITER

def seite_spielleiter():

st.title("🧙 Spielleiter-Übersicht")

pw = st.sidebar.text_input("Spielleiter-Passwort", type="password")

if pw != GM_PASSWORT:

st.info("Bitte links das Spielleiter-Passwort eingeben (Standard: spielleiter).")

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

st.divider()

st.subheader("Backup")

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

# =============================================================== START

init_db()

seite = st.sidebar.radio("Bereich", ["Charakterbogen", "Spielleiter"])

if not alle_charaktere():

if st.sidebar.button("🧪 Beispieldaten laden"):

beispieldaten_laden()

st.rerun()

st.sidebar.divider()

if seite == "Charakterbogen":

seite_charakterbogen()

else:

seite_spielleiter()



