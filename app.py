import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import time
import unicodedata
from supabase import create_client, Client

# ── Credenciales ──────────────────────────────────────────────────────────────
API_TICKET    = st.secrets["API_TICKET"]
NOTION_TOKEN  = st.secrets["NOTION_TOKEN"]
NOTION_DB     = "d13f6cc5-3ddb-4d3a-9b71-648779c68f37"
SUPABASE_URL  = st.secrets["SUPABASE_URL"]
SUPABASE_KEY  = st.secrets["SUPABASE_KEY"]

API_URL = "https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json"

# ── Cliente Supabase ──────────────────────────────────────────────────────────
@st.cache_resource
def get_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Palabras clave ────────────────────────────────────────────────────────────
PALABRAS_BASE = [
    "capacitacion", "capacitaciones", "curso", "cursos",
    "taller", "talleres", "formacion", "transformacion digital"
]

PALABRAS_SCORE = [
    "power bi", "excel", "inteligencia artificial", " ia ",
    "google workspace", "office 365", "hojas de calculo",
    "transformacion digital", "herramientas digitales", "mejora continua"
]

# ── Utilidades ────────────────────────────────────────────────────────────────
def normalizar(texto):
    texto = texto.lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return texto

def calcular_score(texto):
    return sum(1 for p in PALABRAS_SCORE if p in texto)

# ── API Mercado Público ───────────────────────────────────────────────────────
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

def procesar(licitaciones):
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
                "Nombre":         l.get("Nombre", ""),
                "ID":             codigo,
                "Organismo":      organismo,
                "Productos":      detalle_texto[:200] if detalle_texto else "",
                "Cierre":         cierre_str[:16].replace("T", " "),
                "Dias restantes": dias,
                "Score":          score,
            })
        except:
            pass
        barra.progress((i + 1) / total, text=f"Analizando {i+1} de {total}...")
    barra.empty()
    return sorted(resultado, key=lambda x: (-x["Score"], x["Dias restantes"]))

# ── Supabase ──────────────────────────────────────────────────────────────────
def guardar_en_supabase(resultados):
    ahora = datetime.now().isoformat()
    filas = [
        {
            "codigo_externo": r["ID"],
            "nombre":         r["Nombre"],
            "organismo":      r["Organismo"],
            "productos":      r["Productos"],
            "cierre":         r["Cierre"],
            "dias_restantes": r["Dias restantes"],
            "score":          r["Score"],
            "actualizado":    ahora,
        }
        for r in resultados
    ]
    try:
        get_supabase().table("licitaciones").upsert(filas, on_conflict="codigo_externo").execute()
        return True
    except Exception as e:
        st.warning(f"No se pudo guardar en Supabase: {e}")
        return False

def leer_desde_supabase():
    try:
        hoy = datetime.now().strftime("%Y-%m-%d %H:%M")
        response = (
            get_supabase().table("licitaciones")
            .select("*")
            .gte("cierre", hoy)
            .order("score", desc=True)
            .order("dias_restantes")
            .execute()
        )
        return [
            {
                "Nombre":         f["nombre"],
                "ID":             f["codigo_externo"],
                "Organismo":      f["organismo"],
                "Productos":      f["productos"],
                "Cierre":         f["cierre"],
                "Dias restantes": f["dias_restantes"],
                "Score":          f["score"],
            }
            for f in (response.data or [])
        ]
    except Exception as e:
        st.warning(f"No se pudo leer desde Supabase: {e}")
        return []

def ultima_actualizacion_supabase():
    try:
        response = (
            get_supabase().table("licitaciones")
            .select("actualizado")
            .order("actualizado", desc=True)
            .limit(1)
            .execute()
        )
        if response.data:
            dt = datetime.fromisoformat(response.data[0]["actualizado"])
            return dt.strftime("%d/%m/%Y %H:%M")
    except:
        pass
    return None

# ── Notion ────────────────────────────────────────────────────────────────────
def registrar_en_notion(nombre, id_lic, organismo, cierre, monto_disponible, monto_ofertado, tematica, modalidad, region, estado):
    headers = {
        "Authorization":  f"Bearer {NOTION_TOKEN}",
        "Content-Type":   "application/json",
        "Notion-Version": "2022-06-28"
    }
    data = {
        "parent": {"database_id": NOTION_DB},
        "properties": {
            "Nombre":            {"title":       [{"text": {"content": nombre}}]},
            "ID Licitacion":     {"rich_text":   [{"text": {"content": id_lic}}]},
            "Organismo":         {"rich_text":   [{"text": {"content": organismo}}]},
            "Estado":            {"select":      {"name": estado}},
            "Monto Disponible":  {"number":      monto_disponible},
            "Monto Ofertado":    {"number":      monto_ofertado},
            "Temática":          {"multi_select":[{"name": tematica}]},
            "Modalidad":         {"select":      {"name": modalidad}},
            "Region":            {"rich_text":   [{"text": {"content": region}}]},
            "Fecha Cierre":      {"date":        {"start": cierre[:10]}},
            "Fecha Postulacion": {"date":        {"start": datetime.now().strftime("%Y-%m-%d")}},
        }
    }
    try:
        response = requests.post(
            "https://api.notion.com/v1/pages",
            headers=headers, json=data, timeout=15
        )
        return response.status_code == 200
    except:
        return False

# ── UI ────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="LicitaComte", layout="wide")
st.title("🏆 LicitaComte")
st.caption("Sistema de inteligencia de licitaciones — Perfil: COMTE")

