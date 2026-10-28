# Release Checklist

- [ ] **Update Change Notes**: Ensure `CHANGELOG.md` has a section for the new version in the form `## [<version>] - <date>` (e.g. `## [1.2.0] - 2026-10-26`) followed by a summary of changes. The release workflows extract this section verbatim as the GitHub Release body, and a build fails when the section is missing.
- [ ] **Update Release Log**: Verify that any internal release logs or documentation sites are updated to reflect the new version.
- [ ] **Check dependencies**: Verify that `requirements.txt` is up to date with `pyproject.toml` (regenerate with `uv pip compile pyproject.toml --universal -o requirements.txt`; `--universal` keeps the platform-specific entries such as PyInstaller's `pefile` on Windows and `macholib` on macOS).
- [ ] **Run Tests**: Execute `.venv/bin/python mhub.py config test` to ensure the environment and configuration are valid.
- [ ] **Build Executables on Linux** (optional - the tag push below builds them in CI): the CLI and the web GUI, both onefile.
        Command: `.venv/bin/python build_project.py cli` then `.venv/bin/python build_project.py gui`
        Artefacts: `dist/mhub`, `dist/mhub-gui`
- [ ] **Build Executables on Windows** (optional - the tag push below builds them in CI): the CLI as onefile and the web GUI as onedir (a folder, which is fast to start).
        Command: `.venv/bin/python build_project.py cli` then `.venv/bin/python build_project.py gui --layout onedir`
        Artefacts: `dist/mhub.exe`, and the `dist/mhub-gui` folder to be zipped as `mhub-gui-<version>-windows.zip`
- [ ] **Merge the feature branch into main as one squashed commit**:
        - git switch main
        - git pull origin main
        - git merge --squash <branch>
        - git commit -m "<summary of the release>"
        - git push origin main
        `git merge --squash` stages the complete branch diff as a single commit: it replaces
        `git rebase -i main` and produces one clean commit on main without rewriting the branch
        history, so no force push is needed. Resolve any conflicts before committing.
        Pushing the feature branch is optional now (only for a pull request or a backup copy).
        If the branch has an open pull request, the squash creates a new commit SHA, so GitHub
        does not mark the PR as merged: close it with `gh pr close <branch>`.
- [ ] **Delete the feature branch**: `git branch -D <branch>`.
        Use `-D`, not `-d`: a squashed branch is not recorded as merged. Delete the remote copy
        too if it was pushed (`git push origin --delete <branch>`).
- [ ] **Add Git Release Tag**: Create the tag on main, after the squash merge, so it points at the released commit (e.g., `git tag -a <version> -m "Release <version>"`).
- [ ] **Push the tag**: `git push origin <version>`.
        This triggers the "Build Linux binary" and "Build Windows binary" workflows, which build
        the binaries and attach them to the GitHub Release for that tag.
- [ ] **Check the GitHub Release**:
        - The tag push creates the release and fills its body from the matching
          `CHANGELOG.md` section (`utils/release_notes.py`, consumed via `body_path`).
          There is nothing to paste: if the body looks wrong, fix `CHANGELOG.md`
          and edit the release.
        - The Windows and Linux executables and their SHA256 checksums are attached by the workflows.
        - A build fails when the tag, `version.py` and the changelog disagree, so a
          mis-tagged release cannot publish the wrong notes.
