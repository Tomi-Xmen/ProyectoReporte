"""
Reporte en vivo: el HTML de un lote servido por el propio programa, que se
recarga solo cuando cambia.

El HTML del lote ya se regenera en disco con cada escaneo, edición o equipo
que llega de clonación; lo que faltaba era que la pestaña abierta se enterara.
Acá se sirve ese MISMO archivo con un script agregado al vuelo que pregunta
cada 2 segundos la huella del archivo (fecha y tamaño) y recarga la página
si cambió, conservando la posición del scroll. El archivo en disco no se toca:
el que se abre con doble clic sigue siendo idéntico.

Sin Qt ni red: el transporte (ui/reporte_vivo.py) solo mueve bytes.
"""

import html
import json
import os

from .lotes import (
    MOV_CFG,
    carpeta_lote,
    esta_cerrado,
    etiqueta_lote,
    hacer_lote,
    listar_lotes_abiertos,
    normalizar_cliente,
    normalizar_numero,
    numero_sec_en_disco,
    ruta_html_lote,
)

INTERVALO_MS = 2000


def partes_de_lote(lote):
    """(grupo, cliente, carpeta): cómo se nombra el lote en la URL."""
    return (
        MOV_CFG[lote["mov"]]["grupo"],
        lote["cliente"],
        carpeta_lote(lote["mov"], lote["numero"]),
    )


def lote_desde_partes(grupo, cliente, carpeta):
    """
    El lote que nombra la URL, o None. Solo acepta nombres en forma canónica:
    lo que llega por la URL termina en una ruta del disco.
    """
    mov = next((m for m, cfg in MOV_CFG.items() if cfg["grupo"] == grupo), None)
    if not mov or not cliente or cliente != normalizar_cliente(cliente):
        return None
    prefijo = MOV_CFG[mov]["prefijo"] + "-"
    if not carpeta.startswith(prefijo):
        return None
    numero = carpeta[len(prefijo):]
    if not numero or numero != normalizar_numero(numero, mov):
        return None
    lote = hacer_lote(mov, cliente, numero)
    if not os.path.isdir(lote["ruta"]):
        return None
    lote["numero_sec"] = numero_sec_en_disco(lote["ruta"])
    return lote


def huella_lote(lote):
    """{"huella", "cerrado"}: la huella cambia cada vez que se regenera el HTML."""
    try:
        st = os.stat(ruta_html_lote(lote))
        firma = f"{st.st_mtime_ns}-{st.st_size}"
    except OSError:
        firma = ""
    return {"huella": firma, "cerrado": esta_cerrado(lote["ruta"])}


def _script_vivo(url_huella, huella):
    datos = json.dumps({"url": url_huella, "huella": huella})
    return f"""
<div id="vivo-insignia" style="position:fixed;top:12px;right:12px;z-index:9999;padding:6px 14px;
  border-radius:20px;font:700 12px 'Segoe UI',Tahoma,sans-serif;background:#dcfce7;color:#166534;
  border:1px solid #bbf7d0;box-shadow:0 2px 6px rgba(0,0,0,.15)">● EN VIVO</div>
<script>
(function(){{
  var cfg = {datos};
  var insignia = document.getElementById('vivo-insignia');
  try {{
    var y = sessionStorage.getItem('vivo-scroll');
    if (y !== null) {{ window.scrollTo(0, parseInt(y, 10)); sessionStorage.removeItem('vivo-scroll'); }}
  }} catch (e) {{}}
  function pintar(texto, ok) {{
    insignia.textContent = texto;
    insignia.style.background = ok ? '#dcfce7' : '#fef3c7';
    insignia.style.color = ok ? '#166534' : '#92400e';
    insignia.style.borderColor = ok ? '#bbf7d0' : '#fde68a';
  }}
  function revisar() {{
    fetch(cfg.url, {{cache: 'no-store'}}).then(function(r) {{ return r.json(); }}).then(function(d) {{
      pintar(d.cerrado ? '● EN VIVO · lote cerrado' : '● EN VIVO', true);
      if (d.huella !== cfg.huella) {{
        try {{ sessionStorage.setItem('vivo-scroll', String(window.scrollY)); }} catch (e) {{}}
        location.reload();
      }}
    }}).catch(function() {{ pintar('○ Sin conexión con el programa', false); }});
  }}
  setInterval(revisar, {INTERVALO_MS});
}})();
</script>
"""


def pagina_lote(lote, url_huella):
    """El HTML del lote con el script de recarga agregado (el archivo no cambia)."""
    actual = huella_lote(lote)["huella"]
    try:
        with open(ruta_html_lote(lote), "r", encoding="utf-8") as f:
            contenido = f.read()
    except OSError:
        contenido = (
            "<!DOCTYPE html><html lang='es'><head><meta charset='utf-8'>"
            f"<title>{html.escape(etiqueta_lote(lote))}</title></head>"
            "<body style=\"font-family:'Segoe UI',Tahoma,sans-serif;background:#eef2f7;"
            "color:#1e293b;padding:40px;text-align:center\">"
            f"<h2>{html.escape(etiqueta_lote(lote))}</h2>"
            "<p>Todavía no hay equipos en este lote. La página se actualiza sola "
            "apenas llegue el primero.</p></body></html>"
        )
    script = _script_vivo(url_huella, actual)
    corte = contenido.lower().rfind("</body>")
    if corte < 0:
        return contenido + script
    return contenido[:corte] + script + contenido[corte:]


def pagina_indice(base):
    """Lista de lotes abiertos con su enlace en vivo. Se refresca sola."""
    filas = []
    for lote in listar_lotes_abiertos():
        grupo, cliente, carpeta = partes_de_lote(lote)
        sec = lote.get("numero_sec") or "—"
        filas.append(
            f"<a class='lote' href='{base}/lote/{grupo}/{cliente}/{carpeta}'>"
            f"<b>{html.escape(etiqueta_lote(lote))}</b>"
            f"<span>{lote['equipos']} equipo(s) · documento: {html.escape(sec)}</span></a>"
        )
    cuerpo = "\n".join(filas) or "<p>No hay OT ni guías abiertas.</p>"
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"><meta http-equiv="refresh" content="5">
<title>Reportes en vivo</title>
<style>
  body{{font-family:'Segoe UI',Tahoma,sans-serif;background:#eef2f7;color:#1e293b;padding:30px}}
  .c{{max-width:760px;margin:auto}}
  h1{{font-size:24px;color:#1a3c6e;margin:0 0 6px}}
  p.s{{color:#64748b;font-size:13px;margin:0 0 20px}}
  a.lote{{display:flex;justify-content:space-between;gap:12px;background:#fff;border:1px solid #e2e8f0;
    border-radius:12px;padding:14px 18px;margin-bottom:10px;text-decoration:none;color:#1e293b;
    box-shadow:0 2px 8px rgba(0,0,0,.06)}}
  a.lote:hover{{border-color:#93c5fd}}
  a.lote span{{color:#64748b;font-size:13px}}
</style></head>
<body><div class="c">
<h1>📡 Reportes en vivo</h1>
<p class="s">OT y guías abiertas. Cada reporte se actualiza solo mientras el programa esté abierto.</p>
{cuerpo}
</div></body></html>"""
