/* ARAT Platform dashboard.
   All text from comments is inserted with textContent / text nodes (never innerHTML),
   because comments are untrusted public text. */
'use strict';

const CONCERN_LABELS = {
  range_anxiety: 'Range anxiety',
  charging_anxiety: 'Charging anxiety',
  battery_longevity_fear: 'Battery longevity fear',
  price_value_concern: 'Price / value concern',
  brand_trust_issue: 'Brand trust issue',
  after_sales_concern: 'After-sales concern',
  comfort_design_concern: 'Comfort & design',
  no_concern: 'No concern',
  unclear: 'Unclear',
};
const ACTION_LABELS = {
  AUTOMATED_RETENTION: 'Automated retention',
  DEALERSHIP_GUIDANCE: 'Dealership guidance',
  DIRECT_OUTREACH: 'Direct outreach',
  NO_ACTION: 'No action',
};
const RISK_ORDER = ['high', 'medium', 'low'];
const RISK_LABELS = { high: 'High', medium: 'Medium', low: 'Low' };
const SENTIMENT_LABELS = { positive: 'Positive', negative: 'Negative', neutral: 'Neutral', mixed: 'Mixed' };
const PAGE = 10;
const TOP_CONCERNS = 6;

let DATA = { rows: [], source: 'none', pool: {}, analyzer: '', car_models: [] };
const filters = { model: '', concern: '', risk: '', action: '', q: '' };
let shown = PAGE;
let showAllConcerns = false;
let selectedTestCommentId = null;
let selectedTestCommentText = '';
let lastAgentTrace = null;
let selectedHypothesisCount = 3;

/* ---------- helpers ---------- */
const $ = (id) => document.getElementById(id);

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === false || value == null) continue;
    if (key === 'class') node.className = value;
    else if (key === 'style') node.style.cssText = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat()) {
    node.append(child instanceof Node ? child : document.createTextNode(child ?? ''));
  }
  return node;
}

const label = (map, key) => map[key] || String(key || '—').replace(/_/g, ' ');
const isRealConcern = (c) => c && c !== 'no_concern' && c !== 'unclear';
const isSoftTone = (s) => s === 'positive' || s === 'neutral';
const pct = (n, total) => (total ? Math.round((100 * n) / total) : 0);
const fmt = (n) => Number(n).toLocaleString('en-US');

function countBy(rows, key) {
  const counts = {};
  rows.forEach((r) => { counts[r[key]] = (counts[r[key]] || 0) + 1; });
  return Object.entries(counts).sort((a, b) => b[1] - a[1]);
}

/* rows matching the filters, optionally ignoring some of them (so a chart keeps showing its own options) */
function apply(ignore = []) {
  const q = filters.q.trim().toLowerCase();
  return DATA.rows.filter((r) =>
    (ignore.includes('model') || !filters.model || r.car_model === filters.model) &&
    (ignore.includes('concern') || !filters.concern || r.latent_concern === filters.concern) &&
    (ignore.includes('risk') || !filters.risk || r.churn_risk === filters.risk) &&
    (ignore.includes('action') || !filters.action || r.action === filters.action) &&
    (ignore.includes('q') || !q || r.comment.toLowerCase().includes(q))
  );
}

function toggleFilter(key, value) {
  filters[key] = filters[key] === value ? '' : value;
  shown = PAGE;
  render();
}

function pill(text, cls = '') {
  return el('span', { class: `pill ${cls}`.trim() }, text);
}

/* ---------- KPIs ---------- */
function renderKpis() {
  const rows = apply(['q']);
  const high = rows.filter((r) => r.churn_risk === 'high').length;
  const soft = rows.filter((r) => isSoftTone(r.surface_sentiment));
  const hiddenBehindSoft = soft.filter((r) => isRealConcern(r.latent_concern)).length;
  const topConcern = countBy(rows.filter((r) => isRealConcern(r.latent_concern)), 'latent_concern')[0];
  const poolTotal = DATA.pool && DATA.pool.total;

  const cards = [
    kpi('Comments analyzed', fmt(rows.length),
        poolTotal ? `sample of ${fmt(poolTotal)} collected comments` : 'in this view'),
    kpi('High churn risk', `${pct(high, rows.length)}%`, `${fmt(high)} of ${fmt(rows.length)} comments`, 'danger'),
    kpi('Hidden behind a positive or neutral tone', soft.length ? `${pct(hiddenBehindSoft, soft.length)}%` : '—',
        soft.length ? `${fmt(hiddenBehindSoft)} of ${fmt(soft.length)} comments a sentiment tool would miss` : 'no positive or neutral comments'),
    kpi('Top hidden concern', topConcern ? label(CONCERN_LABELS, topConcern[0]) : '—',
        topConcern ? `${fmt(topConcern[1])} comments` : 'nothing detected', '', true),
  ];
  $('kpis').replaceChildren(...cards);
}

