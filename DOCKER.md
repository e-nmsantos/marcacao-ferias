# 🐳 Docker Deployment Guide

Deploy **Marcação de Férias** using Docker containers for easy scalability and isolation.

---

## Quick Start: Docker Compose

The easiest way to get started with full PostgreSQL support.

### Prerequisites
- Docker and Docker Compose installed
- Port `8501` available (Streamlit)
- Port `5432` available (PostgreSQL, optional)

### 1. Build and run the app

```bash
docker-compose up -d
```

This starts:
- **App service**: Streamlit on `http://localhost:8501`
- **PostgreSQL service**: (optional) For persistent data, accessible at `localhost:5432`

### 2. First login

Access the app at `http://localhost:8501` and login with:
- Username: `admin`
- Password: `admin123`

### 3. Configure PostgreSQL (optional)

To enable persistent PostgreSQL storage:

1. Find the `POSTGRES_PASSWORD` in `docker-compose.yml` (default: `ferias_secure_pass`)
2. Once the postgres service is running, set the `DATABASE_URL` environment variable:

```bash
# For local development
export DATABASE_URL=postgresql://ferias_user:ferias_secure_pass@postgres:5432/marcacao_ferias

# Or in docker-compose.yml, add to app service environment:
DATABASE_URL: postgresql://ferias_user:ferias_secure_pass@postgres:5432/marcacao_ferias
```

### 4. Stop the services

```bash
docker-compose down
```

To also remove data volumes:

```bash
docker-compose down -v
```

---

## Building the Docker Image

### Build locally

```bash
docker build -t marcacao-ferias:v0.2.0 .
```

### Run the image

```bash
docker run -p 8501:8501 \
  -v $(pwd)/data_store.json:/app/data_store.json \
  -v $(pwd)/audit_logs:/app/audit_logs \
  marcacao-ferias:v0.2.0
```

### Run with PostgreSQL

```bash
docker run -p 8501:8501 \
  -e DATABASE_URL=postgresql://user:pass@host:5432/db \
  -v $(pwd)/audit_logs:/app/audit_logs \
  marcacao-ferias:v0.2.0
```

---

## Environment Variables

Configure the app behavior via environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | (empty) | PostgreSQL connection string; if empty, uses SQLite (`ferias.db`) |
| `STREAMLIT_SERVER_PORT` | `8501` | Port for Streamlit web server |
| `STREAMLIT_SERVER_ADDRESS` | `0.0.0.0` | Bind address (0.0.0.0 for all interfaces) |
| `STREAMLIT_SERVER_HEADLESS` | `true` | Run without browser (required for containers) |
| `STREAMLIT_LOGGER_LEVEL` | `info` | Log level (debug, info, warning, error) |

### Example with environment override

```bash
docker run -p 8501:8501 \
  -e DATABASE_URL=postgresql://user:pass@host:5432/db \
  -e STREAMLIT_LOGGER_LEVEL=debug \
  marcacao-ferias:v0.2.0
```

---

## Data Persistence

### SQLite (default)

Data stored in local `ferias.db` file within the container. To persist:

```bash
docker run -p 8501:8501 \
  -v $(pwd)/ferias.db:/app/ferias.db \
  marcacao-ferias:v0.2.0
```

### PostgreSQL (recommended for production)

Use the provided `docker-compose.yml` with PostgreSQL service, or:

1. Spin up a PostgreSQL container separately:

```bash
docker run -d --name ferias-postgres \
  -e POSTGRES_DB=marcacao_ferias \
  -e POSTGRES_USER=ferias_user \
  -e POSTGRES_PASSWORD=secure_password \
  -v postgres_data:/var/lib/postgresql/data \
  -p 5432:5432 \
  postgres:15-alpine
```

2. Run the app container with `DATABASE_URL` pointing to it:

```bash
docker run -p 8501:8501 \
  -e DATABASE_URL=postgresql://ferias_user:secure_password@ferias-postgres:5432/marcacao_ferias \
  --link ferias-postgres \
  marcacao-ferias:v0.2.0
```

---

## Audit Logs

Audit logs are stored in `/app/audit_logs/audit.jsonl` inside the container.

To persist audit logs locally:

```bash
docker run -p 8501:8501 \
  -v $(pwd)/audit_logs:/app/audit_logs \
  marcacao-ferias:v0.2.0
```

Inspect audit logs:

```bash
cat audit_logs/audit.jsonl | jq .
```

---

## Production Deployment

### Health Check

The Docker image includes a health check endpoint. To verify the container is running:

```bash
curl http://localhost:8501/_stcore/health
```

### Using Docker Compose in Production

1. Create a `.env` file with production values:

```env
POSTGRES_PASSWORD=your_secure_password_here
DATABASE_URL=postgresql://ferias_user:your_secure_password_here@postgres:5432/marcacao_ferias
STREAMLIT_LOGGER_LEVEL=warning
```

2. Run with production settings:

```bash
docker-compose -f docker-compose.yml up -d
```

3. Monitor logs:

```bash
docker-compose logs -f app
```

### Reverse Proxy (Nginx)

To expose the app safely behind a reverse proxy:

```nginx
server {
    listen 80;
    server_name ferias.example.com;

    location / {
        proxy_pass http://localhost:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## Troubleshooting

### Container exits immediately

Check logs:

```bash
docker logs <container_id>
```

### Port 8501 already in use

Either stop the conflicting container or use a different port:

```bash
docker run -p 8502:8501 marcacao-ferias:v0.2.0
```

### Database connection errors

Verify the `DATABASE_URL` format:

```
postgresql://username:password@host:5432/database_name
```

Ensure the PostgreSQL service is accessible from the app container.

### Slow startup

The first run initializes the database. Subsequent startups are faster. Check with `docker logs`.

---

## Testing

The project includes end-to-end tests. To run them inside a container:

```bash
docker run --rm \
  -v $(pwd):/app \
  python:3.11 \
  bash -c "pip install -e /app && pytest /app/tests/test_e2e.py -v"
```

---

## Next Steps

- **Monitor**: Use `docker-compose logs` and the health check endpoint
- **Scale**: Deploy multiple replicas behind a load balancer
- **Backup**: Regularly export PostgreSQL backups or data via the admin interface
- **Update**: Build a new image, test in staging, then deploy to production

---

**For more info, see the main [README.md](README.md) and [pyproject.toml](pyproject.toml).**
