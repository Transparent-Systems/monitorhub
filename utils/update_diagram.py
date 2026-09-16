"""
Script: update_diagram.py
Description:
    Regenerate a generated Mermaid class diagram block in ARCHITECTURE.md.

    Replaces the earlier bash scripts (update_diagram_actionhandler.sh and
    update_diagram_commands.sh), which required bash, a source'd virtualenv,
    bare ``python3``/``pyreverse`` calls and temporary files in the repository
    root.

    pyreverse is run inside a temporary directory, so no classes.mmd /
    packages.mmd artifacts are left behind. The marked block is written with an
    explicit separator, so regenerating an up-to-date diagram is a no-op.

Usage:
    .venv/bin/python utils/update_diagram.py actionhandler
    .venv/bin/python utils/update_diagram.py commands
    .venv/bin/python utils/update_diagram.py commands --source-path app/cli/commands.py
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET_FILE = "ARCHITECTURE.md"


@dataclass(frozen=True)
class DiagramSpec:
    """Which module to scan and which markdown markers hold its diagram."""

    source_path: str
    start_marker: str
    end_marker: str


# Defaults mirror the previous bash scripts.
DIAGRAMS: dict[str, DiagramSpec] = {
    "actionhandler": DiagramSpec(
        source_path="app/monitor/action_handler.py",
        start_marker="<!-- ACTIONHANDLER_MERMAID_START -->",
        end_marker="<!-- ACTIONHANDLER_MERMAID_END -->",
    ),
    "commands": DiagramSpec(
        source_path="app/cli/commands.py",
        start_marker="<!-- COMMANDS_MERMAID_START -->",
        end_marker="<!-- COMMANDS_MERMAID_END -->",
    ),
}


class DiagramUpdateError(RuntimeError):
    """Raised when a diagram could not be regenerated."""


def find_pyreverse() -> str:
    """Return the pyreverse executable that belongs to the running interpreter."""
    sibling = Path(sys.executable).with_name("pyreverse")
    if sibling.is_file():
        return str(sibling)

    found = shutil.which("pyreverse")
    if found:
        return found

    raise DiagramUpdateError(
        "pyreverse not found. It ships with pylint; install the dev requirements "
        "into the virtualenv first (.venv/bin/pip install -r requirements.txt)."
    )


def generate_diagram(source_path: Path) -> str:
    """Run pyreverse on source_path and return the generated Mermaid diagram."""
    if not source_path.is_file():
        raise DiagramUpdateError(f"Source path does not exist: {source_path}")

    pyreverse = find_pyreverse()

    # pyreverse writes classes.mmd into its working directory: use a temporary
    # one to keep the repository clean, and make the project importable so the
    # scanned module's imports resolve.
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    with tempfile.TemporaryDirectory() as tmp_dir:
        result = subprocess.run(
            [pyreverse, "-o", "mmd", "-a", "1", "-s", "1", str(source_path)],
            cwd=tmp_dir,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        classes_mmd = Path(tmp_dir) / "classes.mmd"
        if result.returncode != 0 or not classes_mmd.is_file():
            output = f"{result.stdout}{result.stderr}".strip()
            raise DiagramUpdateError(
                f"pyreverse failed for {source_path} "
                f"(exit {result.returncode}):\n{output}"
            )
        return classes_mmd.read_text(encoding="utf-8").rstrip("\n")


def build_block(spec: DiagramSpec, diagram: str) -> str:
    """
    Build the fenced markdown block that holds diagram.

    The block deliberately has no trailing newline: everything that followed
    the end marker (blank lines included) is preserved by ``replace_block``,
    which keeps repeated runs idempotent.
    """
    return (
        f"{spec.start_marker}\n"
        "```mermaid\n"
        f"{diagram.rstrip()}\n"
        "```\n"
        f"{spec.end_marker}"
    )


def replace_block(content: str, spec: DiagramSpec, block: str) -> str:
    """Return content with the marked block replaced by block."""
    if spec.start_marker not in content or spec.end_marker not in content:
        raise DiagramUpdateError(
            f"Could not find markers '{spec.start_marker}' and "
            f"'{spec.end_marker}' in the target file."
        )

    prefix = content.split(spec.start_marker, 1)[0]
    suffix = content.split(spec.end_marker, 1)[1]
    return f"{prefix}{block}{suffix}"


def update_diagram(spec: DiagramSpec, source_path: str, target_file: str) -> bool:
    """
    Regenerate spec's diagram inside target_file.

    :return: True when the file changed, False when it was already up to date.
    """
    source = (REPO_ROOT / source_path).resolve()
    target = (REPO_ROOT / target_file).resolve()

    print(f"Scanning '{source}' with pyreverse...")
    block = build_block(spec, generate_diagram(source))

    with open(target, encoding="utf-8", newline="") as handle:
        content = handle.read()

    updated = replace_block(content, spec, block)
    if updated == content:
        print(f"{target} is already up to date.")
        return False

    with open(target, "w", encoding="utf-8", newline="") as handle:
        handle.write(updated)

    print(f"Successfully updated {target}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate a generated Mermaid class diagram block.",
        epilog=(
            "Per-diagram defaults: "
            + ", ".join(
                f"{name}={spec.source_path}" for name, spec in sorted(DIAGRAMS.items())
            )
        ),
    )
    parser.add_argument(
        "diagram",
        choices=sorted(DIAGRAMS),
        help="Which diagram to regenerate",
    )
    parser.add_argument(
        "--source-path",
        default=None,
        metavar="<PATH>",
        help="Module to scan (default: the module for the chosen diagram)",
    )
    parser.add_argument(
        "--target-file",
        default=DEFAULT_TARGET_FILE,
        metavar="<PATH>",
        help=f"Markdown file to update (default: {DEFAULT_TARGET_FILE})",
    )
    args = parser.parse_args(argv)

    spec = DIAGRAMS[args.diagram]
    try:
        update_diagram(spec, args.source_path or spec.source_path, args.target_file)
    except DiagramUpdateError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

