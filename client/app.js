const startBtn = document.getElementById('startBtn');
const stopBtn = document.getElementById('stopBtn');
const statusEl = document.getElementById('status');
const eventLogEl = document.getElementById('eventLog');
const transcriptEl = document.getElementById('transcript');
const eventCreatedEl = document.getElementById('eventCreated');

const state = {
  phase: 'idle', // idle | connecting | connected | stopping | error
  pc: null,
  dc: null,
  stream: null,
  remoteAudioEl: null,
  requestId: null,
  model: null,
  webrtcUrl: null,
  pendingUserTurn: false,
  responseInFlight: false,
};

function nowLabel() {
  return new Date().toLocaleTimeString();
}

function toSafePreview(value) {
  const text = typeof value === 'string' ? value : JSON.stringify(value);
  return text
    .replace(/Bearer\s+[A-Za-z0-9._-]+/gi, 'Bearer ***')
    .replace(/"value"\s*:\s*"[^"]+"/g, '"value":"***"')
    .slice(0, 380);
}

function logEvent(direction, type, payload) {
  const row = document.createElement('div');
  row.className = 'log-row';

  const ts = document.createElement('div');
  ts.className = 'log-time';
  ts.textContent = nowLabel();

  const dir = document.createElement('div');
  dir.className = `log-dir ${direction}`;
  dir.textContent = direction.toUpperCase();

  const body = document.createElement('div');
  body.textContent = `${type} ${payload ? `— ${toSafePreview(payload)}` : ''}`;

  row.append(ts, dir, body);
  eventLogEl.appendChild(row);
  eventLogEl.scrollTop = eventLogEl.scrollHeight;
}

function setStatus(nextPhase, message) {
  state.phase = nextPhase;
  statusEl.textContent = message || nextPhase;
  startBtn.disabled = nextPhase !== 'idle';
  stopBtn.disabled = !(nextPhase === 'connected' || nextPhase === 'connecting');
}

function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(';').shift();
  return null;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const requestId = response.headers.get('x-request-id');
  if (requestId) {
    state.requestId = requestId;
  }
  const body = await response.json().catch(() => ({}));
  return { response, body, requestId };
}

function appendTranscript(role, text) {
  if (!text || !text.trim()) return;
  const row = document.createElement('div');
  row.className = `transcript-row ${role}`;
  row.textContent = `${role === 'user' ? 'You' : 'Assistant'}: ${text}`;
  transcriptEl.appendChild(row);
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
}

function renderCreatedEvent(result) {
  if (!result || typeof result !== 'object') return;
  const eventId = result.event_id || result.eventId;
  const htmlLink = result.html_link || result.htmlLink;
  if (!eventId && !htmlLink) return;

  eventCreatedEl.innerHTML = '';
  const p = document.createElement('p');
  p.textContent = `Event created: ${eventId || 'unknown id'}`;
  eventCreatedEl.appendChild(p);

  if (htmlLink) {
    const a = document.createElement('a');
    a.href = htmlLink;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.className = 'created-link';
    a.textContent = 'Open in Google Calendar';
    eventCreatedEl.appendChild(a);
  }
}

async function ensureServerSession() {
  const { response, body, requestId } = await fetchJson('/api/session/start', { method: 'POST' });
  if (!response.ok) {
    throw new Error(body?.detail?.message || 'Failed to initialize backend session');
  }
  logEvent('out', 'POST /api/session/start', requestId ? { request_id: requestId } : {});
}

async function createRealtimeSessionHandoff() {
  const csrfToken = getCookie('vsa_csrf') || '';
  const { response, body, requestId } = await fetchJson('/api/realtime/session', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': csrfToken,
    },
  });

  if (!response.ok) {
    const detail = body?.detail?.message || 'Failed to create realtime session';
    const action = body?.detail?.action;
    throw new Error(action ? `${detail} ${action}` : detail);
  }

  if (!body?.client_secret?.value || !body?.model || !body?.webrtc_url) {
    throw new Error('Realtime handoff payload was incomplete');
  }

  logEvent('out', 'POST /api/realtime/session', {
    request_id: requestId || state.requestId,
    session_id: body.id,
    model: body.model,
  });

  return body;
}

