/**
 * Boot and orchestration — admin console.
 *
 * The only module that knows about both the store and the gateway. Views read
 * from the store and dispatch intents; the gateway performs all I/O.
 */
import { config } from './config.js';
import { strings } from './strings.js';
import { createStore } from './store.js';
import { createGateway } from './gateway/index.js';
import { el, clear } from './dom.js';
import { createNav } from './views/nav.js';
import { createInboxList } from './views/inboxList.js';
import { createTranscript } from './views/transcript.js';
import { createRepComposer } from './views/repComposer.js';
import { createIntelligence } from './views/intelligence.js';
import { createObservability } from './views/observability.js';
import { createCases } from './views/cases.js';
import { createHarness } from './views/harness.js';

document.title = strings.documentTitle;

const ROUTES = ['inbox', 'cases', 'harness'];
const store = createStore();

let gateway = null;
let bootError = null;
try {
  gateway = createGateway(config);
  store.capabilitiesSet(gateway.capabilities);
} catch (error) {
  bootError = error;
  console.error('[admin] transport unavailable:', error.message);
}

const newClientId = () =>
  typeof crypto !== 'undefined' && crypto.randomUUID
    ? `r-${crypto.randomUUID()}`
    : `r-${Date.now().toString(36)}`;

/* ==========================================================================
   Actions
   ========================================================================== */

async function loadInbox() {
  if (!gateway) return store.inboxFailed();
  store.inboxLoading();
  try {
    const { items } = await gateway.listConversations();
    store.inboxLoaded(items);
  } catch (error) {
    console.error('[admin] inbox load failed:', error);
    store.inboxFailed();
  }
}

async function loadCases() {
  if (!gateway) return store.casesFailed();
  store.casesLoading();
  try {
    const { items } = await gateway.listCases();
    store.casesLoaded(items);
  } catch (error) {
    console.error('[admin] cases load failed:', error);
    store.casesFailed();
  }
}

async function openConversation(id) {
  if (!gateway) return;
  store.conversationRequested(id);
  try {
    const result = await gateway.getConversation(id);
    store.conversationLoaded(result);
  } catch (error) {
    console.error('[admin] conversation load failed:', error);
    store.conversationFailed();
    return;
  }

  if (!store.getState().capabilities.telemetry) return;
  store.runsLoading();
  try {
    const { items } = await gateway.listAgentRuns({ opportunityId: id });
    store.runsLoaded(items);
  } catch (error) {
    console.error('[admin] agent runs load failed:', error);
    store.runsFailed();
  }
}

async function transitionCase(caseId, statusToken) {
  if (!gateway) return;
  store.transitionStarted(caseId);
  try {
    const updated = await gateway.updateCaseStatus(caseId, statusToken);
    store.transitionSucceeded(updated);
    // The inbox row's takeover marker depends on this, so refresh it.
    loadInbox();
  } catch (error) {
    console.error('[admin] case transition failed:', error);
    store.transitionFailed(caseId, error.message);
  }
}

async function sendReply(text) {
  const state = store.getState();
  const opportunity = state.conversation.opportunity;
  if (!gateway || !opportunity) return;

  store.replyStarted();
  try {
    const { message } = await gateway.sendRepReply({
      id: opportunity.id,
      text,
      repName: config.operator.name,
      clientMessageId: newClientId(),
    });
    store.replyAppended(message);
    loadInbox();
  } catch (error) {
    console.error('[admin] reply failed:', error);
    store.replyFailed(error.message);
  }
}

async function seedDemoData() {
  if (!gateway) return;
  try {
    await gateway.seedDemoData();
  } catch (error) {
    console.error('[admin] seed failed:', error);
  }
  loadInbox();
  loadCases();
}

function navigate(route) {
  if (!ROUTES.includes(route)) route = 'inbox';
  if (window.location.hash !== `#/${route}`) {
    window.location.hash = `#/${route}`;
    return; // hashchange will re-enter
  }
  store.routeChanged(route);
  if (route === 'cases') loadCases();
}

