"""
Simulador del celular: habla con el panel "Lector celular" del PC igual que
lo hará la app Android, para probar el flujo completo sin ella.

    1. En el PC: menú → Lector celular → Encender → "Copiar datos de emparejamiento".
    2. Acá:  python herramientas/simular_celular.py  y pegar esos datos.

Cada línea que escribas es un escaneo. Sirve también con la pistola USB: la
pistola escribe el código y aprieta Enter. Para simular una etiqueta con
varios códigos, separalos con ' | '  (ej: 7801234567890 | S/N: 5CD805DVNV).

Comandos:  :modo   :lote   :ver   :salir
"""

import json
import os
import sys
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from inventario.nucleo.api_celular import describir_respuesta  # noqa: E402

TIPOS = ["Notebook", "Monitor", "Impresora", "Transformador"]
GUIADO = "Notebook + transformador (guiado)"
MODOS = TIPOS + [GUIADO]


class Cliente:
    def __init__(self, url, token):
        self.url = url.rstrip("/")
        self.token = token

    def pedir(self, metodo, ruta, datos=None, reintentos=3):
        """(código, dict). Reintenta con el MISMO cuerpo: el id del escaneo evita duplicados."""
        cuerpo = json.dumps(datos).encode() if datos is not None else None
        pedido = urllib.request.Request(
            f"{self.url}/api/v1{ruta}",
            data=cuerpo,
            method=metodo,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        for intento in range(1, reintentos + 1):
            try:
                with urllib.request.urlopen(pedido, timeout=5) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read() or b"{}")
            except OSError as e:
                if intento == reintentos:
                    raise ConnectionError(f"No responde el PC ({e})") from e
                print(f"   …sin respuesta, reintento {intento}/{reintentos - 1}")


def preguntar(texto, opciones):
    for i, op in enumerate(opciones, 1):
        print(f"  {i}) {op}")
    while True:
        r = input(f"{texto} ").strip()
        if r.isdigit() and 1 <= int(r) <= len(opciones):
            return opciones[int(r) - 1]


def si_no(texto):
    return input(f"{texto} (s/n) ").strip().lower().startswith("s")


def elegir_lote(cli):
    _, r = cli.pedir("GET", "/lotes")
    lotes = r.get("lotes", [])
    opciones = [f"{l['etiqueta']}  ({l['equipos']} equipo/s)" for l in lotes] + ["➕ Nuevo lote"]
    print("\nLotes abiertos en el PC:")
    elegido = preguntar("Lote:", opciones)
    if elegido != opciones[-1]:
        l = lotes[opciones.index(elegido)]
        return {"mov": l["mov"], "cliente": l["cliente"], "numero": l["numero"]}

    datos = {
        "mov": preguntar("Movimiento:", ["Entrega", "Retiro"]),
        "cliente": input("Cliente: "),
    }
    es_entrega = datos["mov"] == "Entrega"
    datos["numero"] = input("N° de OT: " if es_entrega else "N° de guía: ")
    datos["numero_sec"] = input("N° de guía (opcional): " if es_entrega else "N° de OT (opcional): ")
    codigo, r = cli.pedir("POST", "/lotes", datos)
    if codigo == 409 and si_no(f"⚠️ {r['mensaje']}"):
        codigo, r = cli.pedir("POST", "/lotes", {**datos, "reabrir": True})
    if codigo != 200:
        print(f"❌ {r.get('mensaje')}")
        return elegir_lote(cli)
    print(f"✅ {r['etiqueta']}")
    return {"mov": r["mov"], "cliente": r["cliente"], "numero": r["numero"]}


def escanear(cli, lote, linea, esperado, serial_equipo=None, **extra):
    datos = {
        "id": str(uuid.uuid4()),
        "lote": lote,
        "lecturas": [{"texto": t.strip()} for t in linea.split(" | ") if t.strip()],
        "esperado": esperado,
        **extra,
    }
    if serial_equipo:
        datos["serial_equipo"] = serial_equipo
    codigo, r = cli.pedir("POST", "/escaneo", datos)
    if codigo != 200:
        print(f"   ❌ {r.get('mensaje', r)}")
        return None

    for d in r.get("descartes", []):
        print(f"   · descartado {d['texto']!r}: {d['motivo']}")
    print(f"   {describir_respuesta(r)}")

    # Las mismas preguntas que hará la app.
    estado = r["estado"]
    if estado == "elegir":
        valor = preguntar("¿Cuál es el serial?", r["candidatos"])
        return escanear(cli, lote, valor, esperado, serial_equipo)
    if estado == "en_otra_ot" and si_no("   ¿Registrarlo igual en este lote?"):
        return escanear(cli, lote, r["serial"], esperado, serial_equipo, forzar=True)
    if estado == "otro_tipo" and si_no(f"   ¿Usarlo igual como {r['esperado']}?"):
        return escanear(cli, lote, r["valor"], esperado, serial_equipo, tipo=r["esperado"])
    if estado == "sin_tipo":
        tipo = preguntar("   ¿Qué es?", TIPOS)
        return escanear(cli, lote, r["valor"], tipo, serial_equipo, tipo=tipo)
    return r


def main():
    # Igual que app.py: una consola cp1252 no revienta por un emoji.
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(errors="replace")
        except Exception:
            pass

    texto =sys.argv[1] if len(sys.argv) > 1 else input("Pegá los datos de emparejamiento: ")
    try:
        datos = json.loads(texto)
        cli = Cliente(datos["url"], datos["token"])
    except (ValueError, KeyError):
        sys.exit("Esos no son los datos del panel (botón 'Copiar datos de emparejamiento').")

    codigo, r = cli.pedir("GET", "/estado")
    if codigo != 200:
        sys.exit(f"El PC respondió {codigo}: {r.get('mensaje')}")
    print("📶 Emparejado con el PC.")

    lote = elegir_lote(cli)
    modo = preguntar("\nQué vas a escanear:", MODOS)
    equipo_guiado = None  # en modo guiado, el notebook que espera su transformador

    print("\nComandos:  :modo   :lote   :ver   :salir   (varios códigos: A | B)\n")
    while True:
        if modo == GUIADO:
            esperado = "Transformador" if equipo_guiado else "Notebook"
            aviso = f"transformador de {equipo_guiado}" if equipo_guiado else "notebook"
        else:
            esperado, aviso = modo, modo.lower()
        linea = input(f"[{aviso}] > ").strip()

        if not linea:
            continue
        if linea == ":salir":
            break
        if linea == ":modo":
            modo, equipo_guiado = preguntar("Qué vas a escanear:", MODOS), None
            continue
        if linea == ":lote":
            lote, equipo_guiado = elegir_lote(cli), None
            continue
        if linea == ":ver":
            _, r = cli.pedir("POST", "/lote", {"lote": lote})
            for e in r.get("equipos", []):
                transf = f"  🔌 {e['sn_transf']}" if e["sn_transf"] else ""
                falta = "  (sin hardware)" if e["sin_hardware"] else ""
                print(f"   {e['tipo']:<10} {e['serial']}{transf}{falta}")
            continue

        try:
            r = escanear(cli, lote, linea, esperado, serial_equipo=equipo_guiado)
        except ConnectionError as e:
            print(f"   ❌ {e}")
            continue
        if modo == GUIADO and r:
            if equipo_guiado is None and r["estado"] in ("registrado", "ya_estaba"):
                equipo_guiado = r["serial"]
            elif equipo_guiado and r["estado"] in ("asignado", "ya_estaba"):
                equipo_guiado = None


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print()
