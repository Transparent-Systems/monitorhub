# Changelog

The canonical changelog lives in the repository and is updated with every
release:

- [CHANGELOG.md](https://github.com/Transparent-Systems/monitorhub/blob/main/CHANGELOG.md)
- [All releases](https://github.com/Transparent-Systems/monitorhub/releases)

The version of the binary you are running is reported by:

```bash
mhub version
```

## Release artifacts

Every release tag publishes both binaries for both platforms. Each binary is
accompanied by a SHA256 checksum file.

| Platform | File | Layout |
| --- | --- | --- |
| Windows | `mhub-gui-<version>-windows.zip` | The web GUI **and** the full CLI, as a folder in a zip |
| Windows | `mhub.exe` | The CLI only, single file |
| Linux | `mhub-gui` | The web GUI **and** the full CLI, single self-contained file |
| Linux | `mhub` | The CLI only, single file |

The Windows GUI ships as a folder because a onefile build of the Streamlit
application starts slowly; the Linux GUI ships as a single file. Both carry the
whole CLI, so the GUI download alone is enough to manage MonitorHub from the
command line.

## Upgrading

1. Download the new binary (or zip) from the release page.
2. Stop any running monitors.
3. Replace the binary, keeping the `conf/`, `data/` and `logs/` folders beside it.
4. Run `mhub database version` and, when the schema changed,
   `mhub database upgrade`.

See [Database](../reference/database.md) for the database commands.
