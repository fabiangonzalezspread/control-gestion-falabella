import streamlit as st
import pandas as pd
import numpy as np
import requests
import base64
import io
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

st.set_page_config(page_title="Control de Gestión Falabella 2026", layout="wide")

def hoy_chile():
    return datetime.now(ZoneInfo("America/Santiago"))

# ============================================================
# LOGIN (mismo esquema que el panel principal: correo @spread.cl + clave)
# ============================================================
DOMINIO_PERMITIDO = "@spread.cl"

def puede_entrar():
    def credenciales_ingresadas():
        correo = st.session_state.get("login_email_input", "").strip().lower()
        clave = st.session_state.get("login_password_input", "")
        if correo.endswith(DOMINIO_PERMITIDO) and clave == st.secrets.get("APP_PASSWORD", ""):
            st.session_state["login_ok"] = True
            st.session_state["usuario_autorizado"] = correo
        else:
            st.session_state["login_ok"] = False

    if st.session_state.get("login_ok", False):
        return True

    st.markdown("### Control de Gestión Falabella 2026")
    col1, col2 = st.columns(2)
    with col1:
        st.text_input("Correo Spread", key="login_email_input", placeholder="tunombre@spread.cl")
    with col2:
        st.text_input("Contraseña", type="password", key="login_password_input")
    if st.button("Ingresar"):
        credenciales_ingresadas()
        if not st.session_state.get("login_ok", False):
            st.error(f"Correo o contraseña incorrectos (el correo debe terminar en {DOMINIO_PERMITIDO})")
    return st.session_state.get("login_ok", False)

# ============================================================
# GITHUB COMO ALMACENAMIENTO -- lee el consolidado del panel principal
# (mismo repo/token) y guarda los manifiestos en una carpeta aparte.
# ============================================================
GITHUB_TOKEN  = st.secrets.get("GITHUB_TOKEN", "")
GITHUB_REPO   = st.secrets.get("GITHUB_REPO", "")     # "usuario/repositorio" -- el MISMO repo del panel principal
GITHUB_BRANCH = st.secrets.get("GITHUB_BRANCH", "main")
DATA_PREFIX        = "data/"
MANIFIESTOS_PREFIX = "data/manifiestos_devolucion/"

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
}

def _gh_url(prefix, nombre):
    return f"https://api.github.com/repos/{GITHUB_REPO}/contents/{prefix}{nombre}"

def github_get_file(nombre, prefix=DATA_PREFIX):
    r = requests.get(_gh_url(prefix, nombre), headers=HEADERS, params={"ref": GITHUB_BRANCH})
    if r.status_code != 200:
        return None, None
    data = r.json()
    sha = data["sha"]
    contenido_b64 = data.get("content")
    if contenido_b64:
        return base64.b64decode(contenido_b64), sha
    headers_raw = dict(HEADERS)
    headers_raw["Accept"] = "application/vnd.github.raw"
    r_raw = requests.get(_gh_url(prefix, nombre), headers=headers_raw, params={"ref": GITHUB_BRANCH})
    if r_raw.status_code == 200:
        return r_raw.content, sha
    return None, None

