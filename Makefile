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
.PHONY: help install update install-no-update config dry-run uninstall doctor files monitor check

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

check: ## syntax of every script (bash, zsh, python) and shellcheck · for changes to the repo
	@for f in install.sh uninstall.sh install/*.sh tmux/system.sh tmux/system/*.sh; do bash -n "$$f" || exit 1; done
	@for f in zsh/zshrc zsh/*.zsh zsh/platform/*.zsh tmux/*.zsh; do zsh -n "$$f" || exit 1; done
	@python3 -c 'import ast, sys; [ast.parse(open(f).read(), f) for f in sys.argv[1:]]' tmux/*.py
	@if command -v shellcheck >/dev/null; then shellcheck -S warning -x install.sh uninstall.sh install/*.sh tmux/system.sh tmux/system/*.sh || exit 1; \
	  else echo "– shellcheck is not installed: bash scripts only parsed"; fi
	@git diff --check
	@echo "✔ every script parses"
