# Release Notes MonitorHub

## v1.0.0 - first release

Initial release of Monitor Hub.
This release has been tested on Windows 11 and Linux (Ubuntu 22.04)

### ⚠️ Prerequisites
When running MonitorHub from source, ensure you have:
1. **Python** installed and configured in your system PATH.


### ⚠️ Dependencies
MonitorHub supports S3 compatible cloud storage providers out of the box.
If you require other storage providers like Google Drive or FTP, then you need to:
- Install Rclone
- Configure rclone for one or more storage providers
- Import Rclone config into MonitorHub with
```bash
mhub profile import
```

It is possible to configure Rclone profiles directly in MonitorHub, but importing an Rclone profile is in most cases the easiest option.
