let activeChatId = null;
let subjects = [];
let skills = [];
let applications = [];
let studyPlans = [];
let expandedUnitKeys = new Set();
let expandedSubjectIds = new Set();
let initializedSubjectUnitDefaults = new Set();
let reminderPollTimer = null;
let speechRecognition = null;
let isMicListening = false;
let reminderAudio = null;
let planningSwRegistration = null;

const APP_STATUSES = ["Preparing", "Applied", "Interviewing", "Offered", "Rejected"];

window.onload = async function () {
    const page = document.body.dataset.page;

    if (page === "dashboard") {
        await loadDashboardData();
    }

    if (page === "academic") {
        initAcademicModeSelector();
        document.getElementById("subjectForm").addEventListener("submit", onAddSubject);
        document.getElementById("syllabusImportForm").addEventListener("submit", onImportSyllabus);
        await loadSubjects();
    }

    if (page === "skills") {
        document.getElementById("skillForm").addEventListener("submit", onAddSkill);
        await loadSkills();
    }

    if (page === "placement") {
        document.getElementById("applicationForm").addEventListener("submit", onAddApplication);
        await loadApplications();
    }

    if (page === "planning") {
        document.getElementById("planForm").addEventListener("submit", onAddPlan);
        bindVoiceReminderEvents();
        await loadPlans();
        await loadReminders();
        startReminderPolling();
    }

    if (page === "tutor") {
        bindTutorEvents();
        await loadChats();
    }

    runRevealAnimations();
};

async function requestJSON(url, options = {}) {
    const method = (options.method || "GET").toUpperCase();
    const finalOptions = { ...options };
    if (method === "GET" && !finalOptions.cache) {
        finalOptions.cache = "no-store";
    }

    const response = await fetch(url, finalOptions);

    if (!response.ok) {
        let message = `${response.status} ${response.statusText}`;
        try {
            const data = await response.json();
            message = data.message || data.error || message;
        } catch (_) {
            // ignore parse error
        }
        throw new Error(message);
    }

    if (response.status === 204) return null;
    return response.json();
}

function escapeHtml(text) {
    if (text === null || text === undefined) return "";
    return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/\"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function showError(containerId, message) {
    const target = document.getElementById(containerId);
    if (!target) return;
    target.innerHTML = `<div class="error-box">${escapeHtml(message)}</div>`;
}

function runRevealAnimations() {
    const items = document.querySelectorAll(".panel, .list-item, .list-item-block, .chip-card, .message");
    items.forEach((item) => {
        item.classList.add("reveal");
        // Safe default: keep content visible even if observer callback is delayed/missed.
        item.classList.add("in");
    });

    if (!("IntersectionObserver" in window)) {
        return;
    }

    const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            if (entry.isIntersecting) {
                entry.target.classList.add("in");
            }
        });
    }, { threshold: 0.1 });

    items.forEach((item) => observer.observe(item));
}

function initAcademicModeSelector() {
    const radios = document.querySelectorAll("input[name='academicMode']");
    const manualPanel = document.getElementById("manualPanel");
    const automaticPanel = document.getElementById("automaticPanel");
    const importStatusPanel = document.getElementById("importStatusPanel");
    if (!radios.length || !manualPanel || !automaticPanel) return;

    const applyMode = (mode) => {
        const isManual = mode === "manual";
        manualPanel.classList.toggle("hidden", !isManual);
        automaticPanel.classList.toggle("hidden", isManual);
        if (importStatusPanel) importStatusPanel.classList.toggle("hidden", isManual);
    };

    radios.forEach((radio) => {
        radio.addEventListener("change", () => {
            if (radio.checked) applyMode(radio.value);
        });
    });

    const selected = Array.from(radios).find((r) => r.checked)?.value || "manual";
    applyMode(selected);
}

function animateCounter(el, target, suffix = "") {
    const start = 0;
    const duration = 650;
    const startedAt = performance.now();

    function tick(now) {
        const progress = Math.min((now - startedAt) / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3);
        const value = Math.round(start + (target - start) * eased);
        el.textContent = `${value}${suffix}`;
        if (progress < 1) requestAnimationFrame(tick);
    }

    requestAnimationFrame(tick);
}

