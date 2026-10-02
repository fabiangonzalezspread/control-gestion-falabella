import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import numpy as np
import requests
import base64
import io
import re
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
DATA_PREFIX         = "data/"
MANIFIESTOS_PREFIX  = "data/manifiestos_devolucion/"
FORMULARIOS_PREFIX  = "data/formularios_ruta/"

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

@st.cache_data(ttl=60)
def cargar_comentarios():
    contenido, _ = github_get_file("comentarios_rutas.parquet", prefix=DATA_PREFIX)
    if contenido is None:
        return pd.DataFrame(columns=["clave_ruta", "comentario", "actualizado_por", "fecha_actualizacion"])
    return pd.read_parquet(io.BytesIO(contenido))

def guardar_comentario(df_comentarios, clave_ruta, comentario):
    _, sha = github_get_file("comentarios_rutas.parquet", prefix=DATA_PREFIX)
    df_sin = df_comentarios[df_comentarios["clave_ruta"] != clave_ruta]
    nueva_fila = pd.DataFrame([{
        "clave_ruta": clave_ruta,
        "comentario": comentario,
        "actualizado_por": st.session_state.get("usuario_autorizado", ""),
        "fecha_actualizacion": hoy_chile().strftime("%Y-%m-%d %H:%M"),
    }])
    df_final = pd.concat([df_sin, nueva_fila], ignore_index=True)
    buf = io.BytesIO()
    df_final.to_parquet(buf, index=False)
    github_put_file("comentarios_rutas.parquet", buf.getvalue(), "Actualiza comentario de ruta", prefix=DATA_PREFIX, sha=sha)
    st.cache_data.clear()

@st.cache_data(ttl=60)
def cargar_indice_formularios():
    contenido, _ = github_get_file("indice_formularios_ruta.parquet", prefix=DATA_PREFIX)
    if contenido is None:
        return pd.DataFrame(columns=[
            "clave_folio", "Suborden", "Ruta", "Fecha_carga", "CT", "Conductor",
            "nombre_archivo", "ruta_github", "fecha_subida", "subido_por",
        ])
    return pd.read_parquet(io.BytesIO(contenido))

def guardar_indice_formularios(df):
    _, sha = github_get_file("indice_formularios_ruta.parquet", prefix=DATA_PREFIX)
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    github_put_file("indice_formularios_ruta.parquet", buf.getvalue(), "Actualiza indice de formularios de ruta", prefix=DATA_PREFIX, sha=sha)
    st.cache_data.clear()

@st.cache_data(ttl=60)
def cargar_comentarios_folios():
    contenido, _ = github_get_file("comentarios_folios.parquet", prefix=DATA_PREFIX)
    if contenido is None:
        return pd.DataFrame(columns=["clave_folio", "comentario", "actualizado_por", "fecha_actualizacion"])
    return pd.read_parquet(io.BytesIO(contenido))

def guardar_comentario_folio(df_comentarios, clave_folio, comentario):
    _, sha = github_get_file("comentarios_folios.parquet", prefix=DATA_PREFIX)
    df_sin = df_comentarios[df_comentarios["clave_folio"] != clave_folio]
    nueva_fila = pd.DataFrame([{
        "clave_folio": clave_folio,
        "comentario": comentario,
        "actualizado_por": st.session_state.get("usuario_autorizado", ""),
        "fecha_actualizacion": hoy_chile().strftime("%Y-%m-%d %H:%M"),
    }])
    df_final = pd.concat([df_sin, nueva_fila], ignore_index=True)
    buf = io.BytesIO()
    df_final.to_parquet(buf, index=False)
    github_put_file("comentarios_folios.parquet", buf.getvalue(), "Actualiza comentario de folio en ruta", prefix=DATA_PREFIX, sha=sha)
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

    # SOC (Suborden) de cada pedido no entregado, agrupadas por motivo -- para
    # mostrarlas como chips debajo de cada motivo en el detalle de la ruta.
    socs_por_motivo = {}
    for clave, grupo in pendientes.groupby("_clave_ruta"):
        por_motivo = []
        orden_motivos = grupo.groupby("_motivo")["Suborden"].nunique().sort_values(ascending=False)
        for motivo in orden_motivos.index:
            socs = sorted(grupo.loc[grupo["_motivo"] == motivo, "Suborden"].astype(str).unique().tolist())
            por_motivo.append((motivo, socs))
        socs_por_motivo[clave] = por_motivo
    agrupado["Detalle_motivos"] = agrupado["clave_ruta"].map(socs_por_motivo)
    agrupado["Detalle_motivos"] = agrupado["Detalle_motivos"].apply(lambda v: v if isinstance(v, list) else [])

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
    return agrupado.sort_values(["CT", "Estado_manifiesto", "Fecha_carga"], ascending=[True, False, True])

