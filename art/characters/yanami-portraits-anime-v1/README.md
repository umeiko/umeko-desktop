# Yanami empty-chat portraits · anime style

Twelve standard portraits for the built-in main character, redrawn with the official TV-anime model sheet as the primary face/style reference. Existing expression indices are retained. Portrait 01 uses a smaller, softer greeting smile. Portrait 05 follows the official episode-12 face-framing smug smile; the user subsequently requested removal of the upper-left hand and sleeve, leaving the lower-right gesture. Portrait 11: the user explicitly requested removal of its hand and chopsticks after rejecting two hand drawings. The full-cheek eating expression remains.

`generation.json` records sources, hashes and per-image prompts in `prompts/`. Image generation used the built-in image tool, whose model identifier was not exposed. Final transparent PNGs live in `app/icons/portraits/01.png` through `12.png`; the C++ edition uses lossless WebP equivalents. No expression is synthesized by deforming another image.

The old portrait 02 is preserved as `app/icons/yanami-chat-watermark` for the existing background watermark. Desktop pets, message avatars, rare scenes, expression selection and interaction behavior are unchanged. The user accepted the final set on 2026-11-17 and authorized submission. This change does not publish a versioned release.

Official visual references: https://makeine-anime.com/character/ . This is a non-official adaptation, not official character artwork or endorsement.
