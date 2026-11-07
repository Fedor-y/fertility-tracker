"use strict";

// Протокол eventual consistency; рисуется только подтверждённый снимок.
new QWebChannel(qt.webChannelTransport, function (channel) {
    const bridge = channel.objects.bridge;
    const pageId = bridge.pageId;
    const id = value => typeof value === "string" && /^[0-9a-f]{32}$/.test(value);
    let sequence = -1;
    let candidate = null;
    let state = "loading";
    const events = document.createElement("section");
    events.className = "calendar-events";
    events.setAttribute("aria-label", "События по датам и специальные ответы");
    document.body.appendChild(events);
    let renderer;
    try {
        renderer = HealthTrackerRenderer(document.getElementById("chart"), events, (envelope, source) => {
        if (state === "confirmed" && candidate && envelope.delivery_id === candidate.delivery_id)
            bridge.openSource(pageId, envelope.request_id, envelope.delivery_id, source.kind, String(source.record_id));
        });
    } catch (_) {
        bridge.requestInitialState(pageId, "failed");
        return;
    }
    const status = document.createElement("p");
    status.setAttribute("role", "status");
    document.body.appendChild(status);
    function setState(next) {
        state = next;
        const labels = {ready: "График готов. Ожидаются данные.",
            provisional: "Данные обновляются — снимок предварительный",
            confirmed: "Снимок проверен Python на момент подтверждения.",
            stale: "Данные устарели", checking: "Данные обновляются",
            error: "Ошибка доставки. Повторите запрос."};
        document.getElementById("chart").classList.toggle("outdated", next !== "confirmed" && next !== "ready");
        status.textContent = labels[next] || "Данные обновляются";
    }
    function source(ref) {
        return ref && ["cognitive", "physical", "mood", "stress", "sleep", "meals", "gym"].includes(ref.kind)
            && Number.isSafeInteger(ref.record_id) && ref.record_id > 0
            && Array.isArray(ref.definitions) && Array.isArray(ref.cognitive_answers);
    }
    function validData(data) {
        return data && ["day", "compact", "timeline", "daily"].includes(data.mode)
            && data.period && typeof data.period.start === "string" && typeof data.period.end === "string"
            && data.context && typeof data.context.now === "string" && typeof data.context.zone === "string"
            && Number.isFinite(data.line_gap_hours) && data.line_gap_hours > 0
            && Array.isArray(data.series) && data.series.every(series =>
                ["cognitive", "learning", "application", "speed", "physical", "mood", "stress"].includes(series.kind)
                && Array.isArray(series.points) && series.points.every(point =>
                    (point.value === null || (Number.isFinite(point.value) && point.value >= 0 && point.value <= 10))
                    && Array.isArray(point.sources) && point.sources.length > 0 && point.sources.every(source))
                && Array.isArray(series.segments) && series.segments.every(segment =>
                    Array.isArray(segment.indices) && segment.indices.length >= 2
                    && segment.indices.every(i => Number.isSafeInteger(i) && i >= 0 && i < series.points.length)))
            && Array.isArray(data.calendar_events) && data.calendar_events.every(e => source(e.source))
            && Array.isArray(data.sleep) && data.sleep.every(e => source(e.source));
    }
    function matches(message) {
        return candidate && message.request_id === candidate.request_id
            && message.delivery_id === candidate.delivery_id && message.sequence === candidate.sequence;
    }
    function receive(message) {
        let envelope;
        try {
            envelope = JSON.parse(message);
            if (envelope.protocol !== 1 || envelope.page_id !== pageId
                    || !Number.isSafeInteger(envelope.sequence) || envelope.sequence < sequence) return;
            if (envelope.kind === "data") {
                if (envelope.sequence <= sequence || !id(envelope.request_id) || !id(envelope.delivery_id)) return;
                sequence = envelope.sequence;
                candidate = null; // Новая доставка всегда отменяет прежнюю.
                if (!validData(envelope.data)) throw new Error("protocol");
                candidate = envelope;
                setState("provisional");
                bridge.received(pageId, envelope.request_id, envelope.delivery_id);
            } else if (envelope.kind === "confirmed" && matches(envelope)) {
                renderer.render(candidate);
                setState("confirmed");
            } else if (envelope.kind === "checking" && matches(envelope)) {
                setState("checking");
            } else if (["stale", "error"].includes(envelope.kind)) {
                sequence = envelope.sequence;
                candidate = null;
                setState(envelope.kind);
            }
        } catch (_) {
            const failed = candidate || envelope;
            candidate = null;
            setState("error");
            if (failed && id(failed.request_id) && id(failed.delivery_id))
                bridge.reportFailure(pageId, failed.request_id, failed.delivery_id);
        }
    }
    // Диагностическое чтение состояния не обходит Python-проверку подтверждения.
    window.healthtrackerChannel = Object.freeze({
        snapshot: () => JSON.parse(JSON.stringify({pageId, sequence, state, candidate})),
        receive: receive,
        rendering: renderer.snapshot,
        showTip: renderer.showTip,
        zoom: renderer.zoom,
        tooltip: renderer.tooltip
    });
    bridge.payload.connect(receive);
    try {
        window.addEventListener("resize", renderer.resize);
        setState("ready");
        bridge.requestInitialState(pageId, echarts.version);
    } catch (_) {
        setState("error");
        bridge.requestInitialState(pageId, "failed");
    }
});
