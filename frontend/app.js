/* ═══════════════════════════════════════════════════════════════════════════
   VoxGuard — Dashboard Application Logic
   WebSocket client, Chart.js graph, mic input (pitch/volume), alert flow
   ═══════════════════════════════════════════════════════════════════════════ */

// ── Configuration ───────────────────────────────────────────────────────────

const CONFIG = {
    WS_URL: `ws://${window.location.host}/ws/monitor`,
    API_BASE: window.location.origin,
    CHART_MAX_POINTS: 120,         // 60 seconds at 2 readings/sec
    STRAIN_THRESHOLD: 0.57,
    RECONNECT_DELAY_MS: 3000,
    MIC_UPDATE_INTERVAL_MS: 100,
    MIC_CHART_INTERVAL_MS: 500,    // Push mic data to chart every 500ms
};


// ── State ───────────────────────────────────────────────────────────────────

let ws = null;
let strainChart = null;
let audioContext = null;
let analyserNode = null;
let micStream = null;
let currentPitch = 0;
let currentVolume = 0;
let currentStrain = 0;
let alertActive = false;
let receivingServerData = false;   // true when Arduino/server is sending data
let lastServerDataTime = 0;
let lastHeartRate = null;          // latest HR from server/simulator
let lastSpO2 = null;               // latest SpO2 from server/simulator


// ── Initialisation ──────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    initChart();
    connectWebSocket();
    initMicrophone();
    addLog('System Initialized', 'normal');
});


// ── WebSocket ───────────────────────────────────────────────────────────────

function connectWebSocket() {
    ws = new WebSocket(CONFIG.WS_URL);

    ws.onopen = () => {
        updateConnectionStatus(true);
        addLog('WebSocket connected', 'normal');
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        receivingServerData = true;
        lastServerDataTime = Date.now();
        handleIncomingData(data);
    };

    ws.onclose = () => {
        updateConnectionStatus(false);
        receivingServerData = false;
        addLog('WebSocket disconnected — reconnecting...', 'warning');
        setTimeout(connectWebSocket, CONFIG.RECONNECT_DELAY_MS);
    };

    ws.onerror = () => {
        addLog('WebSocket error', 'critical');
    };
}

function updateConnectionStatus(connected) {
    const dot = document.querySelector('#connection-status .status-dot');
    const text = document.querySelector('#connection-status .status-text');
    if (connected) {
        dot.classList.add('connected');
        text.textContent = 'CONNECTED';
    } else {
        dot.classList.remove('connected');
        text.textContent = 'DISCONNECTED';
    }
}


// ── Data Handler (Server / Arduino data) ────────────────────────────────────

function handleIncomingData(data) {
    // Only update HR and SpO2 from server/simulator data
    // Pitch, volume, and strain come from the local microphone
    updateMetricCard('hr-value', data.heart_rate != null ? data.heart_rate : '--');
    updateMetricCard('spo2-value', data.spo2 != null ? data.spo2 : '--');

    // Save latest HR/SpO2 for use in mic-triggered alerts
    if (data.heart_rate != null) lastHeartRate = data.heart_rate;
    if (data.spo2 != null) lastSpO2 = data.spo2;

    // Apply alert styling to cards
    applyAlertStyling(data.alert_level);

    // Log the reading
    if (data.alert_level === 'critical') {
        addLog(`CRITICAL — HR:${data.heart_rate} SpO2:${data.spo2}% Strain:${currentStrain.toFixed(2)}`, 'critical');
    } else if (data.alert_level === 'warning') {
        addLog(`WARNING — HR:${data.heart_rate} SpO2:${data.spo2}% Strain:${currentStrain.toFixed(2)}`, 'warning');
    }

    // Trigger alert modal if threshold breached
    if (data.alert_level !== 'normal' && !alertActive) {
        data.voice_stress_level = currentStrain;  // use mic strain
        data.pitch = currentPitch;
        data.volume = currentVolume;
        showAlert(data);
    }
}

