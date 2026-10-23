# DSH Menu for Omarchy

Desktop controls for [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) on Omarchy. Start and stop a local DSH service, manage an SSH tunnel to a remote DSH service, and open either in a labeled app window.

- **Local:** a managed DSH process with a green window header.
- **Remote:** a managed SSH tunnel to a remote DSH instance, with a blue window header.
- **Open**, **Start**, **Stop**, and **Logs** actions for both targets.
- Persistent window labels and title prefixes to distinguish local and remote sessions.

The app extends Omarchy's Quickshell menu through its JSONC interface. It supports one local target and one remote target. The remote target is labeled **Remote**, regardless of the configured SSH alias.

## Requirements

- Omarchy with `omarchy-menu`, JSONC menu extensions, `omarchy-launch-terminal`, and `uwsm-app`.
- Python 3.9 or newer. Python helpers use only the standard library.
- Node.js and npm, with `node` and `npx` available on PATH.
- Chromium, OpenSSH, user systemd and its journal, and `notify-send`.
- For remote access: working SSH key/agent authentication and DSH already running on the remote host.

The installer checks required commands. Node/npm and the DSH npm package are external dependencies and are not vendored here. DSH's own setup and model/provider credentials are configured separately.

## Installation

Clone or download the repository and open a terminal in its directory. Run as your normal desktop user inside a logged-in Omarchy session:

```bash
python3 install.py --dry-run
python3 install.py --prepare-dsh
```

`--dry-run` previews settings and destination files without writing or downloading. `--prepare-dsh` prepares DSH through npm before installation and requires network access. Subsequent service starts use the npm cache in offline mode.

No `sudo` is needed. Installation does not start services or enable login autostart. Installed files are independent copies, so the source checkout can be moved after installation.

Open **Win + Space → DeepSeek Harness**, or run:

```bash
omarchy menu summon dsh
```

### Configuration

| Setting | Default | Installer option |
| --- | --- | --- |
| Local DSH port | `3080` | `--local-port` |
| SSH host alias | `remote` | `--ssh-host` |
| Local tunnel port | `3081` | `--tunnel-port` |
| DSH port on the remote host | `3080` | `--remote-port` |
| Local DSH working directory | `~/Projects` | `--workdir` |
| npm launcher | mise shim if available, otherwise `npx` on PATH | `--npx` |

Both local listeners bind to `127.0.0.1`. The SSH tunnel forwards to `localhost` on the remote host. The working directory is created if needed.

For example:

```bash
python3 install.py --prepare-dsh \
  --ssh-host my-server \
  --local-port 4080 \
  --tunnel-port 4081 \
  --remote-port 3080 \
  --workdir "$HOME/Projects"
```

Settings are saved in `~/.config/dsh-menu/config.json`. Rerunning the installer retains them unless overridden by command-line options. Run `python3 install.py --help` for all options.

### Remote SSH setup

Configure an SSH alias in `~/.ssh/config`, for example:

```sshconfig
Host my-server
    HostName your-server-address
    User your-remote-username
```

Run `ssh my-server` in a terminal to establish trust and verify authentication. The managed tunnel uses noninteractive SSH and fails rather than prompting for a password. DSH Menu does not configure SSH or install/start DSH on the remote host.

### Browser authentication

The local Open action retrieves the authenticated URL printed by its managed DSH service.

App windows use a dedicated Chromium profile. On first launch, the app imports existing DSH login cookies for `localhost` and `127.0.0.1` from Chromium's default profile. Other sites' cookies and browsing history are not imported. Subsequent logins are stored independently in the DSH profile.

If the remote target needs authentication, get the login URL printed by DSH on the remote host. Replace its host and port with the local tunnel address, preserving the token, then open it in the dedicated browser:

```bash
dsh-control remote start
dsh-webapp remote 'http://localhost:3081/?token=YOUR_REMOTE_DSH_LOGIN_TOKEN'
```

Use the configured tunnel port if it differs. Login URLs are private. Later Open actions reuse the browser login.

## Usage

| Action | Local | Remote |
| --- | --- | --- |
| Open webapp | Starts DSH if needed, waits for it, and opens its authenticated app window | Starts the tunnel if needed, waits for a remote HTTP response, and opens its app window |
| Start | Starts the managed local DSH process | Starts the managed SSH tunnel |
| Stop | Stops the local service and its child processes | Stops the tunnel; remote DSH and its jobs keep running |
| Logs | Opens local DSH logs in a terminal | Opens SSH tunnel logs in a terminal |

A checkmark beside a target means its user service is active. For Remote, it indicates the tunnel process is running; it does not continuously check the remote DSH service. Closing a window leaves its service or tunnel running.

App windows have permanent 32-pixel sans-serif headers: **Local** in green and **Remote** in blue. Headers reserve space above DSH controls and survive navigation, reloads, and session changes. Window titles also begin with `[DSH · Local]` or `[DSH · Remote]`.