function sendRealtimeEvent(event) {
  if (!state.dc || state.dc.readyState !== 'open') {
    return;
  }
  state.dc.send(JSON.stringify(event));
  logEvent('out', event.type || 'event', event);
}

function requestAssistantResponse(instructions) {
  if (state.responseInFlight) {
    return;
  }
  state.responseInFlight = true;
  sendRealtimeEvent({
    type: 'response.create',
    response: {
      modalities: ['audio', 'text'],
      ...(instructions ? { instructions } : {}),
    },
  });
}

async function executeToolOnBackend(toolName, toolArgs, callId) {
  const csrfToken = getCookie('vsa_csrf') || '';

  const payload = {
    tool: toolName,
    arguments: toolArgs,
  };

  logEvent('out', 'tool.forward', { tool: toolName, call_id: callId });

  const { response, body, requestId } = await fetchJson('/api/tools/execute', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': csrfToken,
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const message = body?.detail?.message || 'Tool execution failed';
    const action = body?.detail?.action;
    const reason = action ? `${message} ${action}` : message;

    sendRealtimeEvent({
      type: 'conversation.item.create',
      item: {
        type: 'function_call_output',
        call_id: callId,
        output: JSON.stringify({ ok: false, error: reason }),
      },
    });
    state.responseInFlight = false;
    requestAssistantResponse();
    logEvent('in', 'tool.error', { request_id: requestId || state.requestId, reason });
    return;
  }

  const result = body?.result || {};
  renderCreatedEvent(result);

  sendRealtimeEvent({
    type: 'conversation.item.create',
    item: {
      type: 'function_call_output',
      call_id: callId,
      output: JSON.stringify({ ok: true, result }),
    },
  });
  state.responseInFlight = false;
  requestAssistantResponse();
  logEvent('in', 'tool.result', { request_id: requestId || state.requestId, tool: toolName });
}

async function handleModelFunctionCall(event) {
  const item = event?.item || event;
  const toolName = item?.name;
  const callId = item?.call_id;
  if (!toolName || !callId) return;

  let args = item?.arguments || {};
  if (typeof args === 'string') {
    try {
      args = JSON.parse(args);
    } catch {
      args = {};
    }
  }

  await executeToolOnBackend(toolName, args, callId);
}

function onRealtimeMessage(raw) {
  let event;
  try {
    event = JSON.parse(raw.data);
  } catch {
    logEvent('in', 'invalid_json', raw.data);
    return;
  }

  logEvent('in', event.type || 'event', event);

  if (event.type === 'conversation.item.input_audio_transcription.completed') {
    const transcript = (event.transcript || '').trim();
    if (transcript) {
      appendTranscript('user', transcript);
      state.pendingUserTurn = false;
      state.responseInFlight = false;
      requestAssistantResponse();
    }
    return;
  }

  if (event.type === 'input_audio_buffer.speech_started') {
    state.pendingUserTurn = true;
    return;
  }

  if (event.type === 'input_audio_buffer.speech_stopped') {
    return;
  }

  if (event.type === 'response.audio_transcript.done' || event.type === 'response.text.done') {
    appendTranscript('assistant', event.transcript || event.text || '');
    return;
  }

  if (event.type === 'response.done' || event.type === 'response.completed' || event.type === 'response.output_text.done') {
    state.responseInFlight = false;
    return;
  }

  if (event.type === 'response.output_item.done' && event?.item?.type === 'function_call') {
    handleModelFunctionCall(event).catch((error) => {
      logEvent('in', 'tool.bridge.error', { message: error.message });
    });
    return;
  }

  if (event.type === 'response.function_call_arguments.done') {
    const synthetic = {
      item: {
        type: 'function_call',
        name: event.name,
        call_id: event.call_id,
        arguments: event.arguments,
      },
    };
    handleModelFunctionCall(synthetic).catch((error) => {
      logEvent('in', 'tool.bridge.error', { message: error.message });
    });
    return;
  }
}

