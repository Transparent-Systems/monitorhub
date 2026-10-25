# Architecture

![Monitor Lego Architecture](../assets/images/monitorhub-lego-architecture.jpeg)

MonitorHub is a lego box. Monitors are the bricks that consume events, and
profiles are the bricks that do the work.  
The two are connected by an event dispatcher, and both are stored in a local SQLite database.

## Monitors consume events

A monitor watches a source and converts what happens there into an action:

- An **instant monitor** watches a folder for file system events and reacts
  immediately.
- A **backup monitor** copies the local folder to the destination on a schedule.
- A **restore monitor** copies the destination back to a local folder on a
  schedule.

Each monitor runs as a separate process. That isolation means one monitor cannot
block or crash another, each monitor has its own logging, and each can be started
and stopped individually.

## Profiles do the work

A profile holds the configuration of a handler. One or more profiles are attached
to a monitor:

- A **remote profile** copies files to a cloud storage provider, an FTP/SFTP or
  WebDAV server, or a local folder. S3-compatible storage uses the built-in S3
  handler; other providers are delegated to rclone. The route is recorded per
  profile in `remote_handler`.
- A **command profile** runs a shell command or script in response to events.

A profile category is a superset of profile types: the remote category covers
every storage destination, the command category covers event commands.

## The dispatcher

When a monitor picks up an event — `created`, `modified`, `deleted`, `moved`,
`closed` or `timer` — it hands the event to the event dispatcher. The dispatcher
queues each event and detaches it to the handlers of all attached profiles. Each
handler runs on its own worker thread, so a slow upload or a long-running command
never blocks other events.

## Extensible by design

The architecture is deliberately pluggable. Adding a capability means adding one
brick, not rewiring the box:

- **A new monitor type** is one class implementing the monitor contract,
  registered in the monitor registry. The event loop, dispatcher, profile
  handling, logging and process lifecycle are already in place.
- **A new remote storage provider** is one handler class implementing the remote
  contract (copy, delete, restore) plus one entry in the handler table. The
  profile editor, the CLI, the dispatcher and the runtime pick it up
  automatically.
- **A new event type** can be routed to any mix of handlers through the per
  profile event filters, without code changes.

## Scaling out

There is no architectural limit on the number of instances on a LAN or in the
cloud. A typical multi-hop arrangement: an instance on a server without internet
access uses an instant monitor to transfer changed files over FTP to a second
instance that does have internet access; that second instance runs its own
instant monitor and propagates the files to cloud storage. A scheduled monitor on
the second instance can also watch a heartbeat file and raise an alert when its
timestamp goes stale, which is how server failure detection is built.

## Further reading

The repository's `ARCHITECTURE.md` contains the class diagrams for the action
handler and command layers, generated from the source:

- [ARCHITECTURE.md](https://github.com/Transparent-Systems/monitorhub/blob/main/ARCHITECTURE.md)
- [Monitor process lifecycle notes](https://github.com/Transparent-Systems/monitorhub/blob/main/docs/development_notes.md)
