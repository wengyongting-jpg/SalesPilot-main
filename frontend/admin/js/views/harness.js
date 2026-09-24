/**
 * Test harness route — debug panel on the left, a real device on the right.
 *
 * The device is the **unmodified customer app** in an iframe, not a replica
 * (requirement 6.1, 6.3). Three consequences that matter:
 *
 * 1. Sales intelligence renders only in this panel. The iframe contains an app
 *    that has no shape for it, so the boundary is structural rather than a matter
 *    of discipline (requirement 6.12).
 * 2. Telemetry is fetched by this console from the admin surface and joined on
 *    `clientMessageId`. It is never routed through the device
 *    (requirement 6.11) — see docs/v0.0/api/interface-v1.md §3.
 * 3. Reconfiguration reloads the iframe with new query parameters rather than
 *    mutating a live transport. Rebuilding the gateway from scratch is the
 *    robust option, and the console itself never reloads (requirement 6.6).
 */
import { config } from '../config.js';
import { strings } from '../strings.js';
import { el, clear, badge, section, stateBlock, kvRow } from '../dom.js';
import { time, duration, count } from '../format.js';
import { createObservability } from './observability.js';

const OUTBOUND_SOURCE = 'salespilot-admin';

/**
 * @param {object} deps
 * @param {HTMLElement} deps.debugEl
 * @param {HTMLElement} deps.deviceEl
 * @param {object} deps.store
 * @param {(id: string) => void} deps.onSelectEntry
 * @param {(clientMessageId: string) => void} deps.onFetchRun
 */
