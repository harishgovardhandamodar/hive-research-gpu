# Security

## Authentication

Hive Research supports optional Bearer token authentication for API endpoints.

### Enabling

Set the `HIVE_AUTH_TOKEN` environment variable before starting the server:

```bash
export HIVE_AUTH_TOKEN="your-secret-token"
python -m hive_research serve
```

All API endpoints will now require authentication. Unauthenticated requests receive a `401 Unauthorized` response.

### Using with the Python Client

```python
client = HiveClient("http://localhost:7777", auth_token="your-secret-token")
```

### Using with curl

```bash
curl -H "Authorization: Bearer your-secret-token" http://localhost:7777/api/stats
```

### Using with the Chrome Extension

1. Click the extension icon → **⚙ Settings**
2. Enter your auth token in the **Auth Token** field
3. Click **Test Connection** to verify
4. Click **Save**

## Input Validation

The server validates incoming data for key endpoints:

- **arXiv IDs** — Must match format `1234.56789` or `1234.56789v1`
- **URLs** — Must be valid HTTP(S) URLs
- **Required fields** — Missing required fields return `400 Bad Request`

Validation is handled by Pydantic models in `hive_research/schemas.py`. If Pydantic is not installed, validation falls back gracefully (no validation, but no crash).

## Network Security

- The server binds to `127.0.0.1` by default (localhost only)
- To expose to a network, use `--host 0.0.0.0` and configure a firewall
- For production use, place behind a reverse proxy (nginx, Caddy) with HTTPS
