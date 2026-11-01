# Rust Port Assessment

> **Status:** decision record (draft) · **Owner:** John Zoetebier · **Created:** 2026-11-01
>
> **Maintainer-only.** This page is excluded from the published manual via
> `exclude_docs` in `mkdocs.yml`; it is not part of the MonitorHub user manual.

## Purpose

This document records the assessment of porting MonitorHub from Python to Rust.
It covers the motivation, the ground rules the port must respect, a
component-by-component feasibility analysis, the compile-time question, the
risks, a proposed target architecture for the new Rust application (its own
repository), and a phased migration strategy with measurable decision gates.

It is a decision record, not a specification. Its purpose is to make the decision
to port (and how to port) written down, reviewable, and reversible before any
code is written.

## 1. Summary

- MonitorHub is a small (~13,000 lines of Python), I/O-bound orchestration
  application. It is not CPU-bound; its runtime cost is dominated by the three
  external systems it drives: **SQLite**, **S3** (via `boto3`), and **rclone**
  (an external Go binary invoked through `subprocess`).
- The original packaging concern is **resolved**. The `mhub-gui` Windows binary
  used to start slowly because of the size of the frozen bundle; shipping the GUI
  with the **onedir** layout (`build_project.py gui --layout onedir`, see
  `.github/workflows/build-windows.yml`) fixed this. The GUI is now fast on
  Windows as well.
- The build/release workflow is **robust and current**; it is not a reason to
  change anything and does **not** drive this decision.
- Because neither packaging nor the workflow is a live problem, this port is a
  **forward-looking, strategic decision** — not a fix for a current pain point.
- **Positive motivation.** With no defect to fix, the case for porting rests on
  the strategic reasons recorded in §3 ("Reasons to port anyway"): a self-contained
  binary with no Python runtime, faster startup and lower memory, predictable
  performance at scale, a smaller dependency/security surface, and a single
  statically-typed codebase.
- The highest-cost Rust target is the **GUI** (Streamlit plus its data stack). Its
  former payoff (binary performance) is now resolved, so any justification for
  porting it must come from elsewhere.
- **Recommendation:** proceed with a **100% Rust, greenfield** application in its
  **own repository**, developed in parallel with the frozen Python application and
  gated by a short **Phase 0 spike** with measurable success criteria (build time,
  binary size, cold start, edit→rebuild loop).
- **Biggest risks:** `rclone` stays Go (so "one self-contained binary" is not
  achievable without dropping rclone); the GUI rewrite is the 80% of the effort
  with the weakest cost/benefit now; and the port must not stall into a second
  half-finished system.

## 2. Motivation and context

The Streamlit web GUI was built in roughly two days. Getting an acceptable
Windows GUI binary took a further few days, because the frozen bundle
(Streamlit plus its transitive data stack) was large and slow to start.

**This has since been resolved.** Shipping the GUI with the **onedir** layout
(`build_project.py gui --layout onedir`) removed the startup penalty: the GUI is
now fast on Windows as well. The build/release workflow is also robust and
current. Neither packaging nor the workflow is a live problem.

Two facts follow:

1. There is **no current pain point** — not performance, not packaging, and not
   the build workflow — forcing a rewrite. The port is therefore a
   **forward-looking, strategic decision**, and its justification must stand on
   its own merits rather than on fixing a defect.
2. Because nothing is urgent, a port carries the classic full-rewrite risk of
   stalling into a second half-finished system (§10.8). The Phase 0 gates (§13)
   exist to make that outcome cheap to detect and cheap to abandon.

The question this document answers is: *is there a better way, and if we port to
Rust, how do we do it without the complexity of a mixed Python/Rust system?*

## 3. Reasons to port anyway

There is no defect to fix, so the case for porting must rest on its own merits.
The following are legitimate, forward-looking reasons to proceed.

1. **A single, self-contained binary.** A Rust build removes the Python runtime
   from the deliverable: the CLI becomes one static executable, and the GUI no
   longer depends on a frozen interpreter plus a large bundled dependency tree.
   (Caveat: `rclone` remains an external Go binary — see §10.1.)