function updateMetricCard(elementId, value) {
    const el = document.getElementById(elementId);
    if (el) el.textContent = value;
}

function applyAlertStyling(level) {
    const cards = document.querySelectorAll('.metric-card');
    cards.forEach(card => {
        card.classList.remove('warning', 'critical');
    });
    document.body.classList.remove('alert-warning', 'alert-critical');

    if (level === 'warning') {
        document.getElementById('card-vitals').classList.add('warning');
        document.body.classList.add('alert-warning');
    } else if (level === 'critical') {
        document.getElementById('card-vitals').classList.add('critical');
        document.getElementById('card-strain').classList.add('critical');
        document.body.classList.add('alert-critical');
    }
}


// ── Chart.js ────────────────────────────────────────────────────────────────

function initChart() {
    const ctx = document.getElementById('strain-chart').getContext('2d');

    const gradient = ctx.createLinearGradient(0, 0, 0, 400);
    gradient.addColorStop(0, 'rgba(0, 255, 200, 0.25)');
    gradient.addColorStop(1, 'rgba(0, 255, 200, 0.0)');

    strainChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'Strain Index',
                    data: [],
                    borderColor: '#00ffc8',
                    borderWidth: 2,
                    backgroundColor: gradient,
                    fill: true,
                    tension: 0.35,
                    pointRadius: 0,
                    pointHitRadius: 10,
                },
                {
                    label: 'Threshold',
                    data: [],
                    borderColor: 'rgba(255, 51, 85, 0.5)',
                    borderWidth: 1,
                    borderDash: [6, 4],
                    pointRadius: 0,
                    fill: false,
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: {
                duration: 150,
            },
            interaction: {
                intersect: false,
                mode: 'index',
            },
            scales: {
                x: {
                    display: true,
                    ticks: {
                        color: '#4a5568',
                        font: { family: "'JetBrains Mono'", size: 9 },
                        maxTicksLimit: 8,
                        maxRotation: 0,
                    },
                    grid: {
                        color: 'rgba(255,255,255,0.03)',
                    },
                },
                y: {
                    display: true,
                    min: 0,
                    max: 1.2,
                    ticks: {
                        color: '#4a5568',
                        font: { family: "'JetBrains Mono'", size: 10 },
                        stepSize: 0.25,
                    },
                    grid: {
                        color: 'rgba(255,255,255,0.04)',
                    },
                },
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#0d1321',
                    borderColor: 'rgba(0, 255, 200, 0.2)',
                    borderWidth: 1,
                    titleFont: { family: "'Orbitron'", size: 10 },
                    bodyFont: { family: "'Inter'", size: 12 },
                    titleColor: '#7a8ba0',
                    bodyColor: '#e8f0f2',
                },
            },
        },
    });
}

function addChartDataPoint(strainValue, timestamp) {
    const time = timestamp ? new Date(timestamp).toLocaleTimeString('en-US', { hour12: false }) : new Date().toLocaleTimeString('en-US', { hour12: false });

    strainChart.data.labels.push(time);
    strainChart.data.datasets[0].data.push(strainValue);
    strainChart.data.datasets[1].data.push(CONFIG.STRAIN_THRESHOLD);

    // Keep chart rolling
    if (strainChart.data.labels.length > CONFIG.CHART_MAX_POINTS) {
        strainChart.data.labels.shift();
        strainChart.data.datasets[0].data.shift();
        strainChart.data.datasets[1].data.shift();
    }

    strainChart.update('none'); // skip animation for perf
}


// ── Microphone Input (Pitch & Volume) ───────────────────────────────────────

async function initMicrophone() {
    try {
        micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const source = audioContext.createMediaStreamSource(micStream);

        analyserNode = audioContext.createAnalyser();
        analyserNode.fftSize = 2048;
        source.connect(analyserNode);

        addLog('Microphone active — capturing audio', 'normal');

        // Fast mic data processing (100ms) — updates pitch/volume cards
        setInterval(processMicData, CONFIG.MIC_UPDATE_INTERVAL_MS);

        // Slower chart feed (500ms) — pushes local strain to chart when no server data
        setInterval(pushMicDataToChart, CONFIG.MIC_CHART_INTERVAL_MS);

    } catch (err) {
        addLog('Microphone access denied — pitch/volume disabled', 'warning');
        console.warn('Mic error:', err);
    }
}

