# Database

MonitorHub stores its configuration — profiles, monitors and support tables — in
a local SQLite database. The database is created explicitly, in the same spirit as
`git init`, so a fresh installation has no database until you ask for one.

## Location

The database lives in the directory given by `--db-dir`, or by the
`default_database` setting in `conf/config.yaml`, or in `data` when neither is
set. Relative paths in the config resolve against the application folder. A
released binary therefore keeps its data in the `data/` folder beside the
executable unless you point it elsewhere.

## Commands

### Initialise

```bash
mhub database init
```

This creates the schema and loads the support tables. Run it once after
installing.

### Inspect

```bash
mhub database info       # database information
mhub database version    # schema version
```

`mhub database version` reports the schema version and whether it matches the
version this application supports.

### Upgrade

```bash
mhub database upgrade
```

Applies any pending schema migrations without touching your data. It refuses to
downgrade a database that was created by a newer version of MonitorHub, so an
older binary cannot corrupt a newer database.

### Recreate

```bash
mhub database init --recreate
```

!!! danger "This deletes your configuration"
    `--recreate` drops the existing schema and recreates it from scratch, which
    removes every profile and monitor you have configured. Back up the database
    first.

### Load example data

```bash
mhub database sample-data
```

Loads a small set of example data so you can see how profiles, monitors and their
mapping fit together: one example monitor, one fake S3 profile and the mapping
between them, using clearly fake credentials and paths. The command only adds the
examples once and is safe to run again. Delete them with
`mhub profile delete` and `mhub monitor delete`.

Next: [Placeholders](placeholders.md) lists the template variables available to
command profiles.
