const $ = id => document.getElementById(id);
const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char]));
const time = value => value ? new Date(value).toLocaleString("es-MX", {month:"short", day:"2-digit", hour:"2-digit", minute:"2-digit"}) : "sin datos";
const api = (path, options) => fetch(path, options).then(async response => { const data = await response.json(); if (!response.ok) throw Error(data.detail || "No se pudo completar la acción"); return data; });
const list = (target, items, renderer, empty) => { $(target).innerHTML = items.length ? items.map(renderer).join("") : `<div class="empty">${empty}</div>`; };

function renderOverview(summary, history, alerts, events) {
  $("devices-count").textContent = summary.devices;
  $("up-count").textContent = summary.up;
  $("risk-count").textContent = summary.degraded + summary.down;
  $("incident-count").textContent = summary.active_incidents;
  $("latency").textContent = summary.average_latency_ms == null ? "—" : `${summary.average_latency_ms} ms`;
  $("loss").textContent = summary.packet_loss_percent == null ? "—" : `${summary.packet_loss_percent}%`;
  $("updated").textContent = summary.last_monitor_run ? `Actualizado ${time(summary.last_monitor_run)}` : "Sin mediciones";
  $("empty-hint").textContent = summary.has_data ? "NetPulse muestra datos obtenidos por el monitoreo que configuraste." : "Carga un ejemplo o agrega un equipo que quieras supervisar.";
  const values = history.filter(item => item.latency_ms != null).slice(0, 30).reverse();
  $("latency-chart").innerHTML = values.length ? values.map(item => `<div class="bar" style="height:${Math.max(8, Math.min(150, item.latency_ms))}px" title="${esc(item.device_name)}: ${item.latency_ms} ms"></div>`).join("") : "Todavía no hay mediciones.";
  $("latency-chart").classList.toggle("empty", !values.length);
  list("overview-alerts", alerts.filter(item => item.state === "open"), item => `<div class="list-item"><i class="list-dot ${item.severity === "CRITICAL" ? "critical" : "alert"}"></i><div><b>${esc(item.device_name)} · ${esc(item.severity)}</b><p>${esc(item.message)}</p><small>${time(item.created_at)}</small></div></div>`, "No hay avisos abiertos.");
  list("events", events, item => `<div class="list-item"><i class="list-dot"></i><div><b>${esc(item.category)}${item.simulated ? " · EJEMPLO" : ""}</b><p>${esc(item.message)}</p><small>${time(item.created_at)}</small></div></div>`, "Aún no hay actividad.");
}

function renderNetwork(snapshot) {
  $("network-status-label").textContent = snapshot.connection.includes("Conectado") ? "CONEXIÓN IDENTIFICADA" : "REVISIÓN INCOMPLETA";
  $("network-connection").textContent = snapshot.connection;
  $("network-detail").textContent = snapshot.connection_detail;
  $("network-scan-time").textContent = `revisado ${time(snapshot.scanned_at)}`;
  $("network-gateway").textContent = snapshot.gateway;
  $("network-interface").textContent = snapshot.interface;
  $("network-address").textContent = snapshot.local_address;
  $("network-count").textContent = snapshot.device_count;
  $("discovery-note").textContent = snapshot.discovery_note;
  $("privacy-note").textContent = snapshot.privacy_note;
  list("network-devices", snapshot.devices, device => `<article class="network-device"><div class="network-device-top"><span class="device-avatar">${device.kind === "router" ? "⌂" : "◉"}</span><div><b>${esc(device.name)}</b><small>${esc(device.address)}</small></div></div><p>${esc(device.description)}</p><span class="device-state">${esc(device.status)}</span><div class="identifier">${esc(device.identifier)}</div></article>`, "No se detectaron otros equipos todavía. Conecta un dispositivo, navega unos segundos y vuelve a actualizar.");
}

function renderDevices(devices) {
  $("device-table").innerHTML = devices.length ? devices.map(device => `<tr><td><b>${esc(device.name)}</b><small>${esc(device.host)}</small></td><td>${esc(device.kind)}</td><td>${device.port ? `TCP/${device.port}` : "sin puerto TCP"}</td><td><span class="status ${device.status}">${device.status}</span></td><td>${device.simulated ? "EJEMPLO" : "agregado por ti"}</td><td><button class="secondary check" data-id="${device.id}">Comprobar</button></td></tr>`).join("") : '<tr><td colspan="6" class="empty">Todavía no has agregado equipos.</td></tr>';
  $("diagnostic-device").innerHTML = devices.length ? devices.map(device => `<option value="${device.id}">${esc(device.name)} · ${esc(device.host)}</option>`).join("") : "<option>Sin equipos</option>";
  document.querySelectorAll(".check").forEach(button => button.onclick = async () => { await api(`/api/devices/${button.dataset.id}/check`, {method:"POST"}); refresh(); });
}

