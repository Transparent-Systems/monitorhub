# Monitor Hub

![AIP logo](https://aip.transparent.co.nz/wp-content/uploads/2025/06/AIP_grey_transparent_background_github-e1750625832556.png)

## 🚀 Quick Start

  You can configure MonitorHub with just a few commands

  **Initialise the database**:
  MonitorHub stores its configuration (profiles, monitors, and support tables) in a SQLite database.  
  The database is created explicitly, similar to ``git init``:

  ```bash
  mhub database init
  ```

  Next create one or more profiles. Each profile is linked to one or more monitors.
  After configuring a monitor you can start it.
  ```bash
  mhub profile new
  mhub monitor new
  mhub monitor start
  ```

  Stop a monitor with:
  ```bash
  mhub monitor stop
  ```
  
  Examples to get help:
  ```bash
  mhub --help
  mhub database --help
  mhub profile --help
  mhub monitor --help
  ```
  

## How to run MonitorHub

  ### Windows

  Download one or both files from the
  [Releases](https://github.com/Transparent-Systems/monitorhub/releases) page:

  | File | What it is |
  | ---- | ---------- |
  | `mhub-gui-<version>-windows.zip` | The web GUI **and** the full CLI (recommended) |
  | `mhub.exe` | The CLI only — smaller, for servers and scripts |

  **Web GUI**: unzip the archive and run the executable inside it:

  ```powershell
  .\mhub-gui\mhub-gui.exe
  ```

  Your browser opens http://127.0.0.1:8501. Keep the `mhub-gui` folder together:
  the first run creates `conf\`, `data\` and `logs\` inside it, so keep those
  subfolders when you upgrade. Streamlit options work as well:

  ```powershell
  .\mhub-gui\mhub-gui.exe --server.port 9000
  ```

  The GUI binary also carries the whole CLI, so it is the only download you need:

  ```powershell
  .\mhub-gui\mhub-gui.exe database init
  .\mhub-gui\mhub-gui.exe monitor start
  .\mhub-gui\mhub-gui.exe --help
  ```

  Windows SmartScreen may warn that the executable is unrecognised because it is
  not code-signed. Choose **More info → Run anyway**.

  **CLI only**: download `mhub.exe` and run it directly:

  ```powershell
  .\mhub.exe monitor new
  ```

  ### Linux

  Download the binaries you want from the
  [Releases](https://github.com/Transparent-Systems/monitorhub/releases) page and
  make them executable (the executable bit is not kept by the download):

  ```bash
  chmod +x mhub mhub-gui
  ```

  **CLI**:

  ```bash
  ./mhub monitor new
  ```

  **Web GUI** (a single self-contained file that also carries the whole CLI):

  ```bash
  ./mhub-gui                     # opens http://127.0.0.1:8501
  ./mhub-gui --server.port 9000
  ./mhub-gui database init
  ```

  ### Running from Source
    
    **Install Python**: Download from [python.org](https://www.python.org/downloads/).

    **Install Python**: Download from [python.org](https://www.python.org/downloads/).
    
    **Setup Environment**:
    ```bash
    python -m venv .venv
    # Windows:
    ./.venv/Scripts/activate
    # macOS/Linux:
    source .venv/bin/activate
    pip install -r requirements.txt
    ```

  ### Database commands

  **Initialise the database**:
  MonitorHub stores its configuration (profiles, monitors, and support tables) in a SQLite database.  
  The database is created explicitly, similar to ``git init``:

  ```bash
  mhub database init
  ```
  This creates the database schema.
  You can view database information with:

  ```bash
  mhub database info
  ```

  You can check the database schema version (and whether it matches the
  version this application supports) and, when needed, upgrade it in place:

  ```bash
  mhub database version
  mhub database upgrade
  ```

  ``mhub database upgrade`` applies any pending schema migrations without
  touching your data. It refuses to downgrade a database that was created by a
  newer version of MonitorHub.

  You can rebuild the database.
  IMPORTANT: 
    This will override your existing database.
    Make a backup of your database first

  ```bash
  mhub database init --recreate
  ```

  To get a feel for how profiles, monitors, and their mapping look, you can
  optionally load a small set of example data. This creates one example
  monitor, one fake S3 profile, and the mapping between them, using clearly
  fake credentials and paths:

  ```bash
  mhub database sample-data
  ```

  This command is opt-in and only adds the examples once (it is safe to run
  again). Delete the examples with the ``profile delete`` and
  ``monitor delete`` commands.

  d. **Run**:
  ```bash
  mhub monitor start
  ```

### Profiles: remote and command
  1. A remote profile stores the configuration for a remote storage provider, like S3 cloud storage, FTP, Google Drive or Onedrive.  
    If the remote profile is for an S3 compatable storage provider, then you can use the builtin MonitorHub S3 handler.  
    All storage providers can be handled by Rclone.
    Rclone requires the following steps:  
    - Install Rclone for your operation system: Windows or Linux  
    - Optional: create an Rclone profile with ``rclone config``  
    - Optional: import one or more Rclone profiles with ``mhub profile import``  

  2. A command profile stores the configuration for a shell command.  
    For example you can run a command to send a notification, or run a script to block a firewall port.
  
  Create a new remote profile with command:
  ```bash
  mhub profile new  
  ```

  If you have Rclone installed, you can import profiles with command:
  ```bash
  mhub profile import
  ```
  You can pick which profiles to import: enter `0` to import all, enter a
  profile number to add individual profiles one at a time, or press Enter to
  stop (nothing is imported when no profile was selected).

### Getting help
  Getting help about commands available
  ```bash
  mhub --help
  ```
  Getting help about a specific command
  ```bash
  mhub database --help
  mhub monitor --help
  mhub profile --help
  ```

  Checking which Python interpreter is in use and the version the project is
  pinned to:
  ```bash
  mhub config python
  ```

  This reports the runtime Python version and the interpreter path. Inside the
  released `mhub`/`mhub.exe` binary the interpreter is bundled, so the runtime
  version still reports correctly. When run from a source checkout it also reads
  the `.python-version` pin and shows whether the running interpreter matches it.


## More information about Monitor Hub

[Website](https://aip.transparent.co.nz) |
[Documentation](https://aip.transparent.co.nz/monitorhub/) |

MonitorHub has monitors and profiles. A monitor is an event consumer and triggers a handler configured in a profile.   At present we have:
- an instant monitor for file system events
- a scheduled monitor like a backup monitor or restore monitor triggered by timer events

At present we have:
- A remote profile to copy files to a destination in the cloud storage provider, FTP share or local file system
- A command profile to run any command or script on a workstation or server

Examples of cloud storage providers are:

* Microsoft OneDrive
* Google Drive
* Amazon S3
* IDrive E3
* Backblaze B2
* Any S3 compatible cloud storage provider.
* A WEBDAV server
* Any FTP server

S3-compatible providers represent the vast majority of the object storage market.

Examples of scripts to run by a command handler are:
- send a notification to a user
- email a user
- block a port on a firewall
- change all files in a folder to root-only access
- start or stop another monitor. 

### S3Handler

The S3Handler is builtin to MonitorHub.
It handles S3 compatible cloud storage providers, like:
- Amazon S3 (tested)
- Cloudflare R2 (tested)
- Idrive E2 (tested)
- Backblaze B2 (tested)
- Oracle Cloud Object Storage  
- IBM Cloud Object Storage
- Alibaba Cloud OSS
  
The S3Handler is a builtin file handler. It eliminates the need for Rclone when using S3 compatible cloud storage.  
A builtin S3 handler makes it easier to use MonitorHub.
You can import the rclone profiles with command:  
.venv/bin/python mhub.py profile import

The import lets you choose which profiles to bring over: enter `0` to import
all, a profile number to add individual profiles one at a time, or press Enter
to stop.

Over time we will add native handlers for common cloud storage providers and other storage types.  

### Rclone

Rclone is the swiss knife of copying file to and from cloud storage. 
Any remote profile type without a native handler is delegated to a call to Rclone,
which is configured from a MonitorHub profile itself (no `rclone.conf` needed).

### S3 via rclone

Every remote profile records which handler it is routed through in its
`remote_handler` setting, so an S3 profile does not have to use the builtin
S3Handler:

* `remote_handler: s3` - the builtin S3Handler (what `profile new` stores).
* `remote_handler: rclone` - the profile is delegated to rclone.

Use the rclone route when you want rclone's transfer tuning for S3, for example
`transfers`, `chunk_size`, `storage_class` or `object_lock_mode`.

**MonitorHub owns the profile configuration.** An rclone-routed profile does not
need a section in `rclone.conf`: MonitorHub passes the profile's settings to the
rclone process through its environment, and rclone resolves them as the remote:

    RCLONE_CONFIG_MY_REMOTE_TYPE=s3
    RCLONE_CONFIG_MY_REMOTE_PROVIDER=Other
    RCLONE_CONFIG_MY_REMOTE_ENDPOINT=https://example.invalid
    RCLONE_CONFIG_MY_REMOTE_ACCESS_KEY_ID=...
    RCLONE_CONFIG_MY_REMOTE_SECRET_ACCESS_KEY=...

The variables are set per rclone process, so they are local to the transfer that
belongs to that profile: other monitors, other rclone runs and your shell are
unaffected, and secrets never appear on the command line. If an `rclone.conf`
section with the same name exists, the MonitorHub settings win.

An S3 profile stores the provider under rclone's own `provider` key (for example
`AWS` or `IDrive`), so its configuration matches the `rclone.conf` section it
would otherwise need.

Per-profile rclone options live in the profile config as `rclone_options`. They
mirror an `rclone.conf` section: backend properties use their bare rclone name
(the backend is implied by the profile type), while global session flags keep
their own name:

    "rclone_options": {
      "transfers": 8,
      "chunk_size": "16M",
      "upload_concurrency": 8,
      "storage_class": "STANDARD",
      "object_lock_mode": "GOVERNANCE",
      "object_lock_legal_hold_status": "ON",
      "object_lock_retain_until_date": "2030-01-01T00:00:00Z",
      "bucket_object_lock_enabled": true
    }

A backend property becomes `RCLONE_<BACKEND>_<OPTION>` (`no_check_bucket` ->
`RCLONE_S3_NO_CHECK_BUCKET`) and a global flag becomes `RCLONE_<OPTION>`
(`transfers` -> `RCLONE_TRANSFERS`). The `s3_` prefix is accepted but optional;
`profile edit` strips it so the stored name matches `rclone.conf`, and a name
that is already prefixed (`s3_chunk_size`) keeps working because MonitorHub
resolves each option against the installed rclone's flags. Option names are
case-insensitive and accept the flag spelling (`no-check-upload`,
`--ftp-no-check-upload`); `profile edit` normalises them to the lowercase
underscore `rclone.conf` form (and rewrites the profile's existing options on
save), so `no-check-upload`, `NO_CHECK_UPLOAD` and `no_check_upload` all store
`no_check_upload`.

Object lock needs an rclone that supports it (1.7x; check with
`rclone help flags | grep object-lock`). rclone silently ignores options it does
not know, so MonitorHub logs a warning naming any configured option the installed
rclone cannot apply, and `profile edit` rejects an unknown name as it is typed
(the check is skipped when rclone is not installed).

`mhub profile edit` edits every remote profile. An `s3` profile using the
built-in S3Handler keeps its provider/credentials/region wizard, while any
rclone-routed profile -- an imported `ftp`/`sftp`/`drive`/... remote, or an `s3`
profile switched to rclone -- is edited property by property: each backend
option is shown with its current value and pressing Enter keeps it. The
profile's `rclone_options` are entered as `key=value` pairs using the bare
rclone property name (enter `none` to remove them). Switch a profile between the
built-in handler and rclone by
answering the rclone question, or by setting `remote_handler` in the profile
configuration (`mhub profile show` displays it). `mhub profile import` reads
profiles out of `rclone.conf` once; from then on MonitorHub is the source of
truth for their configuration.

A profile name can contain any characters -- rclone itself is happy with dashes
(`s3-test`). The name is only normalised for the environment-variable channel,
which allows letters, digits and underscores, so a profile named `s3-test` is
used as `s3_test` for rclone; the mapping is logged at DEBUG level when the two
differ.

Also note that `transfers` only applies to folder copies (backup and restore); a
single-file instant upload is tuned with `s3_chunk_size` and
`s3_upload_concurrency` instead.

## Features

* mhub CLI
    This is the command-line interface for managing profiles, monitors, configuration, and diagnostics.  
    Call example:  
    mhub monitor start
* A monitor consumes an event and detaches actions to one or more profile handlers
* A profile stores the configuration details of a profile handler
* A remote profile records the handler it is routed through (`remote_handler`: `s3` or `rclone`), so an S3 profile can use the builtin handler or rclone
* A profile category is a superset of profile types, for example remote profiles or command profiles

## Shell Command Handler

MonitorHub can run a shell command in response to events on any monitor
(file system events on instant monitors, or timer events on scheduled
monitors). This makes it useful for a wide range of use cases, such as:

* Triggering an alert (email, SMS, webhook, chat notification)
* Locking down a firewall or revoking access
* Starting an external program or pipeline
* Intrusion detection and ransomware protection responses

Create a **command profile** (profile category `command`, type `event_command`)
and attach it to a monitor. The profile's command runs when the monitor fires a
matching event.

### Placeholders

A command template may contain placeholders that are replaced with event
details before execution:

| Placeholder      | Description                                            |
|------------------|--------------------------------------------------------|
| `{monitor_name}` | Name of the monitor                                    |
| `{profile_name}` | Name of the attached profile                           |
| `{event_name}`   | Event type: `created`, `deleted`, `modified`, `moved`, `closed`, `timer` |
| `{src_path}`     | Absolute source path                                   |

Example:

```bash
notify-send "Testing command of monitor = {monitor_name}, profile = {profile_name}, event = {event_name}, source path = {src_path}"
```

### Safety

* By default a command is executed **without a shell** (`shell=False`) to
  avoid shell injection. Enable shell execution (opt-in) to use pipes,
  redirects, or environment variable expansion.
* Event filtering: restrict the handler to specific events (e.g. only
  `created` and `closed`).
* Cooldown: a global interval (default `0s`) suppresses repeat firings of any
  event within the window. `0s` disables throttling.

Configuration is stored in the command profile's `config` under the keys
`command`, `command_events`, `command_cooldown`, `command_timeout`,
`command_shell`, and `command_max_workers`.

`command_max_workers` bounds the number of command processes that run
concurrently (default `100`, min `1`, max `1000`). When the limit is reached
further commands are queued FIFO and are never dropped.

`command_events` may include `timer` to fire on scheduled (backup/restore)
timer ticks in addition to file system events. For a timer event, the command
fires once per monitor `interval` (with no cooldown by default).


## Why MonitorHub

You can find more information on website [aip.transparent.co.nz/MonitorHub](https://aip.transparent.co.nz/MonitorHub)

Project MonitorHub grew organically over time.
I wanted the solve the many issues I experienced with common Windows desktop solutions.
- Very slow to load initially
- Privacy intrusion
- Issues with backup handling
- Not a real backup
- Vendor lockin
- Up to 100% CPU usage (what was it doing?)
- Tool made PC hang if several explorer windows were open

Initially I used `Rclone`, which is the swiss knife of (cloud) file transfer.
I scheduled an rclone job every few hours and this was just fine for my purposes.  
Until one day I wanted to upload my security videos to the cloud as well.  
It was critical to upload those videos instantly and build a simple PowerShell script to do the job.  
It worked, but it was not scalable. Each time I wanted to monitor another folder I had to copy the script and change the settings.  
The logging was cumersome as well and I needed to run a separate cleanup job for the log files generated.  
The main issue was that PowerShell was running on Windows only.  

Now I had the choice to build a separate application for Linux, or build a generic solution for Windows, Linux and Mac OS.  
To make the application scalable:
- each monitor needed to be a separate process that could be started or stopped individually
- a monitor could handle file events, timer events and futue prrof to handle events
- a pluggable architecture that allowed adding new monitor types and profile types easily

While I was working on the application it gradually became clear to me that on a high level it was a lego box with monitors that consume events and profile handlers that process an event.
The application is scalable and the architecture is scalable as well.
For example adding a webhook monitor only requires one new class WebhookMonitor that registers itself with an ActionHandler. ALl the plumbing is already in place. This makes it simple to expand the application.

## Use cases

Some use cases are:
* Consolidate several cloud storage locations into a single local repository
  you are probably familiar with the following scenario. The family is on a holiday and each mobile phone uploads their photos to a cloud provider.
  When back home you spend hours downloading photos from all family members and copy them to a media server so you can watch the holiday pics on your PC.
  One restore monitor with a profile for each cloud storage handles this automatically for you.
  When you come home all photos and videos are ready to watch on your TV
* Intrusion detection
  Monitor some critical folder and possible honeypot files.
  This could trigger an alarm, like email, SMS message or a Discours event.
  You could trigger a job to instantly block firewall access to the server!
* Ransomware protection
  Backup your files to a versioned cloud provider
  In case of ransomware you can restore a previous file version.

---

## Acknowledgments
This project was developed with the assistance of several AI agents, mainly Deepseek V4 Pro and Google Gemini.  
Later on in the project I used `OpenRouter` which makes it easy to try out different models.

## License
This is free software under the terms of the MIT license included in this package.  
See file: LICENSE


### 👤 Author
John Zoetebier

* Website: [aip.transparent.co.nz](http://aip.transparent.co.nz)
