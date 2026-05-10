import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import time
import unicodedata
from supabase import create_client, Client

# ── Credenciales ──────────────────────────────────────────────────────────────
API_TICKET   = st.secrets["API_TICKET"]
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

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

ESTADOS = ["De interés", "Postulando", "Adjudicada", "Perdida", "Desierta"]

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
                region    = l.get("Comprador", {}).get("RegionUnidad", "")
                monto     = l.get("MontoEstimado", 0) or 0
                items     = l.get("Items", {}).get("Listado", [])
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
            dias   = (cierre - datetime.now()).days
            codigo = l.get("CodigoExterno", "")
            productos, organismo, region, monto, raw = obtener_detalle(codigo)
            score = calcular_score(nombre) + calcular_score(productos)
            resultado.append({
                "Nombre":         l.get("Nombre", ""),
                "ID":             codigo,
                "Organismo":      organismo,
                "Productos":      productos[:200] if productos else "",
                "Cierre":         cierre_str[:16].replace("T", " "),
                "Dias restantes": dias,
                "Score":          score,
                "Region":         region,
                "Monto":          monto,
                "_raw":           raw,
            })
        except:
            pass
        barra.progress((i + 1) / total, text=f"Analizando {i+1} de {total}...")
    barra.empty()
    return sorted(resultado, key=lambda x: (-x["Score"], x["Dias restantes"]))

# ── Supabase: licitaciones ────────────────────────────────────────────────────
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
                "Region":         "",
                "Monto":          0,
                "_raw":           {},
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

