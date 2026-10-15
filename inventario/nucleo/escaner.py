"""
Escáner de hardware: corre un script de PowerShell (CIM/WMI + powercfg) y
devuelve el dict `data` que usa todo el resto (formulario, guardado, HTML).
Además, las utilidades que leen o cambian la identidad del equipo.
"""

import json
import os
import re
import socket
import subprocess
import tempfile
import time
from datetime import datetime

from .reporte_html import render_filas_discos, render_filas_ram, render_filas_red

PS_SCRIPT = """
$ErrorActionPreference = 'SilentlyContinue'
$bios   = Get-CimInstance Win32_Bios
$sys    = Get-CimInstance Win32_ComputerSystem
$cpu    = Get-CimInstance Win32_Processor
$svc    = Get-CimInstance SoftwareLicensingService
$winKey = if ($svc.OA3xOriginalProductKey) { $svc.OA3xOriginalProductKey } else { "No encontrada en BIOS" }

# --- NUEVO: LÓGICA DE BATERÍA CON POWERCFG XML ---
$battInfo = "No detectada"
$xmlPath = "$env:TEMP\\batt_report_temp.xml"
if (Test-Path $xmlPath) { Remove-Item $xmlPath -Force -ErrorAction SilentlyContinue }

# Ejecutamos powercfg silenciosamente para que genere el XML
& powercfg /batteryreport /xml /output $xmlPath | Out-Null

if (Test-Path $xmlPath) {
    try {
        [xml]$battXml = Get-Content $xmlPath
        $baterias = $battXml.BatteryReport.Batteries.Battery
        if ($baterias) {
            # Tomar la primera batería por si el equipo tiene dos
            $bat = if ($baterias.Count -gt 1) { $baterias[0] } else { $baterias }

            $design = [int]$bat.DesignCapacity
            $full = [int]$bat.FullChargeCapacity

            if ($design -gt 0) {
                $salud = [math]::Round(($full / $design) * 100)
                if ($salud -gt 100) { $salud = 100 } # Tope visual al 100%
                $battInfo = "$salud% | Diseño: $design mWh | Actual: $full mWh"
            }
        }
    } catch {
        $battInfo = "Error al leer datos XML"
    }
    # Autodestruir el reporte temporal para no dejar basura
    Remove-Item $xmlPath -Force -ErrorAction SilentlyContinue
}
# ------------------------------------------------

$ramInfo = @(Get-CimInstance Win32_PhysicalMemory | ForEach-Object {
    $speed = if ($_.Speed) { "$($_.Speed)" } else { "Desconocida" }
    $Partnumber = if ($_.PartNumber) { $_.PartNumber.Trim() } else { "Desconocida" }
    $Manufacturer = if ($_.Manufacturer) { $_.Manufacturer.Trim() } else { "Desconocida" }
    $typeNum = if ($_.SMBIOSMemoryType) { $_.SMBIOSMemoryType } else { $_.MemoryType }
    $typeStr = switch ($typeNum) { 24 {"PC3"} 26 {"PC4"} 30 {"LPDDR4"} 34 {"PC5"} 35 {"LPDDR5"} default {"PC4"} }
    "{0}GB | {1} | {2} | {3} | {4}" -f ([math]::Round($_.Capacity/1GB)), $speed, $typeStr, $Manufacturer, $Partnumber
})

$disksData = @(Get-PhysicalDisk | Where-Object { $_.BusType -notin @('USB','File Backed Virtual') } | ForEach-Object {
    $size  = [math]::Round($_.Size / 1000000000)
    $media = if ([string]::IsNullOrWhiteSpace($_.MediaType) -or $_.MediaType -eq 'Unspecified') { 'SSD' } else { [string]$_.MediaType }
    $bus   = if ([string]$_.BusType -match 'NVMe') { 'M.2' } else { [string]$_.BusType }
    @{ desc = "{0} {1}GB {2} {3}" -f $_.FriendlyName.Trim(), $size, $media, $bus
       serial = if ($_.SerialNumber) { $_.SerialNumber.Trim() } else { "SIN-SERIE" } }
})
if ($disksData.Count -eq 0) {
    $disksData = @(Get-CimInstance Win32_DiskDrive | Where-Object { $_.InterfaceType -ne 'USB' } | ForEach-Object {
        @{ desc = "{0} {1}GB SSD" -f $_.Model.Trim(), ([math]::Round($_.Size/1000000000))
           serial = if ($_.SerialNumber) { $_.SerialNumber.Trim() } else { "SIN-SERIE" } }
    })
}

$netInfo = @(Get-CimInstance Win32_NetworkAdapterConfiguration | Where-Object { $_.IPEnabled } | ForEach-Object {
    "{0} | IP: {1} | MAC: {2}" -f $_.Description, $_.IPAddress[0], $_.MACAddress
})

@{ serial=($bios.SerialNumber); model=($sys.Model); win_key=($winKey)
   cpu=($cpu.Name); ram_rows=$ramInfo; disks_data=$disksData; net_rows=$netInfo; battery=($battInfo)
} | ConvertTo-Json -Compress -Depth 3
"""


