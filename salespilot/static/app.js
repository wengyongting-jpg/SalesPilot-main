/* ===== SalesPilot Frontend Logic =====
   The frontend ONLY displays backend results — no business logic here.
   All state, signals, score, priority, NBA and HITL come from the API.
*/

const API = '/api';

// ---- View switching ----
function switchView(view) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('view-' + view).classList.add('active');
  document.querySelector(`.nav-btn[data-view="${view}"]`).classList.add('active');
  if (view === 'dashboard') loadDashboard();
  if (view === 'customer') loadCustomerList();
  if (view === 'cases') loadCases();
}

// ---- Chat: send message ----
async function sendMessage() {
  const input = document.getElementById('chatInput');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';

  const custName = document.getElementById('chatCustomerName').value || 'Customer';
  const custId = document.getElementById('chatCustomerId').value || 'C-' + Date.now();

  // Optimistic: show customer message immediately
  appendBubble(text, 'customer');

  try {
    const res = await fetch(`${API}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ customer_id: custId, customer_name: custName, text }),
    });
    const data = await res.json();
    // Structured agent response
    appendAgentResponse(data);
    updateSalesPanel(data);
    // Update case badge
    if (data.case) updateCaseBadge();
  } catch (err) {
    appendBubble('(Connection error — is the server running?)', 'agent');
  }
}

// ---- Chat: append customer bubble ----
function appendBubble(text, role) {
  const container = document.getElementById('chatMessages');
  const empty = container.querySelector('.chat-empty');
  if (empty) empty.remove();

  const bubble = document.createElement('div');
  bubble.className = `bubble ${role}`;
  const now = new Date();
  const ts = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  bubble.innerHTML = `<div>${escapeHtml(text)}</div><div class="ts">${ts}</div>`;
  container.appendChild(bubble);
  container.scrollTop = container.scrollHeight;
}

// ---- Chat: structured agent response ----
function appendAgentResponse(data) {
  const container = document.getElementById('chatMessages');
  const bubble = document.createElement('div');
  bubble.className = 'bubble agent';
  const now = new Date();
  const ts = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  const det = data.detection || {};
  const score = data.score || {};
  const nba = data.next_best_action || {};
  const caseData = data.case;

  let metaHtml = '';
  if (det.intent) metaHtml += `<span>Intent: ${det.intent}</span>`;
  if (det.product && det.product !== 'unknown') metaHtml += `<span>Product: ${det.product}</span>`;
  if (score.total !== undefined) metaHtml += `<span>Score: ${score.total}/100</span>`;
  if (score.priority) metaHtml += `<span>Priority: ${score.priority}</span>`;

  let nbaHtml = '';
  if (nba.action) nbaHtml += `<div class="resp-nba">Next: ${nba.action}</div>`;

  let escHtml = '';
  if (caseData) {
    escHtml += `<div class="resp-escalation">Case: ${caseData.id} — ${caseData.reason}</div>`;
  }

  bubble.innerHTML = `
    <div class="agent-response">
      <div class="resp-text">${escapeHtml(data.reply || '')}</div>
      <div class="resp-meta">${metaHtml}</div>
      ${nbaHtml}
      ${escHtml}
      <div class="ts">${ts}</div>
    </div>
  `;
  container.appendChild(bubble);
  container.scrollTop = container.scrollHeight;
}

// ---- Sales Intelligence Panel update ----
function updateSalesPanel(data) {
  const opp = data.opportunity;
  const det = data.detection;
  const score = data.score;
  const nba = data.next_best_action;
  const caseData = data.case;

  // Show panel content
  document.getElementById('panelEmpty').classList.add('hidden');
  document.getElementById('panelContent').classList.remove('hidden');

  setPanelRow('pCustomer', opp.customer_name);
  setPanelRow('pState', opp.state);
  setPanelRow('pPurchaseIntent', intentLabel(score.purchase_intent));
  setPanelRow('pScore', `${score.total}/100`);
  setPanelRow('pPriority', score.priority);
  setPanelRow('pConcern', opp.main_concern || '—');
  setPanelRow('pCompRisk', opp.competitive_risk ? 'High' : 'None');
  setPanelRow('pExpansion', opp.expansion.length ? opp.expansion.join(', ') : 'No');
  setPanelRow('pNBA', nba.action);
  setPanelRow('pHuman', nba.human_intervention_required ? 'Required' : 'Not required');
  setPanelRow('pSource', data.extraction_source || 'rule');

  // Signals as tags
  const sigContainer = document.getElementById('pSignals');
  sigContainer.innerHTML = '';
  if (!opp.signals || opp.signals.length === 0) {
    sigContainer.textContent = '—';
  } else {
    opp.signals.forEach(s => {
      const tag = document.createElement('span');
      tag.className = `signal-tag ${signalClass(s)}`;
      tag.textContent = shortSignal(s);
      sigContainer.appendChild(tag);
    });
  }

  // Score bar
  const scoreEl = document.getElementById('pScore');
  scoreEl.textContent = `${score.total}/100`;
  const barTrack = document.createElement('div');
  barTrack.className = 'bar-track';
  const inner = document.createElement('div');
  inner.className = 'bar-fill';
  inner.style.width = score.total + '%';
  inner.style.background = priorityColor(score.priority);
  barTrack.appendChild(inner);
  scoreEl.appendChild(barTrack);

  // Priority badge
  const prioEl = document.getElementById('pPriority');
  prioEl.innerHTML = `<span class="badge ${priorityBadge(score.priority)}">${score.priority}</span>`;

  // Takeover banner
  const banner = document.getElementById('takeoverBanner');
  const active = document.getElementById('takeoverActive');
  if (caseData) {
    banner.classList.remove('hidden');
    active.classList.add('hidden');
    document.getElementById('takeoverReason').textContent = `Reason: ${caseData.reason}`;
    document.getElementById('takeoverAction').textContent = `Action: ${caseData.recommended_action}`;
  } else if (opp.human_takeover) {
    banner.classList.add('hidden');
    active.classList.remove('hidden');
  } else {
    banner.classList.add('hidden');
    active.classList.add('hidden');
  }
}

// Flash animation on updated rows
function setPanelRow(id, val) {
  const el = document.getElementById(id);
  if (el.textContent !== String(val)) {
    el.textContent = val;
    const row = el.closest('.panel-row');
    if (row) {
      row.classList.remove('updated');
      void row.offsetWidth; // trigger reflow
      row.classList.add('updated');
    }
  }
}

// ---- Takeover button (from chat panel) ----
async function executeTakeover() {
  document.getElementById('takeoverBanner').classList.add('hidden');
  document.getElementById('takeoverActive').classList.remove('hidden');
  // Refresh cases view if open
  if (document.getElementById('view-cases').classList.contains('active')) {
    loadCases();
  }
}

// ---- New Customer ----
function newCustomer() {
  const id = 'C-' + Math.random().toString(36).substr(2, 4).toUpperCase();
  document.getElementById('chatCustomerId').value = id;
  document.getElementById('chatCustomerName').value = '';
  document.getElementById('chatCustomerName').focus();
  document.getElementById('chatMessages').innerHTML = '<div class="chat-empty">New customer registered. Start typing to begin a conversation.</div>';
  clearPanel();
}

// ---- Reset conversation ----
async function resetConversation() {
  const custId = document.getElementById('chatCustomerId').value;
  try {
    await fetch(`${API}/opportunities/${custId}`, { method: 'DELETE' });
  } catch (e) { /* ignore */ }
  document.getElementById('chatMessages').innerHTML = '<div class="chat-empty">Conversation reset. Start typing to begin again.</div>';
  clearPanel();
}

function clearPanel() {
  document.getElementById('panelEmpty').classList.remove('hidden');
  document.getElementById('panelContent').classList.add('hidden');
  document.getElementById('takeoverBanner').classList.add('hidden');
  document.getElementById('takeoverActive').classList.add('hidden');
}

// ---- Dashboard ----
async function loadDashboard() {
  try {
    const res = await fetch(`${API}/dashboard`);
    const data = await res.json();
    const opps = data.items || [];

    let h=0, m=0, l=0;
    opps.forEach(o => {
      if (!o.priority) { l++; return; }
      if (o.priority === 'HIGH') h++;
      else if (o.priority === 'MEDIUM') m++;
      else l++;
    });
    setText('dashHigh', h);
    setText('dashMedium', m);
    setText('dashLow', l);

    const body = document.getElementById('dashBody');
    if (opps.length === 0) {
      body.innerHTML = '<tr><td colspan="7" class="table-empty">No opportunities yet.</td></tr>';
      return;
    }
    body.innerHTML = '';
    opps.forEach(o => {
      const tr = document.createElement('tr');
      const prioClass = priorityBadge(o.priority || 'LOW');
      const signals = (o.signals || []).map(shortSignal).join(' + ');
      const actionCell = o.human_takeover
        ? '<button class="btn-takeover-small" onclick="goToCases()">Take Over</button>'
        : '<button class="btn-secondary" onclick="goToCustomer()">View</button>';
      tr.innerHTML = `
        <td>${escapeHtml(o.customer_name)}</td>
        <td>${o.state}</td>
        <td><strong>${o.final_score ?? '—'}</strong></td>
        <td>${signals || '—'}</td>
        <td><span class="badge ${prioClass}">${o.priority || '—'}</span></td>
        <td>${o.human_takeover ? 'Take Over' : 'Follow Up'}</td>
        <td>${actionCell}</td>
      `;
      body.appendChild(tr);
    });
  } catch (err) {
    console.error('Dashboard load failed', err);
  }
}

function goToCases() { switchView('cases'); }
function goToCustomer() { switchView('customer'); }

// ---- Seed demo data ----
async function seedDemoData() {
  try {
    const res = await fetch(`${API}/seed`, { method: 'POST' });
    const data = await res.json();
    alert(data.seeded ? 'Demo data seeded.' : 'Already seeded: ' + (data.reason || ''));
    loadDashboard();
    updateCaseBadge();
  } catch (err) {
    alert('Seed failed: ' + err.message);
  }
}

// ---- Customer Detail View ----
async function loadCustomerList() {
  try {
    const res = await fetch(`${API}/opportunities`);
    const data = await res.json();
    const select = document.getElementById('custSelect');
    select.innerHTML = '<option value="">— Select Customer —</option>';
    (data.items || []).forEach(o => {
      const opt = document.createElement('option');
      opt.value = o.opportunity_id;
      opt.textContent = `${o.customer_name} (${o.opportunity_id})`;
      select.appendChild(opt);
    });
  } catch (err) { console.error(err); }
}

async function loadCustomerDetail() {
  const id = document.getElementById('custSelect').value;
  if (!id) return;
  try {
    const res = await fetch(`${API}/opportunities/${id}`);
    const o = await res.json();
    const container = document.getElementById('custDetail');

    // Score history
    let histHtml = '';
    if (o.score_history && o.score_history.length) {
      histHtml = `<div class="cust-card cust-score-history"><h3>Score History</h3>` +
        o.score_history.map(h => {
          const c = h.score >= 80 ? '#dc2626' : h.score >= 50 ? '#f59e0b' : '#64748b';
          const time = h.ts ? h.ts.substring(11, 16) : '—';
          return `<div class="score-hist-item"><span class="score-hist-dot" style="background:${c}"></span><span>${time}</span><span>—</span><span><strong>${h.score}</strong></span><span>${h.state}</span><span style="color:var(--text-muted)">${h.trigger}</span></div>`;
        }).join('') + `</div>`;
    }

    // State history
    const stateHistHtml = (o.state_history && o.state_history.length) ? `
      <div class="cust-card cust-score-history">
        <h3>State History</h3>
        ${o.state_history.map(h => `<div class="score-hist-item"><span class="score-hist-dot" style="background:#2563eb"></span><span>${h.ts ? h.ts.substring(11,16) : '—'}</span><span>${h.from}</span><span>→</span><span><strong>${h.to}</strong></span><span style="color:var(--text-muted)">${h.reason}</span></div>`).join('')}
      </div>` : '';

    // Message history
    let msgHtml = '';
    if (o.messages && o.messages.length) {
      msgHtml = `<div class="cust-card cust-messages"><h3>Conversation History</h3>` +
        o.messages.map(m => {
          const time = m.ts ? m.ts.substring(11, 16) : '';
          return `<div class="cust-msg-item"><span class="msg-ts">${time}</span><span class="msg-role">${m.role === 'customer' ? 'Customer' : 'AI'}</span><span>${escapeHtml(m.text)}</span></div>`;
        }).join('') + `</div>`;
    }

    container.innerHTML = `
      <div class="cust-grid">
        <div class="cust-card"><div class="cust-card-label">Customer</div><div class="cust-card-value">${escapeHtml(o.customer_name)}</div></div>
        <div class="cust-card"><div class="cust-card-label">State</div><div class="cust-card-value">${o.state}</div></div>
        <div class="cust-card"><div class="cust-card-label">Priority</div><div class="cust-card-value">${o.priority || '—'}</div></div>
        <div class="cust-card"><div class="cust-card-label">Opportunity Score</div><div class="cust-card-value">${o.final_score ?? '—'}/100</div></div>
        <div class="cust-card"><div class="cust-card-label">Key Signals</div><div class="cust-card-value">${(o.signals || []).join(', ') || '—'}</div></div>
        <div class="cust-card"><div class="cust-card-label">Main Concern</div><div class="cust-card-value">${o.main_concern || '—'}</div></div>
        <div class="cust-card"><div class="cust-card-label">Competitive Risk</div><div class="cust-card-value">${o.competitive_risk ? 'High' : 'None'}</div></div>
        <div class="cust-card"><div class="cust-card-label">Expansion Opportunity</div><div class="cust-card-value">${(o.expansion || []).join(', ') || 'No'}</div></div>
        <div class="cust-card"><div class="cust-card-label">Human Takeover</div><div class="cust-card-value">${o.human_takeover ? 'Yes' : 'No'}</div></div>
        <div class="cust-card"><div class="cust-card-label">Turns</div><div class="cust-card-value">${o.turns}</div></div>
        ${histHtml}
        ${stateHistHtml}
        ${msgHtml}
      </div>
    `;
  } catch (err) {
    console.error(err);
  }
}

// ---- HITL Cases ----
async function loadCases() {
  try {
    const res = await fetch(`${API}/cases`);
    const data = await res.json();
    const cases = data.items || [];
    const container = document.getElementById('casesContainer');

    if (cases.length === 0) {
      container.innerHTML = '<div class="cases-empty">No HITL cases. Cases appear here when human intervention is triggered.</div>';
      return;
    }

    container.innerHTML = '';
    cases.forEach(c => {
      const card = document.createElement('div');
      card.className = 'case-card';
      // The API serializes status as "Open" / "Taken Over" / "Closed".
      // Normalize to canonical tokens (OPEN / TAKEN_OVER / CLOSED) so the
      // comparisons below match regardless of casing / spacing.
      const status = normalizeStatus(c.status);
      const statusClass = status === 'OPEN' ? 'open' : status === 'TAKEN_OVER' ? 'taken' : 'closed';
      const actions = status === 'OPEN'
        ? `<button class="btn-takeover-small" onclick="takeoverCase('${c.id}')">Take Over</button>
           <button class="btn-resolve" onclick="resolveCase('${c.id}')">Resolve</button>`
        : status === 'TAKEN_OVER'
        ? `<button class="btn-resolve" onclick="resolveCase('${c.id}')">Mark Resolved</button>`
        : '';
      card.innerHTML = `
        <div class="case-card-header">
          <span class="case-id">${c.id}</span>
          <span class="case-status ${statusClass}">${c.status}</span>
        </div>
        <div class="case-card-body">
          <div><strong>Customer</strong> ${escapeHtml(c.customer_name)} (${c.opportunity_id})</div>
          <div><strong>Reason</strong> ${escapeHtml(c.reason)}</div>
          <div><strong>Summary</strong> ${escapeHtml(c.summary || '—')}</div>
          <div><strong>Recommended</strong> ${escapeHtml(c.recommended_action || '—')}</div>
          <div><strong>Created</strong> ${c.created_at || '—'}</div>
        </div>
        <div class="case-card-actions">${actions}</div>
      `;
      container.appendChild(card);
    });
  } catch (err) {
    console.error('Cases load failed', err);
  }
}

async function takeoverCase(caseId) {
  try {
    await fetch(`${API}/cases/${caseId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'TAKEN_OVER' }),
    });
    loadCases();
    updateCaseBadge();
  } catch (err) {
    alert('Takeover failed: ' + err.message);
  }
}