# ── Supabase: postulaciones ───────────────────────────────────────────────────
def registrar_postulacion(fila, estado):
    try:
        get_supabase().table("postulaciones").insert({
            "codigo_externo":  fila["ID"],
            "nombre":          fila["Nombre"],
            "organismo":       fila["Organismo"],
            "productos":       fila.get("Productos", ""),
            "region":          fila.get("Region", ""),
            "monto_estimado":  int(fila.get("Monto", 0)),
            "cierre":          fila["Cierre"],
            "estado":          estado,
            "fecha_registro":  datetime.now().isoformat(),
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

# ── UI ────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="LicitaSimple", layout="wide")
st.title("LicitaSimple")
st.caption("Sistema de inteligencia de licitaciones — Perfil: COMTE")

if "resultados" not in st.session_state:
    st.session_state.resultados = []
if "cargado_desde_supabase" not in st.session_state:
    st.session_state.cargado_desde_supabase = False
if "fila_seleccionada" not in st.session_state:
    st.session_state.fila_seleccionada = None
if "estado_accion" not in st.session_state:
    st.session_state.estado_accion = None

if not st.session_state.cargado_desde_supabase:
    datos = leer_desde_supabase()
    if datos:
        st.session_state.resultados = datos
    st.session_state.cargado_desde_supabase = True

tab1, tab2 = st.tabs(["🔍 Oportunidades", "📋 Mis Postulaciones"])

with tab1:
    ultima = ultima_actualizacion_supabase()
    col_btn, col_info = st.columns([2, 3])
    with col_btn:
        cargar = st.button("🔄 Cargar licitaciones desde API")
    with col_info:
        if ultima:
            st.info(f"📅 Última actualización: **{ultima}** — mostrando datos guardados")
        else:
            st.warning("Sin datos guardados. Presiona 'Cargar licitaciones' para comenzar.")

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
                st.success(f"✅ {len(resultados)} licitaciones procesadas y guardadas.")
        else:
            st.warning("No se encontraron licitaciones relevantes.")

    if st.session_state.resultados:
        st.success(f"{len(st.session_state.resultados)} licitaciones vigentes")
        df = pd.DataFrame(st.session_state.resultados)

        busqueda = st.text_input("🔍 Buscar dentro de los resultados", placeholder="Ej: excel, power bi, Santiago...")
        if busqueda:
            mask = df.apply(lambda row: row.astype(str).str.contains(busqueda, case=False).any(), axis=1)
            df = df[mask]
            st.caption(f"{len(df)} resultados para '{busqueda}'")

        df_display = df.drop(columns=["_raw"]).reset_index(drop=True)
        df_display.index = range(1, len(df_display) + 1)

        st.caption("👆 Haz clic en una fila para seleccionarla")
        seleccion = st.dataframe(
            df_display,
            use_container_width=True,
            on_select="rerun",
            selection_mode="single-row",
        )

        filas_sel = seleccion.selection.rows if seleccion.selection else []
        if filas_sel:
            fila_nueva = df.iloc[filas_sel[0]].to_dict()
            if st.session_state.fila_seleccionada != fila_nueva:
                st.session_state.fila_seleccionada = fila_nueva
                st.session_state.estado_accion = None

        if st.session_state.fila_seleccionada:
            fila = st.session_state.fila_seleccionada
            st.divider()
            st.markdown(f"**✅ Seleccionada:** {fila['Nombre']}  \n`{fila['ID']}` · {fila['Organismo']} · Cierre: {fila['Cierre']}")
            st.markdown(f"**Productos:** {fila.get('Productos','—')} · **Región:** {fila.get('Region','—')} · **Monto:** ${fila.get('Monto',0):,.0f}")

            col_verde, col_amarillo, col_cancel = st.columns([2, 2, 3])
            with col_verde:
                if st.button("🟢 Postulando", use_container_width=True):
                    ok = registrar_postulacion(fila, "Postulando")
                    if ok:
                        st.success(f"✅ '{fila['Nombre']}' registrada como **Postulando**.")
                        st.session_state.fila_seleccionada = None
                    else:
                        st.error("Error al registrar.")

            with col_amarillo:
                if st.button("🟡 De interés", use_container_width=True):
                    ok = registrar_postulacion(fila, "De interés")
                    if ok:
                        st.success(f"⭐ '{fila['Nombre']}' registrada como **De interés**.")
                        st.session_state.fila_seleccionada = None
                    else:
                        st.error("Error al registrar.")

            with col_cancel:
                if st.button("✖ Cancelar", use_container_width=True):
                    st.session_state.fila_seleccionada = None
                    st.rerun()

            # ── DEBUG: ver documentos adjuntos ──
            raw = fila.get("_raw", {})
            if raw:
                with st.expander("🔍 DEBUG — Estructura completa de la licitación"):
                    st.json(raw)

    else:
        st.info("Presiona 'Cargar licitaciones' para comenzar.")

with tab2:
    postulaciones = leer_postulaciones()

    if not postulaciones:
        st.info("Aún no tienes postulaciones registradas.")
    else:
        df_post = pd.DataFrame(postulaciones)
        col1, col2, col3, col4, col5 = st.columns(5)
        for estado, col, emoji in zip(
            ESTADOS,
            [col1, col2, col3, col4, col5],
            ["⭐", "🟢", "✅", "❌", "⬜"]
        ):
            count = len(df_post[df_post["estado"] == estado])
            col.metric(f"{emoji} {estado}", count)

        st.divider()

        filtro = st.selectbox("Filtrar por estado", ["Todos"] + ESTADOS)
        if filtro != "Todos":
            df_filtrado = df_post[df_post["estado"] == filtro]
        else:
            df_filtrado = df_post

        columnas_mostrar = ["nombre", "organismo", "region", "estado", "monto_estimado", "monto_ofertado", "monto_adjudicado", "cierre", "notas"]
        df_vista = df_filtrado[columnas_mostrar].copy()
        df_vista.columns = ["Nombre", "Organismo", "Región", "Estado", "Monto Estimado", "Monto Ofertado", "Monto Adjudicado", "Cierre", "Notas"]
        df_vista.index = range(1, len(df_vista) + 1)

        seleccion_crm = st.dataframe(
            df_vista,
            use_container_width=True,
            on_select="rerun",
            selection_mode="single-row",
        )

        filas_crm = seleccion_crm.selection.rows if seleccion_crm.selection else []
        if filas_crm:
            idx = filas_crm[0]
            registro = df_filtrado.iloc[idx]
            id_reg = int(registro["id"])

            st.divider()
            st.subheader(f"✏️ Editar: {registro['nombre'][:60]}...")

            col_a, col_b = st.columns(2)
            with col_a:
                nuevo_estado = st.selectbox("Estado", ESTADOS, index=ESTADOS.index(registro["estado"]))
                monto_ofertado = st.number_input("Monto ofertado ($)", value=int(registro.get("monto_ofertado") or 0), step=100000)
            with col_b:
                monto_adjudicado = st.number_input("Monto adjudicado ($)", value=int(registro.get("monto_adjudicado") or 0), step=100000)
                modalidad = st.selectbox("Modalidad", ["", "Online", "Presencial", "Híbrido"],
                    index=["", "Online", "Presencial", "Híbrido"].index(registro.get("modalidad") or ""))

            notas = st.text_area("Notas", value=registro.get("notas") or "")

            if st.button("💾 Guardar cambios", type="primary"):
                ok = actualizar_postulacion(id_reg, {
                    "estado":           nuevo_estado,
                    "monto_ofertado":   monto_ofertado,
                    "monto_adjudicado": monto_adjudicado,
                    "modalidad":        modalidad,
                    "notas":            notas,
                })
                if ok:
                    st.success("✅ Cambios guardados.")
                    st.rerun()
                else:
                    st.error("Error al guardar.")
