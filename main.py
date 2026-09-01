import random
import base64
import json
import os
import time
from pathlib import Path

import streamlit as st



st.set_page_config(layout="wide", page_title="Coffeecrawler Charakterbogen", page_icon="CoffeCrawler.jpg")
st.html(Path(__file__).parent / "styles.css")


################################## region 1. INITIALISIERUNG DES SESSION STATES

# Standardwerte für einen leeren Charakterbogen
standard_werte = {
    "char_name": "",
    "Spielername": "",
    "Volksangehörigkeit": "",
    "Geschlecht": "",
    "Aussehen": "",
    "Erster Eindruck": "",
    "Level": 1,
    "Lebenspunkte": 43,
    "Charisma": 40,
    "Manipulation": 40,
    "Erscheinung": 40,
    "Intelligenz": 40,
    "Weisheit": 40,
    "Wahrnehmung": 40,
    "Stärke": 40,
    "Geschick": 40,
    "Konstitution": 40,
    "Steigerungspunkte": 40,
    "Diredare": "",
    "Erlernte Fähigkeiten": "",
    "Beruf": "",
    "Hintergrund": "",
    "Ziele": "",
    "Charaktereigenschaften": "",
    "Ideale": "",
    "Bindung": "",
    "Makel": "",
    "Ängste": "",
    "Notizen": "",
    "bild_name": "Kein Bild",
    "bild_base64": "",
    "zähler1": 0,
    "zähler2": 0,
    "zähler3": 0,
    "Hotslots": 2,
    "skill1": "",
    "skill_1_kosten" : 0,
    "skill_1_aktiv" : False,
    "skill2": "",
    "skill_2_kosten" : 0,
    "skill_2_aktiv" : False,
    "Skillenergie" : 20,
    "max_Skillenergie" : 20

}

ATTRIBUTE_LISTE = [
    "Charisma", "Manipulation", "Erscheinung", "Intelligenz",
    "Weisheit", "Wahrnehmung", "Stärke", "Geschick", "Konstitution",
]

anzahl_talente = 10
anzahl_item = 15
anzahl_kampftalente = 6
anzahl_tricks = 6

# Talente initialisieren
for i in range(1, anzahl_talente + 1):
    st.session_state.setdefault(f"TalentWert {i}", 0)
    st.session_state.setdefault(f"Talent {i}", "")

# Inventar initialisieren
for i in range(1, anzahl_item + 1):
    st.session_state.setdefault(f"itemmenge {i}", 0)
    st.session_state.setdefault(f"item {i}", "")

# Kampftalente initialisieren (Attacke/Probe/Reichweite/Schaden pro Zeile)
for i in range(1, anzahl_kampftalente + 1):
    st.session_state.setdefault(f"Attacke {i}", "")
    st.session_state.setdefault(f"Probe_Kampf {i}", "")
    st.session_state.setdefault(f"Reichweite {i}", "")
    st.session_state.setdefault(f"Schaden {i}", "")

# Tricks initialisieren (Trick/Probe/Reichweite/Schaden pro Zeile)
for i in range(1, anzahl_tricks + 1):
    st.session_state.setdefault(f"Trick {i}", "")
    st.session_state.setdefault(f"Probe_Trick {i}", "")
    st.session_state.setdefault(f"Reichweite_Trick {i}", "")
    st.session_state.setdefault(f"Schaden_Trick {i}", "")

for key, wert in standard_werte.items():
    st.session_state.setdefault(key, wert)

# Hotslots initialisieren (Anzahl ist dynamisch über st.session_state["Hotslots"])
for i in range(st.session_state["Hotslots"]):
    st.session_state.setdefault(f"hotslot_auswahl_{i}", "")

# Alle Keys, die beim Speichern/Laden berücksichtigt werden sollen
alle_speicher_keys = list(standard_werte.keys())
for i in range(1, anzahl_talente + 1):
    alle_speicher_keys += [f"TalentWert {i}", f"Talent {i}"]
for i in range(1, anzahl_item + 1):
    alle_speicher_keys += [f"itemmenge {i}", f"item {i}"]
for i in range(1, anzahl_kampftalente + 1):
    alle_speicher_keys += [f"Attacke {i}", f"Probe_Kampf {i}", f"Reichweite {i}", f"Schaden {i}"]
for i in range(1, anzahl_tricks + 1):
    alle_speicher_keys += [f"Trick {i}", f"Probe_Trick {i}", f"Reichweite_Trick {i}", f"Schaden_Trick {i}"]
