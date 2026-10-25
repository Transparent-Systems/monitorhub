# Install on Linux

Download the binaries you want from the
[Releases](https://github.com/Transparent-Systems/monitorhub/releases) page and
make them executable — the executable bit is not kept by the download:

```bash
chmod +x mhub mhub-gui
```

## CLI

```bash
./mhub monitor new
```

## Web GUI

The GUI is a single self-contained file that also carries the whole CLI:

```bash
./mhub-gui                     # opens http://127.0.0.1:8501
./mhub-gui --server.port 9000
./mhub-gui database init
```

!!! note "Data lives beside the binary"
    The first run creates `conf/`, `data/` and `logs/` next to the executable.
    Run the binary from a directory you can write to (for example
    `/opt/monitorhub`), and keep those folders when you upgrade.

Next: [create your first monitor](first-monitor.md).
