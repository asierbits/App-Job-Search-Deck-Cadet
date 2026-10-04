FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY knok ./knok
RUN pip install --no-cache-dir .
COPY alembic.ini ./
EXPOSE 8000
# Aplica las migraciones y arranca la API. El worker usa la misma imagen con otro comando.
CMD ["sh", "-c", "alembic upgrade head && uvicorn knok.api.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