for i in range(st.session_state["Hotslots"]):
    alle_speicher_keys += [f"hotslot_auswahl_{i}"]

if "Skillenergie" not in st.session_state:
    st.session_state.Skillenergie = 20
if "max_Skillenergie" not in st.session_state:
    st.session_state.max_Skillenergie = 20


#endregion

################################## region 2. CALLBACK- UND HILFSFUNKTIONEN

def bild_verarbeiten_callback():
    """Wird aufgerufen, wenn ein neues Bild hochgeladen wird."""
    if st.session_state["neues_bild_uploader"] is not None:
        datei = st.session_state["neues_bild_uploader"]
        st.session_state["bild_base64"] = base64.b64encode(datei.getvalue()).decode("utf-8")


def json_laden_callback():
    """Wird aufgerufen, wenn eine JSON-Datei hochgeladen wird (Charakter laden)."""
    if st.session_state["json_uploader"] is not None:
        try:
            datei_inhalt = st.session_state["json_uploader"].read()
            daten = json.loads(datei_inhalt)
            _daten_in_session_state_uebernehmen(daten)
            st.toast("🔮 Charakter erfolgreich beschworen!", icon="✨")
        except Exception as e:
            st.error(f"Fehler beim Laden der Datei: {e}")


SPEICHER_ORDNER = "gespeicherte_charaktere"


def _daten_in_session_state_uebernehmen(daten):
    """Gemeinsame Logik zum Zurückschreiben geladener Daten in den session_state."""
    for key in alle_speicher_keys:
        if key in daten:
            st.session_state[key] = daten[key]

    # Hotslots gesondert behandeln: die Anzahl kann von der aktuellen
    # abweichen (mehr oder weniger als jetzt vorhanden), deshalb wird
    # hier explizit über die in der Datei gespeicherte Anzahl iteriert.
    anzahl_hotslots_geladen = daten.get("Hotslots", st.session_state.get("Hotslots", 0))
    for i in range(anzahl_hotslots_geladen):
        hotslot_key = f"hotslot_auswahl_{i}"
        if hotslot_key in daten:
            st.session_state[hotslot_key] = daten[hotslot_key]


def charakter_lokal_speichern():
    """Speichert den aktuellen Charakter direkt als Datei auf der Festplatte."""
    try:
        os.makedirs(SPEICHER_ORDNER, exist_ok=True)
        charakter_daten = {key: st.session_state[key] for key in alle_speicher_keys}
        dateiname = f"charakter_{st.session_state['char_name'] or 'unbenannt'}.json"
        pfad = os.path.join(SPEICHER_ORDNER, dateiname)
        with open(pfad, "w", encoding="utf-8") as f:
            json.dump(charakter_daten, f, indent=4)
        st.session_state["_zuletzt_gespeicherter_pfad"] = pfad
        st.toast(f"💾 Gespeichert: {dateiname}", icon="✅")
    except Exception as e:
        st.error(f"Fehler beim lokalen Speichern: {e}")


def charakter_lokal_laden():
    """Lädt den zuletzt lokal gespeicherten Charakter direkt von der Festplatte."""
    try:
        dateiname = f"charakter_{st.session_state['char_name'] or 'unbenannt'}.json"
        pfad = os.path.join(SPEICHER_ORDNER, dateiname)
        if not os.path.exists(pfad):
            st.error(f"Keine Speicherdatei gefunden: {dateiname}")
            return
        with open(pfad, "r", encoding="utf-8") as f:
            daten = json.load(f)
        _daten_in_session_state_uebernehmen(daten)
        st.toast(f"📂 Geladen: {dateiname}", icon="✨")
    except Exception as e:
        st.error(f"Fehler beim lokalen Laden: {e}")


def attribut_aendern(attribut, delta):
    """Erhöht/verringert ein Attribut um delta und passt die Steigerungspunkte an."""
    st.session_state[attribut] += delta
    st.session_state["Steigerungspunkte"] -= 2 * delta


def level_erhoehen():
    st.session_state["Level"] += 1
    st.session_state["Steigerungspunkte"] += 4
    st.session_state.Lebenspunkte += 3


def level_weniger():
    st.session_state["Level"] -= 1
    st.session_state["Steigerungspunkte"] -= 4
    st.session_state.Lebenspunkte -= 3


def talent_erhoehen(i):
    st.session_state[f"TalentWert {i}"] += 1
    st.session_state["Steigerungspunkte"] -= 2