function kpi(title, value, sub, extra = '', small = false) {
  return el('div', { class: `kpi ${extra}`.trim() },
    el('div', { class: 'kpi-label' }, title),
    el('div', { class: `kpi-value${small ? ' small' : ''}` }, value),
    el('div', { class: 'kpi-sub' }, sub));
}

/* ---------- bar charts ---------- */
function renderBars(containerId, entries, labelMap, filterKey) {
  const container = $(containerId);
  if (!entries.length) { container.replaceChildren(el('div', { class: 'no-data' }, 'No comments match the filters.')); return; }
  const max = Math.max(...entries.map((e) => e[1]));
  container.replaceChildren(...entries.map(([key, n]) =>
    el('button', {
      class: 'bar-row', type: 'button', 'aria-pressed': String(filters[filterKey] === key),
      title: `Filter: ${label(labelMap, key)}`, onclick: () => toggleFilter(filterKey, key),
    },
      el('span', { class: 'bar-label' }, label(labelMap, key)),
      el('span', { class: 'bar-track' }, el('span', { class: 'bar-fill', style: `width:${(100 * n) / max}%` })),
      el('span', { class: 'bar-num' }, String(n)))));
}

function renderConcerns() {
  const entries = countBy(apply(['concern', 'q']), 'latent_concern');
  let visible = entries;
  if (!showAllConcerns && entries.length > TOP_CONCERNS) {
    visible = entries.slice(0, TOP_CONCERNS);
    // keep the selected concern visible even when it is not in the top list
    const active = entries.find(([key]) => key === filters.concern);
    if (active && !visible.includes(active)) visible = [...visible.slice(0, TOP_CONCERNS - 1), active];
  }
  renderBars('chart-concerns', visible, CONCERN_LABELS, 'concern');
  const toggle = $('concerns-toggle');
  toggle.hidden = entries.length <= TOP_CONCERNS;
  toggle.textContent = showAllConcerns ? `Show top ${TOP_CONCERNS} only` : `Show all ${entries.length} concerns`;
}
function renderActions() {
  renderBars('chart-actions', countBy(apply(['action', 'q']), 'action'), ACTION_LABELS, 'action');
}

/* ---------- risk donut ---------- */
function renderRisk() {
  const rows = apply(['risk', 'q']);
  const counts = Object.fromEntries(countBy(rows, 'churn_risk'));
  const total = rows.length;

  let acc = 0;
  const parts = [];
  RISK_ORDER.forEach((r) => {
    const share = total ? (100 * (counts[r] || 0)) / total : 0;
    if (share > 0) parts.push(`var(--${r}) ${acc}% ${acc + share}%`);
    acc += share;
  });
  const gradient = parts.length ? parts.join(', ') : 'var(--line) 0 100%';

  const donut = el('div', { class: 'donut', style: `background:conic-gradient(${gradient})`, role: 'img',
                            'aria-label': 'Churn risk distribution' },
    el('div', { class: 'donut-center' }, el('strong', {}, String(total)), el('span', {}, 'comments')));

  const legend = el('div', { class: 'legend' }, RISK_ORDER.map((r) =>
    el('button', { class: 'legend-item', type: 'button', 'aria-pressed': String(filters.risk === r),
                   onclick: () => toggleFilter('risk', r) },
      el('span', { class: `dot ${r}` }),
      el('span', {}, RISK_LABELS[r]),
      el('b', {}, `${counts[r] || 0} · ${pct(counts[r] || 0, total)}%`))));

  $('chart-risk').replaceChildren(donut, legend);
}

/* ---------- heatmap: concern x car model ---------- */
function renderHeatmap() {
  const rows = apply(['model', 'concern', 'q']);
  const models = [...new Set(DATA.rows.map((r) => r.car_model))].sort();
  const concerns = countBy(rows, 'latent_concern').map((e) => e[0]);
  if (!rows.length) { $('heatmap').replaceChildren(el('div', { class: 'no-data' }, 'No comments match the filters.')); return; }

  const grid = {};
  let max = 1;
  rows.forEach((r) => {
    const key = `${r.latent_concern}|${r.car_model}`;
    grid[key] = (grid[key] || 0) + 1;
    max = Math.max(max, grid[key]);
  });

  const head = el('tr', {}, el('th', {}, 'Hidden concern'), models.map((m) => el('th', { class: 'col' }, m)));
  const body = concerns.map((c) => el('tr', {},
    el('td', { class: 'row-head' }, label(CONCERN_LABELS, c)),
    models.map((m) => {
      const n = grid[`${c}|${m}`] || 0;
      const v = n / max;
      const active = filters.concern === c && filters.model === m;
      return el('td', { class: 'cell' }, n
        ? el('button', { type: 'button', class: v > 0.55 ? 'hot' : '', style: `--v:${v.toFixed(2)}`,
                         'aria-pressed': String(active), title: `${label(CONCERN_LABELS, c)} · ${m}: ${n}`,
                         onclick: () => {
                           const same = filters.concern === c && filters.model === m;
                           filters.concern = same ? '' : c; filters.model = same ? '' : m;
                           $('f-model').value = filters.model; shown = PAGE; render();
                         } }, String(n))
        : el('span', { class: 'muted' }, '·'));
    })));

  $('heatmap').replaceChildren(el('table', { class: 'heat' }, el('thead', {}, head), el('tbody', {}, body)));
}