function processMicData() {
    if (!analyserNode) return;

    const bufferLength = analyserNode.fftSize;
    const dataArray = new Float32Array(bufferLength);
    analyserNode.getFloatTimeDomainData(dataArray);

    // ── Volume (RMS → dB) ──
    let sumSquares = 0;
    for (let i = 0; i < bufferLength; i++) {
        sumSquares += dataArray[i] * dataArray[i];
    }
    const rms = Math.sqrt(sumSquares / bufferLength);
    currentVolume = rms > 0 ? Math.max(0, 20 * Math.log10(rms) + 90) : 0;

    // ── Pitch (autocorrelation) ──
    currentPitch = detectPitch(dataArray, audioContext.sampleRate);

    // ── Local Strain Index ──
    // Compute a strain value from volume intensity (0-1 range)
    // Higher volume = higher strain, pitch instability adds strain
    const volumeStrain = Math.min(currentVolume / 100, 1.0);    // normalise: 100dB = max strain (raised from 85)
    const pitchFactor = currentPitch > 600 ? 0.1 : 0;           // only very high pitch adds strain
    currentStrain = Math.min(1.0, volumeStrain * 0.7 + pitchFactor + Math.random() * 0.03);
    currentStrain = Math.round(currentStrain * 100) / 100;

    // ── Always update pitch, volume & strain cards from mic ──
    // HR and SpO2 come from server/simulator data only
    updateMetricCard('pitch-value', currentPitch > 0 ? Math.round(currentPitch) : '--');
    updateMetricCard('volume-value', Math.round(currentVolume));
    updateMetricCard('strain-value', currentStrain.toFixed(2));
}

function pushMicDataToChart() {
    // Always push mic strain data to the chart
    if (analyserNode) {
        addChartDataPoint(currentStrain, null);

        // ── Local strain threshold alert ──
        if (currentStrain >= CONFIG.STRAIN_THRESHOLD && !alertActive) {
            const localAlertData = {
                heart_rate: lastHeartRate != null ? lastHeartRate : '--',
                spo2: lastSpO2 != null ? lastSpO2 : '--',
                voice_stress_level: currentStrain,
                pitch: currentPitch,
                volume: currentVolume,
                alert_level: currentStrain >= 0.95 ? 'critical' : 'warning',
                alert_message: currentStrain >= 0.95
                    ? `⚠️ CRITICAL: Vocal strain dangerously high (${currentStrain.toFixed(2)}). Stop immediately!`
                    : `⚠ WARNING: Vocal strain above safe threshold (${currentStrain.toFixed(2)}). Consider resting.`,
            };

            addLog(
                `${localAlertData.alert_level.toUpperCase()} — Strain:${currentStrain.toFixed(2)} Pitch:${Math.round(currentPitch)}Hz Vol:${Math.round(currentVolume)}dB`,
                localAlertData.alert_level
            );

            applyAlertStyling(localAlertData.alert_level);
            showAlert(localAlertData);
        } else if (currentStrain < CONFIG.STRAIN_THRESHOLD) {
            applyAlertStyling('normal');
        }
    }
}

