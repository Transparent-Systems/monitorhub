import os
import shutil
import subprocess
import sys

# --- Configuration ---
MAIN_SCRIPT = "mhub.py"
APP_NAME = "mhub"
ICON_FILE = "app_icon.ico"
DIST_DIR = "dist"

def get_app_version():
    from version import __version__ as version
    major, minor, build = version
    version = f"{major}.{minor}.{build}"
    return version

def clean_previous_builds():
    """Removes old build and dist folders to ensure a fresh start."""
    for folder in [DIST_DIR, "build"]:
        if os.path.exists(folder):
            print(f"Cleaning {folder}...")
            shutil.rmtree(folder)

def build_executable():
    # On Linux, binaries don't usually have extensions like .exe
    # output_name = f"{APP_NAME}_v{version}"
    output_name = f"{APP_NAME}"
    
    print(f"--- Preparing build for {output_name} ---")
    clean_previous_builds()

    # Base PyInstaller command
    # --onefile: Bundles everything into one executable
    build_cmd = ["pyinstaller", "--onefile", "--name", output_name]

    # Ensure the monitor-runner module is packaged inside the binary.
    # app/monitor/run_monitor.py is a separate entry point reached via a file path
    # (not an import), so PyInstaller's static analysis cannot discover it.
    build_cmd.append("--hidden-import=scripts.run_monitor")

    # Platform Specifics
    if sys.platform == "win32":
        print("Detected OS: Windows")
        # build_cmd.append("--noconsole") # Do NOT hide the terminal as that will hode all log lines and causes flashing terminal windows
        if os.path.exists(ICON_FILE):
            build_cmd.append(f"--icon={ICON_FILE}")
    else:
        print(f"Detected OS: {sys.platform} (Linux/Unix)")
        # Linux binaries don't use --noconsole or .ico files in the same way

    build_cmd.append(MAIN_SCRIPT)

    try:
        subprocess.run(build_cmd, check=True)
        print(f"\nSUCCESS: {output_name} created in /{DIST_DIR}")
    except subprocess.CalledProcessError:
        print("\nERROR: PyInstaller build failed.")

if __name__ == "__main__":
    build_executable()
    