/* ---------- comments table ---------- */
function renderTable() {
  const rows = apply();
  $('table-count').textContent = `${fmt(rows.length)} comment${rows.length === 1 ? '' : 's'}`;
  $('tab-count').textContent = fmt(rows.length);
  if (!rows.length) { $('table').replaceChildren(el('div', { class: 'no-data' }, 'No comments match the filters.')); $('more').hidden = true; return; }

  const head = el('tr', {}, ['Car model', 'Comment', 'Tone', 'Hidden concern', 'Risk', 'Action'].map((h) => el('th', {}, h)));
  const body = rows.slice(0, shown).map((r) => {
    const text = r.comment.length > 150 ? `${r.comment.slice(0, 150)}…` : r.comment;
    return el('tr', { class: 'clickable', tabindex: '0', onclick: () => openDrawer(r),
                      onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openDrawer(r); } } },
      el('td', {}, r.car_model),
      el('td', { class: 'comment-cell' }, text),
      el('td', {}, pill(label(SENTIMENT_LABELS, r.surface_sentiment))),
      el('td', {}, pill(label(CONCERN_LABELS, r.latent_concern), 'concern')),
      el('td', {}, pill(label(RISK_LABELS, r.churn_risk), r.churn_risk)),
      el('td', {}, label(ACTION_LABELS, r.action)));
  });
  $('table').replaceChildren(el('table', {}, el('thead', {}, head), el('tbody', {}, body)));

  const more = $('more');
  more.hidden = rows.length <= shown;
  more.textContent = `Show more (${Math.min(PAGE, rows.length - shown)} of ${rows.length - shown} remaining)`;
}

/* ---------- filter bar ---------- */
function renderChips() {
  const defs = [
    ['model', filters.model, filters.model],
    ['concern', filters.concern, label(CONCERN_LABELS, filters.concern)],
    ['risk', filters.risk, `${label(RISK_LABELS, filters.risk)} risk`],
    ['action', filters.action, label(ACTION_LABELS, filters.action)],
  ].filter((d) => d[1]);
  $('chips').replaceChildren(...defs.map(([key, , text]) =>
    el('span', { class: 'chip' }, text,
      el('button', { type: 'button', 'aria-label': `Remove filter ${text}`,
                     onclick: () => { filters[key] = ''; if (key === 'model') $('f-model').value = ''; shown = PAGE; render(); } }, '✕'))));
}

/* ---------- details (drawer and live result) ---------- */
function field(title, content) {
  return el('div', {}, el('div', { class: 'label' }, title), content);
}

function detailView(r, includeComment = true) {
  const parts = [];
  if (includeComment) parts.push(field('Comment', el('blockquote', {}, r.comment)));

  if (isSoftTone(r.surface_sentiment) && isRealConcern(r.latent_concern)) {
    parts.push(el('div', { class: 'callout' },
      `This comment sounds ${r.surface_sentiment}, but the agents detected a hidden concern: `,
      el('b', {}, label(CONCERN_LABELS, r.latent_concern)), '. A basic sentiment tool would miss it.'));
  }

  parts.push(el('div', { class: 'detail-grid' },
    field('Car model', r.car_model),
    field('Tone of the comment', pill(label(SENTIMENT_LABELS, r.surface_sentiment))),
    field('Hidden concern', pill(label(CONCERN_LABELS, r.latent_concern), 'concern')),
    field('Churn risk', pill(label(RISK_LABELS, r.churn_risk), r.churn_risk)),
    field('Recommended action', el('b', {}, label(ACTION_LABELS, r.action)))));

  parts.push(field(`What the agents inferred (${r.hypothesis_type || 'hypothesis'})`, el('p', {}, r.hypothesis || '—')));
  if (r.evidence) parts.push(field('Evidence in the comment', el('p', {}, r.evidence)));

  const copy = el('button', { class: 'btn', type: 'button' }, 'Copy message');
  copy.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(r.message); copy.textContent = 'Copied ✓'; }
    catch { copy.textContent = 'Copy failed'; }
    setTimeout(() => { copy.textContent = 'Copy message'; }, 1800);
  });
  parts.push(field('Suggested message', el('div', {},
    el('div', { class: 'message' }, r.message || '—'), el('div', { class: 'detail-actions' }, copy))));

  const quality = r.utility !== '' && r.utility != null && !isNaN(parseFloat(r.utility))
    ? `Response quality score: ${parseFloat(r.utility).toFixed(2)} / 1 · revisions: ${r.revisions_done || 0}` : '';
  if (quality) parts.push(el('p', { class: 'meta' }, quality));

  return el('div', { class: 'detail' }, parts);
}

