# Contributing

Thanks for helping. Bug reports, evaluation results on new datasets, and fixes are all welcome.

## Setting up

You need Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 24, PostgreSQL and Redis. Models
are optional for most work: the test suite and the Docker Compose stack in CI use a stand-in
([`e2e/ollama_stub.py`](e2e/ollama_stub.py)).

```bash
cd backend && uv sync && createdb docflow && uv run python manage.py migrate
cd frontend && npm ci
```

[Running locally](README.md#running-locally) covers the API, worker, review app and real models.

## Before opening a pull request

Run what CI runs:

```bash
cd backend && uv run ruff format --check . && uv run ruff check . && uv run mypy . && uv run pytest
cd frontend && npm run typecheck && npm run lint && npm test
```

- **One logical change per pull request**, with a test that fails without it.
- **Anything that changes what the models see or how fields are scored** (prompts, checks, rules)
  needs an evaluation run with it: `uv run python -m evaluation.run --dataset cord|sroie`, and the
  results committed next to the change. If only the checks changed, `--rescore` reuses the cached
  model output. See [ADR 7](docs/adr/0007-evaluation-before-prompts.md).
- **API changes** regenerate the spec and the frontend types: `uv run python manage.py
  spectacular --file ../docs/openapi.yaml --validate`, then `npm run api:types`.
- **Bigger design changes:** open an issue first, and add a decision record in
  [`docs/adr/`](docs/adr/README.md) if the change sets a direction others will build on.

## Style

The code is checked by ruff (Python) and oxlint (TypeScript); mypy runs in strict mode. Commit
messages say what changed and why, in the imperative ("Find whole amounts printed with cents").

## Reporting bugs

Use the bug report form. For a wrong extraction, include the receipt image if you can share it,
the pipeline version shown on the document, and what the right value is.

Security problems: please don't open an issue; see [SECURITY.md](SECURITY.md).

By contributing, you agree that your work is released under the [MIT License](LICENSE) and to follow
the [Code of Conduct](CODE_OF_CONDUCT.md).