def talent_verringern(i):
    st.session_state[f"TalentWert {i}"] -= 1
    st.session_state["Steigerungspunkte"] += 2

def kampftalent_erhoehen(i):
    st.session_state[f"kampftalentemenge {i}"] += 1
    st.session_state["Steigerungspunkte"] -= 2


def kampftalent_verringern(i):
    st.session_state[f"kampftalentemenge {i}"] -= 1
    st.session_state["Steigerungspunkte"] += 2

def kräft_neu_zuweisen():
    for key, wert in standard_werte.items():
        if key not in st.session_state:
            st.session_state[key] = wert


def skillenergie_plus():
    st.session_state.Skillenergie += 1
def skillenergie_minus():
    st.session_state.Skillenergie -= 1

def max_Skillenergie_plus():
    st.session_state.max_Skillenergie += 1
def skill_aktivieren():
    st.session_state.Skillenergie -= st.session_state.skill_1_kosten
    if st.session_state.Skillenergie <= -1:
        st.session_state.Lebenspunkte -= st.session_state.skill_1_kosten
def skill_2_aktivieren():
    st.session_state.Skillenergie -= st.session_state.skill_2_kosten
    if st.session_state.Skillenergie <= -1:
        st.session_state.Lebenspunkte -= st.session_state.skill_2_kosten



WÜRFEL_SEITEN = {"": 0 ,"W4": 4, "W6": 6, "W8": 8, "W10": 10, "W12": 12, "W20": 20, "W100": 100}


def würfel_würfeln(würfel):
    return random.randint(1, WÜRFEL_SEITEN[würfel])

# endregion

################################## region 3. SIDEBAR

with st.sidebar:
    st.sidebar.header("Charakter")

    st.header("📜 Regelwerk")
    st.selectbox("Wähle das Regelwerk", options=["Standard", "Miniregelwerk"])
    st.button("Regelwerk einsehen")

    st.divider()

    st.subheader("Schnellspeichern (lokal)")
    col_lokal_speichern, col_lokal_laden = st.columns(2)
    with col_lokal_speichern:
        st.button(
            "💾 Speichern",
            on_click=charakter_lokal_speichern,
            use_container_width=True,
        )
    with col_lokal_laden:
        st.button(
            "📂 Laden",
            on_click=charakter_lokal_laden,
            use_container_width=True,
        )
    st.caption("Speichert lokal unter „gespeicherte_charaktere/“ – funktioniert nur, wenn die App lokal läuft.")

    st.divider()

    st.subheader("Charakter laden")
    st.file_uploader(
        "JSON-Datei hochladen",
        type=["json"],
        key="json_uploader",
        on_change=json_laden_callback,
        label_visibility="collapsed",
    )

    st.divider()

    st.subheader("Charakter exportieren")
    charakter_daten = {key: st.session_state[key] for key in alle_speicher_keys}
    json_string = json.dumps(charakter_daten, indent=4)
    dateiname = f"charakter_{st.session_state['char_name'] or 'unbenannt'}.json"

    st.download_button(
        label="💾 Als JSON speichern",
        data=json_string,
        file_name=dateiname,
        mime="application/json",
        use_container_width=True,
    )

    st.divider()

    with st.container():
        # 1. Würfelart wählen
        typ = st.selectbox(f"Wähle deinen Würfel", options=list(WÜRFEL_SEITEN.keys()), key=f"type_")
        seiten = WÜRFEL_SEITEN[typ]

        # 2. Anzahl wählen
        anzahl = st.slider(f"Wähle die Anzahl", min_value=1, max_value=10, key=f"slider")

        # 3. Würfeln-Button
        if st.button(f"Station  werfen ({anzahl}{typ})", key=f"btn"):
            gesamt = 0

            # So oft würfeln wie im Slider eingestellt
            for e in range(anzahl):
                gesamt += random.randint(1, seiten)

            st.success(f"Ergebnis: {gesamt}")

#endregion




st.html('<p id="mein_mittelalter_header"> Coffeecrawler Pen and Paper Charakterbogen 📑</p>')

tab_Übersicht, tab_Charakter, tab_Talente_Attribute, tab_Skills, tab_Inventar, tab_Notizen, tab_sessionstate = st.tabs(
    ["Übersicht", "Charakter Details", "Attribute und Talente", "Skills und Tricks", "Inventar", "Notizen", "Sessionstate"],
    key="grosse_tabs"
)

