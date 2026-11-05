/* Host controller (/control). Only the host owns handoff timers. Each mutation is checked against its revision.

   Sections:
     - match state, painting and writes (mutate)
     - game setup: players (recent names as one-tap chips), game, double out, camera or manual (M3 UI-02);
       the draft is mirrored to the TV lobby through /api/lobby
     - win: Rematch (same players, the next player starts) and New game (M3 UI-03)
     - tap-the-board entry (M1-11) and camera darts (M1-12)
     - polish: camera status chip, toasts, haptics, Screen Wake Lock (M3 UI-05) */
(() => {
  const $ = s => document.querySelector(s);
  let state = null, busy = false, ring = 1, timer = null, tick = null, pausedRevision = null, showSetup = false;
  let entryReadyAt = 0, checking = false, lastHealthy = 0;

  const notice = message => { $('#notice').textContent = message; };
  document.querySelectorAll('a.brand').forEach(a => { a.href = '#'; });
  document.querySelector('footer a').href = '/?t=' + encodeURIComponent(DartRoom.token);

  /* ---- Polish helpers (M3 UI-05) ---- */
  function buzz(ms = 12) {
    try { if (navigator.vibrate) navigator.vibrate(ms); } catch { /* not supported */ }
  }

  function toast(text, kind = 'good', ms = 2200) {
    const item = document.createElement('div');
    item.className = 'toast ' + kind;
    item.textContent = text;
    const stack = $('#toasts');
    stack.append(item);
    while (stack.children.length > 3) stack.firstElementChild.remove();
    setTimeout(() => {
      item.classList.add('leaving');
      setTimeout(() => item.remove(), 350);
    }, ms);
  }

  const keepAwake = DartRoom.keepAwake(() => !!state?.game && state.game.winner === null && !showSetup);

  const back = document.createElement('button');
  back.type = 'button';
  back.id = 'back-to-match';
  back.className = 'ghost';
  back.textContent = 'Back to the match';
  back.hidden = true;
  $('#setup').append(back);
  back.onclick = () => {
    showSetup = false;
    sendLobby({open: false});
    paint();
  };

  function cancel() {
    clearTimeout(timer);
    clearInterval(tick);
    timer = tick = null;
    $('#handoff').textContent = '';
    $('#cancel').hidden = true;
  }

  function done() {
    return state?.game && state.game.winner === null && (state.game.bust || state.game.darts.length === 3);
  }

  function paint() {
    const g = state?.game;
    const inSetup = !g || showSetup;
    if (inSetup) DartRoom.renderLobby(draftLobby());
    else DartRoom.render(g, {checkout: state.checkout, stats: state.stats});
    $('#setup').hidden = !inSetup;
    $('#entry').hidden = inSetup;
    $('#display-link').href = state?.presentation_path || '/play';
    back.hidden = !g || !showSetup;
    paintSetup();
    keepAwake();
    cameraChip();
    if (!g) return;
    const won = g.winner !== null;
    $('#prompt').textContent = won ? g.names[g.winner] + ' wins!'
      : done() ? 'Turn complete · ' + g.names[(g.player + 1) % g.names.length] + ' up next'
        : g.names[g.player] + ' · dart ' + (g.darts.length + 1) + ' of 3';
    $('#entry').classList.toggle('won', won);
    $('#win-panel').hidden = !won;
    if (won) paintWin(g);
    $('#record').disabled = busy || Date.now() < entryReadyAt || done() || won;
    $('#next').disabled = busy || !done();
    $('#undo').disabled = busy;
    const tap = tapAllowed();
    $('#tap-board').classList.toggle('disabled', !tap);
    $('#miss').disabled = !tap;
    paintCamera();
  }

  function schedule() {
    cancel();
    if (!done() || !$('#auto').checked || pausedRevision === state.revision) return;
    const rev = state.revision;
    let left = 4;
    $('#cancel').hidden = false;
    $('#handoff').textContent = 'Next player in ' + left + ' seconds · Undo or pause to review.';
    tick = setInterval(() => {
      left--;
      $('#handoff').textContent = 'Next player in ' + Math.max(left, 0) + ' seconds · Undo or pause to review.';
    }, 1000);
    timer = setTimeout(() => handoff(rev, 0), 4000);
  }

  // QA M1-17 #4: the handoff used to give up when a state poll happened to be in flight (every 0.4 s in camera
  // games) or a write was running at that instant. Now it waits for them; it pauses only on a real connection problem.
  function handoff(rev, waited) {
    if (state.revision !== rev || !done()) { cancel(); return; }
    if ((checking || busy) && waited < 3000) { timer = setTimeout(() => handoff(rev, waited + 100), 100); return; }
    cancel();
    if (busy || Date.now() - lastHealthy > 3000) {
      pausedRevision = rev;
      notice('Connection check pending. Handoff paused; review the turn before choosing Next player.');
      return;
    }
    mutate('/api/next', {}, false);
  }

  // Sends one write. Resolves to true if the server recorded it, false if not (QA M1-17 #5: callers show that).
  async function mutate(path, body = {}, allowSchedule = true) {
    if (busy) return false;
    if (['/api/throw', '/api/correct', '/api/turn/fill_misses'].includes(path)) {
      if (Date.now() < entryReadyAt) return false;
      entryReadyAt = Date.now() + 600;
      setTimeout(paint, 610);
    }
    cancel();
    busy = true;
    notice('');
    paint();
    const revision = state?.revision;
    try {
      const payload = {...body, expected_revision: revision};
      state = await DartRoom.request(path, payload);
      showSetup = false;
      pausedRevision = null;
      paint();
      if (allowSchedule) schedule();
      return true;
    } catch (e) {
      pausedRevision = e.state?.revision ?? revision;
      if (e.state?.game !== undefined) state = e.state;  // a 409 carries the current match: show it
      notice(e.status === 409 ? e.message : e.status ? 'Could not save: ' + e.message : 'Connection interrupted. Check the current match before trying again.');
      if (!e.status) {
        try { state = await DartRoom.request('/api/state'); } catch { /* still offline */ }
      }
      return false;
    } finally {
      busy = false;
      paint();
    }
  }

  /* ---- Game setup (M3 UI-02) ---- */
  const setup = {start: 301, doubleOut: false, scoring: null};  // scoring null = automatic from camera readiness

  function cameraReady() {
    return !!state?.vision?.verified;
  }

  function chosenScoring() {
    if (setup.scoring === 'camera' && cameraReady()) return 'camera';
    if (setup.scoring === 'manual') return 'manual';
    return cameraReady() ? 'camera' : 'manual';
  }

  function nameInputs() {
    return [...$('#names').querySelectorAll('input')];
  }

  function players() {
    return nameInputs().map(input => input.value.trim()).filter(Boolean);
  }

  function draftLobby() {
    return {open: true, players: players(), start: setup.start, double_out: setup.doubleOut};
  }

  function addRow(value = '') {
    const rows = $('#names');
    if (rows.children.length >= 4) return null;
    const seat = rows.children.length;
    const row = document.createElement('div');
    row.className = 'player-row';
    const badge = document.createElement('span');
    badge.className = 'avatar';
    badge.dataset.seat = String(seat);
    const input = document.createElement('input');
    input.name = 'player';
    input.maxLength = 30;
    input.autocomplete = 'off';
    input.placeholder = 'Player ' + (seat + 1);
    input.setAttribute('aria-label', 'Player ' + (seat + 1) + ' name');
    input.value = value;
    input.oninput = () => { paintSetup(); lobbyChanged(); };
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'remove-player';
    remove.setAttribute('aria-label', 'Remove player ' + (seat + 1));
    remove.textContent = '×';
    remove.onclick = () => {
      buzz();
      if (rows.children.length > 2) row.remove();
      else input.value = '';
      renumber();
      paintSetup();
      lobbyChanged();
    };
    row.append(badge, input, remove);
    rows.append(row);
    return input;
  }

  function renumber() {
    [...$('#names').children].forEach((row, seat) => {
      row.querySelector('.avatar').dataset.seat = String(seat);
      const input = row.querySelector('input');
      input.placeholder = 'Player ' + (seat + 1);
      input.setAttribute('aria-label', 'Player ' + (seat + 1) + ' name');
      row.querySelector('.remove-player').setAttribute('aria-label', 'Remove player ' + (seat + 1));
    });
  }

  function setPlayers(names) {
    $('#names').replaceChildren();
    for (const name of names.slice(0, 4)) addRow(name);
    while ($('#names').children.length < 2) addRow();
  }

  // A recent name: tap to add it (to the first empty row, or a new one); tap again to take it out.
  function toggleRecent(name) {
    buzz();
    const inputs = nameInputs();
    const existing = inputs.find(input => input.value.trim().toLowerCase() === name.toLowerCase());
    if (existing) {
      existing.value = '';
      if ($('#names').children.length > 2) existing.closest('.player-row').remove();
      renumber();
    } else {
      const empty = inputs.find(input => !input.value.trim());
      const target = empty || addRow();
      if (!target) { toast('Four players is the most', 'bad'); return; }
      target.value = name;
    }
    paintSetup();
    lobbyChanged();
  }

  function paintSetup() {
    const g = state?.game;
    for (const row of [...$('#names').children]) {
      const input = row.querySelector('input');
      row.querySelector('.avatar').textContent = input.value.trim() ? DartRoom.initials(input.value) : String(Number(row.querySelector('.avatar').dataset.seat) + 1);
    }
    const count = players().length;
    $('#player-count').textContent = count + ' of 2–4';
    $('#add-player').disabled = $('#names').children.length >= 4;
    const recent = state?.lobby?.recent || [];
    const chips = $('#recent');
    const chosen = new Set(players().map(name => name.toLowerCase()));
    const key = JSON.stringify([recent, [...chosen]]);
    if (chips.dataset.key !== key) {
      chips.dataset.key = key;
      chips.replaceChildren(...recent.map(name => {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'recent-chip';
        chip.textContent = name;
        chip.setAttribute('aria-pressed', String(chosen.has(name.toLowerCase())));
        chip.onclick = () => toggleRecent(name);
        return chip;
      }));
    }
    chips.hidden = recent.length === 0;
    document.querySelectorAll('.game-option[data-start]').forEach(button => {
      button.setAttribute('aria-pressed', String(Number(button.dataset.start) === setup.start));
    });
    $('#double-out').setAttribute('aria-pressed', String(setup.doubleOut));
    const scoring = chosenScoring();
    document.querySelectorAll('[data-scoring]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.scoring === scoring));
      if (button.dataset.scoring === 'camera') button.disabled = !cameraReady();
    });
    $('#scoring-note').textContent = cameraReady()
      ? (scoring === 'camera' ? 'Camera is ready: darts are scored automatically, tap to correct.' : 'Manual: tap each dart on the board.')
      : 'Camera not ready, so darts are tapped in by hand. Set up the camera on the Mac to score automatically.';
  }

  // Mirror the draft to the TV lobby. Serialised, so a Start always follows the last lobby write.
  let lobbyQueue = Promise.resolve(), lobbyTimer = null;
  function sendLobby(body) {
    clearTimeout(lobbyTimer);
    lobbyTimer = null;
    lobbyQueue = lobbyQueue.then(() => DartRoom.request('/api/lobby', {...body, expected_revision: state?.revision ?? 0}))
      .then(fresh => {
        if (state && fresh.revision === state.revision) state.lobby = fresh.lobby;
      })
      .catch(() => { /* the lobby is cosmetic; the next change sends it again */ });
    return lobbyQueue;
  }
  function lobbyChanged() {
    clearTimeout(lobbyTimer);
    lobbyTimer = setTimeout(() => sendLobby(draftLobby()), 250);
    DartRoom.renderLobby(draftLobby());
  }

  function openSetup(names) {
    cancel();
    pausedRevision = state?.revision ?? null;
    showSetup = true;
    if (names) setPlayers(names);
    if (state?.game) {
      setup.start = state.game.start;
      setup.doubleOut = state.game.double_out;
    }
    paint();
    sendLobby(draftLobby());
    nameInputs()[0]?.focus();
  }

  $('#add-player').onclick = () => {
    buzz();
    const input = addRow();
    renumber();
    paintSetup();
    input?.focus();
  };
  document.querySelectorAll('.game-option[data-start]').forEach(button => {
    button.onclick = () => { buzz(); setup.start = Number(button.dataset.start); paintSetup(); lobbyChanged(); };
  });
  $('#double-out').onclick = () => { buzz(); setup.doubleOut = !setup.doubleOut; paintSetup(); lobbyChanged(); };
  document.querySelectorAll('[data-scoring]').forEach(button => {
    button.onclick = () => { buzz(); setup.scoring = button.dataset.scoring; paintSetup(); };
  });

  $('#setup').onsubmit = async event => {
    event.preventDefault();
    const names = players();
    if (names.length < 2) {
      notice('Add at least two players.');
      nameInputs().find(input => !input.value.trim())?.focus();
      return;
    }
    if (new Set(names.map(name => name.toLowerCase())).size !== names.length) {
      notice('Each player needs a different name.');
      return;
    }
    buzz(20);
    clearTimeout(lobbyTimer);
    await lobbyQueue;
    const camera = chosenScoring() === 'camera';
    if (await mutate('/api/game', {names, start: setup.start, double_out: setup.doubleOut, camera})) {
      toast(`${setup.start} · ${names.join(' vs ')} · ${camera ? 'camera scoring' : 'manual scoring'}`);
    }
  };

  /* ---- Win: Rematch and New game (M3 UI-03) ---- */
  function paintWin(g) {
    const winner = state.stats?.players?.[g.winner];
    $('#win-summary').textContent = winner
      ? `${g.names[g.winner]} wins · ${winner.average.toFixed(1)} average · ${winner.checkout ?? '—'} checkout`
      : `${g.names[g.winner]} wins`;
  }

  $('#rematch').onclick = async () => {
    const g = state?.game;
    if (!g || busy) return;
    buzz(20);
    // Same players; the player after this game's starter throws first.
    const names = [...g.names.slice(1), g.names[0]];
    const camera = !!state.camera_game && cameraReady();
    if (await mutate('/api/game', {names, start: g.start, double_out: g.double_out, camera})) {
      toast('Rematch · ' + names[0] + ' throws first');
    }
  };
  $('#new-match').onclick = () => { buzz(); openSetup(state?.game?.names); };

  /* ---- Keypad (fallback entry) ---- */
  $('#value').replaceChildren();
  for (const [v, title] of [[0, 'Miss'], ...[...Array(20)].map((_, i) => [i + 1, String(i + 1)]), [25, 'Bull / outer bull']]) {
    const option = document.createElement('option');
    option.value = v;
    option.textContent = title;
    $('#value').append(option);
  }
  $('#value').value = 20;
  function normalize() {
    const v = Number($('#value').value);
    if (v === 0) ring = 1;
    if (v === 25 && ring === 3) ring = 2;
    document.querySelectorAll('[data-ring]').forEach(button => {
      const r = Number(button.dataset.ring);
      button.disabled = (v === 0 && r !== 1) || (v === 25 && r === 3);
      button.setAttribute('aria-pressed', String(r === ring));
    });
    $('#entry-preview').textContent = DartRoom.label({value: v, multiplier: ring}) + ' · ' + (v * ring) + ' points';
  }
  document.querySelectorAll('[data-ring]').forEach(button => { button.onclick = () => { ring = Number(button.dataset.ring); normalize(); }; });
  $('#value').onchange = normalize;
  normalize();
  $('#dart-form').onsubmit = event => {
    event.preventDefault();
    if ($('#record').disabled) return;
    buzz();
    mutate('/api/throw', {value: Number($('#value').value), multiplier: ring});
  };

  /* ---- Tap-the-board entry (M1-11) and camera darts (M1-12) ----
     A tap does one of three things:
       - a committed dart chip is selected: correct that dart (/api/correct; 2 taps in all);
       - a camera dart is pending: commit the tapped value instead of it (1 tap; logged as a correction);
       - otherwise: record a manual dart (also how a missed detection is entered).
     Camera darts auto-accept on the server after a few seconds unless corrected or paused (owner decision #1). */
  let correcting = null, polledAt = performance.now();
  const pending = () => state?.camera_game ? state.camera?.pending || null : null;
  // Every pending camera dart, oldest (the one Accept and taps apply to) first (M4-01).
  const pendingDarts = () => state?.camera_game ? state.camera?.pending_darts || (pending() ? [pending()] : []) : [];

  function tapAllowed() {
    const g = state?.game;
    if (!g || busy || Date.now() < entryReadyAt) return false;
    if (correcting !== null) return correcting < g.darts.length;
    return !done() && g.winner === null;
  }

  function tapScore(value, multiplier, key) {
    if (!tapAllowed()) return;
    buzz();
    if (key) DartBoard.flash($('#tap-board'), key);
    const text = value === 0 ? 'Miss' : DartBoard.label(value, multiplier);
    if (correcting !== null) {
      const index = correcting;
      correcting = null;
      const result = mutate('/api/correct', {dart_index: index, value, multiplier});
      report('Dart ' + (index + 1) + ' corrected to ' + text, result);
      result.then(ok => { if (ok) toast('Dart ' + (index + 1) + ' corrected to ' + text); });
      return;
    }
    const p = pending();
    if (p) {
      const result = mutate('/api/throw', {value, multiplier, replaces_proposal_id: p.id});
      report(text + ' (instead of camera ' + p.label + ')', result);
      result.then(ok => { if (ok) toast('Camera ' + p.label + ' corrected to ' + text); });
      return;
    }
    report(text, mutate('/api/throw', {value, multiplier}));
  }

  // Tap feedback follows the server's answer: "saving…", then the value, or "Not recorded" (QA M1-17 #5).
  function report(text, result) {
    const feedback = $('#tap-feedback');
    feedback.textContent = text + ' · saving…';
    feedback.classList.remove('refused');
    result.then(ok => {
      if (feedback.textContent !== text + ' · saving…') return;
      feedback.textContent = ok ? text : 'Not recorded: ' + text + '. Check the turn and tap again.';
      feedback.classList.toggle('refused', !ok);
    });
  }

  DartBoard.tapBoard($('#tap-board'), tapScore);
  $('#miss').onclick = () => tapScore(0, 1, null);
  // Accept names the value the host saw: a near-wire label that flipped since then gives 409 (QA Q4).
  $('#accept').onclick = () => {
    const p = pending();
    if (p && !busy && !p.turn_over) { buzz(); mutate('/api/throw', {proposal_id: p.id, label: p.label}); }
  };
  $('#auto-pause').onclick = () => {
    if (!busy) mutate('/api/camera/auto_commit', {paused: !state.camera.auto_commit.paused}, false);
  };
  $('#end-turn').onclick = () => {
    if (!busy) { buzz(); mutate('/api/turn/fill_misses', {}); }
  };

  function dartText(d) {
    return d.value === 0 ? (d.filled ? 'Miss · filled in' : 'Miss') : DartBoard.label(d.value, d.multiplier);
  }

  function chip(d, i) {
    // Short visible text so all three chips fit a phone row (demo: dart 3 was off-screen); full text for screen readers.
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'dart-chip' + (correcting === i ? ' selected' : '') + (d.filled ? ' filled' : '');
    const full = document.createElement('span');
    full.className = 'visually-hidden';
    full.textContent = 'Dart ' + (i + 1) + ': ' + dartText(d);
    b.append((i + 1) + ' · ' + DartRoom.label(d) + (d.filled ? '*' : ''), full);
    b.setAttribute('aria-pressed', String(correcting === i));
    b.onclick = () => { buzz(); correcting = correcting === i ? null : i; paint(); };
    return b;
  }

  // The camera panel has fixed-height lines (QA R1): a headline and a two-line detail.
  function pendingText(p) {
    if (!p) {
      const v = state.vision || {};
      if (v.verified) return ['Camera: watching for the next dart', ''];
      // Say what is wrong and what to do (QA M1-17 #3); tapping the board always works meanwhile.
      const phases = {
        camera_disconnected: ['Camera reconnecting…', 'Phone stream lost. It reconnects by itself; tap darts on the board meanwhile.'],
        needs_alignment: ['Board check needed', v.message && /Camera back/.test(v.message) ? v.message
          : 'Checking the board… If this stays: on the Mac press Check / realign board, then Markers correct.'],
        review_overlay: ['Check the overlay on the Mac', 'Then press Markers correct · Ready to play.'],
        calibrating: ['Calibrating on the Mac', 'Select the four points on the setup page.'],
        waiting_camera: ['Camera not connected', 'Connect the phone on the Mac setup page.'],
        ready_to_calibrate: ['Camera not calibrated', 'Set the four points on the Mac setup page.'],
      };
      return phases[v.phase] || ['Camera: not ready', v.message || 'Check the setup page on the Mac.'];
    }
    // What to do comes first, so a narrow phone never cuts it off (QA M4 L3); then why.
    const notes = [];
    if (p.turn_over) notes.push('turn is over: Undo, End turn or Next player');
    else if (p.commit_in == null) notes.push('waiting for Accept');
    else notes.push('auto-accept in ' + Math.max(0, p.commit_in - (performance.now() - polledAt) / 1000).toFixed(1) + ' s');
    const reasons = (p.check || []).slice();  // low confidence (M4-02): waits for Accept
    if (p.near_wire) reasons.push('near a wire');
    if (p.together) reasons.push(p.together + ' darts at once, order?');
    if (p.label_changes) reasons.push('value changed');
    if (reasons.length) notes.push('check: ' + reasons.join(', '));
    const later = pendingDarts().length - 1;
    const queue = later > 0 ? ' · +' + later + ' waiting' : '';  // the later darts are marked on the board
    return ['Camera: ' + p.label + ' (' + p.score + ')' + queue, notes.join(' · ')];
  }

  // The camera status chip in the header (fixed size, so nothing below it moves).
  function cameraChip() {
    const chipEl = $('#camera-chip');
    let status = 'manual', text = 'Manual';
    if (state?.game && state.camera_game) {
      const v = state.vision || {};
      if (pending()) { status = 'pending'; text = 'Pending'; }
      else if (v.verified) { status = 'watching'; text = 'Watching'; }
      else if (v.phase === 'camera_disconnected' || v.phase === 'waiting_camera') { status = 'lost'; text = 'Reconnecting'; }
      else { status = 'check'; text = 'Board check needed'; }
    } else if (!state?.game || showSetup) {
      status = cameraReady() ? 'watching' : 'manual';
      text = cameraReady() ? 'Camera ready' : 'Manual';
    }
    if (chipEl.dataset.status !== status || chipEl.textContent !== text) {
      chipEl.dataset.status = status;
      chipEl.textContent = text;
      chipEl.title = 'Camera: ' + text;
    }
  }

  function entryMode() {
    $('#entry-mode').textContent = state?.camera_game ? 'CAMERA SCORING · TAP TO CORRECT' : 'MANUAL SCORE ENTRY';
  }

  // Compact match status for phones, where the full scoreboard is hidden (live demo finding).
  function compactStatus(g) {
    const box = $('#compact-status');
    document.body.classList.toggle('in-game', !!g && !showSetup);
    if (!g) { box.replaceChildren(); return; }
    // One fixed-height line for all players (QA M1-16 L4: the board must start on the first phone screen).
    const playersRow = document.createElement('div');
    playersRow.className = 'compact-players';
    g.names.forEach((name, i) => {
      const who = document.createElement('span');
      who.className = 'compact-player' + (i === g.player ? ' current' : '');
      who.textContent = (i === g.player ? '▶ ' : '') + name + ' ' + (g.scores ? g.scores[i] : '');
      playersRow.append(who);
    });
    const darts = document.createElement('div');
    darts.className = 'compact-darts';
    darts.textContent = 'This turn: ' + ([0, 1, 2].map(i => g.darts[i] ? dartText(g.darts[i]) : '—').join(' · ')) +
      (g.bust ? ' · BUST' : '') + (g.winner !== null ? ' · ' + g.names[g.winner] + ' wins' : '');
    // The suggested finish (M3 UI-03), on its own fixed-height line.
    const checkout = document.createElement('div');
    checkout.className = 'compact-checkout';
    const route = state.checkout && state.checkout.player === g.player ? state.checkout.route : null;
    checkout.textContent = route ? 'Checkout: ' + route.join(' · ') : '';
    box.replaceChildren(playersRow, darts, checkout);
  }

  function paintCamera(full = true) {
    compactStatus(state?.game);
    entryMode();
    const g = state?.game, p = pending(), camera = !!state?.camera_game;
    // Committed darts of this turn: tap one, then tap the board to correct it.
    const chips = $('#turn-darts'), signature = JSON.stringify([g?.darts, correcting]);
    if (full && signature !== chips.dataset.signature) {
      chips.dataset.signature = signature;
      chips.replaceChildren(...(g ? g.darts.map(chip) : []));
    }
    if (correcting !== null && (!g || correcting >= g.darts.length)) correcting = null;
    $('#tap-hint').textContent = correcting !== null ? 'Tap the board (or Miss) to correct dart ' + (correcting + 1) + '. Tap its chip to cancel.'
      : p ? 'Camera dart pending: tap the board for another value.' : 'Tap where the dart landed.';
    $('#camera-panel').hidden = !camera;
    if (camera) {
      const auto = state.camera.auto_commit;
      const [headline, detail] = pendingText(p);
      $('#pending').textContent = headline;
      $('#pending-detail').textContent = detail;
      $('#pending').classList.toggle('active', !!p);
      $('#camera-panel').classList.toggle('check', !!(p && p.check && p.check.length));
      $('#accept').style.visibility = !p || p.turn_over ? 'hidden' : 'visible';  // keeps its space: no layout shift
      $('#accept').disabled = busy || !p || p.turn_over;
      $('#auto-status').textContent = !auto.enabled ? 'Auto-accept is off (--auto-commit 0).'
        : auto.paused ? 'Auto-accept paused: camera darts wait for Accept.' : 'Camera darts auto-accept after ' + auto.seconds + ' s.';
      $('#auto-pause').style.visibility = auto.enabled ? 'visible' : 'hidden';
      $('#auto-pause').textContent = auto.paused ? 'Resume auto-accept' : 'Pause auto-accept';
      $('#auto-pause').disabled = busy;
    }
    $('#end-turn').hidden = !camera || !g || g.winner !== null || g.bust || g.darts.length >= 3 || !!p;
    $('#end-turn').disabled = busy;
    // Pending dart marker on the tap board (board mm -> tap board picture units).
    const markers = $('#tap-board .markers');
    if (markers) {
      // Every pending dart is marked; the later ones dashed (they wait for the first).
      markers.innerHTML = pendingDarts().filter(d => d.x != null).map((d, i) => {
        const at = DartBoard.tapPoint(d.x, d.y);
        const kind = (i ? ' queued' : '') + (d.check && d.check.length ? ' check' : '');
        return `<circle class="pending-marker${kind}" cx="${at[0]}" cy="${at[1]}" r="9"/>`;
      }).join('');
    }
    cameraChip();
  }

  setInterval(() => { if (pending()) paintCamera(false); }, 200);

  $('#undo').onclick = async () => {
    buzz();
    if (await mutate('/api/undo', {}, false)) toast('Undone · ' + (state.game ? state.game.names[state.game.player] + ' to throw' : 'no match'));
  };
  $('#next').onclick = () => { buzz(); mutate('/api/next', {}, false); };
  $('#cancel').onclick = () => {
    pausedRevision = state.revision;
    cancel();
    $('#handoff').textContent = 'Handoff paused. Review the turn, then choose Next player.';
  };
  $('#auto').onchange = () => { pausedRevision = null; schedule(); };
  $('#new-game').onclick = () => openSetup(state?.game?.names);

  setPlayers([]);

  async function poll() {
    checking = true;
    try {
      const fresh = await DartRoom.request('/api/state');
      lastHealthy = Date.now();
      DartRoom.connection('CONNECTED · HOST', 'live');
      // First load with no match: continue the draft another controller (or this one, before a reload) started.
      if (!state && !fresh.game && fresh.lobby?.players?.length && !players().length) setPlayers(fresh.lobby.players);
      if (!busy && (!state || fresh.revision > state.revision)) {
        // Camera games change the match on their own (auto-accept): no review notice for those.
        if (state && !fresh.camera_game) {
          cancel();
          pausedRevision = fresh.revision;
          notice('Match updated. Review the current turn before continuing.');
        }
        state = fresh;
        paint();
        if (fresh.camera_game) schedule();
      } else if (!busy && fresh.revision === state.revision) {
        state = fresh;
        polledAt = performance.now();
        paint();
      }
    } catch (e) {
      cancel();
      pausedRevision = state?.revision;
      DartRoom.connection(e.status === 401 ? 'PAIRING LINK REQUIRED' : 'CONNECTION LOST', 'lost');
      notice(e.status === 401 ? 'Open the full private controller link printed by the host.' : 'Connection lost. Automatic handoff is paused.');
    } finally {
      checking = false;
      setTimeout(poll, state?.camera_game ? 400 : 1000);
    }
  }
  poll();
})();
