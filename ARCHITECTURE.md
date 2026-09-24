# Architecture Overview

## ActionHandler UML Diagram

Below is the automatically generated class hierarchy:

<!-- ACTIONHANDLER_MERMAID_START -->
```mermaid
classDiagram
  class ActionContext {
    dest_path : str | None
    event_type : str
    is_directory : bool
    src_path : str
  }
  class ActionDispatcher {
    handlers : list[ActionHandler]
    queue : Queue
    queue_action(context: ActionContext)
    run()
  }
  class ActionHandler {
    handle_action(context: ActionContext)*
  }
  class CommandActionHandler {
    command : str
    cooldown_seconds : float, int
    events : NoneType
    logger
    max_workers : int
    monitor_name : str
    pending_commands : int
    profile_name : str
    shell : bool
    timeout_seconds : float, int
    handle_action(context: ActionContext)
    stop(wait: bool, cancel_futures: bool) None
  }
  class DebounceManager {
    callback
    condition : Condition
    delay : float
    pending_files : dict[str, float]
    add_event(file_path: str)
    cancel_event(file_path: str)
    run()
  }
  class HandlerFactory {
    get_handler(monitor: dict, profile: dict | None, logger: logging.Logger | None, debounce_delay: float) ActionHandler | None
  }
  class RemoteActionHandler {
    debounce_manager
    logger
    remote_handler
    handle_action(context: ActionContext)
    stop()
  }
  class RemoteHandler {
    CATEGORY : str
    DESCRIPTION : str
    PROFILE_TYPE : str
    exclude_patterns : list[str]
    copy_file(monitor_path: str, remote_path: str | None)* RemoteResult
    copy_folder(monitor_path: str)* RemoteResult
    delete_file(remote_path: str)* RemoteResult
    delete_folder(remote_path: str)* RemoteResult
    file_exists(remote_path: str)* RemoteResult
    get_remote_path(monitor_path: str)* str
    normalize_path(path: str) str
    restore_folder(remote_path: str)* RemoteResult
  }
  class StoppableWorker {
    is_running : bool
    is_stopped : bool
    logger
    name : str
    stop_event : Event
    thread : threading.Thread | None
    run()* None
    start() None
    stop(timeout: float) None
    wait_stop(timeout: float | None) bool
  }
  ActionDispatcher --|> StoppableWorker
  CommandActionHandler --|> ActionHandler
  DebounceManager --|> StoppableWorker
  RemoteActionHandler --|> ActionHandler
  DebounceManager --* RemoteActionHandler : debounce_manager
  ActionHandler --o ActionDispatcher : handlers
  RemoteHandler --o RemoteActionHandler : remote_handler
```
<!-- ACTIONHANDLER_MERMAID_END -->




## Commands UML Diagram

Below is the automatically generated class hierarchy:

