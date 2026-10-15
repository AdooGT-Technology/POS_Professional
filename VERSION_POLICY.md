# Version snapshot policy

- The repository root is the canonical source tree for the current release.
- Keep the root `VERSION.txt`, `Manager/VERSION.txt`, runtime version markers, and release checks synchronized.
- For every accepted update, create a top-level folder named exactly for the new version and copy the matching source snapshot into it. Do not nest older version folders inside a new snapshot.
- This release is `27.6.1`, based on `27.5.10`; the next patch release is `27.6.2`.
- Version snapshots must not include `.git`, local credentials/configuration, runtime SQLite databases, caches, build artifacts, or generated audit reports. Keep source, tests, documentation, and tracked design references.
- The release ZIP workflow excludes version snapshot folders so a release package does not contain a second copy of the project.
