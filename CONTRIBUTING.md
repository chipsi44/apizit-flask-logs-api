# Contributing

This fixture helps inspect APIZIT's logs with predictable synthetic requests.
Preserve its bounds and correlation fields. Do not add unbounded load generation.
The Light/Heavy reference suite remains independent of this ten-route fixture.

Before publication, run:

```bash
ruff check .
ruff format --check .
pytest -q
python -c "from app import app; assert app is not None"
```

Also run the current APIZIT local scanner from a separate platform checkout.
Record the exact scanner commit, observed routes and technical recommendation
outside this source repository; do not commit generated reports or handlers.
Keep all waits mocked in unit tests. CI must never download models or call AWS.
Use a `codex/` branch, a Conventional Commit and a reviewed PR with passing CI.
