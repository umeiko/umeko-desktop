.pragma library

// One random salt per launch. A message keeps its choice even when ListView
// recreates its delegate; streamed text never participates in the key.
var salt = Math.floor(Math.random() * 0x100000000)

function choose(messageKey) {
    let hash = salt
    for (let i = 0; i < messageKey.length; ++i)
        hash = Math.imul(hash ^ messageKey.charCodeAt(i), 16777619)
    hash ^= hash >>> 16
    return (hash >>> 0) % 3
}
