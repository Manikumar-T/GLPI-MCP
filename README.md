# GLPI MCP Server

A Python [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server for [GLPI](https://glpi-project.org/) IT Service Management, using **SSE transport** so it can be hosted as a persistent HTTP service and connected to by any MCP client (Claude Desktop, Claude Code, etc.).

## Features

Full ITIL coverage across **80+ tools**:

| Category | Tools |
|---|---|
| **Tickets** | list, get, create, update, delete, add followup/task/solution, assign |
| **Problems** | list, get, create, update |
| **Changes** | list, get, create, update |
| **Computers** | list, get, create, update, delete |
| **Software** | list, get, create |
| **Network Equipment** | list, get |
| **Printers / Monitors / Phones** | list, get |
| **Knowledge Base** | list, get, search, create |
| **Contracts** | list, get, create |
| **Suppliers** | list, get, create |
| **Locations** | list, get, create |
| **Projects** | list, get, create, update |
| **Users** | list, get, search, create |
| **Groups** | list, get, create, add user |
| **Categories / Entities / Documents** | list, get |
| **Statistics** | ticket stats by status, asset inventory counts |
| **Session** | get full session info |
| **Search** | advanced search by criteria |

## Quick start

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `GLPI_URL` | Yes | Base URL of your GLPI instance, e.g. `https://glpi.example.com` |
| `GLPI_APP_TOKEN` | Recommended | Application token (configured in GLPI Setup → API) |
| `GLPI_USER_TOKEN` | One of these | Personal API token for the user |
| `GLPI_USERNAME` | One of these | Username (used with `GLPI_PASSWORD`) |
| `GLPI_PASSWORD` | One of these | Password |
| `HOST` | No | Bind host (default `0.0.0.0`) |
| `PORT` | No | Bind port (default `8000`) |

### Run with Docker (recommended)

```bash
docker run -d \
  -p 8000:8000 \
  -e GLPI_URL=https://glpi.example.com \
  -e GLPI_APP_TOKEN=your_app_token \
  -e GLPI_USER_TOKEN=your_user_token \
  manikumart/glpi-mcp:latest
```

### Run locally

```bash
pip install -r requirements.txt

export GLPI_URL=https://glpi.example.com
export GLPI_APP_TOKEN=your_app_token
export GLPI_USER_TOKEN=your_user_token

python server.py
```

The server starts at `http://localhost:8000/sse`.

### Docker Compose

```yaml
services:
  glpi-mcp:
    image: manikumart/glpi-mcp:latest
    ports:
      - "8000:8000"
    environment:
      GLPI_URL: https://glpi.example.com
      GLPI_APP_TOKEN: your_app_token
      GLPI_USER_TOKEN: your_user_token
    restart: unless-stopped
```

## Connect to Claude

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "glpi": {
      "url": "http://localhost:8000/sse"
    }
  }
}
```

### Claude Code (CLI)

```bash
claude mcp add glpi --transport sse http://localhost:8000/sse
```

## GLPI API setup

1. In GLPI, go to **Setup → General → API**
2. Enable the REST API
3. Create an **Application Token** for this server
4. Either use a **User Token** (from user preferences) or provide `GLPI_USERNAME` + `GLPI_PASSWORD`

## Build

```bash
docker build -t glpi-mcp .
```

## Docker image

Pre-built images are published to [Docker Hub](https://hub.docker.com/r/manikumart/glpi-mcp) on every push to `main` and on version tags:

```
manikumart/glpi-mcp:latest
manikumart/glpi-mcp:main
manikumart/glpi-mcp:v1.0.0
```

## License

MIT
