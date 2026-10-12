# Explicit, ownership-scoped reset; refuses active demo jobs. No volume deletion.
docker compose exec api python -m app.seed --reset-demo-data
if ($LASTEXITCODE -ne 0) { throw 'Demo reset failed; resolve active jobs first.' }
