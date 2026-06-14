#!/bin/bash
# Runs once, the first time the Postgres volume is initialised.
# Creates a login role your Flask app uses that can ONLY read.
# TeslaMate creates its tables later as ${POSTGRES_USER}; the ALTER DEFAULT
# PRIVILEGES line makes those future tables readable by flask_ro automatically.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
	CREATE ROLE flask_ro LOGIN PASSWORD '${FLASK_DB_PASSWORD}';
	GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO flask_ro;
	GRANT USAGE ON SCHEMA public TO flask_ro;
	GRANT SELECT ON ALL TABLES IN SCHEMA public TO flask_ro;
	ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA public
	  GRANT SELECT ON TABLES TO flask_ro;
EOSQL