def calcular_folios_en_ruta(df_fal):
    """Arma una fila por folio (Suborden) que siga en Estado 'En ruta' desde
    el dia de ayer hacia atras (no incluye los de hoy, que recien van en
    camino), con los dias que lleva abierto.

    Cada sincronizacion con Geosort agrega una fila nueva por Fecha_carga --
    si un pedido estaba 'En ruta' un dia y al dia siguiente ya aparece
    'Entregado' o 'No entregado', el consolidado queda con AMBAS filas (la
    vieja 'En ruta' nunca se borra). Por eso aca nos quedamos solo con la
    fila mas reciente de cada Suborden antes de filtrar: lo que importa es
    su estado actual, no cada fecha en la que paso por el sistema."""
    if df_fal is None or df_fal.empty:
        return pd.DataFrame()

    ayer = (hoy_chile().date() - timedelta(days=1))

    df_ultimo = df_fal.copy()
    df_ultimo["_fecha_dt_orden"] = pd.to_datetime(df_ultimo["Fecha_carga"], dayfirst=True, errors="coerce")
    # Igual que en "Pendientes por subir": solo miramos datos desde ayer en
    # adelante, no todo el historico -- asi no arrastramos filas viejisimas
    # con Estado 'En ruta' de hace semanas que ya no son relevantes.
    df_ultimo = df_ultimo[df_ultimo["_fecha_dt_orden"].dt.date >= ayer]
    if df_ultimo.empty:
        return pd.DataFrame()
    df_ultimo = df_ultimo.sort_values("_fecha_dt_orden").drop_duplicates(subset="Suborden", keep="last")

    en_ruta = df_ultimo[df_ultimo["Estado"].astype(str).str.strip().str.lower() == "en ruta"].copy()
    if en_ruta.empty:
        return pd.DataFrame()

    en_ruta["_fecha_dt"] = pd.to_datetime(en_ruta["Fecha_carga"], dayfirst=True, errors="coerce")
    en_ruta = en_ruta[en_ruta["_fecha_dt"].dt.date <= ayer]
    if en_ruta.empty:
        return pd.DataFrame()

    en_ruta["Fecha_carga"] = en_ruta["Fecha_carga"].astype(str)
    hoy = hoy_chile().date()
    en_ruta["Dias_abierto"] = en_ruta["_fecha_dt"].dt.date.apply(lambda d: (hoy - d).days)

    agrupado = en_ruta.groupby(["Suborden", "Ruta", "Fecha_carga", "CT"], dropna=False).agg(
        Conductor=("Conductor", "first"),
        Dias_abierto=("Dias_abierto", "max"),
    ).reset_index()
    agrupado["clave_folio"] = agrupado["Suborden"].astype(str)
    agrupado["clave_ruta"] = agrupado["Ruta"].astype(str) + "__" + agrupado["Fecha_carga"].astype(str)

    return agrupado.sort_values(["CT", "Dias_abierto"], ascending=[True, False])

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

