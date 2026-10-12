# Release procedure (TopoGPU)

1. Finish and test the code changes.
2. Open `pyproject.toml`; change `version = "X.Y.Z"` to the new number (e.g. 2.0.1).
3. GitHub Desktop: commit the change, click **Push origin**.
4. GitHub Desktop: **History** tab → right-click the commit you just pushed → **Create Tag…** → name `vX.Y.Z` (same number, with a leading `v`) → **Create Tag**.
5. Click **Push origin** again (this pushes the tag and starts the build).
6. github.com → **Actions** tab → wait until the `build-wheels` run is green (~30 min).
7. github.com → **Releases** → open `vX.Y.Z` → **Edit** → write the release notes → **Update release**.