# Install on Windows

MonitorHub ships as two downloads. Take one or both from the
[Releases](https://github.com/Transparent-Systems/monitorhub/releases) page:

| File | What it is |
| --- | --- |
| `mhub-gui-<version>-windows.zip` | The web GUI **and** the full CLI (recommended) |
| `mhub.exe` | The CLI only — smaller, for servers and scripts |

## Web GUI (recommended)

The GUI ships as a zip that contains a folder. Unzip it and run the executable
inside it:

```powershell
.\mhub-gui\mhub-gui.exe
```

Your browser opens <http://127.0.0.1:8501>.

!!! warning "Keep the folder together"
    The first run creates `conf\`, `data\` and `logs\` inside the `mhub-gui`
    folder. Keep those subfolders when you upgrade, or you will start with an
    empty database.

Streamlit options work as well:

```powershell
.\mhub-gui\mhub-gui.exe --server.port 9000
```

The GUI binary also carries the whole CLI, so it is the only download you need:

```powershell
.\mhub-gui\mhub-gui.exe database init
.\mhub-gui\mhub-gui.exe monitor start
.\mhub-gui\mhub-gui.exe --help
```

## CLI only

Download `mhub.exe` and run it directly:

```powershell
.\mhub.exe monitor new
```

## SmartScreen warning

Windows SmartScreen may warn that the executable is unrecognised because it is
not code-signed. Choose **More info → Run anyway**.

Next: [create your first monitor](first-monitor.md).
