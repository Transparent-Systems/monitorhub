import os
import shutil
import time
from pathlib import Path

"""
This script contains helper functions to create and delete test data
It is used by other test scripts to create test data and delete test data 
"""


def create_test_data(path: str | Path, files: list[str]) -> Path:
    """
    Create files relative to path.
    Returns the path to the last created file.
    """
    file_path = Path(path)
    for file_name in files:
        file_name = file_name.lstrip("/\\")
        file_path = Path(path) / Path(file_name)
        parent_path = file_path.parent
        if not parent_path.exists():
            parent_path.mkdir(parents=True, exist_ok=True)

        file_path.write_text(f"Test data for {file_path.as_posix()}\n")

    return file_path

def create_big_file(
    path: str,
    filename: str,
    write_duration_seconds: int = 10,
    write_interval_seconds: float = 0.2,
    chunk_size_bytes: int = 1024 * 50,
    ) -> Path:
    """
    Emulates a large file being written incrementally over time.

    The file will be created and written to periodically for `write_duration_seconds`.
    After the duration, the file handle will be closed, simulating file finalization.

    Args:
        path (str): The directory where the file will be created.
        filename (str): The name of the file to create.
        write_duration_seconds (int): How long (in seconds) to continuously write to the file.
        write_interval_seconds (float): How often (in seconds) to write a chunk to the file.
        chunk_size_bytes (int): The size of each data chunk written to the file.
    """
    file_path = os.path.join(path, filename)

    # Ensure the directory exists
    os.makedirs(path, exist_ok=True)

    # print(f"Emulating writing to: {filepath}")
    # print(f"Duration: {write_duration_seconds} seconds")
    # print(f"Write interval: {write_interval_seconds} seconds")
    # print(f"Chunk size: {chunk_size_bytes / 1024:.1f} KB per write")

    start_time = time.time()
    total_bytes_written = 0
    data_chunk = b"A" * chunk_size_bytes  # A simple repeating chunk for consistency

    try:
        # Open the file in binary append mode
        with open(file_path, "ab") as f:
            while (time.time() - start_time) < write_duration_seconds:
                f.write(data_chunk)
                f.flush()  # Ensure data is written to disk/OS buffer immediately
                total_bytes_written += chunk_size_bytes
                # print(
                #     f"  Written {chunk_size_bytes / 1024:.1f} KB. Total: {total_bytes_written / (1024 * 1024):.2f} MB. Current size: {os.path.getsize(file_path) / (1024 * 1024):.2f} MB"
                # )
                time.sleep(write_interval_seconds)

        # print(f"\nFinished writing to {filepath}.")
        # print(f"Total bytes written: {total_bytes_written / (1024 * 1024):.2f} MB")
        # print(f"Final file size: {os.path.getsize(filepath) / (1024 * 1024):.2f} MB")

    except Exception as e:
        print(f"An error occurred during file emulation: {e}")
    finally:
        # The 'with open(...)' block ensures the file is closed automatically
        # print(f"File handle for {filepath} is now closed (if it was opened).")
        # print(
        #     f"Modification time will be updated now by OS (if not already during write close)."
        # )
        # Give a brief moment for OS to fully finalize metadata
        time.sleep(0.1)

    return Path(file_path)

def delete_test_data(path: str | Path, files: list[str]) -> Path:
    """
    Delete files in path
    """
    last_path = Path(path)
    for file_name in files:
        try:
            file_name = file_name.lstrip("/\\")
            file_path = Path(path) / Path(file_name)
            last_path = file_path
            if file_path.exists():
                if file_path.is_file():
                    file_path.unlink()
                else:
                    shutil.rmtree(path=file_path)
        except Exception:
            continue

    return last_path
