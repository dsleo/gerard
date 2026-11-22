# Gérard · La France politique

An exploratory atlas of French legislative constituencies. The application
compares the official 2024 electoral map with a saved redistricting scenario and [partisan map experiments](redistricting/webapp/scenarios.html).
[Comment ça marche](redistricting/webapp/method.html) explains the territorial
search, ReCom, electoral estimates, and limitations.

## Local preview

From the project root:

```bash
python3 -m http.server 8765 --bind 127.0.0.1
```

Open <http://127.0.0.1:8765/redistricting/webapp/>.

## GitHub Pages

The workflow in [.github/workflows/pages.yml](.github/workflows/pages.yml)
publishes pushes to `main`. In the repository’s **Settings → Pages**, select
**GitHub Actions** as the publishing source first.

To inspect the exact release package locally:

```bash
python3 redistricting/scripts/build_pages.py
```

This builds `_site/` without rerunning the optimizer or changing its results.
The package contains the app, saved browser snapshots, and the methodology
references. All URLs work beneath a project prefix such as `/gerard/`.
Raw source data, local environments, and optimization runs are excluded by
`.gitignore` and are not copied into the site.

After publishing, the workflow downloads the deployed files and compares their
SHA-256 hashes with the release manifest. To run this check manually:

```bash
python3 redistricting/scripts/verify_pages.py https://OWNER.github.io/REPOSITORY/
```

## Checks

```bash
node --check redistricting/webapp/atlas.js
node --check redistricting/webapp/method.js
cd redistricting
.venv/bin/python -m pytest tests/test_pages.py -q
```

See [the engine documentation](redistricting/README.md) for the scientific
pipeline. The displayed scenario remains an exploratory, uncertified draft.
