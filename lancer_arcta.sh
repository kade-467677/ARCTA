#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

PORT=8737
URL="http://127.0.0.1:${PORT}"

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3.12 ou plus recent est requis (commande 'python3' introuvable)."
    exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
    echo "Premiere utilisation : creation de l'environnement et installation des dependances..."
    python3 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -r requirements.txt
fi

echo "Demarrage d'ARCTA sur ${URL} ..."
( sleep 2; if command -v xdg-open >/dev/null 2>&1; then xdg-open "${URL}"; elif command -v open >/dev/null 2>&1; then open "${URL}"; fi ) &
.venv/bin/python -m uvicorn apps.arcta_web.main:app --host 127.0.0.1 --port "${PORT}"
