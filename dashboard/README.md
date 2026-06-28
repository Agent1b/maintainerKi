# maintainerKi dashboard

This is the React + Vite frontend for maintainerKi.

## Development

```bash
npm ci
npm run dev -- --host 127.0.0.1 --port 3000
```

The development server expects the FastAPI backend at:

- `http://127.0.0.1:8000`

Vite proxies `/api` requests there automatically.

## Production build

```bash
npm run build
```

The packaged production stack serves the built dashboard through nginx using:

- `dashboard/Dockerfile`
- `docker/nginx/dashboard.conf`