function traceMetric(title, value) {
  const shownValue = value == null || value === '' || Number.isNaN(Number(value))
    ? '—' : Number(value).toFixed(3);
  return el('div', { class: 'trace-metric' }, el('span', {}, title), el('b', {}, shownValue));
}

function traceCopy(title, content, variant = '') {
  return el('div', { class: `trace-copy ${variant}` },
    el('h4', {}, title), el('p', {}, content || '—'));
}

function traceStageHeader(number, title, subtitle) {
  return el('div', { class: 'trace-stage-head' },
    el('span', { class: 'trace-stage-number' }, String(number).padStart(2, '0')),
    el('div', {}, el('h3', {}, title), el('p', { class: 'trace-note' }, subtitle)));
}

function hypothesisCard(h, stage, selectedId = null) {
  const card = el('article', { class: `trace-item${h.id === selectedId ? ' selected' : ''}` },
    el('div', { class: 'trace-item-head' },
      el('b', {}, `${h.id || 'Hypothesis'} · ${h.type || 'Unknown'}`),
      el('span', { class: 'pill concern' }, label(CONCERN_LABELS, h.latent_concern))));
  if (stage === 'initial') {
    card.append(traceCopy('Interpretation', h.explanation));
    card.append(el('div', { class: 'trace-meta-line' },
      el('span', {}, `Tone · ${label(SENTIMENT_LABELS, h.surface_sentiment)}`),
      el('span', {}, `Evidence · ${h.evidence || '—'}`)));
  } else {
    if (h.original_explanation) card.append(traceCopy('Before domain review', h.original_explanation));
    card.append(traceCopy('Refined interpretation', h.explanation, 'emphasis'));
    card.append(el('div', { class: 'trace-metrics' },
      traceMetric('Fit to this comment', h.p_cond), traceMetric('General likelihood', h.p_prior),
      traceMetric('Information gain', h.ig), traceMetric('Final selection score', h.score)));
    card.append(traceCopy('Domain review', `${h.compliant ? 'Compliant' : 'Needs adjustment'} · ${h.modification_log || 'No change was needed.'}`));
  }
  if (h.id === selectedId) card.append(el('span', { class: 'selected-badge' }, 'Selected by Agent 2'));
  return card;
}

function responseTraceCard(item, index, total) {
  const response = item.response || {};
  const validation = item.validation || {};
  return el('article', { class: 'trace-item' },
    el('div', { class: 'trace-item-head' }, el('b', {}, index === 0 ? 'Initial draft' : `Revision ${index}`),
      el('span', { class: 'pill' }, `${index + 1}/${total}`)),
    el('div', { class: 'trace-metrics' },
      traceMetric('Empathy', validation.empathy), traceMetric('Coherence', validation.coherence),
      traceMetric('Utility', validation.utility),
      el('div', { class: 'trace-metric' }, el('span', {}, 'Compliant'), el('b', {}, validation.compliant ? 'Yes' : 'No'))),
    el('div', { class: 'trace-meta-line' },
      el('span', {}, `Recommended action · ${label(ACTION_LABELS, response.action)}`),
      el('span', {}, `Risk · ${label(RISK_LABELS, response.churn_risk)}`)),
    traceCopy('Draft response', response.message, 'response-copy'),
    traceCopy('Quality review', validation.critique, 'review-copy'));
}

function renderAgentTrace(trace) {
  const initial = trace.initial_hypotheses || [];
  const refined = trace.refined_hypotheses || [];
  const response = trace.response || {};
  const revisions = response.revision_trace || [];
  const rounds = [
    el('section', { class: 'trace-stage' },
      traceStageHeader(1, `Initial interpretations (${initial.length})`, 'Agent 1 · Generates one candidate for each selected perspective.'),
      ...initial.map((h) => hypothesisCard(h, 'initial'))),
    el('section', { class: 'trace-stage' },
      traceStageHeader(2, `Evaluation and selection (${refined.length})`, 'Agent 2 · Refines every candidate, checks it against the domain rules, then selects the strongest one.'),
      el('p', { class: 'trace-explainer' }, 'Fit to this comment estimates how well a candidate explains this specific comment. General likelihood estimates how common it is overall. Information gain compares the two; the final score combines fit and information gain.'),
      ...refined.map((h) => hypothesisCard(h, 'refined', trace.selected_hypothesis_id))),
    el('section', { class: 'trace-stage' },
      traceStageHeader(3, 'Recommended response and review', `Agent 3 · Drafts and evaluates the response, revising it if needed. ${trace.hypothesis_count || initial.length} initial hypotheses were considered.`),
      ...(revisions.length ? revisions.map((item, index) => responseTraceCard(item, index, revisions.length)) : [
        responseTraceCard({ response: response.initial_response, validation: response.final_validation }, 0, 1),
      ])),
  ];
  return rounds;
}

