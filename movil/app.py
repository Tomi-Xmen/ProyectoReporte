"""
Reporte Móvil — vista web para el celular, corre en el servidor 192.168.10.15.
============================================================================

Lee DIRECTO el árbol que REPORTE3.py sube por SCP (no pasa por SSH ni toca
el .exe): OT abiertas, OT activa publicada y equipos llegados vs esperados.

Lo único que escribe es '.transformadores' en la carpeta de la OT (módulo
2): los pares equipo → transformador escaneados desde el celular. NUNCA toca
los JSON de los equipos — el escritorio los re-sube por SCP y pisaría
cualquier cambio hecho acá. El escritorio lee ese archivo al abrir su módulo
"Agregar transformadores" y fusiona lo que falta.

Disposición que se lee (idéntica a la de REPORTE3.py, ver _MOV_CFG allá):

    <BASE>/_control/.lote_activo.json          OT que recibe lo escaneado
    <BASE>/ENTREGA/<CLIENTE>/OT-553/*.json      un JSON por equipo
    <BASE>/RETIROS/<CLIENTE>/GUIA-8891/*.json
    <carpeta del lote>/.esperados              lista JSON de seriales
    <carpeta del lote>/.cerrado                lote finalizado
    <carpeta del lote>/.transformadores        lo escaneado desde el celular

Configuración por variables de entorno (ver .env.example).
"""

import fcntl
import hmac
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

# Debe calzar con _MOV_CFG de REPORTE3.py.
MOV_CFG = {
    "Entrega": {"grupo": "ENTREGA", "prefijo": "OT", "tipo_doc": "Entregas"},
    "Retiro": {"grupo": "RETIROS", "prefijo": "GUIA", "tipo_doc": "Retiros"},
}
GRUPO_A_MOV = {cfg["grupo"]: mov for mov, cfg in MOV_CFG.items()}
MOV_CFG_GRUPOS = [cfg["grupo"] for cfg in MOV_CFG.values()]

CONTROL = "_control"
ARCHIVO_LOTE_ACTIVO = ".lote_activo.json"
ARCHIVO_ESPERADOS = ".esperados"
MARCADOR_CERRADO = ".cerrado"
TRANSF_PENDIENTE = "PENDIENTE"
# Sin extensión .json a propósito (igual que .esperados): así ni este módulo
# ni REPORTE3.py lo confunden con el JSON de un equipo, y el escritorio
# nunca lo sube ni lo pisa.
ARCHIVO_TRANSF_MOVIL = ".transformadores"

BASE = os.environ.get(
    "REPORTES_BASE",
    "/srv/dev-disk-by-uuid-50e34ae9-5743-420d-b093-89dfd29299cd"
    "/DocumentosLab/Reportes_Guardados",
)
CLAVE = os.environ.get("MOVIL_CLAVE", "")

app = Flask(__name__)
# Fija en el .env: si se generara al azar, cada reinicio del servicio (o cada
# worker de gunicorn) invalidaría la sesión y pediría la clave de nuevo.
app.secret_key = os.environ.get("MOVIL_SECRET_KEY") or os.urandom(32)
app.permanent_session_lifetime = timedelta(days=90)
# Ahora hay formularios que escriben: la cookie no viaja en POST de otro sitio.
app.config["SESSION_COOKIE_SAMESITE"] = "Strict"


# ─────────────────────────────────────────────────────────
#  Acceso: una sola clave (un solo usuario, red de oficina)
# ─────────────────────────────────────────────────────────
def requiere_login(vista):
    @wraps(vista)
    def envuelta(*args, **kwargs):
        if not session.get("ok"):
            return redirect(url_for("login", siguiente=request.path))
        return vista(*args, **kwargs)

    return envuelta


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        if not CLAVE:
            error = "Falta MOVIL_CLAVE en el servidor."
        elif hmac.compare_digest(request.form.get("clave", ""), CLAVE):
            session.permanent = True
            session["ok"] = True
            siguiente = request.args.get("siguiente", "")
            # Solo rutas internas: nada de redirigir a otro host.
            if not siguiente.startswith("/") or siguiente.startswith("//"):
                siguiente = url_for("inicio")
            return redirect(siguiente)
        else:
            error = "Clave incorrecta."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ─────────────────────────────────────────────────────────
#  Lectura del árbol
# ─────────────────────────────────────────────────────────
def _leer_json(ruta):
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _nombre_valido(nombre):
    """Un solo componente de ruta, sin trucos: evita salir de BASE."""
    return bool(nombre) and nombre not in (".", "..") and "/" not in nombre and "\\" not in nombre


def _subdirs(ruta):
    try:
        return sorted(e.name for e in os.scandir(ruta) if e.is_dir() and not e.name.startswith("."))
    except OSError:
        return []