def construir_excel_consolidado(rutas, df_indice, df_comentarios):
    """Arma el Excel exportable con la misma info que muestra el panel (ya
    filtrada), mas el link del manifiesto subido y el comentario de cada ruta."""
    df = rutas.copy()
    indice_por_clave = df_indice.set_index("clave_ruta") if not df_indice.empty else pd.DataFrame()
    comentarios_por_clave = df_comentarios.set_index("clave_ruta") if not df_comentarios.empty else pd.DataFrame()

    def manifiesto_de(clave):
        if clave in indice_por_clave.index:
            fila = indice_por_clave.loc[clave]
            if isinstance(fila, pd.DataFrame):
                fila = fila.iloc[-1]
            return fila.get("ruta_github", "")
        return ""

    def comentario_de(clave):
        if clave in comentarios_por_clave.index:
            fila = comentarios_por_clave.loc[clave]
            if isinstance(fila, pd.DataFrame):
                fila = fila.iloc[-1]
            return fila.get("comentario", "")
        return ""

    df["Manifiesto"] = df["clave_ruta"].apply(manifiesto_de)
    df["Comentario"] = df["clave_ruta"].apply(comentario_de)

    columnas = [
        "CT", "Fecha_carga", "Ruta", "Patente", "Conductor",
        "Pedidos_pendientes", "Motivos", "Estado_manifiesto", "Manifiesto", "Comentario",
    ]
    df_export = df[columnas].rename(columns={
        "Fecha_carga": "Fecha", "Pedidos_pendientes": "No_entregas", "Estado_manifiesto": "Estado",
    })

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df_export.to_excel(writer, index=False, sheet_name="Consolidado")
    return buf.getvalue()

# ============================================================
# UI
# ============================================================
def badge(texto, color_fondo, color_texto):
    return f'<span style="display:inline-flex;align-items:center;gap:4px;font-size:11.5px;background:{color_fondo};color:{color_texto};padding:4px 9px;border-radius:6px;font-weight:700;">{texto}</span>'

def texto_copiable_ruta(r):
    """Arma el texto plano de una ruta (CT + encabezado + conductor + motivos
    con sus SOC) listo para pegar en WhatsApp u otro chat."""
    lineas = []
    if r.get("CT"):
        ct_txt = str(r["CT"]).strip()
        ct_txt = ct_txt if ct_txt.upper().startswith("CT") else f"CT {ct_txt}"
        lineas.append(ct_txt)
    lineas.append(f"Ruta {r['Ruta']} · PPU {r['Patente']} · {r['Fecha_carga']}")
    if r.get("Conductor"):
        lineas.append(f"Conductor: {r['Conductor']}")
    for motivo, socs in (r.get("Detalle_motivos") or []):
        lineas.append(f"{len(socs)} {motivo.lower()}: {', '.join(socs)}")
    return "\n".join(lineas)

def boton_copiar(texto, key, etiqueta="Copiar", alto=34):
    """Botón chico que copia 'texto' al portapapeles al hacer click.
    st.markdown(unsafe_allow_html=True) filtra los atributos onclick por
    seguridad, así que esto se renderiza con components.html, que sí ejecuta
    el HTML/JS de verdad (iframe dedicado, sin sanitizar)."""
    import json as _json
    texto_js = _json.dumps(texto)
    html = f"""
    <div style="font-family:sans-serif;">
    <button id="{key}" style="font-size:11px;padding:3px 10px;border:1px solid #d8d8d6;
        border-radius:6px;background:#fff;color:#3C3C3B;cursor:pointer;">{etiqueta}</button>
    <script>
    document.getElementById("{key}").addEventListener("click", function() {{
        const texto = {texto_js};
        const btn = this;
        const original = btn.textContent;
        function marcarCopiado() {{
            btn.textContent = "Copiado";
            setTimeout(function() {{ btn.textContent = original; }}, 1200);
        }}
        if (navigator.clipboard && navigator.clipboard.writeText) {{
            navigator.clipboard.writeText(texto).then(marcarCopiado).catch(function() {{
                const ta = document.createElement("textarea");
                ta.value = texto;
                document.body.appendChild(ta);
                ta.select();
                document.execCommand("copy");
                document.body.removeChild(ta);
                marcarCopiado();
            }});
        }} else {{
            const ta = document.createElement("textarea");
            ta.value = texto;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand("copy");
            document.body.removeChild(ta);
            marcarCopiado();
        }}
    }});
    </script>
    </div>
    """
    components.html(html, height=alto)