################################## region 4.1 Übersicht

with tab_Übersicht:
    col_Details, col_Werte, col_Kampf, col_Portrait = st.columns(4)

    with col_Details:
        with st.container(border=True, key="CSS_Charakterdetails"):
            st.subheader("Charakter")
            st.html(f"🏷️Charaktername:&emsp; {st.session_state['char_name']}")

            st.subheader("👤 Porträt")
            if st.session_state["bild_base64"] != "":
                bild_bytes = base64.b64decode(st.session_state["bild_base64"])
                st.image(bild_bytes, use_container_width=True)
                st.caption(f"Datei: {st.session_state['char_name'] or 'Der namenlos geborene von irgendwoher'}")
            else:
                st.info("Dein Held hat noch kein Gesicht.")

            with st.expander("Stammdaten"):
                st.html(f"Volkszugehörigkeit:&emsp; {st.session_state['Volksangehörigkeit']}")
                st.html(f"Geschlecht:&emsp; {st.session_state['Geschlecht']}")
                st.html(f"Aussehen:&emsp; {st.session_state['Aussehen']}")
                st.html(f"Erster Eindruck:&emsp; {st.session_state['Erster Eindruck']}")

            with st.expander("Hintergrund"):
                st.html(f"Beruf:&emsp; {st.session_state['Beruf']}")
                st.html(f"Erlernte Fähigkeiten:&emsp; {st.session_state['Erlernte Fähigkeiten']}")
                st.html(f"Hintergrund:&emsp; {st.session_state['Hintergrund']}")
                st.html(f"Ziele:&emsp; {st.session_state['Ziele']}")

            with st.expander("Persönliches"):
                st.html(f"Charaktereigenschaften:&emsp; {st.session_state['Charaktereigenschaften']}")
                st.html(f"Ideale:&emsp; {st.session_state['Ideale']}")
                st.html(f"Bindung:&emsp; {st.session_state['Bindung']}")
                st.html(f"Makel:&emsp; {st.session_state['Makel']}")
                st.html(f"Ängste:&emsp; {st.session_state['Ängste']}")

    with col_Werte:
        with st.container(border=True, key="CSS_Container_AttributeundTalente"):
            col_Attribute, col_Talente = st.columns(2)

            with col_Attribute:
                st.subheader("📊Attribute")
                st.html(f"Level: {st.session_state['Level']}")
                st.divider()
                for attr in ATTRIBUTE_LISTE:
                    st.html(f"{attr}: {st.session_state[attr]}")

            with col_Talente:
                st.subheader("Talente")
                with st.container():
                    col_wert, col_name = st.columns([1, 10])
                    with col_wert:
                        for i in range(1, anzahl_talente + 1):
                            talent_wert = st.session_state.get(f"TalentWert {i}", 0)
                            if talent_wert >= 1:
                                st.html(f'<p class=st-key-Talentwerte>{talent_wert}</p>')
                    with col_name:
                        for i in range(1, anzahl_talente + 1):
                            talent = st.session_state.get(f"Talent {i}", "")
                            st.html(f'<p class=st-key-Talentwerte>{talent}</p>')

    with col_Kampf:
        with st.container(border=True):
            st.subheader("Kampf")
            Übersicht_Attacke, Übersicht_Probe, Übersicht_Reichweite, Übersicht_Schaden = st.columns([4,2,1,2])

            with Übersicht_Attacke:
                st.html(f'<p class=st-key-Talentwerte>Attacke</p>')
                for i in range(1, anzahl_kampftalente + 1):
                    a = st.session_state.get(f"Attacke {i}", "")
                    st.html(f'<p class=st-key-Talentwerte>{a}</p>')

            with Übersicht_Probe:
                st.html(f'<p class=st-key-Talentwerte>Probe</p>')
                for i in range(1, anzahl_kampftalente + 1):
                    b = st.session_state.get(f"Probe_Kampf {i}", "")
                    st.html(f'<p class=st-key-Talentwerte>{b}</p>')


            with Übersicht_Reichweite:
                st.html(f'<p class=st-key-Talentwerte>RW</p>')
                for i in range(1, anzahl_kampftalente + 1):
                    c = st.session_state.get(f"Reichweite {i}", "")
                    st.html(f'<p class=st-key-Talentwerte>{c}</p>')

            with Übersicht_Schaden:
                st.html(f'<p class=st-key-Talentwerte>Schaden</p>')
                for i in range(1, anzahl_kampftalente + 1):
                    d = st.session_state.get(f"Schaden {i}", "")
                    st.html(f'<p class=st-key-Talentwerte>{d}</p>')

        with st.expander("Skills"):
            st.slider("Skillenergie", min_value=0, max_value=st.session_state.max_Skillenergie,
                      value=st.session_state.Skillenergie, key= "Skillenergie")
            Skillenerige_Minus, Skillenergie_Plus, _ = st.columns([1, 1, 3])
            with Skillenergie_Plus:
                st.button("+1", on_click=skillenergie_plus,
                          disabled=(st.session_state.Skillenergie == st.session_state.max_Skillenergie))
            with Skillenerige_Minus:
                st.button("-1", on_click=skillenergie_minus)



            st.html(f'<p class=st-key-Talentwerte>{st.session_state["skill1"]}</p>')

            st.button("Skill aktvieren", on_click=skill_aktivieren)

            st.html(f'<p class=st-key-Talentwerte>{st.session_state["skill2"]}</p>')

            st.button("Skil2 aktvieren", on_click=skill_aktivieren)

        with st.expander("Tricks"):

            Übersicht_Trick_Attacke, Übersicht_Trick_Probe, Übersicht_Trick_Reichweite, Übersicht_Trick_Schaden = st.columns([4, 2, 1, 2])

            with Übersicht_Trick_Attacke:
                st.html(f'<p class=st-key-Talentwerte>Attacke</p>')
                for i in range(1, anzahl_tricks + 1):
                    aa = st.session_state.get(f"Trick {i}", "")
                    st.html(f'<p class=st-key-Talentwerte>{aa}</p>')

            with Übersicht_Trick_Probe:
                st.html(f'<p class=st-key-Talentwerte>Probe</p>')
                for i in range(1, anzahl_tricks + 1):
                    bb = st.session_state.get(f"Probe_Trick {i}", "")
                    st.html(f'<p class=st-key-Talentwerte>{bb}</p>')

            with Übersicht_Trick_Reichweite:
                st.html(f'<p class=st-key-Talentwerte>RW</p>')
                for i in range(1, anzahl_tricks + 1):
                    cc = st.session_state.get(f"Reichweite_Trick {i}", "")
                    st.html(f'<p class=st-key-Talentwerte>{cc}</p>')

            with Übersicht_Trick_Schaden:
                st.html(f'<p class=st-key-Talentwerte>Schaden</p>')
                for i in range(1, anzahl_tricks + 1):
                    dd = st.session_state.get(f"Schaden_Trick {i}", "")
                    st.html(f'<p class=st-key-Talentwerte>{dd}</p>')

    with col_Portrait:

        with st.container(border=True):

            def hp_einsup():
                st.session_state.Lebenspunkte += 1
            def hp_fünfup():
                st.session_state.Lebenspunkte += 5
            def hp_einsdown():
                st.session_state.Lebenspunkte -= 1
            def hp_fünfdown():
                st.session_state.Lebenspunkte -= 5

            st.subheader("Lebenspunkte")
            col_Lebenspunkte, col_LP_up, col_Lp_down = st.columns(3)
            with col_Lebenspunkte:
                st.header(st.session_state.Lebenspunkte)
            with col_LP_up:
                st.button("LP+1", on_click=hp_einsup)
                st.button("LP+5", on_click=hp_fünfup)
            with col_Lp_down:
                st.button("LP-1", on_click=hp_einsdown)
                st.button("LP-5", on_click=hp_fünfdown)


        with st.container(border=True):
            st.subheader("Zähler")
            col_zähler1, col_zähler2, col_zähler3 = st.columns(3)
            with col_zähler1:
                st.number_input("Zähler 1", min_value=0, max_value=10, step=1, label_visibility="collapsed", key="zähler1")
            with col_zähler2:
                st.number_input("Zähler 2", min_value=0, max_value=10, step=1, label_visibility="collapsed", key="zähler2")
            with col_zähler3:
                st.number_input("Zähler 3", min_value=0, max_value=10, step=1, label_visibility="collapsed", key="zähler3")

        with st.expander("Inventar"):
            col_itemmenge, col_item = st.columns([1, 100])

            with col_itemmenge:
                for i in range(1, anzahl_item + 1):
                    wert = st.session_state.get(f"itemmenge {i}", 0)
                    if wert >= 1:
                        st.html(f'<p class=st-key-Talentwerte>{wert}</p>')

            with col_item:
                for i in range(1, anzahl_item + 1):
                    wert_item = st.session_state.get(f"item {i}", "")
                    st.html(f'<p class=st-key-Talentwerte>{wert_item}</p>')

            diredare = st.session_state["Diredare"]
            st.html(f'<p class=st-key-Talentwerte>🤑Diredare:&emsp;{diredare}</p>')

        with st.container(border=True, key="Hotslots_Übersicht"):
            st.subheader("Hotslots")

            optionen = [""]
            for i in range(1, anzahl_item + 1):
                key = f"item {i}"
                if st.session_state[key].strip():
                    optionen.append(st.session_state[key])

            menge_hotslots = st.session_state["Hotslots"]
            for i in range(menge_hotslots):
                st.selectbox(f"Hotslot {i}", options=optionen, key=f"hotslot_auswahl_{i}", label_visibility="collapsed")

