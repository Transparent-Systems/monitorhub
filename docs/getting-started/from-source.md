# Run from source

Running from source is the development setup: it needs Python 3.12 and a virtual
environment. For normal use, prefer the [Windows](install-windows.md) or
[Linux](install-linux.md) binaries.

## Create the environment

```bash
python -m venv .venv
```

Activate it — Windows (PowerShell) or Linux/macOS:

=== "Windows"

    ```powershell
    ./.venv/Scripts/activate
    ```

=== "Linux / macOS"

    ```bash
    source .venv/bin/activate
    ```

Then install the dependencies:

```bash
pip install -r requirements.txt
```

## Run the CLI

From the repository root:

```bash
python mhub.py --help
python mhub.py database init
python mhub.py monitor new
```

## Run the web GUI

The `webgui` subcommand starts the same Streamlit application that the
`mhub-gui` binary runs:

```bash
python mhub.py webgui
```

## Run the tests

The Makefile targets use the project virtualenv explicitly:

```bash
make test-unit
```

!!! tip "Use the project interpreter"
    Prefer `.venv/bin/python` (or the Makefile targets) over a bare `python`:
    the system interpreter may be older than the 3.12 this project requires,
    which shows up as a `TypeError: unsupported operand type(s) for |`.

Next: [create your first monitor](first-monitor.md).
