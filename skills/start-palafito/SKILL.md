---
name: start-palafito
description: "Arranca Docker Desktop si no está corriendo y despliega el stack de Paperclip palafito-prod."
model: sonnet
context: fork
allowed-tools: Bash
---

# Start Palafito

Levanta el servicio Paperclip de Palafito en Docker.

## Workflow

### 1. Verificar si Docker Desktop está corriendo

```bash
docker info > /dev/null 2>&1
```

- Si devuelve **código 0** → Docker daemon activo → saltar al paso 3
- Si falla → el daemon no está listo → paso 2

### 2. Arrancar Docker Desktop

```bash
# Arrancar Docker Desktop en Windows
powershell.exe -Command "Start-Process 'C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe'"
```

Esperar a que el daemon responda (poll con `docker info`):

```bash
for i in $(seq 1 30); do
  docker info > /dev/null 2>&1 && break
  echo "Esperando Docker daemon... ($i/30)"
  sleep 5
done

docker info > /dev/null 2>&1 || { echo "ERROR: Docker Desktop no arrancó en 150s"; exit 1; }
```

### 3. Levantar el compose de palafito-prod

```bash
cd /c/palafito-prod && docker compose up -d
```

Si el init container (`palafito-paperclip-init`) ya está en estado `exited` con código 0 de una ejecución anterior, Docker Compose lo reconoce como completado y no lo relanza — esto es correcto.

### 4. Verificar salud

Esperar hasta que el healthcheck pase (máx 120s):

```bash
for i in $(seq 1 24); do
  STATUS=$(docker inspect --format='{{.State.Health.Status}}' palafito-paperclip 2>/dev/null)
  echo "Health: $STATUS ($i/24)"
  [ "$STATUS" = "healthy" ] && break
  sleep 5
done

STATUS=$(docker inspect --format='{{.State.Health.Status}}' palafito-paperclip 2>/dev/null)
if [ "$STATUS" = "healthy" ]; then
  echo ""
  echo "✓ Paperclip Palafito corriendo en http://localhost:3101"
else
  echo ""
  echo "⚠ El contenedor no alcanzó estado healthy en 120s. Estado actual: $STATUS"
  echo "Logs recientes:"
  docker logs --tail 20 palafito-paperclip
fi
```

### 5. Reportar estado final

Mostrar:
- URL: `http://localhost:3101`
- Estado del contenedor (`docker ps --filter name=palafito-paperclip`)
- Si es la primera vez (volumen vacío), recordar que hay que crear la cuenta admin en la UI

## Notas

- El directorio del compose es siempre `C:\palafito-prod\` (`/c/palafito-prod/` en bash)
- Los datos persisten en el volumen Docker `palafito-paperclip-data` — no se pierden al reiniciar
- La cuenta de admin solo se crea una vez; después de eso el login funciona con las credenciales guardadas
- Para parar: `docker compose -f /c/palafito-prod/docker-compose.yml down`
