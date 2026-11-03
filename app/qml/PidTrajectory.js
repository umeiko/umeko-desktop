.pragma library

// Same controller and limits as PidMotion. Compute only when the setpoint
// changes; the resulting curve can run entirely on the scene graph thread.
var kp = 280, ki = 60, kd = 20
var step = 1 / 240

function clamp(value, limit) { return Math.max(-limit, Math.min(limit, value)) }

function plan(position, velocity, integral, destination) {
    const samples = [[position, velocity, integral]]
    const maxSteps = Math.ceil(Math.abs(destination - position) / 1800 / step) + 960
    for (let i = 0; i < maxSteps; ++i) {
        const error = destination - position
        integral = clamp(integral + error * step, 60) * Math.exp(-3 * step)
        velocity = clamp(velocity + clamp(kp * error + ki * integral - kd * velocity, 30000) * step, 1800)
        position += velocity * step
        samples.push([position, velocity, integral])
        if (Math.abs(destination - position) < 0.15 && Math.abs(velocity) < 0.8)
            break
    }
    samples.push([destination, 0, 0])
    const start = samples[0][0]
    // A reversal can target the exact current position with nonzero velocity.
    // Keep a nonzero interpolation span so that its inertial excursion survives.
    const end = Math.abs(destination - start) < 0.001 ? start + 0.001 : destination
    const span = end - start, last = samples.length - 1, curve = []
    function segment(a, b) {
        const seconds = (b - a) * step, p0 = samples[a][0]
        const p3 = b === last ? end : samples[b][0]
        const points = [p0, p0 + samples[a][1] * seconds / 3,
                        p3 - samples[b][1] * seconds / 3, p3]
        let error = 0, split = a
        for (let i = a + 1; i < b; ++i) {
            const difference = Math.abs(cubic(points, (i - a) / (b - a)) - samples[i][0])
            if (difference > error) { error = difference; split = i }
        }
        return {a: a, b: b, points: points, error: error, split: split}
    }
    const segments = [segment(0, last)]
    // Qt 6.10's BezierEase stores at most ten segments. Adaptive Hermite
    // fitting preserves the controller's overshoot without exceeding that limit.
    while (segments.length < 10) {
        let worst = 0
        for (let i = 1; i < segments.length; ++i)
            if (segments[i].error > segments[worst].error) worst = i
        const part = segments[worst]
        if (part.error <= 0.15 || part.split === part.a) break
        segments.splice(worst, 1, segment(part.a, part.split), segment(part.split, part.b))
    }
    for (const part of segments) {
        const x0 = part.a / last, x1 = part.b / last
        curve.push(x0 + (x1 - x0) / 3, (part.points[1] - start) / span,
                   x0 + (x1 - x0) * 2 / 3, (part.points[2] - start) / span,
                   x1, part.b === last ? 1 : (part.points[3] - start) / span)
    }
    return {samples: samples, segments: segments, curve: curve, duration: Math.round(last * step * 1000),
            start: start, end: end, destination: destination}
}

function cubic(points, t) {
    const s = 1 - t
    return s*s*s*points[0] + 3*s*s*t*points[1] + 3*s*t*t*points[2] + t*t*t*points[3]
}

function sample(trajectory, milliseconds) {
    const last = trajectory.samples.length - 1
    const offset = Math.max(0, milliseconds) / trajectory.duration * last
    if (offset >= last) return [trajectory.destination, 0, 0]
    const index = Math.floor(offset), fraction = offset - index
    const a = trajectory.samples[index], b = trajectory.samples[index + 1]
    const part = trajectory.segments.find(part => offset <= part.b)
    const t = (offset - part.a) / (part.b - part.a), s = 1 - t, p = part.points
    const velocity = 3 * (s*s*(p[1]-p[0]) + 2*s*t*(p[2]-p[1]) + t*t*(p[3]-p[2]))
                     / ((part.b - part.a) / last * trajectory.duration / 1000)
    return [cubic(p, t), velocity, a[2] + (b[2] - a[2]) * fraction]
}