#endregion

################################## region 4.2 Charakterbeschreibung

with tab_Charakter:
    col_Details, col_Hintergrund, col_Persönlichkeit, col_Portrait = st.columns(4)

    with col_Details:
        st.header("📝 Stammdaten")
        st.text_input("Charaker Name", key="char_name")
        st.text_input("Volksangehörigkeit:", key="Volksangehörigkeit")
        st.text_input("Geschlecht:", key="Geschlecht")
        st.text_area("Aussehen:", key="Aussehen", height=150)
        st.text_area("Erster Eindruck:", key="Erster Eindruck", height=150)

    with col_Hintergrund:
        st.header("Hintergrund")
        st.text_input("Beruf:", key="Beruf")
        st.text_area("Erlernte Fähigkeiten:", key="Erlernte Fähigkeiten", height=150)
        st.text_area("Hintergrund:", key="Hintergrund", height=150)
        st.text_area("Ziele:", key="Ziele", height=150)

    with col_Persönlichkeit:
        st.header("Persönlichkeit")
        st.text_input("Charaktereigenschaften", key="Charaktereigenschaften")
        st.text_input("Ideale", key="Ideale")
        st.text_input("Bindung", key="Bindung")
        st.text_input("Makel", key="Makel")
        st.text_input("Ängste", key="Ängste")

    with col_Portrait:
        st.subheader("Porträt einfügen")

        if st.session_state["bild_base64"] != "":
            bild_bytes = base64.b64decode(st.session_state["bild_base64"])
            st.image(bild_bytes, use_container_width=True)
            st.caption(f"Name: {st.session_state['char_name'] or 'Der namenlos geborene von irgendwoher'}")

        st.file_uploader(
            "Bild auswählen",
            type=["png", "jpg", "jpeg"],
            key="neues_bild_uploader",
            on_change=bild_verarbeiten_callback,
            label_visibility="collapsed",
        )

