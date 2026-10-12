#!/bin/sh
set -eu
docker compose exec api python -m app.seed --reset-demo-data
