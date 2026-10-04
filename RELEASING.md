# Releasing

The import buttons in the README and each blueprint's `source_url` point at a
GitHub owner and a version. Releases are git tags.

1. Run the tests: `python tests/policy_model.py` and
   `python tests/render_blueprints.py`.
2. Update `CHANGELOG.md`.
3. Point the links at the new tag (use `main` for "latest"):
   ```bash
   python scripts/set_repo.py --owner YOUR_GITHUB_NAME --version v0.1.0
   ```
4. Commit, tag and push:
   ```bash
   git add -A && git commit -m "Release v0.1.0"
   git tag v0.1.0 && git push && git push --tags
   ```
5. Create a GitHub release for the tag with the changelog entry.

Users who want stability import from a tag URL; users who want updates import
from `main` and use **Re-import blueprint** in Home Assistant. A blueprint
change only takes effect after automations are reloaded.
