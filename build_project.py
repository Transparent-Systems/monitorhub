import os
import shutil
import subprocess
import sys

# --- Configuration ---
MAIN_SCRIPT = "mhub.py"
APP_NAME = "mhub"
ICON_FILE = "app_icon.ico"
DIST_DIR = "dist"

# The web GUI is built as a *separate* artifact: bundling Streamlit (frontend
# bundle, pandas/pyarrow/altair, ...) would bloat the CLI binary by hundreds of
# megabytes for no benefit to CLI users.
WEBGUI_MAIN_SCRIPT = "mhub_webgui.py"
WEBGUI_APP_NAME = "mhub-webgui"

# Build target -> (PyInstaller entry script, output binary name).
TARGETS = {
    "cli": (MAIN_SCRIPT, APP_NAME),
    "webgui": (WEBGUI_MAIN_SCRIPT, WEBGUI_APP_NAME),
}


def _data_spec(source: str, destination: str) -> str:
    """Build an ``--add-data`` value using this platform's path separator."""
    return f"{source}{os.pathsep}{destination}"


# Extra PyInstaller options for the web GUI target only.
WEBGUI_BUILD_OPTIONS = [
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

def clean_previous_builds():
    """Removes old build and dist folders to ensure a fresh start."""
    for folder in [DIST_DIR, "build"]:
        if os.path.exists(folder):
            print(f"Cleaning {folder}...")
            shutil.rmtree(folder)

def build_executable(target: str = "cli"):
    """Build the ``cli`` (default) or ``webgui`` executable."""
    main_script, output_name = TARGETS[target]

    print(f"--- Preparing build for {output_name} (target: {target}) ---")
    clean_previous_builds()

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
    # mhub.py / mhub_webgui.py import app.monitor.run_monitor inside their
    # ``run-monitor`` dispatch branch to re-execute themselves as a monitor
    # child; declaring it as a hidden import guarantees it is bundled even if
    # static analysis ever misses that conditional import.
    build_cmd.append("--hidden-import=app.monitor.run_monitor")

    if target == "webgui":
        build_cmd.extend(WEBGUI_BUILD_OPTIONS)

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
    # Optional target argument: `python build_project.py [cli|webgui]`.
    requested_target = sys.argv[1] if len(sys.argv) > 1 else "cli"
    if requested_target not in TARGETS:
        print(
            f"Unknown target '{requested_target}'. "
            f"Choose from: {', '.join(TARGETS)}."
        )
        sys.exit(2)
    build_executable(requested_target)
