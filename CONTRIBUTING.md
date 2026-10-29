# Contributing

This community integration is licensed under the MIT license. Please report problems using GitHub Issues. Include Home Assistant and integration versions and describe the expected and observed behavior. Redact controller addresses, usernames, passwords, tokens, session cookies, and installation-specific IDs from logs and captures.

## Local validation

Use Python 3.14 for the full test suite:

```sh
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
python3 -m compileall -q custom_components
```

Run Home Assistant's official Hassfest container from the repository root:

```sh
docker run --rm -v "$PWD:/github/workspace" ghcr.io/home-assistant/hassfest:latest
```

On ARM hosts, the current Hassfest image may require Docker's `--platform linux/amd64` option.

The active `.github/workflows/validate.yml` workflow runs tests, Hassfest, and `hacs/action` without an `ignore` list. Keep all jobs passing. The workflow is also available through manual dispatch and runs weekly.

## Artwork

The original SVG source is in `assets/cascade-icon.svg`. The 256 px and 512 px PNG icons are shipped inside the integration's `brand/` folder. Preserve their square dimensions and transparent background. Do not substitute Home Assistant branding or imply manufacturer endorsement.

## Releases and HACS catalog submission

1. Make the required code or metadata changes and update the manifest version, changelog, and English release notes.
2. Push and wait for the test, Hassfest, and HACS jobs to pass without ignored checks.
3. Publish a new GitHub release after those successful runs.
4. Submit the repository name alphabetically in the `integration` file of `hacs/default` from a branch in the owner's personal fork. Allow maintainer edits.
5. Complete the upstream pull request template accurately and include the new release URL and successful HACS/Hassfest run URLs.

Catalog inclusion requires HACS maintainer review. A submitted pull request is not confirmation of acceptance. See the [official inclusion requirements](https://www.hacs.xyz/docs/publish/include/).

## Scope of validation

Automated tests and replayed HAR responses do not prove hardware write behavior or actual phone notification delivery. Preserve the limitations documented in the README and report live verification separately. Do not include real credentials or HAR captures in commits or release archives.

## Heating curve frontend checks

Run `node --test tests/frontend/math.test.mjs` for the dependency-free logic checks. For browser interaction and responsive checks, install Playwright 1.56.1 and its Chromium browser, then run `node tests/frontend/browser.cjs`. The dedicated frontend workflow runs both and saves screenshots. Browser fixtures use invented controller data only.
