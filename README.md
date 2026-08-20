# pyutils

A Python **monorepo** of independent utilities. Each package under `packages/` has its own dependencies and can be developed, tested, and installed on its own. Shared tooling lives at the repo root.

Requires **Python 3.13+**. The workspace is managed with [uv](https://docs.astral.sh/uv/).

## Quick start

```bash
make setup    # install uv if needed, pin Python 3.13, create .venv, sync all packages
make list     # show packages
make test     # pytest across the workspace
make lint     # ruff check
make clean    # remove .venv, caches, build artifacts
```

`make env` is an alias for `make setup`.

## Add a new utility

```bash
make new NAME=my-util DESC="does one thing"
make add PKG=my-util DEP=httpx          # optional runtime dep
make test PKG=my-util
make run PKG=my-util
```

That scaffolds:

```
packages/my-util/
  pyproject.toml
  README.md
  src/my_util/
    __init__.py
    __main__.py
  tests/
    test_smoke.py
```

The directory name is the distribution name (`my-util`); the import name uses underscores (`my_util`).

## Daily Makefile targets

| Target | What it does |
|---|---|
| `make setup` / `make env` | Install uv, Python 3.13, create `.venv`, `uv sync --all-packages` |
| `make python` | Print the workspace interpreter |
| `make list` | List packages |
| `make new NAME=foo` | Scaffold `packages/foo` |
| `make add PKG=foo DEP=x` | Add a dependency to one package |
| `make test` / `make test PKG=foo` | Pytest (all, or one package) |
| `make lint` / `make lint PKG=foo` | Ruff check |
| `make format` | Ruff format + autofix |
| `make check` | `lint` then `test` |
| `make run PKG=foo` | `python -m <import>` (`ARGS="..."` optional) |
| `make clean` | Remove `.venv`, caches, build artifacts |
| `make clean-venv` | Remove only `.venv` |
| `make clean-caches` | Remove `__pycache__`, ruff/pytest/mypy/build artifacts |

## Layout

```
.
├── Makefile
├── pyproject.toml          # uv workspace + shared ruff/pytest
├── .python-version         # 3.13
├── packages/
│   └── <util>/             # one independent utility each
├── scripts/new_package.py
└── templates/package/      # scaffold used by `make new`
```

Packages do not import each other unless you add an explicit workspace dependency. Keep it that way: a utility should be usable on its own.

## Packages

- [`workflow-engine`](packages/workflow-engine) — existing LangChain workflow engine, moved in from the repo root.
