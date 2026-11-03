# terminal-setup

Mi terminal, lista en minutos en cualquier máquina: **zsh** con prompt, autocompletado y atajos, y **tmux** con todo integrado: barra con pestañas y botones, menús con el ratón, una guía de atajos con buscador y un **monitor del sistema** (procesos, puertos, disco, paquetes, servidores SSH, contenedores Docker y sus logs, y tus repos git).

Funciona en **Ubuntu 26.04**, **Ubuntu 24.04**, **WSL** (Ubuntu dentro de Windows) y **macOS**.

---

## Índice

1. [Qué incluye](#qué-incluye)
2. [Instalación](#instalación)
   - [Ubuntu 26.04 / 24.04](#ubuntu-2604--2404)
   - [WSL (Windows)](#wsl-windows)
   - [macOS](#macos)
3. [Qué hace el instalador](#qué-hace-el-instalador)
4. [Primeros pasos](#primeros-pasos)
5. [Cambiar cosas](#cambiar-cosas)
6. [Actualizar](#actualizar)
7. [Desinstalar](#desinstalar)
8. [Estructura del repo](#estructura-del-repo)
9. [Problemas frecuentes](#problemas-frecuentes)

---

## Qué incluye

**zsh**
- Prompt [starship](https://starship.rs) en dos líneas: usuario, carpeta, rama y estado de git, duración del último comando, hora.
- Sugerencias mientras escribes (`zsh-autosuggestions`) y colores de sintaxis (`zsh-syntax-highlighting`).
- Autocompletado con vista previa ([fzf-tab](https://github.com/Aloxaf/fzf-tab)), `Ctrl+R` para buscar en el historial, `Ctrl+T` para buscar ficheros.
- `ls` con iconos y colores ([eza](https://github.com/eza-community/eza)), `bat` en lugar de `cat`, `micro` como editor.
- Buscar y moverse: [ripgrep](https://github.com/BurntSushi/ripgrep) (`rg`, texto dentro de ficheros), [fd](https://github.com/sharkdp/fd) (ficheros por nombre; también lo usa `Ctrl+T`), [zoxide](https://github.com/ajeetdsouza/zoxide) (`z carpeta` salta a las que más usas, `zi` para elegir).
- [lazygit](https://github.com/jesseduffield/lazygit) para trabajar con git en la terminal (`Ctrl+a G` lo abre en una ventana flotante en la carpeta del panel, y también desde la pestaña git), [yq](https://github.com/mikefarah/yq) (jq para YAML), [shellcheck](https://www.shellcheck.net) (errores en scripts de shell; micro lo usa solo al guardar un `.sh`) y [tldr](https://github.com/tealdeer-rs/tealdeer) (`tldr tar`: ejemplos cortos de cualquier comando).
- Funciones propias:

  | Comando | Qué hace |
  |---|---|
  | `update` | actualiza todo: apt, snap, Homebrew, uv, pnpm, Composer, el último Node LTS (fnm), las páginas de tldr, los plugins de zsh y de tmux (estos, con tmux abierto) |
  | `clean` | limpia cachés y restos de apt, snap, Homebrew, journal, Docker, uv, pnpm, npm y Composer |
  | `rgf <texto>` | busca dentro de los ficheros (rg), eliges el resultado con vista previa y lo abre en el editor en esa línea |
  | `fe [patrón]` | eliges ficheros por nombre (fd + fzf, `Tab` marca varios) y los abre en el editor |
  | `mkcd <dir>` / `extract <fichero>` | crear una carpeta y entrar / descomprimir cualquier formato |
  | `serve [puerto]` | servidor web de la carpeta: PHP si hay `index.php` (o `public/index.php`), Python si no |
  | `lg` · `pn` · `uvr` | lazygit · pnpm · uv run |
  | `installed-packages` | los paquetes que instalaste **tú** (apt, snap, brew) y por qué (notas) |
  | `ports` / `killport <puerto>` | qué escucha en cada puerto / liberarlo (pregunta antes) |
  | `dps` / `dsh` | contenedores Docker de un vistazo / entrar en uno |
  | `fkill` | buscar procesos con fzf y pararlos |
  | `terminal` | gestor de sesiones de tmux (`terminal help`) |

**tmux** (prefijo `Ctrl+a`)
- Barra arriba con las pestañas como botones, CPU y RAM, botones de **menú** y **guía**, y la hora. Se adapta al ancho de la ventana.
- Todo se puede hacer **con el ratón o con el teclado**, y las dos cosas a la vez: clic en pestañas, clic derecho en paneles, pestañas y sesiones para abrir su menú, rueda para desplazarte; y cada clic tiene su tecla.
- `Ctrl+a ?`: **guía** de todos los atajos, con buscador. `Ctrl+a Space`: **menú rápido**.
- **Selector de sesiones** con vista previa (`Ctrl+a s`), descripciones de sesión y árbol de sesiones.
- Las sesiones **sobreviven a un reinicio**: se guardan solas cada 5 minutos ([tmux-resurrect](https://github.com/tmux-plugins/tmux-resurrect) + [continuum](https://github.com/tmux-plugins/tmux-continuum)).
- Antes de cerrar algo que no se puede recuperar (una sesión, una pestaña, un panel con un programa en marcha, el historial), **pregunta** con un pequeño menú: clic en la respuesta, o `y` / `n` (`Esc` cancela).

**El monitor del sistema** (sesión `system`, se abre sola en cada terminal nueva)

| Pestaña | Contenido |
|---|---|
| 1 · info | resumen del equipo (fastfetch), recursos (CPU, RAM, GPU, discos, red, ping) y btop |
| 2 · monitor | procesos y puertos: ordenar, filtrar, parar (pregunta antes), saltar de uno a otro |
| 3 · disk | qué ocupa sitio, carpeta a carpeta (como ncdu), los discos y lo que se puede limpiar (apt, journal, snap, brew, Docker, cachés de pip / npm / Composer…, versiones viejas de Claude Code), con cuánto libera cada cosa |
| 4 · packages | tus paquetes (apt, snap, brew) con notas, actualizaciones, buscador e información de cada uno |
| 5 · ssh | los hosts de `~/.ssh/config` (y los que usaste a mano): si responden, qué cuenta ve GitHub con tu clave, sesiones y túneles abiertos; conectar, abrir un túnel, instalar tu clave; tus claves y cuáles tiene el agente |
| 6 · docker | contenedores, detalle (Dockerfile, compose, configuración final), logs en vivo con buscador |
| 7 · git | todos tus repos: rama, cambios, ↑ por subir · ↓ por bajar, stash, último commit y fetch, con qué identidad haces commit; estado, diff, log, ramas y stash de cada uno; fetch, pull, push (pregunta antes) |

La pestaña **git** busca repos en las carpetas de `~/.tmux/git-roots` (una por línea, y opcionalmente cuántos niveles bajar: `~/clientes 2`). Sin ese fichero mira `~/workspace`, `~/projects`, `~/code`, `~/src`, `~/dev`, `~/repos` y `~/git`. Se cambia desde el propio panel: clic derecho → *Add a folder to look in…* o *Edit the folders to look in…*.

Solo trabaja lo que estás viendo: las pestañas ocultas (y todo el monitor cuando no está a la vista o nadie está conectado) no leen nada ni gastan CPU, y se ponen al día en cuanto aparecen.

Cada panel tiene su botón de **zoom**, su menú (clic derecho o `Enter`) y se adapta a cualquier tamaño de ventana. En las listas: escribe para filtrar (`Esc` o clic en **✕** lo borra), `↑↓` para moverte, `← →` o clic en un título para ordenar (`Ctrl+r` invierte), `Tab` para cambiar de fuente (all · apt · snap · brew). En los paneles de detalle y logs, `Tab` o `← →` cambian de pestaña.

---

## Instalación

Lo único que necesitas antes es **git**. El instalador hace el resto: te enseña lo que va a hacer y pregunta antes de empezar.

```bash
git clone https://github.com/kibanly/terminal-setup.git ~/workspace/terminal-setup
cd ~/workspace/terminal-setup
./install.sh
```

> El repo puede estar en cualquier carpeta (sin espacios en la ruta). Si después lo mueves, vuelve a ejecutar `./install.sh` para que tus ficheros apunten al sitio nuevo.

Al terminar, **abre una terminal nueva**.

### Ubuntu 26.04 / 24.04

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/kibanly/terminal-setup.git ~/workspace/terminal-setup
cd ~/workspace/terminal-setup && ./install.sh
```

- Te pedirá tu contraseña (`sudo`) para instalar paquetes.
- **Ubuntu 24.04** trae versiones antiguas de algunas herramientas. El instalador lo detecta y, solo en ese caso:
  - **compila tmux 3.6** (24.04 trae la 3.4, y la configuración necesita la 3.6). Tarda un minuto y se instala en `/usr/local`.
  - instala **fzf**, **fastfetch** y **starship** desde sus versiones oficiales, porque las de 24.04 son antiguas o no existen.
- **Fuente**: si tienes escritorio, la instala en `~/.local/share/fonts`. Después, en la configuración de tu terminal (GNOME Terminal, Konsole, etc.), elige **JetBrainsMono Nerd Font**.
- Por SSH en un servidor: la fuente va en el ordenador **desde el que te conectas**, no en el servidor.

### WSL (Windows)

1. **Instala WSL con Ubuntu** (en PowerShell como administrador) y reinicia si te lo pide:
   ```powershell
   wsl --install -d Ubuntu-24.04
   ```
   (o `Ubuntu-26.04` si ya está disponible: `wsl --list --online` las muestra).
2. **Instala [Windows Terminal](https://aka.ms/terminal)** si no lo tienes (viene con Windows 11).
3. **Dentro de Ubuntu**, igual que en Ubuntu:
   ```bash
   sudo apt update && sudo apt install -y git
   git clone https://github.com/kibanly/terminal-setup.git ~/workspace/terminal-setup
   cd ~/workspace/terminal-setup && ./install.sh
   ```
4. **La fuente y el perfil se configuran en Windows**, no en Linux: [windows/windows-terminal.md](windows/windows-terminal.md). En resumen, en PowerShell:
   ```powershell
   winget install --id DEVCOM.JetBrainsMonoNerdFont
   ```
   y en Windows Terminal › Configuración › tu perfil de Ubuntu › Apariencia › Tipo de fuente: **JetBrainsMono Nerd Font**.

En WSL, «abrir en el navegador» y `open` usan el navegador y el Explorador **de Windows**.

### macOS

> **Estado**: probado en un Mac. El monitor usa las herramientas propias de macOS (procesos con `ps`, puertos con `lsof`, memoria con `vm_stat`, red con `netstat`…). Si algo falla, `bash install/doctor.sh` es el primer paso.
>
> La pestaña **disk** mide tu carpeta personal: la primera vez macOS pregunta si la terminal puede leer Documentos, Escritorio, Descargas… Si dices que no, esas carpetas salen como «unreadable» y el resto se mide igual. Las pestañas disk, ssh y git aún no se han probado en un Mac.

1. **Herramientas de línea de comandos de Apple** (traen git):
   ```bash
   xcode-select --install
   ```
2. **Clona e instala**:
   ```bash
   git clone https://github.com/kibanly/terminal-setup.git ~/workspace/terminal-setup
   cd ~/workspace/terminal-setup && ./install.sh
   ```
   Si no tienes [Homebrew](https://brew.sh), el instalador lo instala primero (te pedirá la contraseña). Después instala todo con `brew bundle` (lista en [`install/Brewfile`](install/Brewfile)), **fuente incluida**.
3. **Terminal**: recomiendo [iTerm2](https://iterm2.com), [Ghostty](https://ghostty.org) o [WezTerm](https://wezfurlong.org/wezterm/), que muestran bien los colores y los iconos. En sus ajustes:
   - Fuente: **JetBrainsMono Nerd Font**.
   - **Option como Meta / Alt** (iTerm2: Settings › Profiles › Keys › *Left Option key: Esc+*). Algunos atajos de tmux usan `Alt` (por ejemplo, `Ctrl+a Alt+c`).

---

## Qué hace el instalador

`./install.sh` primero **enseña el plan** (qué falta y qué va a hacer) y pregunta. Luego:

1. **Paquetes**: instala solo los que faltan (apt en Ubuntu/WSL, Homebrew en macOS), con la versión mínima que necesita la configuración (tmux ≥ 3.6, fzf ≥ 0.48…). Versiones en [`install/versions.sh`](install/versions.sh).
2. **Fuente**: JetBrainsMono Nerd Font, donde corresponda (ver arriba).
3. **Configuración**: **no sustituye ni enlaza nada**. Añade unas líneas **al final** de tu `~/.zshrc` y de tu `~/.tmux.conf` (si no existen, los crea), entre dos marcas para que `./uninstall.sh` pueda quitarlas:
   ```zsh
   # >>> terminal-setup >>>  (./uninstall.sh takes it out)
   source "/ruta/al/repo/zsh/zshrc"
   # <<< terminal-setup <<<
   ```
   En `~/.tmux.conf` es lo mismo, con `source-file`. En `~/.zshenv` añade `skip_global_compinit=1`, para que Ubuntu no cargue el autocompletado otra vez antes que el repo. El resto de tus ficheros queda igual; por si acaso, guarda una copia de cómo estaban en `~/.terminal-setup-backup/<fecha>/`.
   - Ese `source` carga también los alias y las funciones del repo: no hace falta nada más.
   - `~/.tmux` sigue siendo una carpeta tuya: ahí van los plugins, los logs y las descripciones de sesión.
   - El prompt usa el `starship.toml` del repo (variable `STARSHIP_CONFIG`). La config de btop y la de micro se copian solo si no tienes una.
   - Si tienes una instalación anterior (con enlaces al repo), la convierte: tu `~/.zshrc.local` pasa a ser tu `~/.zshrc`, y `~/.tmux` vuelve a ser una carpeta con tus plugins y logs.
4. **Plugins** de tmux y zsh, en las versiones probadas ([`install/plugins.lock`](install/plugins.lock)).
5. **zsh como shell** de inicio (pregunta antes; en macOS ya lo es).
6. **Comprobación**: [`install/doctor.sh`](install/doctor.sh) revisa versiones, configuración, plugins y fuente.

Se puede ejecutar **todas las veces que quieras**: solo hace lo que falta. Si ya está instalado, además hace un **`update`** (paquetes y plugins a su última versión); con `--no-update` no lo hace.

| Opción | Qué hace |
|---|---|
| `./install.sh --dry-run` | enseña lo que haría, sin cambiar nada |
| `./install.sh --yes` | sin preguntas (por ejemplo, para scripts) |
| `./install.sh --config-only` | solo la configuración: ni paquetes, ni fuente, ni plugins (ni `update`) |
| `./install.sh --no-update` | ya instalado: solo lo que falte, sin `update` |
| `bash install/doctor.sh` | comprobar la instalación en cualquier momento |
| `terminal files` | qué archivos ha puesto en tu máquina y para qué sirve cada uno |

Lo mismo con **`make`** (si no lo tienes: `sudo apt install make`; `./install.sh` funciona igual sin él). `make` a secas enseña la lista; `YES=1` quita las preguntas (`make install YES=1`):

| `make …` | Qué hace |
|---|---|
| `install` · `update` | instala lo que falte y, si ya está instalado, actualiza (`./install.sh`) |
| `install-no-update` | solo lo que falte, sin `update` |
| `config` | solo la configuración |
| `dry-run` | enseña lo que haría, sin cambiar nada |
| `uninstall` | quita las líneas de terminal-setup (`./uninstall.sh`) |
| `doctor` | comprobar la instalación |
| `files` | todos los archivos que ha puesto la instalación y para qué sirve cada uno (también: `terminal files`) |
| `monitor` | reconstruir el monitor del sistema |
| `check` | sintaxis de todos los scripts (para cambios en el repo) |

**Qué se instala**

| | Ubuntu 26.04 / WSL | Ubuntu 24.04 | macOS |
|---|---|---|---|
| zsh, git, python3, jq, eza, bat, micro, btop, entr, ansifilter, git-delta, ripgrep, fd, zoxide, tealdeer, shellcheck, zsh-autosuggestions, zsh-syntax-highlighting | apt | apt | Homebrew (zsh y python3 ya vienen) |
| lazygit | apt | binario oficial (`~/.local/bin`) | Homebrew |
| yq (mikefarah) | binario oficial (`~/.local/bin`: el `yq` de Ubuntu es otro programa) | igual | Homebrew |
| tmux ≥ 3.6 | apt | compilado | Homebrew |
| fzf ≥ 0.48 | apt | binario oficial (`~/.local/bin`) | Homebrew |
| fastfetch | apt | `.deb` oficial | Homebrew |
| starship | apt | instalador oficial (`~/.local/bin`) | Homebrew |
| coreutils, flock, bash ≥ 4.2 | ya vienen | ya vienen | Homebrew (el `/bin/bash` de macOS es 3.2; tmux-autoreload necesita uno moderno) |
| JetBrainsMono Nerd Font | `~/.local/share/fonts` (en WSL: en Windows) | igual | Homebrew |
| plugins (tpm, resurrect, continuum, extrakto, fzf-url, logging, cowboy, autoreload, fzf-tab) | git | git | git |

**Opcionales** (si están, se usan; si no, no pasa nada): **Docker** (pestaña docker y su limpieza en disk), **tig** (desde la pestaña git, además de lazygit), **gh** (GitHub), **snap** y **Homebrew** en Linux (aparecen en la pestaña packages), **nvidia-smi** (GPU en Resources).

---

## Primeros pasos

Abre una terminal nueva: tmux arranca solo y te lleva al **monitor del sistema** (o a la sesión que elijas como de inicio, ver abajo). Desde ahí:

| Quiero… | Cómo |
|---|---|
| ver todos los atajos | `Ctrl+a ?` (o el botón **󰋖 guide** arriba a la derecha) |
| el menú con lo más usado | `Ctrl+a Space` (o **󰍜 menu**, o clic derecho en la barra) |
| abrir / cambiar de sesión | `Ctrl+a s` · en la terminal: `terminal` |
| una sesión nueva para un proyecto | `Ctrl+a s`, escribe el nombre, Enter, elige la carpeta |
| pestaña nueva / dividir | `Ctrl+a c` · `Ctrl+a v` (al lado) · `Ctrl+a -` (debajo) |
| volver al monitor | `Ctrl+a M` (o clic en CPU / RAM de la barra) |
| que las terminales nuevas abran otra sesión | en `Ctrl+a s`, sobre la sesión: `Ctrl+s` (o clic derecho → *New terminals start here*) · en la terminal: `terminal start NOMBRE` · `terminal start system` vuelve al monitor. Si esa sesión no está abierta, se crea en su carpeta |
| una terminal sin tmux | `Ctrl+a d`: sales de tmux al shell normal y tmux sigue funcionando (vuelves con `terminal`). Para que no arranque nunca: `export TERMINAL_NO_AUTOSTART=1` en tu `~/.zshrc` |

> **`Ctrl+a`** es el prefijo de tmux: pulsa `Ctrl+a`, suelta, y luego la tecla. Mientras está activo, la barra se pone roja y muestra «press a key».

---

## Cambiar cosas

Hay dos sitios, según para quién sea el cambio:

- **Para todas tus máquinas**: edita los ficheros **del repo** (tabla de abajo), haz `git commit` y llévalo a las demás con `git pull`.
- **Solo para esta máquina** (alias propios, rutas, nvm, pyenv…): en **tu `~/.zshrc`**, como siempre.
  - Lo que pongas **antes** de la línea de terminal-setup se carga primero.
  - Lo que pongas **después** se carga al final y **gana** sobre el repo (por ejemplo, para redefinir un alias). tmux arranca cuando ya se ha cargado todo tu `~/.zshrc`, así que también ve lo de después (un `export DOCKER_HOST=…`, el `PATH`…).
  - En `~/.tmux.conf` funciona igual: lo que va después de la línea de terminal-setup gana.

Para aplicar los cambios:
- **tmux** recarga la configuración solo al guardar `~/.tmux.conf` o `tmux/tmux.conf` (o con `Ctrl+a r`).
- **zsh**: abre una terminal nueva o ejecuta `exec zsh`.

| Quiero cambiar… | Fichero |
|---|---|
| alias | `zsh/aliases.zsh` |
| funciones (`update`, `ports`…) | `zsh/functions.zsh` |
| algo solo de Linux / WSL / macOS | `zsh/platform/<linux, wsl, macos>.zsh` |
| el prompt | `config/starship.toml` |
| atajos, colores y barra de tmux | `tmux/tmux.conf` |
| el monitor del sistema | `tmux/system.sh` (pestañas) y los `.py` / `system/*.sh` de cada panel |
| la guía (`Ctrl+a ?`) | `tmux/guide.zsh` |

---

## Actualizar

```bash
cd ~/workspace/terminal-setup
git pull          # lo último del repo
./install.sh      # instala lo que falte y, como ya está instalado, hace `update`:
                  # paquetes del sistema y plugins a su última versión
```

---

## Desinstalar

```bash
cd ~/workspace/terminal-setup && ./uninstall.sh
```

Quita **solo las líneas de terminal-setup** de `~/.zshrc`, `~/.tmux.conf` y `~/.zshenv`; el resto de esos ficheros queda igual (si solo tenían esas líneas, los borra). También quita las configs de btop y micro que copió, si no las has cambiado.

Los paquetes, la fuente y los plugins **se quedan instalados**, porque otras cosas pueden usarlos. `~/.tmux` también se queda, porque ahí están tus logs.

---

## Estructura del repo

```
terminal-setup/
├── install.sh / uninstall.sh       instalar / deshacer
├── Makefile                        los mismos comandos con make (make a secas: la lista)
├── install/
│   ├── lib.sh                      funciones comunes (detectar el sistema, preguntar, versiones)
│   ├── versions.sh                 versiones mínimas y las que se descargan
│   ├── apt.sh                      Ubuntu / WSL
│   ├── tmux-build.sh               compila tmux (Ubuntu 24.04)
│   ├── brew.sh · Brewfile          macOS
│   ├── fonts.sh                    JetBrainsMono Nerd Font
│   ├── config.sh                   las líneas en ~/.zshrc, ~/.tmux.conf y ~/.zshenv
│   ├── plugins.sh · plugins.lock   plugins en sus versiones probadas
│   ├── doctor.sh                   comprobación
│   └── files.sh                    qué archivos ha puesto y para qué (terminal files)
├── zsh/
│   ├── zshrc                       lo carga tu ~/.zshrc
│   ├── aliases.zsh                 alias (los carga zshrc)
│   ├── functions.zsh               funciones (las carga zshrc)
│   └── platform/                   lo propio de linux / wsl / macos
├── tmux/
│   ├── tmux.conf                   lo carga tu ~/.tmux.conf
│   ├── terminal.zsh                gestor de sesiones (comando `terminal`, selector)
│   ├── guide.zsh · quick-menu.zsh  guía (Ctrl+a ?) y menú rápido (Ctrl+a Space)
│   ├── system.sh                   construye el monitor (sesión `system`)
│   ├── *.py                        los paneles del monitor
│   └── system/                     scripts del monitor (info, recursos, btop, abrir URLs…)
├── config/
│   ├── starship.toml               el prompt (STARSHIP_CONFIG)
│   ├── btop/btop.conf              el btop del monitor (copiado a ~/.config/btop si no tienes)
│   └── micro/settings.json         copiado a ~/.config/micro si no tienes
└── windows/windows-terminal.md     WSL: fuente y perfil de Windows Terminal
```

**No van al repo** (son de cada máquina y viven en tu home): tu `~/.zshrc`, `~/.zshenv` y `~/.tmux.conf`, los plugins (`~/.tmux/plugins`), los logs de tmux (`~/.tmux/logs`), las descripciones de sesión (`~/.tmux/descriptions.tsv`), las carpetas de la pestaña git (`~/.tmux/git-roots`), la sesión de inicio (`~/.tmux/start-session`), los guardados de tmux-resurrect, tus notas de paquetes (`~/.apt-notes.tsv`) y la caché del autocompletado (`~/.cache/zsh/zcompdump`).

---

## Problemas frecuentes

**Veo cuadrados `□` o interrogantes en vez de iconos**
La terminal no usa la Nerd Font. Instálala (en WSL: en Windows) y elígela en los ajustes de la terminal: **JetBrainsMono Nerd Font**. `bash install/doctor.sh` te dice si está instalada.

**Al abrir la terminal no arranca tmux**
No arranca dentro de VS Code, JetBrains, por SSH ni si `TERMINAL_NO_AUTOSTART` está puesto. Para abrirlo a mano: `terminal`.

**`tmux: unknown option` o errores al cargar la configuración**
El tmux que se ejecuta es anterior a la 3.6. Comprueba con `tmux -V` y `which tmux`. En Ubuntu 24.04 debería ser `/usr/local/bin/tmux`; si no, vuelve a ejecutar `./install.sh`. Si tenías tmux abierto con la versión vieja, ciérralo del todo: `tmux kill-server`.

**Los atajos con `Alt` no hacen nada (macOS)**
La tecla Option tiene que funcionar como Meta / Alt: ver [macOS](#macos).

**Quiero ver qué falta o qué está mal**
```bash
bash install/doctor.sh
```
