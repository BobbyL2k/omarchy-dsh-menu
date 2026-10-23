# DSH Menu for Omarchy

Desktop controls for [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness): manage a local DSH service and SSH tunnels to any number of remote instances, then open each connection in a named app window.

Each target gets **Open webapp**, **Start**, **Stop**, and **Logs** actions. Persistent colored headers and window-title prefixes identify the connection, including during navigation and session changes.

## Requirements

- Omarchy's Quickshell menu with JSONC extensions, `omarchy-menu`, `omarchy-launch-terminal`, and `uwsm-app`.
- Python 3.9 or newer; only the standard library is used.
- Node.js/npm (`node` and `npx`), Chromium, OpenSSH, user systemd, `systemd-analyze`, the journal, and `notify-send`.
- For remote targets: SSH key/agent authentication and DSH already running on each server.

The installer checks dependencies. DSH's own setup and model/provider credentials are separate. Dependencies are not vendored in this repository.

## Install

Clone or download the repository and open a terminal in its directory, inside your Omarchy desktop session. Run as your normal user; no `sudo` is needed.

For a fresh installation, copy the example config:

```bash
mkdir -p ~/.config/dsh-menu
cp config.example.json ~/.config/dsh-menu/config.json
```

Edit `~/.config/dsh-menu/config.json` to match your SSH aliases and ports. If already installed, edit the existing config instead of replacing it with the example.

Preview and install:

```bash
python3 install.py --dry-run
python3 install.py --prepare-dsh
```

`--prepare-dsh` downloads/prepares DSH through npm and requires network access. Later service starts use the npm cache in offline mode. Installation leaves new targets stopped and does not enable login autostart.

Open **Win + Space → DeepSeek Harness**, or run:

```bash
omarchy menu summon dsh
```

The example creates this menu:

```text
DeepSeek Harness
├── Local
├── Development
└── Research
```

Each submenu contains the same four controls. With no config file, the installer creates a local-only configuration. Installed files are independent copies, so the checkout can be moved afterward.

## Configuration

The only configuration file you edit is **`~/.config/dsh-menu/config.json`**. It is strict JSON: no comments or trailing commas. Use [config.example.json](config.example.json) as a starting point:

```json
{
  "version": 2,
  "local": {
    "label": "Local",
    "port": 3080,
    "workdir": "~/Projects"
  },
  "remotes": {
    "development": {
      "label": "Development",
      "ssh_host": "dev-server",
      "local_port": 3081,
      "remote_port": 3080,
      "color": "#99baff"
    },
    "research": {
      "label": "Research",
      "ssh_host": "research-server",
      "local_port": 3082,
      "remote_port": 3080,
      "color": "#dfb0ff"
    }
  }
}
```

### Local service

| Field | Default | Meaning |
| --- | --- | --- |
| `label` | `Local` | Menu, header, and window-title name |
| `port` | `3080` | Local DSH loopback port |
| `workdir` | `~/Projects` | DSH working directory, created if needed |

The local service is always present. Omitting `remotes`, or setting it to `{}`, gives a local-only menu.

### Remote targets

The key under `remotes` is the target's **stable ID**. It is used in commands, menu IDs, and service names. Use lowercase letters, digits, and hyphens, starting with a letter; maximum length is 48 characters. `local` is reserved.

| Field | Required | Meaning |
| --- | --- | --- |
| `ssh_host` | Yes | SSH alias or `user@hostname` |
| `local_port` | Yes | Port on this computer for this target's tunnel |
| `remote_port` | No; defaults to `3080` | DSH port reached as `localhost` on the remote host |
| `label` | No; derived from the ID | Human-readable menu/header/window-title name |
| `color` | No; a stable default is chosen | Header accent as a six-digit hex color |

Every local listener needs a different port, including the local DSH service. All remote servers may use the same remote port. Local listener ports must be 1024–65535; remote ports may be 1–65535. Tunnels bind only to `127.0.0.1`.

Display names may contain spaces; use IDs in terminal commands. Keep IDs and local ports stable to preserve familiar service names and browser login endpoints. Labels must be at most 80 characters and cannot contain control characters or square brackets.

