PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
PYTEST ?= $(PYTHON) -m pytest
EDITABLE := \
	-e packages/protocol \
	-e packages/core \
	-e packages/storage \
	-e packages/provider-sdk \
	-e packages/runtime \
	-e packages/media \
	-e packages/index \
	-e packages/mcp \
	-e packages/skills \
	-e packages/provider-google \
	-e packages/provider-openai \
	-e packages/provider-wavespeed \
	-e packages/provider-fal \
	-e packages/provider-elevenlabs \
	-e packages/provider-cloudflare \
	-e packages/provider-higgsfield \
	-e packages/provider-magnific \
	-e packages/harness \
	-e apps/daemon

.PHONY: install test conformance lint proprietary-scan secret-scan skills-validate demo clone-smoke github studio require-python selfhost-dry-run free-gate

free-gate:
	chmod +x scripts/run-free-gate.sh && ./scripts/run-free-gate.sh

selfhost-dry-run:
	DRY_RUN=1 FIXTURE_MODE=1 ROOT=deploy/cloudflare ./deploy/cloudflare/scripts/deploy.sh

require-python:
	@if ! $(PYTHON) -c 'import sys; raise SystemExit(0 if sys.version_info>=(3,12) else 1)'; then \
		ver=$$($(PYTHON) -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])'); \
		printf '%s\n' \
			"Python $$ver detected. Python 3.12+ is required because make install installs the OpenAI provider (vinci-provider-openai)." \
			"pyenv install --list | grep -E ' 3\\.12\\.'" \
			"If that list is empty, run brew update && brew upgrade pyenv and list again." \
			"Install one version from that list:" \
			"pyenv install <that version>" \
			"pyenv shell <that version>" \
			"python3 --version" \
			"make install"; \
		exit 1; \
	fi

install: require-python
	$(PIP) install -U pip
	$(PIP) install pytest ruff mypy jsonschema types-jsonschema pyyaml types-PyYAML httpx fastapi uvicorn python-multipart
	$(PIP) install $(EDITABLE)
	npm install
	npm run typecheck --workspaces --if-present
	npm run build --workspace @tryvinci/cli --if-present

test:
	$(PYTEST) -q packages tests

conformance:
	$(PYTEST) -q packages/provider-sdk/tests/conformance

lint:
	ruff check packages tests apps/daemon scripts/*.py
	mypy --config-file pyproject.toml \
		packages/protocol/vinci_protocol \
		packages/core/vinci_core \
		packages/storage/vinci_storage \
		packages/provider-sdk/vinci_provider_sdk \
		packages/skills/vinci_skills \
		packages/runtime/vinci_runtime \
		packages/mcp/vinci_mcp \
		packages/media/vinci_media \
		packages/index/vinci_index \
		packages/provider-elevenlabs/vinci_provider_elevenlabs \
		packages/provider-cloudflare/vinci_provider_cloudflare \
		packages/provider-wavespeed/vinci_provider_wavespeed \
		packages/provider-google/vinci_provider_google \
		packages/provider-fal/vinci_provider_fal \
		packages/provider-higgsfield/vinci_provider_higgsfield \
		packages/provider-magnific/vinci_provider_magnific \
		packages/harness/vinci_harness
	npm run typecheck
	$(MAKE) proprietary-scan
	$(MAKE) secret-scan
	$(MAKE) skills-validate

DAEMON_URL ?= http://127.0.0.1:4310

demo:
	$(PYTHON) -m vinci_harness demo
	VINCI_DAEMON_URL=$(DAEMON_URL) VINCI_DAEMON_PORT=4310 ./scripts/vinci init --demo
	VINCI_DAEMON_URL=$(DAEMON_URL) VINCI_DAEMON_PORT=4310 ./scripts/vinci run @tryvinci/image-generate --input '{"prompt":"a red cube"}'

studio:
	VINCI_DAEMON_URL=$(DAEMON_URL) VINCI_DAEMON_PORT=4310 ./scripts/vinci studio

clone-smoke:
	./scripts/clone-smoke.sh

github:
	./scripts/create-github-repo.sh

skills-validate:
	$(PYTHON) scripts/validate_skills.py

proprietary-scan:
	$(PYTHON) scripts/check_no_proprietary.py

secret-scan:
	$(PYTHON) scripts/check_no_secrets.py