def github_put_file(nombre, contenido_bytes, mensaje, prefix=DATA_PREFIX, sha=None):
    payload = {
        "message": mensaje,
        "content": base64.b64encode(contenido_bytes).decode("utf-8"),
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha
    r = requests.put(_gh_url(prefix, nombre), headers=HEADERS, json=payload)
    if r.status_code not in (200, 201):
        raise Exception(f"Error guardando {nombre} en GitHub: {r.status_code} {r.text}")

@st.cache_data(ttl=300)
def cargar_consolidado_falabella():
    contenido, _ = github_get_file("consolidado_falabella.parquet", prefix=DATA_PREFIX)
    if contenido is None:
        return None
    return pd.read_parquet(io.BytesIO(contenido))

@st.cache_data(ttl=60)
def cargar_indice_manifiestos():
    contenido, _ = github_get_file("indice_manifiestos.parquet", prefix=DATA_PREFIX)
    if contenido is None:
        return pd.DataFrame(columns=[
            "clave_ruta", "Ruta", "Fecha_carga", "CT", "Patente", "Conductor",
            "nombre_archivo", "ruta_github", "fecha_subida", "subido_por",
        ])
    return pd.read_parquet(io.BytesIO(contenido))

def guardar_indice_manifiestos(df):
    _, sha = github_get_file("indice_manifiestos.parquet", prefix=DATA_PREFIX)
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    github_put_file("indice_manifiestos.parquet", buf.getvalue(), "Actualiza indice de manifiestos", prefix=DATA_PREFIX, sha=sha)
    st.cache_data.clear()

def clave_de_ruta(row):
    """Une Ruta + fecha para identificar la ruta física del día -- una misma
    Ruta puede repetirse en fechas distintas."""
    return f"{row['Ruta']}__{row['Fecha_carga']}"

# ============================================================
# LOGICA DE NEGOCIO
# ============================================================
def calcular_rutas_pendientes(df_fal, df_indice):
    """Arma una fila por Ruta+Fecha que tenga al menos un pedido en Estado
    'No entregado', desde el dia de ayer en adelante (no se listan no-entregas
    viejas), con el conteo de pedidos y el estado de plazo (Pendiente / Vencido /
    Subido) segun si ya se subio manifiesto."""
    if df_fal is None or df_fal.empty:
        return pd.DataFrame()

    pendientes = df_fal[df_fal["Estado"].astype(str).str.strip().str.lower() == "no entregado"].copy()
    if pendientes.empty:
        return pd.DataFrame()

    pendientes["_fecha_dt"] = pd.to_datetime(pendientes["Fecha_carga"], dayfirst=True, errors="coerce")
    ayer = (hoy_chile().date() - timedelta(days=1))
    pendientes = pendientes[pendientes["_fecha_dt"].dt.date >= ayer]
    if pendientes.empty:
        return pd.DataFrame()

    pendientes["Fecha_carga"] = pendientes["Fecha_carga"].astype(str)
    pendientes["_clave_ruta"] = pendientes["Ruta"].astype(str) + "__" + pendientes["Fecha_carga"].astype(str)
    pendientes["_motivo"] = pendientes["Motivonoentrega"].astype(str).str.strip()
    pendientes.loc[pendientes["_motivo"].isin(["", "nan", "None"]), "_motivo"] = "Sin motivo registrado"

    agrupado = pendientes.groupby(["Ruta", "Fecha_carga", "CT"], dropna=False).agg(
        Patente=("Patente", "first"),
        Conductor=("Conductor", "first"),
        Pedidos_pendientes=("Suborden", "nunique"),
    ).reset_index()
    agrupado["clave_ruta"] = agrupado["Ruta"].astype(str) + "__" + agrupado["Fecha_carga"].astype(str)

    conteo_motivos = (
        pendientes.groupby(["_clave_ruta", "_motivo"])["Suborden"].nunique().reset_index()
    )
    resumen_motivos = {}
    for clave, grupo in conteo_motivos.groupby("_clave_ruta"):
        partes = [f"{int(r['Suborden'])} {r['_motivo'].lower()}" for _, r in grupo.sort_values("Suborden", ascending=False).iterrows()]
        resumen_motivos[clave] = ", ".join(partes)
    agrupado["Motivos"] = agrupado["clave_ruta"].map(resumen_motivos).fillna("")

    subidas = set(df_indice["clave_ruta"]) if not df_indice.empty else set()
    hoy = hoy_chile().date()

    def estado_fila(row):
        if row["clave_ruta"] in subidas:
            return "Subido"
        try:
            fecha_ruta = pd.to_datetime(row["Fecha_carga"], dayfirst=True, errors="coerce").date()
        except Exception:
            fecha_ruta = None
        if fecha_ruta is None:
            return "Pendiente"
        dias_transcurridos = (hoy - fecha_ruta).days
        return "Vencido" if dias_transcurridos > 1 else "Pendiente"

    agrupado["Estado_manifiesto"] = agrupado.apply(estado_fila, axis=1)
    return agrupado.sort_values(["Estado_manifiesto", "Fecha_carga"], ascending=[False, True])

def buscar_suborden_en_falabella(df_fal, texto):
    """Para el buscador de la vista Subidos: si el texto ingresado calza con
    una Suborden, devuelve su Ruta+Fecha para poder filtrar el indice."""
    if df_fal is None or not texto:
        return None
    fila = df_fal[df_fal["Suborden"].astype(str).str.strip() == texto.strip()]
    if fila.empty:
        return None
    f = fila.iloc[0]
    return f"{f['Ruta']}__{f['Fecha_carga']}"

# ============================================================
# UI
# ============================================================
def badge(texto, color_fondo, color_texto):
    return f'<span style="display:inline-flex;align-items:center;gap:4px;font-size:11.5px;background:{color_fondo};color:{color_texto};padding:4px 9px;border-radius:6px;font-weight:700;">{texto}</span>'

def render_vista_pendientes(df_fal, df_indice):
    st.markdown("#### Rutas con devolución pendiente")

    rutas = calcular_rutas_pendientes(df_fal, df_indice)
    if rutas.empty:
        st.info("No hay rutas con pedidos en estado Pendiente en el consolidado actual.")
        return

    total = len(rutas)
    subidos = (rutas["Estado_manifiesto"] == "Subido").sum()
    vencidos = (rutas["Estado_manifiesto"] == "Vencido").sum()

    c1, c2, c3 = st.columns(3)
    c1.metric("Rutas pendientes", total)
    c2.metric("Con manifiesto", subidos)
    c3.metric("Vencidas sin manifiesto", vencidos)

    st.divider()

    for _, r in rutas.iterrows():
        col_info, col_estado, col_accion = st.columns([4, 1.2, 1.6])
        with col_info:
            detalle_motivos = f" ({r['Motivos']})" if r.get("Motivos") else ""
            st.markdown(
                f"**Ruta {r['Ruta']}** &nbsp;·&nbsp; PPU {r['Patente']} &nbsp;·&nbsp; "
                f"{r['Fecha_carga']} &nbsp;·&nbsp; {r['CT']} &nbsp;·&nbsp; {r['Conductor']} "
                f"&nbsp;·&nbsp; *{r['Pedidos_pendientes']} no entrega(s){detalle_motivos}*"
            )
        with col_estado:
            if r["Estado_manifiesto"] == "Subido":
                st.markdown(badge("Subido", "#dff5ec", "#009972"), unsafe_allow_html=True)
            elif r["Estado_manifiesto"] == "Vencido":
                st.markdown(badge("Vencido", "#fdecea", "#E03C31"), unsafe_allow_html=True)
            else:
                st.markdown(badge("Pendiente", "#fff6da", "#8a6d00"), unsafe_allow_html=True)
        with col_accion:
            if r["Estado_manifiesto"] != "Subido":
                archivo = st.file_uploader(
                    "Subir manifiesto", type=["pdf", "jpg", "jpeg", "png"],
                    key=f"upload_{r['clave_ruta']}", label_visibility="collapsed",
                )
                if archivo is not None:
                    nombre_archivo = f"{r['clave_ruta']}_{archivo.name}".replace("/", "-")
                    github_put_file(
                        nombre_archivo, archivo.getvalue(),
                        f"Manifiesto ruta {r['Ruta']} ({r['Fecha_carga']})",
                        prefix=MANIFIESTOS_PREFIX,
                    )
                    nueva_fila = pd.DataFrame([{
                        "clave_ruta": r["clave_ruta"], "Ruta": r["Ruta"], "Fecha_carga": r["Fecha_carga"],
                        "CT": r["CT"], "Patente": r["Patente"], "Conductor": r["Conductor"],
                        "nombre_archivo": nombre_archivo,
                        "ruta_github": f"{MANIFIESTOS_PREFIX}{nombre_archivo}",
                        "fecha_subida": hoy_chile().strftime("%Y-%m-%d %H:%M"),
                        "subido_por": st.session_state.get("usuario_autorizado", ""),
                    }])
                    guardar_indice_manifiestos(pd.concat([df_indice, nueva_fila], ignore_index=True))
                    st.success("Manifiesto subido.")
                    st.rerun()
            else:
                st.caption("Ya tiene manifiesto")
        st.markdown("<hr style='margin:4px 0;border-color:#f0f0f0;'>", unsafe_allow_html=True)

def render_vista_subidos(df_fal, df_indice):
    st.markdown("#### Manifiestos subidos")

    if df_indice.empty:
        st.info("Todavía no se ha subido ningún manifiesto.")
        return

    texto = st.text_input("Buscar por Suborden, Ruta o Patente", placeholder="Ej: SO-000123, R-045 o ABCD12")

    resultado = df_indice.copy()
    if texto:
        clave_suborden = buscar_suborden_en_falabella(df_fal, texto)
        mask = (
            resultado["Ruta"].astype(str).str.contains(texto, case=False, na=False) |
            resultado["Patente"].astype(str).str.contains(texto, case=False, na=False)
        )
        if clave_suborden:
            mask = mask | (resultado["clave_ruta"] == clave_suborden)
        resultado = resultado[mask]

    if resultado.empty:
        st.warning("No se encontraron manifiestos para esa búsqueda.")
        return

    for _, r in resultado.sort_values("fecha_subida", ascending=False).iterrows():
        col_info, col_descarga = st.columns([4, 1.2])
        with col_info:
            st.markdown(
                f"**Ruta {r['Ruta']}** &nbsp;·&nbsp; PPU {r['Patente']} &nbsp;·&nbsp; "
                f"{r['Fecha_carga']} &nbsp;·&nbsp; {r['CT']} &nbsp;·&nbsp; {r['Conductor']} "
                f"&nbsp;·&nbsp; *subido {r['fecha_subida']} por {r['subido_por']}*"
            )
        with col_descarga:
            contenido, _ = github_get_file(r["nombre_archivo"], prefix=MANIFIESTOS_PREFIX)
            if contenido:
                st.download_button(
                    "Descargar", data=contenido, file_name=r["nombre_archivo"],
                    key=f"dl_{r['clave_ruta']}",
                )
        st.markdown("<hr style='margin:4px 0;border-color:#f0f0f0;'>", unsafe_allow_html=True)

# ============================================================
# MAIN
# ============================================================
def main():
    if not puede_entrar():
        return

    st.markdown(
        f"<div style='display:flex;justify-content:space-between;align-items:center;'>"
        f"<h2 style='margin:0;'>Control de Gestión Falabella 2026</h2>"
        f"<span style='font-size:12px;color:#8a8a88;'>{hoy_chile().strftime('%d-%m-%Y')} · "
        f"{st.session_state.get('usuario_autorizado','')}</span></div>",
        unsafe_allow_html=True,
    )
    st.markdown("<div style='height:3px;background:#009972;border-radius:2px;margin:10px 0 20px;'></div>", unsafe_allow_html=True)

    if not GITHUB_TOKEN or not GITHUB_REPO:
        st.error("Faltan configurar los secretos GITHUB_TOKEN / GITHUB_REPO / APP_PASSWORD.")
        return

    df_fal = cargar_consolidado_falabella()
    if df_fal is None:
        st.error("No se pudo leer el consolidado de Falabella desde GitHub. Revisa GITHUB_REPO / GITHUB_TOKEN.")
        return
    df_indice = cargar_indice_manifiestos()

    vista = st.radio("Vista", ["Pendientes por subir", "Manifiestos subidos"], horizontal=True, label_visibility="collapsed")
    st.markdown("<br>", unsafe_allow_html=True)

    if vista == "Pendientes por subir":
        render_vista_pendientes(df_fal, df_indice)
    else:
        render_vista_subidos(df_fal, df_indice)

if __name__ == "__main__":
    main()