/* ---------------- Dashboard ---------------- */
async function loadDashboardData() {
    try {
        const [s, sk, a, p] = await Promise.all([
            requestJSON("/api/subjects"),
            requestJSON("/api/skills"),
            requestJSON("/api/applications"),
            requestJSON("/api/study-plans")
        ]);

        subjects = s || [];
        skills = sk || [];
        applications = a || [];
        studyPlans = p || [];

        renderDashboard();
    } catch (error) {
        showError("dashboardStats", error.message);
    }
}

function renderDashboard() {
    const totalTopics = subjects.flatMap((x) => x.topics || []).length;
    const doneTopics = subjects.flatMap((x) => x.topics || []).filter((x) => x.isCompleted).length;
    const progress = totalTopics ? Math.round((doneTopics / totalTopics) * 100) : 0;

    const stats = [
        { label: "Academic Progress", value: progress, suffix: "%" },
        { label: "Skills Tracked", value: skills.length, suffix: "" },
        { label: "Applications", value: applications.length, suffix: "" },
        { label: "Active Plans", value: studyPlans.filter((x) => !x.isCompleted).length, suffix: "" }
    ];

    const statsEl = document.getElementById("dashboardStats");
    if (statsEl) {
        statsEl.innerHTML = stats.map((s) => `
            <div class="panel stat-card">
                <div class="stat-value" data-value="${s.value}" data-suffix="${s.suffix}">0${s.suffix}</div>
                <div class="stat-label">${escapeHtml(s.label)}</div>
            </div>
        `).join("");

        statsEl.querySelectorAll(".stat-value").forEach((el) => {
            const value = Number(el.dataset.value || 0);
            const suffix = el.dataset.suffix || "";
            animateCounter(el, value, suffix);
        });
    }

    const plansEl = document.getElementById("dashboardPlans");
    if (plansEl) {
        const nextPlans = [...studyPlans]
            .sort((a, b) => new Date(a.targetDate || "2999-12-31") - new Date(b.targetDate || "2999-12-31"))
            .slice(0, 5);

        plansEl.innerHTML = nextPlans.length
            ? nextPlans.map((p) => `
                <div class="list-item">
                    <div>
                        <strong>${escapeHtml(p.title)}</strong>
                        <div class="muted">${escapeHtml(p.description || "No description")}</div>
                    </div>
                    <span class="badge">${p.targetDate ? new Date(p.targetDate).toLocaleDateString() : "No date"}</span>
                </div>
            `).join("")
            : `<div class="muted">No plans yet.</div>`;
    }

    const appEl = document.getElementById("dashboardApps");
    if (appEl) {
        appEl.innerHTML = APP_STATUSES.map((status) => {
            const count = applications.filter((x) => (x.status || "").toLowerCase() === status.toLowerCase()).length;
            return `<div class="list-item"><span>${escapeHtml(status)}</span><span class="badge">${count}</span></div>`;
        }).join("");
    }

    runRevealAnimations();
}

/* ---------------- Academic ---------------- */
async function loadSubjects() {
    try {
        const data = await requestJSON("/api/subjects");
        if (!Array.isArray(data)) {
            throw new Error("Unexpected subjects response from server.");
        }
        subjects = data;
        renderSubjects();
    } catch (error) {
        showError("subjectList", error.message);
    }
}

async function onAddSubject(event) {
    event.preventDefault();
    const name = document.getElementById("subjectName").value.trim();
    const semester = document.getElementById("subjectSemester").value.trim();
    if (!name || !semester) return;

    try {
        const created = await requestJSON("/api/subjects", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, semester, proficiencyLevel: 0 })
        });

        if (created && typeof created === "object") {
            subjects = [created, ...(Array.isArray(subjects) ? subjects : [])];
            renderSubjects();
        }
        event.target.reset();
        await loadSubjects();
    } catch (error) {
        showError("subjectList", error.message);
    }
}