function detectPitch(buffer, sampleRate) {
    const SIZE = buffer.length;
    const MAX_SAMPLES = Math.floor(SIZE / 2);
    let bestOffset = -1;
    let bestCorrelation = 0;
    let foundGoodCorrelation = false;
    const correlations = new Array(MAX_SAMPLES);

    let rms = 0;
    for (let i = 0; i < SIZE; i++) {
        rms += buffer[i] * buffer[i];
    }
    rms = Math.sqrt(rms / SIZE);
    if (rms < 0.01) return 0;

    let lastCorrelation = 1;
    for (let offset = 0; offset < MAX_SAMPLES; offset++) {
        let correlation = 0;
        for (let i = 0; i < MAX_SAMPLES; i++) {
            correlation += Math.abs(buffer[i] - buffer[i + offset]);
        }
        correlation = 1 - (correlation / MAX_SAMPLES);
        correlations[offset] = correlation;

        if ((correlation > 0.9) && (correlation > lastCorrelation)) {
            foundGoodCorrelation = true;
            if (correlation > bestCorrelation) {
                bestCorrelation = correlation;
                bestOffset = offset;
            }
        } else if (foundGoodCorrelation) {
            break;
        }
        lastCorrelation = correlation;
    }

    if (bestCorrelation > 0.01 && bestOffset > 0) {
        return sampleRate / bestOffset;
    }
    return 0;
}

/**
 * Get current mic readings for sending with WebSocket data.
 */
function getMicReadings() {
    return {
        pitch: Math.round(currentPitch * 100) / 100,
        volume: Math.round(currentVolume * 100) / 100,
        strain: currentStrain,
    };
}


// ── Alert System ────────────────────────────────────────────────────────────

async function showAlert(data) {
    alertActive = true;

    const overlay = document.getElementById('alert-overlay');
    const modal = document.getElementById('alert-modal');
    const header = document.getElementById('alert-header');
    const title = document.getElementById('alert-title');

    // Set content
    document.getElementById('alert-message-text').textContent = data.alert_message || 'Threshold breached';
    document.getElementById('alert-hr').textContent = data.heart_rate ?? '--';
    document.getElementById('alert-spo2').textContent = data.spo2 != null && data.spo2 !== '--' ? `${data.spo2}%` : '--';
    document.getElementById('alert-strain').textContent = typeof data.voice_stress_level === 'number' ? data.voice_stress_level.toFixed(2) : '--';

    // Style based on level
    if (data.alert_level === 'critical') {
        modal.classList.remove('warning-modal');
        header.classList.remove('warning-header');
        title.textContent = '🚨 CRITICAL ALERT';
        title.style.color = '#ff3355';
    } else {
        modal.classList.add('warning-modal');
        header.classList.add('warning-header');
        title.textContent = '⚠ WARNING ALERT';
        title.style.color = '#ffaa00';
    }

    // Reset Gemini section
    const spinner = document.getElementById('gemini-spinner');
    const resultDiv = document.getElementById('gemini-result');
    spinner.classList.remove('done');
    resultDiv.innerHTML = '<p>Verifying alert with Gemini AI...</p>';

    // Show modal
    overlay.classList.add('active');

    // Call Gemini verification
    try {
        const response = await fetch(`${CONFIG.API_BASE}/api/verify-alert`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                heart_rate: typeof data.heart_rate === 'number' ? data.heart_rate : null,
                spo2: typeof data.spo2 === 'number' ? data.spo2 : null,
                voice_stress_level: data.voice_stress_level,
                alert_level: data.alert_level,
                alert_message: data.alert_message,
            }),
        });

        const result = await response.json();
        spinner.classList.add('done');

        const verdictClass = result.verdict || 'uncertain';
        resultDiv.innerHTML = `
            <p class="verdict ${verdictClass}">VERDICT: ${(result.verdict || 'UNKNOWN').toUpperCase()}</p>
            <p>${result.explanation || 'No explanation available.'}</p>
            ${result.recommendation ? `<p class="recommendation">💡 ${result.recommendation}</p>` : ''}
            ${result.risk_level ? `<p style="margin-top:6px;color:#7a8ba0;font-size:11px;">Risk Level: ${result.risk_level.toUpperCase()}</p>` : ''}
        `;

        addLog(`Gemini: ${result.verdict} — ${result.explanation || ''}`, data.alert_level);
    } catch (err) {
        spinner.classList.add('done');
        resultDiv.innerHTML = '<p style="color:#ff3355;">Failed to reach Gemini API</p>';
        addLog('Gemini verification failed', 'critical');
    }
}