An optional top-level `npx` field selects an absolute npm launcher path, or a path beginning with `~/`. Otherwise the installer discovers a mise shim or `npx` on PATH. Omitting this field lets reinstall rediscover a changed Node installation path.

Duplicate keys, duplicate local ports, invalid IDs, invalid colors, and unknown fields are rejected before installation changes files or services.

### SSH setup

Configure each alias in `~/.ssh/config`, for example:

```sshconfig
Host dev-server
    HostName your-development-server-address
    User your-remote-username

Host research-server
    HostName your-research-server-address
    User your-remote-username
```

Run `ssh dev-server` and `ssh research-server` in a terminal to establish trust and verify authentication. Managed tunnels use noninteractive SSH; password or host-key prompts must be resolved in a terminal. SSH options such as keys and jump hosts belong in your SSH config.

DSH Menu does not install, start, or stop DSH on the remote hosts. It manages only the local tunnels to them.

## Reinstall and apply changes

After editing the config, run this from the checkout:

```bash
python3 install.py
```

That is the entire synchronization workflow. There are no add/remove commands or service files to maintain manually.

| Config change | What reinstall does |
| --- | --- |
| Add a remote | Creates its menu and service; leaves it stopped until opened |
| Change an SSH host or tunnel port | Replaces the unit and restarts it if it was running |
| Change local service settings | Restarts the local service if it was running |
| Change a label or color | Updates menu/header data without restarting a service |
| Remove a remote | Stops/disables its managed tunnel and removes its unit/menu/header mapping |
| Rename a target ID | Treats it as removing the old target and adding a new one |
| Change nothing | Leaves files and services untouched |

Removing a remote closes its tunnel; remote DSH and its jobs continue running. Restarting the local DSH service stops its child processes, so apply local service changes between local jobs.

Changed files and removed unit files receive timestamped backups. Unrelated menu entries, comments, and service files are preserved. All affected running units stop before any restart, so swapping local ports between targets works.

The helpers use a generated applied snapshot, `runtime.json`. Editing the desired config alone does not change their behavior; reinstall applies it. Do not edit the generated snapshot or ownership state directly.

Chromium caches the header extension. After changing labels, colors, or ports, close all dedicated DSH windows and reopen them to load the updated mapping. Ordinary browser windows can stay open. Removing a target does not forcibly close its browser window.

For source updates:

```bash
git pull
python3 install.py
```

To import a config from another location:

```bash
python3 install.py --config /path/to/settings.json
```

It is saved to the standard config location; later reinstalls need no flag. `--dry-run` previews changes without writing or stopping services. `--prepare-dsh` can be used again if the npm cache was cleared.

### Existing single-remote installations

The old flat config format is migrated automatically on reinstall. Its SSH host, ports, working directory, and npm launcher are preserved. The previous remote becomes the target ID `remote`; you can then edit the generated `remotes` object to add others.

An earlier managed tunnel unit is adopted from the existing app menu, backed up, and replaced if necessary. Its running/stopped state is preserved during the single-remote migration. Ordinary target-ID changes after migration leave the newly named target stopped until opened.

## Usage

| Action | Local | Any remote |
| --- | --- | --- |
| Open webapp | Starts local DSH if needed and opens its authenticated app window | Starts that target's tunnel if needed, waits for HTTP readiness, and opens its app window |
| Start | Starts local DSH | Starts only that target's tunnel |
| Stop | Stops local DSH and its child processes | Stops only that target's tunnel |
| Logs | Opens local DSH logs | Opens that target's SSH tunnel logs |

A checkmark means the service or tunnel process is active, not that the remote server is continuously health-checked. Closing an app window leaves its service/tunnel running. Services are not enabled at login.

Headers reserve 32 pixels above DSH controls. Window titles also receive a prefix such as `[DSH · Research]`. Target names persist across page reloads and session changes.

### Terminal controls

Press **Win + Enter** if the menu is unavailable. Use the configured target ID:

```bash
dsh-control local open
dsh-control development start
dsh-control research open
dsh-control research status
dsh-control research logs
dsh-control research stop
```

