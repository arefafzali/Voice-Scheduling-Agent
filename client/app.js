const startBtn = document.getElementById('startBtn');
const stopBtn = document.getElementById('stopBtn');
const newSessionBtn = document.getElementById('newSessionBtn');
const clearSessionBtn = document.getElementById('clearSessionBtn');
const connectBtn = document.getElementById('connectBtn');
const checkCalendarBtn = document.getElementById('checkCalendarBtn');
const disconnectBtn = document.getElementById('disconnectBtn');
const statusEl = document.getElementById('status');
const sessionStateEl = document.getElementById('sessionState');
const listenStateEl = document.getElementById('listenState');
const turnStateEl = document.getElementById('turnState');
const calendarStateEl = document.getElementById('calendarState');
const eventLogEl = document.getElementById('eventLog');
const transcriptEl = document.getElementById('transcript');
const liveTranscriptEl = document.getElementById('liveTranscript');
const eventCreatedEl = document.getElementById('eventCreated');
const queryParams = new URLSearchParams(window.location.search);

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
  liveTranscript: '',
  isListening: false,
  assistantSpeaking: false,
  lastAssistantMessage: '',
  ignoreVoiceInputUntil: 0,
  processedToolCallIds: new Set(),
};

let currentSessionId = null;

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
  if (!eventLogEl) {
    return;
  }

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

function setListeningState(isListening) {
  state.isListening = isListening;
  listenStateEl.textContent = isListening ? 'Mic: listening' : 'Mic: idle';
}

function setTurnState(value) {
  turnStateEl.textContent = `Turn: ${value}`;
}

function setLiveTranscript(text, tone = 'idle') {
  const content = (text || '').trim();
  if (!content) {
    liveTranscriptEl.textContent = 'Live user transcript appears here...';
    liveTranscriptEl.className = 'live-transcript empty';
    return;
  }

  liveTranscriptEl.textContent = content;
  if (tone === 'listening') {
    liveTranscriptEl.className = 'live-transcript listening';
  } else if (tone === 'thinking') {
    liveTranscriptEl.className = 'live-transcript thinking';
  } else {
    liveTranscriptEl.className = 'live-transcript';
  }
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
  if (role === 'assistant') {
    state.lastAssistantMessage = text;
  }
}

function setMicEnabled(enabled) {
  if (!state.stream) return;
  state.stream.getAudioTracks().forEach((track) => {
    track.enabled = enabled;
  });
}

