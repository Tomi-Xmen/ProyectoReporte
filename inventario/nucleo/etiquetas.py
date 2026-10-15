"""
Etiqueta manual de diagnóstico (equipos defectuosos): una hoja HTML que se
abre en el navegador y se imprime sola, sin tocar los reportes de inventario.
"""

import os
import tempfile
from datetime import datetime


def html_etiqueta_manual(serial, modelo, cpu, guia, ot, componentes):
    """
    HTML de la etiqueta. 'componentes' es [{'nombre', 'estado', 'obs'}], el
    mismo formato que guarda el JSON del equipo. Los campos vacíos salen como
    'S/N' o 'Desconocido'.
    """
    serial = serial.strip() or "S/N"
    modelo = modelo.strip() or "Desconocido"
    cpu = cpu.strip() or "Desconocido"
    guia = guia.strip() or "S/N"
    ot = ot.strip() or "S/N"
    fecha = datetime.now().strftime('%d/%m/%Y')

    trs = ""
    for c in componentes:
        nombre = c["nombre"]
        estado = c["estado"]
        obs = c["obs"]

        iconOK = "☑" if estado == "OK" else "□"
        iconOBS = "☑" if estado == "OBS" else "□"
        iconMalo = "☑" if estado == "MALO" else "□"

        trs += f"""<tr>
          <td>{nombre}</td>
          <td style="text-align: center;">{iconOK} OK &nbsp;&nbsp;&nbsp; {iconOBS} OBS &nbsp;&nbsp;&nbsp; {iconMalo} MALO</td>
          <td>{obs}</td>
        </tr>"""

    html_etiqueta = f"""<!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Etiqueta_{serial}</title>
        <style>
          @media print {{ @page {{ margin: 15mm; size: auto; }} body {{ margin: 0; }} }}
          body {{ font-family: 'Arial', sans-serif; font-size: 11px; color: #000; max-width: 700px; margin: auto; padding: 20px; line-height: 1.4; }}
          .header-title {{ display: flex; justify-content: space-between; font-weight: bold; margin-bottom: 20px; font-size: 13px; }}
          .row {{ margin-bottom: 10px; font-size: 11px;}}
          .row span {{ margin-right: 25px; }}
          table {{ width: 100%; border-collapse: collapse; margin-top: 15px; margin-bottom: 20px; }}
          th, td {{ border: 1px solid #000; padding: 5px 8px; text-align: left; }}
          .checkboxes {{ font-family: 'Segoe UI Symbol', sans-serif; }}
          .bold {{ font-weight: bold; }}
        </style>
    </head>
    <body onload="setTimeout(() => {{ window.print(); }}, 500);">
        <div class="header-title">
          <span>ETIQUETAS NOTEBOOK</span>
          <span>FECHA: {fecha}</span>
        </div>
        <div class="row">
          <span><span class="bold">MODELO:</span> {modelo}</span>
          <span><span class="bold">OT:</span> {ot}</span>
          <span><span class="bold">PROCESADOR:</span> {cpu}</span>
          <span><span class="bold">GUIA:</span> {guia}</span>
          <span><span class="bold">SERIAL:</span> {serial}</span>
        </div>
        <div class="row checkboxes" style="margin-bottom:20px;">
          <span class="bold">ESTADO GLOBAL:</span> &nbsp;&nbsp;&nbsp;&nbsp;
          □ BUENA &nbsp;&nbsp;&nbsp; ☑ POR REPARAR &nbsp;&nbsp;&nbsp; □ MALA &nbsp;&nbsp;&nbsp; □ REPUESTO
        </div>
        <table>
          <thead>
            <tr>
              <th width="20%">REVISIÓN DE COMPONENTES</th>
              <th width="35%" style="text-align: center;">ESTADO</th>
              <th width="45%">OBSERVACIÓN</th>
            </tr>
          </thead>
          <tbody class="checkboxes">
            {trs}
          </tbody>
        </table>
        <div class="row checkboxes bold" style="margin-top:20px;">
          CHECKLIST: &nbsp;&nbsp;&nbsp;&nbsp; □ PRUEBA S/O &nbsp;&nbsp;&nbsp;&nbsp; □ HYDRA &nbsp;&nbsp;&nbsp;&nbsp; □ HARDWARE DEFAULT
        </div>
    </body>
    </html>
    """
    return html_etiqueta


def generar_etiqueta_manual(serial, modelo, cpu, guia, ot, componentes):
    """Escribe la etiqueta en un temporal y devuelve su ruta."""
    temp_path = os.path.join(tempfile.gettempdir(), "etiqueta_manual_temp.html")
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(html_etiqueta_manual(serial, modelo, cpu, guia, ot, componentes))
    return temp_path