2. **Faster startup and lower memory.** No interpreter start-up and no importing
   of Streamlit/pandas, with a much smaller resident footprint per monitor
   process — which matters when many monitors run concurrently on a server.
3. **Predictable performance under load.** Rust removes interpreter overhead and
   allocator/GC pauses from the event→action hot path (file events, hashing, S3
   transfers), which helps at high event volumes.
4. **A smaller dependency and security surface.** No bundled CPython, no
   third-party wheel set, no PyInstaller bootstrap: fewer components to patch and
   a smaller attack surface for a tool that watches folders and executes commands.
5. **One language, one codebase.** A single statically-typed codebase with
   compile-time guarantees for the concurrency-heavy monitor engine, instead of
   maintaining Python and Rust side by side.
6. **Longevity.** An explicit, well-defined dependency graph is easier to keep
   building over years than a Python application pinned to a large frozen
   dependency set.
7. **Demonstrated feasibility.** Third-party projects have shown that even large
   applications can be reimplemented in Rust quickly with modern tooling (§5),
   which lowers the perceived risk of a fast first increment.

**Weighing them.** These reasons should be weighed against the costs and risks in
§10. If none of them is compelling on its own, keeping the Python application is a
defensible outcome — the Phase 0 gates (§13) exist to make that call cheap.

## 4. Scope and ground rules

These constraints are deliberate and are the reason the port is structured as a
clean, separate application.

1. **100% Rust.** No hybrid. No PyO3/maturin extension modules, no Rust core
   called from Python, no sidecar invoked by the Python app. The Rust
   application must be complete on its own.
2. **Greenfield, in its own repository.** The Rust application lives in a
   **separate repository**, not inside the `monitorhub` repository and not as a
   set of libraries bolted onto the Python package. It is a standalone
   application with its own history, CI, and release process.
3. **The Python application is frozen.** While the Rust port is in progress the
   Python app receives **maintenance and bug fixes only — no new features**. This
   prevents feature drift between the two codebases.
4. **Parallel workstreams.** Python maintenance and Rust development proceed in
   parallel. The Python app remains the shipping product until the Rust app is
   live.
5. **Reduce complexity, not add it.** The Python application is already complex.
   The port must not introduce a second, entangled system; the boundary between
   the two applications is a repository boundary and (during migration) a shared
   database file, nothing more.

### Tooling isolation

Because the Rust application lives in its own repository, the two toolchains are
naturally isolated: the Python toolchain (Ruff via `make lint`, pytest/unittest
discovery via `make test-unit`, and the PyInstaller specs `mhub.spec` /
`mhub-gui.spec`) and the Cargo toolchain never share a build root. The only
shared artefact during migration is the **SQLite database file** (§11).

## 5. Reality check: "everyone is porting to Rust"

The examples that motivate a Rust port are real, but several are overstated, and
the distinction matters — it changes what a port actually buys us.

| Claim | Reality |
| --- | --- |
| Cloudflare rewrote in Rust | **Real.** **Pingora** (Rust) replaced **NGINX** in Cloudflare's HTTP proxy: ~70% less CPU and ~67% less memory at the same traffic load, serving over 1 trillion requests per day. |
| Part of the Linux kernel was "rewritten" in Rust | **Additive, not a rewrite.** Rust for Linux *adds* new Rust drivers/modules (e.g. the Apple GPU driver). Existing C code is untouched. |
| Google is rewriting applications in Rust | **Partly, at component level.** Rust is used in Android (Keystore, DNS-over-TLS, Bluetooth), Fuchsia, and some Chrome components — not whole applications. |
| Microsoft's suite is in Rust | **Two things.** Microsoft ports *components* officially (e.g. **SymCrypt**, parts of the Windows kernel and Azure services). Separately, **ArtCraft** has released a third-party Rust reimplementation of Office (WordCraft, plus Excel and PowerPoint). |
| Adobe's suite is in Rust | **Third-party.** Adobe uses Rust in *some* components; the full-suite Rust rewrite (PhotoCraft) is an **independent ArtCraft project**, not an official Adobe port. |

