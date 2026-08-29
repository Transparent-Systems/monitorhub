
import logging
import os
import sys
import time
from pathlib import Path

from scripts.remote_handler import RemoteHandler
from scripts.rclone_handler import RcloneHandler
from scripts.s3_handler import S3Handler


def main():
    logger = logging.getLogger()
    # logger.setLevel(logging.DEBUG)
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Create console logger
    console_logger = logging.StreamHandler()
    console_logger.setFormatter(formatter)
    logger.addHandler(console_logger)

    # Create file logger
    file_logger = logging.FileHandler("logs/simple_performance_test.log")
    file_logger.setFormatter(formatter)
    logger.addHandler(file_logger)

    s3_handler = S3Handler(
        logger=logger,
        base_monitor_path="data/Source/idrive-cloud-storage/performance-test",
        base_remote_path="test-monitorhub/idrive-cloud-storage/performance-test-s3",
        profile_config="idrive-test"
    )

    rclone_handler = RcloneHandler(
        logger=logger,
        base_monitor_path="data/Source/idrive-cloud-storage/performance-test",
        base_remote_path="test-monitorhub/idrive-cloud-storage/performance-test-rclone",
        profile_name="idrive-test"
    )

    NUMBER_OF_TESTS = 10
    logger.info(f"Simple performance test - number of tests: {NUMBER_OF_TESTS}")
    remote_handlers = [s3_handler, rclone_handler]
    # remote_handlers = [s3_handler]

    for remote_handler in remote_handlers:
        file = "data/Source/idrive-cloud-storage/performance-test/testfile-8kb.txt"
        _test_copy_file_performance(
            logger=logger,
            remote_handler=remote_handler,
            monitor_path=file,
            number_of_tests=NUMBER_OF_TESTS
        )

        file = "data/Source/idrive-cloud-storage/performance-test/testfile-1mb.txt"
        # test_copy_file_performance(
        #     logger=logger,
        #     remote_handler=remote_handler,
        #     monitor_path=file,
        #     number_of_tests=3
        # )


def _test_copy_file_performance(logger: logging.Logger, remote_handler: RemoteHandler, monitor_path: str, number_of_tests: int = 10):
    logger.info("=" * 20)
    base_class_name = remote_handler.__class__.__name__
    logger.info(f"BEGIN: {base_class_name}")

    if not os.path.exists(monitor_path):
        logger.info(f"File {monitor_path} does not exist")
        sys.exit(1)

    now = time.time()
    error_count = 0
    # Create an artificial monitor path that we will use for deriving a new remote path for each iteration
    monitor_path_obj = Path(monitor_path)
    monitor_path_parent = monitor_path_obj.parent
    monitor_path_name = monitor_path_obj.name
    monitor_path_short = monitor_path_name.split('.')[0]
    ext_name = monitor_path_name.split('.')[1]

    for i in range(number_of_tests):
        monitor_path_virtual = f"{monitor_path_parent}/{monitor_path_short}-{i}.{ext_name}"
        # Derive remote_path from virtual monitor path
        remote_path = remote_handler.get_remote_path(monitor_path=monitor_path_virtual)
        logger.info(f"Remote path: {remote_path}")
        (result_code, result_output) = remote_handler.copy_file(monitor_path=monitor_path, remote_path=remote_path)
        if (result_code != 0):
            logger.info(f"Error: {result_output}")
            error_count += 1

    logger.info(f"Error count: {error_count}")
    duration = time.time() - now
    logger.info(f"Duration: {duration:.2f} seconds")
    logger.info(f"END: {base_class_name}")
    logger.info("=" * 20)

if __name__ == "__main__":
    main()

