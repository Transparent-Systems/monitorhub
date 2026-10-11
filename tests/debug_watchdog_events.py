import os
import time

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class DebugHandler(FileSystemEventHandler):
    def on_any_event(self, event):
        print(f"Event: {event.event_type} - {event.src_path}")

if __name__ == "__main__":
    path = "tests/temp_watchdog_test"
    os.makedirs(path, exist_ok=True)
    
    event_handler = DebugHandler()
    observer = Observer()
    # Schedule without filter to see EVERYTHING
    observer.schedule(event_handler, path, recursive=False)
    observer.start()
    
    print(f"Monitoring {path}...")
    
    try:
        # Create and write to a file
        file_path = os.path.join(path, "test_file.txt")
        print("Creating and writing to file...")
        with open(file_path, "w") as f:
            f.write("Hello World")
            f.flush()
            os.fsync(f.fileno())
        print("File closed.")
        
        time.sleep(2)
        
    finally:
        observer.stop()
        observer.join()
        # Cleanup
        try:
            os.remove(file_path)
            os.rmdir(path)
        except OSError as e:
            print(f"Error: {e.filename} - {e.strerror}.")