def ruta_lote(grupo, cliente, carpeta):
    if grupo not in GRUPO_A_MOV or not (_nombre_valido(cliente) and _nombre_valido(carpeta)):
        abort(404)
    ruta = os.path.join(BASE, grupo, cliente, carpeta)
    if not os.path.isdir(ruta):
        abort(404)
    return ruta


def _es_json_equipo(nombre):
    return nombre.endswith(".json") and not nombre.endswith("_FUSIONADO.json")


def contar_equipos(ruta):
    try:
        return sum(1 for n in os.listdir(ruta) if _es_json_equipo(n))
    except OSError:
        return 0


def leer_equipos(ruta):
    """JSON individuales del lote, del más reciente al más antiguo."""
    equipos = []
    try:
        nombres = os.listdir(ruta)
    except OSError:
        return equipos
    for nombre in nombres:
        if not _es_json_equipo(nombre):
            continue
        jdata = _leer_json(os.path.join(ruta, nombre))
        if isinstance(jdata, dict) and jdata.get("SERIAL"):
            equipos.append(jdata)
    equipos.sort(key=lambda j: j.get("ESCANEADO", ""), reverse=True)
    return equipos


def leer_esperados(ruta):
    datos = _leer_json(os.path.join(ruta, ARCHIVO_ESPERADOS))
    if not isinstance(datos, list):
        return []
    return [str(s).strip().upper() for s in datos if str(s).strip()]


def leer_lote_activo():
    """(grupo, cliente, carpeta) de la OT publicada, o None."""
    cfg = _leer_json(os.path.join(BASE, CONTROL, ARCHIVO_LOTE_ACTIVO))
    if not isinstance(cfg, dict) or cfg.get("mov") not in MOV_CFG:
        return None
    mov = MOV_CFG[cfg["mov"]]
    clave = (mov["grupo"], str(cfg.get("cliente", "")), f"{mov['prefijo']}-{cfg.get('numero', '')}")
    ruta = os.path.join(BASE, *clave)
    # Mismo criterio que el escritorio: una OT cerrada no sigue activa.
    if os.path.exists(os.path.join(ruta, MARCADOR_CERRADO)):
        return None
    return clave


def listar_lotes_abiertos():
    lotes = []
    for grupo in MOV_CFG_GRUPOS:
        base_grupo = os.path.join(BASE, grupo)
        for cliente in _subdirs(base_grupo):
            for carpeta in _subdirs(os.path.join(base_grupo, cliente)):
                ruta = os.path.join(base_grupo, cliente, carpeta)
                if os.path.exists(os.path.join(ruta, MARCADOR_CERRADO)):
                    continue
                lotes.append(
                    {
                        "grupo": grupo,
                        "cliente": cliente,
                        "carpeta": carpeta,
                        "equipos": contar_equipos(ruta),
                        "mtime": os.path.getmtime(ruta),
                    }
                )
    lotes.sort(key=lambda l: l["mtime"], reverse=True)
    return lotes


def comparar(equipos, esperados, transf_movil=None):
    """
    Filas para la vista, igual que el Panel de clonación del escritorio:
    'ok' llegó y se esperaba (o no hay lista), 'sobra' llegó sin esperarse,
    'falta' se esperaba y no llegó.

    'transf' es lo que ya está en el JSON (lo guardó el escritorio);
    'transf_movil' es lo escaneado acá que el escritorio todavía no fusionó
    (o que quedó distinto a lo del escritorio: se muestran los dos).
    """
    transf_movil = transf_movil or {}
    set_esperados = set(esperados)
    filas = []
    recibidos = set()
    for eq in equipos:
        sn = str(eq.get("SERIAL", "")).strip().upper()
        recibidos.add(sn)
        transf = normalizar_sn(eq.get("SN_Transf", ""))
        movil = (transf_movil.get(sn) or {}).get("sn", "")
        filas.append(
            {
                "estado": "ok" if not esperados or sn in set_esperados else "sobra",
                "serial": eq.get("SERIAL", ""),
                "modelo": eq.get("MODELO", "") or (eq.get("DATA") or {}).get("model", ""),
                "fecha": (eq.get("DATA") or {}).get("fecha", "") or eq.get("ESCANEADO", ""),
                "transf": transf,
                "transf_movil": "" if movil.upper() == transf.upper() else movil,
            }
        )
    for sn in esperados:
        if sn not in recibidos:
            filas.append(
                {"estado": "falta", "serial": sn, "modelo": "", "fecha": "", "transf": "", "transf_movil": ""}
            )
    return filas


