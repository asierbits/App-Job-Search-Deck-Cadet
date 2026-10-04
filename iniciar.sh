#!/usr/bin/env sh
# knok: arranca el motor con Docker y abre el banco de pruebas (Mac / Linux).
set -e
cd "$(dirname "$0")"
command -v docker >/dev/null || { echo "Instala Docker Desktop: https://www.docker.com/products/docker-desktop/"; exit 1; }
docker info >/dev/null 2>&1 || { echo "Abre Docker Desktop y vuelve a ejecutar este script."; exit 1; }
if [ ! -f .env ]; then
  printf 'KNOK_SECRET_KEY=local-%s\n' "$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')" > .env
  echo "Creado .env"
fi
# Las versiones anteriores creaban .env "sin red" (solo datos de ejemplo): se quita esa línea
sed -i.bak '/^KNOK_OFFLINE_SOURCES=/d' .env && rm -f .env.bak
grep -q '^KNOK_LOCAL_SINGLE_USER=' .env || echo 'KNOK_LOCAL_SINGLE_USER=true' >> .env
echo "Arrancando knok (la primera vez tarda unos minutos)..."
docker compose up -d --build
i=0
until curl -fs http://localhost:8000/health >/dev/null 2>&1; do
  i=$((i+1)); [ "$i" -gt 60 ] && { echo "La API no responde: docker compose logs api"; exit 1; }
  sleep 2
done
echo "Listo: http://localhost:8000/  (para pararlo: docker compose down)"
(open http://localhost:8000/ 2>/dev/null || xdg-open http://localhost:8000/ 2>/dev/null) || true
