import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import time
import unicodedata
from supabase import create_client, Client
import google.generativeai as genai

# Credenciales
API_TICKET   = st.secrets["API_TICKET"]
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

API_URL = "https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json"

# Cliente Supabase
@st.cache_resource
def get_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

# Palabras clave
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

# Utilidades
def normalizar(texto):
    texto = texto.lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return texto

def calcular_score(texto):
    return sum(1 for p in PALABRAS_SCORE if p in texto)

# API Mercado Publico
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

# Supabase: licitaciones
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
                "Nombre":         f["nombre"],
                "ID":             f["codigo_externo"],
                "Organismo":      f["organismo"],
                "Productos":      f["productos"],
                "Cierre":         f["cierre"],
                "Dias restantes": f["dias_restantes"],
                "Score":          f["score"],
                "Region":         "",
                "Monto":          f.get("monto", 0) or 0,
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

# Supabase: postulaciones
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

# Supabase: historico adjudicaciones
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
    minimo   = min(montos)
    maximo   = max(montos)
    prom_oferentes = sum(oferentes) / len(oferentes) if oferentes else 0
    from collections import Counter
    top_empresas = Counter(empresas).most_common(5)
    recomendacion = promedio * 0.95
    return {
        "total":           len(datos),
        "promedio":        promedio,
        "minimo":          minimo,
        "maximo":          maximo,
        "prom_oferentes":  prom_oferentes,
        "top_empresas":    top_empresas,
        "recomendacion":   recomendacion,
    }



# UI
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
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if not st.session_state.cargado_desde_supabase:
    datos = leer_desde_supabase()
    if datos:
        st.session_state.resultados = datos
    st.session_state.cargado_desde_supabase = True

tab1, tab2, tab3, tab4 = st.tabs([
    "Oportunidades",
    "Mis Postulaciones",
    "Inteligencia de Mercado",
    "Asistente IA"
])