# Session state
if "resultados" not in st.session_state:
    st.session_state.resultados = []
if "cargado_desde_supabase" not in st.session_state:
    st.session_state.cargado_desde_supabase = False
if "fila_seleccionada" not in st.session_state:
    st.session_state.fila_seleccionada = None
if "estado_accion" not in st.session_state:
    st.session_state.estado_accion = None

# Carga automática desde Supabase
if not st.session_state.cargado_desde_supabase:
    datos = leer_desde_supabase()
    if datos:
        st.session_state.resultados = datos
    st.session_state.cargado_desde_supabase = True

# Cabecera
ultima = ultima_actualizacion_supabase()
col_btn, col_info = st.columns([2, 3])
with col_btn:
    cargar = st.button("🔄 Cargar licitaciones desde API")
with col_info:
    if ultima:
        st.info(f"📅 Última actualización: **{ultima}** — mostrando datos guardados")
    else:
        st.warning("Sin datos guardados. Presiona 'Cargar licitaciones' para comenzar.")

# Proceso desde API
if cargar:
    with st.spinner("Descargando licitaciones de los últimos 30 días..."):
        licitaciones = obtener_licitaciones()
    resultados = procesar(licitaciones)
    if resultados:
        with st.spinner("Guardando en Supabase..."):
            ok = guardar_en_supabase(resultados)
        st.session_state.resultados = resultados
        st.session_state.fila_seleccionada = None
        st.session_state.estado_accion = None
        if ok:
            st.success(f"✅ {len(resultados)} licitaciones procesadas y guardadas en Supabase.")
        else:
            st.success(f"✅ {len(resultados)} licitaciones procesadas (sin guardar en Supabase).")
    else:
        st.warning("No se encontraron licitaciones relevantes.")

# ── Tabla con selección de fila ──
if st.session_state.resultados:
    st.success(f"{len(st.session_state.resultados)} licitaciones vigentes")
    df = pd.DataFrame(st.session_state.resultados)

    busqueda = st.text_input("🔍 Buscar dentro de los resultados", placeholder="Ej: excel, power bi, Santiago...")
    if busqueda:
        mask = df.apply(lambda row: row.astype(str).str.contains(busqueda, case=False).any(), axis=1)
        df = df[mask]
        st.caption(f"{len(df)} resultados para '{busqueda}'")

    df_display = df.reset_index(drop=True)
    df_display.index = range(1, len(df_display) + 1)

    st.caption("👆 Haz clic en una fila para seleccionarla")
    seleccion = st.dataframe(
        df_display,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
    )

    # Detectar fila seleccionada
    filas_sel = seleccion.selection.rows if seleccion.selection else []
    if filas_sel:
        idx = filas_sel[0]
        fila_nueva = df_display.iloc[idx].to_dict()
        if st.session_state.fila_seleccionada != fila_nueva:
            st.session_state.fila_seleccionada = fila_nueva
            st.session_state.estado_accion = None

    # ── Panel de acción ──
    if st.session_state.fila_seleccionada:
        fila = st.session_state.fila_seleccionada
        st.divider()
        st.markdown(f"**✅ Seleccionada:** {fila['Nombre']}  \n`{fila['ID']}` · {fila['Organismo']} · Cierre: {fila['Cierre']}")

        col_verde, col_amarillo, col_cancel = st.columns([2, 2, 3])
        with col_verde:
            if st.button("🟢 Postulando", use_container_width=True):
                st.session_state.estado_accion = "Postulando"
        with col_amarillo:
            if st.button("🟡 De interés", use_container_width=True):
                st.session_state.estado_accion = "De interés"
        with col_cancel:
            if st.button("✖ Cancelar", use_container_width=True):
                st.session_state.fila_seleccionada = None
                st.session_state.estado_accion = None
                st.rerun()

        # ── Formulario según acción ──
        if st.session_state.estado_accion:
            estado = st.session_state.estado_accion
            icono = "🟢" if estado == "Postulando" else "🟡"
            st.subheader(f"{icono} Registrar en Notion — {estado}")

            col1, col2 = st.columns(2)
            with col1:
                monto_ofertado = st.number_input("Monto ofertado ($)", min_value=0, step=100000)
            with col2:
                monto_disponible = st.number_input("Monto disponible ($)", min_value=0, step=100000)

            col3, col4, col5 = st.columns(3)
            with col3:
                tematica = st.selectbox("Temática", [
                    "Power BI", "Excel", "IA", "Office 365", "Google Workspace",
                    "Transformacion Digital", "Herramientas Digitales", "Mejora Continua"
                ])
            with col4:
                modalidad = st.selectbox("Modalidad", ["Online", "Presencial", "Híbrido"])
            with col5:
                region = st.text_input("Región")

            if st.button("Confirmar y registrar en Notion", type="primary"):
                ok = registrar_en_notion(
                    fila["Nombre"], fila["ID"], fila["Organismo"],
                    fila["Cierre"], monto_disponible, monto_ofertado,
                    tematica, modalidad, region, estado
                )
                if ok:
                    st.success(f"✅ '{fila['Nombre']}' registrada en Notion como **{estado}**.")
                    st.session_state.fila_seleccionada = None
                    st.session_state.estado_accion = None
                else:
                    st.error("Error al registrar. Verifica el token y el acceso a la base de datos.")
else:
    st.info("Presiona 'Cargar licitaciones' para comenzar.")