async function onImportSyllabus(event) {
    event.preventDefault();
    const name = document.getElementById("importSubjectName").value.trim();
    const semester = document.getElementById("importSubjectSemester").value.trim();
    const fileInput = document.getElementById("syllabusFile");
    const file = fileInput.files && fileInput.files[0];
    if (!name || !semester || !file) return;

    const form = new FormData();
    form.append("name", name);
    form.append("semester", semester);
    form.append("proficiencyLevel", "0");
    form.append("syllabus", file);

    const status = document.getElementById("importStatus");
    if (status) status.innerHTML = `<div class="muted">Importing syllabus...</div>`;

    try {
        const data = await requestJSON("/api/subjects/import-syllabus", {
            method: "POST",
            body: form
        });

        event.target.reset();
        if (status) {
            const summary = data.summary || {};
            status.innerHTML = `
                <div class="list-item-block">
                    <strong>Import complete</strong>
                    <div class="muted">Units: ${summary.unitsCreated || 0}</div>
                    <div class="muted">Topics: ${summary.topicsCreated || 0}</div>
                </div>
            `;
        }
        await loadSubjects();
    } catch (error) {
        if (status) status.innerHTML = `<div class="error-box">${escapeHtml(error.message)}</div>`;
    }
}

function renderSubjects() {
    const el = document.getElementById("subjectList");
    if (!el) return;

    if (!subjects.length) {
        el.innerHTML = `<div class="muted">No subjects yet.</div>`;
        return;
    }

    try {
        el.innerHTML = subjects.map((subject) => {
            const total = (subject.topics || []).length;
            const done = (subject.topics || []).filter((x) => x.isCompleted).length;
            const progress = total ? Math.round((done / total) * 100) : 0;
            const units = Array.isArray(subject.units) ? subject.units : [];
            const subjectExpanded = expandedSubjectIds.has(subject.id);
            const assignedTopicIds = new Set(units.flatMap((u) => ((u && u.topics) || []).map((t) => t.id)));
            const unassigned = (subject.topics || []).filter((t) => !assignedTopicIds.has(t.id));
            const allUnits = [...units];
            if (unassigned.length) {
                allUnits.push({ id: null, name: "General Topics", topics: unassigned });
            }

            if (!initializedSubjectUnitDefaults.has(subject.id)) {
                initializedSubjectUnitDefaults.add(subject.id);
            }

            const unitsHtml = allUnits.map((unit) => {
                const unitKey = `${subject.id}:${(unit && unit.id) !== null && (unit && unit.id) !== undefined ? unit.id : "general"}`;
                const isExpanded = expandedUnitKeys.has(unitKey);
                const unitTopics = (unit && unit.topics) || [];
                const unitRows = unitTopics.map((topic) => `
                    <tr>
                        <td>
                            <label>
                                <input type="checkbox" ${topic.isCompleted ? "checked" : ""} onchange="toggleTopic(${topic.id}, this.checked)">
                                ${escapeHtml(topic.name)}
                            </label>
                        </td>
                        <td class="row-actions">
                            <button type="button" class="danger" onclick="deleteTopic(${topic.id})">Delete</button>
                        </td>
                    </tr>
                `).join("");

                return `
                    <div class="panel">
                        <div class="subject-header unit-header-row">
                            <button type="button" class="unit-toggle" onclick="toggleUnitPanel('${unitKey}')">
                                <span class="chevron">${isExpanded ? "▾" : "▸"}</span>
                                <strong>${escapeHtml((unit && unit.name) || "Unit")}</strong>
                                <span class="badge">${unitTopics.length}</span>
                            </button>
                        </div>
                        <div class="unit-body ${isExpanded ? "" : "hidden"}">
                            <table class="module-table">
                                <thead>
                                    <tr>
                                        <th>Topics</th>
                                        <th>Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${unitRows || `<tr><td colspan="2" class="muted">No topics yet.</td></tr>`}
                                </tbody>
                            </table>
                            <form class="topic-form" onsubmit="return addTopic(event, ${subject.id}, ${unit && unit.id === null ? "null" : (unit ? unit.id : "null")})">
                                <input type="text" placeholder="Add topic to ${escapeHtml((unit && unit.name) || "unit")}" required>
                                <button type="submit">Add</button>
                            </form>
                        </div>
                    </div>
                `;
            }).join("");

            return `
                <div class="list-item-block">
                    <div class="subject-header subject-header-row">
                        <button type="button" class="subject-toggle" onclick="toggleSubjectPanel(${subject.id})">
                            <span class="chevron">${subjectExpanded ? "▾" : "▸"}</span>
                            <strong>${escapeHtml(subject.name)}</strong>
                            <span class="muted">${escapeHtml(subject.semester)} - ${progress}%</span>
                        </button>
                        <button type="button" class="danger" onclick="deleteSubject(${subject.id})">Delete</button>
                    </div>
                    <div class="subject-body ${subjectExpanded ? "" : "hidden"}">
                        <div class="progress"><div style="width:${progress}%"></div></div>
                        <form class="topic-form" onsubmit="return addUnit(event, ${subject.id})">
                            <input type="text" placeholder="Add unit (e.g. Unit 1: Graphs)" required>
                            <button type="submit">Add Unit</button>
                        </form>
                        <div class="panel-grid">${unitsHtml || `<div class="muted">No units yet. Add one or import syllabus.</div>`}</div>
                    </div>
                </div>
            `;
        }).join("");
    } catch (error) {
        el.innerHTML = `<div class="error-box">Failed to render subjects. Please refresh and try again.</div>`;
    }

    runRevealAnimations();
}

