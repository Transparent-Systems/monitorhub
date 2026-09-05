# Architecture Overview

## ActionHandler UML Diagram

Below is the automatically generated class hierarchy:

<!-- ACTIONHANDLER_MERMAID_START -->
```mermaid
classDiagram
  class ActionContext {
    action_type : str
    dest_path : str | None
    event_type : str
    is_directory : bool
    src_path : str
  }
  class ActionDispatcher {
    handlers : list[ActionHandler]
    logger
    queue : Queue
    thread : NoneType, Thread
    queue_action(context: ActionContext)
    start()
    stop()
  }
  class ActionHandler {
    handle_action(context: ActionContext)*
  }
  class ActionHandlerFactory {
    get_handler(monitor: dict, profile: dict | None, logger: logging.Logger | None, debounce_delay: float, category: str | None) ActionHandler | None
  }
  class CommandActionHandler {
    command : str
    cooldown_seconds : int, str
    events : NoneType
    logger
    monitor_name : str
    profile_name : str
    shell : bool
    timeout_seconds : int, str
    handle_action(context: ActionContext)
  }
  class DebounceManager {
    callback
    condition : Condition
    delay : float
    logger : Logger
    pending_files : dict[str, float]
    running : bool
    thread : threading.Thread | None
    add_event(file_path: str)
    cancel_event(file_path: str)
    start()
    stop()
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
    copy_file(monitor_path: str, remote_path: str | None)* tuple[int, str]
    copy_folder(monitor_path: str)* tuple[int, str]
    delete_file(remote_path: str)* tuple[int, str]
    delete_folder(remote_path: str)* tuple[int, str]
    file_exists(remote_path: str)* tuple[int, str]
    get_remote_path(monitor_path: str)* str
    normalize_path(path: str) str
    restore_folder(remote_path: str)* tuple[int, str]
  }
  CommandActionHandler --|> ActionHandler
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
    logger : NoneType, RootLogger
    sqlite_handler
    check_app_env() bool
    check_monitor_config(monitor_id: int | None) bool
    check_profile_import()
    check_rclone_dependency() bool
    print_overview()
  }
  class MonitorCommands {
    db_dir : str
    log_config : str
    log_level : str | None
    logger : Logger
    prompt
    sqlite_handler
    delete(monitor_id: int | None, monitor_name: str | None)
    edit()
    new()
    show(monitor_id: int | None, monitor_name: str | None)
    start(monitor_id: int | None, monitor_name: str | None)
    start_all()
    stop(monitor_id: int | None, immediate: bool, monitor_name: str | None)
    stop_all(immediate: bool)
    test(monitor_id: int | None, monitor_name: str | None)
  }
  class ProfileCommands {
    diagnostic_util
    logger : Logger
    prompt
    sqlite_handler
    delete()
    edit()
    import_profiles()
    new()
    show()
    test(profile_id: int | None, live: bool) bool
  }
  class PromptService {
    input(prompt: str) str
    print() None
  }
  class SQLiteHandler {
    connection : _LockedConnection
    cursor : _LockedCursor
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
    get_monitor(monitor_id: int | None, monitor_name: str | None) dict[str, Any]
    get_monitors() list[dict[str, Any]]
    get_monitors_for_profile(profile_id: int) list[dict[str, Any]]
    get_profile(profile_id: int | None, profile_name: str | None) dict[str, Any]
    get_profiles() list[dict[str, Any]]
    get_profiles_for_monitor(monitor_id: int) list[dict[str, Any]]
    get_schema_versions() list[dict[str, Any]]
    is_initialized() bool
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
  Commands --> MonitorCommands : monitor
  Commands --> ProfileCommands : profile
  Commands --> PromptService : prompt
  Commands --> SQLiteHandler : sqlite_handler
  Commands --> DiagnosticUtil : diagnostic_util
  PromptService --o AppCommands : prompt
  PromptService --o DatabaseCommands : prompt
  PromptService --o MonitorCommands : prompt
  PromptService --o ProfileCommands : prompt
  SQLiteHandler --o DatabaseCommands : sqlite_handler
  SQLiteHandler --o MonitorCommands : sqlite_handler
  SQLiteHandler --o ProfileCommands : sqlite_handler
  SQLiteHandler --o DiagnosticUtil : sqlite_handler
  DiagnosticUtil --o AppCommands : diagnostic_util
  DiagnosticUtil --o ProfileCommands : diagnostic_util
```
<!-- COMMANDS_MERMAID_END -->