#endregion

################################## region 4.3 ATTRIBUTE UND TALENTE (Steigerung)

with tab_Talente_Attribute:

    @st.fragment
    def attr_ändern():
        col_Attribute, col_Talente, col_Kampf = st.columns(3)

        with col_Attribute:
            with st.container(key="Attributswerte2"):
                st.subheader("Level")
                with st.container(horizontal=True):
                    st.button("Level +1", on_click=level_erhoehen, use_container_width=True)
                    st.html(f"Level: {st.session_state['Level']}")
                    st.button("Level -1", on_click=level_weniger, use_container_width=True)

                st.divider()
                st.subheader("Attribute")

                for attr in ATTRIBUTE_LISTE:
                    with st.container(horizontal=True):
                        st.button(
                            f"{attr} +1", key=f"btn_{attr}_plus", on_click=attribut_aendern,
                            args=(attr, 1), use_container_width=True
                        )
                        st.html(f"{attr}: {st.session_state[attr]}")
                        st.button(
                            f"{attr} -1", key=f"btn_{attr}_minus", on_click=attribut_aendern,
                            args=(attr, -1), use_container_width=True
                        )

                st.space()
                st.html(f"Steigerungspunkte: {st.session_state['Steigerungspunkte']}")

        with col_Talente:
            st.subheader("Talente")
            with st.container(key="Talente"):
                col_text, col_plus, col_minus, col_Talent = st.columns([2, 1, 1, 15], vertical_alignment="center")

                with col_text:
                    for i in range(1, anzahl_talente + 1):
                        talent_wert = st.session_state.get(f"TalentWert {i}")

                        st.html(f'<p class=st-key-TalentwerteSpeicher>{talent_wert}</p>')


                with col_plus:
                    for i in range(1, anzahl_talente + 1):
                        st.button(
                            "+", key=f"talent_plus_{i}", on_click=talent_erhoehen, args=(i,),
                        )

                with col_minus:
                    for i in range(1, anzahl_talente + 1):
                        st.button(
                            "-", key=f"talent_minus_{i}", on_click=talent_verringern, args=(i,),
                        )

                with col_Talent:
                    for i in range(1, anzahl_talente + 1):
                        talent_wert_key = f"Talent {i}"
                        st.text_input(f"{talent_wert_key}:", key=talent_wert_key, label_visibility="collapsed")

                st.subheader("Maximale Hotslots")

                def Hotslot_up():
                    st.session_state["Hotslots"] += 1
                def Hotslot_down():
                    st.session_state["Hotslots"] -= 1

                col_Hotslot, col_Hotslot_minus ,col_Hotslot_plus, col_Hotslot_Abstand = st.columns([2,1,1,2])
                with col_Hotslot:
                    st.html(f'<p class=st-key-Talentwerte>Maximale Hotslots: {st.session_state['Hotslots']}</p>')
                with col_Hotslot_plus:
                    st.button("+1 Hotslot", on_click=Hotslot_up)
                with col_Hotslot_minus:
                    st.button("-1 Hotslot", on_click=Hotslot_down)

                col_Skillenergie, col_man_Skillenergie = st.columns(2)

                with col_Skillenergie:
                    st.html(f'<p class=st-key-Talentwerte>Maximale Skillenergie: {st.session_state['max_Skillenergie']}</p>')
                with col_man_Skillenergie:
                    st.button("Max Skillenergie +1", on_click=max_Skillenergie_plus)


            with col_Kampf:
                with st.container(key="Handverteilung"):
                    st.subheader("Kampftalente")
                    Schadenswürfel= ["1W4", "1W8", "2W6"]
                    col_Haupthand, col_Zweihand, col_nebenhand = st.columns(3)

                    with col_Haupthand:
                        st.html(f'<p class= st-key-Handverteilung >Haupthand</p>')
                        st.text_input("Nahkampf", key="HH_Nahkampf")
                        st.text_input("Fernkampf", key="HH_Fernkampf")
                        st.selectbox("Schadenswert", Schadenswürfel, key="HH_Schadenswert")

                    with col_Zweihand:
                        st.html(f'<p class= st-key-Handverteilung >Zweihändig</p>')
                        st.text_input("Nahkampf", key="ZH_Nahkampf")
                        st.text_input("Fernkampf", key="ZH_Fernkampf")
                        st.selectbox("Schadenswert", Schadenswürfel, key="ZH_Schadenswert")

                    with col_nebenhand:
                        st.html(f'<p class= st-key-Handverteilung >Nebenhand</p>')
                        st.text_input("Nahkampf", key="NH_Nahkampf")
                        st.text_input("Fernkampf", key="NH_Fernkampf")
                        st.selectbox("Schadenswert", Schadenswürfel, key="NH_Schadenswert")


                with st.container(key="Angriffe"):
                    col_Attacke, col_Probe, col_Reichweite, col_Schaden = st.columns([3,2,1,2], vertical_alignment="center")
                    with col_Attacke:
                        st.html(f'<p class= st-key-Handverteilung >Attacke</p>')
                        for i in range(1, anzahl_kampftalente + 1):
                            Attacke_wert_key = f"Attacke {i}"
                            st.text_input(f"{Attacke_wert_key}:", key=Attacke_wert_key, label_visibility="collapsed")


                    with col_Probe:
                        st.html(f'<p class= st-key-Handverteilung >Probe</p>')
                        for i in range(1, anzahl_kampftalente + 1):
                            Probe_wert_key = f"Probe_Kampf {i}"
                            st.selectbox(f"{Probe_wert_key}:", key=Probe_wert_key, options= list(WÜRFEL_SEITEN.keys()), label_visibility="collapsed")

                    with col_Reichweite:
                        st.html(f'<p class= st-key-Handverteilung >Reichweite</p>')

                        for i in range(1, anzahl_kampftalente + 1):
                            Reichweite_wert_key = f"Reichweite {i}"
                            st.text_input(f"{Reichweite_wert_key}:", key=Reichweite_wert_key, label_visibility="collapsed")

                    with col_Schaden:
                        st.html(f'<p class= st-key-Handverteilung >Schaden</p>')
                        for i in range(1, anzahl_kampftalente + 1):
                            Schaden_wert_key = f"Schaden {i}"
                            st.selectbox(f"{Schaden_wert_key}:", key=Schaden_wert_key, options=WÜRFEL_SEITEN, label_visibility="collapsed")


        if st.button("Kräfte neu zuweisen", use_container_width=True, on_click=kräft_neu_zuweisen):


            with st.spinner("Mächte werden Übertragen"):
                # Hier läuft der schwere Code im Hintergrund
                import time
                time.sleep(2)  # Simuliert Ladezeit
            st.success("Fertig!")
            st.rerun()

    attr_ändern()

