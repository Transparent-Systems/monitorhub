import configparser
import importlib.util
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from app.cli.process_test_result import ProcessTestResult
from app.cli.prompt_service import PromptService
from app.cli.selectors import ProfileImportSelector
from app.utils import reference_data
from app.utils.sqlite_handler import SQLiteHandler


class DiagnosticUtil:
    """
    Utility class for system diagnostics and configuration checks.
    """

    def __init__(
        self,
        sqlite_handler: SQLiteHandler,
        logger: logging.Logger | None = None,
        prompt: PromptService | None = None,
    ):
        self.logger = logger or logging.getLogger(__name__)

        self.prompt = prompt or PromptService()
        # Interactive import selection is delegated to a focused collaborator.
        self.selector = ProfileImportSelector(prompt=self.prompt)
        self.check_app_env_result = False
        self.check_profile_import_result = False
        self.check_rclone_dependency_result = False
        self.check_app_config_result = False
        self.sqlite_handler = sqlite_handler

    def print_overview(self):
        self.prompt.print("=" *50)
        self.prompt.print("=== Summary environment and configuration test results BEGIN ===")
        self.prompt.print(f"===> App environment test: {'OK' if self.check_app_env_result else 'FAILED'} <===")
        self.prompt.print(f"===> Check import remote profiles: {'OK' if self.check_profile_import_result else 'FAILED'} <===")
        self.prompt.print(f"===> Check rclone dependency: {'OK' if self.check_rclone_dependency_result else 'FAILED'} <===")
        self.prompt.print(f"===> App configuration test: {'OK' if self.check_app_config_result else 'FAILED'} <==")
        self.prompt.print("=== Summary environment and configuration test results END ===")


    def check_profile_import(
        self,
        select: bool = False,
        rclone_config_path: Path | None = None,
    ):
        """
        Check if we can import profiles from rclone.
        Only import profiles not yet present in profiles table.

        When ``select`` is True the user chooses which profiles to import
        (none, all, or individual entries) via :class:`ProfileImportSelector`;
        otherwise the legacy all-or-nothing Y/n confirmation is used, as in
        ``config test``.
        """
        self.check_profile_import_result = True

        rclone_config_path = rclone_config_path or self._default_rclone_config_path()
        parser = self._read_rclone_config(rclone_config_path)
        if parser is None:
            return

        profiles_to_import = self._find_importable_profiles(parser.sections())
        if not profiles_to_import:
            self.prompt.print("No profiles to import")
            return

        if select:
            profiles_to_import = self.selector.select_interactive(profiles_to_import)
            if not profiles_to_import:
                self.prompt.print("No profiles selected")
                return
        elif not self._confirm_profile_import(profiles_to_import):
            self.prompt.print("Profile import cancelled")
            return

        self._import_profiles(parser=parser, profile_names=profiles_to_import)

    @staticmethod
    def _default_rclone_config_path() -> Path:
        """Return the platform-specific default rclone config path."""
        if os.name == "nt":
            return Path(os.environ.get("APPDATA", "")) / "rclone" / "rclone.conf"
        return Path.home() / ".config" / "rclone" / "rclone.conf"

    def _read_rclone_config(self, rclone_config_path: Path) -> configparser.ConfigParser | None:
        """Read the rclone config file, returning None when it has no sections."""
        if not rclone_config_path.is_file():
            self.prompt.print(f"No profiles found in {rclone_config_path}")
            return None

        parser = configparser.ConfigParser()
        parser.read(rclone_config_path, encoding="utf-8")
        if not parser.sections():
            self.prompt.print(f"No profiles found in {rclone_config_path}")
            return None
        return parser

    def _find_importable_profiles(self, rclone_profile_names: list[str]) -> list[str]:
        """Return rclone profile names that are not yet in the profiles table."""
        existing_names = {
            profile.get("name", "") for profile in self.sqlite_handler.get_profiles()
        }
        return [name for name in rclone_profile_names if name not in existing_names]

    def _confirm_profile_import(self, profiles_to_import: list[str]) -> bool:
        """Print the import list and ask the legacy all-or-nothing Y/n question."""
        self.prompt.print("\n")
        self.prompt.print("=" * 60)
        self.prompt.print("Please confirm to import the following profiles from Rclone")
        self.prompt.print("This increases performance and reduces dependencies")
        self.prompt.print("The profiles are:")
        for i, profile_name in enumerate(profiles_to_import, start=1):
            self.prompt.print(f"{i}. {profile_name}")

        self.prompt.print("Ok to import profiles? (Y/n)")
        self.prompt.print("Y: Yes is default value, press Enter to accept")
        self.prompt.print("N: No")
        return self.prompt.prompt_yes_no("Import Rclone profiles (Y/n)\n", default=True)

    def _import_profiles(
        self, parser: configparser.ConfigParser, profile_names: list[str]
    ) -> None:
        """Convert the selected rclone sections into MonitorHub profiles."""
        # Some Rclone attribute names differ from those in MonitorHub.
        config_attribute_map = {
            "provider": "provider_name",
            "access_key_secret": "access_key_secret",
        }
        config_attribute_map_keys = config_attribute_map.keys()

        for profile_name in profile_names:
            rclone_profile = dict(parser[profile_name]) if profile_name in parser else {}
            profile_type = ""
            profile_config = {}
            # Store each attribute with their corresponding name in profile_config
            for key in rclone_profile:
                if key == "type":
                    profile_type = rclone_profile[key]
                elif key in config_attribute_map_keys:
                    profile_config[config_attribute_map[key]] = rclone_profile[key]
                else:
                    profile_config[key] = rclone_profile[key]

            # Add display hints: credentials are informational only and the
            # profile must remain in rclone.conf to keep working.
            config = profile_config
            config["comment"] = reference_data.RCLONE_PROFILE_COMMENT
            config["important"] = reference_data.RCLONE_PROFILE_IMPORTANT
            # Add profile to database
            if self.sqlite_handler.add_profile(
                name=profile_name,
                profile_type=profile_type,
                config=profile_config,
            ):
                self.prompt.print(f"Profile name: {profile_name} imported to profiles")
            else:
                self.prompt.print(f"Profile name: {profile_name} not imported to profiles")

    
    def check_app_env(self) -> bool:
        """
        Checks the environment setup, including Python version, and dependencies.
        Returns True if all checks pass, False otherwise.
        """
        error_count = 0
        self.prompt.print("--- Monitor Hub: Environment Self-Test ---")
        
        # Check Python Version
        self.prompt.print(f"[*] Python Version: {sys.version.split()[0]} - OK")

        # Check for key Python dependencies
        packages = ["watchdog", "yaml", "boto3"]
        missing = []

        for pkg in packages:
            # find_spec returns None if the package isn't installed
            if importlib.util.find_spec(pkg) is None:
                missing.append(pkg)
        
        if missing:
            self.prompt.print(f"[!] ERROR: Missing Python dependency: {', '.join(missing)}")
            self.prompt.print("    Run 'pip install -r requirements.txt' to fix this.")
            error_count += 1
        else:
            self.prompt.print(f"[*] Python dependencies ({', '.join(packages)}) - OK")

        self.check_app_env_result = error_count == 0
        if error_count == 0:
            self.prompt.print("--- Monitor Hub: App Environment Self-Test Completed successfully ---")
        else:
            self.prompt.print(f"--- Monitor Hub: App Environment Self-Test - {error_count} tests failed ---")

        return error_count == 0

    def _check_rclone_exists(self) -> bool:
        """
        Check if Rclone exists and we can get the version
        """

        # Check rclone
        rclone_path = shutil.which("rclone")
        if rclone_path:
            self.prompt.print(f"[*] rclone found at: {rclone_path} - OK")
            try:
                version = subprocess.check_output(["rclone", "version"], text=True).split('\n')[0]
                self.prompt.print(f"    ({version})")
                return True
            except (OSError, subprocess.SubprocessError) as e:
                self.prompt.print("    [!] Warning: Could not execute rclone version.")
                self.prompt.print(f"    Error: {e}")
                return False
        else:
            self.prompt.print("[!] ERROR: 'rclone' not found in system PATH. Please install it from rclone.org.")
            return False

    def check_rclone_dependency(self) -> bool:
        """Check whether any profile depends on rclone, and if so whether it is installed.

        Dependency is derived from the profile's ``profile_type`` (the same
        routing rule used by ``handler_factory``): command profiles and profile
        types with a native handler do not need rclone; every other remote
        profile type is delegated to the rclone CLI. Returns True when no
        rclone-backed profile exists or rclone is available, False otherwise.
        """

        # All profiles should be in monitorhub database now, because:
        # - We either have imported the rclone profiles
        # - Or we have created the profiles manually

        # If there is no profile that depends on rclone, then we set result to True (no failure)
        self.check_rclone_dependency_result = True
        profiles = self.sqlite_handler.get_profiles()
        if not profiles:
            self.logger.error("No profiles in database")
            return True

        for profile in profiles:
            profile_type = profile.get("profile_type", "")
            if not reference_data.is_rclone_profile_type(profile_type):
                continue

            # Check to see if rclone is installed, if not then we have a dependency problem
            if self._check_rclone_exists():
                self.check_rclone_dependency_result = True
                # We need to check rclone dependency once only
                return True

            self.check_rclone_dependency_result = False
            self.logger.error(
                f"Rclone is not installed but is required by profile "
                f"'{profile.get('name')}' (type={profile_type})."
            )
            return False

        return True


    def check_monitor_config(self, monitor_id: int | None = None) -> bool:
        """
        - For each monitor test remote_profiles
        - For each monitor print test results
        - Print overview of all test results

        Returns True if checks for all profiles passed.
        """

        # Get all monitors using SQLiteHandler
        monitors = self.sqlite_handler.get_monitors()
        if not monitors:
            self.logger.error("Failed to get monitors from database")
            return False

        process_test_results : list[ProcessTestResult] = []
        for monitor in monitors:
            current_monitor_id: int = monitor.get("id", 0)
            if monitor_id is not None and current_monitor_id != monitor_id:
                continue

            self.prompt.print(f"Processing monitor: {monitor.get('name')}")

            if not current_monitor_id:
                self.logger.error("Monitor ID is missing or invalid for monitor: %s", current_monitor_id)
                continue
            
            # Get testing_delay
            config = monitor.get("config", {})
            if config and "testing_delay" in config:
                testing_delay = config.get("testing_delay", 1)
            else:
                testing_delay = 1

            process_test_result = self._run_path_checks(
                monitor=monitor,
                check_delay=testing_delay
            )
            process_test_results.append(process_test_result)

        # Print test results of all monitors
        total_success_count = 0
        total_failure_count = 0
        total_duration = 0
        
        for process_test_result in process_test_results:
            total_success_count += process_test_result.success_count
            total_failure_count += process_test_result.failure_count
            total_duration += process_test_result.duration
            self._log_test_result(process_test_result)

        # Print totals over all monitors
        self.prompt.print("===> Total counts for all monitors <===")
        self.prompt.print("==================================================")
        self.prompt.print(f"Total number of tests : {total_success_count + total_failure_count}")
        self.prompt.print(f"Total success count   : {total_success_count}")
        self.prompt.print(f"Total failure count   : {total_failure_count}")
        self.prompt.print(f"Total duration        : {total_duration: .2f} seconds")
        self.prompt.print("===> End total counts for all monitors <===")

        self.check_app_config_result = total_failure_count == 0
        return total_failure_count == 0

    def _run_path_checks(self, monitor: dict[str, Any], check_delay: int = 1) -> ProcessTestResult:
        """
        - Check if monitor path exists
        - Copy temporary file to remote path
        - Delete temporary file from remote path
        """

        # Lazy import: handler_factory pulls in boto3 (via S3Handler), which
        # is only needed to construct handlers when a monitor config is actually
        # exercised (``mhub config test``). Keeping it out of the module top
        # stops plain CLI imports from paying the boto3 import cost.
        from app.monitor.handler_factory import get_remote_handler

        monitor_id = monitor.get("id", 0)
        monitor_path = monitor.get("monitor_path", "")
        remote_path = monitor.get("remote_path", "")

        process_test_result = ProcessTestResult(testsuite_name=monitor.get('name', 'Unknown'))
        self.prompt.print(f"Starting tests for monitor name [{monitor.get('name', '')}] on monitor path [{monitor_path}]...")
        #####################################

        testname = f"Test monitor path exists: {monitor_path}"
        self.prompt.print(testname)
        #####################################
        found = os.path.exists(monitor_path)
        process_test_result.process(test_case_name=testname, test_ok=found, test_output=f"Monitor path {monitor_path} exists: {found}")
        
        # Create a local temporary file with dummy content
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".txt") as tmp_file:
            tmp_file.write("This is a temporary test file for Monitor Hub diagnostics.")

        # Iterate over remote_profiles of this monitor
        profiles = self.sqlite_handler.get_profiles_for_monitor(
            monitor_id=monitor_id
            )

        profile_count = len(profiles)
        self.prompt.print(f"Iterating over {profile_count} remote profiles for monitor: {monitor.get('name', 'Unknown')}")
        for profile in profiles:
            profile_type = profile.get("profile_type", "")
            # Get profile category from profile_type
            profile_category = reference_data.get_profile_category(profile_type)
            if profile_category == reference_data.PROFILE_CATEGORY_COMMAND:
                profile_name = profile.get('name', '')
                self.prompt.print(f"Skipping command profile: {profile_name}")
                self.prompt.print("Test command profile with command: mhub profile test")
                continue

            #####################################
            profile_name = profile.get("name", "")
            testname = f"Testing remote_profile: {profile_name}"
            self.prompt.print(testname)
            #####################################

            remote_handler = get_remote_handler(
                logger=self.logger,
                monitor_path=monitor_path,
                remote_path=remote_path,
                profile=profile,
            )

            if remote_handler is None:
                process_test_result.process(test_case_name=testname, test_ok=False, test_output=f"Could not get remote_handler for remote_profile: {profile_name}")
                continue
            
            monitor_path_file = str(Path(tmp_file.name).resolve())
            self.prompt.print(f"monitor_path_file: {monitor_path_file}")
            # Create a temporary remote file name
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            temp_remote_file_name = f"diagnostic_util_test_{timestamp}.txt"
            remote_path_file = f"{remote_path}/{temp_remote_file_name}"
            self.prompt.print(f"remote_path_file: {remote_path_file}")

            copy_result = remote_handler.copy_file(
                monitor_path=monitor_path_file,
                remote_path=remote_path_file
                )
            process_test_result.process(test_case_name=testname, test_ok=copy_result.ok, test_output=f"Result of copy: {copy_result}")

            # Wait 
            time.sleep(check_delay)
            delete_result = remote_handler.delete_file(
                remote_path=remote_path_file
                )
            process_test_result.process(test_case_name=testname, test_ok=delete_result.ok, test_output=f"Result of delete: {delete_result}")

        # Delete local temporary file
        try:
            # Convert str to Path
            temp_file_path = Path(tmp_file.name)
            if temp_file_path.exists():
                os.unlink(temp_file_path)
        except OSError as e:
            self.logger.warning(f"Failed to delete local temp file {temp_remote_file_name}: {e}")

        return process_test_result


    def _log_test_result(self, process_test_result: ProcessTestResult):
        """
        Helper to log the results of a ProcessTestResult.
        """
        self.prompt.print(f"===> BEGIN: test results for [{process_test_result.testsuite_name}] <===")
        self.prompt.print("==================================================")
        self.prompt.print(f"Number of tests : {process_test_result.success_count + process_test_result.failure_count}")
        self.prompt.print(f"Success count   : {process_test_result.success_count}")
        self.prompt.print(f"Failure count   : {process_test_result.failure_count}")
        self.prompt.print(f"Duration        : {process_test_result.duration: .2f} seconds")
        self.prompt.print("==================================================")
       
        len_test_results = len(process_test_result.test_results)
        max_width = len(str(len_test_results))
        for test_result in process_test_result.test_results:
            test_case_name = test_result.get("test_case_name", "")
            test_step_name = test_result.get("test_step_name", "")
            test_duration = test_result.get("test_duration", 0.0)
            test_counter = test_result.get("test_counter", 0)

            if len(test_step_name) == 0:        
                test_full_name = test_case_name
            else:
                test_full_name = f"{test_case_name} - {test_step_name}"
            
            if test_result.get("test_ok"):
                self.prompt.print(f"success    | {test_counter:>{max_width}} : {test_full_name}")
                self.prompt.print(f"           |      ==> duration: {test_duration: .2f} s")
            else:
                self.prompt.print(f"failure    | {test_counter:>{max_width}} : {test_full_name}")
                self.prompt.print(f"           |      ==> duration: {test_duration: .2f} s")

                for item in test_result.get("test_output", []):
                    self.prompt.print(f"           |      {item}")

        self.prompt.print(f"===> END: test results for [{process_test_result.testsuite_name}] <===")