function dismissAlert() {
    const overlay = document.getElementById('alert-overlay');
    overlay.classList.remove('active');
    alertActive = false;
    addLog('Alert acknowledged by user', 'normal');
}


// ── System Log ──────────────────────────────────────────────────────────────

function addLog(message, level = 'normal') {
    const container = document.getElementById('log-container');
    const entry = document.createElement('div');
    entry.className = `log-entry ${level}`;

    const now = new Date().toLocaleTimeString('en-US', { hour12: false });
    entry.innerHTML = `<span class="log-time">[${now}]</span><span class="log-msg">${message}</span>`;

    container.appendChild(entry);
    container.scrollTop = container.scrollHeight;

    // Keep log manageable
    while (container.children.length > 200) {
        container.removeChild(container.firstChild);
    }
}


// ── Session Actions ─────────────────────────────────────────────────────────

async function exportSessionLog() {
    addLog('Exporting session log...', 'normal');
    try {
        const response = await fetch(`${CONFIG.API_BASE}/api/sessions?limit=500`);
        const data = await response.json();

        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `voxguard_session_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.json`;
        a.click();
        URL.revokeObjectURL(url);

        addLog('Session log exported successfully', 'normal');
    } catch (err) {
        addLog('Export failed: ' + err.message, 'critical');
    }
}

function addMarker() {
    const timestamp = new Date().toLocaleTimeString('en-US', { hour12: false });
    addLog(`📌 MARKER set at ${timestamp}`, 'normal');
    // Placeholder — marker persistence can be added later
}

// ── Dummy Calibration Feature ───────────────────────────────────────────────

function runDummyCalibration() {
    const inputs = document.querySelectorAll('.stem-input');
    let filesSelected = 0;
    inputs.forEach(input => { if (input.files.length > 0) filesSelected++; });

    // Enforce 3 files for the dummy demo
    if (filesSelected < 3) {
        alert("Please select 3 dummy audio files (Baseline, Comfort, Pushed) to calibrate.");
        return;
    }

    const btn = document.getElementById('btn-calibrate');
    const status = document.getElementById('calibration-status');
    const progressText = status.querySelector('span');
    const progressFill = document.getElementById('calib-progress');

    btn.style.display = 'none';
    status.style.display = 'block';
    progressFill.style.width = '0%';
    progressText.innerText = "Extracting FFT Features...";
    progressText.style.color = 'var(--warning)';

    setTimeout(() => {
        progressFill.style.width = '40%';
        progressText.innerText = "Analyzing Dynamic Range...";
    }, 1500);

    setTimeout(() => {
        progressFill.style.width = '80%';
        progressText.innerText = "Training Personal Model...";
    }, 3000);

    setTimeout(() => {
        progressFill.style.width = '100%';
        progressText.innerText = "Calibration Complete!";
        progressText.style.color = 'var(--success)';

        // Generate a random personalized threshold between 0.45 and 0.75
        const newThresholdStr = (Math.random() * (0.75 - 0.45) + 0.45).toFixed(2);
        const newThreshold = parseFloat(newThresholdStr);

        // Update globally
        CONFIG.STRAIN_THRESHOLD = newThreshold;

        // Update UI
        document.getElementById('threshold-val').innerText = newThresholdStr;

        // Update Chart threshold line
        if (strainChart) {
            strainChart.data.datasets[1].data = Array(CONFIG.CHART_MAX_POINTS).fill(CONFIG.STRAIN_THRESHOLD);
            strainChart.update();
        }

        addLog(`AI Calibration Done. New Personal Threshold: ${newThresholdStr}`, 'normal');

        // Reset UI after success
        setTimeout(() => {
            status.style.display = 'none';
            btn.style.display = 'block';
            inputs.forEach(input => input.value = ''); // Reset file inputs
        }, 4000);

    }, 5000);
}
