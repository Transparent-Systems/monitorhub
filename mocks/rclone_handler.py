# rclone_handler.py
import subprocess


class RcloneHandler:
    def __init__(self, rclone_path="rclone"):
        self.rclone_path = rclone_path

    def _execute_rclone_command(self, command_parts):
        try:
            full_command = [self.rclone_path] + command_parts
            result = subprocess.run(
                full_command,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            print(f"Rclone command failed: {e}")
            print(f"Stdout: {e.stdout}")
            print(f"Stderr: {e.stderr}")
            raise RuntimeError(f"Rclone command failed: {e.stderr}")
        except FileNotFoundError:
            raise RuntimeError(f"Rclone not found at {self.rclone_path}. Make sure it's in your PATH or specify the correct path.")

    def list_remotes(self):
        """Lists all configured rclone remotes."""
        return self._execute_rclone_command(["listremotes"])

    def copy_file(self, monitor_path, remote_path):
        """Copies a file using rclone."""
        return self._execute_rclone_command(["copy", monitor_path, remote_path])

    def sync_directory(self, monitor_path, remote_path):
        """Syncs a local directory with a remote directory."""
        return self._execute_rclone_command(["sync", monitor_path, remote_path])

    def get_version(self):
        """Gets the rclone version."""
        return self._execute_rclone_command(["version"])

    def is_rclone_installed(self):
        """Checks if rclone is installed and accessible."""
        try:
            self.get_version()
            return True
        except RuntimeError:
            return False