# Local tests run in Docker (per project convention). `make test` is the
# canonical way to run the suite; `make test-local` is an escape hatch if you
# already have the deps in your own environment.

IMAGE := posture:latest
# Fixed name for the running server container, so `make stop` can find it.
CONTAINER := posture
# Host port to publish the app on. Override if 8000 is taken, e.g. `make serve PORT=8001`.
PORT ?= 8000
# Database URL for the served app. SQLite file by default; override for Postgres,
# e.g. `make serve DB_URL=postgresql+psycopg://user:pass@host/posture`.
DB_URL ?= sqlite:////app/posture.db
# LAN address used for the HTTPS cert (auto-detected; override e.g. `make serve-https HOST=192.168.1.5`).
HOST ?= $(shell hostname -I 2>/dev/null | awk '{print $$1}')
CERT_DIR := certs

.PHONY: build test test-local serve serve-local serve-https stop certs migrate seed catalog clean

build:
	docker build -t $(IMAGE) .

# Run the full test suite inside a container.
test: build
	docker run --rm -v "$(CURDIR)":/app $(IMAGE) pytest

# Apply database migrations (Alembic) inside a container.
migrate: build
	docker run --rm -e POSTURE_DATABASE_URL=$(DB_URL) -v "$(CURDIR)":/app $(IMAGE) alembic upgrade head

# Seed one user per role + sample data, and import the exercise catalog (idempotent).
seed: build
	docker run --rm -e POSTURE_DATABASE_URL=$(DB_URL) -v "$(CURDIR)":/app $(IMAGE) python -m app.seed

# Import only the local MuscleWiki exercise catalog into the database.
catalog: build
	docker run --rm -e POSTURE_DATABASE_URL=$(DB_URL) -v "$(CURDIR)":/app $(IMAGE) python -m app.catalog_import

# Serve at http://localhost:$(PORT), backed by the database. Migrations run on
# startup (build_default_store); we seed first so there's data to log in with.
# Runs as container "$(CONTAINER)"; use `make stop` to shut it down.
serve: build
	docker run --rm --name $(CONTAINER) -p $(PORT):8000 -e POSTURE_DATABASE_URL=$(DB_URL) -v "$(CURDIR)":/app $(IMAGE) \
		sh -c "python -m app.seed && uvicorn app.server:app --host 0.0.0.0 --port 8000"

# Run tests without Docker (requires deps installed locally).
test-local:
	pytest

serve-local:
	POSTURE_DATABASE_URL=sqlite:///posture.db python -m app.seed && \
		POSTURE_DATABASE_URL=sqlite:///posture.db uvicorn app.server:app --reload --port $(PORT)

# Generate a self-signed TLS cert valid for this machine's LAN IP (and localhost).
certs:
	@mkdir -p $(CERT_DIR)
	@test -f $(CERT_DIR)/server.crt || ( \
		echo "Generating self-signed cert for IP:$(HOST) ..." && \
		openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
			-keyout $(CERT_DIR)/server.key -out $(CERT_DIR)/server.crt \
			-subj "/CN=posture-dev" \
			-addext "subjectAltName=IP:$(HOST),DNS:localhost,IP:127.0.0.1" )

# Serve over HTTPS on the LAN so the camera works on phones/tablets.
# Browsers only allow getUserMedia in a secure context, which a LAN IP needs TLS for.
serve-https: build certs
	@echo ">>> Open  https://$(HOST):$(PORT)  on your tablet (accept the self-signed warning once)."
	docker run --rm --name $(CONTAINER) -p $(PORT):8000 -e POSTURE_DATABASE_URL=$(DB_URL) -v "$(CURDIR)":/app $(IMAGE) \
		sh -c "python -m app.seed && uvicorn app.server:app --host 0.0.0.0 --port 8000 \
		       --ssl-keyfile certs/server.key --ssl-certfile certs/server.crt"

# Stop (and remove) the running server container.
stop:
	@docker rm -f $(CONTAINER) 2>/dev/null && echo "stopped $(CONTAINER)" || echo "$(CONTAINER) is not running"

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache
	rm -f posture.db
