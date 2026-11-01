# Windows Terminal (solo WSL)

En WSL, Linux corre «dentro» de Windows, pero **la ventana que ves es Windows Terminal**, un programa de Windows. Por eso hay dos cosas que se configuran en Windows y no las puede hacer `install.sh`: la **fuente** y el **perfil** de Ubuntu.

## 1. La fuente: JetBrainsMono Nerd Font

Los iconos del prompt, de la barra de tmux y de los paneles (󰍛 󰘚 󰋽 …) son caracteres de una *Nerd Font*. Si Windows Terminal no la usa, verás cuadrados `□` o interrogantes.

**Instalarla** (una de las dos):

- En **PowerShell**:
  ```powershell
  winget install --id DEVCOM.JetBrainsMonoNerdFont
  ```
- A mano: descarga [JetBrainsMono.zip](https://github.com/ryanoasis/nerd-fonts/releases/download/v3.5.1/JetBrainsMono.zip), descomprímelo, selecciona todos los `.ttf` › clic derecho › **Instalar para todos los usuarios**.

`install.sh` comprueba si ya está en Windows y, si no, te lo recuerda al terminar.

## 2. El perfil de Ubuntu

Windows Terminal › **Configuración** (`Ctrl+,`) › en la lista de la izquierda, tu perfil **Ubuntu-26.04** (o el que uses) › **Apariencia**:

| Opción | Valor |
|---|---|
| Tipo de fuente | `JetBrainsMono Nerd Font` |
| Tamaño de fuente | `12` (a tu gusto) |

Y en **Inicio** (Configuración › Inicio):

| Opción | Valor | Por qué |
|---|---|---|
| Perfil predeterminado | tu Ubuntu | cada pestaña nueva abre WSL, y con él tmux |

### Lo mismo en `settings.json`

Si prefieres editar el JSON (Configuración › abajo a la izquierda, **Abrir archivo JSON**), la parte que importa es:

```jsonc
{
    "defaultProfile": "{guid-de-tu-perfil-ubuntu}",
    "profiles": {
        "defaults": {
            "font": { "face": "JetBrainsMono Nerd Font", "size": 12 }
        }
    },
    "actions": [
        { "command": { "action": "copy", "singleLine": false }, "id": "User.copy" },
        { "command": "paste", "id": "User.paste" }
    ],
    "keybindings": [
        { "id": "User.copy",  "keys": "ctrl+c" },
        { "id": "User.paste", "keys": "ctrl+v" }
    ],
    "copyOnSelect": false
}
```

- `ctrl+c` copia **solo si hay texto seleccionado**; sin selección sigue mandando Ctrl+C al programa (para pararlo), como siempre.
- `ctrl+v` pega. tmux deja `Ctrl+V` libre por esto (en el modo copia, la selección en bloque es `r`).
- El portapapeles funciona en las dos direcciones sin más: tmux copia al de Windows con OSC 52, que Windows Terminal entiende.

## 3. Pantalla completa

El panel de sistema se adapta a cualquier tamaño, pero luce más grande. `F11` (o `Alt+Enter`) pone Windows Terminal a pantalla completa.

## 4. Opcional: Windows en el `$PATH` de WSL

Por defecto WSL añade todas las carpetas de Windows al `$PATH`, y eso hace que zsh tarde más en buscar comandos. Si quieres desactivarlo, en `/etc/wsl.conf`:

```ini
[interop]
appendWindowsPath = false
```

y en PowerShell `wsl --shutdown` para que se aplique. La configuración ya cuenta con ello: abre el navegador y el Explorador de Windows por su ruta completa (`tmux/system/open.sh`), así que todo sigue funcionando con o sin este cambio.

## 5. Una pestaña que entra en tu VPS

La IP y el usuario **no van en el repo**: van en `~/.ssh/config` de WSL, que solo está en tu PC.

```sshconfig
Host vps
  HostName <ip-del-servidor>
  User <usuario>
  IdentityFile ~/.ssh/id_ed25519
  ServerAliveInterval 30
```

Con eso, `ssh vps` (y `scp archivo vps:`) ya funcionan, y también el comando `vps`: dentro de tmux abre una ventana nueva conectada al servidor. Si tu `Host` se llama distinto, `vps <nombre>` o `export TERMINAL_VPS=<nombre>` en `~/.zshrc`.

Para abrirla desde el menú ▾ de Windows Terminal, añade un perfil en `settings.json` (en `profiles.list`):

```jsonc
{
    "name": "VPS",
    "tabTitle": "VPS",
    "commandline": "wsl.exe -d Ubuntu-24.04 -- ssh vps",
    "font": { "face": "JetBrainsMono Nerd Font" },
    "guid": "{un-guid-nuevo}"
}
```

Cambia `Ubuntu-24.04` por tu distro (`wsl -l` en PowerShell). Al salir del servidor (`exit`), la pestaña se cierra.
