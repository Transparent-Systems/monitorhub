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
    mhub monitor start-all
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
This makes it much easier to use MonitorHub without having to depend on Rclone.  
For small files the S3Handler is between 2 - 3 times as fast as rclone.  
For files of about 1Mb the data transfer is a fraction faster.  
MonitorHub will use S3Handler if the remote profile is in monitorhub.conf  
You can import the rclone S3 profiles with command:  
python mhub.py profile import

Any remote profile not in monitorhub.conf will use Rclone.

Over time we will add native handlers for common cloud storage providers and other storage types.  
This will reduce dependency on Rclone, and simplifies deployment and configuration. 

### Rclone

Rclone is the swiss knife of copying file to and from cloud storage.
Any remote profile not in monitorhub.conf will use Rclone.


## Acknowledgments

This project was developed with the assistance of Google Gemini.
We used Gemini Code Assist in VS Code for development.
The code suggestions and quality are excellent.

## Features

* mhub.py  
    This is the command-line interface for managing profiles, monitors, configuration, and diagnostics.  
    Call example:  
    python mhub.py monitor start-all
* YAML configuration file
    The YAML configuration file, default ./conf/config.yaml, contains settings for logging and one or more monitors
* Decoupled architecture where file system events are decoupled from the processing of events
* Events are processed by an ActionHandler, currently BaseActionHandler, that runs in a separate thread
* Shell command handler
    A shell command can be linked to any monitor. When a matching file event
    occurs, the command is executed on its own thread so monitoring never
    blocks.

## Shell Command Handler

MonitorHub can run a shell command in response to file events on any
monitor. This makes it useful for a wide range of use cases, such as:

* Triggering an alert (email, SMS, webhook, chat notification)
* Locking down a firewall or revoking access
* Starting an external program or pipeline
* Intrusion detection and ransomware protection responses

When creating or editing a monitor, answer **y** to "Attach a shell command to
this monitor?" to configure a command.

### Placeholders

The command template may contain placeholders that are replaced with event
details before execution:

| Placeholder    | Description                                            |
|----------------|--------------------------------------------------------|
| `{action_type}` | Event type: `created`, `deleted`, `modified`, `moved`, `closed` |
| `{src_path}`    | Absolute source path                                   |
| `{dest_path}`   | Destination path (moved events only, empty otherwise)  |
| `{is_directory}`| `true` or `false`                                      |

Example:

```bash
notify-send "File {action_type}" "{src_path}"
```

### Safety

* By default the command is executed **without a shell** (`shell=False`) to
  avoid shell injection. Enable shell execution (opt-in) to use pipes,
  redirects, or environment variable expansion.
* Event filtering: restrict the handler to specific events (e.g. only
  `created` and `closed`).
* Cooldown: a per-event interval (default `60m`) suppresses repeat firings of
  the same event type within the window.

Configuration is stored in the monitor's `config` under the keys `command`,
`command_events`, `command_cooldown`, and `command_shell`.


## License

This is free software under the terms of the MIT license included in this package.  
See file: LICENSE

## Why MonitorHub

You can find more information on website [aip.transparent.co.nz/MonitorHub](https://aip.transparent.co.nz/MonitorHub)

Project MonitorHub grew organically over time.  
All tools I used had some problem, like no real backup, cloud provider locking, hard to debug, huge CPU usage (let me guess ...)  
Initially I used OneDrive to "backup" files to the OneDrive cloud storage.  
However with several file explorers running simulteneously the PC became unresponsive.  
OneDrive was frequently using 100% CPU making working on the PC impossible.  
This was a deal breaker to me, I uninstalled OneDrive and decided to use rclone for copying files to the cloud.  

Rclone worked better than OneDrive and unobtrusive in the background.  
I scheduled an rclone job every few hours and this was just fine for my purposes.  
Until one day I wanted to upload my security videos to the cloud as well.  
It was critical to upload those videos instantly and build a simple PowerShell script to do the job.  
It worked, but it was not scalable. Each time I wanted to monitor another folder I had to copy the script and change the settings.  
The logging was cumersome as well and I needed to run a separate cleanup job for the log files generated.  
The main issue was that PowerShell was running on Windows only.  

Now I had the choice to build a separate application for Linux, or build a generic solution for Windows, Linux and Mac OS.  
This is when MonitorHub was born.  
While I had little experience with Python, it has proven to be a great choice.  
VS Code has fantastic support for Python development like code completion and debugging.  
I added the Gemini Code Assist extension. Gemini worked just great.  

## Future development

Some new features could include:

* Intrusion detection
  This could trigger an alarm, like email, SMS message or a Discours event.
* Ransomware protection
  This could trigger an alarm, like email, SMS message or a Discours event.
* Develop a GUI to create a configuration file, test a configuration and start a monitor

---

### 👤 Author

John Zoetebier

* Website: [aip.transparent.co.nz](http://aip.transparent.co.nz)
