import json
import random
import re
from datetime import datetime
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components

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

options = ["W4", "W6", "W8", "W10", "W12"]

attribute = ["Stärke", "Geschicklichkeit", "Konstitution", "Intelligenz",
             "Weisheit", "Wahrnehmung", "Erscheinung", "Charisma", "Manipulation"]

anzahl_talente = 3
max_historie = 50

# Startwerte (nur beim ersten Aufruf)
for a in attribute:
    st.session_state.setdefault(f"attr_{a}", "W4")
st.session_state.setdefault("mana_wert", 100)
st.session_state.setdefault("historie", [])
st.session_state.setdefault("portrait_data", None)
st.session_state.setdefault("portrait_version", 0)

# --- Portrait-Komponente (Canvas mit Rückgabe an Python) ---
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

PNG_PREFIX = "data:image/png;base64,"


# --- Callbacks ---
def in_historie(name, wuerfel, ergebnis):
    historie = st.session_state["historie"]
    historie.append({
        "zeit": datetime.now().strftime("%H:%M:%S"),
        "name": name,
        "wuerfel": wuerfel,
        "ergebnis": ergebnis,
    })
    del historie[:-max_historie]


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
    stufe = options.index(wuerfel) + 1  # W4 = 1, W6 = 2, ... W12 = 5
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


def wuerfel_ok(wert):
    return wert if wert in options else None


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

    # Charakter
    char = daten.get("charakter", {})
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
    for a in attribute:
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

    # Mana
    mana = daten.get("mana", {})
    st.session_state["mana_name"] = mana.get("name", "")
    prozent = mana.get("prozent")
    st.session_state["mana_wert"] = (
        max(0, min(prozent, 100)) if isinstance(prozent, int) else 100
    )

    # Talente
    talente = daten.get("talente", [])
    for i in range(anzahl_talente):
        eintrag = talente[i] if i < len(talente) and isinstance(talente[i], dict) else {}
        st.session_state[f"talent_name_{i}"] = eintrag.get("name", "")
        st.session_state[f"talent_wuerfel_{i}"] = wuerfel_ok(eintrag.get("wuerfel"))

    st.session_state["lade_status"] = ("success", "Charakterbogen geladen.")


# --- Titel ---
st.title("Charakterbogen")
st.markdown("**Miniregelwerk**")

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

for i, attribut in enumerate(attribute):
    links, mitte, rechts = st.columns([2, 5, 1], vertical_alignment="center")
    with links:
        st.write(attribut)
    with mitte:
        attribute_werte[attribut] = st.segmented_control(
            attribut,
            options=options,
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

for i in range(anzahl_talente):
    links, mitte, rechts = st.columns([2, 5, 1], vertical_alignment="center")
    with links:
        name = st.text_input(
            f"Name {i + 1}",
            key=f"talent_name_{i}",
            placeholder="Talent",
            label_visibility="collapsed",
        )
    with mitte:
        wuerfel = st.segmented_control(
            f"Würfel {i + 1}",
            options=options,
            key=f"talent_wuerfel_{i}",
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

# --- Speichern / Laden ---
st.header("Speichern / Laden")

daten = {
    "charakter": {
        "name": char_name,
        "alter": char_alter,
        "aussehen": char_aussehen,
    },
    "portrait": portrait_data,
    "attribute": attribute_werte,
    "hp": {"aktuell": hp_aktuell, "maximum": hp_max},
    "mana": {"name": mana_name, "prozent": mana_wert},
    "talente": talente_werte,
}

json_text = json.dumps(daten, ensure_ascii=False, indent=2)

# Dateiname aus dem Charakternamen (unerlaubte Zeichen entfernen)
dateiname = re.sub(r'[\\/:*?"<>|]', "", char_name or "").strip()[:50]
if not dateiname:
    dateiname = "charakterbogen"

st.download_button(
    label="Charakterbogen als JSON herunterladen",
    data=json_text,
    file_name=f"{dateiname}.json",
    mime="application/json",
)

with st.expander("Charakterbogen laden"):
    st.file_uploader(
        "JSON-Datei auswählen",
        type="json",
        key="json_upload",
        on_change=json_laden,
    )
    status = st.session_state.get("lade_status")
    if status:
        getattr(st, status[0])(status[1])
