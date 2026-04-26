---
name: start
description: >
  Starts the full MCP stack: LiteLLM proxy + Docker services (Hindsight, Atlassian, Google Workspace)
  + skills-manager + notebooklm. All services connect directly — no proxy.
  Use /start at the beginning of any session where MCP tools are needed, or when any service is stopped.
  LiteLLM must start before Docker — Hindsight depends on it at startup.
argument-hint: ""
model: haiku
allowed-tools: Bash
---

# Start — MCP Stack Launcher

Ensures the full MCP stack is running:
- **LiteLLM proxy** at `http://localhost:4000` (HOST) — Claude Haiku gateway for Hindsight
- **Docker stack** (Hindsight :8888, atlassian-marlink :9000, atlassian-geeplo :9001, google-workspace-arturo :9003, google-workspace-palafito :9004)
- **skills-manager server** at `http://localhost:9002` (Python on HOST)
- **notebooklm server** at `http://localhost:9005` (Python on HOST)

**Start order matters**: LiteLLM → Docker (Hindsight calls LiteLLM on `verify_connection` at startup).

## Steps

### Step 1 — Check if stack is already running

```bash
HINDSIGHT=$(curl -s --max-time 1 -o /dev/null -w "%{http_code}" http://localhost:8888/health 2>/dev/null)
SKILLS_MGR=$(curl -s --max-time 1 -o /dev/null -w "%{http_code}" http://localhost:9002 2>/dev/null)
LITELLM=$(curl -s --max-time 1 -o /dev/null -w "%{http_code}" http://localhost:4000/health 2>/dev/null)
```

- Hindsight != 000 AND skills_mgr != 000 AND litellm != 000 → stack is active. Print status (Step 9 format) and stop.

### Step 2 — Resolve paths and load secrets

This must run before LiteLLM and before Docker — both need secrets and paths.

```bash
# Resolve ONEDRIVE_PATH
if [ -z "$ONEDRIVE_PATH" ]; then
  DEVICE_JSON="$USERPROFILE/.claude/eligia/local_device.json"
  if [ -f "$DEVICE_JSON" ]; then
    export ONEDRIVE_PATH=$(python -c "import json; print(json.load(open('$DEVICE_JSON'))['onedrive_path'])")
  else
    [ -n "$ONEDRIVE" ] && export ONEDRIVE_PATH="$ONEDRIVE"
    if [ -z "$ONEDRIVE_PATH" ]; then
      for _od in "$USERPROFILE/OneDrive" "$USERPROFILE/OneDrive - UNITAS" "$USERPROFILE/OneDrive - Personal"; do
        [ -d "$_od/.eligia" ] && export ONEDRIVE_PATH="$_od" && break
      done
    fi
    [ -z "$ONEDRIVE_PATH" ] && echo "ERROR: ONEDRIVE_PATH no encontrada. Ejecuta install-eligia.bat primero." && exit 1
    echo "WARNING: ONEDRIVE_PATH resuelto por fallback: $ONEDRIVE_PATH (ejecuta install-eligia.bat para persistir)"
  fi
fi

# Resolve ELIGIA_DIR
if [ -z "$ELIGIA_DIR" ]; then
  DEVICE_JSON="$USERPROFILE/.claude/eligia/local_device.json"
  if [ -f "$DEVICE_JSON" ]; then
    export ELIGIA_DIR=$(python -c "import json; print(json.load(open('$DEVICE_JSON'))['eligia_dir'])")
  else
    export ELIGIA_DIR="${ONEDRIVE_PATH}/.eligia"
    echo "WARNING: ELIGIA_DIR resuelto por fallback: $ELIGIA_DIR"
  fi
fi

SECRETS="${ONEDRIVE_PATH}/.eligia/secrets.env"
AGE_KEY="$USERPROFILE/.config/sops/age/keys.txt"

if [ ! -f "$SECRETS" ]; then
  echo "ERROR: $SECRETS no encontrado. Verifica que OneDrive esté sincronizado."
  exit 1
fi

set -a
source <(SOPS_AGE_KEY_FILE="$AGE_KEY" sops --input-type dotenv --output-type dotenv --decrypt "$SECRETS" | grep -v '^#')
set +a
```

### Step 3 — Start LiteLLM proxy (if not running)

```bash
curl -s --max-time 1 http://localhost:4000/health > /dev/null 2>&1
```

- Returns any HTTP code → already running, skip.
- Fails / empty → start it:

```bash
LITELLM=$(which litellm 2>/dev/null || echo "$USERPROFILE/AppData/Roaming/Python/Python313/Scripts/litellm")
PYTHONIOENCODING=utf-8 nohup "$LITELLM" --config "${ONEDRIVE_PATH}/.eligia/stack/litellm_config.yaml" --port 4000 > /tmp/litellm.log 2>&1 &
sleep 6
```

Verify: `curl -s --max-time 3 -o /dev/null -w "%{http_code}" http://localhost:4000/health`
- Any response → running.
- No response → print `ERROR: LiteLLM no arrancó. Revisa: /tmp/litellm.log` and stop.

### Step 4 — Check if Docker daemon is running