**The ArtCraft data point.** ArtCraft (an independent, AI-assisted project) has
released clean-room Rust reimplementations of the Adobe suite and Microsoft
Office — a first public release in roughly **two weeks**, shipping **daily
updates**, exposing an **MCP** interface for automation, and attracting a large
audience. The signal is twofold: it shows that a fast Rust reimplementation of
even large applications is *feasible*, and it shows the caveats — the releases
are early (`v0.1.0`), the author states they are "not anywhere close to ready"
for full parity, and they carry reported piracy and safety concerns. It is
evidence for *speed of porting*, not for production readiness.

**Takeaway.** The proven pattern for *production* is a **scoped rewrite of one
well-bounded, high-value component** (NGINX→Pingora, a crypto library, a kernel
driver) — not "rewrite the whole application". ArtCraft shows a whole-application
rewrite is now *fast to attempt* (with AI assistance), but its early state also
shows that speed of porting is not production readiness. That is compatible with
the intended component-by-component strategy, provided we sequence components by
*value*, not by *ease* (see §7).

## 6. The shape of MonitorHub today

- **Size:** ~13,000 lines of Python under `app/`. Largest modules:
  `app/cli/monitor_commands.py` (~48 KB), `app/webgui/pages/monitors.py` (~40 KB),
  `app/webgui/pages/profiles.py` (~37 KB), `app/cli/profile_editor.py` (~37 KB),
  `app/utils/sqlite_handler.py` (~36 KB), `app/monitor/action_handler.py` (~21 KB),
  `app/monitor/s3_handler.py` (~20 KB), `app/monitor/rclone_handler.py` (~19 KB).
- **Layering:** `app/utils` and `app/monitor` are the backend; `app/cli` is the
  presentation layer, and the backend must not import it
  (`tests/test_import_layering.py` enforces this). `app/webgui` is a second
  presentation layer (Streamlit) over the same backend.
- **External dependencies:** `boto3` (S3), the external `rclone` binary
  (`subprocess`), SQLite (Python stdlib), `watchdog` (file events), `PyYAML`,
  `python-dotenv`, Streamlit (GUI).
- **Concurrency:** `action_handler.py` uses `ThreadPoolExecutor` + `queue.Queue`
  with a `Condition`-based `DebounceManager` and a `StoppableWorker` base;
  `monitor_process_manager.py` launches detached child processes and escalates a
  stop from SIGTERM to SIGKILL.
- **Packaging:** `mhub.spec` (CLI, excludes Streamlit) and `mhub-gui.spec`
  (GUI, `collect_all('streamlit')` + `copy_metadata`). The shipped GUI uses the
  **onedir** layout (`build_project.py gui --layout onedir`), which fixed the
  Windows startup performance. Built by `build_project.py` in
  `.github/workflows/build-windows.yml` and `build-linux.yml`.

**Where the size actually is (and why it no longer hurts).** The GUI bundle is
large because Streamlit drags in pandas, numpy, pyarrow, altair, protobuf, and
pillow. Our own code is small. The **onedir** packaging layout already removes
the startup penalty this size used to cause, so bundle size is no longer a
user-visible problem. It remains relevant only as a *strategic* argument for a
self-contained binary, not as a defect to fix.

## 7. Component-by-component feasibility