def get_inventory_fast(max_retries=3, timeout_per_attempt=45):
    last_error = None

    for attempt in range(1, max_retries + 1):
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".ps1", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(PS_SCRIPT)
                tmp_path = tmp.name

            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0  # SW_HIDE

            cmd = [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                tmp_path,
            ]

            result = subprocess.check_output(
                cmd,
                text=True,
                startupinfo=si,
                stderr=subprocess.PIPE,
                timeout=timeout_per_attempt,
            )

            json_match = re.search(r"\{.*\}", result, flags=re.DOTALL)
            if not json_match:
                raise ValueError(
                    f"Salida de PowerShell no contiene JSON válido "
                    f"(intento {attempt}/{max_retries}). "
                    f"Salida recibida: {result[:200]!r}"
                )

            data = json.loads(json_match.group(0))

            try:
                os.unlink(tmp_path)
                tmp_path = None
            except Exception:
                pass

            raw_model = data.get("model", "Desconocido")
            cln_model = re.sub(
                r'(?i)\b(11\.6|12\.5|13\.3|14|15\.6|16|17\.3)\s*(inch|")?\b',
                "",
                raw_model,
            )
            cln_model = re.sub(r"(?i)\bnotebook\s*pc\b", "", cln_model)
            cln_model = re.sub(r"\s+", " ", cln_model).strip()

            ram_list = data.get("ram_rows", [])
            if isinstance(ram_list, str):
                ram_list = [ram_list]
            ram_html = render_filas_ram(ram_list)

            fabricantes_ram = []
            for r in ram_list:
                partes = r.split("|")
                if len(partes) >= 4:
                    fabricantes_ram.append(partes[3].strip())
            fabricantes_unicos = list(set(fabricantes_ram))
            fabricante_final = (
                " / ".join(fabricantes_unicos) if fabricantes_unicos else "Desconocida"
            )

            partnumbers_ram = []
            for r in ram_list:
                partes = r.split("|")
                if len(partes) >= 5:
                    partnumbers_ram.append(partes[4].strip())
            partnumber_final = (
                " / ".join(set(partnumbers_ram)) if partnumbers_ram else "Desconocida"
            )

            disks = data.get("disks_data", [])
            if isinstance(disks, dict):
                disks = [disks]
            disk_html, disk_serials = render_filas_discos(disks)

            net_list = data.get("net_rows", [])
            if isinstance(net_list, str):
                net_list = [net_list]
            net_html = render_filas_red(net_list)

            return {
                "fecha": datetime.now().strftime("%d/%m/%Y %H:%M"),
                "host": socket.gethostname(),
                "model": cln_model,
                "serial": data.get("serial", "SN_DESCONOCIDO").strip(),
                "key": data.get("win_key", "N/A"),
                "cpu": data.get("cpu", "Desconocido"),
                "ram_html": ram_html,
                "ram_raw": ram_list,
                "disk_html": disk_html,
                # Crudos además del HTML: si el HTML se pierde o cambia de
                # formato, la reconstrucción rearma las filas desde acá sin
                # perder la descripción del disco (que el serial solo no trae).
                "disk_raw": disks,
                "disk_serials": disk_serials,
                "net_html": net_html,
                "net_raw": net_list,
                # Se conserva el nombre viejo: los JSON ya guardados lo usan y
                # reconstruir_entry_desde_json sigue leyéndolo primero.
                "net_rows": net_html,
                "Manufacturer": fabricante_final,
                "Partnumber": partnumber_final,
                "Battery": data.get("battery", "No detectada"),
            }

        except subprocess.TimeoutExpired:
            last_error = (
                f"Timeout tras {timeout_per_attempt}s (intento {attempt}/{max_retries})"
            )
            print(f"⚠️  {last_error}")
        except json.JSONDecodeError as e:
            last_error = f"JSON inválido (intento {attempt}/{max_retries}): {e}"
            print(f"⚠️  {last_error}")
        except Exception as e:
            last_error = f"Error inesperado (intento {attempt}/{max_retries}): {e}"
            print(f"⚠️  {last_error}")
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        if attempt < max_retries:
            time.sleep(2)

    print(f"❌ Escaneo falló después de {max_retries} intentos. Último: {last_error}")
    return None


# ─────────────────────────────────────────────────────────
#  Nombre del equipo (ARR-<serial de BIOS>)
# ─────────────────────────────────────────────────────────
_SERIALES_BIOS_INVALIDOS = ("to be filled by o.e.m.", "default string")


def _startupinfo_oculto():
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    return si


def leer_serial_bios():
    """
    Número de serie de la BIOS, o "" si no hay uno válido (placas genéricas
    traen 'To be filled by O.E.M.'). Lanza si PowerShell no se puede correr.
    """
    cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        "(Get-CimInstance Win32_Bios).SerialNumber",
    ]
    serial = subprocess.check_output(
        cmd, text=True, startupinfo=_startupinfo_oculto()
    ).strip()
    if not serial or serial.lower() in _SERIALES_BIOS_INVALIDOS:
        return ""
    return serial


def nombre_equipo_para(serial):
    """'ARR-<serial>' saneado y truncado a 15 caracteres (límite NetBIOS)."""
    serial_limpio = re.sub(r"[^a-zA-Z0-9\-]", "", serial)
    return f"ARR-{serial_limpio}"[:15]


def cambiar_nombre_equipo(nuevo_nombre):
    """
    Pide el cambio de nombre con elevación de Administrador (UAC). Lanza
    subprocess.CalledProcessError si el usuario rechaza el permiso. El cambio
    recién aplica después de reiniciar.
    """
    ps_command = f'Rename-Computer -NewName "{nuevo_nombre}"'
    cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        f"Start-Process powershell -ArgumentList '-NoProfile -WindowStyle Hidden "
        f"-Command {ps_command}' -Verb RunAs",
    ]
    subprocess.run(cmd, check=True)
