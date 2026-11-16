# Time-zone fallback

`tzdata-2026.6-py2.py3-none-any.whl` is the unmodified Python Software Foundation tzdata wheel from https://pypi.org/project/tzdata/2026.6/.

SHA-256: `0a10eec6e13ef16b627fabed9a5f2ba61a62b1c67f327305f4e7e412a70b4aec`

It supplies IANA zones when the operating system has no zoneinfo database, including standalone Windows Python. The standard library reads it directly as a zip resource; nothing is downloaded or installed at application startup. Apache-2.0 and IANA data licenses are included inside the wheel under `tzdata-2026.6.dist-info/licenses/`.
