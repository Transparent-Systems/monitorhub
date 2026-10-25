"""Status messages shared by the web GUI pages.

Kept out of the page scripts because Streamlit executes those as stand-alone
scripts (so their internals cannot be imported), while the wording and the
flash kind are exactly what needs a unit test.
"""

from __future__ import annotations


def start_result_message(
    monitor_name: str,
    monitor_id: int,
    *,
    alive: bool,
    settled: bool,
) -> tuple[str, str]:
    """Return the (flash kind, message) for a finished start attempt.

    ``settled`` is False when the child did not report ``running`` within the
    page's wait. A frozen child unpacks its whole bundle before it can write
    that status (about 10 s on a Windows VM), so an unsettled start is reported
    as a warning instead of implying that it has finished - the page would
    otherwise show a stale 'stopped' status with no explanation.
    """
    if not alive:
        return (
            "error",
            f"Monitor '{monitor_name}' (id={monitor_id}) exited during startup. "
            f"See logs/monitor_{monitor_id}.log.",
        )
    if not settled:
        return (
            "warning",
            f"Monitor '{monitor_name}' (id={monitor_id}) was launched and is "
            "still starting. Its status becomes 'running' as soon as the child "
            "process reports in - press ↻ Refresh to update this page.",
        )
    return "success", f"Monitor '{monitor_name}' (id={monitor_id}) started."
