# ============================================================
# VISTA BUSQUEDA -- vida completa de una SOC (NUEVO)
# Solo lee los mismos datos que ya carga el panel (consolidado, indice de
# manifiestos, comentarios y evidencias). No escribe nada en GitHub.
# ============================================================
def _texto_limpio(v):
    """Texto sin espacios ni '.0' al final (ej. 100000037814610.0)."""
    s = "" if v is None else str(v).strip()
    if s.lower() in ("nan", "none", "nat"):
        return ""
    return s[:-2] if re.fullmatch(r"\d+\.0", s) else s

def _primera_columna(df, *nombres):
    """Devuelve el primer nombre de columna que exista en df (o None)."""
    for n in nombres:
        if n in df.columns:
            return n
    return None

def _fecha_corta(v):
    """dd/mm/aaaa (o dd/mm/aaaa hh:mm) a partir de lo que venga en el consolidado."""
    s = _texto_limpio(v)
    if not s or s in ("-", "N/A"):
        return ""
    if s.startswith("31/12/0001") or s.startswith("0001-"):
        return ""
    return s

def _a_fecha(v):
    s = _fecha_corta(v)
    if not s:
        return None
    dt = pd.to_datetime(s, dayfirst=True, errors="coerce")
    return None if pd.isna(dt) else dt.date()

def buscar_vida_soc(df_fal, texto):
    """Devuelve (subordenes_encontradas, filas) para una SOC o un LPN.
    Las filas son todas las apariciones de esas SOC en el consolidado,
    ordenadas por Fecha_carga (una fila por cada sincronizacion)."""
    texto = _texto_limpio(texto)
    if df_fal is None or df_fal.empty or not texto:
        return [], pd.DataFrame()

    sub_norm = df_fal["Suborden"].map(_texto_limpio)
    mask = sub_norm == texto
    col_do = _primera_columna(df_fal, "Do", "DO")
    if col_do:
        mask = mask | (df_fal[col_do].map(_texto_limpio) == texto)
    col_lpn = _primera_columna(df_fal, "LPN", "Lpn", "lpn")
    if col_lpn and texto.upper() not in ("NA", "N/A"):
        mask = mask | (df_fal[col_lpn].map(_texto_limpio) == texto)

    subordenes = sorted(sub_norm[mask].unique().tolist())
    if not subordenes:
        return [], pd.DataFrame()

    filas = df_fal[sub_norm.isin(subordenes)].copy()
    filas["_suborden"] = sub_norm[filas.index]
    filas["_fecha_dt"] = pd.to_datetime(filas["Fecha_carga"], dayfirst=True, errors="coerce")
    filas["_orden"] = range(len(filas))
    try:
        filas = filas.drop_duplicates(subset=[c for c in filas.columns if c not in ("_orden",)])
    except TypeError:
        pass  # alguna columna con valores no comparables: se dejan todas las filas
    filas = filas.sort_values(["_fecha_dt", "_orden"])
    return subordenes, filas

def _estado_manifiesto_no_entrega(clave_ruta, fecha_carga, subidas, hoy):
    """Misma regla que 'Pendientes por subir': Subido si la Ruta+Fecha tiene
    manifiesto; si no, Vencido cuando ya paso mas de 1 dia, si no Pendiente."""
    if clave_ruta in subidas:
        return "Subido", None
    fecha_ruta = _a_fecha(fecha_carga)
    if fecha_ruta is None:
        return "Pendiente", None
    dias = (hoy - fecha_ruta).days
    return ("Vencido" if dias > 1 else "Pendiente"), dias

