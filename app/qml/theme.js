.pragma library

const bases = {
    white: {bg:"#ffffff",sidebar:"#f7f9fc",surface:"#ffffff",userBubble:"#f0f5ff",hover:"#edf3ff",line:"#e3e8f0",ink:"#182238",muted:"#667085",accent:"#2864f0",accentBg:"#edf3ff",selectionBg:"#2864f0",selectionText:"#ffffff",button:"#2864f0",buttonText:"#ffffff",danger:"#c24141"},
    light: {bg:"#fcfcfa",sidebar:"#f2f3ef",surface:"#ffffff",userBubble:"#f0f1ee",hover:"#e9ede7",line:"#e5e8e1",ink:"#252d28",muted:"#828b83",accent:"#365e47",accentBg:"#eaf0e8",selectionBg:"#315e47",selectionText:"#ffffff",button:"#365e47",buttonText:"#ffffff",danger:"#a25a44"},
    dark: {bg:"#191c1b",sidebar:"#141716",surface:"#212523",userBubble:"#2b302e",hover:"#2a302c",line:"#343a36",ink:"#e7eae5",muted:"#929e95",accent:"#9dc5ac",accentBg:"#2b3c31",selectionBg:"#a5cdb3",selectionText:"#13271a",button:"#8dbd9e",buttonText:"#19271e",danger:"#e7a791"},
    yanami: {bg:"#f4f7ff",sidebar:"#e9effd",surface:"#ffffff",userBubble:"#e5ecfc",hover:"#dce6fc",line:"#d6e1f7",ink:"#283957",muted:"#7b8dac",accent:"#456fbe",accentBg:"#e6edff",selectionBg:"#2f5597",selectionText:"#ffffff",button:"#4d75c1",buttonText:"#ffffff",danger:"#a25a44"}
}
function palette(base, colors) { return Object.assign({}, bases[base] || bases.white, colors || {}) }