function openAgentDetails(trace) {
  lastAgentTrace = trace;
  $('agent-details-body').replaceChildren(...renderAgentTrace(trace));
  $('agent-details-dialog').showModal();
}

let lastFocus = null;
function openDrawer(row) {
  lastFocus = document.activeElement;
  $('drawer-body').replaceChildren(detailView(row));
  $('drawer').classList.add('open');
  $('drawer').setAttribute('aria-hidden', 'false');
  $('backdrop').hidden = false;
  $('drawer-close').focus();
}
function closeDrawer() {
  $('drawer').classList.remove('open');
  $('drawer').setAttribute('aria-hidden', 'true');
  $('backdrop').hidden = true;
  if (lastFocus) lastFocus.focus();
}

/* ---------- live analysis ---------- */
/* Light the pill of the agent that is currently working (1, 2 or 3; 0 = none). */
const agentProgress = { stage: 0, since: 0 };  // read by the battery animation (initTestPage)
function setAgentStage(stage) {
  agentProgress.stage = stage;
  agentProgress.since = performance.now();
  document.querySelectorAll('#an-loader .charge-steps li').forEach((li, i) => {
    li.classList.toggle('active', i + 1 === stage);
  });
}

/* /api/analyze starts the analysis and returns a job id (validation errors come back
   directly as JSON). We then poll /api/analyze/<id> to light the pill of the agent that is
   working. If a poll skips a stage, each skipped pill is still lit briefly, in order. */
const POLL_MS = 400;
const MIN_STAGE_MS = 350;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitForAnalysis(res) {
  const start = await res.json();
  if (!res.ok || !start.job_id) throw new Error(start.error || 'The analysis failed.');
  let shownStage = 0;
  let failures = 0;
  for (;;) {
    let job;
    try {
      const poll = await fetch(`/api/analyze/${start.job_id}`, { cache: 'no-store' });
      job = await poll.json();
      if (!poll.ok) throw new Error(job.error || 'The analysis failed.');
      failures = 0;
    } catch (err) {
      if (++failures >= 5) throw err;  // tolerate a few network hiccups
      await sleep(POLL_MS);
      continue;
    }
    // Step through every stage up to the current one, one pill at a time.
    while (shownStage < (job.stage || 0)) {
      shownStage += 1;
      setAgentStage(shownStage);
      if (shownStage < job.stage || job.done) await sleep(MIN_STAGE_MS);
    }
    if (job.done) {
      if (job.error) throw new Error(job.error);
      return job.result;
    }
    await sleep(POLL_MS);
  }
}

async function analyze() {
  const status = $('an-status');
  const comment = selectedTestCommentId ? selectedTestCommentText : $('an-text').value.trim();
  status.className = 'status';
  if (comment.length < 8) { status.textContent = 'Please write a comment of at least 8 characters.'; status.classList.add('error'); return; }

  const button = $('an-run');
  setAgentStage(0);
  button.disabled = true;
  $('an-result').replaceChildren();
  const started = Date.now();
  const tick = () => { status.textContent = `Analyzing… ${Math.round((Date.now() - started) / 1000)} s (the three agents make many calls: up to a few minutes with Gemini)`; };
  tick();
  const timer = setInterval(tick, 1000);

  try {
    const res = await fetch('/api/analyze', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ comment, car_model: $('an-model').value,
        test_comment_id: selectedTestCommentId,
        hypothesis_count: Number($('an-hypothesis-count').value) }),
    });
    const data = await waitForAnalysis(res);
    status.textContent = `Done in ${Math.round((Date.now() - started) / 1000)} s.`;
    lastAgentTrace = data.agent_trace || null;
    const resultCard = el('section', { class: 'analysis-result' },
      el('div', { class: 'analysis-result-head' },
        el('div', {}, el('span', { class: 'result-kicker' }, 'ANALYSIS COMPLETE'),
          el('h3', {}, 'Comment analysis')),
        el('span', { class: 'result-model' }, data.car_model || $('an-model').value)),
      detailView(data, false));
    const moreDetails = el('button', { class: 'btn more-details-btn', type: 'button',
      onclick: () => { if (lastAgentTrace) openAgentDetails(lastAgentTrace); } }, 'More Details');
    $('an-result').replaceChildren(resultCard, moreDetails);
    if (selectedTestCommentId) {
      selectedTestCommentId = null;
      await refreshTestStatus();
    }
  } catch (err) {
    status.textContent = `Error: ${err.message}`;
    status.classList.add('error');
  } finally {
    clearInterval(timer);
    button.disabled = false;
  }
}

