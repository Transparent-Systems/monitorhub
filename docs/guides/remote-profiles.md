# Remote profiles

A remote profile stores the configuration for a remote storage provider — S3
cloud storage, an FTP or SFTP server, Google Drive, OneDrive, WebDAV or a local
folder. MonitorHub supports two routes to a destination, and every remote profile
records which one it uses.

Create one interactively:

```bash
mhub profile new
```

## Route 1: the built-in S3 handler

The S3 handler is built into MonitorHub and speaks the S3 protocol directly, so
no rclone installation is needed. It works with:

- Amazon S3 (tested)
- Cloudflare R2 (tested)
- IDrive E2 (tested)
- Backblaze B2 (tested)
- Oracle Cloud Object Storage
- IBM Cloud Object Storage
- Alibaba Cloud OSS

S3-compatible providers represent the vast majority of the object storage
market. The handler is selected with `remote_handler: s3`, which is what
`profile new` stores for an S3 profile.

## Route 2: rclone

Any provider without a native handler is delegated to
[rclone](https://rclone.org), the Swiss army knife of cloud transfer. Install
rclone for your operating system first:

```bash
rclone version
```

Then either create a profile interactively (`mhub profile new`) or import the
profiles you already have:

```bash
mhub profile import
```

The import reads an existing `rclone.conf` and lets you choose which profiles to
bring over: enter `0` to import all, enter a profile number to add profiles one at
a time, or press Enter to stop (nothing is imported when no profile was selected).
The import is a one-time copy — from then on MonitorHub is the source of truth for
that profile's configuration.

## Choosing the route per profile

The `remote_handler` setting decides how an S3 profile is executed:

| `remote_handler` | Effect |
| --- | --- |
| `s3` | The built-in S3 handler (what `profile new` stores for an S3 profile) |
| `rclone` | The profile is delegated to rclone |

Switch routes by answering the rclone question during `mhub profile edit`, or by
setting `remote_handler` in the profile configuration. `mhub profile show`
displays the current value. Use the rclone route when you want rclone's transfer
tuning for S3 — for example `transfers`, `chunk_size`, `storage_class` or the
object-lock options.

## MonitorHub owns the configuration

An rclone-routed profile does not need a section in `rclone.conf`: MonitorHub
passes the profile's settings to the rclone process through its environment, and
rclone resolves them as the remote:

```bash
RCLONE_CONFIG_MY_REMOTE_TYPE=s3
RCLONE_CONFIG_MY_REMOTE_PROVIDER=Other
RCLONE_CONFIG_MY_REMOTE_ENDPOINT=https://example.invalid
RCLONE_CONFIG_MY_REMOTE_ACCESS_KEY_ID=...
RCLONE_CONFIG_MY_REMOTE_SECRET_ACCESS_KEY=...
```

The variables are set per rclone process, so they are local to the transfer that
belongs to that profile: other monitors, other rclone runs and your shell are
unaffected, and secrets never appear on the command line. If an `rclone.conf`
section with the same name exists, the MonitorHub settings win.

A profile name may contain any characters — rclone itself is happy with dashes
(`s3-test`). The name is only normalised for the environment-variable channel,
which allows letters, digits and underscores, so a profile named `s3-test` is
used as `s3_test` for rclone; the mapping is logged at DEBUG level when the two
differ.

## rclone options per profile

Per-profile rclone options live in the profile config as `rclone_options`. They
mirror an `rclone.conf` section: backend properties use their bare rclone name
(the backend is implied by the profile type), while global session flags keep
their own name:

```json
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
```

A backend property becomes `RCLONE_<BACKEND>_<OPTION>` (`no_check_bucket` becomes
`RCLONE_S3_NO_CHECK_BUCKET`) and a global flag becomes `RCLONE_<OPTION>`
(`transfers` becomes `RCLONE_TRANSFERS`). The `s3_` prefix is accepted but
optional: `profile edit` strips it so the stored name matches `rclone.conf`, and a
name that is already prefixed (`s3_chunk_size`) keeps working because MonitorHub
resolves each option against the installed rclone's flags. Option names are
case-insensitive and accept the flag spelling (`no-check-upload`,
`--ftp-no-check-upload`); `profile edit` normalises them to the lowercase
underscore `rclone.conf` form and rewrites the profile's existing options on save,
so `no-check-upload`, `NO_CHECK_UPLOAD` and `no_check_upload` all store
`no_check_upload`.

!!! note "Option support depends on your rclone"
    Object lock needs an rclone that supports it (1.7x; check with
    `rclone help flags | grep object-lock`). rclone silently ignores options it
    does not know, so MonitorHub logs a warning naming any configured option the
    installed rclone cannot apply, and `profile edit` rejects an unknown name as
    it is typed (the check is skipped when rclone is not installed).

Also note that `transfers` only applies to folder copies (backup and restore
monitors); a single-file instant upload is tuned with `s3_chunk_size` and
`s3_upload_concurrency` instead.

## Editing and testing

```bash
mhub profile edit          # prompts for the profile
mhub profile show          # shows every profile and its remote_handler
mhub profile test          # dry-run test of a profile
mhub profile test --live   # execute with sample values
```

`mhub profile edit` edits every remote profile. An `s3` profile using the built-in
handler keeps its provider/credentials/region wizard, while an rclone-routed
profile — an imported `ftp`/`sftp`/`drive`/... remote, or an `s3` profile switched
to rclone — is edited property by property: each backend option is shown with its
current value and pressing Enter keeps it. The profile's `rclone_options` are
entered as `key=value` pairs using the bare rclone property name (enter `none` to
remove them).

Next: attach the profile to a monitor in
[Your first monitor](../getting-started/first-monitor.md).
