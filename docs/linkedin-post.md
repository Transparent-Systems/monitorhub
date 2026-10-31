# MonitorHub — LinkedIn post

Copy-ready text for announcing a MonitorHub release on LinkedIn. Update the
release tag (`v1.3.0`) if you are announcing a different version. This page is
maintainer-only and excluded from the published manual (see `exclude_docs` in
`mkdocs.yml`).

---

🚀 **MonitorHub v1.3.0 is out — watch your files, react automatically.**

I've just released the latest version of MonitorHub, a lightweight, open-source (MIT) file & folder monitor that runs on both Windows and Linux.

Think of it as a set of Lego bricks: **monitors** consume events, and **profiles** do the work.

**What it does**

🗂️ Watches folders in real time (create, modify, move, delete) or runs on a schedule

☁️ Automatically propagates changed files to cloud storage, FTP/SFTP, WebDAV, a local drive or a shared folder

🔌 Built-in S3 handler — works with AWS S3, Cloudflare R2, Backblaze B2, iDrive E2 and any S3-compatible provider (no rclone needed); everything else is delegated to rclone

⚙️ Runs any command or script in response to events (send an email, block a port, lock a folder, start another monitor…)

🧩 Runs each monitor as a separate process, so monitors stay isolated from one another

🖥️ Two ways to drive it: a full CLI (`mhub`) or a browser-based GUI (`mhub-gui`)

**Why you'd want it**

✅ Set up automated backups, sync and event-driven automation without babysitting a cron job or a sync client

✅ Cloud-agnostic — no vendor lock-in, pick any provider

✅ Self-hosted and lightweight — handlers run on worker threads, so a slow upload never blocks the rest

✅ Simple to start: one binary, a local SQLite config, and you're running

**Download the release**

🔗 GitHub Release: https://github.com/Transparent-Systems/monitorhub/releases/tag/v1.3.0

**Full documentation**

📖 https://transparent-systems.github.io/monitorhub/

Give it a try, star the repo ⭐, and let me know what you'd like to see next!

#OpenSource #DevOps #Automation #Backup #CloudStorage #S3 #Windows #Linux #Python