| Python component | Rust approach | Effort | Value | Notes |
| --- | --- | --- | --- | --- |
| `app/utils/sqlite_handler.py` | `rusqlite` (bundled SQLite) or `sqlx` | Low | Low–Medium | Clean fit; schema/versioning logic ports directly. But SQLite is already stdlib in Python, so the win is a self-contained binary, not speed. A good *first* component to learn the stack; a weak *business* case. |
| `app/monitor/s3_handler.py` | `object_store` (Apache) or `aws-sdk-s3` | Medium | Medium | `aws-sdk-s3` is heavy (large dependency tree, slow compile, adds megabytes) — potentially contrary to the size goal. `object_store` is lighter and multi-backend. Verify "S3-compatible" provider coverage either way. |
| `app/monitor/rclone_handler.py` | **None — still invoke the `rclone` binary** | Low | **Near zero** | `rclone` is written in Go; there is no Rust reimplementation with comparable provider breadth. The handler is a thin `subprocess` wrapper, so porting it changes nothing about the dependency or the binary size. |
| `app/monitor/action_handler.py` | `tokio`/`rayon` + channels, or std threads + `crossbeam` | Medium–High | Medium | The dispatcher, `ThreadPoolExecutor`, and `Condition`-based debounce map cleanly onto Rust, but this is where `Send`/`Sync` and ownership will demand the most care. A genuine re-architecture, not a transliteration. |
| `app/monitor/monitor_process_manager.py` | `std::process` / `tokio::process` | Medium | Medium | Detached children, liveness checks, and SIGTERM→SIGKILL escalation must be reproduced per platform (Windows vs POSIX). |
| `rclone_env.py`, `s3_factory.py`, `handler_factory.py` | Traits + factory functions | Low | Low | Straightforward; establishes the `RemoteHandler` trait. |
| `app/webgui/` (Streamlit) | `axum`/`actix` + HTMX or Leptos/Yew | **High** | **High** | The **only** component whose port meaningfully shrinks the deliverable, and the hardest to port. This is the 80% of the effort. |
| `app/cli/` | `clap` | Medium | Medium | Command-surface parity with `mhub` is substantial but mechanical; it also defines the acceptance tests. |

**Sequencing note.** The instinct "SQLite → S3 → rclone → …" sequences by *ease*.
This document recommends a middle path: build the core (DB, remote, CLI) first
because it is a prerequisite for everything and is low-risk; do **not** spend
effort on `rclone` beyond keeping the `subprocess` wrapper (it is a thin wrapper
around a Go binary with no Rust alternative); and treat the **GUI as its own
project** with its own cost/benefit. Note that with the packaging problem already
solved (§6), the GUI is now almost pure *cost* — it must be justified on grounds
other than binary size or startup.

## 8. Evaluated alternatives

### 8.1 API-decoupled Streamlit GUI (backend over HTTP)

**The idea.** Instead of the Streamlit pages importing the backend directly (they
currently import `SQLiteHandler`, `S3Factory`, `RcloneHandler`,
`MonitorProcessManager`, …), put the backend behind a local HTTP API and have the
GUI talk to it over that API. The expectation was that this decouples the GUI from
the backend's Python dependencies, shrinking the GUI binary and making the
PyInstaller `onefile` layout feasible.

**What it removes.** The GUI bundles the backend's S3 stack only because it
imports backend modules directly (`app/webgui/pages/profiles.py` imports
`S3Factory`/`RcloneHandler`, and `collect_submodules('app')` pulls in `s3_handler`
→ `boto3` → `botocore`). Moving the backend behind an API removes these from the
GUI bundle. The PyInstaller analysis confirms the split
(`build/mhub-gui/Analysis-00.toc` vs `build/mhub/Analysis-00.toc`):

| Package | In GUI bundle | In CLI bundle | Uncompressed | Origin |
| --- | ---: | ---: | ---: | --- |
| `pyarrow` | 685 | 0 | 166 MB | Streamlit |
| `pandas` | 334 | 0 | 71 MB | Streamlit |
| `numpy` | 178 | 0 | 42 MB | Streamlit |
| `altair` | 63 | 0 | 10 MB | Streamlit |
| `streamlit` | 2496 | ~1 | 35 MB | Streamlit |
| `botocore` | 1994 | 1994 | 27 MB | backend (`boto3`) |
| `boto3` | 56 | 56 | 2 MB | backend (`boto3`) |

The rows present in **both** bundles (`botocore`, `boto3`) are the *backend's*
dependencies, not Streamlit's — they leak into the GUI bundle through direct
imports, and an API decoupling would drop them.

**What it does not remove.** Streamlit's own dependencies — `pyarrow`, `pandas`,
`numpy`, `altair` — are hard requirements of Streamlit and stay regardless of how
the GUI reaches the backend. The GUI also renders dataframes (`st.dataframe`,
`st.data_editor`), which require `pyarrow`. These are the bulk of the binary.

**Why it does not meet the goal.**

