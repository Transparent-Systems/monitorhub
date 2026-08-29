# emulate_writing_big_file.py

import argparse
import os
import time


def emulate_writing_big_file(
    directory,
    filename,
    write_duration_seconds=10,
    write_interval_seconds=0.5,
    chunk_size_bytes=1024 * 50,
):
    """
    Emulates a large file being written incrementally over time.

    The file will be created and written to periodically for `write_duration_seconds`.
    After the duration, the file handle will be closed, simulating file finalization.

    Args:
        directory (str): The directory where the file will be created.
        filename (str): The name of the file to create.
        filecount (int): The number of fildes to create.
        write_duration_seconds (int): How long (in seconds) to continuously write to the file.
        write_interval_seconds (float): How often (in seconds) to write a chunk to the file.
        chunk_size_bytes (int): The size of each data chunk written to the file.
    """
    filepath = os.path.join(directory, filename)

    # Ensure the directory exists
    os.makedirs(directory, exist_ok=True)

    print(f"Emulating writing to: {filepath}")
    print(f"Duration: {write_duration_seconds} seconds")
    print(f"Write interval: {write_interval_seconds} seconds")
    print(f"Chunk size: {chunk_size_bytes / 1024:.1f} KB per write")

    start_time = time.time()
    total_bytes_written = 0
    data_chunk = b"A" * chunk_size_bytes  # A simple repeating chunk for consistency

    try:
        # Open the file in binary append mode
        with open(filepath, "ab") as f:
            while (time.time() - start_time) < write_duration_seconds:
                f.write(data_chunk)
                f.flush()  # Ensure data is written to disk/OS buffer immediately
                total_bytes_written += chunk_size_bytes
                print(
                    f"  Written {chunk_size_bytes / 1024:.1f} KB. Total: {total_bytes_written / (1024 * 1024):.2f} MB. Current size: {os.path.getsize(filepath) / (1024 * 1024):.2f} MB"
                )
                time.sleep(write_interval_seconds)

        print(f"\nFinished writing to {filepath}.")
        print(f"Total bytes written: {total_bytes_written / (1024 * 1024):.2f} MB")
        print(f"Final file size: {os.path.getsize(filepath) / (1024 * 1024):.2f} MB")

    except Exception as e:
        print(f"An error occurred during file emulation: {e}")
    finally:
        # The 'with open(...)' block ensures the file is closed automatically
        print(f"File handle for {filepath} is now closed (if it was opened).")
        print(
            "Modification time will be updated now by OS (if not already during write close)."
        )
        # Give a brief moment for OS to fully finalize metadata
        time.sleep(0.1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Emulate a large file being written incrementally over time."
    )
    parser.add_argument(
        "-d",
        "--directory",
        type=str,
        default="data/Source/Cloud/Videos/Test1",
        help="The directory where the file will be created (default: test_files)",
    )
    parser.add_argument(
        "-f",
        "--filename",
        type=str,
        default=f"emulated_video_{int(time.time())}.mp4",
        help="The name of the file to create (default: emulated_video_<timestamp>.mp4)",
    )
    parser.add_argument(
        "-l",
        "--filecount",
        type=int,
        default=1,
        help="The number of files to create(default: 1)",
    )
    parser.add_argument(
        "-t",
        "--duration",
        type=int,
        default=5,
        help="How long (in seconds) to continuously write to the file (default: 5)",
    )
    parser.add_argument(
        "-i",
        "--interval",
        type=float,
        default=0.5,
        help="How often (in seconds) to write a chunk to the file (default: 0.5)",
    )
    parser.add_argument(
        "-c",
        "--chunk_size",
        type=int,
        default=1024 * 50,  # 1 KB
        help="The size of each data chunk written to the file in bytes (default: 50KB)",
    )

    args = parser.parse_args()

    for _ in range(args.filecount):
        # fname = f"{os.path.splitext(args.filename)[0]}_{_}{os.path.splitext(args.filename)[1]}"
        fname = f"emulated_video_{_}.mp4"
        emulate_writing_big_file(
            args.directory, fname, args.duration, args.interval, args.chunk_size
        )
