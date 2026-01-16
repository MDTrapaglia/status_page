# Cómo Agregar una Nueva Página al Dominio matiastrapaglia.space

Esta guía explica cómo crear una aplicación Flask desde cero y servirla bajo un subdominio (por ejemplo, `/example`) en el dominio `matiastrapaglia.space` con autenticación por token.

## Tabla de Contenidos

1. [Requisitos Previos](#requisitos-previos)
2. [Estructura del Proyecto](#estructura-del-proyecto)
3. [Crear la Aplicación Flask](#crear-la-aplicación-flask)
4. [Configurar Nginx](#configurar-nginx)
5. [Scripts de Gestión](#scripts-de-gestión)
6. [Poner en Producción](#poner-en-producción)
7. [Verificación](#verificación)

---

## Requisitos Previos

- Python 3.x instalado
- Nginx instalado y configurado
- Acceso sudo para configuración de nginx
- Dominio `matiastrapaglia.space` configurado con SSL
- Token de autenticación: `gaelito2025`

---

## Estructura del Proyecto

Crea una nueva carpeta para tu aplicación:

```bash
mkdir -p ~/projects/mi_nueva_app
cd ~/projects/mi_nueva_app
```

Estructura recomendada:

```
mi_nueva_app/
├── app.py                 # Aplicación Flask principal
├── templates/             # Templates HTML
│   └── index.html
├── static/               # Archivos estáticos (CSS, JS, imágenes)
│   ├── css/
│   ├── js/
│   └── img/
├── requirements.txt      # Dependencias Python
├── venv/                # Entorno virtual Python
├── run.sh               # Script para iniciar la aplicación
└── .backend.pid         # PID del proceso (generado automáticamente)
```

---

## Crear la Aplicación Flask

### 1. Crear entorno virtual e instalar Flask

```bash
python -m venv venv
source venv/bin/activate
pip install flask
pip freeze > requirements.txt
```

### 2. Crear `app.py`

```python
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
AUTH_TOKEN = "gaelito2025"

@app.before_request
def require_token():
    """Middleware para validar el token en todas las rutas"""
    # Permitir archivos estáticos sin autenticación
    if request.endpoint == "static":
        return None

    # Validar token
    token = request.args.get("token")
    if token == AUTH_TOKEN:
        return None

    return "Resource not available", 404

@app.route("/")
def index():
    """Ruta principal"""
    return render_template("index.html")

@app.route("/api/data")
def api_data():
    """Endpoint de API de ejemplo"""
    return jsonify({
        "message": "Hello from my new app!",
        "status": "ok"
    })

if __name__ == "__main__":
    # IMPORTANTE: Usar un puerto único para tu aplicación
    # Status page usa 3010, IoT usa 3000/3001, Game usa 3005/3006
    # Elige un puerto libre, por ejemplo 3020
    app.run(host="127.0.0.1", port=3020, debug=False)
```

### 3. Crear `templates/index.html`

```html
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mi Nueva App</title>
    <style>
        body {
            font-family: system-ui, -apple-system, sans-serif;
            max-width: 800px;
            margin: 50px auto;
            padding: 20px;
            background: #0f172a;
            color: #e2e8f0;
        }
        h1 {
            color: #ffb703;
        }
        .container {
            background: #1e293b;
            padding: 30px;
            border-radius: 10px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Mi Nueva Aplicación</h1>
        <p>Esta es una nueva aplicación Flask servida bajo /example</p>
        <div id="data"></div>
    </div>

    <script>
        // IMPORTANTE: Usar rutas RELATIVAS para que funcionen bajo /example/
        const authToken = new URLSearchParams(window.location.search).get("token");
        const query = authToken ? `?token=${encodeURIComponent(authToken)}` : "";

        // Cargar datos de la API
        fetch(`api/data${query}`)
            .then(response => response.json())
            .then(data => {
                document.getElementById('data').innerHTML =
                    `<p><strong>API Response:</strong> ${data.message}</p>`;
            })
            .catch(err => {
                document.getElementById('data').innerHTML =
                    `<p style="color: #fb7185;">Error: ${err.message}</p>`;
            });
    </script>
</body>
</html>
```

### 4. Crear `run.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="$SCRIPT_DIR/venv"
SELF_PID="$$"
SELF_PPID="${PPID:-}"

kill_running() {
  local pids=""
  # Flask dev server
  pids+=" $(pgrep -f "venv/bin/flask run" || true)"
  pids+=" $(pgrep -f "python .*flask run" || true)"
  # Shell scripts
  pids+=" $(pgrep -f "bash ./run.sh" || true)"

  # Procesos usando el puerto 3020 (o el puerto que hayas elegido)
  if command -v fuser >/dev/null 2>&1; then
    pids+=" $(fuser 3020/tcp 2>/dev/null || true)"
  fi

  # Eliminar duplicados y PIDs propios
  pids=$(echo "$pids" | tr ' ' '\n' | grep -E '^[0-9]+$' | sort -u || true)
  pids=$(echo "$pids" | grep -Ev "^(${SELF_PID}|${SELF_PPID})$" || true)

  if [[ -n "$pids" ]]; then
    echo "Deteniendo procesos previos: $pids" >&2
    kill $pids 2>/dev/null || true
    sleep 1
    kill -9 $pids 2>/dev/null || true
  fi
}

if [[ ! -d "$VENV_PATH" ]]; then
  echo "No se encontró el entorno virtual en $VENV_PATH" >&2
  exit 1
fi

kill_running

source "$VENV_PATH/bin/activate"

echo "Compilando app.py..."
python -m py_compile "$SCRIPT_DIR/app.py"

export FLASK_APP=app
echo "Iniciando servidor Flask en puerto 3020..."
flask run --reload --no-debugger --host 127.0.0.1 --port 3020
```

Dar permisos de ejecución:

```bash
chmod +x run.sh
```

---

## Configurar Nginx

### 1. Editar configuración existente

El archivo de configuración principal está en:
```bash
/etc/nginx/sites-available/matiastrapaglia_iot.conf
```

Editar el archivo:

```bash
sudo nano /etc/nginx/sites-available/matiastrapaglia_iot.conf
```

### 2. Agregar location para `/example/`

Dentro del bloque `server`, agregar (antes del último `location /api/`):

```nginx
  # Mi Nueva Aplicación
  location /example/ {
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_pass http://127.0.0.1:3020/;
  }

  # Redirect /example to /example/
  location = /example {
    return 301 /example/;
  }
```

**Notas importantes:**
- Cambiar `3020` por el puerto que elegiste
- El `/` al final de `proxy_pass http://127.0.0.1:3020/;` es **crucial** para que funcione el rewrite de rutas
- Cada aplicación debe usar un puerto único

### 3. Verificar y recargar nginx

```bash
# Verificar sintaxis
sudo nginx -t

# Si todo está bien, recargar nginx
sudo systemctl reload nginx
```

---

## Scripts de Gestión

### Script para iniciar en background

Crear `start.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -f .backend.pid ]]; then
  OLD_PID=$(cat .backend.pid)
  if ps -p "$OLD_PID" > /dev/null 2>&1; then
    echo "Backend ya está corriendo con PID: $OLD_PID"
    exit 0
  fi
fi

nohup ./run.sh > app.log 2>&1 &
echo $! > .backend.pid
echo "Backend iniciado con PID: $(cat .backend.pid)"
```

```bash
chmod +x start.sh
```

### Script para detener

Crear `stop.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ ! -f .backend.pid ]]; then
  echo "No se encontró archivo .backend.pid"
  exit 1
fi

PID=$(cat .backend.pid)
if ps -p "$PID" > /dev/null 2>&1; then
  echo "Deteniendo proceso $PID..."
  kill "$PID"
  sleep 2
  if ps -p "$PID" > /dev/null 2>&1; then
    echo "Forzando detención..."
    kill -9 "$PID"
  fi
  echo "Proceso detenido"
else
  echo "Proceso $PID no está corriendo"
fi

rm -f .backend.pid
```

```bash
chmod +x stop.sh
```

---

## Poner en Producción

### 1. Iniciar la aplicación

```bash
cd ~/projects/mi_nueva_app
./start.sh
```

### 2. Verificar que está corriendo

```bash
# Verificar que el proceso está activo
ps -p $(cat .backend.pid)

# Verificar que el puerto está escuchando
ss -tlnp | grep :3020
```

### 3. Probar localmente

```bash
curl -I "http://127.0.0.1:3020/?token=gaelito2025"
```

Deberías ver `HTTP/1.1 200 OK`.

### 4. Probar a través de nginx

```bash
curl -I "https://matiastrapaglia.space/example/?token=gaelito2025" -k
```

---

## Verificación

### Acceder desde el navegador

Abre tu navegador y ve a:

```
https://matiastrapaglia.space/example/?token=gaelito2025
```

Deberías ver tu aplicación funcionando correctamente.

### Verificar logs

```bash
# Ver logs de la aplicación
tail -f ~/projects/mi_nueva_app/app.log

# Ver logs de nginx
sudo tail -f /var/log/nginx/error.log
sudo tail -f /var/log/nginx/access.log
```

---

## Solución de Problemas Comunes

### Error 502 Bad Gateway

**Causa:** El backend no está corriendo o el puerto es incorrecto.

**Solución:**
```bash
# Verificar si el backend está corriendo
ps aux | grep flask

# Verificar el puerto
ss -tlnp | grep :3020

# Reiniciar el backend
./stop.sh
./start.sh
```

### Error 404 Not Found

**Causa:** No se está pasando el token correcto.

**Solución:** Asegúrate de incluir `?token=gaelito2025` en la URL.

### JavaScript da error "Unexpected token '<'"

**Causa:** Las rutas de API están usando rutas absolutas en lugar de relativas.

**Solución:** En tu JavaScript, usa rutas relativas:
```javascript
// ✅ Correcto
fetch(`api/data${query}`)

// ❌ Incorrecto
fetch(`/api/data${query}`)
```

### Conflicto de puertos

**Causa:** El puerto ya está en uso por otra aplicación.

**Solución:**
1. Verificar qué está usando el puerto:
```bash
sudo ss -tlnp | grep :3020
```

2. Elegir un puerto diferente y actualizar:
   - `app.py` (línea con `app.run(port=...)`)
   - `run.sh` (línea con `fuser 3020/tcp`)
   - Configuración de nginx (`proxy_pass http://127.0.0.1:3020/`)

---

## Puertos Utilizados en el Sistema

Para evitar conflictos, aquí están los puertos ya asignados:

- **3000**: IoT Frontend (Next.js)
- **3001**: IoT Backend API
- **3005**: Game Frontend
- **3006**: Game Backend API
- **3010**: Status Page

**Puertos disponibles sugeridos para nuevas apps:**
- 3015, 3020, 3025, 3030, etc.

---

## Checklist de Deployment

- [ ] Crear entorno virtual y instalar dependencias
- [ ] Crear `app.py` con autenticación por token
- [ ] Elegir un puerto único para la aplicación
- [ ] Crear templates con rutas relativas en JavaScript
- [ ] Crear scripts `run.sh`, `start.sh`, `stop.sh`
- [ ] Agregar location en nginx (`/example/`)
- [ ] Verificar configuración de nginx (`sudo nginx -t`)
- [ ] Recargar nginx (`sudo systemctl reload nginx`)
- [ ] Iniciar aplicación (`./start.sh`)
- [ ] Probar localmente (`curl http://127.0.0.1:PUERTO/?token=gaelito2025`)
- [ ] Probar via nginx (`curl https://matiastrapaglia.space/example/?token=gaelito2025`)
- [ ] Acceder desde navegador

---

## Ejemplo Completo de Configuración Nginx

Para referencia, así se vería la configuración completa de nginx con múltiples aplicaciones:

```nginx
map $http_upgrade $connection_upgrade {
  default upgrade;
  ''      close;
}

server {
  listen 80;
  listen 443 ssl;
  http2 on;
  server_name matiastrapaglia.space;

  ssl_certificate /etc/letsencrypt/live/matiastrapaglia.space/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/matiastrapaglia.space/privkey.pem;

  if ($scheme = http) {
    return 301 https://$host$request_uri;
  }

  # Game Application
  location /game/ {
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_pass http://127.0.0.1:3005;
  }

  location = /game {
    return 301 /game/;
  }

  # IoT Application
  location /iot/ {
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_pass http://127.0.0.1:3000;
  }

  location = /iot {
    return 301 /iot/;
  }

  # Status Page Application
  location /status/ {
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_pass http://127.0.0.1:3010/;
  }

  location = /status {
    return 301 /status/;
  }

  # Nueva Aplicación - Example
  location /example/ {
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_pass http://127.0.0.1:3020/;
  }

  location = /example {
    return 301 /example/;
  }

  # Fallback API routes
  location /api/ {
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_pass http://127.0.0.1:3001;
  }
}
```

---

## Recursos Adicionales

- [Documentación de Flask](https://flask.palletsprojects.com/)
- [Documentación de Nginx](https://nginx.org/en/docs/)
- [Guía de Nginx Reverse Proxy](https://docs.nginx.com/nginx/admin-guide/web-server/reverse-proxy/)

---

## Notas Finales

1. **Seguridad**: El token `gaelito2025` se valida en el backend, no confíes solo en el frontend
2. **Logging**: Considera implementar logging robusto para debugging
3. **Monitoreo**: Considera agregar tu nueva app al status page para monitoreo
4. **Backups**: Asegúrate de hacer backup de tu código y configuraciones
5. **Documentación**: Documenta las APIs y funcionalidades específicas de tu app

¡Buena suerte con tu nueva aplicación! 🚀
