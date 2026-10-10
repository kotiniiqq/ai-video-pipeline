#!/bin/sh
# First start only (docker-entrypoint-initdb.d): a database for n8n itself and one for the pipeline.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<SQL
CREATE USER n8n WITH PASSWORD '$N8N_DB_PASSWORD';
CREATE DATABASE n8n OWNER n8n;
CREATE USER pipeline WITH PASSWORD '$PIPELINE_DB_PASSWORD';
CREATE DATABASE pipeline OWNER pipeline;
SQL
for f in /migrations/*.sql; do
  echo "applying $f"
  psql -v ON_ERROR_STOP=1 --username pipeline --dbname pipeline -f "$f"
done