# Tab 1: Oportunidades
with tab1:
    ultima = ultima_actualizacion_supabase()
    col_btn, col_info = st.columns([2, 3])
    with col_btn:
        cargar = st.button("Cargar licitaciones desde API")
    with col_info:
        if ultima:
            st.info(f"Ultima actualizacion: **{ultima}** — mostrando datos guardados")
        else:
            st.warning("Sin datos guardados. Presiona 'Cargar licitaciones' para comenzar.")

    if cargar:
        with st.spinner("Descargando licitaciones de los ultimos 30 dias..."):
            licitaciones = obtener_licitaciones()
        resultados = procesar(licitaciones)
        if resultados:
            with st.spinner("Guardando en Supabase..."):
                ok = guardar_en_supabase(resultados)
            st.session_state.resultados = resultados
            st.session_state.fila_seleccionada = None
            st.session_state.estado_accion = None
            if ok:
                st.success(f"{len(resultados)} licitaciones procesadas y guardadas.")
        else:
            st.warning("No se encontraron licitaciones relevantes.")

    if st.session_state.resultados:
        st.success(f"{len(st.session_state.resultados)} licitaciones vigentes")
        df = pd.DataFrame(st.session_state.resultados)

        busqueda = st.text_input("Buscar dentro de los resultados", placeholder="Ej: excel, power bi, Santiago...")
        if busqueda:
            mask = df.apply(lambda row: row.astype(str).str.contains(busqueda, case=False).any(), axis=1)
            df = df[mask]
            st.caption(f"{len(df)} resultados para '{busqueda}'")

        # Ordenar por cierre mas proximo
        df = df.sort_values("Cierre").reset_index(drop=True)

        df_display = df[["ID", "Nombre", "Cierre", "Monto", "Score"]].copy()
        df_display.index = range(1, len(df_display) + 1)

        st.caption("Haz clic en una fila para ver el detalle")
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

            st.markdown("""
<style>
.panel-fijo {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    background: var(--background-color, white);
    border-top: 1px solid rgba(0,0,0,0.1);
    padding: 12px 24px;
    z-index: 999;
    box-shadow: 0 -2px 8px rgba(0,0,0,0.08);
}
div[data-testid="column"]:has(button[kind="secondary"]) {
    display: none;
}
</style>
""", unsafe_allow_html=True)

            st.markdown(f"""
<div class="panel-fijo">
  <div style="display:grid; grid-template-columns: 2fr 1fr; gap:16px; max-width:1200px; margin-left:auto; margin-right:auto; align-items:center;">
    <div style="display:grid; grid-template-columns: 2fr 1fr; gap:16px;">
      <div>
        <p style="font-size:11px; color:gray; margin:0 0 4px;">Productos / descripcion del servicio</p>
        <p style="font-size:13px; margin:0; line-height:1.5;">{fila.get("Productos","—")[:300]}</p>
      </div>
      <div style="display:flex; flex-direction:column; gap:6px;">
        <div><span style="font-size:11px; color:gray;">Organismo</span><br><span style="font-size:13px;">{fila.get("Organismo","—")}</span></div>
        <div><span style="font-size:11px; color:gray;">Monto</span><br><span style="font-size:13px;">${fila.get("Monto",0):,.0f}</span></div>
      </div>
    </div>
    <div style="display:flex; flex-direction:column; gap:8px;">
      <button onclick="localStorage.setItem('accion_licitacion','postulando'); document.getElementById('trigger_postulando').click();" style="padding:8px 0; width:100%; cursor:pointer; border-radius:6px; border:1px solid #ccc; background:white; font-size:13px;">Postulando</button>
      <button onclick="localStorage.setItem('accion_licitacion','interes'); document.getElementById('trigger_interes').click();" style="padding:8px 0; width:100%; cursor:pointer; border-radius:6px; border:1px solid #ccc; background:white; font-size:13px;">De interes</button>
      <button onclick="localStorage.setItem('accion_licitacion','cancelar'); document.getElementById('trigger_cancelar').click();" style="padding:8px 0; width:100%; cursor:pointer; border-radius:6px; border:1px solid #ccc; background:white; font-size:13px;">Cancelar</button>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

            st.markdown("""
<style>
div[data-testid="stHorizontalBlock"] { display: none !important; }
</style>
""", unsafe_allow_html=True)

            col_verde, col_amarillo, col_cancel = st.columns([1, 1, 1])
            with col_verde:
                if st.button("Postulando", use_container_width=True, key="trigger_postulando"):
                    ok = registrar_postulacion(fila, "Postulando")
                    if ok:
                        st.success(f"'{fila['Nombre']}' registrada como Postulando.")
                        st.session_state.fila_seleccionada = None
                    else:
                        st.error("Error al registrar.")
            with col_amarillo:
                if st.button("De interes", use_container_width=True, key="trigger_interes"):
                    ok = registrar_postulacion(fila, "De interes")
                    if ok:
                        st.success(f"'{fila['Nombre']}' registrada como De interes.")
                        st.session_state.fila_seleccionada = None
                    else:
                        st.error("Error al registrar.")
            with col_cancel:
                if st.button("Cancelar", use_container_width=True, key="trigger_cancelar"):
                    st.session_state.fila_seleccionada = None
                    st.rerun()

            st.markdown("<div style='height:150px'></div>", unsafe_allow_html=True)
    else:
        st.info("Presiona 'Cargar licitaciones' para comenzar.")

# Tab 2: Mis Postulaciones
with tab2:
    postulaciones = leer_postulaciones()
    if not postulaciones:
        st.info("Aun no tienes postulaciones registradas.")
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
        df_vista = df_filtrado[columnas_mostrar].copy()
        df_vista.columns = ["Nombre", "Organismo", "Region", "Estado", "Monto Estimado", "Monto Ofertado", "Monto Adjudicado", "Cierre", "Notas"]
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
            st.subheader(f"Editar: {registro['nombre'][:60]}...")
            col_a, col_b = st.columns(2)
            with col_a:
                nuevo_estado = st.selectbox("Estado", ESTADOS, index=ESTADOS.index(registro["estado"]))
                monto_ofertado = st.number_input("Monto ofertado ($)", value=int(registro.get("monto_ofertado") or 0), step=100000)
            with col_b:
                monto_adjudicado = st.number_input("Monto adjudicado ($)", value=int(registro.get("monto_adjudicado") or 0), step=100000)
                modalidad = st.selectbox("Modalidad", ["", "Online", "Presencial", "Hibrido"],
                    index=["", "Online", "Presencial", "Hibrido"].index(registro.get("modalidad") or ""))
            notas = st.text_area("Notas", value=registro.get("notas") or "")
            if st.button("Guardar cambios", type="primary"):
                ok = actualizar_postulacion(id_reg, {
                    "estado":           nuevo_estado,
                    "monto_ofertado":   monto_ofertado,
                    "monto_adjudicado": monto_adjudicado,
                    "modalidad":        modalidad,
                    "notas":            notas,
                })
                if ok:
                    st.success("Cambios guardados.")
                    st.rerun()
                else:
                    st.error("Error al guardar.")

# Tab 3: Inteligencia de Mercado
with tab3:
    st.subheader("Inteligencia de Mercado")

    fila = st.session_state.fila_seleccionada

    if fila:
        st.caption(f"Analizando licitacion seleccionada: **{fila['Nombre'][:80]}**")
        st.divider()

        col_pres, col_org = st.columns([1, 2])
        with col_pres:
            monto = fila.get("Monto", 0)
            st.metric("Presupuesto disponible", f"${monto:,.0f}" if monto else "No informado")
        with col_org:
            st.markdown(f"**Organismo:** {fila.get('Organismo', '—')}")
            st.markdown(f"**Cierre:** {fila.get('Cierre', '—')}")

        st.divider()

        datos = leer_historico(nombre=fila["Nombre"], productos=fila.get("Productos", ""))

        if not datos:
            st.warning("No hay datos historicos similares aun. El agente los cargara en la proxima corrida.")
        else:
            metricas = calcular_metricas(datos)
            if metricas:
                st.markdown(f"**{metricas['total']} licitaciones adjudicadas similares** encontradas")

                col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                col_m1.metric("Monto promedio adjudicado", f"${metricas['promedio']:,.0f}")
                col_m2.metric("Monto minimo", f"${metricas['minimo']:,.0f}")
                col_m3.metric("Monto maximo", f"${metricas['maximo']:,.0f}")
                col_m4.metric("Precio recomendado", f"${metricas['recomendacion']:,.0f}")

                st.divider()
                col_rec, col_emp = st.columns([1, 1])

                with col_rec:
                    st.markdown("### Recomendacion de precio")
                    st.info(f"Para ser competitivo, considera ofertar alrededor de **${metricas['recomendacion']:,.0f}** (5% bajo el promedio adjudicado)")
                    if monto and metricas['promedio']:
                        if metricas['promedio'] < monto * 0.5:
                            st.warning(f"El presupuesto disponible (${monto:,.0f}) es significativamente mayor al promedio historico. Buena oportunidad.")
                        elif metricas['promedio'] > monto:
                            st.error("El promedio historico supera el presupuesto disponible. Evalua bien los costos.")

                with col_emp:
                    st.markdown("### Empresas que mas ganan")
                    for empresa, veces in metricas["top_empresas"]:
                        st.markdown(f"- **{empresa}** — {veces} adjudicacion{'es' if veces > 1 else ''}")

                st.divider()
                st.markdown("### Ultimas adjudicaciones similares")
                df_hist = pd.DataFrame(datos)
                columnas_hist = ["nombre", "organismo", "region", "monto_adjudicado", "empresa_adjudicada", "numero_oferentes", "fecha_adjudicacion"]
                df_hist_vista = df_hist[columnas_hist].copy()
                df_hist_vista.columns = ["Nombre", "Organismo", "Region", "Monto Adjudicado", "Empresa Ganadora", "N Oferentes", "Fecha"]
                df_hist_vista.index = range(1, len(df_hist_vista) + 1)
                st.dataframe(df_hist_vista, use_container_width=True)
    else:
        st.info("Selecciona una licitacion en la tab Oportunidades para ver su inteligencia de mercado.")

# Tab 4: Asistente IA
with tab4:
    st.subheader("Asistente IA — LicitaSimple")
    st.caption("Consulta sobre tus licitaciones vigentes, estrategias y mas")

    GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")

    if not GEMINI_API_KEY:
        st.error("Falta agregar GEMINI_API_KEY en los secrets de Streamlit.")
        st.stop()

    def contexto_licitaciones():
        datos = st.session_state.resultados or leer_desde_supabase()
        if not datos:
            return "No hay licitaciones vigentes cargadas aun."
        lines = []
        for l in datos[:15]:
            lines.append(
                f"- {l['Nombre']} | Organismo: {l['Organismo']} "
                f"| Cierre: {l['Cierre']} | Score: {l['Score']} "
                f"| Dias restantes: {l['Dias restantes']}"
            )
        return "\n".join(lines)

    SYSTEM_PROMPT = f"""Eres un asistente experto en licitaciones publicas chilenas integrado en LicitaSimple.
Perfil del usuario: capacitacion, talleres, formacion, transformacion digital, Power BI, Excel, IA.

Licitaciones vigentes filtradas para este usuario:
{contexto_licitaciones()}

Ayuda al usuario a:
- Priorizar que licitaciones postular
- Estimar esfuerzo y conveniencia
- Analizar la competencia
- Sugerir estrategias de precio
- Responder preguntas sobre el proceso de licitacion en Chile

Se directo, concreto y usa los datos reales de arriba cuando sea relevante."""

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Preguntame sobre tus licitaciones..."):
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
                        gemini_history.append({
                            "role": "user" if msg["role"] == "user" else "model",
                            "parts": [msg["content"]]
                        })
                    chat = model.start_chat(history=gemini_history)
                    response = chat.send_message(f"{SYSTEM_PROMPT}\n\nUsuario: {prompt}")
                    respuesta = response.text
                except Exception as e:
                    respuesta = f"Error al conectar con Gemini: {e}"
                st.markdown(respuesta)
                st.session_state.chat_history.append({"role": "assistant", "content": respuesta})

    if st.session_state.chat_history:
        if st.button("Limpiar conversacion"):
            st.session_state.chat_history = []
            st.rerun()
