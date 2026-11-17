# Release payload size and artwork policy

Packaging writes component reports to build/ci-smoke/package-size.json (Python)
or build/package-size.json (C++), plus a CI summary. ZIP reports attribute actual
compressed entry sizes; headers account for remaining bytes. Tar reports
attribute expanded bytes because gzip uses a shared compression stream.
MB below means 1,000,000 bytes.

## Published Windows baseline, 2026-11-17

| Compressed content | Python v0.7.5 | C++ v0.7.2 |
| --- | ---: | ---: |
| Desktop-pet animations | 92.6 MB | 109.5 MB |
| External UI artwork | 75.5 MB | 87.8 MB |
| Application executable | 7.1 MB | 71.5 MB |
| Node and npm | 36.8 MB | 36.7 MB |
| Pi and dependencies | 35.7 MB | 28.5 MB |
| Qt and native libraries | 50.3 MB | 28.0 MB |
| Bundled Python | 2.6 MB | 22.4 MB |
| **Whole ZIP, including other resources and headers** | **321.4 MB** | **403.8 MB** |

The art source directory is not shipped, so cleaning it did not shrink these
packages. C++ also embedded artwork in its executable while shipping the same
artwork externally for public Widget imports.

## Current staged artwork policy

Original source assets stay unchanged. scripts/package_payload.py transforms
only fresh distribution staging trees:

- Bound static images by UI role, preserving aspect ratio and never upscaling.
  Avatars use about 256 px; loading/drop art 384 px; welcome portraits 512 px;
  character welcome/background art up to 768 px.
- Use WebP quality 92 for larger character art and welcome portraits. Keep small
  avatars lossless after resizing. Preserve legacy PNG paths by resizing their
  PNG canvases rather than changing hard-coded URLs.
- Target a 320 px longest edge for pet animations, using animated WebP quality 90.
  Existing animated WebP is also considered. Keep originals when re-encoding
  would enlarge them. Do not deliberately drop motion frames or change speed.
- Validate alpha exactly against each resized reference frame. Check visible RGB
  RMS error on light and dark backgrounds, with a 4.5/255 bound. Raise quality to
  96 for static art / 95 for animation, then fall back to lossless when necessary.
  This bound measures encoding error after resizing; it does not claim original
  full-resolution pixel equality.
- Compare the full animation timeline, including coalesced identical holds,
  durations and finite/infinite loop semantics. Update staged state references,
  frame/canvas metadata and rare-idle filenames together. Retain persona,
  dialogue, relative content offsets, aspect ratios and interaction physics.
- Record output hashes in payload-assets.json. Re-running the optimizer on
  unchanged optimized staging performs no further lossy encoding. A changed
  policy or changed output requires fresh staging.
- Remove standard JavaScript source maps and the obsolete lossless-assets.json
  build manifest. Keep SDK code, declarations, examples and licenses.
- C++ loads main QML and art from the same installed tree as Widgets, eliminating
  the large embedded duplicate. Its update-installer shell/art stay embedded.

Pillow is a build dependency, not an application runtime requirement. Existing
Qt WebP support plays the animations.

## Actual Windows resource repack experiments

Both published downloads were verified against their release SHA-256 files.
These experiments keep the original Windows executables and use the original
ZIP compression levels:

| Archive | Published | Lossless trial | Current resized/quality-bounded |
| --- | ---: | ---: | ---: |
| Python v0.7.5 | 321,359,702 B | 283,757,213 B | 202,433,939 B |
| C++ v0.7.2 | 403,758,296 B | 365,391,225 B | 278,899,920 B |

The current reduction is 37.0% for Python and 30.9% for C++ resources alone.
The C++ experiment still contains the old executable's embedded duplicate.

On the same current-main Linux source/compiler, removing that duplicate reduced
the executable from 78,493,576 B to 8,243,080 B. Raw DEFLATE level 9 reduced its
content from 72,088,338 B to 4,682,543 B, saving another 67,405,795 B. This is a
Linux comparison, not a measured rebuilt Windows ZIP. Native Windows CI must
confirm the accepted source's complete package size before publication.

## Validation

- Nine payload regression tests per repository cover scaling, alpha, timing,
  loop conversion, fine-line quality fallback, metadata, no repeated degradation,
  source checkout protection, SDK retention and macOS Frameworks data links.
- Local Qt 6.10.2 compared every transformed encoded asset with Pillow decoding:
  121 assets / 2,122 frames in Python, 124 assets / 2,125 frames in C++.
  Qt loop counts and total playback durations match the original animations.
- Animation decode medians were about 0.67 ms before and 0.72 ms after; p95 was
  about 1.19 ms afterward. These are decoder timings, not GUI FPS claims.
- Matched offscreen software startup probes used the same Tiara main/pet profile.
  Both variants peaked at about 300 MiB; no application-memory reduction is claimed.
- The actual C++ application loaded all ten Widget QML entry points, artwork and
  the tray icon. The pruned staged Pi passed native-tool self-test and read-only
  Skills, extension and background-job catalog requests.
- Update-engine/native installer tests cover successful installation and rejection
  of a changed archive. Visual comparison uses the same on-screen artwork sizes
  over light and dark backgrounds.

The acceptance preview uses the current prepared Pi bridge and an isolated data
profile. The user accepted the local preview on 2026-11-17. These Windows resource
experiments are not published releases; native CI reports the final package sizes.
