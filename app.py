import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import time
import unicodedata

API_TICKET = "8F57D03F-2EFC-4B43-BF38-7DADD5169A7D"
API_URL = "https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json"

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
            if cierre <= ahora:
                continue
            dias = (cierre - ahora).days
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
else:
    st.info("Presiona 'Cargar licitaciones' para comenzar.")