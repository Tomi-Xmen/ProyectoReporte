"""
Reporte HTML de un lote: la plantilla (CSS + JS), las filas de hardware y la
entrada <details> de cada equipo, siempre armada desde su JSON.

NOTA: la apariencia del REPORTE HTML vive en HTML_START/HTML_END y en
construir_entry_html; no se debe alterar sin querer cambiar el reporte.
"""

import html
import json
import re
from datetime import datetime

# Valor de SN_Transf mientras el equipo no tiene transformador cargado.
TRANSF_PENDIENTE = "PENDIENTE"

# ============================================================================
# 4. PLANTILLA HTML DEL REPORTE  (⚠️ apariencia del reporte — NO modificar)
# ----------------------------------------------------------------------------
# HTML_START trae toda la página (CSS + JS de estadísticas, etiquetas, export
# CSV, etc.) y termina en <div id="main-list">. HTML_END cierra las etiquetas.
# Las entradas de cada equipo se insertan entre ambos (ver construir_entry_html).
# ============================================================================
HTML_START = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Inventario Maestro</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Segoe UI',Tahoma,sans-serif;background:#eef2f7;color:#1e293b;padding:30px}
  .container{max-width:1050px;margin:auto}
  .header{text-align:center;margin-bottom:28px}
  h1{font-size:26px;color:#1a3c6e;margin-bottom:6px}
  .subtitle{color:#64748b;font-size:13px;margin-bottom:14px}
  .counter-box{background:#dbeafe;color:#1d4ed8;padding:5px 18px;border-radius:20px;
    font-weight:700;font-size:13px;display:inline-block;border:1px solid #bfdbfe;margin-bottom:12px}

  .stats-container { display:flex; justify-content:center; gap:10px; margin-bottom:22px; flex-wrap:wrap; }
  .stat-pill { padding:5px 16px; border-radius:20px; font-weight:700; font-size:12px; border:1px solid; }
  .stat-ram { background:#fce7f3; color:#be185d; border-color:#fbcfe8; }
  .stat-cpu { background:#fef3c7; color:#b45309; border-color:#fde68a; }
  .stat-disk { background:#dcfce7; color:#15803d; border-color:#bbf7d0; }

  .button-group{display:flex;justify-content:center;gap:12px;margin-bottom:32px;flex-wrap:wrap}
  .btn{color:#fff;border:none;padding:10px 22px;font-size:13px;font-weight:700;border-radius:8px;
    cursor:pointer;box-shadow:0 2px 6px rgba(0,0,0,.18);transition:transform .1s,box-shadow .1s}
  .btn:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(0,0,0,.22)}
  .btn:active{transform:translateY(0)}
  .btn-copy{background:linear-gradient(135deg,#0078d4,#005a9e)}
  .btn-export{background:linear-gradient(135deg,#16a34a,#15803d)}
  .btn-delete{background:#ef4444;padding:5px 12px;font-size:11px;border-radius:6px}
  .btn-delete:hover{background:#dc2626}

  details{background:#fff;margin-bottom:12px;border-radius:12px;
    box-shadow:0 2px 8px rgba(0,0,0,.08);overflow:hidden;border:1px solid #e2e8f0}
  summary{padding:14px 18px;font-weight:700;cursor:pointer;
    background:linear-gradient(135deg,#1a3c6e,#0f2d5a);color:#fff;
    list-style:none;display:flex;justify-content:space-between;align-items:center;gap:10px}
  summary:hover{background:linear-gradient(135deg,#1e4a84,#142f60)}
  summary::-webkit-details-marker{display:none}

  .tag-entrega{background:#22c55e;color:#fff;padding:3px 9px;border-radius:20px;font-size:11px;font-weight:700}
  .tag-retiro{background:#f97316;color:#fff;padding:3px 9px;border-radius:20px;font-size:11px;font-weight:700}
  .tag-falla{background:#ef4444;color:#fff;padding:3px 9px;border-radius:20px;font-size:11px;font-weight:700;margin-left:8px}
  .logistics-row{background:#f8fafc}

  .content{padding:20px 22px;border-top:1px solid #f1f5f9}
  .content-header{display:flex;justify-content:flex-end;margin-bottom:10px; gap: 8px;}
  table{border-collapse:collapse;width:100%}
  th,td{border:1px solid #e2e8f0;padding:9px 12px;text-align:left;font-size:13px}
  th{background:#f8fafc;width:28%;color:#475569;font-weight:600}
  tr:hover td,tr:hover th{background:#f0f9ff}
  .serial-tag{color:#dc2626;font-weight:700;font-family:Consolas,monospace}
  .net-tag{background:#dcfce7;color:#166534;padding:2px 7px;border-radius:4px;font-weight:600;font-size:12px}
  .win-key{color:#1d4ed8;font-family:Consolas,monospace;font-weight:700;font-size:12px}
  .obs-row{background:#fef9c3!important}
  .obs-row td,.obs-row th{color:#854d0e;font-weight:600;font-style:italic}
  .falla-row{background:#fee2e2!important}
  .falla-row td,.falla-row th{color:#991b1b;font-weight:600}
  .office-row{background:#eff6ff}
  .office-row td,.office-row th{color:#1e40af}
</style>
<script>
function actualizarEstadisticas() {
  let eqs = document.querySelectorAll('details');
  document.getElementById('total-count').innerText = eqs.length;

  let cpus = {}, rams = {}, discos = {};

  eqs.forEach(eq => {
    let d = extraerDatos(eq);

    let cpuU = d.cpu.toUpperCase();
    let cpuKey = "Otro";
    if(cpuU.includes("I3")) cpuKey = "i3";
    else if(cpuU.includes("I5")) cpuKey = "i5";
    else if(cpuU.includes("I7")) cpuKey = "i7";
    else if(cpuU.includes("I9")) cpuKey = "i9";
    else if(cpuU.includes("RYZEN 3")) cpuKey = "Ryzen 3";
    else if(cpuU.includes("RYZEN 5")) cpuKey = "Ryzen 5";
    else if(cpuU.includes("RYZEN 7")) cpuKey = "Ryzen 7";
    cpus[cpuKey] = (cpus[cpuKey] || 0) + 1;

    let ramMatch = d.specs.match(/^(\d+GB)/);
    let ramKey = ramMatch ? ramMatch[1] : "Otra";
    rams[ramKey] = (rams[ramKey] || 0) + 1;

    d.discos.forEach(dk => {
      let desc = dk.desc.toUpperCase();
      let tipo = "Desconocido";
      if(desc.includes("M.2") || desc.includes("NVME")) tipo = "M.2 NVMe";
      else if(desc.includes("SSD")) tipo = "SSD 2.5\"";
      else if(desc.includes("HDD")) tipo = "HDD";
      discos[tipo] = (discos[tipo] || 0) + 1;
    });
  });

  let mkHTML = (obj, clase, prefijo) => {
    let arr = Object.entries(obj).map(([k,v]) => `${k} (${v})`);
    return arr.length ? `<span class="stat-pill ${clase}">${prefijo}: ${arr.join(' | ')}</span>` : '';
  };

  let statsDiv = document.getElementById('stats-container');
  if(statsDiv) {
    statsDiv.innerHTML = mkHTML(rams, 'stat-ram', 'RAM') +
                         mkHTML(cpus, 'stat-cpu', 'CPU') +
                         mkHTML(discos, 'stat-disk', 'Discos');
  }
}

document.addEventListener("DOMContentLoaded", actualizarEstadisticas);

function eliminarEquipo(id){
  if(confirm("¿Quitar este equipo del reporte actual?\n(No afecta los archivos ya guardados)")){
    let n=document.getElementById(id);
    if(n){
      n.remove();
      actualizarEstadisticas();
    }
  }
}

function extraerDatos(eq){
  let model  = eq.querySelector('.model-name').innerText.trim();
  let serial = eq.querySelector('.serial-tag').innerText.trim();
  let tds=eq.querySelectorAll('th,td');
  let obs="",cpu="",office="",guia="",mov="",ramSpeed="",ramTech="PC4",fallas="",Manufacturer="",Partnumber="Desconocida",ot="",transf="";
  let totalRam=0,ramArr=[],discos=[],tempDesc="";

  for(let i=0;i<tds.length;i++){
    if(tds[i].tagName !== 'TH') continue;

    let t=tds[i].innerText.trim();
    if(t==='N° de Guía')          guia   =tds[i+1].innerText.trim();
    if(t==='N° de OT')            ot     =tds[i+1].innerText.trim();
    if(t==='Tipo Movimiento')     mov    =tds[i+1].innerText.trim();
    if(t.includes('Obs. General'))obs    =tds[i+1].innerText.trim();
    if(t==='Fallas Detectadas')   fallas =tds[i+1].innerText.trim();
    if(t==='Procesador')          cpu    =tds[i+1].innerText.trim();
    if(t.includes('Office'))      office =tds[i+1].innerText.trim();
    if(t==='Discos Internos')     tempDesc=tds[i+1].innerText.trim();
    if(t==='Serie Disco Duro')    discos.push({desc:tempDesc,serial:tds[i+1].innerText.trim()});
    /* includes y no ===: el th lleva el emoji 🔌 adelante. */
    if(t.includes('Serie Transformador')) transf=tds[i+1].innerText.trim();
    if(t==='Módulo RAM'){
      let p=tds[i+1].innerText.split('|');
      let n=parseInt(p[0].replace(/\D/g,''));
      if(!isNaN(n)){totalRam+=n;ramArr.push(n)}
      if(p[1]&&ramSpeed==="")ramSpeed=p[1].trim();
      if(p[2]&&ramTech==="PC4")ramTech=p[2].trim();
      if(p[3]&&Manufacturer==="")Manufacturer=p[3].trim()
      if(p[4]&&Partnumber==="Desconocida")Partnumber=p[4].trim()
    }
  }

  let ramFinal="RAM Desconocida";
  if(totalRam>0){
    let det=ramArr.length>1?(ramArr.every(v=>v===ramArr[0])?`(${ramArr[0]}X${ramArr.length})`:`(${ramArr.join('+')})`):"";
    let ts=ramSpeed!=="Desconocida"?`${ramTech}-${ramSpeed}Mhz`:ramTech;
    ramFinal=`${totalRam}GB${det} (${ts})`;
  }
  let diskSimple=discos.map(d=>{let m=d.desc.match(/(\d+)\s*GB\s*(.*)/i);return m?m[1]+" GB "+m[2]:d.desc});
  let specs=ramFinal+(diskSimple.length>0?", "+diskSimple.join(" + "):"");
  if(obs&&obs!=="Sin observaciones")specs+=", OBS: "+obs;
  if(fallas&&fallas!=="Ninguna")specs+=", FALLAS: "+fallas;

  return {model,serial,cpu,obs,office,guia,mov,discos,specs,equipoFull:model+" "+cpu, fallas, Manufacturer, Partnumber, ot, transf};
}

/* --- EXPORT A VALIDA: COPIAR FILAS Y CSV --- */

const MSG_COPIADO="✅ ¡Filas copiadas!\n\nPega directamente en tu Excel / Valida.";

/* Filas que un equipo aporta a Valida, como [nombre, descripción, serie, obs].
   Fuente ÚNICA de copiarFilas y exportarValidaCSV: las dos salidas describen el
   mismo equipo y tienen que decir lo mismo. Cuando cada una armaba sus filas por
   su cuenta terminaron divergiendo (la fila del transformador salía distinta en
   cada export). Accesorio nuevo = una línea acá y aparece en las dos. */
function filasValida(d){
  let filas=[[d.equipoFull, d.specs, d.serial, d.obs]];

  d.discos.forEach(dk=>{
    let lbl=dk.desc.toUpperCase().includes("HDD")?"HDD":"SSD";
    filas.push([lbl, dk.desc, dk.serial, ""]);
  });

  /* d.office solo existe si tiene_office fue true al cargar el equipo (ver
     construir_entry_html): si el registro no llevaba Office, esta fila no
     entra. La key puede faltar (SN_APP="PENDIENTE") y aun así el equipo
     lleva Office, así que la fila se exporta igual, con la serie en blanco. */
  if(d.office){
    let ver=(d.office.match(/Office\s+([A-Za-z0-9]+)/)||[])[1]||"2016";
    let key=(d.office.match(/Key:\s*([^)]+)/)||[])[1]||"";
    filas.push([`OFFICE ${ver}`, "HOME AND BUSINESS", key.trim(), ""]);
  }

  /* El transformador va sin nombre: en Valida se carga como accesorio y con la
     descripción alcanza. */
  if(d.transf) filas.push(["", "TRANSFORMADOR C/ADAPTADOR 45 W PUNTA FINA", d.transf, ""]);

  return filas;
}

function copiarFilas(){
  let txt="";
  let filasTransf=[];
  document.querySelectorAll('details').forEach(eq=>{
    /* Al portapapeles van solo las 3 primeras columnas: la obs ya viaja dentro
       de specs y la cuarta es para el CSV. Los transformadores se juntan aparte
       para pegarlos todos al final, uno debajo del otro. */
    filasValida(extraerDatos(eq)).forEach(f=>{
      if(f[1]==="TRANSFORMADOR C/ADAPTADOR 45 W PUNTA FINA") filasTransf.push(f);
      else txt+=f.slice(0,3).join("\t")+"\n";
    });
  });
  filasTransf.forEach(f=>{ txt+=f.slice(0,3).join("\t")+"\n" });

  if(!txt){ alert("No hay equipos en el reporte para copiar."); return; }

  if(navigator.clipboard && window.isSecureContext){
      navigator.clipboard.writeText(txt)
        .then(()=>alert(MSG_COPIADO))
        .catch(()=>copiarConTextarea(txt));
  } else {
      copiarConTextarea(txt);
  }
}

/* Respaldo del portapapeles. Se usa en dos casos: el reporte abierto con
   file://, donde navigator.clipboard no existe, y el rebote de la API cuando la
   ventana perdió el foco —de ahí que el catch caiga acá y no en un alert de
   error. */
function copiarConTextarea(txt){
  let ta=document.createElement("textarea");
  ta.value=txt;
  ta.style.cssText="position:fixed;left:-9999px;top:0";  /* que select() no salte el scroll */
  document.body.appendChild(ta);
  ta.select();
  try{ document.execCommand('copy'); alert(MSG_COPIADO); }
  catch(e){ alert("Error al copiar al portapapeles.") }
  document.body.removeChild(ta);
}

/* Nombre base compartido por las descargas: Reporte_<tipo>_<cliente>_<AAAAMMDD> */
function nombreBaseReporte(){
  let titulo=document.querySelector('title').innerText;
  let tipo=titulo.includes("Entregas")?"Entregas":(titulo.includes("Retiros")?"Retiros":"General");
  let cliente=titulo.replace(tipo+" - ","").replace("Inventario Maestro","General").replace(/ /g,"_");
  return `Reporte_${tipo}_${cliente}_${new Date().toISOString().slice(0,10).replace(/-/g,"")}`;
}

function descargarArchivo(nombre, contenido, mime){
  let blob=new Blob([contenido],{type:mime}),a=document.createElement("a");
  a.href=URL.createObjectURL(blob);
  a.download=nombre;
  a.style.visibility='hidden';document.body.appendChild(a);a.click();document.body.removeChild(a);
}

function exportarValidaCSV(){
  let csv="\uFEFFTIPO;GUIA;NOMBRE DEL EQUIPO;DESCRIPCION;NUMERO DE SERIE;OBSERVACIONES\n";
  document.querySelectorAll('details').forEach(eq=>{
    let d=extraerDatos(eq);
    /* Movimiento y gu\u00EDa son del equipo, no de la fila: se repiten en todas las
       filas que aporta, que es como Valida espera el CSV. */
    filasValida(d).forEach(f=>{
      csv+=`"${d.mov}";"${d.guia}";"${f[0]}";"${f[1]}";"${f[2]}";"${f[3]}"\n`;
    });
  });
  descargarArchivo(nombreBaseReporte()+".csv", csv, 'text/csv;charset=utf-8;');
}

/* --- EXPORT DEL JSON FUSIONADO --- */

/* Respaldo para entradas sin data-fusion (reportes armados antes de que
   existiera el atributo): se rearma el resumen leyendo la tabla. */
function resumenFusionadoDesdeDOM(eq){
  let val=sel=>{let n=eq.querySelector(sel);return n?n.innerText.trim():""};
  let hdd=[];
  eq.querySelectorAll('th').forEach(th=>{
    if(th.innerText.trim()==='Serie Disco Duro'&&th.nextElementSibling)
      hdd.push(th.nextElementSibling.innerText.trim());
  });
  let obs=val('.obs-row td');
  let key=((val('.office-row td').match(/Key:\s*([^)]+)/)||[])[1]||"").trim();
  return {
    SERIAL: val('.serial-tag'),
    SN_Win: val('.win-key'),
    SN_HDD: hdd.join("_")||"PENDIENTE",
    SN_Transf: val('.transf-tag')||"PENDIENTE",
    SN_APP: key||null,
    OBS: (obs&&obs!=="Sin observaciones")?obs:null
  };
}

function exportarJsonFusionado(){
  let equipos=[];
  document.querySelectorAll('details').forEach(eq=>{
    let raw=eq.getAttribute('data-fusion');
    if(raw){
      try{ equipos.push(JSON.parse(raw)); return; }catch(e){}
    }
    equipos.push(resumenFusionadoDesdeDOM(eq));
  });
  if(!equipos.length){ alert("No hay equipos en el reporte para exportar."); return; }
  descargarArchivo(
    nombreBaseReporte()+"_FUSIONADO.json",
    JSON.stringify(equipos,null,4),
    'application/json;charset=utf-8;'
  );
}

/* --- LOGICA DE IMPRESIÓN CENTRALIZADA --- */

function getPrintStyle() {
  return `
    <style>
      @media print {
        @page { margin: 15mm; size: auto; }
        body { margin: 0; }
        .no-print { display: none; }
        .page-break { page-break-after: always; }
      }
      body { font-family: 'Arial', sans-serif; font-size: 11px; color: #000; max-width: 700px; margin: auto; padding: 20px; line-height: 1.4; }
      .header-title { display: flex; justify-content: space-between; font-weight: bold; margin-bottom: 20px; font-size: 13px; }
      .row { margin-bottom: 10px; font-size: 11px;}
      .row span { margin-right: 25px; }
      table { width: 100%; border-collapse: collapse; margin-top: 15px; margin-bottom: 20px; }
      th, td { border: 1px solid #000; padding: 5px 8px; text-align: left; }
      .center { text-align: center; }
      .checkboxes { font-family: 'Segoe UI Symbol', sans-serif; }
      .bold { font-weight: bold; }
    </style>
  `;
}

function generarHtmlEtiqueta(d, comps) {
  let fecha = new Date().toLocaleDateString('es-CL');
  let cpuLimpia = d.cpu.replace(/Intel\(R\)|Core\(TM\)/gi, "").trim();

  let trs = comps.map(c => {
     let iconOK   = c.estado === "OK" ? "☑" : "□";
     let iconOBS  = c.estado === "OBS" ? "☑" : "□";
     let iconMalo = c.estado === "MALO" ? "☑" : "□";
     return `<tr>
       <td>${c.nombre}</td>
       <td class="center">${iconOK} OK &nbsp;&nbsp;&nbsp; ${iconOBS} OBS &nbsp;&nbsp;&nbsp; ${iconMalo} MALO</td>
       <td>${c.obs}</td>
     </tr>`;
  }).join("");

  return `
    <div class="header-title">
      <span>ETIQUETAS NOTEBOOK</span>
      <span>FECHA: ${fecha}</span>
    </div>
    <div class="row">
      <span><span class="bold">MODELO:</span> ${d.model}</span>
      <span><span class="bold">PROCESADOR:</span> ${cpuLimpia}</span>
      <span><span class="bold">GUIA:</span> ${d.guia}</span>
      <span><span class="bold">SERIAL:</span> ${d.serial}</span>
    </div>
    <div class="row checkboxes" style="margin-bottom:20px;">
      <span class="bold">ESTADO GLOBAL:</span> &nbsp;&nbsp;&nbsp;&nbsp;
      □ BUENA &nbsp;&nbsp;&nbsp; ☑ POR REPARAR &nbsp;&nbsp;&nbsp; □ MALA &nbsp;&nbsp;&nbsp; □ REPUESTO
    </div>
    <table>
      <thead>
        <tr>
          <th width="20%">REVISIÓN DE COMPONENTES</th>
          <th width="35%" class="center">ESTADO</th>
          <th width="45%">OBSERVACIÓN</th>
        </tr>
      </thead>
      <tbody class="checkboxes">
        ${trs}
      </tbody>
    </table>
    <div class="row checkboxes bold" style="margin-top:20px;">
      CHECKLIST: &nbsp;&nbsp;&nbsp;&nbsp; □ PRUEBA S/O &nbsp;&nbsp;&nbsp;&nbsp; □ HYDRA &nbsp;&nbsp;&nbsp;&nbsp; □ HARDWARE DEFAULT
    </div>
  `;
}

function imprimirEtiqueta(id) {
  let eq = document.getElementById(id);
  if(!eq) return;
  let d = extraerDatos(eq);

  let rawComps = eq.getAttribute('data-comps');
  let comps = [];
  try { comps = JSON.parse(rawComps); } catch(e) {}

  let html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>Etiqueta ${d.serial}</title>${getPrintStyle()}</head><body>${generarHtmlEtiqueta(d, comps)}</body></html>`;

  let printWin = window.open('', '', 'width=800,height=600');
  printWin.document.open();
  printWin.document.write(html);
  printWin.document.close();
  printWin.focus();
  setTimeout(() => { printWin.print(); printWin.close(); }, 350);
}

function imprimirTodasEtiquetas() {
  let etiquetasHtml = [];

  document.querySelectorAll('details').forEach(eq => {
    if (eq.querySelector('.tag-falla')) {
      let d = extraerDatos(eq);
      let rawComps = eq.getAttribute('data-comps');
      let comps = [];
      try { comps = JSON.parse(rawComps); } catch(e) {}

      etiquetasHtml.push(generarHtmlEtiqueta(d, comps));
    }
  });

  if (etiquetasHtml.length === 0) {
    alert("No hay equipos con fallas en este reporte para imprimir.");
    return;
  }

  let contenido = etiquetasHtml.join('<div class="page-break"></div>');

  let html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>Lote de Etiquetas</title>${getPrintStyle()}</head><body>${contenido}</body></html>`;

  let printWin = window.open('', '', 'width=800,height=600');
  printWin.document.open();
  printWin.document.write(html);
  printWin.document.close();
  printWin.focus();
  setTimeout(() => { printWin.print(); printWin.close(); }, 500);
}
</script>
</head>
<body>
<div class="container">
<div class="header">
  <h1>📋 Inventario Maestro de Equipos</h1>
  <p class="subtitle">Sistema de Control de Entregas y Retiros</p>
  <span class="counter-box">Total Equipos: <span id="total-count">0</span></span>

  <div id="stats-container" class="stats-container"></div>

  <div class="button-group">
    <button class="btn btn-copy"   onclick="copiarFilas()">📋 Copiar Filas (Pegar en Valida)</button>
    <button class="btn btn-export" onclick="exportarValidaCSV()">📥 Descargar CSV</button>
    <button class="btn" style="background:#0f766e;" onclick="exportarJsonFusionado()">🧩 Descargar JSON Fusionado</button>
    <button class="btn" style="background:#334155;" onclick="imprimirTodasEtiquetas()">🖨️ Imprimir Lote de Etiquetas</button>
  </div>
</div>
<div id="main-list">"""

HTML_END = "\n</div></div></body></html>"


# ─────────────────────────────────────────────────────────
#  Filas de hardware del reporte HTML — ÚNICA fuente
#
#  El JS del reporte (extraerDatos) lee la RAM, los discos y la red de estas
#  filas, no de los JSON: los th 'Módulo RAM', 'Discos Internos' y
#  'Serie Disco Duro' son el contrato del que salen "Copiar Filas" y el CSV
#  para Valida. Por eso las arma un solo lugar, usado tanto por el escaneo
#  como por la reconstrucción: si divergen, el reporte reconstruido pierde
#  specs y exporta filas incompletas.
# ─────────────────────────────────────────────────────────
def render_filas_ram(ram_list):
    """Filas 'Módulo RAM' desde la lista cruda '8GB|3200|PC4|Fabricante|PN'."""
    if isinstance(ram_list, str):
        ram_list = [ram_list]
    ram_list = [r for r in (ram_list or []) if r]
    return (
        "".join(f"<tr><th>Módulo RAM</th><td>{r}</td></tr>" for r in ram_list)
        or "<tr><th>RAM</th><td>No detectada</td></tr>"
    )


def render_filas_discos(discos):
    """
    Filas de discos desde [{'desc':…, 'serial':…}]. Devuelve (html, seriales).
    El serial se normaliza igual que en el escaneo (sin símbolos, 16 últimos)
    para que el mismo disco dé la misma cadena vino de donde vino.
    """
    if isinstance(discos, dict):
        discos = [discos]
    html_discos = ""
    seriales = []
    for d in discos or []:
        desc = (d.get("desc") or "Desconocido").strip()
        serie = re.sub(r"[^a-zA-Z0-9]", "", str(d.get("serial", "NA")))[-16:]
        seriales.append(serie)
        html_discos += (
            f"<tr><th>Discos Internos</th><td>{desc}</td></tr>"
            f"<tr><th>Serie Disco Duro</th><td class='serial-tag'>{serie}</td></tr>"
        )
    return html_discos, seriales


def render_filas_red(net_list):
    """Filas 'Red Activa' desde la lista cruda de adaptadores."""
    if isinstance(net_list, str):
        net_list = [net_list]
    net_list = [n for n in (net_list or []) if n]
    return (
        "".join(
            f"<tr><td>Red Activa</td><td><span class='net-tag'>{n}</span></td></tr>"
            for n in net_list
        )
        or "<tr><td colspan='2'>Sin red activa</td></tr>"
    )



# ============================================================================
# PLANTILLA COMPARTIDA DE LA ENTRADA <details> DEL REPORTE HTML
# ----------------------------------------------------------------------------
# Constructor único, alimentado SIEMPRE desde el JSON del equipo vía
# reconstruir_entry_desde_json: el HTML del lote se regenera entero en cada
# guardado, así que el JSON individual es la única fuente de verdad.
#
# Por eso la reconstrucción debe reponer todo lo que el registro contiene
# (batería y la Key de Office, que vive en SN_APP): si algo no se rearma aquí,
# desaparece del reporte en la siguiente regeneración.
# ============================================================================
def construir_entry_html(
    *,
    safe_id,
    model,
    serial,
    fecha,
    key,
    cpu,
    mov,
    guia_final,
    num_ot,
    obs_final,
    ram_html,
    disk_html,
    net_rows,
    comps_json,
    fusion_json="",
    tag_falla_html="",
    falla_html="",
    btn_imprimir="",
    office_html="",
    bateria_html="",
    transf_html="",
):
    return f"""<details id="{safe_id}" data-comps='{comps_json}' data-fusion='{fusion_json}' open>
<summary>
  <span class="model-name">{model}</span>
  <span style="font-size:12px;opacity:.85">S/N: {serial} &nbsp;|&nbsp; 📅 {fecha} {tag_falla_html}</span>
</summary>
<div class="content">
  <div class="content-header">
    {btn_imprimir}
    <button class="btn btn-delete" onclick="eliminarEquipo('{safe_id}')">🗑️ Quitar del Reporte</button>
  </div>
  <table>
    <tr class="logistics-row"><th>Tipo Movimiento</th><td><b>{mov}</b></td></tr>
    <tr class="logistics-row"><th>N° de Guía</th><td><b>{guia_final}</b></td></tr>
    <tr class="logistics-row"><th>N° de OT</th><td><b>{num_ot}</b></td></tr>
    {falla_html}
    <tr class="obs-row"><th>⚠️ Obs. General</th><td>{obs_final}</td></tr>
    {office_html}
    <tr><th>Número de Serie</th><td class="serial-tag">{serial}</td></tr>
    <tr><th>Licencia Windows (OA3)</th><td class="win-key">{key}</td></tr>
    <tr><th>Procesador</th><td>{cpu}</td></tr>{bateria_html}
    {ram_html}{disk_html}{transf_html}{net_rows}
  </table>
</div></details>"""


def fijar_total_count(content, total):
    """Reescribe el contador <span id="total-count"> del reporte HTML."""
    return re.sub(
        r'<span id="total-count">\d+</span>',
        f'<span id="total-count">{total}</span>',
        content,
    )


def resumen_fusionado(eq):
    """Resumen logístico de un equipo para el JSON FUSIONADO del lote."""
    sn_app = eq.get("SN_APP", "PENDIENTE")
    obs = eq.get("OBS", "")
    return {
        "SERIAL": eq.get("SERIAL", ""),
        "SN_Win": eq.get("SN_Win", ""),
        "SN_HDD": eq.get("SN_HDD", ""),
        "SN_Transf": eq.get("SN_Transf", "PENDIENTE"),
        "SN_APP": None if sn_app in ("PENDIENTE", "", None) else sn_app,
        "OBS": None if obs in ("Sin observaciones", "", None) else obs,
    }



# ============================================================================
# ENTRADA DE UN EQUIPO DESDE SU JSON — la única forma en que se arma el HTML
# ============================================================================
def _es_html(valor):
    """True si el valor ya viene renderizado como filas de tabla."""
    return isinstance(valor, str) and valor.lstrip().startswith("<")


def _fecha_legible(jdata):
    """Fecha del encabezado del equipo cuando DATA no la trae, desde ESCANEADO."""
    ts = jdata.get("ESCANEADO", "")
    try:
        return datetime.fromisoformat(ts).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return ""


def filas_hardware_desde_json(jdata):
    """
    (ram_html, disk_html, net_html) de un equipo, con cadena de respaldo.

    El HTML del reporte NO es decorativo: el JS lee de estas filas la RAM, los
    discos y sus seriales para "Copiar Filas" y el CSV de Valida. Un JSON al
    que le falte el HTML pre-renderizado —viejo, editado a mano o bajado del
    servidor— daría un reporte que se ve bien pero exporta "RAM Desconocida" y
    sin discos. Por eso se intenta, en orden:

        1. el HTML ya guardado en DATA (lo normal),
        2. los datos crudos (ram_raw / disk_raw / net_raw),
        3. lo que quede: los seriales sueltos o el SN_HDD del nivel superior.
    """
    data = jdata.get("DATA") or {}

    # --- RAM ---
    ram_html = data.get("ram_html")
    if not _es_html(ram_html):
        ram_html = render_filas_ram(data.get("ram_raw") or data.get("ram_rows"))

    # --- Discos ---
    disk_html = data.get("disk_html")
    if not _es_html(disk_html):
        discos = data.get("disk_raw") or data.get("disks_data")
        if not discos:
            # Sin descripción no se puede inventar el modelo del disco, pero el
            # serial sí se conserva: es el dato que viaja a Valida.
            seriales = data.get("disk_serials") or [
                s for s in str(jdata.get("SN_HDD", "")).split("_") if s
            ]
            seriales = [s for s in seriales if s and s != "PENDIENTE"]
            discos = [{"desc": "Disco interno", "serial": s} for s in seriales]
        disk_html, _ = render_filas_discos(discos)

    # --- Red ---
    net_html = data.get("net_rows")
    if not _es_html(net_html):
        if _es_html(data.get("net_html")):
            net_html = data["net_html"]
        else:
            net_html = render_filas_red(data.get("net_raw") or data.get("net_rows"))

    return ram_html, disk_html, net_html


def reconstruir_entry_desde_json(jdata):
    data = jdata.get("DATA") or {}
    obs_final = jdata.get("OBS", "Sin observaciones")
    guia_final = jdata.get("GUIA_ID", "Sin Guía")
    ot = jdata.get("OT_ID", "Sin Orden")
    mov = jdata.get("TIPO_MOVIMIENTO", "Entrega")
    detalle_componentes = jdata.get("DETALLE_COMPONENTES", [])
    office_str = jdata.get("OFFICE", "No")

    # La Key de Office vive en SN_APP: hay que reponerla en la fila porque el
    # export a Valida (filasValida) la saca leyendo el "(Key: ...)" de este
    # texto. Si no se repone, la fila igual se ve en el reporte pero el export
    # la saltea: sin key no hay nada que cargar en Valida.
    office_html = ""
    if office_str and office_str != "No":
        sn_app = jdata.get("SN_APP", "")
        key_part = (
            f" (Key: {sn_app})" if sn_app and sn_app not in ("PENDIENTE", None) else ""
        )
        office_html = (
            f'<tr class="office-row"><th>🔑 Office Instalado</th>'
            f"<td><b>{office_str}</b>{key_part}</td></tr>"
        )

    # El nivel superior del JSON repite serial, modelo y licencia; se usan como
    # respaldo para que un registro con DATA incompleta —editado a mano o de una
    # versión vieja— igual salga con su identidad correcta en el reporte.
    serial = data.get("serial") or jdata.get("SERIAL") or "?"
    model = data.get("model") or jdata.get("MODELO") or "Desconocido"
    win_key = data.get("key") or jdata.get("SN_Win") or "N/A"

    safe_id = f"dev-{re.sub(r'[^a-zA-Z0-9]', '', str(serial)) or 'DESCONOCIDO'}"

    tiene_fallas = jdata.get("TIENE_FALLAS", False)
    fallas_str = ", ".join(
        [
            f"{c['nombre']} ({c['estado']})"
            for c in detalle_componentes
            if c.get("estado", "OK") != "OK"
        ]
    )

    falla_html = ""
    tag_falla_html = ""
    btn_imprimir = ""

    if tiene_fallas:
        tag_falla_html = '<span class="tag-falla">CON FALLAS</span>'
        falla_html = f'<tr class="falla-row"><th>Fallas Detectadas</th><td>{fallas_str}</td></tr>'
        btn_imprimir = (
            f'<button class="btn" style="background:#475569; padding:5px 12px; font-size:11px;" '
            f"onclick=\"imprimirEtiqueta('{safe_id}')\">🖨️ Etiqueta Individual</button>"
        )

    comps_json = html.escape(json.dumps(detalle_componentes))
    fusion_json = html.escape(json.dumps(resumen_fusionado(jdata)))

    ram_html, disk_html, net_rows = filas_hardware_desde_json(jdata)
    bateria_html = (
        f'\n    <tr><th>🔋 Salud Batería</th>'
        f'<td>{data.get("Battery", "No detectada")}</td></tr>'
    )

    # El transformador se carga después del escaneo (módulo aparte), así que la
    # fila solo aparece si ya tiene serial. Va al HTML porque el export a
    # Valida (copiarFilas / CSV) lee del DOM, no de los JSON.
    sn_transf = jdata.get("SN_Transf", TRANSF_PENDIENTE)
    transf_html = ""
    if sn_transf and sn_transf != TRANSF_PENDIENTE:
        transf_html = (
            f'\n    <tr><th>🔌 Serie Transformador</th>'
            f'<td class="transf-tag">{sn_transf}</td></tr>'
        )

    return construir_entry_html(
        safe_id=safe_id,
        model=model,
        serial=serial,
        fecha=data.get("fecha") or _fecha_legible(jdata),
        key=win_key,
        cpu=data.get("cpu", "Desconocido"),
        mov=mov,
        num_ot=ot,
        guia_final=guia_final,
        obs_final=obs_final,
        ram_html=ram_html,
        disk_html=disk_html,
        net_rows=net_rows,
        comps_json=comps_json,
        fusion_json=fusion_json,
        tag_falla_html=tag_falla_html,
        falla_html=falla_html,
        btn_imprimir=btn_imprimir,
        office_html=office_html,
        bateria_html=bateria_html,
        transf_html=transf_html,
    )

