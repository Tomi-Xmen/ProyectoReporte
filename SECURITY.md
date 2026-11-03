# Seguridad

## Reportar una vulnerabilidad

Si encontrás un problema de seguridad, **no abras un issue público**.
Reportalo en privado desde la pestaña **Security → Report a vulnerability**
de este repositorio. Respondemos lo antes posible y, una vez resuelto, se
publica el aviso con el crédito correspondiente.

## Qué nunca va al repositorio

El programa trabaja con datos sensibles que viven **solo en cada
instalación**, junto al programa, y están en el `.gitignore`:

| Archivo | Qué tiene |
|---|---|
| `servidor.json` | Datos del servidor SSH (ver `servidor.ejemplo.json`) |
| `id_clonado` | Clave privada SSH con que se envían los reportes |
| `licencias_office.db`, planillas `.xls`/`.xlsx` | Keys de Office |
| `Reportes_Guardados/` | Reportes de entregas y retiros: datos de clientes |
| `lector_celular.json` | Código de emparejamiento del lector celular |

Los tokens de la API de FOG van en `%PROGRAMDATA%\Reporte3\fog_api.json` (o
`~/.reporte3/fog_api.json`), nunca junto al programa: el programa se copia a
cada equipo clonado.

## Lector celular

El servidor HTTP del lector solo acepta conexiones de la red local, exige el
token del QR en cada pedido y viene apagado. El reporte en vivo escucha solo
en `127.0.0.1`.
