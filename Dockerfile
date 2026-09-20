FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATROLX_ENV=production \
    PATROLX_LOG_JSON=1

WORKDIR /app

COPY requirements-lock.txt pyproject.toml ./
COPY app ./app
COPY deploy ./deploy
COPY scripts ./scripts

RUN pip install --no-cache-dir setuptools \
    && pip install --no-cache-dir -r requirements-lock.txt \
    && pip install --no-cache-dir --no-deps .

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