function renderTopology(data) {
  $("topology-canvas").innerHTML = data.nodes.length ? data.nodes.map(node => `<div class="node ${node.status}"><span class="icon">${node.kind === "router" ? "◉" : node.kind === "switch" ? "▦" : "◆"}</span><b>${esc(node.name)}</b><small>${node.status} · ${node.simulated ? "EJEMPLO" : "AGREGADO"}</small></div>`).join("") : "Carga el ejemplo guiado para ver un mapa.";
  $("topology-canvas").classList.toggle("empty", !data.nodes.length);
}

async function refresh() {
  try {
    const [summary, history, alerts, events, devices, topology, incidents] = await Promise.all([
      api("/api/summary"), api("/api/measurements?limit=120"), api("/api/alerts"), api("/api/events"), api("/api/devices"), api("/api/topology"), api("/api/incidents")
    ]);
    renderOverview(summary, history, alerts, events); renderDevices(devices); renderTopology(topology);
    list("alert-list", alerts, item => `<div class="list-item"><i class="list-dot ${item.severity === "CRITICAL" ? "critical" : "alert"}"></i><div><b>${esc(item.device_name)} · ${esc(item.rule_code)} · ${esc(item.severity)}</b><p>${esc(item.message)}</p><small>${item.state} · ${time(item.updated_at)}</small></div></div>`, "No hay avisos registrados.");
    list("incident-list", incidents, item => `<div class="list-item"><i class="list-dot ${item.state === "open" ? "critical" : ""}"></i><div><b>${esc(item.device_name)} · ${esc(item.title)}</b><p>${esc(item.note || "Sin nota")}</p><small>${item.state} · ${time(item.opened_at)}</small></div></div>`, "Sin incidentes registrados.");
    list("performance-list", history.slice(0, 30), item => `<div class="list-item"><i class="list-dot ${item.success ? "" : "critical"}"></i><div><b>${esc(item.device_name)} · ${item.success ? "respuesta registrada" : "no respondió"}${item.simulated ? " · EJEMPLO" : ""}</b><p>Tiempo de respuesta: ${item.latency_ms ?? "—"} ms · Pérdida: ${item.loss_percent}% · ${esc(item.error || "sin error")}</p><small>${time(item.measured_at)}</small></div></div>`, "No hay mediciones para analizar.");
  } catch (error) { $("connection").textContent = "Sin conexión"; }
}

async function scanNetwork() {
  const button = $("scan-network");
  button.disabled = true; button.textContent = "Revisando tu red…";
  try { renderNetwork(await api("/api/network/discovery")); }
  catch (error) { $("network-detail").textContent = "No pudimos consultar la información local. Inténtalo otra vez."; }
  finally { button.disabled = false; button.textContent = "↻ Actualizar dispositivos"; }
}

document.querySelectorAll("nav a").forEach(link => link.onclick = () => {
  document.querySelector("nav a.active").classList.remove("active"); link.classList.add("active");
  document.querySelector(".view.active").classList.remove("active"); $(link.dataset.view).classList.add("active"); $("section-name").textContent = link.textContent.trim().replace(/^[^ ]+ /, "");
  if (link.dataset.view === "my-network") scanNetwork();
});
$("reload").onclick = refresh;
$("scan-network").onclick = scanNetwork;
$("load-lab").onclick = async () => { await api("/api/lab/load", {method:"POST"}); refresh(); };
document.querySelectorAll(".scenario-buttons button").forEach(button => button.onclick = async () => { await api("/api/lab/run", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({scenario:button.dataset.scenario})}); refresh(); });
$("clear-lab").onclick = async () => { await api("/api/lab", {method:"DELETE"}); refresh(); };
$("add-device").onclick = $("add-device-2").onclick = () => $("device-modal").showModal();
$("device-modal").querySelector(".close").onclick = () => $("device-modal").close();
$("device-form").onsubmit = async event => {
  event.preventDefault(); const form = Object.fromEntries(new FormData(event.target));
  if (!form.port) delete form.port; form.port = form.port ? Number(form.port) : undefined; form.latency_warning_ms = Number(form.latency_warning_ms); form.loss_warning_percent = Number(form.loss_warning_percent);
  try { await api("/api/devices", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(form)}); $("device-modal").close(); refresh(); }
  catch (error) { $("form-error").textContent = error.message; }
};
$("run-diagnostic").onclick = async () => { const id = $("diagnostic-device").value; if (id) $("diagnostic-result").textContent = JSON.stringify(await api(`/api/diagnostics/${id}`), null, 2); };
refresh();
