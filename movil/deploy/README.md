# Instalar Reporte Móvil en el servidor (192.168.10.15)

Todo como un usuario con `sudo`, en el servidor.

## 1. Python

```bash
python3 --version                 # si no está: sudo apt install python3
sudo apt install python3-venv
```

## 2. Copiar la app

Desde el PC donde está el repo:

```bash
scp -r movil/ <usuario>@192.168.10.15:/tmp/reporte-movil
```

En el servidor:

```bash
sudo mkdir -p /opt/reporte-movil
sudo cp -r /tmp/reporte-movil/* /tmp/reporte-movil/.env.example /opt/reporte-movil/
sudo python3 -m venv /opt/reporte-movil/venv
sudo /opt/reporte-movil/venv/bin/pip install -r /opt/reporte-movil/requirements.txt
```

## 3. Configurar

```bash
sudo cp /opt/reporte-movil/.env.example /opt/reporte-movil/.env
sudo nano /opt/reporte-movil/.env           # MOVIL_CLAVE y MOVIL_SECRET_KEY
sudo chown -R Reporte: /opt/reporte-movil
sudo chmod 600 /opt/reporte-movil/.env
```

## 4. Servicio

```bash
sudo cp /opt/reporte-movil/deploy/reporte-movil.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now reporte-movil
systemctl status reporte-movil
```

Si hay firewall (`ufw`): `sudo ufw allow 5070/tcp`.

## 5. Probar

Desde el celular, con la app de Tailscale conectada: `http://<IP-tailscale>:5070`
(la IP sale con `tailscale ip -4` en el servidor). El wifi de la oficina no
llega a `192.168.10.x`: el router no tiene ruta a esa red.

## 6. HTTPS (para escanear con la cámara)

El navegador solo deja usar la cámara por HTTPS. Tailscale lo da gratis:

1. En https://login.tailscale.com/admin/dns: activar **MagicDNS** y
   **HTTPS Certificates**.
2. En el servidor:
   ```bash
   sudo tailscale serve --bg 5070
   sudo tailscale serve status      # muestra la URL https://<servidor>.<tailnet>.ts.net
   ```
3. En el celular (Chrome, con Tailscale conectado) entrar por esa URL
   `https://…ts.net`. La primera vez pide permiso de cámara.

`tailscale serve --bg` queda guardado y sobrevive reinicios. Para sacarlo:
`sudo tailscale serve reset`.

## Actualizar

Desde el PC, en la carpeta del repo:

```bash
movil/deploy/subir.sh -n    # ver qué cambiaría
movil/deploy/subir.sh       # subir y reiniciar
```

Sincroniza con `rsync --delete` pero respeta `.env` y `venv/` del servidor.
Nunca borrar `/opt/reporte-movil` a mano: sin `.env` ni `venv` el servicio no
arranca (`Result: resources`).
Logs: `journalctl -u reporte-movil -f`.
