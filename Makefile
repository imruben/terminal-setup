# ═══════════════════════════════════════════════════════════════
#  terminal-setup · every way to run the installer, as make targets
#    make              this list
#    make install      install what is missing (and `update` when installed already)
#    YES=1             no questions, e.g.  make install YES=1
#  The scripts do the work: make only calls them (./install.sh --help has the details).
# ═══════════════════════════════════════════════════════════════

SHELL := /bin/bash
YES_FLAG := $(if $(filter 1 yes true,$(YES)),--yes,)

.DEFAULT_GOAL := help
.PHONY: help install update install-no-update config dry-run uninstall doctor files monitor check test smoke test-install bench release version

help: ## this list
	@printf '\n  \033[1mterminal-setup\033[0m · make <target>   \033[2m(YES=1: no questions)\033[0m\n\n'
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | \
	  awk -F':.*## ' '{ printf "    \033[36m%-18s\033[0m %s\n", $$1, $$2 }'
	@printf '\n'

install: ## install what is missing · when installed already, also update (packages, plugins)
	./install.sh $(YES_FLAG)

update: install ## the same as install: once installed, it updates

install-no-update: ## installed already: only what is missing, no update
	./install.sh --no-update $(YES_FLAG)

config: ## only the config files (no packages, font, plugins, update)
	./install.sh --config-only $(YES_FLAG)

dry-run: ## show what install would do, changing nothing
	./install.sh --dry-run --yes

uninstall: ## take the terminal-setup lines out of ~/.zshrc, ~/.tmux.conf and ~/.zshenv
	./uninstall.sh $(YES_FLAG)

doctor: ## check the installation (versions, config, plugins, font)
	bash install/doctor.sh

files: ## every file the install put on this machine, and what it is for
	@bash install/files.sh

monitor: ## rebuild the system monitor (tmux session `system`)
	tmux/system.sh restart

SH := install.sh uninstall.sh install/*.sh tmux/system.sh tmux/system/*.sh tests/*/*.sh

check: ## syntax of every script (bash, zsh, python) and shellcheck · for changes to the repo
	@for f in $(SH); do bash -n "$$f" || exit 1; done
	@for f in zsh/zshrc zsh/*.zsh zsh/platform/*.zsh tmux/*.zsh; do zsh -n "$$f" || exit 1; done
	@python3 -c 'import ast, sys; [ast.parse(open(f).read(), f) for f in sys.argv[1:]]' tmux/*.py tests/unit/*.py
	@if command -v shellcheck >/dev/null; then shellcheck -S warning -x $(SH) || exit 1; \
	  else echo "– shellcheck is not installed: bash scripts only parsed"; fi
	@git diff --check
	@echo "✔ every script parses"

test: ## unit tests: the monitor's code (drawing, keys, logs, parsers) and the installer's functions · seconds, changes nothing
	@PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/unit -t tests/unit $(if $(V),-v,)
	@bash tests/shell/lib.sh

smoke: ## every monitor pane run in a private tmux, given keys, checked for errors (~1 min)
	@tests/smoke/panes.sh

test-install: ## the whole install in fresh Ubuntu containers (Docker; TAGS="24.04 26.04" · ~15 min)
	@tests/install/run.sh $(TAGS)

bench: ## CPU of every monitor pane, tab by tab, in a private tmux (SECS=30 per tab)
	@tests/bench/cpu.sh $(or $(SECS),30)

version: ## which version this is (v1.0.0 · v1.0.0-3-gabc1234: 3 commits after it · -dirty: changes not committed)
	@git describe --tags --match 'v[0-9]*' --always --dirty 2>/dev/null || echo unknown

release: ## tag a version: make release VERSION=1.2.0 (CHANGELOG.md needs its section · then git push origin main v1.2.0)
	@[[ "$(VERSION)" =~ ^[0-9]+\.[0-9]+\.[0-9]+$$ ]] || { echo "✘ make release VERSION=X.Y.Z (e.g. 1.0.0)"; exit 1; }
	@[ -z "$$(git status --porcelain)" ] || { echo "✘ there are changes not committed: commit them first"; exit 1; }
	@! git rev-parse -q --verify "refs/tags/v$(VERSION)" >/dev/null || { echo "✘ v$(VERSION) exists already"; exit 1; }
	@grep -Eq '^## \[$(subst .,\.,$(VERSION))\] — [0-9]{4}-[0-9]{2}-[0-9]{2}$$' CHANGELOG.md || \
	  { echo "✘ CHANGELOG.md needs a section \"## [$(VERSION)] — YYYY-MM-DD\" (with the date: \"sin publicar\" is not one)"; exit 1; }
	@$(MAKE) --no-print-directory check test
	@git tag -a "v$(VERSION)" -m "terminal-setup $(VERSION)"
	@echo "✔ tagged v$(VERSION) · publish it: git push origin $$(git branch --show-current) v$(VERSION)"