#endregion


################################## region 4.4 Skills und Tricks

with tab_Skills:
    col_skills, col_kosten_aktiv, space = st.columns([2,1,2])
    with col_skills:
        st.text_area("Slill 1", key="skill1")
        st.space("xxsmall")
        st.text_area("Slill 2", key="skill2")
    with col_kosten_aktiv:
            st.number_input("Skillenergie kosten", key="skill_1_kosten", min_value=0, value=0)
            st.toggle("Skill 1 passiv", key="skill_1_aktiv")
            st.space("small")
            st.number_input("Skillenergie kosten", key="skill_2_kosten", min_value=0, value=0)
            st.toggle("Skill 2 passiv", key="skill_2_aktiv")

    st.subheader("Tricks")
    with st.container():
        col_Attacke, col_Probe, col_Reichweite, col_Schaden = st.columns([3, 2, 1, 2], vertical_alignment="center")
        with col_Attacke:
            st.html(f'<p class= st-key-Handverteilung >Trick</p>')
            for i in range(1, anzahl_tricks + 1):
                Trick_wert_key = f"Trick {i}"
                st.text_input(f"{Trick_wert_key}:", key=Trick_wert_key, label_visibility="collapsed")

        with col_Probe:
            st.html(f'<p class= st-key-Handverteilung >Probe</p>')
            for i in range(1, anzahl_tricks + 1):
                Probe_Trick_wert_key = f"Probe_Trick {i}"
                st.selectbox(f"{Probe_Trick_wert_key}:", key=Probe_Trick_wert_key, options=list(WÜRFEL_SEITEN.keys()),
                             label_visibility="collapsed")

        with col_Reichweite:
            st.html(f'<p class= st-key-Handverteilung >Reichweite</p>')

            for i in range(1, anzahl_tricks + 1):
                Reichweite_Trick_wert_key = f"Reichweite_Trick {i}"
                st.text_input(f"{Reichweite_Trick_wert_key}:", key=Reichweite_Trick_wert_key, label_visibility="collapsed")

        with col_Schaden:
            st.html(f'<p class= st-key-Handverteilung >Schaden</p>')
            for i in range(1, anzahl_tricks + 1):
                Schaden_Trick_wert_key = f"Schaden_Trick {i}"
                st.selectbox(f"{Schaden_Trick_wert_key}:", key=Schaden_Trick_wert_key, options=WÜRFEL_SEITEN,
                             label_visibility="collapsed")

#endregion

################################## region 4.5 Inventar

with tab_Inventar:
    col_Item_Menge, col_Item, col_Abstand, col_Diredare = st.columns([1, 5, 1, 1])

    with col_Item_Menge:
        for i in range(1, anzahl_item + 1):
            itemmenge_key = f"itemmenge {i}"
            st.number_input(f"{itemmenge_key}:", key=itemmenge_key, label_visibility="collapsed", value=0)

    with col_Item:
        for i in range(1, anzahl_item + 1):
            item_key = f"item {i}"
            st.text_input(f"{item_key}:", key=item_key, label_visibility="collapsed")

    with col_Diredare:
        st.header("🤑 Diredare")
        st.text_input("Diredare", key="Diredare", label_visibility="collapsed")

#endregion

################################## region 4.6 Notizen

with tab_Notizen:
    st.header("Notizen")
    st.text_area("Notizen", key="Notizen", label_visibility="collapsed", height=850)



with tab_sessionstate:
    # 1. Sortiertes Dictionary erstellen
    sorted_session_state = {k: st.session_state[k] for k in sorted(st.session_state.keys())}

    # 2. Alphabetisch sortiert in der App anzeigen
    st.json(sorted_session_state)

#endregion
