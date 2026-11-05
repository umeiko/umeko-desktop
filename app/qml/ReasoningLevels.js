.pragma library

var defaults = ["low", "high", "max"]
function label(value) {
    return ({none:"None", minimal:"Minimal", low:"Low", medium:"Medium", high:"High", xhigh:"XHigh", max:"Max", ultra:"Ultra"})[value] || value
}
