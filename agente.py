import requests
import os
import unicodedata
from datetime import datetime, timedelta
from supabase import create_client
import time

# ── Credenciales desde variables de entorno ───────────────────────────────────
API_TICKET   = os.environ["API_TICKET"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

API_URL = "https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

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

# ── Descargar licitaciones ────────────────────────────────────────────────────
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
    print(f"Total descargadas: {len(todas)}")
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
                    return normalizar(productos), organismo, region, monto
        except:
            pass
        time.sleep(2)
    return "", "", "", 0

# ── Procesar y guardar ────────────────────────────────────────────────────────
def procesar_y_guardar(licitaciones):
    ahora = datetime.now().isoformat()
    guardadas = 0

    for l in licitaciones:
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
            productos, organismo, region, monto = obtener_detalle(codigo)
            score = calcular_score(nombre) + calcular_score(productos)

            supabase.table("licitaciones").upsert({
                "codigo_externo": codigo,
                "nombre":         l.get("Nombre", ""),
                "organismo":      organismo,
                "productos":      productos[:200] if productos else "",
                "cierre":         cierre_str[:16].replace("T", " "),
                "dias_restantes": dias,
                "score":          score,
                "actualizado":    ahora,
            }, on_conflict="codigo_externo").execute()

            guardadas += 1

        except Exception as e:
            print(f"Error procesando {l.get('CodigoExterno','')}: {e}")
            continue

    print(f"Licitaciones guardadas en Supabase: {guardadas}")

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Agente iniciado: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    licitaciones = obtener_licitaciones()
    procesar_y_guardar(licitaciones)
    print("Agente finalizado.")
