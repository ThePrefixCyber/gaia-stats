/* Shared presentation for the current cohort tables. Values stay numeric until display. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.GaiaTables = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const states = new WeakMap();
  const collator = new Intl.Collator('en', { numeric: true, sensitivity: 'base' });
  const number = new Intl.NumberFormat('en', { maximumFractionDigits: 2 });
  const integer = new Intl.NumberFormat('en', { maximumFractionDigits: 0 });
  const percent = new Intl.NumberFormat('en', { style: 'percent', maximumFractionDigits: 1 });
  const labels = {
    label: 'Observation', faction: 'Faction', samples: 'Samples', games: 'Games',
    available: 'Opportunities', frequency: 'Acquisition rate', score_samples: 'Measured samples',
    mean_score: 'Mean final net VP', mean_final_score: 'Mean final net VP', mean_rank: 'Mean rank',
    win_share: 'Win share', median: 'Median VP', q1: 'Lower quartile VP', q3: 'Upper quartile VP',
    final1: 'Final tile 1', final2: 'Final tile 2',
    'adv-terra': 'Terraforming', 'adv-nav': 'Navigation', 'adv-int': 'Artificial intelligence',
    'adv-gaia': 'Gaia Project', 'adv-eco': 'Economy', 'adv-sci': 'Science', 'adv-ext': 'Extra technology',
    ...Object.fromEntries(Array.from({ length: 6 }, (_, i) => ['round' + (i + 1), 'Round ' + (i + 1)]))
  };
  const titles = {
    metrics: 'Exact chart observations', comparison: 'Faction results',
    'round-comparison': 'Round scoring VP', 'final-comparison': 'Final scoring VP',
    'tech-comparison': 'Advanced technology results'
  };
  const isMissing = value => value == null || (typeof value === 'number' && !Number.isFinite(value));

  function formatValue(key, value) {
    if (isMissing(value)) return 'Unavailable';
    if (typeof value === 'number') {
      if (key === 'frequency' || key === 'win_share') return percent.format(value);
      return (['samples', 'games', 'available', 'score_samples'].includes(key) ? integer : number).format(value);
    }
    if (key === 'faction') return String(value).replaceAll('-', ' ').replace(/\b\w/g, letter => letter.toUpperCase());
    return Array.isArray(value) ? value.join(', ') : String(value);
  }

  // Missing observations are always last. Use original positions to make equal values stable.
  function sortRows(rows, key, direction = 'ascending', valueFor = row => row[key]) {
    const multiplier = direction === 'descending' ? -1 : 1;
    return rows.map((row, index) => ({ row, index })).sort((a, b) => {
      const left = valueFor(a.row), right = valueFor(b.row);
      if (isMissing(left) || isMissing(right)) {
        return isMissing(left) === isMissing(right) ? a.index - b.index : isMissing(left) ? 1 : -1;
      }
      const comparison = typeof left === 'number' && typeof right === 'number'
        ? left - right : collator.compare(String(left), String(right));
      return comparison * multiplier || a.index - b.index;
    }).map(item => item.row);
  }

  function render(target, rows, columns, options = {}) {
    const doc = target.ownerDocument;
    const make = (tag, text, className) => {
      const element = doc.createElement(tag);
      if (text != null) element.textContent = text;
      if (className) element.className = className;
      return element;
    };
    const title = options.title || titles[target.id] || 'Cohort results';
    target.setAttribute('role', 'region');
    target.setAttribute('aria-label', title);
    target.tabIndex = 0; // The horizontal scroll region remains keyboard-accessible on small screens.
    const table = make('table');
    table.className = 'data-table';
    const caption = make('caption', rows.length
      ? `${integer.format(rows.length)} rows. Select a column heading to sort.`
      : 'No observations match this selection.');
    table.append(caption);
    const heading = make('tr'), head = make('thead'), body = make('tbody');
    head.append(heading);
    table.append(head, body);
    const announcement = make('span', '', 'sr-only');
    announcement.setAttribute('role', 'status');
    announcement.setAttribute('aria-live', 'polite');
    const previous = states.get(target);
    const state = previous && columns.includes(previous.key) ? { ...previous } : { key: null, direction: 'ascending' };
    states.set(target, state);
    const headers = [];
    const displayValue = (key, value) => key === 'label' && options.kind && globalThis.GaiaTiles
      ? GaiaTiles.metric(options.kind, value) : formatValue(key, value);
    const rowNodes = rows.map(row => {
      const tr = make('tr');
      for (const key of columns) {
        const value = row[key];
        const cell = make('td');
        cell.className = key === 'label' || key === 'faction' ? 'cell-label' : 'cell-number';
        const display = displayValue(key, value);
        cell.append(make('span', display, isMissing(value) ? 'unavailable' : 'cell-value'));
        if (typeof value === 'number' && Number.isFinite(value)) cell.title = String(value);
        if (!isMissing(value) && row[key + '_n'] != null) {
          cell.append(make('small', `${integer.format(row[key + '_n'])} samples`, 'sample-count'));
        }
        tr.append(cell);
      }
      return { row, tr };
    });

    function applySort(announce) {
      const ordered = state.key ? sortRows(rowNodes.map((item, index) => ({ ...item.row, __tableIndex: index })), state.key, state.direction, row => {
          const value = row[state.key];
          return !isMissing(value) && (state.key === 'label' || state.key === 'faction')
            ? displayValue(state.key, value) : value;
        })
        .map(row => rowNodes[row.__tableIndex]) : rowNodes;
      body.replaceChildren(...ordered.map(item => item.tr));
      for (const { key, name, th, button, arrow } of headers) {
        const active = state.key === key;
        if (active) th.setAttribute('aria-sort', state.direction);
        else th.removeAttribute('aria-sort');
        arrow.textContent = active ? state.direction === 'ascending' ? '↑' : '↓' : '↕';
        button.setAttribute('aria-label', `${name}: sort ${active && state.direction === 'ascending' ? 'descending' : 'ascending'}`);
      }
      if (announce) announcement.textContent = `${title} sorted by ${headers.find(header => header.key === state.key).name}, ${state.direction}.`;
    }

    for (const key of columns) {
      let name = options.labels?.[key] || labels[key] || key.replaceAll('_', ' ');
      if (key.startsWith('adv-') && globalThis.GaiaTiles) name = GaiaTiles.position(key);
      const th = make('th');
      th.setAttribute('scope', 'col');
      if (key !== 'label' && key !== 'faction') th.className = 'cell-number';
      const button = make('button', null, 'sort-button');
      button.type = 'button';
      const arrow = make('span', '↕', 'sort-arrow');
      arrow.setAttribute('aria-hidden', 'true');
      button.append(make('span', name), arrow);
      button.addEventListener('click', () => {
        state.direction = state.key === key && state.direction === 'ascending' ? 'descending' : 'ascending';
        state.key = key;
        applySort(true);
      });
      th.append(button);
      heading.append(th);
      headers.push({ key, name, th, button, arrow });
    }
    if (rows.length) applySort(false);
    else {
      const empty = make('td', 'Try broadening the filters or choosing another plot.', 'empty-table');
      empty.colSpan = columns.length;
      const row = make('tr');
      row.append(empty);
      body.append(row);
      for (const { button } of headers) button.disabled = true;
    }
    target.replaceChildren(table, announcement);
  }

  return { render, sortRows, formatValue };
});
