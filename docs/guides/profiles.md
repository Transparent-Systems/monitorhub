# Profiles

A profile is used to configure a remote or command profile.
Each profile is associated with a single handler.
Each profile can be linked to zero, one or more monitors.

The properties of a profile are:

| Property Name | Property Description | Required |
| --- | --- | --- |
| `name` | Unique name identifying the profile | Yes |
| `profile_type` | The type of handler the profile configures, for example `s3` for a remote profile or `event_command` for a command profile | Yes |
| `config` | The settings for that type: provider, credentials, `remote_handler` and optional `rclone_options` for a remote profile, or the command and its options for a command profile | Yes |
| `monitors` | Monitors linked to the profile through `monitor_profile_map` | No — zero, one or more |
| `date_created` | Timestamp the profile was created | Set by MonitorHub |
| `last_modified` | Timestamp the profile was last changed | Set by MonitorHub |

The `name`, `profile_type` and `config` properties are the ones you set when
creating a profile (`mhub profile new` or the web GUI). The remaining properties
are written by MonitorHub while the profile is used and are shown by
`mhub profile show`.

!!! note "Category is derived, not stored"
    A profile's category (`remote` or `command`) is not one of its properties:
    MonitorHub derives it from `profile_type`, which is why the two are
    different things. See [Profile Categories](#profile-categories) below.

!!! note "MonitorHub needs at least one profile"
    The reason is that a monitor requires at least one profile.
    Without a profile the monitor would have no action to do.

## Profile Categories
Please note that a profile category is different from a profile type.
At present there are two profile categories:

- Remote profile
    A remote profile propagates files from and to a remote storage.  
    See: [Remote profiles](remote-profiles.md)
- Command profile
    A command profile handles a command similar to running a command in a shell.  
    See: [Command profiles](command-profiles.md)