# ─────────────────────────────────────────────────────────
#  Módulo 2: transformadores escaneados desde el celular
# ─────────────────────────────────────────────────────────
#  Formato de .transformadores (clave = serial del equipo en mayúsculas):
#      {"5CD1234XYZ": {"sn": "WTGAB123", "fecha": "2026-10-01T10:22:05"}}
def normalizar_sn(valor):
    """Serial utilizable, o '' si viene vacío o PENDIENTE (como el escritorio)."""
    limpio = " ".join(str(valor or "").split())
    return "" if limpio.upper() in ("", TRANSF_PENDIENTE) else limpio


def leer_transf_movil(ruta):
    datos = _leer_json(os.path.join(ruta, ARCHIVO_TRANSF_MOVIL))
    if not isinstance(datos, dict):
        return {}
    return {
        str(k).strip().upper(): v
        for k, v in datos.items()
        if isinstance(v, dict) and normalizar_sn(v.get("sn"))
    }


@contextmanager
def transf_movil_editable(ruta):
    """
    Lee .transformadores con lock y lo reescribe al salir (atómico: temporal +
    rename), para que dos envíos seguidos desde el celular no se pisen.
    """
    with open(os.path.join(ruta, ARCHIVO_TRANSF_MOVIL + ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        datos = leer_transf_movil(ruta)
        yield datos
        fd, tmp = tempfile.mkstemp(dir=ruta, prefix=".transf-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(datos, f, ensure_ascii=False, indent=2, sort_keys=True)
            os.chmod(tmp, 0o664)
            os.replace(tmp, os.path.join(ruta, ARCHIVO_TRANSF_MOVIL))
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise


def transf_vigente(eq_json, transf_movil, sn_equipo):
    """Transformador que el equipo tiene hoy: lo del celular manda sobre el JSON."""
    movil = (transf_movil.get(sn_equipo) or {}).get("sn", "")
    return movil or normalizar_sn((eq_json or {}).get("SN_Transf", ""))


def _clave_orden(jdata):
    """Timestamp ordenable del escaneo, igual que _clave_orden de REPORTE3.py."""
    ts = jdata.get("ESCANEADO", "")
    if ts:
        return ts
    fecha = (jdata.get("DATA") or {}).get("fecha", "")
    try:
        return datetime.strptime(fecha, "%d/%m/%Y %H:%M").isoformat(timespec="seconds")
    except ValueError:
        return ""


def equipos_en_orden(ruta):
    """
    {SERIAL (mayúsculas): jdata} en ORDEN DE ESCANEO, el más viejo primero.
    Es el orden en que se etiquetaron los equipos y el mismo del módulo de
    transformadores del escritorio: el trafo escaneado cae en el primero que
    no tiene, como la pistola bajando por la grilla.
    """
    equipos = sorted(leer_equipos(ruta), key=_clave_orden)
    return {str(e["SERIAL"]).strip().upper(): e for e in equipos}


def siguiente_sin_transf(equipos, transf_movil):
    return next((sn for sn, eq in equipos.items() if not transf_vigente(eq, transf_movil, sn)), None)


def validar_transf(sn_transf, destino, equipos, transf_movil, elegido):
    """
    (errores, avisos). Los errores bloquean; los avisos se pueden saltar
    confirmando, igual que el "¿Guardar igual?" del escritorio.
    """
    errores, avisos = [], []
    if not sn_transf:
        return ["Falta el serial del transformador."], avisos
    if not destino:
        return ["Todos los equipos de la OT ya tienen transformador."], avisos
    if sn_transf.upper() in equipos:
        errores.append(
            f"{sn_transf} es el serial de un equipo de la OT, no de un transformador."
        )
    actual = transf_vigente(equipos[destino], transf_movil, destino)
    if elegido and actual and actual.upper() != sn_transf.upper():
        avisos.append(f"{destino} ya tiene el transformador {actual}: se va a reemplazar.")
    for otro, eq in equipos.items():
        if otro != destino and transf_vigente(eq, transf_movil, otro).upper() == sn_transf.upper():
            avisos.append(f"El transformador {sn_transf} ya está asignado a {otro}.")
    return errores, avisos


# ─────────────────────────────────────────────────────────
#  Vistas
# ─────────────────────────────────────────────────────────
@app.route("/")
@requiere_login
def inicio():
    if not os.path.isdir(BASE):
        return render_template("inicio.html", error_base=BASE, lotes=[], activo=None)
    activo = leer_lote_activo()
    lotes = listar_lotes_abiertos()
    for l in lotes:
        l["activo"] = activo == (l["grupo"], l["cliente"], l["carpeta"])
    return render_template("inicio.html", error_base=None, lotes=lotes, activo=activo)


@app.route("/lote/<grupo>/<cliente>/<carpeta>")
@requiere_login
def lote(grupo, cliente, carpeta):
    ruta = ruta_lote(grupo, cliente, carpeta)
    esperados = leer_esperados(ruta)
    filas = comparar(leer_equipos(ruta), esperados, leer_transf_movil(ruta))
    resumen = {
        "llegados": sum(1 for f in filas if f["estado"] != "falta"),
        "esperados": len(esperados),
        "faltan": sum(1 for f in filas if f["estado"] == "falta"),
        "sobran": sum(1 for f in filas if f["estado"] == "sobra"),
        "con_transf": sum(1 for f in filas if f["transf"] or f["transf_movil"]),
    }
    return render_template(
        "lote.html",
        grupo=grupo,
        cliente=cliente,
        carpeta=carpeta,
        tipo_doc=MOV_CFG[GRUPO_A_MOV[grupo]]["tipo_doc"],
        cerrado=os.path.exists(os.path.join(ruta, MARCADOR_CERRADO)),
        activo=leer_lote_activo() == (grupo, cliente, carpeta),
        filas=filas,
        resumen=resumen,
    )


@app.route("/lote/<grupo>/<cliente>/<carpeta>/transformadores", methods=["GET", "POST"])
@requiere_login
def transformadores(grupo, cliente, carpeta):
    ruta = ruta_lote(grupo, cliente, carpeta)
    equipos = equipos_en_orden(ruta)
    transf_movil = leer_transf_movil(ruta)
    cerrado = os.path.exists(os.path.join(ruta, MARCADOR_CERRADO))
    # Normalmente el trafo va al siguiente equipo sin trafo. Tocando una
    # tarjeta se elige otro (para corregir uno que quedó mal).
    elegido = request.values.get("equipo", "").strip().upper()
    if elegido not in equipos:
        elegido = ""
    destino = elegido or siguiente_sin_transf(equipos, transf_movil)
    sn_transf = ""
    errores, avisos = [], []

    if request.method == "POST" and not cerrado:
        sn_transf = normalizar_sn(request.form.get("transf", ""))
        errores, avisos = validar_transf(sn_transf, destino, equipos, transf_movil, bool(elegido))
        if not errores and (not avisos or request.form.get("confirmar") == "1"):
            with transf_movil_editable(ruta) as datos:
                datos[destino] = {
                    "sn": sn_transf,
                    "fecha": datetime.now().isoformat(timespec="seconds"),
                }
            flash(f"✅ {sn_transf} → {equipos[destino].get('SERIAL', destino)}")
            # PRG: recargar la página no vuelve a mandar el trafo. Sin
            # 'equipo' en la URL: el próximo escaneo vuelve al orden normal.
            return redirect(url_for("transformadores", grupo=grupo, cliente=cliente, carpeta=carpeta))

    filas = []
    for i, (sn, eq) in enumerate(equipos.items(), start=1):
        filas.append(
            {
                "n": i,
                "serial": eq.get("SERIAL", sn),
                "clave": sn,
                "modelo": eq.get("MODELO", "") or (eq.get("DATA") or {}).get("model", ""),
                "escritorio": normalizar_sn(eq.get("SN_Transf", "")),
                "movil": (transf_movil.get(sn) or {}).get("sn", ""),
            }
        )
    return render_template(
        "transformadores.html",
        grupo=grupo,
        cliente=cliente,
        carpeta=carpeta,
        cerrado=cerrado,
        destino=destino,
        destino_eq=equipos.get(destino) or {},
        elegido=elegido,
        sn_transf=sn_transf,
        errores=errores,
        avisos=avisos,
        filas=filas,
        con_transf=sum(1 for f in filas if f["escritorio"] or f["movil"]),
        # Escaneados en el celular que el escritorio aún no tiene.
        sin_fusionar=sum(1 for f in filas if f["movil"] and f["movil"].upper() != f["escritorio"].upper()),
        # Solo al volver de un guardado exitoso (GET tras el redirect) y en el
        # orden normal: con errores, avisos o un equipo elegido, se mira primero.
        reabrir_camara=request.method == "GET" and not elegido,
    )


@app.route("/lote/<grupo>/<cliente>/<carpeta>/transformadores/quitar", methods=["POST"])
@requiere_login
def quitar_transformador(grupo, cliente, carpeta):
    ruta = ruta_lote(grupo, cliente, carpeta)
    if os.path.exists(os.path.join(ruta, MARCADOR_CERRADO)):
        abort(409)
    sn = request.form.get("equipo", "").strip().upper()
    with transf_movil_editable(ruta) as datos:
        quitado = datos.pop(sn, None)
    if quitado:
        flash(f"Quitado {quitado.get('sn', '')} de {sn} (solo lo del celular).")
    return redirect(url_for("transformadores", grupo=grupo, cliente=cliente, carpeta=carpeta))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("MOVIL_PUERTO", "5070")), debug=False)