def render_vista_pendientes(df_fal, df_indice, df_comentarios):
    st.markdown("#### Rutas con devolución pendiente")

    rutas_todas = calcular_rutas_pendientes(df_fal, df_indice)
    if rutas_todas.empty:
        st.info("No hay rutas con pedidos en estado Pendiente en el consolidado actual.")
        return

    fechas_disponibles = sorted(rutas_todas["Fecha_carga"].unique())
    cts_disponibles = sorted(rutas_todas["CT"].unique())

    col_f1, col_f2, col_f3 = st.columns([1.3, 1.3, 1.4])
    with col_f1:
        opciones_fecha = ["Todas las fechas"] + fechas_disponibles
        ayer_str = (hoy_chile().date() - timedelta(days=1)).strftime("%d/%m/%Y")
        indice_default = opciones_fecha.index(ayer_str) if ayer_str in opciones_fecha else 0
        fecha_sel = st.selectbox("Filtrar por fecha", opciones_fecha, index=indice_default)
    with col_f2:
        ct_sel = st.selectbox("Filtrar por CT", ["Todos los CT"] + cts_disponibles)

    rutas = rutas_todas.copy()
    if fecha_sel != "Todas las fechas":
        rutas = rutas[rutas["Fecha_carga"] == fecha_sel]
    if ct_sel != "Todos los CT":
        rutas = rutas[rutas["CT"] == ct_sel]

    with col_f3:
        st.markdown("<div style='height:27px;'></div>", unsafe_allow_html=True)
        st.download_button(
            "⬇ Exportar consolidado",
            data=construir_excel_consolidado(rutas, df_indice, df_comentarios) if not rutas.empty else b"",
            file_name=f"consolidado_falabella_{hoy_chile().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            disabled=rutas.empty,
        )

    if rutas.empty:
        st.warning("No hay rutas que calcen con ese filtro.")
        return

    total = len(rutas)
    subidos = (rutas["Estado_manifiesto"] == "Subido").sum()
    por_subir = total - subidos
    vencidos = (rutas["Estado_manifiesto"] == "Vencido").sum()

    c1, c2, c3 = st.columns(3)
    c1.metric("Rutas totales", total)
    c2.metric("Con manifiesto", subidos)
    c3.metric("Por subir", por_subir)

    st.markdown(
        "<p style='font-size:13px;font-weight:700;color:#3C3C3B;margin:18px 0 10px;"
        "text-transform:uppercase;letter-spacing:0.3px;'>Resumen por CT</p>",
        unsafe_allow_html=True,
    )
    resumen_ct = rutas.groupby("CT").agg(
        Con_manifiesto=("Estado_manifiesto", lambda s: (s == "Subido").sum()),
        Total=("Estado_manifiesto", "size"),
    ).reset_index()
    resumen_ct["Por_subir"] = resumen_ct["Total"] - resumen_ct["Con_manifiesto"]
    resumen_ct = resumen_ct.sort_values("Por_subir", ascending=False)

    cols_ct = st.columns(3)
    for i, (_, ct) in enumerate(resumen_ct.iterrows()):
        pct = int(round(100 * ct["Con_manifiesto"] / ct["Total"])) if ct["Total"] else 0
        with cols_ct[i % 3]:
            st.markdown(
                f"""
                <div style="background:#fff;border-radius:10px;padding:14px 16px;
                    box-shadow:0 2px 8px rgba(0,0,0,0.06);border:1px solid #e8e8e8;margin-bottom:12px;">
                    <p style="font-size:13px;font-weight:700;color:#3C3C3B;margin:0 0 10px;">{ct['CT']}</p>
                    <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px;">
                        <span style="font-size:11.5px;color:#8a8a88;">Con manifiesto</span>
                        <span style="font-size:18px;font-weight:700;color:#009972;">{int(ct['Con_manifiesto'])}</span>
                    </div>
                    <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px;">
                        <span style="font-size:11.5px;color:#8a8a88;">Por subir</span>
                        <span style="font-size:18px;font-weight:700;color:#E03C31;">{int(ct['Por_subir'])}</span>
                    </div>
                    <div style="height:6px;border-radius:3px;background:#fdecea;overflow:hidden;">
                        <div style="height:100%;width:{pct}%;background:#009972;"></div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.divider()

    comentarios_por_clave = (
        df_comentarios.set_index("clave_ruta")["comentario"].to_dict() if not df_comentarios.empty else {}
    )

    texto_por_ct = {
        ct: "\n\n".join(texto_copiable_ruta(r) for _, r in grupo.iterrows())
        for ct, grupo in rutas.groupby("CT")
    }

    ct_actual = None
    for _, r in rutas.iterrows():
        if r["CT"] != ct_actual:
            ct_actual = r["CT"]
            clave_ct = re.sub(r"[^a-zA-Z0-9]", "_", ct_actual)
            col_titulo_ct, col_boton_ct = st.columns([5, 1])
            with col_titulo_ct:
                st.markdown(
                    f"<p style='font-size:12px;font-weight:700;color:#3C3C3B;background:#f0f0f0;"
                    f"padding:6px 10px;border-radius:6px;margin:14px 0 0;"
                    f"text-transform:uppercase;letter-spacing:0.3px;'>{ct_actual}</p>",
                    unsafe_allow_html=True,
                )
            with col_boton_ct:
                st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)
                boton_copiar(
                    f"{ct_actual}\n\n{texto_por_ct.get(ct_actual, '')}",
                    key=f"copiar_ct_{clave_ct}", etiqueta="Copiar CT",
                )

        col_info, col_copiar, col_estado, col_accion, col_comentario = st.columns([2.8, 0.6, 0.9, 1.5, 2])
        with col_info:
            detalle_motivos = f" ({r['Motivos']})" if r.get("Motivos") else ""
            st.markdown(
                f"<p style='font-size:10.5px;color:#1a1a1a;margin:0;'><strong>Ruta {r['Ruta']}</strong> "
                f"&nbsp;·&nbsp; PPU {r['Patente']} &nbsp;·&nbsp; {r['Fecha_carga']}</p>"
                f"<p style='font-size:10px;color:#8a8a88;font-style:italic;margin:2px 0 0;'>"
                f"{r['Conductor']} &nbsp;·&nbsp; {r['Pedidos_pendientes']} no entrega(s){detalle_motivos}</p>",
                unsafe_allow_html=True,
            )
            for motivo, socs in (r.get("Detalle_motivos") or []):
                chips = "".join(
                    f"<span style='background:#f5f5f4;border:1px solid #e8e8e8;border-radius:5px;"
                    f"padding:1px 7px;margin:2px 4px 0 0;font-size:9.5px;font-family:monospace;"
                    f"color:#3C3C3B;display:inline-block;'>{soc}</span>"
                    for soc in socs
                )
                st.markdown(
                    f"<p style='font-size:9.5px;color:#8a8a88;margin:5px 0 0;'>{motivo.lower()}</p>"
                    f"<div style='margin:2px 0 0;'>{chips}</div>",
                    unsafe_allow_html=True,
                )
        with col_copiar:
            boton_copiar(texto_copiable_ruta(r), key=f"copiar_ruta_{re.sub(r'[^a-zA-Z0-9]', '_', str(r['clave_ruta']))}")
        with col_estado:
            if r["Estado_manifiesto"] == "Subido":
                st.markdown(badge("Subido", "#dff5ec", "#009972"), unsafe_allow_html=True)
            elif r["Estado_manifiesto"] == "Vencido":
                st.markdown(badge("Vencido", "#fdecea", "#E03C31"), unsafe_allow_html=True)
            else:
                st.markdown(badge("Pendiente", "#fff6da", "#8a6d00"), unsafe_allow_html=True)
        with col_accion:
            if r["Estado_manifiesto"] != "Subido":
                archivos = st.file_uploader(
                    "Subir manifiesto",
                    type=["pdf", "jpg", "jpeg", "png", "xlsx", "xls", "csv", "docx", "doc",
                          "msg", "eml", "zip", "rar", "7z"],
                    accept_multiple_files=True,
                    key=f"upload_{r['clave_ruta']}", label_visibility="collapsed",
                )
                if archivos:
                    filas_nuevas = []
                    for archivo in archivos:
                        nombre_archivo = f"{r['clave_ruta']}_{archivo.name}".replace("/", "-")
                        github_put_file(
                            nombre_archivo, archivo.getvalue(),
                            f"Manifiesto ruta {r['Ruta']} ({r['Fecha_carga']})",
                            prefix=MANIFIESTOS_PREFIX,
                        )
                        filas_nuevas.append({
                            "clave_ruta": r["clave_ruta"], "Ruta": r["Ruta"], "Fecha_carga": r["Fecha_carga"],
                            "CT": r["CT"], "Patente": r["Patente"], "Conductor": r["Conductor"],
                            "nombre_archivo": nombre_archivo,
                            "ruta_github": f"{MANIFIESTOS_PREFIX}{nombre_archivo}",
                            "fecha_subida": hoy_chile().strftime("%Y-%m-%d %H:%M"),
                            "subido_por": st.session_state.get("usuario_autorizado", ""),
                        })
                    guardar_indice_manifiestos(pd.concat([df_indice, pd.DataFrame(filas_nuevas)], ignore_index=True))
                    st.success(f"{len(archivos)} archivo(s) subido(s).")
                    st.rerun()
            else:
                st.caption("Ya tiene manifiesto")
        with col_comentario:
            valor_actual = comentarios_por_clave.get(r["clave_ruta"], "")
            nuevo_comentario = st.text_input(
                "Comentario", value=valor_actual, key=f"comentario_{r['clave_ruta']}",
                label_visibility="collapsed", placeholder="Agregar comentario...",
            )
            if st.button("Guardar", key=f"guardar_comentario_{r['clave_ruta']}"):
                guardar_comentario(df_comentarios, r["clave_ruta"], nuevo_comentario)
                st.success("Comentario guardado.")
                st.rerun()
        st.markdown("<hr style='margin:4px 0;border-color:#f0f0f0;'>", unsafe_allow_html=True)

def render_vista_en_ruta(df_fal, df_formularios, df_comentarios_folios):
    st.markdown("#### Pedidos en ruta por planchar")

    folios_todos = calcular_folios_en_ruta(df_fal)
    if folios_todos.empty:
        st.info("No hay folios en estado En ruta pendientes de planchar.")
        return

    fechas_disponibles = sorted(folios_todos["Fecha_carga"].unique())
    cts_disponibles = sorted(folios_todos["CT"].unique())

    col_f1, col_f2 = st.columns([1.3, 1.3])
    with col_f1:
        opciones_fecha = ["Todas las fechas"] + fechas_disponibles
        ayer_str = (hoy_chile().date() - timedelta(days=1)).strftime("%d/%m/%Y")
        indice_default = opciones_fecha.index(ayer_str) if ayer_str in opciones_fecha else 0
        fecha_sel = st.selectbox("Filtrar por fecha", opciones_fecha, index=indice_default, key="er_fecha")
    with col_f2:
        ct_sel = st.selectbox("Filtrar por CT", ["Todos los CT"] + cts_disponibles, key="er_ct")

    folios = folios_todos.copy()
    if fecha_sel != "Todas las fechas":
        folios = folios[folios["Fecha_carga"] == fecha_sel]
    if ct_sel != "Todos los CT":
        folios = folios[folios["CT"] == ct_sel]

    if folios.empty:
        st.warning("No hay folios que calcen con ese filtro.")
        return

    total_folios = len(folios)
    rutas_afectadas = folios["clave_ruta"].nunique()
    con_2_mas_dias = (folios["Dias_abierto"] >= 2).sum()

    c1, c2, c3 = st.columns(3)
    c1.metric("Folios abiertos", total_folios)
    c2.metric("Rutas afectadas", rutas_afectadas)
    c3.metric("Con 2+ días abiertos", int(con_2_mas_dias))

    st.divider()

    formularios_subidos = set(df_formularios["clave_folio"]) if not df_formularios.empty else set()
    comentarios_por_clave = (
        df_comentarios_folios.set_index("clave_folio")["comentario"].to_dict()
        if not df_comentarios_folios.empty else {}
    )

    ct_actual = None
    for _, r in folios.iterrows():
        if r["CT"] != ct_actual:
            ct_actual = r["CT"]
            st.markdown(
                f"<p style='font-size:12px;font-weight:700;color:#3C3C3B;background:#f0f0f0;"
                f"padding:6px 10px;border-radius:6px;margin:14px 0 8px;text-transform:uppercase;"
                f"letter-spacing:0.3px;'>{ct_actual}</p>",
                unsafe_allow_html=True,
            )

        col_info, col_formulario, col_comentario = st.columns([2.8, 1.8, 2.2])
        with col_info:
            dias_color = "#E03C31" if r["Dias_abierto"] >= 2 else "#8a6d00"
            st.markdown(
                f"<p style='font-size:10.5px;color:#1a1a1a;margin:0;'>SOC <strong>{r['Suborden']}</strong> "
                f"&nbsp;·&nbsp; Ruta {r['Ruta']} &nbsp;·&nbsp; {r['Fecha_carga']}</p>"
                f"<p style='font-size:10px;color:#8a8a88;font-style:italic;margin:2px 0 0;'>"
                f"{r['Conductor']} &nbsp;·&nbsp; <span style='color:{dias_color};font-weight:700;'>"
                f"{int(r['Dias_abierto'])} día(s) abierto</span></p>",
                unsafe_allow_html=True,
            )
        with col_formulario:
            if r["clave_folio"] in formularios_subidos:
                st.markdown(badge("Subido", "#dff5ec", "#009972"), unsafe_allow_html=True)
            else:
                archivos = st.file_uploader(
                    "Subir evidencia", accept_multiple_files=True,
                    key=f"formulario_{r['clave_folio']}", label_visibility="collapsed",
                )
                if archivos:
                    filas_nuevas = []
                    for archivo in archivos:
                        nombre_archivo = f"{r['clave_folio']}_{archivo.name}".replace("/", "-")
                        github_put_file(
                            nombre_archivo, archivo.getvalue(),
                            f"Formulario/evidencia folio {r['Suborden']} (ruta {r['Ruta']})",
                            prefix=FORMULARIOS_PREFIX,
                        )
                        filas_nuevas.append({
                            "clave_folio": r["clave_folio"], "Suborden": r["Suborden"], "Ruta": r["Ruta"],
                            "Fecha_carga": r["Fecha_carga"], "CT": r["CT"], "Conductor": r["Conductor"],
                            "nombre_archivo": nombre_archivo,
                            "ruta_github": f"{FORMULARIOS_PREFIX}{nombre_archivo}",
                            "fecha_subida": hoy_chile().strftime("%Y-%m-%d %H:%M"),
                            "subido_por": st.session_state.get("usuario_autorizado", ""),
                        })
                    guardar_indice_formularios(pd.concat([df_formularios, pd.DataFrame(filas_nuevas)], ignore_index=True))
                    st.success(f"{len(archivos)} archivo(s) subido(s).")
                    st.rerun()
        with col_comentario:
            valor_actual = comentarios_por_clave.get(r["clave_folio"], "")
            nuevo_comentario = st.text_input(
                "Comentario", value=valor_actual, key=f"comentario_folio_{r['clave_folio']}",
                label_visibility="collapsed", placeholder="Agregar comentario...",
            )
            if st.button("Guardar", key=f"guardar_comentario_folio_{r['clave_folio']}"):
                guardar_comentario_folio(df_comentarios_folios, r["clave_folio"], nuevo_comentario)
                st.success("Comentario guardado.")
                st.rerun()
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
    df_comentarios = cargar_comentarios()
    df_formularios = cargar_indice_formularios()
    df_comentarios_folios = cargar_comentarios_folios()

    vista = st.radio(
        "Vista",
        ["Pendientes por subir", "Manifiestos subidos", "Pedidos en ruta por planchar"],
        horizontal=True, label_visibility="collapsed",
    )
    st.markdown("<br>", unsafe_allow_html=True)

    if vista == "Pendientes por subir":
        render_vista_pendientes(df_fal, df_indice, df_comentarios)
    elif vista == "Manifiestos subidos":
        render_vista_subidos(df_fal, df_indice)
    else:
        render_vista_en_ruta(df_fal, df_formularios, df_comentarios_folios)

if __name__ == "__main__":
    main()
