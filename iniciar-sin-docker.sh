#!/usr/bin/env sh
# knok sin Docker (Mac / Linux): Python + SQLite en un archivo.
set -e
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python || true)
[ -n "$PY" ] || { echo "Instala Python 3.11+: https://www.python.org/downloads/"; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || { echo "Necesitas Python 3.11 o más reciente"; exit 1; }
[ -x .venv/bin/python ] || "$PY" -m venv .venv
if ! cmp -s pyproject.toml .venv/pyproject.instalado; then
  .venv/bin/python -m pip install --disable-pip-version-check -q -e . && cp pyproject.toml .venv/pyproject.instalado
fi
[ -f .env ] || printf 'KNOK_SECRET_KEY=local-%s\n' "$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')" > .env
# Las versiones anteriores creaban .env "sin red" (solo datos de ejemplo): se quita esa línea
sed -i.bak '/^KNOK_OFFLINE_SOURCES=/d' .env && rm -f .env.bak
grep -q '^KNOK_DATABASE_URL=' .env || echo 'KNOK_DATABASE_URL=sqlite:///./knok.db' >> .env
grep -q '^KNOK_EMBEDDED_WORKER=' .env || echo 'KNOK_EMBEDDED_WORKER=true' >> .env
grep -q '^KNOK_LOCAL_SINGLE_USER=' .env || echo 'KNOK_LOCAL_SINGLE_USER=true' >> .env
.venv/bin/python -m alembic upgrade head
echo "knok en marcha: http://localhost:8000/  (Ctrl+C para pararlo)"
(sleep 4; open http://localhost:8000/ 2>/dev/null || xdg-open http://localhost:8000/ 2>/dev/null || true) &
exec .venv/bin/python -m uvicorn knok.api.main:app --host 127.0.0.1 --port 8000
