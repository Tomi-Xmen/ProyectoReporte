"""
Requerimiento de specs de una entrega: lo que el cliente pidió (procesador,
generación, RAM, disco, Office) y la comparación contra cada equipo escaneado.

El requerimiento es de la OT, no del equipo: vive en el '.lote' de la carpeta
(viaja al servidor con ella). Las diferencias NO se guardan en el JSON del
equipo; se calculan al armar el formulario y al regenerar el HTML. Así, si se
corrige el requerimiento o se mueve un equipo a otra OT, la alerta se ajusta
sola en vez de quedar pegada a lo que decía el día del escaneo.

La regla es "distinto", no "menos": un equipo con más RAM que la pedida
también se avisa, porque no es lo que se comprometió con el cliente.
"""

import re

CLAVES = ("cpu", "generacion", "ram_gb", "disco_gb", "disco_tipo", "office", "nota")

TIPOS_DISCO = ("SSD", "HDD")

# Margen para el tamaño del disco: el escaneo mide en GB decimales y el mismo
# disco "de 512" puede leerse 500, 512 o 480 según fabricante.
TOLERANCIA_DISCO = 0.10


def _a_gb(valor):
    """'16', '16 GB', '1 TB', 16 → GB enteros; 0 si no hay número."""
    if isinstance(valor, (int, float)):
        return max(int(valor), 0)
    texto = str(valor or "").strip().upper().replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", texto)
    if not m:
        return 0
    gb = float(m.group(0))
    if "TB" in texto[m.end():]:
        gb *= 1000
    return int(round(gb))


def normalizar(req):
    """
    Requerimiento con tipos fijos y sin campos vacíos: 0, "" y "Cualquiera"
    significan "no se pidió" y se descartan. Devuelve {} si no queda nada.
    """
    if not isinstance(req, dict):
        return {}
    limpio = {}
    cpu = re.sub(r"\s+", " ", str(req.get("cpu") or "")).strip()
    if cpu and cpu.lower() != "cualquiera":
        limpio["cpu"] = cpu
    for clave in ("generacion", "ram_gb", "disco_gb"):
        n = _a_gb(req.get(clave))
        if n:
            limpio[clave] = n
    tipo = str(req.get("disco_tipo") or "").strip().upper()
    if tipo in TIPOS_DISCO:
        limpio["disco_tipo"] = tipo
    office = req.get("office")
    if isinstance(office, str):
        office = {"SÍ": True, "SI": True, "NO": False}.get(office.strip().upper())
    if isinstance(office, bool):
        limpio["office"] = office
    nota = str(req.get("nota") or "").strip()
    if nota:
        limpio["nota"] = nota
    return limpio


def resumen(req):
    """'i5 · 8ª gen · 16 GB RAM · 512 GB SSD · con Office', o '' si no hay."""
    req = normalizar(req)
    partes = []
    if "cpu" in req:
        partes.append(req["cpu"])
    if "generacion" in req:
        partes.append(f"{req['generacion']}ª gen")
    if "ram_gb" in req:
        partes.append(f"{req['ram_gb']} GB RAM")
    if "disco_gb" in req or "disco_tipo" in req:
        tam = f"{req['disco_gb']} GB" if "disco_gb" in req else "Disco"
        partes.append(f"{tam} {req.get('disco_tipo', '')}".strip())
    if "office" in req:
        partes.append("con Office" if req["office"] else "sin Office")
    return " · ".join(partes)


