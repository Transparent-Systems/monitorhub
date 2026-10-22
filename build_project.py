import os
import shutil
import subprocess
import sys

# --- Configuration ---
MAIN_SCRIPT = "mhub.py"
APP_NAME = "mhub"
ICON_FILE = "app_icon.ico"
DIST_DIR = "dist"

# The GUI is built as a *separate* artifact: bundling Streamlit (frontend
# bundle, pandas/pyarrow/altair, ...) would bloat the CLI binary by hundreds of
# megabytes for no benefit to CLI users. The GUI binary also carries the whole
# CLI, so it is self-sufficient - users who want the small download still get
# the CLI-only `mhub`.
GUI_MAIN_SCRIPT = "mhub_gui.py"
GUI_APP_NAME = "mhub-gui"

# Build target -> (PyInstaller entry script, output binary name).
TARGETS = {
    "cli": (MAIN_SCRIPT, APP_NAME),
    "gui": (GUI_MAIN_SCRIPT, GUI_APP_NAME),
}

# Accepted spellings of a target name (the GUI was called "webgui" before the
# binary was renamed to mhub-gui).
TARGET_ALIASES = {"webgui": "gui"}


def resolve_target(name: str) -> str:
    """Return the canonical target name, or the input when it is unknown."""
    return TARGET_ALIASES.get(name, name)


def _data_spec(source: str, destination: str) -> str:
    """Build an ``--add-data`` value using this platform's path separator."""
    return f"{source}{os.pathsep}{destination}"


# Extra PyInstaller options for the CLI target only.
CLI_BUILD_OPTIONS = [
    # Belt and braces: the CLI has no use for Streamlit. mhub.py imports the
    # GUI launcher dynamically precisely so PyInstaller never follows it, and
    # this keeps the small binary small even if something starts referencing
    # Streamlit again.
    "--exclude-module=streamlit",
]

# Extra PyInstaller options for the GUI target only.
GUI_BUILD_OPTIONS = [
    # Streamlit ships no PyInstaller hook. Collect its frontend bundle
    # (streamlit/static), its submodules and its distribution metadata:
    # streamlit/version.py reads importlib.metadata at import time, and
    # starlette_server.py reports the uvicorn/websockets versions.
    "--collect-all=streamlit",
    "--copy-metadata=streamlit",
    "--copy-metadata=uvicorn",
    "--copy-metadata=websockets",
    # Streamlit executes the main script by path and discovers the sidebar pages
    # from the `pages/` folder next to it, so PyInstaller never sees the
    # `app.*` imports of those pages. Collect every application submodule.
    "--collect-submodules=app",
    # The Streamlit main script and its sidebar pages, shipped as data files
    # (globs avoid dragging in __pycache__).
    f"--add-data={_data_spec('app/webgui/*.py', 'app/webgui')}",
    f"--add-data={_data_spec('app/webgui/pages/*.py', 'app/webgui/pages')}",
    # Read-only resources resolved through resource_root() (sys._MEIPASS).
    f"--add-data={_data_spec('README.md', '.')}",
    f"--add-data={_data_spec('app_icon_512.png', '.')}",
]

def clean_previous_builds(target: str = "cli"):
    """Remove this target's previous build output.

    Only the target's own artifacts are removed, so building the CLI and the GUI
    in either order leaves both binaries in ``dist/``. It also preserves any
    ``conf/``/``data/``/``logs/`` a test run left beside the binary, which a
    blanket ``dist/`` wipe used to delete.
    """
    _, output_name = TARGETS[target]
    exe_name = f"{output_name}.exe" if sys.platform == "win32" else output_name
    for path in (os.path.join("build", output_name), os.path.join(DIST_DIR, exe_name)):
        if not os.path.exists(path):
            continue
        print(f"Cleaning {path}...")
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            os.remove(path)

def build_executable(target: str = "cli"):
    """Build the ``cli`` (default) or ``gui`` executable."""
    target = resolve_target(target)
    main_script, output_name = TARGETS[target]

    print(f"--- Preparing build for {output_name} (target: {target}) ---")
    clean_previous_builds(target)

    # Base PyInstaller command
    # Invoke PyInstaller through the running interpreter (``sys.executable -m
    # PyInstaller``) rather than a bare ``pyinstaller``: the bare name depends on
    # the virtualenv being activated / present on PATH, and could resolve to a
    # different interpreter. PyInstaller embeds the interpreter that runs it, so
    # using ``sys.executable`` guarantees the frozen binary bundles the project
    # interpreter (the one reported by ``mhub config python``).
    # --onefile: Bundles everything into one executable
    build_cmd = [sys.executable, "-m", "PyInstaller", "--onefile", "--name", output_name]

    # Ensure the monitor-runner module is packaged inside the binary.
    # mhub.py / mhub_gui.py import app.monitor.run_monitor inside their
    # ``run-monitor`` dispatch branch to re-execute themselves as a monitor
    # child; declaring it as a hidden import guarantees it is bundled even if
    # static analysis ever misses that conditional import.
    build_cmd.append("--hidden-import=app.monitor.run_monitor")

    if target == "gui":
        build_cmd.extend(GUI_BUILD_OPTIONS)
    else:
        build_cmd.extend(CLI_BUILD_OPTIONS)

    # Platform Specifics
    if sys.platform == "win32":
        print("Detected OS: Windows")
        # build_cmd.append("--noconsole") # Do NOT hide the terminal as that will hode all log lines and causes flashing terminal windows
        if os.path.exists(ICON_FILE):
            build_cmd.append(f"--icon={ICON_FILE}")
    else:
        print(f"Detected OS: {sys.platform} (Linux/Unix)")
        # Linux binaries don't use --noconsole or .ico files in the same way

    build_cmd.append(main_script)

    try:
        subprocess.run(build_cmd, check=True)
        print(f"\nSUCCESS: {output_name} created in /{DIST_DIR}")
    except subprocess.CalledProcessError:
        print("\nERROR: PyInstaller build failed.")

if __name__ == "__main__":
    # Optional target argument: `python build_project.py [cli|gui]`.
    requested_target = resolve_target(sys.argv[1] if len(sys.argv) > 1 else "cli")
    if requested_target not in TARGETS:
        print(
            f"Unknown target '{requested_target}'. "
            f"Choose from: {', '.join(TARGETS)}."
        )
        sys.exit(2)
    build_executable(requested_target)