function toggleUnitPanel(unitKey) {
    if (expandedUnitKeys.has(unitKey)) {
        expandedUnitKeys.delete(unitKey);
    } else {
        expandedUnitKeys.add(unitKey);
    }
    renderSubjects();
}

function toggleSubjectPanel(subjectId) {
    if (expandedSubjectIds.has(subjectId)) {
        expandedSubjectIds.delete(subjectId);
    } else {
        expandedSubjectIds.add(subjectId);
    }
    renderSubjects();
}

async function addUnit(event, subjectId) {
    event.preventDefault();
    const input = event.target.querySelector("input");
    const raw = input.value.trim();
    if (!raw) return false;

    const match = raw.match(/^unit\s*([0-9ivxlc]+)\s*[:.)-]?\s*(.*)$/i);
    const unitNo = match ? match[1] : "";
    const name = match ? (match[2] || `Unit ${unitNo}`) : raw;

    await requestJSON(`/api/subjects/${subjectId}/units`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, unitNo })
    });

    event.target.reset();
    await loadSubjects();
    return false;
}

async function addTopic(event, subjectId, unitId = null) {
    event.preventDefault();
    const input = event.target.querySelector("input");
    const name = input.value.trim();
    if (!name) return false;

    await requestJSON(`/api/subjects/${subjectId}/topics`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, unitId, isCompleted: false, confidence: 0 })
    });

    event.target.reset();
    await loadSubjects();
    return false;
}

