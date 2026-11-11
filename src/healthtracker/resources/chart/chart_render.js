"use strict";

// Геометрия ECharts; координаты, подписи и сегменты уже подготовлены Python.
window.HealthTrackerRenderer = function (root, eventRoot, openSource) {
    const chart = echarts.init(root);
    let last = null;
    let lastOption = null;
    let rendered = null;
    let paintCount = 0;
    let renderMs = 0;
    chart.on("rendered", () => { paintCount += 1; });
    let timeLabelIds = [];
    // Подписи overlay используют только готовые Python x/локальный текст.
    function refreshTimeLabels() {
        const view = last && last.data.view;
        const children = [];
        if (view && ["day", "timeline"].includes(view.mode)) {
            const grid = chart.getModel().getComponent("grid", 0).coordinateSystem.getRect();
            const extent = chart.getModel().getComponent("xAxis", 0).axis.scale.getExtent();
            const pixel = x => chart.convertToPixel({xAxisIndex: 0}, x);
            const ticks = view.axis.ticks.map(t => ({x: t.x, date: t.text.split("\n")[0],
                hour: Number((t.text.split("\n")[1] || "").slice(0, 2))}))
                .filter(t => t.x < view.axis.max && Number.isInteger(t.hour) && t.hour >= 0 && t.hour < 24);
            const visible = ticks.filter(t => t.x >= extent[0] && t.x <= extent[1]);
            let hours = [];
            for (const step of [3, 4, 6, 12, 24]) {
                hours = visible.filter(t => t.hour % step === 0);
                if (hours.every((t, i) => !i || pixel(t.x)-pixel(hours[i-1].x) >= 28)) break;
            }
            const add = (id, x, y, text, color, weight, align) => children.push({id, type: "text", silent: true,
                x, y, style: {text, fill: color, font: `${weight} 11px "Noto Sans", sans-serif`,
                    align, verticalAlign: "middle"}});
            let previous = -Infinity;
            for (const tick of hours) {
                const x = pixel(tick.x);
                if (x-previous < 28) continue;
                add(`hour-${tick.x}`, x, grid.y+grid.height+9, String(tick.hour), "#e5e5e5", 600, "center");
                previous = x;
            }
            previous = -Infinity;
            for (let i=0; i<view.axis.boundaries.length; i++) {
                const start = view.axis.boundaries[i], end = view.axis.boundaries[i+1] ?? view.axis.max;
                if (end <= extent[0] || start > extent[1]) continue;
                const tick = ticks.find(t => t.x >= start && t.x < end);
                if (!tick) continue;
                const x = pixel(Math.max(start, extent[0]));
                if (x-previous < 72 || x+36 > grid.x+grid.width) continue;
                add(`date-${i}`, x, grid.y+grid.height+43, tick.date.slice(0,5), "#a0a0a0", 500, "left");
                previous = x;
            }
        }
        const ids = children.map(item => item.id);
        const removed = timeLabelIds.filter(id => !ids.includes(id)).map(id => ({id, $action: "remove"}));
        chart.setOption({graphic: [...removed, ...children.map(item => ({...item, $action: "replace"}))]});
        timeLabelIds = ids;
    }
    chart.on("datazoom", refreshTimeLabels);
    function tooltip(item) {
        const box = document.createElement("div");
        box.className = "observation-tooltip";
        const details = document.createElement("details");
        const summary = document.createElement("summary");
        summary.textContent = "Подробности измерения";
        details.appendChild(summary);
        for (const line of (item.lines || [])) {
            const text = document.createElement("div");
            text.className = /^\d+(\.\d+)?$/.test(line) ? "tooltip-value"
                : /^\d{4}-|^UTC |^Начало часа/.test(line) ? "tooltip-time" : "tooltip-detail";
            text.textContent = line;
            if (/^UTC |^Начало часа/.test(line) || line.includes(" · версия ")) details.appendChild(text);
            else box.appendChild(text);
        }
        if (details.childElementCount > 1) box.appendChild(details);
        for (const source of (item.sources || [])) {
            const button = document.createElement("button");
            button.type = "button";
            button.textContent = "Открыть: " + (source.label || "Запись") + " #" + source.record_id;
            button.addEventListener("click", () => {
                if (last) openSource(last, source);
            });
            box.appendChild(button);
        }
        return box;
    }
    function bands(params, api) {
        const a = api.coord([api.value(1), api.value(0)]);
        const b = api.coord([api.value(2), api.value(0)]);
        const rect = echarts.graphic.clipRectByRect({x: a[0], y: a[1] - 7,
            width: b[0] - a[0], height: 14}, params.coordSys);
        return rect && {type: "rect", shape: rect, style: {fill: "#777777", opacity: 0.7}};
    }
    function option(view) {
        const series = [];
        const colors = {cognitive: "#f0f0f0", learning: "#929292", application: "#787878",
            speed: "#666666", physical: "#9a9a9a", mood: "#858585", stress: "#777777"};
        const symbols = {cognitive: "circle", learning: "rect", application: "triangle", speed: "diamond",
            physical: "roundRect", mood: "pin", stress: "arrow"};
        const hasValues = row => row.points.some(p => p.value[1] !== null);
        const primary = view.series.find(row => row.kind === "cognitive" && hasValues(row))
            || view.series.find(hasValues) || view.series[0];
        const fill = new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            {offset: 0, color: "rgba(242,242,242,0.24)"},
            {offset: 0.3, color: "rgba(242,242,242,0.11)"},
            {offset: 0.6, color: "rgba(242,242,242,0.05)"},
            {offset: 1, color: "rgba(242,242,242,0)"}]);
        for (const [index, row] of view.series.entries()) {
            const leading = row === primary;
            // Отдельный scatter сохраняет каждый исходный ID, включая совпадения UTC.
            series.push({id: row.kind + "-points", name: row.name, type: "scatter",
                symbol: symbols[row.kind], symbolSize: leading ? (row.points.length > 48 ? 4.5 : 7) : (row.points.length > 48 ? 2.5 : 3.5),
                data: row.points.filter(p => p.value[1] !== null),
                itemStyle: {color: leading ? "#f0f0f0" : colors[row.kind], opacity: leading ? 1 : 0.75},
                emphasis: {scale: 1.5, itemStyle: {color: "#ffffff", shadowColor: "rgba(255,255,255,.2)", shadowBlur: 6}},
                clip: true, z: leading ? 6 : 3});
            for (const [number, indices] of row.segments.entries()) {
                series.push({id: row.kind + "-segment-" + number, name: row.name,
                    type: "line", data: indices.map(i => row.points[i]),
                    smooth: 0.3, smoothMonotone: "x", connectNulls: false, clip: true, symbol: "none", silent: true,
                    lineStyle: {color: leading ? "#f0f0f0" : colors[row.kind], width: leading ? 2.4 : 1, opacity: leading ? 1 : 0.8,
                        type: leading ? "solid" : ["learning", "physical"].includes(row.kind) ? "dashed"
                            : ["application", "speed"].includes(row.kind) ? "dotted" : "solid"},
                    areaStyle: leading ? {color: fill, origin: 0} : undefined,
                    tooltip: {show: false}, z: leading ? 5 : 2});
            }
        }
        // Готовые Python-границы локальных дат: только ориентиры, не точки/сегменты.
        // markLine сам отсекается и перемещается существующей координатной системой.
        if (["compact", "timeline"].includes(view.mode) && series.length) {
            const boundaries = [...new Set(view.axis.boundaries)].filter(x => x > view.axis.min && x < view.axis.max);
            series[0].markLine = {silent: true, symbol: "none", animation: false,
                label: {show: false}, lineStyle: {color: "#383838", width: 1, opacity: 0.65, type: "solid"},
                emphasis: {disabled: true}, data: boundaries.map(x => ({xAxis: x}))};
        }
        const sleep = view.sleep.length > 0;
        if (sleep) series.push({id: "sleep", name: "Сон", type: "custom", renderItem: bands,
            xAxisIndex: 1, yAxisIndex: 1, data: view.sleep, encode: {x: [1, 2], y: 0},
            itemStyle: {color: "#777777"}});
        // Только подписи готовых Python-тиков: реальные x/UTC/DST не изменяются.
        const tickLabels = new Map();
        const seenDates = new Set();
        for (const tick of view.axis.ticks) {
            if (tick.x >= view.axis.max) continue;
            const parts = tick.text.split("\n");
            if (view.mode === "day") {
                const time = (parts[1] || "").match(/\d{2}:\d{2}/);
                if (time) tickLabels.set(tick.x, time[0]);
            } else {
                const day = parts[0].slice(0, 5);
                if (day && !seenDates.has(parts[0])) {
                    seenDates.add(parts[0]);
                    tickLabels.set(tick.x, day);
                }
            }
        }
        const candidates = [...tickLabels.keys()];
        const capacity = Math.max(2, Math.floor((root.clientWidth - 64) / 72));
        const stride = Math.max(1, Math.ceil(candidates.length / capacity));
        const labels = new Map(candidates.filter((_, i) => i % stride === 0).map(x => [x, tickLabels.get(x)]));
        const hourly = ["day", "timeline"].includes(view.mode);
        const axis = {type: "value", offset: hourly ? 26 : 0, min: view.axis.min, max: view.axis.max,
            interval: view.axis.step, axisTick: {show: false},
            axisLabel: {show: !hourly, color: "#a0a0a0", fontSize: 11, margin: 16, hideOverlap: true,
                showMaxLabel: false, formatter: value => labels.get(value) || ""},
            splitLine: {show: false}, minorSplitLine: {show: false},
            axisLine: {show: true, onZero: false, lineStyle: {color: "#1c1c1c", width: 1}}};
        const shortDate = date => date.split("-").reverse().join(".");
        const dates = view.caption.split(" · ")[0].split(" — ");
        const caption = dates[0] === dates[1] ? shortDate(dates[0])
            : dates.map(shortDate).join(" — ");
        const compactLegend = view.series.length <= 2;
        // Внешние пол-единицы — только визуальные поля. Подписи шкалы остаются 0…10.
        // Точки и начало заливки (0) не смещаются в данных.
        const scoreAxis = {type: "value", min: -0.5, max: 10.5, interval: 0.5,
            scale: false, boundaryGap: [0, 0],
            axisLabel: {color: "#666666", hideOverlap: true,
                formatter: value => value >= 0 && value <= 10 && value % 2 === 0 ? String(value) : ""},
            axisLine: {show: false}, axisTick: {show: false}, splitLine: {show: false}};
        const result = {animation: false, backgroundColor: "#030303",
            textStyle: {fontFamily: '"Noto Sans", "Inter", sans-serif', fontWeight: 500},
            title: [{text: view.empty ? (view.empty_text || "Нет числовых наблюдений") : "", left: "center", top: "45%",
                     textStyle: {color: "#aaa", fontSize: 13}},
                    {text: caption, left: 15, top: 8, textStyle: {color: "#666666", fontSize: 11, fontWeight: "normal"}}],
            legend: {top: compactLegend ? 8 : 40, right: 15, type: "scroll", selectedMode: false, itemGap: 14,
                pageIconColor: "#ddd", pageIconInactiveColor: "#555", pageTextStyle: {color: "#999"},
                textStyle: {color: "#ccc", fontSize: 11}},
            grid: sleep ? [{left: 45, right: 20, top: compactLegend ? 64 : 88, bottom: hourly ? 115 : 95},
                          {left: 45, right: 20, height: 24, bottom: 25}]
                        : [{left: 45, right: 20, top: compactLegend ? 64 : 88, bottom: hourly ? 65 : 45}],
            xAxis: sleep ? [axis, {...axis, gridIndex: 1, axisLabel: {show: false}}] : [axis],
            yAxis: sleep ? [{...scoreAxis},
                {type: "category", gridIndex: 1, data: ["Сон"], axisLabel: {color: "#bbb"}}]
                : [{...scoreAxis}],
            dataZoom: [{type: "inside", xAxisIndex: sleep ? [0, 1] : [0], filterMode: "none",
                zoomOnMouseWheel: true, moveOnMouseMove: true, moveOnMouseWheel: false}],
            tooltip: {trigger: "item", triggerOn: "mousemove|click", enterable: true,
                confine: true, hideDelay: 1200, backgroundColor: "#090909", borderColor: "#1c1c1c",
                borderWidth: 1, padding: 10, textStyle: {color: "#eee", fontSize: 12},
                extraCssText: "border-radius:6px;box-shadow:none;", formatter: params => tooltip(params.data)},
            series: series};
        if (view.factors) {
            // Только геометрия уже рассчитанных Python-точек. Индекс,
            // группы, даты, исключения и подписи не вычисляются в JS.
            result.grid[0] = {left: 55, right: 25, top: 95, height: 300};
            if (sleep) result.grid[1] = {left: 55, right: 25, top: 430, height: 24};
            const start = result.grid.length;
            result.grid.push({left: 60, right: 30, top: 560, height: 230},
                             {left: 60, right: 30, top: 930, height: 230});
            const valueY = gridIndex => ({...scoreAxis, gridIndex,
                name: "Индекс, пункты", nameTextStyle: {color: "#bbb"},
                splitLine: {show: false}});
            result.xAxis.push({type: "value", gridIndex: start, min: 0, name: "Сон, часы по UTC",
                nameLocation: "middle", nameGap: 30, axisLabel: {color: "#bbb"}, nameTextStyle: {color: "#bbb"},
                splitLine: {show: false}},
                {type: "category", gridIndex: start + 1, data: ["Был", "Не был"],
                 axisLabel: {color: "#bbb"}});
            result.yAxis.push(valueY(start), valueY(start + 1));
            result.title.push({text: "Сон и дневная медиана индекса", top: 500, left: 15,
                textStyle: {fontSize: 13, color: "#ddd"}},
                {text: "Спортзал: явные отметки по датам", top: 870, left: 15,
                 textStyle: {fontSize: 13, color: "#ddd"}});
            result.series.push({id: "sleep-analysis", name: "Сон и индекс", type: "scatter",
                xAxisIndex: start, yAxisIndex: start, data: view.factors.sleep,
                symbolSize: 9, itemStyle: {color: "#dedede"}},
                {id: "gym-analysis", name: "Зал и индекс", type: "scatter",
                 xAxisIndex: start + 1, yAxisIndex: start + 1, data: view.factors.gym,
                 symbol: "diamond", symbolSize: 9, itemStyle: {color: "#a0a0a0"}});
        }
        return result;
    }
    function render(envelope) {
        if (rendered === envelope.delivery_id) return;
        const started = performance.now();
        const view = envelope.data.view;
        if (!view || !view.axis || !Array.isArray(view.series) || !Array.isArray(view.sleep)
                || !Array.isArray(view.events) || !Array.isArray(view.nonnumeric)) throw new Error("view");
        if (view.factors && ![view.factors.sleep, view.factors.gym].every(rows => Array.isArray(rows)
                && rows.every(p => Array.isArray(p.value) && p.value.length === 2
                    && p.value.every(Number.isFinite) && Array.isArray(p.lines)
                    && p.lines.every(line => typeof line === "string")
                    && Array.isArray(p.sources) && p.sources.length === 0))) throw new Error("factors");
        const next = option(view);
        const events = document.createDocumentFragment();
        for (const item of view.events) {
            const block = tooltip(item);
            block.className = "calendar-event";
            events.appendChild(block);
        }
        for (const item of view.nonnumeric) {
            const block = tooltip(item);
            block.className = "special-answer";
            events.appendChild(block);
        }
        try {
            timeLabelIds = [];
            chart.setOption(next, {notMerge: true, lazyUpdate: false});
        } catch (error) {
            if (lastOption) chart.setOption(lastOption, {notMerge: true});
            throw error;
        }
        last = envelope;
        lastOption = next;
        rendered = envelope.delivery_id;
        eventRoot.replaceChildren(events);
        root.classList.toggle("analytics", Boolean(view.factors));
        chart.resize();
        refreshTimeLabels();
        root.setAttribute("aria-label", view.factors ? "Дневная динамика и сравнения сна и спортзала"
            : view.empty ? (view.empty_text || "Нет числовых наблюдений") : "График реальных наблюдений");
        renderMs = performance.now() - started;
    }
    chart.setOption({animation: false, backgroundColor: "#030303", title: {text: "Нет наблюдений", textStyle: {color: "#aaa"}},
        xAxis: {type: "value", splitLine: {show: false}}, yAxis: {min: 0, max: 10, splitLine: {show: false}}, series: []});
    let resizeFrame = null;
    let labelTimer = null;
    let sizeKey = "";
    let labelWidth = root.clientWidth;
    const observer = new ResizeObserver(() => {
        const key = root.clientWidth + ":" + root.clientHeight;
        if (key === sizeKey) return;
        sizeKey = key;
        // При анимации только resize; полную адаптацию подписей делаем после паузы.
        if (labelTimer !== null) clearTimeout(labelTimer);
        labelTimer = setTimeout(() => {
            labelTimer = null;
            if (last && labelWidth !== root.clientWidth) {
                labelWidth = root.clientWidth;
                lastOption = option(last.data.view);
                // Меняются только подписи; zoom/pan остаются на месте.
                const zoom = chart.getOption().dataZoom;
                timeLabelIds = [];
                chart.setOption({...lastOption, dataZoom: zoom}, {notMerge: true});
            }
            chart.resize();
            refreshTimeLabels();
        }, 100);
        if (resizeFrame !== null) cancelAnimationFrame(resizeFrame);
        resizeFrame = requestAnimationFrame(() => {
            resizeFrame = null;
            chart.resize();
            refreshTimeLabels();
        });
    });
    observer.observe(root);
    window.addEventListener("pagehide", () => {
        observer.disconnect();
        if (labelTimer !== null) clearTimeout(labelTimer);
        if (resizeFrame !== null) cancelAnimationFrame(resizeFrame);
        chart.dispose();
    });
    return Object.freeze({render, resize: () => chart.resize(), tooltip,
        snapshot: () => ({rendered, paintCount, renderMs, width: chart.getWidth(), height: chart.getHeight(),
            domWidth: root.clientWidth, domHeight: root.clientHeight,
            series: chart.getOption().series, option: chart.getOption(),
            elements: chart.getZr().storage.getDisplayList().length,
            plotHeight: chart.getModel().getComponent("grid", 0).coordinateSystem.getRect().height,
            models: chart.getModel().getSeries().map(model => {
                const data = model.getData();
                let graphics = 0;
                for (let i = 0; i < data.count(); i += 1) if (data.getItemGraphicEl(i)) graphics += 1;
                return {id: model.id, type: model.subType, count: data.count(), graphics};
            })}),
        zoom: (start, end) => chart.dispatchAction({type: "dataZoom", start, end}),
        showTip: (seriesIndex, dataIndex) => chart.dispatchAction({type: "showTip", seriesIndex, dataIndex})});
};
