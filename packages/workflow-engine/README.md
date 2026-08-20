# workflow-engine

LangChain-based AI workflow engine with SQLite/JSON persistence and a Streamlit dashboard.

```bash
make test PKG=workflow-engine
make add PKG=workflow-engine DEP=<library>
```

Configure providers via environment variables (`LLM_PROVIDER`, `EMBEDDING_PROVIDER`, `STORAGE_TYPE`, and the matching API keys). Set `TEST_MODE=true` to skip live LLM calls.