async function toggleTopic(topicId, isCompleted) {
    await requestJSON(`/api/topics/${topicId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ isCompleted })
    });
    await loadSubjects();
}

async function deleteTopic(topicId) {
    await requestJSON(`/api/topics/${topicId}`, { method: "DELETE" });
    await loadSubjects();
}

async function deleteSubject(subjectId) {
    await requestJSON(`/api/subjects/${subjectId}`, { method: "DELETE" });
    await loadSubjects();
}

/* ---------------- Skills ---------------- */
async function loadSkills() {
    try {
        skills = await requestJSON("/api/skills");
        renderSkills();
    } catch (error) {
        showError("skillList", error.message);
    }
}

async function onAddSkill(event) {
    event.preventDefault();
    const name = document.getElementById("skillName").value.trim();
    const category = document.getElementById("skillCategory").value;
    const proficiencyLevel = Number(document.getElementById("skillProficiency").value || 0);
    if (!name) return;

    await requestJSON("/api/skills", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, category, proficiencyLevel })
    });

    event.target.reset();
    document.getElementById("skillProficiency").value = "10";
    await loadSkills();
}

function renderSkills() {
    const el = document.getElementById("skillList");
    if (!el) return;

    if (!skills.length) {
        el.innerHTML = `<div class="muted">No skills yet.</div>`;
        return;
    }

    el.innerHTML = skills.map((skill) => `
        <div class="chip-card">
            <div class="chip-head">
                <strong>${escapeHtml(skill.name)}</strong>
                <button type="button" class="danger" onclick="deleteSkill(${skill.id})">Delete</button>
            </div>
            <div class="muted">${escapeHtml(skill.category)}</div>
            <div class="progress"><div style="width:${Math.max(0, Math.min(100, skill.proficiencyLevel || 0))}%"></div></div>
            <div class="muted">${skill.proficiencyLevel || 0}%</div>
        </div>
    `).join("");

    runRevealAnimations();
}

async function deleteSkill(skillId) {
    await requestJSON(`/api/skills/${skillId}`, { method: "DELETE" });
    await loadSkills();
}

/* ---------------- Placement ---------------- */
async function loadApplications() {
    try {
        applications = await requestJSON("/api/applications");
        renderApplications();
    } catch (error) {
        showError("applicationBoard", error.message);
    }
}

async function onAddApplication(event) {
    event.preventDefault();
    const company = document.getElementById("appCompany").value.trim();
    const role = document.getElementById("appRole").value.trim();
    const status = document.getElementById("appStatus").value;
    if (!company || !role) return;

    await requestJSON("/api/applications", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ company, role, status })
    });

    event.target.reset();
    await loadApplications();
}

function renderApplications() {
    const el = document.getElementById("applicationBoard");
    if (!el) return;

    el.innerHTML = APP_STATUSES.map((status) => {
        const col = applications.filter((x) => (x.status || "").toLowerCase() === status.toLowerCase());
        const cards = col.map((app) => `
            <div class="list-item-block">
                <strong>${escapeHtml(app.company)}</strong>
                <div class="muted">${escapeHtml(app.role)}</div>
                <div class="row-actions">
                    <button type="button" onclick="moveApplication(${app.id}, '${nextStatus(status)}')">Move</button>
                    <button type="button" class="danger" onclick="deleteApplication(${app.id})">Delete</button>
                </div>
            </div>
        `).join("");

        return `
            <div class="panel">
                <h3>${escapeHtml(status)} <span class="badge">${col.length}</span></h3>
                <div class="list-container">${cards || `<div class="muted">Empty</div>`}</div>
            </div>
        `;
    }).join("");

    runRevealAnimations();
}

function nextStatus(current) {
    const index = APP_STATUSES.indexOf(current);
    if (index < 0) return "Applied";
    return APP_STATUSES[(index + 1) % APP_STATUSES.length];
}

async function moveApplication(appId, status) {
    await requestJSON(`/api/applications/${appId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status })
    });
    await loadApplications();
}

async function deleteApplication(appId) {
    await requestJSON(`/api/applications/${appId}`, { method: "DELETE" });
    await loadApplications();
}

/* ---------------- Planning ---------------- */
async function loadPlans() {
    try {
        studyPlans = await requestJSON("/api/study-plans");
        renderPlans();
    } catch (error) {
        showError("planList", error.message);
    }
}

async function onAddPlan(event) {
    event.preventDefault();
    const title = document.getElementById("planTitle").value.trim();
    const description = document.getElementById("planDescription").value.trim();
    const date = document.getElementById("planDate").value;
    if (!title) return;

    await requestJSON("/api/study-plans", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, description, targetDate: date || undefined, isCompleted: false })
    });

    event.target.reset();
    await loadPlans();
}