async function start() {
  if (state.phase !== 'idle') return;
  setStatus('connecting', 'connecting');

  try {
    await ensureServerSession();
    const handoff = await createRealtimeSessionHandoff();
    state.model = handoff.model;
    state.webrtcUrl = handoff.webrtc_url;

    // Step 1: Capture microphone locally.
    state.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });

    // Step 2: Create RTCPeerConnection and attach local mic tracks.
    state.pc = new RTCPeerConnection();
    state.stream.getTracks().forEach((track) => state.pc.addTrack(track, state.stream));

    // Step 3: Remote audio playback from OpenAI Realtime.
    state.remoteAudioEl = document.createElement('audio');
    state.remoteAudioEl.autoplay = true;
    state.pc.ontrack = (evt) => {
      state.remoteAudioEl.srcObject = evt.streams[0];
    };

    // Step 4: DataChannel carries JSON events for transcripts, function calls, etc.
    state.dc = state.pc.createDataChannel('oai-events');
    state.dc.addEventListener('message', onRealtimeMessage);
    state.dc.addEventListener('open', () => {
      logEvent('in', 'data_channel_open');
      setStatus('connected', 'connected');
      // Kick off the assistant's first response so it starts the slot-filling conversation.
      state.responseInFlight = false;
      requestAssistantResponse('Start the conversation now and ask for the user name first.');
    });

    // Step 5: SDP exchange (offer from browser -> answer from OpenAI realtime endpoint).
    const offer = await state.pc.createOffer();
    await state.pc.setLocalDescription(offer);

    const sdpResponse = await fetch(`${state.webrtcUrl}?model=${encodeURIComponent(state.model)}`, {
      method: 'POST',
      body: offer.sdp,
      headers: {
        Authorization: `Bearer ${handoff.client_secret.value}`,
        'Content-Type': 'application/sdp',
      },
    });

    if (!sdpResponse.ok) {
      throw new Error(`SDP exchange failed (${sdpResponse.status})`);
    }

    const answerSdp = await sdpResponse.text();
    await state.pc.setRemoteDescription({ type: 'answer', sdp: answerSdp });
  } catch (error) {
    logEvent('in', 'start.error', { message: error.message });
    await stop(true);
    setStatus('error', 'error');
  }
}

async function stop(silent = false) {
  if (!(state.phase === 'connected' || state.phase === 'connecting' || state.phase === 'error')) {
    return;
  }

  setStatus('stopping', 'stopping');

  if (state.dc) {
    try {
      state.dc.close();
    } catch {
    }
    state.dc = null;
  }

  if (state.pc) {
    try {
      state.pc.close();
    } catch {
    }
    state.pc = null;
  }

  if (state.stream) {
    state.stream.getTracks().forEach((track) => track.stop());
    state.stream = null;
  }

  if (state.remoteAudioEl) {
    state.remoteAudioEl.srcObject = null;
    state.remoteAudioEl.remove();
    state.remoteAudioEl = null;
  }

  state.model = null;
  state.webrtcUrl = null;
  state.pendingUserTurn = false;
  state.responseInFlight = false;

  setStatus('idle', 'idle');
  if (!silent) {
    logEvent('in', 'session.stopped', { request_id: state.requestId || null });
  }
}

startBtn.addEventListener('click', () => {
  start().catch((error) => {
    logEvent('in', 'unhandled.start.error', { message: error.message });
  });
});

stopBtn.addEventListener('click', () => {
  stop().catch((error) => {
    logEvent('in', 'unhandled.stop.error', { message: error.message });
  });
});

window.addEventListener('beforeunload', () => {
  if (state.stream) {
    state.stream.getTracks().forEach((track) => track.stop());
  }
});

setStatus('idle', 'idle');
logEvent('in', 'client.ready', {});
