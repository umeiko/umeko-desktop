.pragma library

// The host supplies one bounded page; do not retain earlier pages in the Widget.
function nodes(data) {
    if (!data) return []
    const rows = [{key: 'start', kind: 'start', time: data.started, code: 'draft', body: data.cwd}]
    for (const file of data.files || []) rows.push({
        key: 'file-' + file.id, kind: file.source === 'input' ? 'input' : 'file',
        time: file.observed || '', code: file.state, body: file.path, file: file})
    for (const step of data.steps || []) rows.push({
        key: step.kind + '-' + step.key, kind: step.kind, time: step.observed || '',
        code: step.kind === 'delivery_error' ? 'failed' : 'draft', body: step.detail, reference: step.key})
    if (data.ended) rows.push({key: 'end', kind: 'end', time: data.ended, code: data.state, body: data.reason || ''})
    if (data.accepted) rows.push({key: 'accepted', kind: 'accepted', time: data.accepted, code: 'accepted', body: ''})
    if (Array.isArray(data.timelineKeys)) {
        const byKey = new Map(rows.map(row => [row.key, row]))
        return data.timelineKeys.map(key => byKey.get(key)).filter(Boolean)
    }
    // Keep undated legacy events in observed storage order, explicitly undated.
    return rows.map((row, index) => { row.order=index; return row }).sort((a,b) => {
        if (!a.time || !b.time) return a.time ? -1 : b.time ? 1 : a.order-b.order
        return a.time.localeCompare(b.time) || a.order-b.order
    })
}

function checkSummary(result) {
    return Object.keys(result.counts || {}).map(code => ({code: code, count: result.counts[code]}))
}