function normalizeForCompare(value) {
  return (value || '')
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function looksLikeAssistantEcho(candidate, assistantText) {
  const userText = normalizeForCompare(candidate);
  const assistant = normalizeForCompare(assistantText);
  if (!userText || !assistant) return false;
  if (userText === assistant) return true;
  if (userText.length >= 24 && assistant.includes(userText)) return true;
  if (assistant.length >= 24 && userText.includes(assistant)) return true;

  const userWords = userText.split(' ').filter(Boolean);
  const assistantWords = new Set(assistant.split(' ').filter(Boolean));
  if (!userWords.length || !assistantWords.size) return false;

  let overlap = 0;
  for (const word of userWords) {
    if (assistantWords.has(word)) {
      overlap += 1;
    }
  }
  return userWords.length >= 5 && overlap / userWords.length >= 0.6;
}

function shouldSuppressVoiceTranscript(text) {
  if (Date.now() < state.ignoreVoiceInputUntil) return true;
  if (state.assistantSpeaking) return true;
  return looksLikeAssistantEcho(text, state.lastAssistantMessage);
}

function resetLiveTranscript() {
  state.liveTranscript = '';
  setLiveTranscript('');
}

function updateSessionChip() {
  sessionStateEl.textContent = currentSessionId ? `Session: ${currentSessionId.slice(0, 8)}…` : 'Session: —';
}

function clearSessionView() {
  transcriptEl.innerHTML = '';
  if (eventLogEl) {
    eventLogEl.innerHTML = '';
  }
  eventCreatedEl.innerHTML = 'No calendar event created yet.';
  eventCreatedEl.classList.add('empty');
  resetLiveTranscript();
}

function renderCreatedEvent(result) {
  if (!result || typeof result !== 'object') return;
  const eventId = result.event_id || result.eventId;
  const htmlLink = result.html_link || result.htmlLink;
  if (!eventId && !htmlLink) return;

  eventCreatedEl.innerHTML = '';
  eventCreatedEl.classList.remove('empty');
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
  if (currentSessionId) {
    return;
  }

  const callbackSessionId = queryParams.get('session_id');
  const oauthConnected = queryParams.get('oauth') === 'connected';
  const startUrl = (!currentSessionId && oauthConnected && callbackSessionId)
    ? `/api/session/start?session_id=${encodeURIComponent(callbackSessionId)}`
    : '/api/session/start';

  const { response, body, requestId } = await fetchJson(startUrl, { method: 'POST' });
  if (!response.ok) {
    throw new Error(body?.detail?.message || 'Failed to initialize backend session');
  }

  currentSessionId = body?.session_id || currentSessionId;
  updateSessionChip();
  if (oauthConnected) {
    window.history.replaceState({}, document.title, '/voice');
  }

  logEvent('out', 'POST /api/session/start', requestId ? { request_id: requestId, session_id: currentSessionId } : { session_id: currentSessionId });
}

async function startNewSession() {
  await stop(true);
  const { response, body, requestId } = await fetchJson('/api/session/start?force_new=true', { method: 'POST' });
  if (!response.ok) {
    throw new Error(body?.detail?.message || 'Failed to start a new session');
  }

  currentSessionId = body?.session_id || null;
  updateSessionChip();
  clearSessionView();
  await checkConnectionStatus();
  logEvent('out', 'POST /api/session/start?force_new=true', requestId ? { request_id: requestId, session_id: currentSessionId } : { session_id: currentSessionId });
}

async function checkConnectionStatus() {
  const { response, body } = await fetchJson('/api/auth/google/status');
  if (!response.ok) {
    calendarStateEl.textContent = 'Calendar: unknown';
    return false;
  }
  const connected = Boolean(body?.connected);
  calendarStateEl.textContent = connected ? 'Calendar: connected' : 'Calendar: disconnected';
  return connected;
}

async function disconnectCalendar() {
  const csrfToken = getCookie('vsa_csrf') || '';
  const { response, body } = await fetchJson('/api/auth/google/disconnect', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': csrfToken,
    },
    body: JSON.stringify({}),
  });

  if (!response.ok) {
    logEvent('in', 'calendar.disconnect.error', body?.detail || body);
    return;
  }
  logEvent('in', 'calendar.disconnected', body || {});
  await checkConnectionStatus();
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
  setTurnState('assistant');
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

  if (state.processedToolCallIds.has(callId)) {
    logEvent('in', 'tool.duplicate_ignored', { tool: toolName, call_id: callId });
    return;
  }
  state.processedToolCallIds.add(callId);

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
      if (shouldSuppressVoiceTranscript(transcript)) {
        logEvent('in', 'transcript.suppressed', { reason: 'assistant_echo_or_guard' });
        state.liveTranscript = '';
        setLiveTranscript('');
        return;
      }
      appendTranscript('user', transcript);
      state.liveTranscript = '';
      setLiveTranscript(transcript, 'idle');
      state.pendingUserTurn = false;
      state.responseInFlight = false;
      setTurnState('processing');
      requestAssistantResponse();
    }
    return;
  }

  if (event.type === 'conversation.item.input_audio_transcription.delta') {
    const delta = event.delta || '';
    if (delta) {
      state.liveTranscript = `${state.liveTranscript}${delta}`;
      setLiveTranscript(state.liveTranscript, 'listening');
    }
    return;
  }

  if (event.type === 'input_audio_buffer.speech_started') {
    state.pendingUserTurn = true;
    setListeningState(true);
    setTurnState('user');
    state.liveTranscript = '';
    setLiveTranscript('');
    return;
  }

  if (event.type === 'input_audio_buffer.speech_stopped') {
    setListeningState(false);
    setLiveTranscript(state.liveTranscript, 'thinking');
    return;
  }

  if (event.type === 'response.audio_transcript.done' || event.type === 'response.text.done') {
    appendTranscript('assistant', event.transcript || event.text || '');
    setLiveTranscript('');
    setTurnState('idle');
    return;
  }

  if (event.type === 'response.audio.delta' || event.type === 'response.audio_transcript.delta') {
    if (!state.assistantSpeaking) {
      state.assistantSpeaking = true;
      state.ignoreVoiceInputUntil = Date.now() + 2500;
      setMicEnabled(false);
      setListeningState(false);
    }
    return;
  }

  if (event.type === 'response.done' || event.type === 'response.completed' || event.type === 'response.output_text.done') {
    state.responseInFlight = false;
    setTurnState('idle');
    state.assistantSpeaking = false;
    state.ignoreVoiceInputUntil = Date.now() + 1200;
    setMicEnabled(true);
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
    await checkConnectionStatus();
    const handoff = await createRealtimeSessionHandoff();
    state.model = handoff.model;
    state.webrtcUrl = handoff.webrtc_url;

    state.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });

    state.pc = new RTCPeerConnection();
    state.stream.getTracks().forEach((track) => state.pc.addTrack(track, state.stream));

    state.remoteAudioEl = document.createElement('audio');
    state.remoteAudioEl.autoplay = true;
    state.pc.ontrack = (evt) => {
      state.remoteAudioEl.srcObject = evt.streams[0];
    };

    // DataChannel carries realtime JSON events (transcripts + tool calls).
    state.dc = state.pc.createDataChannel('oai-events');
    state.dc.addEventListener('message', onRealtimeMessage);
    state.dc.addEventListener('open', () => {
      logEvent('in', 'data_channel_open');
      setStatus('connected', 'connected');
      setListeningState(true);
      setTurnState('assistant');
      sendRealtimeEvent({
        type: 'session.update',
        session: {
          turn_detection: { type: 'server_vad' },
          input_audio_transcription: { model: 'gpt-4o-mini-transcribe', language: 'en' },
          instructions: 'Default language is English unless the user asks for another language. Start the conversation proactively with a warm one-line greeting and then ask for the user name. Use the exact name the user provides and never invent or replace it. Then collect preferred date, preferred time, and optional meeting title. If title is missing, default to "Meeting with {name}". Before any event creation, summarize all final details and ask for explicit yes/no confirmation. Do not call create_calendar_event without explicit confirmation.',
        },
      });
      state.responseInFlight = false;
      requestAssistantResponse('Speak in English by default unless user requests another language. Start with this introduction sentence: "Hi, I\'m your scheduling assistant and I can help book your meeting." Then ask for the user\'s name, use exactly that name, gather preferred date, preferred time, and optional title, and confirm final details before creating the event. Do not ask for duration unless the user explicitly asks to change it.');
    });

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
  state.assistantSpeaking = false;
  state.lastAssistantMessage = '';
  state.ignoreVoiceInputUntil = 0;
  state.processedToolCallIds = new Set();
  state.liveTranscript = '';
  setListeningState(false);
  setTurnState('idle');
  resetLiveTranscript();

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
updateSessionChip();
setListeningState(false);
setTurnState('idle');
resetLiveTranscript();
ensureServerSession()
  .then(() => checkConnectionStatus())
  .catch((error) => {
    calendarStateEl.textContent = 'Calendar: unknown';
    logEvent('in', 'session.init.error', { message: error.message });
  });

connectBtn.addEventListener('click', () => {
  const qs = currentSessionId
    ? `?session_id=${encodeURIComponent(currentSessionId)}&return_to=%2Fvoice`
    : '?return_to=%2Fvoice';
  window.location.assign(`/api/auth/google/start${qs}`);
});

checkCalendarBtn.addEventListener('click', () => {
  checkConnectionStatus().catch(() => {
    calendarStateEl.textContent = 'Calendar: unknown';
  });
});

disconnectBtn.addEventListener('click', () => {
  disconnectCalendar().catch(() => {
    logEvent('in', 'calendar.disconnect.error', { message: 'disconnect failed' });
  });
});

newSessionBtn.addEventListener('click', () => {
  startNewSession().catch((error) => {
    logEvent('in', 'session.new.error', { message: error.message });
  });
});

clearSessionBtn.addEventListener('click', () => {
  clearSessionView();
  logEvent('in', 'session.view.cleared', { session_id: currentSessionId });
});

logEvent('in', 'client.ready', {});