function routeFromHash() {
  const raw = String(window.location.hash || '').replace(/^#\/?/, '');
  return ROUTES.includes(raw) ? raw : 'inbox';
}

/* ==========================================================================
   Views
   ========================================================================== */

const nav = createNav({
  el: document.getElementById('nav'),
  onNavigate: navigate,
});

const inboxList = createInboxList({
  el: document.getElementById('inboxList'),
  onSelect: openConversation,
  onRefresh: loadInbox,
  onSeed: seedDemoData,
});

const transcript = createTranscript({
  headerEl: document.getElementById('convHeader'),
  transcriptEl: document.getElementById('convTranscript'),
  onRetry: () => {
    const id = store.getState().selectedId;
    if (id) openConversation(id);
  },
  onViewCase: () => navigate('cases'),
});

const repComposer = createRepComposer({
  el: document.getElementById('convComposer'),
  onSend: sendReply,
  onDraftChange: (text) => store.draftChanged(text),
});

const intelligence = createIntelligence({
  el: document.getElementById('panelIntelligence'),
});

const observability = createObservability({
  el: document.getElementById('panelObservability'),
  onSelectRun: (runId) => store.runSelected(runId),
});

const cases = createCases({
  el: document.getElementById('casesRoot'),
  onTransition: transitionCase,
  onRefresh: loadCases,
  onOpenConversation: (id) => {
    navigate('inbox');
    openConversation(id);
  },
});

/* ---- Panel tabs ---------------------------------------------------------- */

const panelTabsEl = document.getElementById('panelTabs');
const panelTabs = [
  { key: 'intelligence', label: strings.panels.intelligence },
  { key: 'observability', label: strings.panels.observability },
].map(({ key, label }) =>
  el('button', {
    className: 'panel-tab',
    text: label,
    attrs: { type: 'button', 'aria-pressed': 'false' },
    on: { click: () => store.panelChanged(key) },
  })
);
clear(panelTabsEl);
panelTabsEl.append(...panelTabs);

const panelTabsView = {
  render(state) {
    panelTabs.forEach((button, index) => {
      const key = index === 0 ? 'intelligence' : 'observability';
      const active = state.activePanel === key;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  },
};

/* ---- Route visibility ---------------------------------------------------- */

const routeSections = new Map(
  ROUTES.map((route) => [route, document.querySelector(`#route-${route}`)])
);

const routeView = {
  render(state) {
    for (const [route, node] of routeSections) {
      node.classList.toggle('is-active', route === state.route);
    }
  },
};

/* ---- Harness ------------------------------------------------------------- */

/**
 * Fetch the agent run for one exchange, joining on the correlation id the device
 * reported. The telemetry is read from the admin surface, never routed through
 * the device — the customer surface has no shape for it.
 */
async function fetchRunForExchange(clientMessageId) {
  if (!gateway || !store.getState().capabilities.telemetry) return;
  store.entryRunLoading(clientMessageId);
  try {
    const { items } = await gateway.listAgentRuns({ clientMessageId });
    store.entryRunLoaded(clientMessageId, items[0] ?? null);
  } catch (error) {
    console.error('[admin] agent run lookup failed:', error);
    store.entryRunFailed(clientMessageId);
  }
}

const harness = createHarness({
  debugEl: document.getElementById('harnessDebug'),
  deviceEl: document.getElementById('harnessDevice'),
  store,
  onSelectEntry: (id) => store.entrySelected(id),
  onFetchRun: fetchRunForExchange,
});

const views = [
  nav,
  routeView,
  inboxList,
  transcript,
  repComposer,
  panelTabsView,
  intelligence,
  observability,
  cases,
  harness,
];

store.subscribe((state) => {
  for (const view of views) view.render(state);
});

/* ==========================================================================
   Start
   ========================================================================== */

window.addEventListener('hashchange', () => store.routeChanged(routeFromHash()));

store.routeChanged(routeFromHash());
// routeChanged is a no-op when the value is unchanged, so force a first paint.
for (const view of views) view.render(store.getState());

if (bootError) {
  store.inboxFailed();
  store.casesFailed();
} else {
  loadInbox();
  loadCases();
}
