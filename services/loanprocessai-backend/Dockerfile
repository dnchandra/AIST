# syntax=docker/dockerfile:1
# =============================================================================
# LoanProcessAI - backend only (FastAPI + Google ADK agents)
#
# Build with the BACKEND directory as the context:
#     cd backend
#     docker build -t loanprocessai-api:azure-v1 .
#
# This image exposes the API only. Use it when the React UI is hosted
# separately (frontend/Dockerfile). For a single-container deployment that
# serves the UI and the API together, build the repository-root Dockerfile
# instead:   docker build -t loanprocessai:azure-v1 .
#
# Runtime port: 8080 (Container Apps ingress target port, PORT overridable).
# =============================================================================
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PORT=8080

WORKDIR /app

# Dependency layer first so source edits do not reinstall the world.
# The requirements resolve to binary wheels for CPython 3.13, so no compiler
# toolchain (gcc/build-essential) is installed in the image.
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# Application source (app.py, agent.py, tools.py, local_tools.py,
# observability.py, prompts/, sub_agents/, financial_anomaly_tool/).
# backend/.dockerignore keeps .venv, data/ and *.log out of the image.
COPY . ./

# STORAGE_MODE=local writes SQLite + uploaded documents here. Point
# LOCAL_DATA_DIR at a mounted Azure Files share in Container Apps to persist
# data across revisions.
RUN mkdir -p /app/data/documents

EXPOSE 8080

# Shell form so ${PORT} is expanded; `exec` keeps SIGTERM handling with uvicorn
# so Container Apps can shut the replica down cleanly.
CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]