<!-- COMMANDS_MERMAID_START -->
```mermaid
classDiagram
  class AppCommands {
    diagnostic_util
    prompt
    config_test() None
    version() None
  }
  class Commands {
    app
    database
    diagnostic_util
    monitor
    profile
    profile_importer
    prompt
    sqlite_handler
  }
  class DatabaseCommands {
    prompt
    sqlite_handler
    info()
    init(recreate: bool)
    sample_data()
    upgrade()
    version()
  }
  class DiagnosticUtil {
    check_app_config_result : bool
    check_app_env_result : bool
    check_profile_import_result : bool
    check_rclone_dependency_result : bool
    logger
    profile_importer
    prompt
    sqlite_handler
    check_app_env() bool
    check_monitor_config(monitor_id: int | None) bool
    check_profile_import(rclone_config_path: Path | None) bool
    check_rclone_dependency() bool
    print_overview()
  }
  class MonitorCommands {
    db_dir : str
    dependency_log_level : str | None
    log_config : str
    log_level : str | None
    logger : Logger
    processes : MonitorProcessManager
    prompt
    selector : MonitorSelector
    sqlite_handler
    delete(monitor_id: int | None, monitor_name: str | None)
    edit(monitor_id: int | None, monitor_name: str | None)
    new()
    show(monitor_id: int | None, monitor_name: str | None)
    start(monitor_id: int | None, monitor_name: str | None)
    stop(monitor_id: int | None, immediate: bool, monitor_name: str | None)
    test(monitor_id: int | None, monitor_name: str | None)
  }
  class ProfileCommands {
    editor : ProfileEditor
    logger : Logger
    profile_importer
    prompt
    selector : ProfileSelector
    sqlite_handler
    delete(profile_id: int | None, profile_name: str | None)
    edit(profile_id: int | None, profile_name: str | None)
    import_profiles()
    new()
    show(profile_id: int | None, profile_name: str | None)
    test(profile_id: int | None, profile_name: str | None, live: bool) bool
  }
  class ProfileImporter {
    logger
    prompt
    selector : ProfileImportSelector
    sqlite_handler
    default_rclone_config_path() Path
    find_importable_profiles(rclone_config_path: Path | None) list[str]
    import_profiles(rclone_config_path: Path | None) list[str]
  }
  class PromptService {
    input(prompt: str) str
    print() None
    prompt_choice(prompt: str) str | None
    prompt_required(prompt: str) str | None
    prompt_yes_no(prompt: str) bool
  }
  class SQLiteHandler {
    connection : sqlite3.Connection
    cursor : sqlite3.Cursor
    db_path
    logger : Logger
    add_monitor(name: str, monitor_path: str, remote_path: str, monitor_type: str, config: dict[str, Any], status: str, pid: int) int | None
    add_monitor_profile_map(monitor_id: int, profile_id: int) bool
    add_profile(name: str, profile_type: str, config: dict[str, Any]) int | None
    apply_pending_migrations() list[str]
    close() None
    create_schema() None
    delete_monitor(monitor_id: int) bool
    delete_monitor_profile_map(monitor_id: int, profile_id: int) bool
    delete_profile(profile_id: int | None, profile_name: str | None) bool
    drop_schema() None
    get_current_schema_version() str
    get_monitor(monitor_id: int | None, monitor_name: str | None) dict[str, Any] | None
    get_monitors() list[dict[str, Any]]
    get_monitors_for_profile(profile_id: int) list[dict[str, Any]]
    get_profile(profile_id: int | None, profile_name: str | None) dict[str, Any] | None
    get_profiles() list[dict[str, Any]]
    get_profiles_for_monitor(monitor_id: int) list[dict[str, Any]]
    get_schema_versions() list[dict[str, Any]]
    is_closed() bool
    is_initialized() bool
    read_cursor(error_message: str | None) Generator[sqlite3.Cursor, None, None]
    transaction(error_message: str | None) Generator[sqlite3.Cursor, None, None]
    update_monitor(monitor_id: int, name: str, monitor_path: str, remote_path: str, monitor_type: str, config: dict[str, Any], status: str, pid: int) int | None
    update_monitor_config(monitor_id: int, config: dict[str, Any]) bool
    update_monitor_last_heartbeat(monitor_id: int, last_heartbeat: str) bool
    update_monitor_last_run(monitor_id: int, last_run: str) bool
    update_monitor_pid(monitor_id: int, pid: int) bool
    update_monitor_status(monitor_id: int, status: str) bool
    update_profile(profile_id: int, name: str, profile_type: str, config: dict[str, Any]) int | None
    update_schema_version(version: str, description: str | None) None
  }
  Commands --> AppCommands : app
  Commands --> DatabaseCommands : database
  Commands --> DiagnosticUtil : diagnostic_util
  Commands --> MonitorCommands : monitor
  Commands --> ProfileCommands : profile
  Commands --> ProfileImporter : profile_importer
  Commands --> PromptService : prompt
  DiagnosticUtil --> PromptService : prompt
  ProfileImporter --> PromptService : prompt
  Commands --> SQLiteHandler : sqlite_handler
  DiagnosticUtil --o AppCommands : diagnostic_util
  ProfileImporter --o DiagnosticUtil : profile_importer
  ProfileImporter --o ProfileCommands : profile_importer
  PromptService --o AppCommands : prompt
  PromptService --o DatabaseCommands : prompt
  PromptService --o MonitorCommands : prompt
  PromptService --o ProfileCommands : prompt
  SQLiteHandler --o DatabaseCommands : sqlite_handler
  SQLiteHandler --o DiagnosticUtil : sqlite_handler
  SQLiteHandler --o MonitorCommands : sqlite_handler
  SQLiteHandler --o ProfileCommands : sqlite_handler
  SQLiteHandler --o ProfileImporter : sqlite_handler
```
<!-- COMMANDS_MERMAID_END -->



