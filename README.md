# Monitor Hub

![AIP logo](https://aip.transparent.co.nz/wp-content/uploads/2025/06/AIP_grey_transparent_background_github-e1750625832556.png)

## 🚀 Quick Start

1. **Run MonitorHub**:

    *Option A: On Windows run executable mhub.exe*
    Download mhub.exe from GitHub. You can find the exe file under Releases.

    ```cmd
    Example:
    mhub.exe monitor new
    ```
    *Option B: On Linux run binary mhub*
    Download mhub.exe from GitHub. You can find the binary file under Releases.

    ```cmd
    Example:
    mhub monitor new
    ```

    *Option C: Running from Source*
    
    a. **Install Python**: Download from [python.org](https://www.python.org/downloads/).
    
    b. **Setup Environment**:
    ```bash
    python -m venv .venv
    # Windows:
    ./.venv/Scripts/activate
    # macOS/Linux:
    source .venv/bin/activate
    
    pip install -r requirements.txt
    ```

    c. **Initialise the database**:

    MonitorHub stores its configuration (profiles, monitors, and support tables) in a SQLite database.  
    The database is created explicitly, similar to ``git init``:

    ```bash
    mhub database init
    ```

    This creates the database schema and loads some tables.  
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

2 **Setup remote profiles**
  Create a new remote profile with command:
  ```bash
  mhub profile new  
  ```

  If you have already Rclone installed, you can import profiles with command:
  ```bash
  mhub profile import
  ```
  You can pick which profiles to import: enter `0` to import all, enter a
  profile number to add individual profiles one at a time, or press Enter to
  stop (nothing is imported when no profile was selected).

3 **Getting help**
  Getting help about commands available
  ```bash
  mhub --help
  ```
  Getting help about a specifi command
  ```bash
  mhub database --help
  mhub monitor --help
  mhub profile --help
  ```


## Monitor Hub

[Website](https://aip.transparent.co.nz) |
[Documentation](https://aip.transparent.co.nz/monitorhub/) |

MonitorHub monitors a folder and files in it for changes and propagates folders and files a target destination.  
The target destination can be a cloud storage provider, FTP server, local drive or shared folder.  
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
python mhub.py profile import

The import lets you choose which profiles to bring over: enter `0` to import
all, a profile number to add individual profiles one at a time, or press Enter
to stop.

Over time we will add native handlers for common cloud storage providers and other storage types.  

### Rclone

Rclone is the swiss knife of copying file to and from cloud storage. 
Any remote profile type without a native handler is delegated to a call to Rclone.


## Acknowledgments

This project was developed with the assistance of several AI agents, mainly Deepseek V4 Pro and Google Gemini.
Later on in the project I started using OpenRouter which makes it easy to try out different models.


## Features

* mhub CLI
    This is the command-line interface for managing profiles, monitors, configuration, and diagnostics.  
    Call example:  
    mhub monitor start
* A monitor consumes an event and detaches actions to one or more profile handlers
* A profile stores the configuration details of a profile handler
* A profile type is linked to a sepcific handler
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


## License

This is free software under the terms of the MIT license included in this package.  
See file: LICENSE

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

Initially I used rclone, which is the swiss knife of (cloud) file transfer.
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

While I was working on the application it gradually became clear to me that on a high level it was a lego box with monitors that consime events and profile handlers that process an event.
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

### 👤 Author

John Zoetebier

* Website: [aip.transparent.co.nz](http://aip.transparent.co.nz)