function bindVoiceReminderEvents() {
    const micBtn = document.getElementById("voiceMicBtn");
    const form = document.getElementById("voiceReminderForm");
    const status = document.getElementById("voiceReminderStatus");
    const pushBtn = document.getElementById("enableDesktopNotifyBtn");
    if (!micBtn || !form) return;

    form.addEventListener("submit", onCreateVoiceReminder);
    if (pushBtn) {
        pushBtn.addEventListener("click", async () => {
            await enableDesktopPush();
        });
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        micBtn.disabled = true;
        if (status) status.textContent = "Voice input is not supported in this browser.";
        return;
    }

    speechRecognition = new SpeechRecognition();
    speechRecognition.lang = "en-IN";
    speechRecognition.interimResults = true;
    speechRecognition.continuous = false;

    speechRecognition.onstart = () => {
        isMicListening = true;
        micBtn.textContent = "Stop Mic";
        if (status) status.textContent = "Listening...";
    };

    speechRecognition.onend = () => {
        isMicListening = false;
        micBtn.textContent = "Start Mic";
        if (status) status.textContent = "Transcript captured. Edit and submit.";
    };

    speechRecognition.onerror = () => {
        isMicListening = false;
        micBtn.textContent = "Start Mic";
        if (status) status.textContent = "Voice capture failed. Please try again.";
    };

    speechRecognition.onresult = (event) => {
        const transcript = Array.from(event.results)
            .map((result) => result[0]?.transcript || "")
            .join(" ")
            .trim();
        const input = document.getElementById("voiceTranscriptInput");
        if (input) input.value = transcript;
    };

    micBtn.addEventListener("click", () => {
        try {
            if (isMicListening) speechRecognition.stop();
            else speechRecognition.start();
        } catch (_) {
            // Ignore transient recognition state errors.
        }
    });
}

function urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; i += 1) {
        outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
}

async function enableDesktopPush() {
    const status = document.getElementById("voiceReminderStatus");
    if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
        if (status) status.textContent = "Desktop push is not supported in this browser.";
        return;
    }
    if (window.location.protocol !== "https:" && window.location.hostname !== "localhost") {
        if (status) status.textContent = "Desktop push requires HTTPS (or localhost).";
        return;
    }

    try {
        const keyData = await requestJSON("/api/push/public-key");
        const publicKey = keyData.publicKey;
        if (!publicKey) {
            if (status) status.textContent = "Push is not configured on server.";
            return;
        }

        const permission = await Notification.requestPermission();
        if (permission !== "granted") {
            if (status) status.textContent = "Desktop notification permission not granted.";
            return;
        }

        planningSwRegistration = planningSwRegistration || await navigator.serviceWorker.register("/static/sw.js");
        let subscription = await planningSwRegistration.pushManager.getSubscription();
        if (!subscription) {
            subscription = await planningSwRegistration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: urlBase64ToUint8Array(publicKey),
            });
        }

        await requestJSON("/api/push/subscribe", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ subscription }),
        });
        if (status) status.textContent = "Desktop alerts enabled.";
    } catch (error) {
        if (status) status.textContent = `Failed to enable desktop alerts: ${error.message}`;
    }
}

async function onCreateVoiceReminder(event) {
    event.preventDefault();
    const input = document.getElementById("voiceTranscriptInput");
    const status = document.getElementById("voiceReminderStatus");
    const transcript = (input?.value || "").trim();
    if (!transcript) return;

    if (status) status.textContent = "Creating reminder...";
    try {
        const data = await requestJSON("/create_voice_reminder", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ transcript })
        });
        if (status) status.textContent = data.message || "Reminder created.";
        event.target.reset();
        await loadReminders();
    } catch (error) {
        if (status) status.textContent = error.message;
    }
}

function startReminderPolling() {
    const page = document.body.dataset.page;
    if (page !== "planning") return;
    if (reminderPollTimer) clearInterval(reminderPollTimer);

    const tick = async () => {
        try {
            const data = await requestJSON("/check_notifications");
            const notifications = data.notifications || [];
            notifications.forEach((note) => showReminderNotification(note));
        } catch (_) {
            // Polling errors are non-fatal; keep interval active.
        }
    };

    tick();
    reminderPollTimer = setInterval(tick, 30000);
}

