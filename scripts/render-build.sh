#!/usr/bin/env bash
# Render build: install both halves, build the SPA, collect static, migrate.
set -o errexit
set -o pipefail
set -o nounset

echo "──> Python dependencies"
pip install --upgrade pip
pip install -r api/requirements.txt

echo "──> Building the SPA"
cd web
npm ci
npm run build
cd ..

echo "──> Collecting static files"
cd api
python manage.py collectstatic --no-input

# Safe to run on every deploy: migrations are idempotent, and running them
# here rather than at request time means a cold start never races a schema
# change. The build fails loudly if a migration fails, before any traffic is
# routed to the new instance.
echo "──> Applying migrations"
python manage.py migrate --no-input

echo "──> Build complete"
