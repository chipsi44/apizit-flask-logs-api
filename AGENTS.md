# Logs reference API guidelines

- Keep this standalone Flask fixture compatible with Python 3.12 and its ten documented routes.
- Preserve immediate /health and the inherited 80-second /slow response; mock waits in unit tests.
- Keep bursts bounded to 1,000 events, synthetic padding to 512 characters, bodies to 8 KiB,
  and timeline cumulative waits to 5 seconds. Validate before emitting bulk events or waiting.
- Keep per-request correlation, all five logging levels, JSON/text formats and flushed stdout.
- Never log request bodies, authorization/API-key headers, raw query values or credentials.
  Accept only bounded ASCII markers and synthetic generated messages.
- Do not add AWS infrastructure, Dockerfiles, Lambda handlers, generated files, background jobs,
  external services, prices or APIZIT-internal imports.
- Pin direct dependencies at the root. Update README and meaningful tests with contract changes.
- Run Ruff check/format, pytest, an application import and a current APIZIT local scan before
  publication. Use a codex/ branch, Conventional Commit, review and passing CI.
- Publication is a GitHub source artifact. Hosted qualification uses only explicitly scoped TEST
  fixtures pinned to exact commits; publishing this repository does not open PROD.
