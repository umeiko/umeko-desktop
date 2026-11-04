.pragma library

var defaults = ["low", "high", "max"]
function label(value) {
    return ({low:"Low", high:"High", max:"Max"})[value] || value
}
