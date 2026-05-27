# Contributing to Faultline

Thank you for your interest in Faultline — an ML training continuity and recovery platform.

## Development setup

```bash
docker compose -f docker-compose.cloud.yml up --build
# API :8080  Web :3000

pip install -e sdk
pip install fastapi uvicorn pydantic python-multipart bcrypt PyJWT sqlalchemy psycopg boto3
```

## Running tests

```bash
python -m unittest discover cloud/tests
set PYTHONPATH=sdk
python -m unittest discover sdk/tests
cd web && npm run build
```

## Pull requests

- Keep changes focused; avoid unrelated refactors
- Match existing code style and naming
- Add tests for behavior changes
- Update docs when changing user-facing flows

## Scope

We welcome improvements to recovery UX, SDK ergonomics, integrations, and docs. Out of scope for now: billing, multi-tenant orgs, Kubernetes operators.