Supported actions are `open`, `start`, `stop`, `status`, and `logs`. Running a command without valid arguments prints the available target IDs. Press **Ctrl + C** to stop watching logs. Logs can contain private DSH login URLs.

### Browser authentication

The local Open action retrieves its DSH login URL from the service journal. All target windows share a dedicated Chromium profile, separate from ordinary browsing.

On first launch, existing DSH login cookies for `localhost` and `127.0.0.1` are imported from Chromium's default profile. Other sites' cookies and browsing history are not imported. Remote targets may each require their own login.

For a remote that needs authentication, get the login URL printed by DSH on that server. Replace its host/port with the target's local tunnel address, keeping the token, then open it in the dedicated profile:

```bash
dsh-control research start
dsh-webapp research 'http://localhost:3082/?token=YOUR_REMOTE_DSH_LOGIN_TOKEN'
```

Use the configured target ID and local port. Login URLs are private. Later Open actions reuse the browser session. Reassigning a port to a different server may require authentication again.

## Installed files

| Path | Purpose |
| --- | --- |
| `~/.local/bin/dsh-control` | Target controls and readiness checks |
| `~/.local/bin/dsh-webapp` | Dedicated Chromium app launcher |
| `~/.local/bin/dsh_config.py` | Shared validation and target model |
| `~/.config/dsh-menu/config.json` | User-edited desired configuration |
| `~/.config/dsh-menu/runtime.json` | Validated, applied configuration |
| `~/.config/dsh-menu/installed.json` | Ownership record for managed units |
| `~/.config/systemd/user/dsh-local.service` | Local DSH service |
| `~/.config/systemd/user/dsh-tunnel-<ID>.service` | One tunnel per remote |
| `~/.config/omarchy/extensions/omarchy-menu.jsonc` | Shared menu; only `dsh` and `dsh.*` entries are managed |
| `~/.config/dsh-webapps/labels/` | Browser extension and generated port-to-label mapping |
| `~/.local/share/dsh-webapps/` | Dedicated browser profile and login state |

The installer validates every generated unit before synchronizing services. It edits no packaged Omarchy files or Hyprland configuration. SSH keys, credentials, npm cache, browser state, and DSH conversations remain outside the repository.

## Troubleshooting

- **Config rejected:** use strict JSON and check the field/target named in the error. Unknown fields often indicate a typo. The existing applied installation stays in use.
- **Port already in use:** stop any manually started process using it, or choose another port and reinstall. DSH Menu does not take over unrelated processes.
- **Remote connection fails:** try `ssh YOUR_ALIAS` in a terminal and resolve authentication or host-key issues.
- **Tunnel active but Open times out:** confirm remote DSH listens on the configured remote port. Tunnel logs contain SSH errors, not remote DSH logs.
- **Remote login required:** authenticate using `dsh-webapp TARGET URL` as above.
- **Local startup fails:** inspect Logs; restore the npm cache with `python3 install.py --prepare-dsh` if needed.
- **Repeated failures:** fix the cause, then use `systemctl --user reset-failed dsh-tunnel-<ID>.service` or `dsh-local.service` before retrying.
- **Menu unavailable:** use the terminal controls. If the desktop shell is unresponsive, run `omarchy restart shell`.
- **Wrong or missing headers:** open through DSH Menu and reopen the dedicated browser windows after configuration updates.

## Uninstall

Stop the local target and each configured remote with `dsh-control TARGET stop`. Remove the app's `dsh` and `dsh.*` entries from the shared menu, preserving unrelated entries. Remove the helpers/module, managed unit files listed in `installed.json`, and the `~/.config/dsh-menu/` and `~/.config/dsh-webapps/labels/` directories. Then run:

```bash
systemctl --user daemon-reload
```

The browser profile can be removed separately after closing its windows. Uninstalling DSH Menu does not remove DSH conversations, the npm package, SSH configuration, or credentials.

## Development

```bash
python3 -m unittest -v
python3 -m py_compile install.py dsh_config.py dsh-control dsh-webapp
node --check labels/labels.js
node --check labels/targets.js
```

Tests cover config validation, legacy migration, multiple targets, independent controls, applied-state isolation, JSONC preservation, service cleanup, active-only restart, port swaps, backups, and unchanged reinstalls.