function updateTestButton(counts = DATA.test_counts || {}) {
  const total = Object.values(counts).reduce((sum, n) => sum + Number(n || 0), 0);
  $('an-pick-test').disabled = Boolean(DATA.test_pool_error) || total === 0;
}

async function refreshTestStatus() {
  const response = await fetch('/api/test-status');
  const data = await response.json();
  if (response.ok) {
    DATA.test_counts = data.test_counts;
    DATA.test_pool_error = '';
    updateTestButton(data.test_counts);
  }
}

async function pickTestComment() {
  const button = $('an-pick-test');
  const status = $('an-status');
  button.disabled = true;
  status.className = 'status';
  status.textContent = 'Picking a random unanalysed test comment…';
  try {
    const model = $('an-model').value;
    const res = await fetch(`/api/test-pick?car_model=${encodeURIComponent(model)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Could not pick a test comment.');
    selectedTestCommentId = data.comment_id;
    selectedTestCommentText = data.comment;
    $('an-model').value = data.car_model;
    status.textContent = `Random test comment selected for ${data.car_model}. Click Analyze to run it.`;
    $('selected-test-text').textContent = data.comment;
    $('selected-test-comment').hidden = false;
    $('an-result').replaceChildren();
    DATA.test_counts = data.test_counts;
    updateTestButton(data.test_counts);
  } catch (err) {
    selectedTestCommentId = null;
    selectedTestCommentText = '';
    status.textContent = err.message;
    status.classList.add('error');
    await refreshTestStatus();
  } finally {
    updateTestButton();
  }
}

/* ---------- main render + setup ---------- */
function render() {
  renderKpis(); renderConcerns(); renderRisk(); renderActions(); renderHeatmap(); renderChips(); renderTable();
}

/* ---------- Training statistics tabs ---------- */
function showTab(name, focus = false) {
  document.querySelectorAll('#dashboard .tab').forEach((tab) => {
    const active = tab.dataset.tab === name;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
    if (active && focus) tab.focus();
  });
  document.querySelectorAll('#dashboard .tab-pane').forEach((pane) => { pane.hidden = pane.id !== `pane-${name}`; });
}

function setupTabs() {
  const tabs = [...document.querySelectorAll('#dashboard .tab')];
  tabs.forEach((tab, i) => {
    tab.addEventListener('click', () => showTab(tab.dataset.tab));
    tab.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
      e.preventDefault();
      const next = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
      showTab(next.dataset.tab, true);
    });
  });
  $('concerns-toggle').addEventListener('click', () => { showAllConcerns = !showAllConcerns; renderConcerns(); });
}

function showPage(pageName) {
  if (pageName === 'home') {
    $('home-choices').hidden = true;
    $('explore-btn').setAttribute('aria-expanded', 'false');
  }
  document.querySelectorAll('.app-page').forEach((page) => {
    page.hidden = page.id !== `page-${pageName}`;
  });
  document.querySelectorAll('.sidebar-nav .nav-item').forEach((button) => {
    const active = button.dataset.page === pageName;
    button.classList.toggle('active', active);
    if (active) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function setupSource() {
  const badge = $('source-badge');
  const banner = $('banner');
  const n = DATA.rows.length;
  if (DATA.source === 'real') {
    badge.textContent = `Real results · ${n} comments`; badge.className = 'badge real'; badge.hidden = false;
  } else if (DATA.source === 'demo') {
    badge.textContent = `Demo data · ${n} comments`; badge.className = 'badge demo'; badge.hidden = false;
    banner.replaceChildren(el('b', {}, 'Demo data. '),
      'These results were produced by a fake model to test the pipeline, so they mean nothing. ',
      'Run ', el('code', {}, 'python main.py --phase train'), ' to build the real training memory and results.');
    banner.hidden = false;
  }
}

async function init() {
  const res = await fetch('/api/data');
  DATA = await res.json();
  setupSource();

  const savedCount = Number(sessionStorage.getItem('aratHypothesisCount'));
  selectedHypothesisCount = [2, 3, 4, 5].includes(savedCount) ? savedCount : 3;
  $('an-hypothesis-count').value = String(selectedHypothesisCount);
  $('an-hypothesis-count').addEventListener('change', (e) => {
    selectedHypothesisCount = Number(e.target.value);
    sessionStorage.setItem('aratHypothesisCount', String(selectedHypothesisCount));
  });

  $('analyzer').textContent = `Model used: ${DATA.analyzer}`;
  $('an-model').replaceChildren(...DATA.car_models.map((m) => el('option', { value: m }, m)));
  updateTestButton(DATA.test_counts);
  $('an-model').addEventListener('change', () => {
    selectedTestCommentId = null; selectedTestCommentText = '';
    $('selected-test-comment').hidden = true;
  });
  $('an-text').addEventListener('input', () => {
    selectedTestCommentId = null; selectedTestCommentText = '';
    $('selected-test-comment').hidden = true;
  });
  $('analyze-card').hidden = false;

  if (DATA.source === 'none') { $('empty').hidden = false; return; }

  const models = [...new Set(DATA.rows.map((r) => r.car_model))].sort();
  $('f-model').replaceChildren(el('option', { value: '' }, 'All models'), ...models.map((m) => el('option', { value: m }, m)));
  $('f-model').addEventListener('change', (e) => { filters.model = e.target.value; shown = PAGE; render(); });
  $('f-q').addEventListener('input', (e) => { filters.q = e.target.value; shown = PAGE; render(); });
  $('f-clear').addEventListener('click', () => {
    Object.keys(filters).forEach((k) => { filters[k] = ''; });
    $('f-model').value = ''; $('f-q').value = ''; shown = PAGE; render();
  });
  $('more').addEventListener('click', () => { shown += PAGE; renderTable(); });

  setupTabs();
  $('dashboard').hidden = false;
  render();
}

$('drawer-close').addEventListener('click', closeDrawer);
$('backdrop').addEventListener('click', closeDrawer);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDrawer(); });
document.querySelectorAll('[data-page="home"]').forEach((button) => {
  button.addEventListener('click', () => showPage('home'));
});
document.querySelectorAll('[data-page]:not([data-page="home"])').forEach((button) => {
  button.addEventListener('click', () => showPage(button.dataset.page));
});

/* "Explore the application": stay on the home page and let the person pick a section. */
$('explore-btn').addEventListener('click', () => {
  const choices = $('home-choices');
  choices.hidden = false;
  $('explore-btn').setAttribute('aria-expanded', 'true');
  choices.scrollIntoView({ behavior: 'smooth', block: 'center' });
  const nav = document.querySelector('.sidebar-nav');
  nav.classList.remove('attention');
  void nav.offsetWidth; /* restart the animation if clicked again */
  nav.classList.add('attention');
});
$('an-run').addEventListener('click', analyze);
$('an-pick-test').addEventListener('click', pickTestComment);
$('agent-details-close').addEventListener('click', () => $('agent-details-dialog').close());
init().catch((err) => {
  $('banner').replaceChildren(`Could not load the data: ${err.message}`);
  $('banner').hidden = false;
});

/* ---------- motion layer ----------
   Purely visual: scroll reveal, growing bars, counting KPI numbers.
   It only reads the DOM that the code above already builds and never touches the data or analysis logic.
   Skipped entirely when the system asks for reduced motion. */
(function initMotion() {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches || !('IntersectionObserver' in window)) return;
  document.documentElement.classList.add('motion');

  /* 1. reveal blocks as they scroll into view */
  const revealObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      entry.target.classList.add('in');
      revealObserver.unobserve(entry.target);
    });
  }, { threshold: 0.12 });
  document.querySelectorAll('[data-reveal]').forEach((node) => revealObserver.observe(node));

  /* 2. bars and donut grow each time their card becomes visible */
  const growObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      const box = entry.target;
      if (!entry.isIntersecting || box.classList.contains('play')) return;
      box.classList.add('play');
      setTimeout(() => box.classList.remove('play'), 1500);
    });
  }, { threshold: 0.2 });
  ['chart-concerns', 'chart-actions', 'chart-risk'].forEach((id) => { if ($(id)) growObserver.observe($(id)); });

  /* 3. KPI numbers count up (0 → value when shown, old value → new value when filters change) */
  const kpiBox = $('kpis');
  if (!kpiBox) return;
  const previous = [];
  let kpiVisible = false;
  const parseNumber = (text) => {
    const match = /^(\d[\d,]*)(%?)$/.exec(text.trim());
    return match ? { n: Number(match[1].replace(/,/g, '')), suffix: match[2] } : null;
  };
  function countTo(node, from, to, suffix) {
    const start = performance.now();
    const duration = 900;
    const step = (now) => {
      const p = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - p, 3);
      node.textContent = `${Math.round(from + (to - from) * eased).toLocaleString('en-US')}${suffix}`;
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  function scanKpis(fromZero) {
    kpiBox.querySelectorAll('.kpi-value').forEach((node, i) => {
      const value = parseNumber(node.textContent);
      if (!value) { previous[i] = null; return; }
      const from = fromZero ? 0 : previous[i];
      previous[i] = value.n;
      if (from != null && from !== value.n) countTo(node, from, value.n, value.suffix);
    });
  }
  new MutationObserver(() => scanKpis(false)).observe(kpiBox, { childList: true });
  new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting && !kpiVisible) { kpiVisible = true; scanKpis(true); }
      else if (!entry.isIntersecting) kpiVisible = false;
    });
  }).observe(kpiBox);
})();

/* ---------- "Test a comment" page: charging loader, risk meter ----------
   Visual helpers only. They watch the DOM that analyze() already updates; the analysis code is untouched. */
(function initTestPage() {
  const run = $('an-run');
  const loader = $('an-loader');
  const fill = $('battery-fill');
  const result = $('an-result');
  const text = $('an-text');
  if (!run || !loader || !fill || !result || !text) return;
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* Battery follows the agents: each agent fills its own third (1 -> 0-33 %, 2 -> 33-67 %,
     3 -> 67-100 %), slowing down near the end of its third while it works. When the analysis
     ends, the battery reaches 100 %, stays visible full for a moment, then fades out. */
  const HOLD_FULL_MS = 900;   // full battery stays visible this long before fading
  const FADE_MS = 700;        // matches the .charge-loader opacity transition
  let frame = 0;
  let fadeTimer = 0;
  let hideTimer = 0;
  let shown = 0;
  function targetWidth(now) {
    const { stage, since } = agentProgress;
    if (stage < 1) return 0;
    const third = 100 / 3;
    const start = (stage - 1) * third;
    if (reduceMotion) return start + third * 0.5;
    const seconds = (now - since) / 1000;
    return start + third * 0.92 * (1 - Math.exp(-seconds / 8));
  }
  function startCharge() {
    clearTimeout(fadeTimer);
    clearTimeout(hideTimer);
    cancelAnimationFrame(frame);
    loader.classList.remove('done', 'full');
    loader.hidden = false;
    shown = 0;
    fill.style.width = '0%';
    const tick = (now) => {
      // Glide toward the target (so finishing an agent fills its third smoothly), never backwards.
      const target = targetWidth(now);
      if (target > shown) shown = reduceMotion ? target : shown + Math.max(0.05, (target - shown) * 0.12);
      fill.style.width = `${shown}%`;
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
  }
  function stopCharge() {
    cancelAnimationFrame(frame);
    loader.classList.add('full');  // smooth jump to 100 %
    fill.style.width = '100%';
    fadeTimer = setTimeout(() => loader.classList.add('done'), HOLD_FULL_MS);
    hideTimer = setTimeout(() => { loader.hidden = true; loader.classList.remove('done', 'full'); },
      HOLD_FULL_MS + FADE_MS);
  }
  new MutationObserver(() => { if (run.disabled) startCharge(); else if (!loader.hidden) stopCharge(); })
    .observe(run, { attributes: true, attributeFilter: ['disabled'] });

  /* colored risk meter on top of each analysis result */
  const LEVELS = ['low', 'medium', 'high'];
  new MutationObserver(() => {
    const card = result.querySelector('.analysis-result');
    if (!card || card.dataset.risk) return;
    const pill = card.querySelector('.detail-grid .pill.low, .detail-grid .pill.medium, .detail-grid .pill.high');
    const level = pill && LEVELS.find((l) => pill.classList.contains(l));
    if (!level) return;
    card.dataset.risk = level;
    const lit = LEVELS.indexOf(level) + 1;
    const meter = el('div', { class: 'risk-meter', role: 'img', 'aria-label': `Churn risk: ${RISK_LABELS[level]}` },
      el('span', { class: 'risk-meter-label' }, 'CHURN RISK'),
      el('div', { class: 'risk-bars' }, LEVELS.map((l, i) => el('i', { class: i < lit ? `on ${level}` : '' }))),
      el('b', { class: `risk-meter-value ${level}` }, RISK_LABELS[level]));
    card.querySelector('.analysis-result-head').after(meter);
  }).observe(result, { childList: true });
})();

/* ---------- theme toggle and print button (top bar) ---------- */
(function initTopbarTools() {
  const root = document.documentElement;
  const toggle = $('theme-toggle');
  const print = $('print-btn');
  const current = () => root.dataset.theme || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  if (!root.dataset.theme) root.dataset.theme = current();

  function paint() {
    const dark = current() === 'dark';
    toggle.setAttribute('aria-pressed', String(dark));
    toggle.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
    toggle.title = dark ? 'Switch to light theme' : 'Switch to dark theme';
  }
  toggle.addEventListener('click', () => {
    const next = current() === 'dark' ? 'light' : 'dark';
    root.classList.add('theme-anim');
    root.dataset.theme = next;
    try { localStorage.setItem('aratTheme', next); } catch { /* private mode: the choice just is not remembered */ }
    paint();
    setTimeout(() => root.classList.remove('theme-anim'), 450);
  });
  print.addEventListener('click', () => window.print());
  paint();
})();