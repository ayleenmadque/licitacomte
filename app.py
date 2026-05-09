import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import time
import unicodedata

API_TICKET = st.secrets["API_TICKET"]
NOTION_TOKEN = st.secrets["NOTION_TOKEN"]
API_URL = "https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json"
NOTION_DB = "d13f6cc5-3ddb-4d3a-9b71-648779c68f37"

PALABRAS_BASE = [
    "capacitacion", "capacitaciones", "curso", "cursos",
    "taller", "talleres", "formacion", "transformacion digital"
]

PALABRAS_SCORE = [
    "power bi", "excel", "inteligencia artificial", " ia ",
    "google workspace", "office 365", "hojas de calculo",
    "transformacion digital", "herramientas digitales", "mejora continua"
]

def normalizar(texto):
    texto = texto.lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return texto

def obtener_licitaciones():
    todas = []
    for dias_atras in range(0, 30):
        try:
            fecha = (datetime.now() - timedelta(days=dias_atras)).strftime("%d%m%Y")
            params = {"ticket": API_TICKET, "fecha": fecha}
            response = requests.get(API_URL, params=params, timeout=30)
            todas.extend(response.json().get("Listado", []))
            time.sleep(0.3)
        except:
            pass
    return todas

def obtener_detalle(codigo):
    for intento in range(3):
        try:
            params = {"ticket": API_TICKET, "codigo": codigo}
            response = requests.get(API_URL, params=params, timeout=30)
            data = response.json()
            listado = data.get("Listado", [])
            if listado:
                l = listado[0]
                organismo = l.get("Comprador", {}).get("NombreOrganismo", "")
                items = l.get("Items", {}).get("Listado", [])
                texto = " ".join([
                    i.get("NombreEspanol", "") + " " + i.get("Descripcion", "")
                    for i in items
                ])
                if organismo or texto:
                    return normalizar(texto), organismo
        except:
            pass
        time.sleep(2)
    return "", ""

def calcular_score(texto):
    return sum(1 for p in PALABRAS_SCORE if p in texto)

def procesar(licitaciones):
    ahora = datetime.now()
    resultado = []
    barra = st.progress(0, text="Analizando licitaciones...")
    total = len(licitaciones)
    for i, l in enumerate(licitaciones):
        nombre = normalizar(l.get("Nombre", ""))
        if not any(p in nombre for p in PALABRAS_BASE):
            continue
        cierre_str = l.get("FechaCierre", "")
        try:
            cierre = datetime.fromisoformat(cierre_str[:19])
            if cierre <= datetime.now():
                continue
            dias = (cierre - datetime.now()).days
            codigo = l.get("CodigoExterno", "")
            detalle_texto, organismo = obtener_detalle(codigo)
            score = calcular_score(nombre) + calcular_score(detalle_texto)
            resultado.append({
                "Nombre": l.get("Nombre", ""),
                "ID": codigo,
                "Organismo": organismo,
                "Productos": detalle_texto[:200] if detalle_texto else "",
                "Cierre": cierre_str[:16].replace("T", " "),
                "Dias restantes": dias,
                "Score": score
            })
        except:
            pass
        barra.progress((i + 1) / total, text=f"Analizando {i+1} de {total}...")
    barra.empty()
    return sorted(resultado, key=lambda x: (-x["Score"], x["Dias restantes"]))

def registrar_en_notion(nombre, id_lic, organismo, cierre, monto_disponible, monto_ofertado, tematica, modalidad, region):
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    data = {
        "parent": {"database_id": NOTION_DB},
        "properties": {
            "Nombre": {"title": [{"text": {"content": nombre}}]},
            "ID Licitacion": {"rich_text": [{"text": {"content": id_lic}}]},
            "Organismo": {"rich_text": [{"text": {"content": organismo}}]},
            "Estado": {"select": {"name": "Postulando"}},
            "Monto Disponible": {"number": monto_disponible},
            "Monto Ofertado": {"number": monto_ofertado},
            "Temática": {"multi_select": [{"name": tematica}]},
            "Modalidad": {"select": {"name": modalidad}},
            "Region": {"rich_text": [{"text": {"content": region}}]},
            "Fecha Cierre": {"date": {"start": cierre[:10]}},
            "Fecha Postulacion": {"date": {"start": datetime.now().strftime("%Y-%m-%d")}}
        }
    }
    try:
        response = requests.post(
            "https://api.notion.com/v1/pages",
            headers=headers,
            json=data,
            timeout=15
        )
        return response.status_code == 200
    except:
        return False

st.set_page_config(page_title="LicitaComte", layout="wide")
st.title("LicitaComte")
st.caption("Sistema de inteligencia de licitaciones - Perfil: COMTE")

if "resultados" not in st.session_state:
    st.session_state.resultados = []

if st.button("Cargar licitaciones"):
    with st.spinner("Cargando ultimos 30 dias..."):
        licitaciones = obtener_licitaciones()
    st.session_state.resultados = procesar(licitaciones)

if st.session_state.resultados:
    st.success(f"{len(st.session_state.resultados)} licitaciones encontradas")
    df = pd.DataFrame(st.session_state.resultados)
    busqueda = st.text_input("Buscar dentro de los resultados", placeholder="Ej: excel, power bi, Santiago...")
    if busqueda:
        mask = df.apply(lambda row: row.astype(str).str.contains(busqueda, case=False).any(), axis=1)
        df = df[mask]
        st.caption(f"{len(df)} resultados para '{busqueda}'")
    df.index = range(1, len(df) + 1)
    st.dataframe(df, use_container_width=True)

    st.divider()
    st.subheader("Registrar postulacion en Notion")
    col1, col2 = st.columns(2)
    with col1:
        id_sel = st.text_input("ID de la licitacion a registrar")
    with col2:
        monto_ofertado = st.number_input("Monto ofertado ($)", min_value=0, step=100000)

    col3, col4, col5 = st.columns(3)
    with col3:
        monto_disponible = st.number_input("Monto disponible ($)", min_value=0, step=100000)
    with col4:
        tematica = st.selectbox("Tematica", ["Power BI", "Excel", "IA", "Office 365", "Google Workspace", "Transformacion Digital", "Herramientas Digitales", "Mejora Continua"])
    with col5:
        modalidad = st.selectbox("Modalidad", ["Online", "Presencial", "Hibrido"])

    region = st.text_input("Region")

    if st.button("Registrar en Notion"):
        fila = next((r for r in st.session_state.resultados if r["ID"] == id_sel), None)
        if fila:
            ok = registrar_en_notion(
                fila["Nombre"], fila["ID"], fila["Organismo"],
                fila["Cierre"], monto_disponible, monto_ofertado,
                tematica, modalidad, region
            )
            if ok:
                st.success(f"Licitacion '{fila['Nombre']}' registrada en Notion.")
            else:
                st.error("Error al registrar. Verifica el token y el acceso a la base de datos.")
        else:
            st.warning("No se encontro ninguna licitacion con ese ID.")
else:
    st.info("Presiona 'Cargar licitaciones' para comenzar.")