```bash
docker info 2>&1
```

- Success → Docker is running. Skip to Step 6.
- Failure → Docker Desktop is closed. Continue to Step 5.

### Step 5 — Start Docker Desktop

```bash
cmd /c start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
```

Poll until Docker daemon responds (max 60s, check every 5s):

```bash
for i in $(seq 1 12); do
  docker info 2>&1 | grep -q "Server Version" && break
  sleep 5
done
```

If timeout reached without success, print:
```
ERROR: Docker Desktop no respondió en 60s.
Abre Docker Desktop manualmente y vuelve a ejecutar /start.
```
Then stop.

### Step 6 — Deploy Docker stack

```bash
COMPOSE="${ONEDRIVE_PATH}/.eligia/stack/docker-compose.yml"
docker compose -f "$COMPOSE" up -d --remove-orphans
```

Wait 5 seconds, verify Hindsight is up:

```bash
curl -s --max-time 3 -o /dev/null -w "%{http_code}" http://localhost:8888/health
```

- Any response → running.
- No response → print `ERROR: Hindsight no arrancó. Revisa: docker logs hindsight` and stop.

### Step 7 — Start skills-manager MCP server (if not running)

```bash
curl -s --max-time 1 http://localhost:9002 > /dev/null 2>&1
```

- Returns any HTTP code → already running, skip.
- Fails / empty → start it:

```bash
python -c "import websockets" 2>/dev/null || pip install "websockets" -q
nohup python "$USERPROFILE/.skills-manager/server.py" > /dev/null 2>&1 &
sleep 3
```

Verify: `curl -s --max-time 2 -o /dev/null -w "%{http_code}" http://localhost:9002`
- Any response → running.
- No response → print `ERROR: skills-manager server no arrancó. Ejecuta manualmente: python ~/.skills-manager/server.py`

### Step 8 — Start paperclip-mcp server (if not running)

```bash
curl -s --max-time 1 http://localhost:9011/mcp > /dev/null 2>&1
```

- Returns any HTTP code → already running, skip.
- Fails / empty → start it:

```bash
python -c "import paperclip_mcp" 2>/dev/null || pip install -e "$USERPROFILE/.paperclip/mcp-server" -q

PAPERCLIP_API_KEY="$PAPERCLIP_API_KEY" \
PAPERCLIP_COMPANY_ID="$PAPERCLIP_COMPANY_ID" \
PAPERCLIP_BASE_URL="${PAPERCLIP_BASE_URL:-http://localhost:3100/api}" \
nohup paperclip-mcp > /tmp/paperclip-mcp.log 2>&1 &
sleep 3
```

Verify: `curl -s --max-time 2 -o /dev/null -w "%{http_code}" http://localhost:9011/mcp`
- Any response → running.
- No response → print `ERROR: paperclip-mcp no arrancó. Revisa: /tmp/paperclip-mcp.log`

### Step 9 — Start notebooklm MCP server (if not running)


```bash
curl -s --max-time 1 http://localhost:9005 > /dev/null 2>&1
```

- Returns any HTTP code → already running, skip.
- Fails / empty → ensure deps and start:

```bash
python -c "import notebooklm" 2>/dev/null || pip install "notebooklm-py[browser]" fastmcp -q

export NOTEBOOKLM_HOME="${ELIGIA_DIR}/data/notebooklm-py"
export NOTEBOOKLM_DEFAULT_NOTEBOOK="4752df21-5550-4d55-924a-540ec2a82c3f"
nohup python "$USERPROFILE/.claude/notebooklm-server/server.py" > /tmp/notebooklm.log 2>&1 &
sleep 3
```

Verify: `curl -s --max-time 5 -o /dev/null -w "%{http_code}" http://localhost:9005/mcp/`
- Any response → running.
- No response → print `ERROR: notebooklm server no arrancó. Revisa: /tmp/notebooklm.log`

#### Setup inicial (nueva máquina — una vez)

Auth se almacena como cookies en `$ELIGIA_DIR/data/notebooklm-py/` (local, gitignored).

```bash
export NOTEBOOKLM_HOME="${ELIGIA_DIR}/data/notebooklm-py"
notebooklm auth   # Abre browser → login con Google → cierra → cookies guardadas
```

### Step 10 — Print status

```
Stack activo:
  Atlassian Marlink :9000  (http direct)
  Atlassian Geeplo  :9001  (http direct)
  skills-manager    :9002  (http direct)
  Google Arturo    :9003  (http direct)
  Google Palafito  :9004  (http direct)
  notebooklm       :9005  (http direct)
  Hindsight        :8888  (http direct)
  LiteLLM proxy    :4000  [claude-haiku]
  context7         https://mcp.context7.com/mcp  (remote)
  miro             https://mcp.miro.com/          (remote)
  trello           stdio (npx -y trello-mcp)      [needs TRELLO_API_KEY/TRELLO_TOKEN]
  camoufox         stdio (npx -y camoufox-mcp-server)
  rag              :9010  (SSE, host Python)
  paperclip-mcp    :9011  (http direct)
```

$ARGUMENTS