async function resolveCase(caseId) {
  try {
    await fetch(`${API}/cases/${caseId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'CLOSED' }),
    });
    loadCases();
    updateCaseBadge();
  } catch (err) {
    alert('Resolve failed: ' + err.message);
  }
}

async function updateCaseBadge() {
  try {
    const res = await fetch(`${API}/cases`);
    const data = await res.json();
    const open = (data.items || []).filter(c => normalizeStatus(c.status) === 'OPEN').length;
    const badge = document.getElementById('caseBadge');
    if (open > 0) {
      badge.textContent = open;
      badge.classList.remove('hidden');
    } else {
      badge.classList.add('hidden');
    }
  } catch (e) { /* ignore */ }
}

// ---- Health check ----
async function checkHealth() {
  try {
    const res = await fetch('/health');
    await res.json();
    document.getElementById('providerStatus').textContent = 'Online';
  } catch {
    document.getElementById('providerStatus').textContent = 'Offline';
  }
}

// ---- Helpers ----
// Normalize a case status from the API ("Open" / "Taken Over" / "Closed")
// into a canonical token ("OPEN" / "TAKEN_OVER" / "CLOSED").
function normalizeStatus(s) {
  return String(s || '').toUpperCase().replace(/[\s-]+/g, '_');
}
function setText(id, val) { document.getElementById(id).textContent = val; }
function escapeHtml(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}
function intentLabel(v) {
  if (v >= 25) return 'High';
  if (v >= 16) return 'Medium';
  if (v >= 6) return 'Low-Medium';
  return 'Low';
}
function priorityColor(p) {
  if (p === 'HIGH') return '#dc2626';
  if (p === 'MEDIUM') return '#f59e0b';
  return '#64748b';
}
function priorityBadge(p) {
  if (p === 'HIGH') return 'badge-high';
  if (p === 'MEDIUM') return 'badge-medium';
  return 'badge-low';
}
function shortSignal(s) {
  if (s.startsWith('Expansion')) return s.replace('Expansion: ', 'Exp: ');
  return s;
}
function signalClass(s) {
  if (s.includes('Purchase')) return 'sig-purchase';
  if (s.includes('Hesitation')) return 'sig-hesitation';
  if (s.includes('Competitive')) return 'sig-competitive';
  if (s.includes('Expansion')) return 'sig-expansion';
  return 'sig-other';
}

// ---- Init ----
checkHealth();
updateCaseBadge();