- **Size.** Removing `botocore` + `boto3` (~29 MB uncompressed, ~5–8 MB
  compressed — `botocore` is largely compressible JSON) takes the GUI binary from
  ~133 MB to ~125–127 MB: a ~5% reduction, not a transformation. The Streamlit
  stack (~324 MB uncompressed, ~101 MB compressed) remains.
- **`onefile`.** PyInstaller `onefile` extracts the entire bundle to a temporary
  directory on every launch, so startup time scales with bundle size. ~125 MB of
  extraction is still slow; the `onedir` layout is the actual fix for startup and
  is already adopted (§6).
- **Two processes.** Splitting GUI and backend ships the Python runtime and
  standard library twice, so the combined on-disk footprint does not shrink.

**Where it is nonetheless valuable.** The decoupling is a genuine *architectural*
improvement, independent of size: a remote GUI (GUI host ≠ backend host),
multiple/scriptable clients, an automation/**MCP** surface, and a clean separation
that matches the Rust target architecture in §11 (`axum` API + thin frontend). Its
cost is the complexity the port is trying to reduce: a second process, an API
surface, and auth/versioning/lifecycle concerns.

**Verdict.** Not adopted as a *packaging* measure — it does not make the GUI
binary small or `onefile` feasible. The only Python route to a small GUI is to
remove Streamlit itself (a thin HTML/JS frontend), or to ship the CLI only (§6).
The decoupling remains a valid *architecture* choice and is essentially what the
Rust port does by construction.

### 8.2 Streamlit replaced by a lightweight, API-only frontend

**The idea.** Go one step further than 8.1: not only move the backend behind an
API, but replace Streamlit itself with a browser-based frontend that talks to that
API over HTTP/JSON. (Note: React is a frontend *UI library*, not a web framework —
a backend API server is still required.)

**What it removes.** The entire Streamlit dependency closure — the same rows that
dominate the GUI binary today (see the table in 8.1): `pyarrow`, `pandas`,
`numpy`, `altair`, and `streamlit` itself (~324 MB uncompressed, ~101 MB
compressed).

**What it adds.** A lightweight API server and static frontend assets, both small.
The server dependencies are already present (pulled in by Streamlit) and
negligible:

| Component | Size |
| --- | ---: |
| `starlette` | 1 MB |
| `uvicorn` | 1 MB |
| `anyio` | 2 MB |
| `h11` | 1 MB |

Estimated result: a Streamlit-free backend (≈ the CLI's ~32 MB + ~5 MB server + a
few MB of assets) of **~38–40 MB**, against **133 MB** today — and `onefile`
becomes genuinely feasible.

**Packaging.** Two distinct parts:

- The **backend** (API server) is a runnable program and must be packaged — with
  the Streamlit stack gone, PyInstaller `onefile` is now practical.
- The **frontend** is static HTML/JS/CSS, not a program, so it does **not** need
  to be a binary. It can be (a) embedded in the backend binary (`datas` /
  `rust-embed`), (b) shipped as a folder next to the executable, or (c) served
  from source in development. Serving assets from the same origin as the API
  avoids CORS.

**Costs.** Choosing React specifically introduces a JavaScript/TypeScript
codebase, Node.js, npm, and a build step (Vite/webpack) — which contradicts the
"one language" goal (§3) and the "reduce complexity" rule (§4), and the GUI
rewrite is the largest single piece of work (§7). The size win comes from removing
Streamlit, **not** from choosing React.

**Lighter alternatives.** The same size win with far less complexity:

- **HTMX / server-rendered templates** (Jinja2 in Python; Askama/Maud in Rust) —
  no Node, no JavaScript build step.
- **For the Rust port: Leptos or Yew (Rust → WASM)** — keeps the whole
  application in one language, compiles to static assets embedded in the binary,
  and yields a single self-contained executable.

**Verdict.** Correct direction — replacing Streamlit is the only Python route to a
small GUI binary and makes `onefile` feasible. React specifically adds a second
language and toolchain; prefer a lighter frontend, or Leptos/Yew in the Rust port.
This is the "GUI stack" open question (§14).

## 9. The compile-time question

**Concern:** the Rust compiler is slow. Can splitting the application into crates
mitigate this?

### The unit of rebuild

In Cargo, the compilation unit is **one crate, for one target, for one
configuration** — not a file and not a module. Editing one line recompiles the
whole crate plus everything that depends on it.

### Does splitting into crates help?

A 2026 measured experiment built identical code as 1, 3, and 12 crates:

| Variant | Cold build (`-j1`) | Cold build (`-j16`) | Edit-one-module rebuild |
| --- | --- | --- | --- |
| 1 crate | 5.71 s | 5.69 s | 4.97 s |
| 3 crates | 7.28 s | 3.55 s | 2.21 s |
| 12 crates | 14.36 s | 4.13 s (6.7× CPU) | 1.18 s |

Conclusions:

- Splitting **slows full/cold builds** (duplicated monomorphization of generic
  code plus per-crate fixed cost). At `-j1`, 12 crates took ~2.5× as long as 1.
- Splitting **speeds up edit→rebuild**, because Cargo recompiles only the touched
  crate and its dependents.
- The trade is stable and directional: **more crates = slower full builds, faster
  edit builds.** Crates are therefore **not** a general mitigation for slow
  compiles; they help only if the daily loop is edit→build.

### What actually mitigates slow compiles

From the Cargo book's *Optimizing Build Performance*:

1. **Reduce debug info** — `[profile.dev] debug = "line-tables-only"` and
   `[profile.dev.package."*"] debug = false`. A big win on codegen and link time.
2. **Faster linker** — `lld`/`mold` on Linux (`-C link-arg=-fuse-ld=mold`),
   `lld-link` on Windows. Linking often dominates incremental rebuilds.
3. **Cranelift codegen backend** for the dev profile — compiles faster than LLVM;
   worse runtime performance; nightly-only; not all targets. Ideal for fast
   iteration, not for release builds.
4. **Parallel frontend** — `-Zthreads=N` (nightly).
5. **`sccache`** — a shared compilation cache; large wins in CI and across
   worktrees.
6. **`cargo check`** for the inner loop instead of `cargo build` — often several
   times faster; machine code is not needed to check correctness.
7. **Trim the dependency tree** — fewer/unused dependencies mean faster full
   builds. This is where `aws-sdk-s3` hurts.
8. **`cargo build --timings`** — measure before optimizing; find the long pole.
9. **Workspace feature unification** (`resolver.feature-unification = "workspace"`,
   nightly) — avoids rebuilding shared dependencies under differing feature sets.

### Bottom line

A MonitorHub-sized Rust workspace (a handful of small crates) compiles fast
enough: our own code is small, and build time will be dominated by dependencies
(`tokio`, the S3 crate, the web stack), not by our code. With `cargo check` +
Cranelift + `lld`/`mold` + `sccache`, cold builds land in the tens of seconds and
incremental builds in a few seconds. **The crate split is an architectural choice
for edit-loop ergonomics, not a compile-time fix.**

## 10. Risks and concerns

1. **`rclone` stays Go.** The port cannot produce a single self-contained binary
   unless rclone is dropped or its provider scope is reduced. There is no Rust
   replacement with comparable breadth. This is a hard floor on the "one binary"
   goal and should be stated plainly to users.
2. **The S3 crate may fight the size goal.** `aws-sdk-s3` is heavyweight (compile
   time and binary size). Prefer `object_store` unless a specific
   `aws-sdk-s3`-only feature is required; validate S3-compatible provider
   coverage before committing.
3. **The GUI is the 80%.** Streamlit delivered a GUI in two days. Replacing it
   with an `axum` backend plus a frontend (HTMX or Leptos/Yew) is a weeks-long
   effort and reintroduces a browser/JS story. Since the packaging/startup problem
   is already solved (§6), the GUI now has the **weakest cost/benefit of any
   component** — it must be scoped as its own project and justified explicitly,
   not treated as "one more component".
4. **Dual maintenance during the port.** Two codebases, two dependency-update
   streams, two cross-platform build pipelines, two test suites — even with the
   Python app frozen, its dependencies still need security updates.
5. **Test-suite re-implementation.** The Python `unittest` suite is the current
   safety net. A Rust port means re-implementing it (handler tests, the import
   layering test, and the rclone/S3 integration tests). Budget for it explicitly.
6. **Ecosystem churn.** Small but real: `serde_yaml` is deprecated (use a
   maintained fork or another config format); the older `rusoto` S3 crate is
   unmaintained; choosing `tokio` is a pervasive architectural commitment.
7. **Concurrency model shift.** The current design is threads + queues +
   conditions. Rust will push toward `tokio`/`rayon`, which is a re-architecture
   of `action_handler.py` and the monitor engine, not a transliteration.
8. **Rewrite risk.** The classic failure mode of a full rewrite: it stalls, and
   you end up maintaining two half-finished systems. The absence of urgency and
   the frozen-feature rule reduce (but do not remove) this risk; the Phase 0
   gates (§13) exist specifically to prevent sunk-cost escalation.
9. **Skills and onboarding.** Future maintainers must know Rust *and* Python for
   the duration of the migration.
10. **Cross-platform parity.** The current app targets Windows + Linux. The Rust
    app must reproduce process-management and path semantics on both, including
    the Windows SIGTERM/SIGKILL nuance already handled in Python.

## 11. Proposed target architecture (separate repository)

The Rust application is its **own repository** containing a Cargo workspace,
split into small crates. The crate boundaries follow the existing Python layering
so the port is a mapping, not a redesign.

```
<repo root>/
  Cargo.toml                 # workspace root
  rust-toolchain.toml        # pin the toolchain
  .cargo/config.toml         # linker (lld/mold), Cranelift for dev, sccache
  .github/workflows/         # CI for the Rust application (its own pipeline)
  crates/
    monly-core/              # domain types: Monitor, Profile, ActionContext, RemoteResult, errors
    monly-db/                # SQLite: port of sqlite_handler.py (+ schema versioning)
    monly-remote/            # RemoteHandler trait; s3 + rclone implementations
    monly-actions/           # dispatcher, debounce, command handler (port of action_handler.py)
    monly-monitor/           # file watching (notify), scheduling, process management
    monly-cli/               # the `mhub`-equivalent binary
    monly-gui/               # the web GUI (axum + frontend), or an embedded asset server
```

Indicative technology choices (to be confirmed by the Phase 0 spike):

| Concern | Candidate | Rationale |
| --- | --- | --- |
| SQLite | `rusqlite` (bundled) | Closest match to the current synchronous, locked model; bundles SQLite. |
| S3 | `object_store` (preferred) / `aws-sdk-s3` | Lighter dependency tree and binary; multi-backend. |
| rclone | external binary via `std::process` | No viable alternative; keep the wrapper thin. |
| File watching | `notify` | Mature cross-platform watcher; replaces `watchdog`. |
| Async / concurrency | `tokio` (or std threads + `crossbeam`) | Decide in Phase 0; mirrors vs replaces the current thread model. |
| Config / env | `serde` + a maintained YAML crate, `dotenvy` | Replaces `PyYAML` and `python-dotenv`. |
| Logging | `tracing` + `tracing-subscriber` | Structured logging; replaces `logging`/`logger_setup.py`. |
| CLI | `clap` | Command-surface parity with `mhub`. |
| GUI | `axum` + HTMX, or Leptos/Yew | The high-value, high-cost component; its own project. |

**Database compatibility.** During migration both applications read and write the
same SQLite schema. The Rust app must honour the existing schema and the
versioning/migration rules in `app/utils/schema_versioning.py`, so the two can
run against the same database during the parallel-run period.

**Tooling isolation.** The two repositories have independent toolchains (Python
vs Cargo) and independent CI pipelines. The Python package is not part of the
Cargo workspace, and the Rust workspace is not part of the Python build.

## 12. Migration strategy

Development proceeds in phases, each a usable increment. The Python application
remains the shipping product until the final cutover.

- **Phase 0 — Spike and go/no-go.** A throwaway Rust spike that does one real
  thing end-to-end: read the existing MonitorHub SQLite database, and perform an
  S3 `file_exists`/`copy_file` against the credentials in `testdata/.env`.
  Measure build time, binary size, cold start, and the edit→rebuild loop. Gate
  per §13. This is deliberately cheap: it can end the port in one to two weeks
  rather than three months.
- **Phase 1 — Core and read path.** `monly-core`, `monly-db`, `monly-remote`, and
  `monly-cli` covering the read-only commands (`database info`, `profile list`,
  `monitor list`). Establish schema compatibility and the `RemoteHandler` trait.
- **Phase 2 — Monitor engine.** `monly-monitor` and `monly-actions`: file
  watching, the dispatcher, debounce, command handling, and process management.
  This is the highest-risk correctness work (concurrency, process lifecycle).
- **Phase 3 — GUI.** `monly-gui`: the web GUI. Scoped and scheduled as its own
  project; the point at which the binary-size payoff is realised.
- **Phase 4 — Parallel run and cutover.** Run both applications against the same
  database, verify behavioural parity, then make the Rust app the shipping
  product and retire the Python app (or reduce it to a maintenance branch).

## 13. Decision gates and success criteria

The port proceeds only while it passes these gates.

**Phase 0 (spike) gates — all must pass:**

- [ ] Cold `cargo build --release` of the spike completes in an acceptable time
      on a developer machine (record the number).
- [ ] The incremental edit→rebuild loop is acceptable with `cargo check` +
      Cranelift + `lld`/`mold` + `sccache` (record the number).
- [ ] The spike reads the real MonitorHub database schema without modification.
- [ ] Record the release binary size and cold-start time (context, not a
      pass/fail gate — size is a strategic goal, not a current defect).
- [ ] A real S3 operation succeeds against the test credentials.

**Phase gates (per phase):** feature parity for the phase's scope, integration
tests green on Windows and Linux, and no regression in the shared database.

**Go-live criteria (before retiring Python):**

- [ ] CLI command-surface parity with `mhub` (or a documented, accepted subset).
- [ ] Monitor engine behavioural parity (event handling, debounce, actions,
      process lifecycle).
- [ ] GUI feature parity with the Streamlit app.
- [ ] Cross-platform builds green in CI on Windows and Linux.
- [ ] Integration tests (rclone and S3) green.
- [ ] Documented handling of the `rclone` dependency for end users.

## 14. Open questions

- **Repository name:** the Rust application lives in its own repository (decided);
  the name is still open (the `monly` working name is provisional).
- **GUI stack:** `axum` + HTMX vs a Rust/WASM frontend (Leptos/Yew); this choice
  drives most of the GUI cost.
- **S3 crate:** `object_store` vs `aws-sdk-s3` (size vs feature coverage).
- **rclone:** keep it (accept the Go dependency) or reduce provider scope to
  remove it? This decision determines whether "one binary" is achievable.
- **Concurrency model:** async (`tokio`) vs threads (`std` + `crossbeam`) for the
  monitor engine.
- **Target platforms:** confirm Windows + Linux only (any macOS ambition?).
- **Scope of the Python freeze:** confirm "bug fixes only" is sustainable for the
  duration of the port.

## 15. References

- Cloudflare, *Pingora* — Rust HTTP proxy replacing NGINX (~70% less CPU, ~67%
  less memory): <https://www.phoronix.com/news/CloudFlare-Pingora-No-Nginx>
- Cargo book, *Optimizing Build Performance*:
  <https://doc.rust-lang.org/stable/cargo/guide/build-performance.html>
- *The Unit of Rebuild When You Split a Rust Workspace* (crate-splitting
  measurements):
  <https://www.mehdi.cz/blog/the-unit-of-rebuild-when-you-split-a-rust-workspace>
- Rust for Linux (additive Rust support in the kernel):
  <https://rust-for-linux.com/>
- ArtCraft — clean-room Rust reimplementations of the Adobe suite and Microsoft
  Office, with an MCP interface (reported as a ~two-week first release with daily
  updates; early and not yet at parity): <https://github.com/storytold/artcraft> ·
  <https://getartcraft.com/apps>
- Repository sources: `app/utils/sqlite_handler.py`, `app/monitor/s3_handler.py`,
  `app/monitor/rclone_handler.py`, `app/monitor/action_handler.py`,
  `app/monitor/monitor_process_manager.py`, `app/webgui/`, `mhub.spec`,
  `mhub-gui.spec`, `build_project.py`.