export function createHarness({ debugEl, deviceEl, store, onSelectEntry, onFetchRun }) {
  /** @type {HTMLIFrameElement|null} */
  let frame = null;
  let readyTimer = null;
  let deviceBuilt = false;
  let lastDebugSignature = null;

  // The run detail reuses the Inbox route's observability renderer, which is why
  // the harness needs no telemetry UI of its own.
  const runDetailEl = el('div', {});
  const runDetail = createObservability({
    el: runDetailEl,
    onSelectRun: () => {},
    standalone: true,
  });

  /* ---- Device ---------------------------------------------------------- */

  function deviceSrc(harness) {
    const params = new URLSearchParams();
    if (harness.transport) params.set('transport', harness.transport);
    if (harness.customerId) params.set('customerId', harness.customerId);
    if (harness.customerName) params.set('customerName', harness.customerName);
    if (harness.scenario) params.set('scenario', harness.scenario);
    // Cache-buster so a reload always re-runs the boot handshake.
    params.set('_t', String(Date.now()));
    return `${config.customerAppPath}?${params.toString()}`;
  }

  function buildDevice(harness) {
    clear(deviceEl);

    frame = el('iframe', {
      className: 'device__screen',
      attrs: {
        src: deviceSrc(harness),
        width: config.device.width,
        height: config.device.height,
        title: strings.harness.deviceCaption,
        // The device is same-origin on purpose: postMessage needs a real origin,
        // which also means it cannot be opened from file://.
        loading: 'eager',
      },
    });

    deviceEl.append(
      el('div', {}, [
        el('div', { className: 'device' }, [frame]),
        el('div', { className: 'device__caption', text: strings.harness.deviceCaption }),
      ])
    );

    store.harnessConfigured({ deviceReady: false, deviceError: null });
    armReadyTimeout();
  }

  function armReadyTimeout() {
    if (readyTimer) clearTimeout(readyTimer);
    readyTimer = setTimeout(() => {
      if (!store.getState().harness.deviceReady) {
        store.deviceLost(strings.harness.deviceTimeout);
      }
    }, config.deviceReadyTimeoutMs);
  }

  function post(type, payload = {}) {
    if (!frame || !frame.contentWindow) return;
    // Explicit target origin, never '*'.
    frame.contentWindow.postMessage(
      { source: OUTBOUND_SOURCE, type, payload },
      window.location.origin
    );
  }

  /* ---- Inbound messages ------------------------------------------------ */

  window.addEventListener('message', (event) => {
    if (event.origin !== window.location.origin) return;
    const data = event.data;
    if (!data || data.source !== 'salespilot-customer') return;
    if (!frame || event.source !== frame.contentWindow) return;

    const payload = data.payload ?? {};
    switch (data.type) {
      case 'ready':
        if (readyTimer) clearTimeout(readyTimer);
        store.deviceReady(payload);
        break;
      case 'state':
        store.deviceStateReported(payload);
        break;
      case 'exchange':
        if (typeof payload.clientMessageId !== 'string') return;
        store.exchangeObserved(payload);
        onFetchRun(payload.clientMessageId);
        break;
      default:
        break;
    }
  });

  /* ---- Debug panel ----------------------------------------------------- */

  function sessionControls(harness) {
    const idInput = el('input', {
      className: 'field__input',
      attrs: {
        type: 'text',
        value: harness.customerId,
        'aria-label': strings.harness.customerIdLabel,
      },
    });
    const nameInput = el('input', {
      className: 'field__input',
      attrs: {
        type: 'text',
        value: harness.customerName,
        'aria-label': strings.harness.customerNameLabel,
      },
    });

    const transportSelect = el('select', {
      className: 'field__select',
      attrs: { 'aria-label': strings.harness.transportLabel },
    });
    for (const [value, label] of [
      ['mock', strings.harness.transportMock],
      ['salespilot', strings.harness.transportSalesPilot],
    ]) {
      const option = el('option', { text: label, attrs: { value } });
      if (harness.transport === value) option.selected = true;
      transportSelect.append(option);
    }

    const scenarioSelect = el('select', {
      className: 'field__select',
      attrs: { 'aria-label': strings.harness.scenarioLabel },
    });
    for (const [value, label] of [
      ['fresh', strings.harness.scenarioFresh],
      ['rendering', strings.harness.scenarioRendering],
    ]) {
      const option = el('option', { text: label, attrs: { value } });
      if (harness.scenario === value) option.selected = true;
      scenarioSelect.append(option);
    }

    const apply = el('button', {
      className: 'btn btn--primary btn--small',
      text: strings.harness.apply,
      attrs: { type: 'button' },
      on: {
        click: () => {
          store.harnessReset();
          store.harnessConfigured({
            customerId: idInput.value.trim(),
            customerName: nameInput.value.trim(),
            transport: transportSelect.value,
            scenario: scenarioSelect.value,
          });
          buildDevice(store.getState().harness);
        },
      },
    });

    const reload = el('button', {
      className: 'btn btn--secondary btn--small',
      text: strings.harness.reload,
      attrs: { type: 'button' },
      on: { click: () => buildDevice(store.getState().harness) },
    });

    const reset = el('button', {
      className: 'btn btn--secondary btn--small',
      text: strings.harness.reset,
      attrs: { type: 'button', disabled: !harness.deviceReady },
      on: {
        click: () => {
          post('reset');
          store.harnessReset();
        },
      },
    });

    return [
      el('div', { className: 'control-row' }, [
        el('div', { className: 'field' }, [
          el('label', {
            className: 'control-group__label',
            text: strings.harness.customerIdLabel,
          }),
          idInput,
        ]),
        el('div', { className: 'field' }, [
          el('label', {
            className: 'control-group__label',
            text: strings.harness.customerNameLabel,
          }),
          nameInput,
        ]),
      ]),
      el('div', { className: 'control-row' }, [
        el('div', { className: 'field' }, [
          el('label', {
            className: 'control-group__label',
            text: strings.harness.transportLabel,
          }),
          transportSelect,
        ]),
        el('div', { className: 'field' }, [
          el('label', {
            className: 'control-group__label',
            text: strings.harness.scenarioLabel,
          }),
          scenarioSelect,
        ]),
      ]),
      el('div', { className: 'control-row' }, [apply, reload, reset]),
    ];
  }

  /**
   * Deliver a human representative's reply into the device.
   *
   * Replaces an earlier "Send as customer" control. That one was redundant —
   * typing in the device on the right is exactly the same action. The customer's
   * view of a *human* reply is the thing nothing else in the product can show,
   * because the backend has no write path for one yet.
   */
  function repMessageControl(harness) {
    const nameInput = el('input', {
      className: 'field__input',
      attrs: {
        type: 'text',
        value: config.operator.name,
        'aria-label': strings.harness.repNameLabel,
      },
    });

    const textInput = el('input', {
      className: 'field__input',
      attrs: {
        type: 'text',
        placeholder: strings.harness.injectPlaceholder,
        'aria-label': strings.harness.injectLabel,
      },
    });

    const submit = () => {
      const text = textInput.value.trim();
      if (!text) return;
      post('receive', {
        text,
        author: 'human',
        repName: nameInput.value.trim() || config.operator.name,
      });
      textInput.value = '';
    };

    textInput.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter') return;
      event.preventDefault();
      submit();
    });

    return [
      el('div', { className: 'control-row' }, [
        el('div', { className: 'field' }, [
          el('label', {
            className: 'control-group__label',
            text: strings.harness.repNameLabel,
          }),
          nameInput,
        ]),
      ]),
      el('div', { className: 'control-row' }, [
        el('div', { className: 'field' }, [textInput]),
        el('button', {
          className: 'btn btn--primary btn--small',
          text: strings.harness.inject,
          attrs: { type: 'button', disabled: !harness.deviceReady },
          on: { click: submit },
        }),
      ]),
      el('div', {
        className: 'kv__val kv__val--muted',
        text: strings.harness.injectNote,
      }),
    ];
  }

  function liveStatus(harness) {
    const runningTokens = harness.timeline.reduce(
      (sum, entry) => sum + (entry.run?.totals?.totalTokens ?? 0),
      0
    );
    return el('div', { className: 'kv' }, [
      ...kvRow(
        strings.harness.deviceReadyLabel,
        harness.deviceReady
          ? strings.harness.deviceReadyYes
          : strings.harness.deviceReadyNo
      ),
      ...kvRow(strings.harness.connection, harness.connection),
      ...kvRow(
        strings.harness.takeover,
        harness.humanTakeover ? strings.intelligence.yes : strings.intelligence.no
      ),
      ...kvRow(
        strings.intelligence.messageCountLabel,
        harness.customerMessageCount
      ),
      ...kvRow(strings.observability.totalTokens, count(runningTokens)),
    ]);
  }

  function timelineEntry(entry, selected) {
    const okStatus = entry.status >= 200 && entry.status < 300;
    return el(
      'button',
      {
        className: selected ? 'timeline__entry is-selected' : 'timeline__entry',
        attrs: { type: 'button', 'aria-pressed': selected ? 'true' : 'false' },
        on: {
          click: () => {
            onSelectEntry(entry.id);
            if (!entry.run && entry.runStatus === 'idle') onFetchRun(entry.clientMessageId);
          },
        },
      },
      [
        el('span', { className: 'history__time', text: time(entry.at) }),
        el('span', { className: 'timeline__id', text: entry.clientMessageId }),
        badge(
          okStatus ? strings.harness.statusOk : strings.harness.statusFailed,
          okStatus ? 'badge--ok' : 'badge--error'
        ),
        el('span', { className: 'run__duration', text: duration(entry.durationMs) }),
      ]
    );
  }

  function selectedDetail(harness) {
    const entry = harness.timeline.find((e) => e.id === harness.selectedEntryId);
    if (!entry) {
      return stateBlock({ body: strings.harness.selectEntry });
    }

    const children = [
      el('div', { className: 'kv' }, [
        ...kvRow(strings.harness.correlationLabel, entry.clientMessageId),
        ...kvRow(strings.harness.durationLabel, duration(entry.durationMs)),
        ...kvRow(strings.harness.statusLabel, String(entry.status)),
      ]),
    ];

    if (entry.runStatus === 'loading') {
      children.push(
        el('div', { className: 'kv__val kv__val--muted', text: strings.harness.runPending })
      );
    } else if (entry.runStatus === 'error') {
      children.push(
        el('div', { className: 'case__error', text: strings.harness.runFailed })
      );
    } else if (!entry.run) {
      children.push(
        el('div', { className: 'kv__val kv__val--muted', text: strings.harness.runMissing })
      );
    } else {
      if (entry.run.simulated) {
        children.push(
          el('div', { className: 'notice', attrs: { role: 'note' } }, [
            el('span', { text: strings.harness.simulatedRun }),
          ])
        );
      }
      runDetail.renderRun(entry.run);
      children.push(runDetailEl);
    }

    return el('div', {}, children);
  }

  return {
    render(state) {
      if (state.route !== 'harness') return;

      if (!deviceBuilt) {
        deviceBuilt = true;
        // Seed identity from the customer app's own default on first entry.
        if (!store.getState().harness.customerId) {
          store.harnessConfigured({ customerId: 'C-2001', customerName: 'Sam' });
        }
        buildDevice(store.getState().harness);
      }

      const harness = state.harness;
      const signature = [
        harness.deviceReady,
        Boolean(harness.deviceError),
        harness.connection,
        harness.humanTakeover,
        harness.customerMessageCount,
        harness.timeline.length,
        harness.selectedEntryId,
        harness.timeline.map((e) => `${e.id}:${e.runStatus}`).join(','),
      ].join('|');
      if (signature === lastDebugSignature) return;
      lastDebugSignature = signature;

      clear(debugEl);

      debugEl.append(
        el('div', { className: 'route-head' }, [
          el('h1', { className: 'route-head__title', text: strings.harness.title }),
        ])
      );

      debugEl.append(
        el('div', { className: 'notice', attrs: { role: 'note' } }, [
          el('span', { text: strings.harness.isolationNote }),
        ])
      );

      if (harness.deviceError) {
        debugEl.append(
          el('div', { className: 'case__error', text: harness.deviceError })
        );
      }

      debugEl.append(section(strings.harness.sessionTitle, sessionControls(harness)));
      debugEl.append(section(strings.harness.injectTitle, repMessageControl(harness)));
      debugEl.append(section(strings.harness.statusTitle, [liveStatus(harness)]));

      debugEl.append(
        section(
          strings.harness.timelineTitle,
          harness.timeline.length === 0
            ? [stateBlock({ body: strings.harness.timelineEmpty })]
            : [
                el(
                  'div',
                  { className: 'timeline' },
                  [...harness.timeline]
                    .reverse()
                    .map((entry) =>
                      timelineEntry(entry, entry.id === harness.selectedEntryId)
                    )
                ),
              ]
        )
      );

      debugEl.append(section(strings.harness.detailTitle, [selectedDetail(harness)]));
    },
  };
}
