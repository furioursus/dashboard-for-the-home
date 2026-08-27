// Office Pi Dashboard frontend.
//
// Vanilla JS, no build step, no framework - this runs on a Pi Zero 2 W's
// GPU/CPU. The one performance rule that matters here: don't touch the DOM
// unless something actually changed. `/api/state` is polled on a timer,
// but each panel only gets re-rendered when its JSON signature differs
// from what's already on screen. A live clock/countdown ticks separately
// on a 1s timer, updating just its own text node rather than going through
// the panel diff at all.

const POLL_INTERVAL_MS = 5000;

const lastSignature = {
  todoist: null,
  calendar: null,
  hue: null,
  bambu: null,
};

function fmtClock(d) {
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function fmtDueDate(dateStr) {
  if (!dateStr) return "";
  const d = new Date(dateStr.length > 10 ? dateStr : dateStr + "T00:00:00");
  const today = new Date();
  const diffDays = Math.round((d.setHours(0, 0, 0, 0) - today.setHours(0, 0, 0, 0)) / 86400000);
  if (diffDays === 0) return "today";
  if (diffDays === 1) return "tomorrow";
  if (diffDays < 0) return `${-diffDays}d overdue`;
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function fmtEventTime(isoStr, allDay) {
  if (allDay) return "All day";
  if (!isoStr) return "";
  return new Date(isoStr).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function fmtCountdown(targetIso) {
  const diffMs = new Date(targetIso).getTime() - Date.now();
  if (diffMs <= 0) return "now";
  const mins = Math.round(diffMs / 60000);
  if (mins < 60) return `in ${mins}m`;
  const hrs = Math.floor(mins / 60);
  const rem = mins % 60;
  return `in ${hrs}h ${rem}m`;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str == null ? "" : String(str);
  return div.innerHTML;
}

// ---- panel body builders --------------------------------------------

function renderTodoistTasks(tasks, groupClass) {
  if (!tasks.length) return "";
  return `<ul class="task-list">${tasks
    .map((t) => {
      const p = t.priority >= 2 ? `p${t.priority}` : "";
      return `<li class="task-item ${groupClass}">
        <span class="priority-dot ${p}"></span>
        <span class="task-content">${escapeHtml(t.content)}</span>
        <span class="task-due">${escapeHtml(fmtDueDate(t.due_date))}</span>
      </li>`;
    })
    .join("")}</ul>`;
}

function buildTodoistHtml(data) {
  const { overdue = [], today = [], upcoming = [] } = data || {};
  if (!overdue.length && !today.length && !upcoming.length) {
    return `<p class="empty">Nothing due. 🎉</p>`;
  }
  let html = "";
  if (overdue.length) {
    html += `<div class="task-group-label">Overdue</div>${renderTodoistTasks(overdue, "overdue")}`;
  }
  html += `<div class="task-group-label">Today</div>`;
  html += today.length ? renderTodoistTasks(today, "") : `<p class="empty">Nothing due today.</p>`;
  if (upcoming.length) {
    html += `<div class="task-group-label">Upcoming</div>${renderTodoistTasks(upcoming, "")}`;
  }
  return html;
}

function buildCalendarHtml(data) {
  const { today = [], next_event: next } = data || {};
  let html = "";
  if (next) {
    html += `<div class="next-event">
      <div class="label">Next up</div>
      <div class="summary">${escapeHtml(next.summary)}</div>
      <div class="countdown" id="next-event-countdown" data-start="${escapeHtml(next.start)}">
        ${escapeHtml(fmtEventTime(next.start, next.all_day))} &middot; ${fmtCountdown(next.start)}
      </div>
    </div>`;
  }
  if (!today.length) {
    html += `<p class="empty">No events today.</p>`;
    return html;
  }
  html += `<ul class="event-list">${today
    .map(
      (e) => `<li class="event-item">
        <span class="event-time">${escapeHtml(fmtEventTime(e.start, e.all_day))}</span>
        <span class="event-summary">${escapeHtml(e.summary)}</span>
      </li>`
    )
    .join("")}</ul>`;
  return html;
}

function buildHueHtml(data) {
  if (!data) return `<p class="empty">Bridge unreachable.</p>`;
  const on = !!data.on;
  return `
    <div class="hue-name">${escapeHtml(data.name || "Lights")}</div>
    <div class="hue-controls">
      <button class="hue-toggle ${on ? "on" : ""}" id="hue-toggle-btn" aria-label="Toggle lights"></button>
      <div class="brightness-row">
        <input type="range" min="1" max="100" value="${data.brightness || 1}"
               class="brightness-slider" id="hue-brightness-slider" ${on ? "" : "disabled"} />
        <span class="brightness-value" id="hue-brightness-value">${data.brightness || 0}%</span>
      </div>
    </div>`;
}

function buildBambuHtml(data) {
  if (!data || !data.connected) {
    return `<p class="error-msg">Printer offline.</p>`;
  }
  const state = data.state || "unknown";
  const pct = typeof data.progress_percent === "number" ? data.progress_percent : null;
  let html = `<span class="bambu-state ${state}">${escapeHtml(state)}</span>`;
  html += `<div class="bambu-task-name">${escapeHtml(data.task_name || "No active job")}</div>`;
  if (pct !== null) {
    html += `<div class="progress-track"><div class="progress-fill" style="width:${pct}%"></div></div>`;
    html += `<div class="bambu-meta">
      <span>${pct}%</span>
      ${
        typeof data.remaining_minutes === "number"
          ? `<span>${Math.round(data.remaining_minutes)} min left</span>`
          : ""
      }
    </div>`;
  }
  const temps = [];
  if (data.nozzle_temp != null) temps.push(`Nozzle ${Math.round(data.nozzle_temp)}°`);
  if (data.bed_temp != null) temps.push(`Bed ${Math.round(data.bed_temp)}°`);
  if (temps.length) {
    html += `<div class="bambu-temps">${temps.map((t) => `<span>${t}</span>`).join("")}</div>`;
  }
  return html;
}

const BUILDERS = {
  todoist: buildTodoistHtml,
  calendar: buildCalendarHtml,
  hue: buildHueHtml,
  bambu: buildBambuHtml,
};

// ---- diff + render -----------------------------------------------------

function renderPanel(key, panelState) {
  const signature = JSON.stringify(panelState);
  if (signature === lastSignature[key]) return;
  lastSignature[key] = signature;

  const bodyEl = document.getElementById(`${key}-body`);
  const panelEl = document.getElementById(`panel-${key}`);
  const { data, error } = panelState;

  if (error && !data) {
    bodyEl.innerHTML = `<p class="error-msg">${escapeHtml(error)}</p>`;
  } else {
    bodyEl.innerHTML = BUILDERS[key](data);
  }
  panelEl.classList.toggle("stale", !!error);
}

async function pollState() {
  try {
    const resp = await fetch("/api/state", { cache: "no-store" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const state = await resp.json();

    const roomNameEl = document.getElementById("room-name");
    const roomName = state.room?.display_name || "Room";
    if (roomNameEl.textContent !== roomName) roomNameEl.textContent = roomName;

    for (const key of Object.keys(BUILDERS)) {
      const panelState = state.panels?.[key];
      if (panelState) renderPanel(key, panelState);
    }
  } catch (err) {
    // Network hiccup (or backend restarting) - leave the last good render
    // on screen rather than blanking the whole dashboard.
    console.warn("poll failed:", err);
  } finally {
    setTimeout(pollState, POLL_INTERVAL_MS);
  }
}

// ---- clock + live countdown tick ---------------------------------------

function tickClock() {
  const now = new Date();
  document.getElementById("clock").textContent = fmtClock(now);

  const countdownEl = document.getElementById("next-event-countdown");
  if (countdownEl) {
    const start = countdownEl.dataset.start;
    const allDay = start && start.length <= 10;
    const label = `${fmtEventTime(start, allDay)} · ${fmtCountdown(start)}`;
    if (countdownEl.textContent.trim() !== label) countdownEl.textContent = label;
  }
}

// ---- Hue touch controls (delegated so they survive panel re-renders) ---

document.getElementById("hue-body").addEventListener("click", async (ev) => {
  if (ev.target.id !== "hue-toggle-btn") return;
  const btn = ev.target;
  const turningOn = !btn.classList.contains("on");
  btn.classList.toggle("on", turningOn); // optimistic
  try {
    await fetch("/api/hue/power", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ on: turningOn }),
    });
  } catch (err) {
    console.warn("hue power toggle failed:", err);
  }
  lastSignature.hue = null; // force re-render with server truth on next poll
});

document.getElementById("hue-body").addEventListener("change", async (ev) => {
  if (ev.target.id !== "hue-brightness-slider") return;
  const percent = Number(ev.target.value);
  try {
    await fetch("/api/hue/brightness", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ percent }),
    });
  } catch (err) {
    console.warn("hue brightness change failed:", err);
  }
  lastSignature.hue = null;
});

// Live-update the %, label while dragging, without spamming the bridge.
document.getElementById("hue-body").addEventListener("input", (ev) => {
  if (ev.target.id !== "hue-brightness-slider") return;
  const valueEl = document.getElementById("hue-brightness-value");
  if (valueEl) valueEl.textContent = `${ev.target.value}%`;
});

// ---- boot ---------------------------------------------------------------

tickClock();
setInterval(tickClock, 1000);
pollState();