function playReminderTone() {
    try {
        if (!reminderAudio) {
            reminderAudio = new Audio("/static/audio/mixkit-bell-notification-933.wav");
            reminderAudio.preload = "auto";
        }
        reminderAudio.currentTime = 0;
        const playPromise = reminderAudio.play();
        if (playPromise && typeof playPromise.catch === "function") {
            playPromise.catch(() => {});
        }
        setTimeout(() => {
            if (!reminderAudio) return;
            reminderAudio.pause();
            reminderAudio.currentTime = 0;
        }, 3000);
    } catch (_) {
        // Ignore audio playback errors silently.
    }
}

function showReminderNotification(note) {
    const modal = document.getElementById("reminderModal");
    const body = document.getElementById("notifyBody");
    const closeBtn = document.getElementById("notifyCloseBtn");
    if (!modal || !body || !closeBtn) return;

    const title = escapeHtml(note.title || "Reminder");
    const deadline = escapeHtml(note.deadlineDatetime || "");
    body.innerHTML = `<strong>${title}</strong><br>Deadline: ${deadline}`;
    modal.classList.remove("hidden");
    playReminderTone();

    closeBtn.onclick = () => {
        modal.classList.add("hidden");
    };
}

async function loadReminders() {
    const el = document.getElementById("reminderList");
    if (!el) return;
    try {
        const data = await requestJSON("/api/reminders");
        const reminders = data.reminders || [];
        renderReminders(reminders);
    } catch (error) {
        el.innerHTML = `<div class="error-box">${escapeHtml(error.message)}</div>`;
    }
}

function renderReminders(reminders) {
    const el = document.getElementById("reminderList");
    if (!el) return;
    if (!reminders.length) {
        el.innerHTML = `<div class="muted">No reminders yet.</div>`;
        return;
    }

    el.innerHTML = reminders.map((r) => `
        <div class="list-item">
            <div>
                <strong>${escapeHtml(r.title)}</strong>
                <div class="muted">Deadline: ${escapeHtml(r.deadlineDatetime)}</div>
                <div class="muted">Remind at: ${escapeHtml(r.reminderTime)} | ${escapeHtml(r.status)}</div>
            </div>
            <button type="button" class="danger" onclick="deleteReminder(${r.id})">Delete</button>
        </div>
    `).join("");
    runRevealAnimations();
}

async function deleteReminder(reminderId) {
    await requestJSON(`/api/reminders/${reminderId}`, { method: "DELETE" });
    await loadReminders();
}

function renderPlans() {
    const el = document.getElementById("planList");
    if (!el) return;

    if (!studyPlans.length) {
        el.innerHTML = `<div class="muted">No plans yet.</div>`;
        return;
    }

    el.innerHTML = studyPlans.map((plan) => `
        <div class="list-item">
            <label class="plan-title ${plan.isCompleted ? "done" : ""}">
                <input type="checkbox" ${plan.isCompleted ? "checked" : ""} onchange="togglePlan(${plan.id}, this.checked)">
                ${escapeHtml(plan.title)}
            </label>
            <span class="badge">${plan.targetDate ? new Date(plan.targetDate).toLocaleDateString() : "No date"}</span>
            <button type="button" class="danger" onclick="deletePlan(${plan.id})">Delete</button>
        </div>
    `).join("");

    runRevealAnimations();
}

