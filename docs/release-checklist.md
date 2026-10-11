# Release Checklist

- [ ] **Update Change Notes**: Ensure `CHANGELOG.md` is updated with the new version number, date, and a summary of changes.
- [ ] **Update Release Log**: Verify that any internal release logs or documentation sites are updated to reflect the new version.
- [ ] **Check dependencies**: Verify that `requirements.txt` is up to date with `pyproject.toml` (regenerate with `uv pip compile pyproject.toml -o requirements.txt`).
- [ ] **Run Tests**: Execute `.venv/bin/python mhub.py config test` to ensure the environment and configuration are valid.
- [ ] **Squash Commits**: Run `git rebase -i main` to combine local commits into a clean history.
- [ ] **Build Executable on Linux**: Run PyInstaller to generate the latest `monitorhub` binary.
        Command: .venv/bin/python build_project.py
- [ ] **Build Executable on Windows**: Run PyInstaller to generate the latest `mhub.exe`.
        Command: .venv/bin/python build_project.py
- [ ] **Add Git Release Tag**: Create a new git tag for the version (e.g., `git tag -a <version> -m "Release <version>"`).
- [ ] **Push to GitHub**: Push the code and the tags to the remote repository (`git push origin <branch> --tags`). 
        If you rebased an existing branch, you may need to force push with `git push --force-with-lease origin <branch> --tags`.
- [ ] **Merge back into main branch**: 
        - Checkout main
        - git merge <branch>
        - delete the branch (`git branch -d <branch>`).
- [ ] **Push main branch to GitHub**: git push origin main.
- [ ] **Create GitHub Release**: 
        - Draft a new release on GitHub
        - Attach the Windows and Linux executables
        - Paste the changelog notes.
