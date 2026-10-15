# Version and snapshot policy

- The repository root is the canonical source tree for the current release. Keep `VERSION.txt`, `Manager/VERSION.txt`, runtime markers, and release checks synchronized.
- Preserve the previous release as a source snapshot under `Archive/<previous-version>/`. For this update, `Archive/27.5.10/` records the project state before the 27.6.1 UI/version update.
- Store each current release under `Release/<version>/`. For this update, the clean snapshot is `Release/27.6.1/`.
- A `Release/<version>/` snapshot must not include `Design_References`, `Archive`, `Release`, or any older version folders. Archive snapshots also omit `Design_References` to avoid duplicating design-only assets.
- Do not copy `.git`, local credentials/configuration, runtime SQLite databases, caches, build outputs, or generated audit reports into snapshots. Keep source, tests, and documentation.
- The next patch snapshot is `Release/27.6.2/`; do not nest prior snapshots inside it.
- The GitHub release ZIP workflow excludes `Archive/` and `Release/` so packages contain only the canonical source tree.
