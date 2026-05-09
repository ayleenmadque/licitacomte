import time
import unicodedata

API_TICKET = "8F57D03F-2EFC-4B43-BF38-7DADD5169A7D"
API_TICKET = st.secrets["API_TICKET"]
NOTION_TOKEN = st.secrets["NOTION_TOKEN"]
API_URL = "https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json"
NOTION_DB = "d13f6cc5-3ddb-4d3a-9b71-648779c68f37"

PALABRAS_BASE = [
"capacitacion", "capacitaciones", "curso", "cursos",
@@ -75,9 +77,9 @@ def procesar(licitaciones):
cierre_str = l.get("FechaCierre", "")
try:
cierre = datetime.fromisoformat(cierre_str[:19])
            if cierre <= ahora:
            if cierre <= datetime.now():
continue
            dias = (cierre - ahora).days
            dias = (cierre - datetime.now()).days
codigo = l.get("CodigoExterno", "")
detalle_texto, organismo = obtener_detalle(codigo)
score = calcular_score(nombre) + calcular_score(detalle_texto)
@@ -96,6 +98,39 @@ def procesar(licitaciones):
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
@@ -118,5 +153,38 @@ def procesar(licitaciones):
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
    st.info("Presiona 'Cargar licitaciones' para comenzar.")
