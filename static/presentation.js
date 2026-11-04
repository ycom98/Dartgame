/* Shared presentation: the TV (/play), the controller's preview and the showcase all draw with
   DartRoom.render(). Live spectators only read state.

   The animated sequence per visit: entrance stage ("YOU'RE UP"), per-dart reveal, gauge drain, then the
   recap stage (or the 180 / bust / victory stage). M3 adds the lobby (renderLobby), checkout suggestions,
   the bust badge and the game-shot screen with match statistics.

   Moments a sound layer can follow (UI-04): DartRoom.onMoment(fn) calls fn(name, detail) with
     'dart'        a new dart on the board            {label, score}
     'turn'        a new player is at the oche         {name}
     'bust'        the visit went bust                 {name}
     'maximum'     a 180                               {name}
     'game-shot'   the winning dart                    {name, checkout}
   Each fires once per change, on the TV only (never for the controller preview or a restart). */
window.DartRoom = (() => {
  const esc = s => String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const initials = s => s.trim().split(/\s+/).map(part => part[0]).slice(0, 2).join('').toUpperCase();
  const label = d => d.value === 0 ? 'MISS' : d.value === 25 ? (d.multiplier === 2 ? 'BULL' : '25') : (['', 'S', 'D', 'T'][d.multiplier] + d.value);
  const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  const isHost = () => document.body.classList.contains('host');
  const avatar = (name, seat, extra = '') => `<span class="avatar ${extra}" data-seat="${seat}">${esc(initials(name))}</span>`;

  /* ---- Moments (sound hooks) ---- */
  const momentListeners = [];
  function onMoment(fn) { momentListeners.push(fn); }
  function moment(name, detail = {}) {
    if (isHost()) return;
    for (const fn of momentListeners) {
      try { fn(name, detail); } catch (error) { console.error(error); }
    }
    document.dispatchEvent(new CustomEvent('dartroom:moment', {detail: {name, ...detail}}));
  }

  /* ---- Motion timers that the showcase can pause ---- */
  let motionPaused = false;
  const motionTimers = new Set();
  function after(fn, ms) {
    const item = {fn, remaining: ms, since: performance.now(), id: null};
    item.fire = () => { motionTimers.delete(item); fn(); };
    if (!motionPaused) item.id = setTimeout(item.fire, ms);
    motionTimers.add(item);
    return item;
  }
  function setPaused(value) {
    if (motionPaused === value) return;
    motionPaused = value;
    document.body.classList.toggle('motion-paused', value);
    for (const item of motionTimers) {
      if (value) {
        clearTimeout(item.id);
        item.remaining = Math.max(0, item.remaining - (performance.now() - item.since));
      } else {
        item.since = performance.now();
        item.id = setTimeout(item.fire, item.remaining);
      }
    }
  }

  let previous = null, signature = '', frame = 0, epoch = 0, visualScore = null, visualTotal = 0;
  const stage = document.createElement('div');
  stage.className = 'match-stage';
  stage.setAttribute('aria-hidden', 'true');
  document.body.append(stage);

  function clearMotion() {
    cancelAnimationFrame(frame);
    for (const item of motionTimers) clearTimeout(item.id);
    motionTimers.clear();
    stage.classList.remove('visible');
    stage.replaceChildren();
    epoch++;
  }

  const STAGE_KICKERS = {
    entrance: 'YOUR TURN', maximum: 'THE PERFECT VISIT', victory: 'GAME SHOT', 'bust-recap': 'BUST · SCORE RESTORED',
  };
  function showStage(kind, name, big, detail, duration = 1900) {
    if (reduced() || isHost()) return;
    stage.dataset.event = kind;
    stage.className = 'match-stage ' + kind;
    stage.innerHTML = `<div class="stage-rule"></div><div class="stage-content">
      <div class="stage-kicker">${esc(STAGE_KICKERS[kind] || 'TURN COMPLETE')}</div>
      <div class="stage-name">${esc(name)}</div>
      <div class="stage-big">${esc(big)}</div>
      <div class="stage-detail">${esc(detail)}</div></div><div class="stage-rule lower"></div>`;
    const stageEpoch = epoch;
    requestAnimationFrame(() => { if (stageEpoch === epoch) stage.classList.add('visible'); });
    after(() => stage.classList.remove('visible'), duration);
  }

  // Score and gauge count down (or back up after a bust) from what is on screen to the new value.
  function tween(from, to, totalFrom, totalTo, duration) {
    const scoreEl = document.querySelector('.hero .score'), totalEl = document.querySelector('.turn-points');
    const water = document.querySelector('.reservoir-water'), percent = document.querySelector('.reservoir-percent');
    let elapsed = 0, last = performance.now();
    const run = epoch;
    function draw(now) {
      if (run !== epoch) return;
      if (!motionPaused) elapsed += now - last;
      last = now;
      const progress = reduced() ? 1 : Math.min(1, elapsed / duration), ease = 1 - Math.pow(1 - progress, 4);
      visualScore = Math.round(from + (to - from) * ease);
      visualTotal = Math.round(totalFrom + (totalTo - totalFrom) * ease);
      scoreEl.textContent = visualScore;
      totalEl.textContent = visualTotal;
      const pct = Math.max(0, Math.min(100, visualScore / Number(scoreEl.dataset.start) * 100));
      water.style.height = pct + '%';
      percent.textContent = Math.round(pct) + '%';
      if (progress < 1) frame = requestAnimationFrame(draw);
      else { visualScore = to; visualTotal = totalTo; }
    }
    frame = requestAnimationFrame(draw);
  }

  /* ---- Lobby ---- */
  const GAMES = [
    {id: '301', title: '301', blurb: 'A quick round', ready: true},
    {id: '501', title: '501', blurb: 'The classic', ready: true},
    {id: 'cricket', title: 'Cricket', blurb: 'Coming soon'},
    {id: 'killer', title: 'Killer', blurb: 'Coming soon'},
    {id: 'shanghai', title: 'Shanghai', blurb: 'Coming soon'},
    {id: 'clock', title: 'Around the Clock', blurb: 'Coming soon'},
  ];

  function lobbyMarkup(lobby) {
    const players = lobby?.players || [];
    const chosen = String(lobby?.start || 301);
    const tiles = GAMES.map(game => `<div class="game-tile ${game.ready ? '' : 'soon'} ${game.id === chosen ? 'chosen' : ''}"
        data-game="${game.id}"><strong>${esc(game.title)}</strong><span>${esc(game.blurb)}</span></div>`).join('');
    const seats = [0, 1, 2, 3].map(i => players[i]
      ? `<div class="lobby-player joined">${avatar(players[i], i)}<span>${esc(players[i])}</span></div>`
      : `<div class="lobby-player empty"><span class="avatar empty">+</span><span>${i < 2 ? 'Player ' + (i + 1) : 'Optional'}</span></div>`).join('');
    const finish = lobby?.double_out ? 'DOUBLE OUT' : 'STRAIGHT OUT';
    return `<section class="lobby lobby-live" data-players="${players.length}">
      <div class="lobby-head">
        <div class="eyebrow">WELCOME TO</div>
        <h1 class="lobby-title">Dart <span>Room</span></h1>
      </div>
      <div class="lobby-section">
        <div class="lobby-label">CHOOSE YOUR GAME <em>${chosen} · ${finish}</em></div>
        <div class="game-tiles">${tiles}</div>
      </div>
      <div class="lobby-section">
        <div class="lobby-label">PLAYERS <em>${players.length ? players.length + ' JOINED' : '2–4 PLAYERS'}</em></div>
        <div class="lobby-players">${seats}</div>
      </div>
      <p class="lobby-hint">${players.length >= 2 ? 'Ready when you are. Press Start on the host controller.' : 'Add players and start the match on the host controller.'}</p>
    </section>`;
  }

  function renderLobby(lobby) {
    const root = document.querySelector('#match'), key = 'lobby:' + JSON.stringify(lobby || null);
    if (key === signature) return;
    signature = key;
    clearMotion();
    previous = null;
    visualScore = null;
    visualTotal = 0;
    root.innerHTML = lobbyMarkup(lobby);
  }

  /* ---- Checkout, bust and game shot ---- */
  function checkoutMarkup(checkout, who) {
    if (!checkout || checkout.player !== who) return '<div class="checkout-line" aria-hidden="true"></div>';
    const darts = checkout.route.map(dart => `<span class="checkout-dart ${dart === 'BULL' || dart.startsWith('D') ? 'double' : ''}">${esc(dart)}</span>`).join('');
    return `<div class="checkout-line has-route" aria-label="Checkout ${esc(checkout.route.join(' '))}">
      <span class="checkout-label">CHECKOUT</span>${darts}</div>`;
  }

  const STAT_ROWS = [
    ['3-dart avg', p => p.average.toFixed(1)],
    ['Highest turn', p => p.highest],
    ['Darts thrown', p => p.darts],
    ['100+', p => p.tons],
    ['140+', p => p.ton_forties],
    ['180s', p => p.maximums],
    ['Checkout', p => p.checkout ?? '—'],
  ];

  function statsMarkup(g, stats) {
    const players = stats.players;
    const head = g.names.map((name, i) => `<th class="${i === g.winner ? 'winner-col' : ''}">${avatar(name, i)}<span>${esc(name)}</span></th>`).join('');
    const rows = STAT_ROWS.map(([title, value]) => `<tr><th scope="row">${title}</th>${players.map((p, i) =>
      `<td class="${i === g.winner ? 'winner-col' : ''}">${esc(value(p))}</td>`).join('')}</tr>`).join('');
    const winner = players[g.winner];
    return `<section class="match-stats" aria-label="Match statistics">
      <div class="game-shot">
        <div class="eyebrow">GAME SHOT</div>
        <div class="game-shot-name">${esc(g.names[g.winner])}</div>
        <div class="game-shot-detail">${winner.checkout !== null ? `${winner.checkout} checkout in ${winner.checkout_darts} dart${winner.checkout_darts === 1 ? '' : 's'}` : 'Winner'}
          · ${winner.average.toFixed(1)} average</div>
      </div>
      <table class="stats-table"><thead><tr><th></th>${head}</tr></thead><tbody>${rows}</tbody></table>
    </section>`;
  }

  /* ---- The match ---- */
  // options: restart (showcase), checkout and stats (from /api/state, M3 UI-03).
  function render(g, options = {}) {
    const root = document.querySelector('#match');
    const key = JSON.stringify([g, options.checkout || null, options.stats || null]);
    if (key === signature && !options.restart) return;
    signature = key;
    const old = options.restart ? null : previous;
    clearMotion();
    if (!g) {
      root.innerHTML = lobbyMarkup(null);
      previous = null;
      visualScore = null;
      visualTotal = 0;
      return;
    }
    const won = g.winner !== null, done = g.bust || g.darts.length === 3, who = won ? g.winner : g.player;
    const next = (g.player + 1) % g.names.length, round = Math.floor((g.turn - 1) / g.names.length) + 1, score = g.scores[who];
    const sameMatch = old && old.start === g.start && JSON.stringify(old.names) === JSON.stringify(g.names) && old.double_out === g.double_out;
    const sameTurn = sameMatch && old.turn === g.turn && old.player === g.player;
    const prefix = sameTurn && old.darts.every((d, i) => JSON.stringify(d) === JSON.stringify(g.darts[i]));
    const added = prefix ? g.darts.length - old.darts.length : 0, forward = added > 0;
    const correction = !!old && sameTurn && (!prefix || g.darts.length < old.darts.length || old.winner !== null && !won);
    const freshTurn = !sameTurn && g.darts.length === 0 && !won;
    const banked = g.bust ? 0 : Math.max(0, g.turn_start - score), attempted = g.darts.reduce((s, d) => s + d.score, 0);
    const max = done && !g.bust && banked === 180;
    const from = sameTurn && visualScore !== null ? visualScore : score, totalFrom = sameTurn ? visualTotal : banked;
    const cue = won ? `${g.names[who]} takes the match. Well played!`
      : g.bust ? `Bust. Score restored · ${g.names[next]} up next`
        : done ? `Turn complete · ${g.names[next]} up next` : `${g.names[who]}, throw dart ${g.darts.length + 1} of 3`;
    const feedback = correction ? 'SCORE CORRECTED'
      : forward ? (g.bust ? 'BUST · SCORE RESTORED' : added === 1 ? `${label(g.darts.at(-1))} · +${g.darts.at(-1).score} POINTS` : `${added} DARTS RECORDED`)
        : won ? 'GAME SHOT' : 'MAKE YOUR MARK';
    const stats = won && options.stats && options.stats.players ? options.stats : null;
    const heroKicker = won ? 'THE WINNER' : g.bust ? 'BUST · BACK TO YOUR TURN START' : done ? 'TURN IN THE BOOKS' : 'AT THE OCHE';
    const darts = [0, 1, 2].map(i => `<div class="dart ${g.darts[i] ? 'filled' : ''} ${forward && i >= g.darts.length - added ? 'dart-reveal' : ''}"
        style="--dart-delay:${Math.max(0, i - (g.darts.length - added)) * 90}ms"><small>DART ${i + 1}</small>
        <strong>${g.darts[i] ? label(g.darts[i]) : '—'}</strong>
        <span class="dart-points">${g.darts[i] ? g.darts[i].score + ' PTS' : 'READY'}</span></div>`).join('');
    const boardSide = stats ? statsMarkup(g, stats)
      : `<div class="board-wrap ${forward ? 'board-impact' : ''}">${DartBoard.markup(g.darts).replaceAll('class="hit"', 'class="board-marker"')}
          <div class="board-caption">ENTERED DARTS · SEGMENT MAP</div></div>`;
    const players = g.names.map((name, i) => `<div class="player ${i === who ? 'active' : ''}" data-seat="${i}">
        <div class="player-identity">${avatar(name, i)}<div class="player-name">${esc(name)}
          <small>${won ? (i === who ? 'WINNER' : 'MATCH COMPLETE') : i === g.player ? 'AT THE OCHE' : i === next ? 'UP NEXT' : 'IN THE MATCH'}</small></div></div>
        <div class="player-score">${g.scores[i]}</div></div>`).join('');

    root.innerHTML = `<div class="match-top"><div class="eyebrow">${won ? 'MATCH COMPLETE' : `ROUND ${round} · TURN ${g.turn}`}</div>
        <div class="rule">${g.start} / ${g.double_out ? 'DOUBLE OUT' : 'STRAIGHT OUT'}</div></div>
      <div class="arena ${won ? 'winner' : g.bust ? 'bust' : ''} ${stats ? 'with-stats' : ''}">
        <section class="hero">
          <div class="eyebrow">${heroKicker}</div>
          <h1>${avatar(g.names[who], who)}${esc(g.names[who])}</h1>
          <div class="score-instrument">
            <div class="score-readout">
              <div class="score" data-start="${g.start}" aria-label="${score} points remaining">${from}</div>
              <div class="remaining">${won ? 'THE WINNING FINISH' : 'POINTS REMAINING'}</div>
            </div>
            <div class="reservoir" role="meter" aria-valuemin="0" aria-valuemax="${g.start}" aria-valuenow="${score}" aria-label="Points remaining">
              <div class="reservoir-cap">${g.start}</div>
              <div class="reservoir-track"><div class="reservoir-water" style="height:${from / g.start * 100}%"></div><div class="reservoir-ticks"></div></div>
              <div class="reservoir-percent">${Math.round(from / g.start * 100)}%</div>
              <div class="reservoir-label">LEFT</div>
            </div>
            ${g.bust ? `<div class="bust-badge ${forward ? 'bust-new' : ''}" role="status">BUST<small>${attempted} attempted · back to ${score}</small></div>` : ''}
          </div>
          <div class="visit-line">
            <div class="visit-total"><span class="turn-points">${totalFrom}</span><span>${g.bust ? 'POINTS BANKED' : 'TURN POINTS'}</span></div>
            <div class="hit-feedback ${forward ? 'new-hit' : ''} ${max ? 'maximum-hit' : ''}">${esc(max ? 'ONE HUNDRED & EIGHTY' : feedback)}</div>
          </div>
          <div class="darts">${darts}</div>
          ${checkoutMarkup(options.checkout, who)}
          <div class="cue" aria-live="polite">${esc(cue)}</div>
        </section>
        ${boardSide}
      </div>
      <div class="players" style="--players:${g.names.length}">${players}</div>`;

    tween(from, score, totalFrom, banked, correction ? 450 : 950);

    // The stage that follows this change, and the moment a sound layer hears.
    const run = epoch;
    const firstWin = won && (!old || old.winner === null);
    if (forward && !options.restart) moment('dart', {label: label(g.darts.at(-1)), score: g.darts.at(-1).score});
    if (firstWin) {
      if (old) moment('game-shot', {name: g.names[who], checkout: banked});
      after(() => {
        if (run === epoch) showStage('victory', g.names[who], 'GAME SHOT', `${banked} checkout · ${g.start} complete`, 3000);
      }, reduced() ? 0 : 1000);
    } else if (forward && done) {
      if (g.bust) moment('bust', {name: g.names[who]});
      else if (max) moment('maximum', {name: g.names[who]});
      after(() => {
        if (run !== epoch) return;
        showStage(g.bust ? 'bust-recap' : max ? 'maximum' : 'recap', g.names[who], g.bust ? 'BUST' : String(banked),
          g.bust ? `${attempted} attempted · ${score} restored` : `${score} remaining · ${g.names[next]} up next`, max ? 2300 : 1800);
      }, 1050);
    } else if (freshTurn && !isHost()) {
      if (old) moment('turn', {name: g.names[who]});
      showStage('entrance', g.names[who], 'YOU’RE UP', `Round ${round} · ${score} points to finish`, 1700);
    }
    previous = structuredClone(g);
  }

  /* ---- Chrome: brand link, full screen, Wake Lock ---- */
  const token = new URLSearchParams(location.search).get('t') || '';
  document.querySelectorAll('a.brand').forEach(a => { a.href = '#'; });

  const fullscreen = document.querySelector('#fullscreen');
  if (fullscreen) {
    fullscreen.onclick = async () => {
      try {
        if (document.fullscreenElement) {
          await document.exitFullscreen();
        } else {
          if (!document.documentElement.requestFullscreen) throw new Error('Fullscreen unavailable');
          await document.documentElement.requestFullscreen();
        }
      } catch {
        fullscreen.textContent = 'Use browser full screen';
        fullscreen.setAttribute('aria-label', 'Use your browser full screen command');
      }
    };
    document.addEventListener('fullscreenchange', () => {
      fullscreen.textContent = document.fullscreenElement ? 'Exit full screen' : 'Full screen';
    });
  }

  // Keeps the screen on while `wanted()` is true (TV always, controller during a match). Best effort.
  function keepAwake(wanted) {
    let lock = null, asking = false;
    async function update() {
      const want = wanted() && document.visibilityState === 'visible';
      if (want && !lock && !asking && navigator.wakeLock?.request) {
        asking = true;
        try {
          lock = await navigator.wakeLock.request('screen');
          lock.addEventListener('release', () => { lock = null; });
        } catch { lock = null; } finally { asking = false; }
      } else if (!want && lock) {
        const held = lock;
        lock = null;
        held.release().catch(() => {});
      }
    }
    document.addEventListener('visibilitychange', update);
    return update;
  }

  async function request(path, body) {
    const abort = new AbortController(), timeout = setTimeout(() => abort.abort(), body === undefined ? 1500 : 8000);
    const options = {headers: {Authorization: 'Bearer ' + token}, signal: abort.signal};
    if (body !== undefined) {
      options.method = 'POST';
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
    try {
      const response = await fetch(path, options);
      const data = await response.json();
      if (!response.ok) {
        const error = new Error(data.error || 'Request failed');
        error.state = data;
        error.status = response.status;
        throw error;
      }
      return data;
    } finally {
      clearTimeout(timeout);
    }
  }

  function connection(text, kind = '') {
    const e = document.querySelector('#connection');
    if (!e) return;
    e.textContent = text;
    e.dataset.kind = kind;
  }

  // The TV: poll the state; show the lobby while no match runs or the host is setting up the next one.
  function live() {
    let shown = '', healthy = false;
    const banner = document.querySelector('#reconnect');
    const awake = keepAwake(() => true);
    async function poll() {
      try {
        const s = await request('/api/state');
        healthy = true;
        const lobby = !s.game || (s.lobby && s.lobby.open);
        // In the lobby the next game's scoring isn't decided yet, so the header just says LIVE (QA UI release L8).
        connection(lobby ? 'LIVE' : s.camera_game ? 'LIVE · CAMERA SCORING' : 'LIVE · MANUAL SCORING', 'live');
        if (banner) banner.hidden = true;
        const footer = document.querySelector('#scoring-mode');
        if (footer) footer.textContent = s.camera_game ? 'Camera scoring · Darts shown on board' : 'Manual scoring · Entered darts shown on board';
        document.body.classList.toggle('in-lobby', lobby);
        const key = JSON.stringify(lobby ? ['lobby', s.lobby] : [s.game, s.checkout, s.stats]);
        if (shown !== key) {
          if (lobby) renderLobby(s.lobby);
          else render(s.game, {checkout: s.checkout, stats: s.stats});
          shown = key;
        }
        awake();
      } catch (e) {
        const unpaired = e.status === 401;
        connection(unpaired ? 'PAIRING LINK REQUIRED' : 'CONNECTION LOST · RETRYING', 'lost');
        if (banner) {
          banner.hidden = false;
          banner.querySelector('strong').textContent = unpaired ? 'Pairing link required' : 'Reconnecting…';
          banner.querySelector('span').textContent = unpaired
            ? 'Open this display with the private TV link from the host.'
            : 'The score will come back by itself as soon as the Mac answers.';
        }
        if (!shown) {
          document.querySelector('#match').innerHTML = '<section class="lobby"><div class="eyebrow">LET’S GET CONNECTED</div><h1>Your match,<br>up here.</h1><p>' +
            esc(unpaired ? 'Open this display with the private pairing token from your host link.' : 'The host is unavailable. This display will reconnect automatically.') + '</p></section>';
        }
        healthy = false;
      } finally {
        setTimeout(poll, healthy ? 1000 : 1500);
      }
    }
    poll();
  }

  return {render, renderLobby, request, connection, label, token, live, setPaused, onMoment, keepAwake, initials};
})();