async function togglePlan(planId, isCompleted) {
    await requestJSON(`/api/study-plans/${planId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ isCompleted })
    });
    await loadPlans();
}

async function deletePlan(planId) {
    await requestJSON(`/api/study-plans/${planId}`, { method: "DELETE" });
    await loadPlans();
}

/* ---------------- Tutor ---------------- */
function bindTutorEvents() {
    document.getElementById("newChatBtn").addEventListener("click", createNewChat);
    document.getElementById("sendBtn").addEventListener("click", sendMessage);

    const input = document.getElementById("messageInput");
    input.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            sendMessage();
        }
    });
}

async function createNewChat() {
    const data = await requestJSON("/new_chat", { method: "POST" });
    activeChatId = data.chat_id;
    await loadChats();
    await loadChat(activeChatId);
}

async function loadChats() {
    const list = document.getElementById("chatList");
    if (!list) return;

    const chats = await requestJSON("/chats");
    list.innerHTML = "";

    chats.forEach((chat) => {
        const wrapper = document.createElement("div");
        wrapper.className = "chat-item";
        if (chat[0] === activeChatId) wrapper.classList.add("active");

        const title = document.createElement("span");
        title.innerText = chat[1];
        title.onclick = () => loadChat(chat[0]);

        const editBtn = document.createElement("span");
        editBtn.innerHTML = "&#9998;";
        editBtn.className = "edit-btn";
        editBtn.onclick = (event) => {
            event.stopPropagation();
            enableRename(chat[0], wrapper, chat[1]);
        };

        const deleteBtn = document.createElement("span");
        deleteBtn.innerHTML = "&times;";
        deleteBtn.className = "delete-btn";
        deleteBtn.onclick = (event) => {
            event.stopPropagation();
            deleteChat(chat[0]);
        };

        wrapper.appendChild(title);
        wrapper.appendChild(editBtn);
        wrapper.appendChild(deleteBtn);
        list.appendChild(wrapper);
    });

    if (!activeChatId && chats.length > 0) {
        activeChatId = chats[0][0];
        await loadChat(activeChatId);
    }

    runRevealAnimations();
}

async function loadChat(chatId) {
    activeChatId = chatId;
    const box = document.getElementById("messages");
    if (!box) return;

    const messages = await requestJSON(`/chat/${chatId}`);
    box.innerHTML = "";

    messages.forEach((msg) => {
        const role = (msg[0] === "model" || msg[0] === "assistant") ? "ai" : msg[0];
        appendMessage(role, msg[1]);
    });

    scrollToBottom();
    await loadChats();
}

async function sendMessage() {
    const input = document.getElementById("messageInput");
    const message = input.value.trim();
    if (!message || !activeChatId) return;

    appendMessage("user", message);
    input.value = "";

    const box = document.getElementById("messages");
    const aiDiv = document.createElement("div");
    aiDiv.className = "message ai";
    box.appendChild(aiDiv);
    scrollToBottom();

    const response = await fetch("/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chat_id: activeChatId, message })
    });

    if (!response.ok || !response.body) {
        aiDiv.innerHTML = "Server error occurred.";
        return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let fullText = "";
    let buffer = "";

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() || "";

        chunks.forEach((chunk) => {
            const lines = chunk.split("\n").filter((line) => line.startsWith("data: "));
            if (!lines.length) return;

            const text = lines.map((line) => line.slice(6)).join("\n");
            if (text.startsWith("ERROR")) {
                aiDiv.innerHTML = escapeHtml(text);
                return;
            }

            fullText += text;
            aiDiv.innerHTML = formatMarkdown(fullText) + '<span class="cursor"></span>';
            if (typeof hljs !== "undefined") hljs.highlightAll();
            scrollToBottom();
        });
    }

    aiDiv.innerHTML = formatMarkdown(fullText);
    await loadChats();
}

async function deleteChat(chatId) {
    await requestJSON(`/delete_chat/${chatId}`, { method: "POST" });
    if (chatId === activeChatId) {
        activeChatId = null;
        const box = document.getElementById("messages");
        if (box) box.innerHTML = "";
    }
    await loadChats();
}

function appendMessage(role, content) {
    const box = document.getElementById("messages");
    if (!box) return;

    const div = document.createElement("div");
    div.className = `message ${role}`;
    div.innerHTML = role === "user" ? escapeHtml(content) : formatMarkdown(content);
    box.appendChild(div);
    runRevealAnimations();
}

function formatMarkdown(text) {
    return marked.parse(text || "");
}

function scrollToBottom() {
    const box = document.getElementById("messages");
    if (box) box.scrollTop = box.scrollHeight;
}

function enableRename(chatId, wrapper, oldTitle) {
    wrapper.innerHTML = "";

    const input = document.createElement("input");
    input.type = "text";
    input.value = oldTitle;
    input.className = "rename-input";

    input.onkeydown = async function (event) {
        if (event.key === "Enter") {
            const title = input.value.trim();
            if (!title) return;

            await requestJSON(`/rename_chat/${chatId}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ title })
            });

            await loadChats();
        }
    };

    wrapper.appendChild(input);
    input.focus();
}
