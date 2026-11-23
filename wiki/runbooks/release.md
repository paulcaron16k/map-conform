---
type: runbook
title: "Release"
description: "Cutting a map-conform release: changelog, tag, the release workflow, PyPI, the GitHub release and the Meltano Hub entry."
resource: .github/workflows/build.yml
tags: [delivery, ci, active]
timestamp: 2026-11-23T18:00:00Z
sources:
  - path: .github/workflows/build.yml
  - path: CHANGELOG.md
  - path: pyproject.toml
  - path: plugin-definition.yml
---

# Release

Parent: [Wiki Index](../index.md) · Related: [CI/CD pipeline](../ci-cd/pipeline.md)

A release is a `v*` tag on `main`. The tag sets the version (hatch-vcs reads it; nothing in
the code holds a version number), and the *Release* workflow (path:.github/workflows/build.yml)
builds, publishes to PyPI and creates the GitHub release. 0.1.0 and 0.2.0 were released this way on
2026-11-23.

## Before the first release (done once)

Held by the repository owner; no token is stored anywhere:

- a PyPI trusted publisher for `map-conform`: this repository, workflow `build.yml`,
  environment `pypi`;
- the repository environment `pypi`;
- the repository variable `PYPI_PUBLISH=true`. With it unset or false, the publish job and
  the GitHub release job are skipped (the build still runs).

## Steps

1. **Choose the version.** Semantic versioning; before 1.0 a minor version may change
   behaviour, and the changelog lists each such change. A fix-only release is a patch.
2. **Date the changelog** on a branch, in a pull request: rename `## [Unreleased]` to
   `## [X.Y.Z] - YYYY-MM-DD` (keep that exact form: the release job finds its notes by the
   `## [X.Y.Z]` heading, and fails if the section is empty). Merge when CI is green.
3. **Tag `main`** at that merge commit, which must have a green CI run (the release workflow
   runs no tests):

   ```bash
   git switch main && git pull
   git tag -a vX.Y.Z -m "map-conform X.Y.Z"
   git push origin vX.Y.Z
   ```

4. **Watch the workflow**: `gh run watch $(gh run list --workflow build.yml --limit 1 --json databaseId --jq '.[0].databaseId')`.
   Build, then *Publish to PyPI* (trusted publishing, with attestations), then *GitHub
   release* (the changelog section as notes, the wheel and sdist attached).
5. **Check the release** in a clean environment:

   ```bash
   uv venv /tmp/mc && uv pip install --python /tmp/mc map-conform==X.Y.Z
   /tmp/mc/bin/map-conform --version
   ```

6. **Meltano Hub.** If the settings or capabilities changed, `plugin-definition.yml` was
   regenerated with them (a test keeps it current); update the entry on Meltano Hub with a
   pull request to `meltano/hub` from it.
7. **Tracking.** Close the release story, and update the [roadmap](../plans/roadmap.md).

## If something goes wrong

- **The build or publish job fails:** nothing reached PyPI. Fix on `main`, delete the tag
  (`git push origin :refs/tags/vX.Y.Z` and `git tag -d vX.Y.Z`), and tag again.
- **A bad version reached PyPI:** a version can never be uploaded twice. Yank it on PyPI if
  it is harmful, and release a patch.
- **The GitHub release job fails** after publishing: rerun that job, or create the release
  by hand with `gh release create vX.Y.Z dist/* --notes-file notes.md`.
