# Release Process

Use this checklist to cut a new Fanout Live release.

## 1. Pick the Version

Choose the next semantic version, for example `0.1.1`.

Update the single source of truth:

- `pyproject.toml`: `[project] version`

The package `__version__` and the Makefile's default `FANOUT_LIVE_TAG` are
derived from this value.

Check for any remaining old references:

```bash
rg "0\.1\.0"
```

## 2. Run Local Checks

Run the standard validation suite:

```bash
make check
```

This runs linting, unit tests, Python compilation, and Compose config
validation.

If the release changes Docker behavior, also build the image locally:

```bash
make docker-build IMAGE=ghcr.io/jlips24/fanout-live TAG=0.1.1
```

Replace `0.1.1` with the version you are releasing.

## 3. Understand the GitHub Workflows

The repo has two workflows:

- `.github/workflows/ci.yml`: runs on pushes to `main` or `master`, pull
  requests, and manual dispatch. It checks Python `3.11` and `3.12`, installs
  FFmpeg, runs linting, coverage, compilation, and `docker compose config`.
- `.github/workflows/release.yml`: runs on pushed tags matching `v*.*.*` and
  on manual dispatch. It builds and publishes the Docker image to GitHub
  Container Registry, then creates a GitHub release with generated notes.

The release workflow sets:

```yaml
IMAGE_NAME: ghcr.io/${{ github.repository }}
```

For this repository, that resolves to:

```text
ghcr.io/jlips24/fanout-live
```

That matches `docker-compose.yml`, so pushing `v0.1.1` publishes these tags:

- `ghcr.io/jlips24/fanout-live:0.1.1`
- `ghcr.io/jlips24/fanout-live:0.1`
- `ghcr.io/jlips24/fanout-live:latest`

Prefer releasing by pushing a semver tag. Use manual `workflow_dispatch` only
for reruns or recovery, and confirm it is running against the intended ref
before publishing.

## 4. Smoke Test the Release Candidate

Start the web UI locally and confirm the dashboard loads:

```bash
make run-web
```

Open:

```text
http://localhost:8080
```

At minimum, verify:

- The dashboard loads without browser console errors
- The status endpoint responds at `/api/status`
- Config changes can be saved
- The relay can be started and stopped

For Docker changes, run the built image:

```bash
mkdir -p data
docker run --rm \
  -p 1935:1935 \
  -p 8080:8080 \
  -v "$PWD/data:/config" \
  ghcr.io/jlips24/fanout-live:0.1.1
```

Replace `0.1.1` with the version you are releasing.

## 5. Commit and Tag

Commit the release updates:

```bash
git status
git add pyproject.toml
git commit -m "Release 0.1.1"
```

Create an annotated tag:

```bash
git tag -a v0.1.1 -m "Fanout Live 0.1.1"
```

## 6. Push Git Refs

Push the release commit first:

```bash
git push
```

Wait for the CI workflow to pass on `main` or `master`.

Then push the release tag:

```bash
git push origin v0.1.1
```

Pushing the tag starts the release workflow. Do not manually push the same image
tag unless the GitHub Actions release failed and you have decided to recover
outside the workflow.

## 7. Monitor GitHub Actions

In GitHub Actions, verify:

- The `CI` workflow passed for the release commit
- The `Release` workflow ran for `refs/tags/v0.1.1`
- The `Build and publish container` job completed
- The generated GitHub release exists
- The GHCR package has the `0.1.1`, `0.1`, and `latest` tags

## 8. Verify the Published Image

Pull and run the published tag from a clean local environment or test host:

```bash
docker pull ghcr.io/jlips24/fanout-live:0.1.1
FANOUT_LIVE_TAG=0.1.1 docker compose up -d
docker compose ps
docker compose logs -f
```

Replace `0.1.1` with the version you released.

Confirm the dashboard is reachable and the app reports healthy status.

When finished:

```bash
docker compose down
```

## 9. Review Release Notes

The release workflow creates GitHub release notes automatically. Review them
and edit if needed to include:

- The version number and release date
- User-facing changes
- Upgrade notes or config changes
- Known issues, if any
- The published image tag: `ghcr.io/jlips24/fanout-live:0.1.1`

After publishing the notes, test the README quick-start command with the new
tag.
