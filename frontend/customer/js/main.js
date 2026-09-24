/**
 * Boot and orchestration.
 *
 * Wires store -> views and store -> gateway. This is the only module that knows
 * about both sides. Views never call the gateway, and the gateway never touches
 * the DOM.
 */
import { config } from './config.js';
import { strings } from './strings.js';
import { createStore, createMessage } from './store.js';
import { createGateway } from './gateway/index.js';
import { createTelemetry } from './telemetry.js';
import { createHeader } from './views/header.js';
import { createBanner } from './views/banner.js';
import { createMessageList } from './views/messageList.js';
import { createComposer } from './views/composer.js';
import { createJumpToLatest } from './views/jumpToLatest.js';
import { createQuickReplies } from './views/quickReplies.js';
import { createQuestionChoices } from './views/questionChoices.js';

document.title = strings.documentTitle;

const store = createStore();
const { id: customerId, name: customerName } = store.getState().customer;

/**
 * Inert unless this app is embedded in the admin console's harness. Standalone it
 * emits nothing at all — see telemetry.js.
 */
const telemetry = createTelemetry();

/** @type {ReturnType<typeof createGateway>|null} */
let gateway = null;
let bootError = null;
let pollCursor = null;
let pollTimer = null;
let pollInFlight = false;
let healthInFlight = false;
try {
  gateway = createGateway(config);
} catch (error) {
  // Requirement 9.4: an unavailable transport fails explicitly rather than
  // presenting a blank screen that looks like it is working.
  bootError = error;
  console.error('[customer-chat] transport unavailable:', error.message);
}

// ---- Actions ---------------------------------------------------------------

async function loadHistory() {
  if (!gateway) {
    store.historyFailed();
    return;
  }
  store.historyLoading();
  try {
    const {
      messages = [],
      humanTakeover = false,
      repName = null,
      capabilities = null,
      quickReplies: restoredQuickReplies = [],
      question: restoredQuestion = null,
    } =
      await gateway.loadHistory(customerId);
    store.historyLoaded(messages);
    store.quickRepliesChanged(restoredQuickReplies);
    store.questionChanged(restoredQuestion);
    pollCursor = messages.at(-1)?.id ?? null;
    if (capabilities) store.capabilitiesDetected(capabilities);
    store.takeoverRestored(humanTakeover, repName);
    messageList.scrollToBottom();
  } catch (error) {
    console.error('[customer-chat] history load failed:', error);
    store.historyFailed();
  }
}

/**
 * Send, or retry an existing message in place.
 *
 * The `sent` -> `read` progression is two distinct store transitions on purpose:
 * one for the HTTP acknowledgement, one for the reply actually rendering. That
 * is what keeps the tick semantics anchored to real events rather than a timer.
 *
 * @param {string|null} text new message text, or null when retrying
 * @param {string} [retryClientId] reuse this identity so no second bubble appears
 */
async function send(text, retryClientId) {
  if (!gateway) return;

  const message = store.sendRequested({ text: text ?? '', clientId: retryClientId });
  const startedAt = performance.now();
  let status = 0;

  try {
    const result = await gateway.send({
      customerId,
      customerName,
      text: message.text,
      clientId: message.clientId,
    });

    // The live gateway surfaces the real HTTP status. Mock mode falls back to
    // 200 because no HTTP exchange exists there.
    status = result?.status ?? 200;

    store.sendAcknowledged(message.clientId);

    if (result?.capabilities) store.capabilitiesDetected(result.capabilities);

    const replies = result?.messages ?? [];
    if (typeof result?.humanTakeover === 'boolean') {
      store.takeoverChanged(result.humanTakeover, result.repName ?? null);
    }
    store.replyReceived(replies);
    pollCursor = replies.at(-1)?.id ?? pollCursor;
    store.markRead(message.clientId);
    store.quickRepliesChanged(result?.quickReplies ?? []);
    store.questionChanged(result?.question ?? null);
  } catch (error) {
    // Diagnostics go to the console; the customer sees a generic failed state.
    console.error('[customer-chat] send failed:', error);
    status = error?.status ?? 0;
    store.sendFailed(message.clientId);
  } finally {
    // Correlation id plus client-observed timing only. No agent telemetry: this
    // app never receives any (interface-v1.md §2).
    telemetry.exchange({
      clientMessageId: message.clientId,
      durationMs: Math.round(performance.now() - startedAt),
      status,
    });
  }
}

async function reset() {
  if (gateway) {
    try {
      await gateway.reset(customerId);
    } catch (error) {
      console.error('[customer-chat] reset failed:', error);
    }
  }
  pollCursor = null;
  store.conversationReset();
  composer.focus();
}

function updateConnection() {
  // Requirement 8.3: reflect the browser going offline immediately, without
  // waiting for a request to fail.
  store.connectionChanged(navigator.onLine ? 'online' : 'offline');
}

async function checkHealth() {
  if (!gateway || healthInFlight) return;
  if (!navigator.onLine) {
    store.connectionChanged('offline');
    return;
  }

  healthInFlight = true;
  store.connectionChanged('checking');
  try {
    store.connectionChanged((await gateway.health()) ? 'online' : 'offline');
  } finally {
    healthInFlight = false;
  }
}