# ─────────────────────────────────────────────────────────
#  Lectura de lo escaneado
# ─────────────────────────────────────────────────────────
def _texto_cpu(cpu):
    texto = str(cpu or "").lower()
    texto = re.sub(r"\((r|tm)\)|®|™", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def generacion_cpu(cpu):
    """
    Generación del procesador desde su nombre, o 0 si no se reconoce.

    Intel Core: i5-8350U → 8, i5-10210U → 10, i5-1135G7 → 11 (los modelos de
    4 cifras que empiezan con 1 son de 10ª en adelante, no de 1ª: esa usaba
    3 cifras, i5-520M → 1). Ryzen 5 5500U → 5. Core Ultra 5 125U → 1.
    """
    texto = _texto_cpu(cpu)
    # La 1ª gen se nombraba 'Core i5 CPU M 520': de ahí el 'cpu x' opcional.
    m = re.search(r"\bi[3579](?:\s+cpu\s+[a-z]+)?[\s-]+(\d{3,5})", texto)
    if m:
        cifras = m.group(1)
        if len(cifras) == 5 or (len(cifras) == 4 and cifras[0] == "1"):
            return int(cifras[:2])
        if len(cifras) == 3:
            return 1
        return int(cifras[0])
    m = re.search(r"\bryzen\s+\d\s+(?:pro\s+)?(\d)\d{3}", texto)
    if m:
        return int(m.group(1))
    m = re.search(r"\bultra\s+\d\s+(\d)\d{2}", texto)
    if m:
        return int(m.group(1))
    return 0


def cpu_coincide(pedido, cpu):
    """
    Cada palabra de lo pedido aparece como comienzo de palabra en el nombre
    del procesador: 'i5' entra en 'Core i5-8350U' pero 'i7' no; 'Ryzen 5'
    exige 'ryzen' y '5'.
    """
    texto = _texto_cpu(cpu)
    return all(
        re.search(r"(?<![a-z0-9])" + re.escape(palabra), texto)
        for palabra in _texto_cpu(pedido).split()
    )


def ram_total_gb(data):
    """Suma de los módulos 'NGB | velocidad | …'. 0 si no se pudo leer."""
    modulos = data.get("ram_raw") or []
    if isinstance(modulos, str):
        modulos = [modulos]
    total = 0
    for modulo in modulos:
        m = re.match(r"\s*(\d+)\s*GB", str(modulo), flags=re.IGNORECASE)
        if m:
            total += int(m.group(1))
    return total


def discos(data):
    """[(GB, 'SSD'|'HDD'|''), …] desde las descripciones 'Modelo 512GB SSD NVMe'."""
    crudos = data.get("disk_raw") or []
    if isinstance(crudos, dict):
        crudos = [crudos]
    encontrados = []
    for d in crudos:
        desc = str((d or {}).get("desc", "")) if isinstance(d, dict) else str(d)
        m = re.search(r"(\d+)\s*GB", desc, flags=re.IGNORECASE)
        if not m:
            continue
        tipo = next((t for t in TIPOS_DISCO if re.search(rf"\b{t}\b", desc.upper())), "")
        encontrados.append((int(m.group(1)), tipo))
    return encontrados


def _mismo_tamano(gb, pedido):
    return abs(gb - pedido) <= pedido * TOLERANCIA_DISCO


def _comparar_cantidad(nombre, tiene, pedido, unidad=" GB"):
    if tiene == pedido:
        return None
    if not tiene:
        return f"{nombre}: no se pudo leer (se pidió {pedido}{unidad})"
    sentido = "más" if tiene > pedido else "menos"
    return f"{nombre}: tiene {tiene}{unidad}, se pidió {pedido}{unidad} ({sentido})"


# ─────────────────────────────────────────────────────────
#  Comparación
# ─────────────────────────────────────────────────────────
def comparar(req, data, tiene_office=None):
    """
    Lista de diferencias legibles entre el requerimiento y el equipo escaneado
    ('data' de get_inventory_fast). Vacía si coincide o no hay requerimiento.
    Office solo se compara si se sabe (tiene_office no es None): sale del
    formulario, no del hardware.
    """
    req = normalizar(req)
    data = data or {}
    difs = []

    cpu = data.get("cpu", "")
    if "cpu" in req and not cpu_coincide(req["cpu"], cpu):
        difs.append(f"Procesador: tiene {cpu or 'desconocido'}, se pidió {req['cpu']}")
    if "generacion" in req:
        gen = generacion_cpu(cpu)
        if gen != req["generacion"]:
            if not gen:
                difs.append(
                    f"Generación: no se reconoce en '{cpu or 'desconocido'}' "
                    f"(se pidió {req['generacion']}ª)"
                )
            else:
                sentido = "más nueva" if gen > req["generacion"] else "más vieja"
                difs.append(
                    f"Generación: es {gen}ª, se pidió {req['generacion']}ª ({sentido})"
                )

    if "ram_gb" in req:
        dif = _comparar_cantidad("RAM", ram_total_gb(data), req["ram_gb"])
        if dif:
            difs.append(dif)

    if "disco_gb" in req or "disco_tipo" in req:
        lista = discos(data)
        pedido_gb, pedido_tipo = req.get("disco_gb"), req.get("disco_tipo")
        cumple = any(
            (not pedido_gb or _mismo_tamano(gb, pedido_gb))
            and (not pedido_tipo or tipo == pedido_tipo)
            for gb, tipo in lista
        )
        if not cumple:
            tiene = " + ".join(f"{gb} GB {tipo}".strip() for gb, tipo in lista)
            pedido = " ".join(
                p for p in (f"{pedido_gb} GB" if pedido_gb else "", pedido_tipo) if p
            )
            difs.append(
                f"Disco: tiene {tiene or 'ninguno legible'}, se pidió {pedido}"
            )

    if "office" in req and tiene_office is not None and bool(tiene_office) != req["office"]:
        difs.append(
            "Office: se pidió con Office y no lo tiene"
            if req["office"]
            else "Office: se pidió sin Office y lo tiene"
        )
    return difs


def diferencias_equipo(req, jdata):
    """comparar() sobre un JSON de equipo ya guardado (Office sale de 'OFFICE')."""
    office = jdata.get("OFFICE")
    tiene_office = None if office is None else office not in ("No", "", None)
    return comparar(req, jdata.get("DATA") or {}, tiene_office)
