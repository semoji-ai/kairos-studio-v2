# resources/

This directory is populated by `scripts/build-resources.*` (core, dist,
publish_agent.zip, python-embed). It is gitignored except for this file and
`.gitkeep`, so a clean checkout has none of those artifacts.

`tauri.conf.json` therefore does NOT declare `bundle.resources` — a plain
`cargo build` / `cargo test` must work on a clean checkout without running
the resource-build scripts first.

For release builds, run the resource build scripts first, then build with
the release overlay config which adds `bundle.resources`:

```
cargo tauri build --config tauri.release.conf.json
```
