# apiome-mock

FastAPI mock runtime for published Apiome OpenAPI specs.

Public URL shape:

```
https://mock.<host>/{tenant}/{project}/{version}/<spec-path>
```

## Development

```bash
cd apiome-mock
cp .env.example .env   # set APIOME_MOCK_DATABASE_URL
uv sync
uv run apiome-mock serve
```

## Tests

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy -p apiome_mock
uv run pytest
```
