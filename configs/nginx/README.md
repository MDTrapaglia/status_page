# Configuración Nginx para Status Page

Este proyecto está configurado para ejecutarse bajo el subdominio `/status` en `https://matiastrapaglia.space/status`.

## Puertos

- **Puerto 3010**: Aplicación Flask (frontend + API)
- **Puerto 3011**: Reservado para uso futuro

## Configuración

### Aplicación Flask

La aplicación Flask está configurada para correr en el puerto 3010:

```bash
python app.py
```

### Nginx

El archivo de configuración nginx está en `configs/nginx/matiastrapaglia_status.conf`.

Características:
- Proxy reverso desde `https://matiastrapaglia.space/status/` a `http://127.0.0.1:3010/`
- Redirección automática de HTTP a HTTPS
- Soporte para WebSocket (útil para futuras implementaciones)
- Headers de proxy configurados correctamente

### Deploy

Para desplegar la configuración de nginx:

```bash
./scripts/deploy_nginx.sh
```

Este script:
1. Copia la configuración a `/etc/nginx/sites-available/`
2. Crea un enlace simbólico en `/etc/nginx/sites-enabled/`
3. Valida la configuración de nginx
4. Recarga nginx para aplicar los cambios

### Verificación

Después del deploy, verifica que todo funcione:

```bash
curl -I https://matiastrapaglia.space/status/
```

## Rutas de la Aplicación

- `/` - Página principal
- `/api/prices` - API de precios y estadísticas
- `/api/port-block` - API de bloqueo de puertos
- `/port-block/<filename>` - Archivos estáticos de port-block

Con nginx, estas rutas se acceden como:
- `https://matiastrapaglia.space/status/`
- `https://matiastrapaglia.space/status/api/prices`
- `https://matiastrapaglia.space/status/api/port-block`
- `https://matiastrapaglia.space/status/port-block/<filename>`

## Certificados SSL

El proyecto usa los certificados de Let's Encrypt ubicados en:
- `/etc/letsencrypt/live/matiastrapaglia.space/fullchain.pem`
- `/etc/letsencrypt/live/matiastrapaglia.space/privkey.pem`

Estos certificados son compartidos con otros subdominios del mismo dominio.
