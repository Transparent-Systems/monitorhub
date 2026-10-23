import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

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

# Pseudo-target that builds every entry in TARGETS, in this order.
ALL_TARGET = "all"
BUILD_ORDER = ("cli", "gui")
TARGET_CHOICES = (*BUILD_ORDER, ALL_TARGET)

# Files the GUI target bundles; a partial checkout must fail with their names
# rather than PyInstaller's "Unable to find ... when adding binary and data
# files". Globs are checked for at least one match.
GUI_INPUT_FILES = ("README.md", "app_icon_512.png")
GUI_INPUT_GLOBS = ("app/webgui/*.py", "app/webgui/pages/*.py")

USAGE = """\
Build the MonitorHub executables with PyInstaller.

Usage:
    python build_project.py [target]

Targets:
    cli     the command-line binary (mhub / mhub.exe) - the default
    gui     the web GUI binary (mhub-gui / mhub-gui.exe), which also
            carries the whole CLI
    all     both, in the order above

Examples:
    python build_project.py            # cli only
    python build_project.py gui        # the web GUI
    python build_project.py all        # both

PyInstaller must be installed for the interpreter that runs this script
(python -m pip install -r requirements.txt).
"""

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
    # ...but the test-support code is not needed at runtime, and it is the only
    # route to pytest and pygments in the bundle:
    #   * streamlit.testing is Streamlit's own AppTest harness (our AppTest
    #     tests run in the dev environment, never inside the frozen binary);
    #   * pandas._testing imports pytest lazily, inside two helper functions
    #     the GUI never calls (`import pandas` works with pytest blocked);
    #   * pytest's terminal writer imports pygments;
    #   * pyarrow.conftest is a pytest fixture module - the pyarrow hook filters
    #     out pyarrow.tests but not this file.
    # An excluded module is not analysed, so its imports disappear with it, and
    # this wins over --collect-all's hidden imports. Together these drop ~430
    # modules (pygments alone is 5.4 MB of source).
    "--exclude-module=streamlit.testing",
    "--exclude-module=pytest",
    "--exclude-module=pygments",
    "--exclude-module=pyarrow.conftest",
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


def missing_inputs(target: str, main_script: str) -> list[str]:
    """Return the files ``target`` needs that are absent from the checkout.

    Checked before PyInstaller runs, so a partial copy names the missing file
    instead of dying inside PyInstaller with "Unable to find ... when adding
    binary and data files".
    """
    missing = [] if Path(main_script).is_file() else [main_script]
    if target != "gui":
        return missing

    for name in GUI_INPUT_FILES:
        if not Path(name).is_file():
            missing.append(name)
    for pattern in GUI_INPUT_GLOBS:
        if not list(Path().glob(pattern)):
            missing.append(pattern)
    return missing


def pyinstaller_problem() -> str | None:
    """Return an actionable message when PyInstaller is not available.

    The build runs PyInstaller through ``sys.executable``, so it must be
    installed for *that* interpreter. A ``pip install`` that targeted a
    different Python (a bare ``pip`` without the virtualenv active) leaves the
    venv without it, which used to surface as a bare
    "No module named PyInstaller" after a misleading "build failed" message.
    """
    try:
        available = importlib.util.find_spec("PyInstaller") is not None
    except (ImportError, ValueError):
        available = False
    if available:
        return None
    return (
        f"PyInstaller is not installed for {sys.executable}.\n"
        "Install the build dependencies with the same interpreter:\n"
        "    python -m pip install -r requirements.txt"
    )

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

def build_target(target: str) -> int:
    """Build one target; return 0 on success, non-zero on failure."""
    main_script, output_name = TARGETS[target]

    missing = missing_inputs(target, main_script)
    if missing:
        print(
            f"ERROR: cannot build {output_name}: missing {', '.join(missing)}.\n"
            "Build from a complete checkout of the repository.",
            file=sys.stderr,
        )
        return 2

    problem = pyinstaller_problem()
    if problem:
        print(f"ERROR: {problem}", file=sys.stderr)
        return 2

    print(
        f"--- Preparing build for {output_name} (target: {target}) "
        f"with {sys.executable} ---"
    )
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
        return 1
    return 0


def build_executable(target: str = "cli") -> int:
    """Build the ``cli`` (default), ``gui`` or ``all`` target(s).

    Returns the worst exit code of the builds that ran, so a failed build also
    fails the caller - CI used to carry on regardless.
    """
    target = resolve_target(target)
    if target == ALL_TARGET:
        results = [build_target(name) for name in BUILD_ORDER]
        return max(results)
    return build_target(target)


def main(argv: list[str] | None = None) -> int:
    """Build the requested target (default ``cli``); return the exit code."""
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0

    requested = argv[0] if argv else "cli"
    target = resolve_target(requested)

    if target not in TARGET_CHOICES:
        print(
            f"Unknown target '{requested}'. "
            f"Choose from: {', '.join(TARGET_CHOICES)}."
        )
        return 2

    if not argv:
        print(
            "No target given: building the CLI only.\n"
            "For the web GUI use 'python build_project.py gui', "
            "or 'python build_project.py all' for both."
        )

    return build_executable(target)


if __name__ == "__main__":
    sys.exit(main())