### Terminal controls

Press **Win + Enter** to open a terminal if the menu is unavailable:

```bash
dsh-control local open
dsh-control local start
dsh-control local stop
dsh-control local status
dsh-control local logs

dsh-control remote open
dsh-control remote start
dsh-control remote stop
dsh-control remote status
dsh-control remote logs
```

Press **Ctrl + C** to stop watching logs. Logs can contain private DSH login URLs.

## Updates

Pull updated source and reinstall:

```bash
git pull
python3 install.py
```

Reinstallation updates the app's `dsh` and `dsh.*` menu entries while preserving unrelated entries and comments. Changed files receive timestamped backups; unchanged files are left alone.

Stop/start affected services after changing service settings. Close all dedicated DSH browser windows and reopen them after changing header settings. Ordinary browser windows can remain open. Windows launched through other browser shortcuts do not acquire headers automatically.

If the Node installation path changes, refresh it with `--npx /path/to/npx`. Use `--prepare-dsh` again if the npm cache was cleared.

## Installed files

| Path | Purpose |
| --- | --- |
| `~/.local/bin/dsh-control` | Service controls, readiness checks, and local login URL retrieval |
| `~/.local/bin/dsh-webapp` | Dedicated Chromium app-window launcher |
| `~/.config/dsh-menu/config.json` | Generated installation settings |
| `~/.config/systemd/user/dsh-local.service` | Local DSH service |
| `~/.config/systemd/user/dsh-tunnel-remote.service` | SSH tunnel service |
| `~/.config/omarchy/extensions/omarchy-menu.jsonc` | Shared menu extension; this app owns only `dsh` and `dsh.*` entries |
| `~/.config/dsh-webapps/labels/` | Header extension and generated port mapping |
| `~/.local/share/dsh-webapps/` | Browser profile and login state |

The installer validates the menu update before writing files, generates the services and header mapping, and reloads user systemd. It does not edit packaged Omarchy files or Hyprland configuration.

SSH keys, credentials, browser state, npm cache, and DSH conversations are outside the repository. Each installation needs its own authentication.

### Menu extension format

Omarchy's extension file uses JSONC: JSON with comments and trailing commas. Dotted IDs establish the submenu hierarchy. A row without an action creates a submenu; a row with an action runs a shell command. A `checked` condition controls its checkmark.

```json
{
  "dsh": {"label": "DeepSeek Harness"},
  "dsh.local": {"label": "Local"},
  "dsh.local.open": {
    "label": "Open webapp",
    "action": "\"$HOME/.local/bin/dsh-control\" local open"
  }
}
```

The installer generates absolute, shell-quoted command paths. Menu commands do not load interactive shell functions.

## Troubleshooting

- **Missing dependencies:** install the commands reported by the installer. Omarchy releases with a different launcher require the Quickshell JSONC menu interface.
- **Port already in use:** stop any manually started DSH process or SSH tunnel using the port, then retry. The app does not kill unrelated processes or take over manually started ones.
- **Remote connection fails:** try `ssh YOUR_ALIAS` in a terminal to resolve authentication or host-key issues.
- **Tunnel active but Open times out:** check that remote DSH is listening on the configured port. Tunnel logs contain SSH errors, not remote DSH logs.
- **Remote authentication required:** follow the browser authentication steps above using `dsh-webapp`.
- **Local service cannot start:** inspect Logs. Restore the npm cache with `python3 install.py --prepare-dsh` if necessary.
- **Repeated service failures:** fix the cause, then run `systemctl --user reset-failed dsh-local.service` or `dsh-tunnel-remote.service` before retrying.
- **Menu unavailable:** use the terminal controls. If the desktop shell is unresponsive, run `omarchy restart shell`.
- **Headers absent:** open through DSH Menu. Close dedicated DSH windows and reopen after updating the extension.

## Uninstall

Stop the managed services:

```bash
dsh-control local stop
dsh-control remote stop
```

Remove the `dsh` and `dsh.*` entries from the shared menu extension, keeping unrelated entries. Remove the two helper scripts, two service units, `~/.config/dsh-menu/`, and `~/.config/dsh-webapps/labels/` listed above. Then reload systemd:

```bash
systemctl --user daemon-reload
```

After closing its windows, the dedicated browser profile can be removed separately or retained. Removing DSH Menu does not uninstall the DSH npm package or remove DSH conversations, SSH configuration, or credentials.

## Development

```bash
python3 -m unittest -v
python3 -m py_compile install.py dsh-control dsh-webapp
node --check labels/labels.js
node --check labels/targets.js
```

Installer tests cover alternate home directories, custom settings, repeat installation, backups, shell quoting, JSONC preservation, and invalid menu input.