async function pollForMessages() {
  if (!gateway || pollInFlight || !navigator.onLine) return;
  pollInFlight = true;
  try {
    const result = await gateway.fetchSince(customerId, pollCursor);
    const messages = result?.messages ?? [];
    if (typeof result?.humanTakeover === 'boolean') {
      store.takeoverChanged(result.humanTakeover, result.repName ?? null);
    }
    store.replyReceived(messages);
    pollCursor = messages.at(-1)?.id ?? pollCursor;
  } catch (error) {
    // A reset from another surface removes the conversation. Treat that as an
    // ended takeover and stop polling instead of logging the same 404 forever.
    if (error?.status === 404) {
      pollCursor = null;
      store.takeoverRestored(false);
      return;
    }
    console.error('[customer-chat] takeover poll failed:', error);
  } finally {
    pollInFlight = false;
  }
}

function syncTakeoverPolling(state) {
  const shouldPoll =
    state.assistant.humanTakeover && state.capabilities.incrementalFetch;
  if (shouldPoll && pollTimer === null) {
    pollForMessages();
    pollTimer = window.setInterval(pollForMessages, config.pollIntervalMs);
  } else if (!shouldPoll && pollTimer !== null) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}

// ---- Views -----------------------------------------------------------------

const header = createHeader({
  el: document.getElementById('chatHeader'),
  onReset: reset,
});

const banner = createBanner({
  el: document.getElementById('bannerStack'),
});

const messageList = createMessageList({
  listEl: document.getElementById('messageList'),
  statesEl: document.getElementById('messageStates'),
  itemsEl: document.getElementById('messageItems'),
  onRetry: (clientId) => send(null, clientId),
  onRetryHistory: loadHistory,
  onScrollChange: (atBottom) => store.scrollChanged(atBottom),
});

const jumpToLatest = createJumpToLatest({
  el: document.getElementById('jumpToLatest'),
  onJump: () => {
    store.unreadCleared();
    store.scrollChanged(true);
    messageList.scrollToBottom();
  },
});

const composer = createComposer({
  el: document.getElementById('composer'),
  onSend: (text) => send(text),
  // Requirement 5.3: typing hides the quick-reply row.
  onTyping: () => store.quickRepliesChanged([]),
});

const quickReplies = createQuickReplies({
  el: document.getElementById('quickReplies'),
  onSelect: (text) => send(text),
});

const questionChoices = createQuestionChoices({
  el: document.getElementById('questionChoices'),
  onSelect: (optionId) => send(optionId),
  onOther: () => composer.focus(),
});

const views = [header, banner, messageList, jumpToLatest, quickReplies, questionChoices, composer];

store.subscribe((state) => {
  for (const view of views) view.render(state);
  syncTakeoverPolling(state);
  reportState(state);
});

// ---- Harness integration (inert unless embedded) ----------------------------

/**
 * Counters reported to the console. Named `customerMessageCount` on purpose:
 * it counts messages the customer sent, which is not an agent turn count.
 * See docs/v0.0/api/interface-v1.md §1.1.
 */
function reportState(state) {
  if (!telemetry.enabled) return;
  telemetry.state({
    customerMessageCount: state.messages.filter((m) => m.direction === 'out').length,
    messageCount: state.messages.length,
    humanTakeover: state.assistant.humanTakeover,
    connection: state.connection,
  });
}

telemetry.onCommand((type, payload) => {
  switch (type) {
    case 'reset':
      reset();
      break;

    case 'inject':
      // Drives the device as if the customer had typed, reusing the ordinary
      // send path. No UI exposes this today — typing in the device itself is
      // equivalent — but scripted scenario replay (stretch A3) needs it.
      if (typeof payload.text === 'string' && payload.text.trim()) {
        send(payload.text.trim());
      }
      break;

    case 'receive': {
      // Deliver an inbound message to the device without a round trip. This is
      // how the harness can preview a representative reply without persisting
      // it. The ordinary Inbox path persists the reply and takeover polling
      // retrieves it from the backend.
      const text = typeof payload.text === 'string' ? payload.text.trim() : '';
      if (!text) break;

      const author = ['ai', 'human', 'system'].includes(payload.author)
        ? payload.author
        : 'human';

      // A human message means a human now owns the conversation, which is what
      // the backend's takeover semantics imply. `takeoverChanged` is idempotent,
      // so only the first one announces it.
      if (author === 'human') {
        store.takeoverChanged(true, payload.repName ?? null);
      }

      store.replyReceived([createMessage({ direction: 'in', author, text })]);
      break;
    }

    default:
      console.warn('[customer-chat] unknown harness command:', type);
  }
});

// ---- Start -----------------------------------------------------------------

window.addEventListener('online', () => {
  updateConnection();
  checkHealth();
  pollForMessages();
});
window.addEventListener('offline', updateConnection);
updateConnection();
checkHealth();
window.setInterval(checkHealth, config.healthIntervalMs);

if (bootError) {
  store.historyFailed();
} else {
  loadHistory();
}

composer.focus();

// Announce readiness last, so the console only configures a live device.
telemetry.ready({
  transport: gateway ? gateway.name : null,
  customerId,
  customerName,
});
reportState(store.getState());