def render_vista_busqueda(df_fal, df_indice, df_comentarios, df_formularios, df_comentarios_folios):
    import html as _html
    esc = lambda v: _html.escape(_texto_limpio(v))

    st.markdown("#### Búsqueda de pedido")
    texto = st.text_input("Buscar por SOC o LPN", key="busqueda_soc", placeholder="Ej: 100000037814610")
    if not texto.strip():
        st.caption("Ingresa una SOC (Suborden) o un LPN para ver toda su historia en el consolidado.")
        return

    subordenes, filas = buscar_vida_soc(df_fal, texto)
    if not subordenes:
        st.warning(f"No se encontró {texto.strip()} en el consolidado de Falabella.")
        return

    soc = subordenes[0]
    if len(subordenes) > 1:
        soc = st.selectbox(
            f"El código coincide con {len(subordenes)} SOC, elige una", subordenes, key="busqueda_soc_sel",
        )
    filas = filas[filas["_suborden"] == soc].copy()

    hoy = hoy_chile().date()
    filas["Fecha_carga"] = filas["Fecha_carga"].astype(str)
    filas["clave_ruta"] = filas["Ruta"].astype(str) + "__" + filas["Fecha_carga"]
    filas["_estado"] = filas["Estado"].astype(str).str.strip()
    filas["_estado_l"] = filas["_estado"].str.lower()

    col_lpn = _primera_columna(filas, "LPN", "Lpn", "lpn")
    col_pac = _primera_columna(filas, "Fechapactada", "Fecha_pactada", "Fecha pactada")
    col_ent = _primera_columna(filas, "Fechaentregareal", "Fecha_entrega_real", "Fecha entrega real")
    col_com = _primera_columna(filas, "Comentarionoentrega", "Comentario_no_entrega")
    col_comercio = _primera_columna(filas, "Commerce", "Comercio")
    col_loc = _primera_columna(filas, "Localidad", "Comuna")

    subidas = set(df_indice["clave_ruta"].astype(str)) if not df_indice.empty else set()
    comentarios_ruta = (
        df_comentarios.set_index("clave_ruta")["comentario"].to_dict() if not df_comentarios.empty else {}
    )

    # ---------- ficha ----------
    ultima = filas.iloc[-1]
    entregadas = filas[filas["_estado_l"] == "entregado"]
    if not entregadas.empty:
        f_ent = entregadas.iloc[0]
        txt_ent = _fecha_corta(f_ent[col_ent]) if col_ent else ""
        txt_ent = txt_ent or f_ent["Fecha_carga"]
        fecha_fin = _a_fecha(txt_ent) or hoy
    else:
        txt_ent = "No"
        fecha_fin = hoy
    pactada = _a_fecha(ultima[col_pac]) if col_pac else None
    atraso = max(0, (fecha_fin - pactada).days) if pactada else None
    veces_ruta = filas[["Ruta", "Fecha_carga"]].drop_duplicates().shape[0]

    no_ent = filas[filas["_estado_l"] == "no entregado"]
    rutas_no_ent = no_ent["clave_ruta"].unique().tolist()
    con_manifiesto = sum(1 for c in rutas_no_ent if c in subidas)

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Estado actual", ultima["_estado"] or "-")
    m2.metric("Fecha pactada", pactada.strftime("%d/%m/%Y") if pactada else "-")
    m3.metric("Entregado", txt_ent)
    m4.metric("Días de atraso", atraso if atraso is not None else "-")
    m5.metric("Veces en ruta", veces_ruta)
    m6.metric("Manifiestos", f"{con_manifiesto} de {len(rutas_no_ent)}" if rutas_no_ent else "-")

    partes = [f"SOC {soc}"]
    if col_lpn and _texto_limpio(ultima[col_lpn]) not in ("", "NA", "N/A"):
        partes.append(f"LPN {_texto_limpio(ultima[col_lpn])}")
    if col_comercio and _texto_limpio(ultima[col_comercio]):
        partes.append(_texto_limpio(ultima[col_comercio]))
    partes.append(_texto_limpio(ultima["CT"]))
    if col_loc and _texto_limpio(ultima[col_loc]):
        partes.append(_texto_limpio(ultima[col_loc]))
    partes.append(f"última carga {ultima['Fecha_carga']}")
    st.caption(" · ".join(p for p in partes if p))

    # ---------- linea de tiempo ----------
    st.markdown(
        "<p style='font-size:13px;font-weight:700;margin:18px 0 8px;text-transform:uppercase;"
        "letter-spacing:0.3px;opacity:0.75;'>Línea de tiempo</p>",
        unsafe_allow_html=True,
    )
    colores_estado = {
        "entregado": ("#dff5ec", "#009972"),
        "no entregado": ("#fdecea", "#E03C31"),
        "en ruta": ("#fff6da", "#8a6d00"),
    }
    th = "text-align:left;padding:8px 10px;border-bottom:1px solid rgba(128,128,128,0.35);font-size:12px;opacity:0.8;"
    td = "padding:8px 10px;border-bottom:1px solid rgba(128,128,128,0.2);font-size:12.5px;vertical-align:top;"
    filas_html = []
    for _, r in filas.iterrows():
        bg, fg = colores_estado.get(r["_estado_l"], ("#f0f0f0", "#3C3C3B"))
        motivo = " · ".join(
            x for x in [_texto_limpio(r.get("Motivonoentrega", "")), _texto_limpio(r[col_com]) if col_com else ""] if x
        )
        if r["_estado_l"] == "no entregado":
            est_m, dias = _estado_manifiesto_no_entrega(r["clave_ruta"], r["Fecha_carga"], subidas, hoy)
            if est_m == "Subido":
                archivos = df_indice[df_indice["clave_ruta"].astype(str) == r["clave_ruta"]]
                detalle = "<br>".join(
                    f"{esc(a['nombre_archivo'])}<br><span style='opacity:0.7;'>subido {esc(a['fecha_subida'])} por {esc(a['subido_por'])}</span>"
                    for _, a in archivos.iterrows()
                )
                celda = badge("Subido", "#dff5ec", "#009972") + f"<div style='font-size:11.5px;margin-top:5px;'>{detalle}</div>"
            elif est_m == "Vencido":
                fuera = ""
                f_r = _a_fecha(r["Fecha_carga"])
                if f_r and f_r < FECHA_INICIO_PENDIENTES:
                    fuera = f" · antes del control ({FECHA_INICIO_PENDIENTES.strftime('%d/%m/%Y')})"
                celda = badge("No devolvió · Vencido", "#fdecea", "#E03C31") + (
                    f"<div style='font-size:11.5px;margin-top:5px;opacity:0.75;'>Ruta {esc(r['Ruta'])} sin manifiesto · {dias} días{fuera}</div>"
                )
            else:
                celda = badge("Pendiente", "#fff6da", "#8a6d00") + (
                    "<div style='font-size:11.5px;margin-top:5px;opacity:0.75;'>En plazo para subir manifiesto</div>"
                )
            com_ruta = _texto_limpio(comentarios_ruta.get(r["clave_ruta"], ""))
            if com_ruta:
                celda += f"<div style='font-size:11.5px;margin-top:4px;'>Comentario ruta: \"{esc(com_ruta)}\"</div>"
        else:
            celda = "<span style='opacity:0.5;'>—</span>"
        filas_html.append(
            f"<tr><td style='{td}white-space:nowrap;'>{esc(r['Fecha_carga'])}</td>"
            f"<td style='{td}'><strong>{esc(r['Ruta'])}</strong></td>"
            f"<td style='{td}'>{esc(r['CT'])}</td>"
            f"<td style='{td}white-space:nowrap;'>{esc(r['Patente'])}</td>"
            f"<td style='{td}'>{esc(r['Conductor'])}</td>"
            f"<td style='{td}white-space:nowrap;'>{badge(esc(r['_estado']) or '-', bg, fg)}</td>"
            f"<td style='{td}'>{_html.escape(motivo)}</td>"
            f"<td style='{td}min-width:230px;'>{celda}</td></tr>"
        )
    st.markdown(
        "<div style='overflow-x:auto;'><table style='width:100%;border-collapse:collapse;'>"
        f"<thead><tr><th style='{th}'>Fecha carga</th><th style='{th}'>Ruta</th><th style='{th}'>CT</th>"
        f"<th style='{th}'>PPU</th><th style='{th}'>Conductor</th><th style='{th}'>Estado</th>"
        f"<th style='{th}'>Motivo</th><th style='{th}'>Manifiesto de devolución (por ID de ruta)</th></tr></thead>"
        f"<tbody>{''.join(filas_html)}</tbody></table></div>",
        unsafe_allow_html=True,
    )

    # ---------- descargas de manifiestos de esta SOC ----------
    rutas_subidas = [c for c in rutas_no_ent if c in subidas]
    if rutas_subidas:
        st.markdown(
            "<p style='font-size:13px;font-weight:700;margin:20px 0 8px;text-transform:uppercase;"
            "letter-spacing:0.3px;opacity:0.75;'>Manifiestos de esta SOC</p>",
            unsafe_allow_html=True,
        )
        archivos = df_indice[df_indice["clave_ruta"].astype(str).isin(rutas_subidas)]
        for _n, (_, a) in enumerate(archivos.iterrows()):
            col_a, col_b = st.columns([4, 1.2])
            with col_a:
                st.markdown(
                    f"**Ruta {a['Ruta']}** &nbsp;·&nbsp; {a['Fecha_carga']} &nbsp;·&nbsp; {a['nombre_archivo']} "
                    f"&nbsp;·&nbsp; *subido {a['fecha_subida']} por {a['subido_por']}*"
                )
            with col_b:
                contenido, _ = github_get_file(a["nombre_archivo"], prefix=MANIFIESTOS_PREFIX)
                if contenido:
                    st.download_button(
                        "Descargar", data=contenido, file_name=a["nombre_archivo"],
                        key=f"busq_dl_{_n}_{a['clave_ruta']}_{a['nombre_archivo']}",
                    )

    # ---------- evidencias y comentarios del folio (vista En ruta) ----------
    evid = df_formularios[df_formularios["clave_folio"].astype(str) == soc] if not df_formularios.empty else pd.DataFrame()
    com_folio = ""
    if not df_comentarios_folios.empty:
        cf = df_comentarios_folios[df_comentarios_folios["clave_folio"].astype(str) == soc]
        if not cf.empty:
            com_folio = _texto_limpio(cf.iloc[-1]["comentario"])
    if not evid.empty or com_folio:
        st.markdown(
            "<p style='font-size:13px;font-weight:700;margin:20px 0 8px;text-transform:uppercase;"
            "letter-spacing:0.3px;opacity:0.75;'>Gestión en ruta (planchado)</p>",
            unsafe_allow_html=True,
        )
        for _, e in evid.iterrows():
            st.markdown(
                f"Evidencia **{e['nombre_archivo']}** &nbsp;·&nbsp; ruta {e['Ruta']} ({e['Fecha_carga']}) "
                f"&nbsp;·&nbsp; *subido {e['fecha_subida']} por {e['subido_por']}*"
            )
        if com_folio:
            st.markdown(f"Comentario del folio: \"{com_folio}\"")

