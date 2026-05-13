import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import time
import unicodedata
from supabase import create_client, Client
import google.generativeai as genai

st.set_page_config(page_title="LicitaSimple", layout="wide")

API_TICKET = st.secrets["API_TICKET"]
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

API_URL = "https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json"

st.markdown("""
<style>
.block-container {
    padding-top: 1rem !important;
    padding-left: 4rem !important;
    padding-right: 4rem !important;
    max-width: 100% !important;
}
#MainMenu, footer, header { visibility: hidden; }
.main-title {
    text-align: center;
    font-size: 42px;
    font-weight: 700;
    color: #2f3140;
    margin-bottom: 4px;
}
.subtitle {
    text-align: center;
    color: #8a8d99;
    font-size: 15px;
    margin-bottom: 26px;
}
.nav-line { border-bottom: 1px solid #e5e7eb; margin-bottom: 22px; }
div[data-testid="stRadio"] > label { display: none !important; }
div[data-testid="stRadio"] div[role="radiogroup"] {
    display: flex !important;
    flex-direction: row !important;
    gap: 28px !important;
}
div[data-testid="stRadio"] div[role="radiogroup"] label {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    padding: 0 0 12px 0 !important;
    margin: 0 !important;
    color: #4b5563 !important;
    font-size: 16px !important;
    font-weight: 500 !important;
    border-bottom: 2px solid transparent !important;
    border-radius: 0 !important;
}
div[data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked) {
    color: #ff4b4b !important;
    border-bottom: 2px solid #ff4b4b !important;
}
[data-testid="stTextInput"] input {
    border-radius: 10px !important;
    background-color: #f5f6fa !important;
    border: 1px solid #e1e4ea !important;
    height: 40px !important;
}
div.stButton > button {
    white-space: nowrap !important;
    border-radius: 10px !important;
    border: 1px solid #d8dce3 !important;
    background: #ffffff !important;
    color: #303442 !important;
    font-size: 14px !important;
    font-weight: 500 !important;
    box-shadow: none !important;
    min-height: 38px !important;
}
div.stButton > button:hover {
    background: #f7f8fa !important;
    border-color: #c9ced8 !important;
}
button[kind="secondary"].nombre-btn {
    border: none !important;
    background: transparent !important;
    text-align: left !important;
    padding: 0 !important;
    font-size: 14px !important;
    font-weight: 400 !important;
    color: #303442 !important;
    min-height: 0 !important;
    box-shadow: none !important;
}
.table-shell {
    border: 1px solid #e5e7eb;
    border-radius: 16px;
    overflow: hidden;
    background: #ffffff;
    margin-top: 12px;
}
.table-head {
    font-weight: 600;
    color: #4b5563;
    font-size: 13px;
    padding: 12px 10px;
    background: #f9fafb;
    border-bottom: 1px solid #e5e7eb;
    cursor: pointer;
    user-select: none;
}
.table-head:hover { background: #f3f4f6; }
.row-line { border-top: 1px solid #eef0f3; }
.row-text { color: #303442; font-size: 14px; padding: 10px; }
.muted { color: #7b8190; font-size: 13px; padding: 10px; }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


PALABRAS_BASE = [
    "capacitacion", "capacitaciones", "curso", "cursos",
    "taller", "talleres", "formacion", "transformacion digital"
]

PALABRAS_SCORE = [
    "power bi", "excel", "inteligencia artificial", " ia ",
    "google workspace", "office 365", "hojas de calculo",
    "transformacion digital", "herramientas digitales", "mejora continua"
]

ESTADOS = ["De interés", "Postulando", "Adjudicada", "Perdida", "Desierta"]


def normalizar(texto):
    texto = str(texto or "").lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return texto


def calcular_score(texto):
    return sum(1 for p in PALABRAS_SCORE if p in normalizar(texto))


def formato_pesos(valor):
    try:
        return f"${int(valor or 0):,}".replace(",", ".")
    except:
        return "$0"


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
                region = l.get("Comprador", {}).get("RegionUnidad", "")
                monto = l.get("MontoEstimado", 0) or 0
                items = l.get("Items", {}).get("Listado", [])
                productos = " ".join([
                    i.get("NombreProducto", "") + " " + i.get("Descripcion", "")
                    for i in items
                ])
                if organismo or productos:
                    return normalizar(productos), organismo, region, monto, l
        except:
            pass
        time.sleep(2)
    return "", "", "", 0, {}


def procesar(licitaciones):
    resultado = []
    barra = st.progress(0, text="Analizando licitaciones...")
    total = len(licitaciones) if licitaciones else 1
    for i, l in enumerate(licitaciones):
        nombre = normalizar(l.get("Nombre", ""))
        if not any(p in nombre for p in PALABRAS_BASE):
            barra.progress((i + 1) / total, text=f"Analizando {i+1} de {total}...")
            continue
        cierre_str = l.get("FechaCierre", "")
        try:
            cierre = datetime.fromisoformat(cierre_str[:19])
            if cierre <= datetime.now():
                barra.progress((i + 1) / total, text=f"Analizando {i+1} de {total}...")
                continue
            dias = (cierre - datetime.now()).days
            codigo = l.get("CodigoExterno", "")
            productos, organismo, region, monto, raw = obtener_detalle(codigo)
            score = calcular_score(nombre) + calcular_score(productos)
            resultado.append({
                "Nombre": l.get("Nombre", ""),
                "ID": codigo,
                "Organismo": organismo,
                "Productos": productos[:200] if productos else "",
                "Cierre": cierre_str[:16].replace("T", " "),
                "Dias restantes": dias,
                "Score": score,
                "Region": region,
                "Monto": monto,
                "_raw": raw,
            })
        except:
            pass
        barra.progress((i + 1) / total, text=f"Analizando {i+1} de {total}...")
    barra.empty()
    return sorted(resultado, key=lambda x: (-x["Score"], x["Dias restantes"]))


def guardar_en_supabase(resultados):
    ahora = datetime.now().isoformat()
    filas = [
        {
            "codigo_externo": r["ID"],
            "nombre": r["Nombre"],
            "organismo": r["Organismo"],
            "productos": r["Productos"],
            "cierre": r["Cierre"],
            "dias_restantes": r["Dias restantes"],
            "score": r["Score"],
            "monto": int(r.get("Monto", 0) or 0),
            "actualizado": ahora,
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
        hoy = datetime.now().strftime("%Y-%m-%d")
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
                "Nombre": f["nombre"],
                "ID": f["codigo_externo"],
                "Organismo": f["organismo"],
                "Productos": f["productos"],
                "Cierre": f["cierre"],
                "Dias restantes": f["dias_restantes"],
                "Score": f["score"],
                "Region": f.get("region", ""),
                "Monto": f.get("monto", 0) or 0,
                "_raw": {},
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


def registrar_postulacion(fila, estado):
    try:
        get_supabase().table("postulaciones").insert({
            "codigo_externo": fila["ID"],
            "nombre": fila["Nombre"],
            "organismo": fila["Organismo"],
            "productos": fila.get("Productos", ""),
            "region": fila.get("Region", ""),
            "monto_estimado": int(fila.get("Monto", 0) or 0),
            "cierre": fila["Cierre"],
            "estado": estado,
            "fecha_registro": datetime.now().isoformat(),
            "fecha_actualizacion": datetime.now().isoformat(),
        }).execute()
        return True
    except Exception as e:
        st.error(f"Error al registrar: {e}")
        return False


def leer_postulaciones():
    try:
        response = (
            get_supabase().table("postulaciones")
            .select("*")
            .order("fecha_registro", desc=True)
            .execute()
        )
        return response.data or []
    except Exception as e:
        st.warning(f"Error al leer postulaciones: {e}")
        return []


def actualizar_postulacion(id_postulacion, campos):
    try:
        campos["fecha_actualizacion"] = datetime.now().isoformat()
        get_supabase().table("postulaciones").update(campos).eq("id", id_postulacion).execute()
        return True
    except:
        return False


def leer_historico(nombre=None, productos=None):
    try:
        query = get_supabase().table("historico_adjudicaciones").select("*")
        response = query.order("fecha_adjudicacion", desc=True).limit(500).execute()
        datos = response.data or []
        if (nombre or productos) and datos:
            texto_busqueda = normalizar((nombre or "") + " " + (productos or ""))
            palabras = [p for p in texto_busqueda.split() if len(p) > 3]
            def puntaje(d):
                texto_hist = normalizar(d.get("nombre", "") + " " + d.get("productos", ""))
                return sum(1 for p in palabras if p in texto_hist)
            datos = [(d, puntaje(d)) for d in datos]
            datos = [d for d, pts in datos if pts >= 2]
            datos = sorted(datos, key=lambda d: puntaje(d), reverse=True)[:20]
        return datos
    except Exception as e:
        st.warning(f"Error al leer historico: {e}")
        return []


def calcular_metricas(datos):
    if not datos:
        return None
    montos = [d["monto_adjudicado"] for d in datos if d.get("monto_adjudicado", 0) > 0]
    oferentes = [d["numero_oferentes"] for d in datos if d.get("numero_oferentes", 0) > 0]
    empresas = [d["empresa_adjudicada"] for d in datos if d.get("empresa_adjudicada", "")]
    if not montos:
        return None
    promedio = sum(montos) / len(montos)
    from collections import Counter
    top_empresas = Counter(empresas).most_common(5)
    return {
        "total": len(datos),
        "promedio": promedio,
        "minimo": min(montos),
        "maximo": max(montos),
        "prom_oferentes": sum(oferentes) / len(oferentes) if oferentes else 0,
        "top_empresas": top_empresas,
        "recomendacion": promedio * 0.95,
    }


if "resultados" not in st.session_state:
    st.session_state.resultados = []
if "cargado_desde_supabase" not in st.session_state:
    st.session_state.cargado_desde_supabase = False
if "fila_seleccionada" not in st.session_state:
    st.session_state.fila_seleccionada = None
if "estado_accion" not in st.session_state:
    st.session_state.estado_accion = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "orden_col" not in st.session_state:
    st.session_state.orden_col = "Cierre"
if "orden_asc" not in st.session_state:
    st.session_state.orden_asc = True

if not st.session_state.cargado_desde_supabase:
    datos = leer_desde_supabase()
    if datos:
        st.session_state.resultados = datos
    st.session_state.cargado_desde_supabase = True


st.markdown('<div class="main-title">LicitaSimple</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">Sistema de inteligencia de licitaciones — Perfil: COMTE</div>', unsafe_allow_html=True)

# Navegacion por query params
params = st.query_params
tab_actual = params.get("tab", "Oportunidades")

secciones = ["Oportunidades", "Mis Postulaciones", "Inteligencia de Mercado", "Asistente IA"]
tabs_html = '<div style="display:grid; grid-template-columns:repeat(4,1fr); border-bottom:1px solid #e5e7eb; margin-bottom:16px;">'
for s in secciones:
    activo = tab_actual == s
    color = "#ff4b4b" if activo else "#6b7280"
    borde = "2px solid #ff4b4b" if activo else "2px solid transparent"
    slug = s.replace(" ", "+")
    tabs_html += f'<div onclick="window.location.replace('?tab={slug}')" style="padding:14px 0; text-align:center; font-size:15px; font-weight:500; color:{color}; border-bottom:{borde}; cursor:pointer;">{s}</div>'
tabs_html += '</div>'
st.markdown(tabs_html, unsafe_allow_html=True)

seccion = tab_actual

if seccion == "Oportunidades":
    ultima = ultima_actualizacion_supabase()
    col_btn, col_info, col_busq = st.columns([1, 1, 2])
    with col_btn:
        cargar = st.button("Cargar licitaciones desde API", use_container_width=True)
    with col_info:
        if ultima:
            st.markdown(f"""<div style="background:#eff6ff; border-radius:10px; padding:9px 14px; font-size:14px; color:#374151; border: 1px solid #bfdbfe;">Última actualización: <strong>{ultima}</strong></div>""", unsafe_allow_html=True)
        else:
            st.markdown(f"""<div style="background:#fffbeb; border-radius:10px; padding:9px 14px; font-size:14px; color:#374151; border: 1px solid #fde68a;">Sin datos guardados.</div>""", unsafe_allow_html=True)
    with col_busq:
        busqueda_global = st.text_input("Buscar", placeholder="Buscar licitación...", label_visibility="collapsed")

    if cargar:
        with st.spinner("Descargando licitaciones de los últimos 30 días..."):
            licitaciones = obtener_licitaciones()
        resultados = procesar(licitaciones)
        if resultados:
            with st.spinner("Guardando en Supabase..."):
                ok = guardar_en_supabase(resultados)
            st.session_state.resultados = resultados
            st.session_state.fila_seleccionada = None
            if ok:
                st.success(f"{len(resultados)} licitaciones procesadas y guardadas.")
        else:
            st.warning("No se encontraron licitaciones relevantes.")

    if st.session_state.resultados:
        st.success(f"{len(st.session_state.resultados)} licitaciones vigentes")

        df = pd.DataFrame(st.session_state.resultados)

        if busqueda_global:
            mask = df.apply(lambda row: row.astype(str).str.contains(busqueda_global, case=False, na=False).any(), axis=1)
            df = df[mask]
            st.caption(f"{len(df)} resultados para '{busqueda_global}'")

        # Ordenamiento
        col = st.session_state.orden_col
        asc = st.session_state.orden_asc
        if col == "Score":
            df = df.sort_values("Score", ascending=asc).reset_index(drop=True)
        elif col == "Monto":
            df = df.sort_values("Monto", ascending=asc).reset_index(drop=True)
        elif col == "Cierre":
            df = df.sort_values("Cierre", ascending=asc).reset_index(drop=True)
        else:
            df = df.sort_values("Cierre").reset_index(drop=True)

        # Encabezados con ordenamiento
        def flecha(c):
            if st.session_state.orden_col == c:
                return " ↑" if st.session_state.orden_asc else " ↓"
            return ""

        col_id, col_nom, col_cierre, col_monto, col_score, col_acc = st.columns([1.2, 4.4, 1.5, 1.4, 0.7, 2.4])
        col_id.markdown('<div class="table-head">ID</div>', unsafe_allow_html=True)
        col_nom.markdown('<div class="table-head">Nombre</div>', unsafe_allow_html=True)

        with col_cierre:
            if st.button(f"Cierre{flecha('Cierre')}", key="ord_cierre", use_container_width=True):
                if st.session_state.orden_col == "Cierre":
                    st.session_state.orden_asc = not st.session_state.orden_asc
                else:
                    st.session_state.orden_col = "Cierre"
                    st.session_state.orden_asc = True
                st.rerun()

        with col_monto:
            if st.button(f"Monto{flecha('Monto')}", key="ord_monto", use_container_width=True):
                if st.session_state.orden_col == "Monto":
                    st.session_state.orden_asc = not st.session_state.orden_asc
                else:
                    st.session_state.orden_col = "Monto"
                    st.session_state.orden_asc = True
                st.rerun()

        with col_score:
            if st.button(f"Score{flecha('Score')}", key="ord_score", use_container_width=True):
                if st.session_state.orden_col == "Score":
                    st.session_state.orden_asc = not st.session_state.orden_asc
                else:
                    st.session_state.orden_col = "Score"
                    st.session_state.orden_asc = False
                st.rerun()

        col_acc.markdown('<div class="table-head">Acción</div>', unsafe_allow_html=True)

        for i, row in df.iterrows():
            st.markdown('<div class="row-line"></div>', unsafe_allow_html=True)
            col_id, col_nom, col_cierre, col_monto, col_score, col_acc = st.columns([1.2, 4.4, 1.5, 1.4, 0.7, 2.4])

            col_id.markdown(f'<div class="muted">{row["ID"]}</div>', unsafe_allow_html=True)

            col_nom.markdown(f'<div class="row-text" style="cursor:default;">{row["Nombre"][:90]}</div>', unsafe_allow_html=True)
            if col_nom.button("▸", key=f"sel_{i}"):
                st.session_state.fila_seleccionada = row.to_dict()
                st.rerun()

            col_cierre.markdown(f'<div class="muted">{row["Cierre"]}</div>', unsafe_allow_html=True)
            col_monto.markdown(f'<div class="muted">{formato_pesos(row.get("Monto", 0))}</div>', unsafe_allow_html=True)
            col_score.markdown(f'<div class="muted">{int(row["Score"])}</div>', unsafe_allow_html=True)

            with col_acc:
                c1, c2 = st.columns([1, 1])
                if c1.button("Postular", key=f"post_{i}", use_container_width=True):
                    ok = registrar_postulacion(row.to_dict(), "Postulando")
                    if ok:
                        st.success("Registrada como Postulando.")
                        st.rerun()
                if c2.button("Interés", key=f"int_{i}", use_container_width=True):
                    ok = registrar_postulacion(row.to_dict(), "De interés")
                    if ok:
                        st.success("Registrada como De interés.")
                        st.rerun()

        if st.session_state.fila_seleccionada:
            fila = st.session_state.fila_seleccionada
            st.divider()
            col_prod, col_info = st.columns([2, 1])
            with col_prod:
                st.markdown("**Productos / descripción del servicio**")
                st.write(fila.get("Productos", "—"))
            with col_info:
                st.markdown(f"**Organismo:** {fila.get('Organismo', '—')}")
                st.markdown(f"**Monto:** {formato_pesos(fila.get('Monto', 0))}")
            if st.button("Cancelar selección", key="btn_cancelar"):
                st.session_state.fila_seleccionada = None
                st.rerun()
    else:
        st.info("Presiona 'Cargar licitaciones' para comenzar.")


elif seccion == "Mis Postulaciones":
    postulaciones = leer_postulaciones()
    if not postulaciones:
        st.info("Aún no tienes postulaciones registradas.")
    else:
        df_post = pd.DataFrame(postulaciones)
        col1, col2, col3, col4, col5 = st.columns(5)
        for estado, col in zip(ESTADOS, [col1, col2, col3, col4, col5]):
            count = len(df_post[df_post["estado"] == estado])
            col.metric(estado, count)
        st.divider()
        filtro = st.selectbox("Filtrar por estado", ["Todos"] + ESTADOS)
        if filtro != "Todos":
            df_filtrado = df_post[df_post["estado"] == filtro]
        else:
            df_filtrado = df_post
        columnas_mostrar = ["nombre", "organismo", "region", "estado", "monto_estimado", "monto_ofertado", "monto_adjudicado", "cierre", "notas"]
        columnas_existentes = [c for c in columnas_mostrar if c in df_filtrado.columns]
        df_vista = df_filtrado[columnas_existentes].copy()
        df_vista = df_vista.rename(columns={
            "nombre": "Nombre", "organismo": "Organismo", "region": "Región",
            "estado": "Estado", "monto_estimado": "Monto Estimado",
            "monto_ofertado": "Monto Ofertado", "monto_adjudicado": "Monto Adjudicado",
            "cierre": "Cierre", "notas": "Notas"
        })
        df_vista.index = range(1, len(df_vista) + 1)
        seleccion_crm = st.dataframe(df_vista, use_container_width=True, on_select="rerun", selection_mode="single-row")
        filas_crm = seleccion_crm.selection.rows if seleccion_crm.selection else []
        if filas_crm:
            idx = filas_crm[0]
            registro = df_filtrado.iloc[idx]
            id_reg = int(registro["id"])
            st.divider()
            st.subheader(f"Editar: {registro['nombre'][:60]}...")
            col_a, col_b = st.columns(2)
            with col_a:
                nuevo_estado = st.selectbox("Estado", ESTADOS, index=ESTADOS.index(registro["estado"]))
                monto_ofertado = st.number_input("Monto ofertado ($)", value=int(registro.get("monto_ofertado") or 0), step=100000)
            with col_b:
                monto_adjudicado = st.number_input("Monto adjudicado ($)", value=int(registro.get("monto_adjudicado") or 0), step=100000)
                opciones_modalidad = ["", "Online", "Presencial", "Híbrido", "Hibrido"]
                modalidad_actual = registro.get("modalidad") or ""
                modalidad = st.selectbox("Modalidad", opciones_modalidad, index=opciones_modalidad.index(modalidad_actual) if modalidad_actual in opciones_modalidad else 0)
            notas = st.text_area("Notas", value=registro.get("notas") or "")
            if st.button("Guardar cambios", type="primary"):
                ok = actualizar_postulacion(id_reg, {"estado": nuevo_estado, "monto_ofertado": monto_ofertado, "monto_adjudicado": monto_adjudicado, "modalidad": modalidad, "notas": notas})
                if ok:
                    st.success("Cambios guardados.")
                    st.rerun()
                else:
                    st.error("Error al guardar.")


elif seccion == "Inteligencia de Mercado":
    st.subheader("Inteligencia de Mercado")
    fila = st.session_state.fila_seleccionada
    if fila:
        st.caption(f"Analizando licitación seleccionada: **{fila['Nombre'][:80]}**")
        st.divider()
        col_pres, col_org = st.columns([1, 2])
        with col_pres:
            monto = fila.get("Monto", 0)
            st.metric("Presupuesto disponible", formato_pesos(monto) if monto else "No informado")
        with col_org:
            st.markdown(f"**Organismo:** {fila.get('Organismo', '—')}")
            st.markdown(f"**Cierre:** {fila.get('Cierre', '—')}")
        st.divider()
        datos = leer_historico(nombre=fila["Nombre"], productos=fila.get("Productos", ""))
        if not datos:
            st.warning("No hay datos históricos similares aún.")
        else:
            metricas = calcular_metricas(datos)
            if metricas:
                st.markdown(f"**{metricas['total']} licitaciones adjudicadas similares** encontradas")
                col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                col_m1.metric("Monto promedio adjudicado", formato_pesos(metricas["promedio"]))
                col_m2.metric("Monto mínimo", formato_pesos(metricas["minimo"]))
                col_m3.metric("Monto máximo", formato_pesos(metricas["maximo"]))
                col_m4.metric("Precio recomendado", formato_pesos(metricas["recomendacion"]))
                st.divider()
                col_rec, col_emp = st.columns([1, 1])
                with col_rec:
                    st.markdown("### Recomendación de precio")
                    st.info(f"Para ser competitivo, considera ofertar alrededor de **{formato_pesos(metricas['recomendacion'])}** (5% bajo el promedio adjudicado)")
                with col_emp:
                    st.markdown("### Empresas que más ganan")
                    for empresa, veces in metricas["top_empresas"]:
                        st.markdown(f"- **{empresa}** — {veces} adjudicación{'es' if veces > 1 else ''}")
                st.divider()
                st.markdown("### Últimas adjudicaciones similares")
                df_hist = pd.DataFrame(datos)
                columnas_hist = ["nombre", "organismo", "region", "monto_adjudicado", "empresa_adjudicada", "numero_oferentes", "fecha_adjudicacion"]
                columnas_existentes = [c for c in columnas_hist if c in df_hist.columns]
                df_hist_vista = df_hist[columnas_existentes].copy()
                df_hist_vista = df_hist_vista.rename(columns={"nombre": "Nombre", "organismo": "Organismo", "region": "Región", "monto_adjudicado": "Monto Adjudicado", "empresa_adjudicada": "Empresa Ganadora", "numero_oferentes": "N° Oferentes", "fecha_adjudicacion": "Fecha"})
                df_hist_vista.index = range(1, len(df_hist_vista) + 1)
                st.dataframe(df_hist_vista, use_container_width=True)
    else:
        st.info("Selecciona una licitación en Oportunidades para ver su inteligencia de mercado.")


elif seccion == "Asistente IA":
    st.subheader("Asistente IA — LicitaSimple")
    st.caption("Consulta sobre tus licitaciones vigentes, estrategias y más")
    GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
    if not GEMINI_API_KEY:
        st.error("Falta agregar GEMINI_API_KEY en los secrets de Streamlit.")
        st.stop()

    def contexto_licitaciones():
        datos = st.session_state.resultados or leer_desde_supabase()
        if not datos:
            return "No hay licitaciones vigentes cargadas aún."
        lines = []
        for l in datos[:15]:
            lines.append(f"- {l['Nombre']} | Organismo: {l['Organismo']} | Cierre: {l['Cierre']} | Score: {l['Score']} | Días restantes: {l['Dias restantes']}")
        return "\n".join(lines)

    SYSTEM_PROMPT = f"""Eres un asistente experto en licitaciones públicas chilenas integrado en LicitaSimple.
Perfil del usuario: capacitación, talleres, formación, transformación digital, Power BI, Excel, IA.

Licitaciones vigentes filtradas para este usuario:
{contexto_licitaciones()}

Ayuda al usuario a priorizar licitaciones, estimar conveniencia, analizar competencia y sugerir estrategias de precio."""

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Pregúntame sobre tus licitaciones..."):
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("Analizando..."):
                try:
                    genai.configure(api_key=GEMINI_API_KEY)
                    model = genai.GenerativeModel("gemini-2.0-flash")
                    gemini_history = []
                    for msg in st.session_state.chat_history[:-1]:
                        gemini_history.append({"role": "user" if msg["role"] == "user" else "model", "parts": [msg["content"]]})
                    chat = model.start_chat(history=gemini_history)
                    response = chat.send_message(f"{SYSTEM_PROMPT}\n\nUsuario: {prompt}")
                    respuesta = response.text
                except Exception as e:
                    respuesta = f"Error al conectar con Gemini: {e}"
                st.markdown(respuesta)
                st.session_state.chat_history.append({"role": "assistant", "content": respuesta})

    if st.session_state.chat_history:
        if st.button("Limpiar conversación"):
            st.session_state.chat_history = []
            st.rerun()
