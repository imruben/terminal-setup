# Changelog

Lo que trae cada versión. El número sigue [SemVer](https://semver.org/lang/es/):

- **1.x.0**: algo nuevo.
- **1.0.x**: arreglos.
- **2.0.0**: algo que cambia cómo se usa o se instala (hay que leer la nota antes de actualizar).

Qué versión tienes: `terminal version`, `make doctor` o la primera línea de `./install.sh`. Verás
uno de estos formatos:

- `v1.0.0`: exactamente esa versión.
- `v1.0.0-3-gabc1234`: 3 commits después de ella.
- `-dirty` al final: hay cambios sin commit.

Para publicar una versión, mira [Publicar una versión](#publicar-una-versión) al final.

## [Sin publicar]

## [1.0.0] — sin publicar

La primera versión etiquetada: todo lo que había hasta ahora.

### Instalación
- `./install.sh` (o `make install`) en **Ubuntu 24.04 / 26.04**, **WSL** y **macOS**.
  - Instala lo que falta, en las versiones que hacen falta. Lo que no está en apt se descarga y se comprueba con sha256 antes de usarlo.
  - Una vez instalado, cada nueva ejecución también actualiza.
- **Tus ficheros siguen siendo tuyos.** `~/.zshrc`, `~/.tmux.conf` y `~/.zshenv` reciben un bloque entre marcas al final, con copia de seguridad. `./uninstall.sh` quita exactamente ese bloque.
- Funciona aunque el repo esté en una carpeta con espacios (a través de un enlace en `~/.local/share/terminal-setup`).
- Utilidades:
  - `make doctor`: comprueba que todo esté en su sitio.
  - `terminal files`: qué ha puesto la instalación y para qué sirve cada cosa.
  - `--dry-run`, `--config-only` y `--no-update`: variantes del instalador.

### zsh
- Prompt de starship, autocompletado con fzf-tab, autosuggestions y syntax highlighting.
- Funciones: `update`, `clean`, `extract`, `rgf`, `fe`, `serve`, `ports`, `killport`, `dps`, `dsh`, `fkill`…
- Arranca en unos 50 ms: las salidas de las herramientas quedan en caché y los autocompletados pesados se cargan solo cuando se usan.

### tmux
- **Ratón y teclado para todo.** Menús, una guía con búsqueda (`Ctrl+a ?`) y un menú rápido (`Ctrl+a Space`).
- **Sesiones:**
  - Selector de sesiones con vista previa y descripciones.
  - El comando `terminal` gestiona las sesiones.
  - Puedes elegir qué sesión abren las terminales nuevas.
- **Las sesiones se guardan cada 5 minutos** y se restauran al arrancar.
- Plugins fijados a versiones probadas (`install/plugins.lock`).

### Monitor del sistema (sesión `system`)
- **Siete pestañas:**
  - **info**: fastfetch, btop y recursos.
  - **monitor**: procesos y puertos.
  - **disk**: carpetas, discos y limpieza.
  - **packages**: apt, snap y brew, con buscador y actualizaciones.
  - **ssh**: hosts, claves y túneles.
  - **docker**: contenedores, detalles y logs en vivo con búsqueda.
  - **git**: tus repos, con estado, diff, log, ramas y stash.
- Paneles interactivos:
  - pasar el ratón resalta;
  - clic derecho abre el menú;
  - escribir filtra;
  - todo lo que borra o para algo pregunta antes.
- Ligero:
  - fuera de la vista no hace nada;
  - los paneles de detalle siguen al principal sin sondear;
  - Docker se lee con streaming (`docker stats`) y eventos (`docker events`).
- Se repara solo: si cierras un panel o una pestaña, vuelve.

### Para desarrollar el repo
- `make check` (sintaxis y shellcheck).
- `make test`: tests unitarios del monitor y de las funciones del instalador.
- `make smoke`: cada panel en un tmux privado.
- `make test-install`: la instalación en contenedores Ubuntu.
- `make bench`: la CPU del monitor.
- CI en GitHub Actions en cada push, con las acciones fijadas por commit. Dependabot propone las versiones nuevas.

[Sin publicar]: https://github.com/kibanly/terminal-setup/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/kibanly/terminal-setup/releases/tag/v1.0.0

---

## Publicar una versión

1. **Pasa lo apuntado a la nueva versión.** Mueve lo que haya bajo **[Sin publicar]** a una sección `## [X.Y.Z] — AAAA-MM-DD`. Si es la primera, basta con poner la fecha a la de 1.0.0.
2. **Crea la etiqueta:** `make release VERSION=X.Y.Z`. Comprueba que no hay cambios sin commit, que la sección existe y que los tests pasan; después crea la etiqueta `vX.Y.Z`.
3. **Súbela:** `git push origin main vX.Y.Z`. El workflow `release` crea la release en GitHub con el texto de esa sección.

En las demás máquinas, `git pull` y `./install.sh`. La primera línea del instalador dice qué versión quedó.
