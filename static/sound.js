'use strict';
/*
 * Dart Room sounds for the TV (UI-04). Synthesised with WebAudio: no audio files, fully offline.
 *
 * Browsers only allow sound after someone interacts with the page, so sound starts OFF. Call
 * DartSound.enable() from a click (for example a "Sound on" button). The choice is remembered in
 * localStorage: if sound was on last time, the first click or key press anywhere on the page turns it
 * back on by itself.
 *
 * API (a global `DartSound`; nothing else is added to the page):
 *   DartSound.enable()        Turn sound on. Call from a user gesture. Returns a Promise<boolean> (true if audio runs).
 *   DartSound.mute()          Turn sound off (remembered).
 *   DartSound.toggle()        enable() or mute(); returns a Promise<boolean> of the new state.
 *   DartSound.isEnabled()     true while sound is on.
 *   DartSound.play(name)      Play one sound; returns true if it was played, false if muted or unknown.
 *   DartSound.attachToggle(button)
 *                             Make a button the Sound on / Sound off switch (text and aria-pressed kept in sync).
 *   DartSound.onchange        Optional callback(enabled) when the state changes.
 *   DartSound.names           The sound names below.
 *   DartSound.renderOffline(name)
 *                             For tests: renders a sound silently, resolves to {duration, peak, rms}.
 *
 * Sound names (when to play them):
 *   'dart'      every dart that scores (a short board thud)
 *   'turn'      the next player is up (two-note chime)
 *   'bust'      the turn is bust (falling "wah")
 *   'ton'       a turn of 100 or more, but not 180 (quick rising arpeggio)
 *   '180'       a maximum, 180 (brass fanfare)
 *   'gameshot'  the winning dart, game shot (celebration)
 */
(function (global) {
  const STORAGE_KEY = 'dartroom.sound';  // 'on' or 'off'
  const VOLUME = 0.5;

  let context = null;   // AudioContext, made on the first enable()
  let output = null;    // master gain -> compressor -> speakers
  let enabled = false;

  // ---- building blocks; every voice takes (ctx, destination, start time) ----

  // A note with a quick attack and an exponential decay.
  function tone(ctx, destination, start, {frequency, endFrequency, type = 'sine', duration = 0.3, gain = 0.3,
    attack = 0.008, filter = null}) {
    const oscillator = ctx.createOscillator();
    const envelope = ctx.createGain();
    oscillator.type = type;
    oscillator.frequency.setValueAtTime(frequency, start);
    if (endFrequency) oscillator.frequency.exponentialRampToValueAtTime(endFrequency, start + duration);
    envelope.gain.setValueAtTime(0.0001, start);
    envelope.gain.exponentialRampToValueAtTime(gain, start + attack);
    envelope.gain.exponentialRampToValueAtTime(0.0001, start + duration);
    let node = oscillator;
    if (filter) {
      const lowpass = ctx.createBiquadFilter();
      lowpass.type = 'lowpass';
      lowpass.frequency.setValueAtTime(filter, start);
      node.connect(lowpass);
      node = lowpass;
    }
    node.connect(envelope);
    envelope.connect(destination);
    oscillator.start(start);
    oscillator.stop(start + duration + 0.05);
  }

  // A short burst of filtered noise (the impact of a dart).
  function noise(ctx, destination, start, {duration = 0.08, gain = 0.4, frequency = 1800}) {
    const length = Math.ceil(ctx.sampleRate * duration);
    const buffer = ctx.createBuffer(1, length, ctx.sampleRate);
    const samples = buffer.getChannelData(0);
    for (let i = 0; i < length; i++) samples[i] = (Math.random() * 2 - 1) * (1 - i / length) ** 3;
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    const bandpass = ctx.createBiquadFilter();
    bandpass.type = 'bandpass';
    bandpass.frequency.value = frequency;
    bandpass.Q.value = 0.9;
    const envelope = ctx.createGain();
    envelope.gain.value = gain;
    source.connect(bandpass);
    bandpass.connect(envelope);
    envelope.connect(destination);
    source.start(start);
  }

  // A brass-like note: two slightly detuned sawtooths through a lowpass that opens and closes.
  function brass(ctx, destination, start, frequency, duration, gain = 0.16) {
    const lowpass = ctx.createBiquadFilter();
    lowpass.type = 'lowpass';
    lowpass.Q.value = 2;
    lowpass.frequency.setValueAtTime(400, start);
    lowpass.frequency.linearRampToValueAtTime(2600, start + 0.06);
    lowpass.frequency.exponentialRampToValueAtTime(900, start + duration);
    const envelope = ctx.createGain();
    envelope.gain.setValueAtTime(0.0001, start);
    envelope.gain.exponentialRampToValueAtTime(gain, start + 0.04);
    envelope.gain.setValueAtTime(gain, start + duration * 0.7);
    envelope.gain.exponentialRampToValueAtTime(0.0001, start + duration);
    lowpass.connect(envelope);
    envelope.connect(destination);
    for (const detune of [-7, 7]) {
      const oscillator = ctx.createOscillator();
      oscillator.type = 'sawtooth';
      oscillator.frequency.value = frequency;
      oscillator.detune.value = detune;
      oscillator.connect(lowpass);
      oscillator.start(start);
      oscillator.stop(start + duration + 0.05);
    }
  }

  const note = semitonesFromA4 => 440 * 2 ** (semitonesFromA4 / 12);
  const C5 = note(3), E5 = note(7), G5 = note(10), A5 = note(12), C6 = note(15), E6 = note(19), G4 = note(-2);

  // ---- the sounds; each returns its length in seconds ----
  const SOUNDS = {
    dart(ctx, out, t) {
      noise(ctx, out, t, {duration: 0.07, gain: 1.0, frequency: 2200});
      tone(ctx, out, t, {frequency: 150, endFrequency: 55, type: 'sine', duration: 0.16, gain: 0.9, attack: 0.003});
      return 0.2;
    },
    turn(ctx, out, t) {
      tone(ctx, out, t, {frequency: E5, type: 'sine', duration: 0.5, gain: 0.22});
      tone(ctx, out, t, {frequency: E5 * 2, type: 'sine', duration: 0.25, gain: 0.04});
      tone(ctx, out, t + 0.14, {frequency: A5, type: 'sine', duration: 0.7, gain: 0.24});
      tone(ctx, out, t + 0.14, {frequency: A5 * 2, type: 'sine', duration: 0.3, gain: 0.05});
      return 0.9;
    },
    bust(ctx, out, t) {
      tone(ctx, out, t, {frequency: 330, endFrequency: 110, type: 'sawtooth', duration: 0.55, gain: 0.4, filter: 1200});
      tone(ctx, out, t + 0.02, {frequency: 311, endFrequency: 104, type: 'square', duration: 0.55, gain: 0.16, filter: 800});
      return 0.65;
    },
    ton(ctx, out, t) {
      [C5, E5, G5, C6].forEach((frequency, i) =>
        tone(ctx, out, t + i * 0.07, {frequency, type: 'triangle', duration: 0.35 + i * 0.05, gain: 0.22}));
      return 0.7;
    },
    '180'(ctx, out, t) {
      // da-da-da DAAA, then a held major chord
      [[G4, 0, 0.14], [G4, 0.16, 0.14], [G4, 0.32, 0.14], [C5, 0.5, 0.5]].forEach(([frequency, at, length]) =>
        brass(ctx, out, t + at, frequency, length));
      for (const frequency of [C5, E5, G5, C6]) brass(ctx, out, t + 1.0, frequency, 1.1, 0.09);
      noise(ctx, out, t + 1.0, {duration: 0.5, gain: 0.12, frequency: 6000});  // cymbal
      return 2.2;
    },
    gameshot(ctx, out, t) {
      [C5, E5, G5, C6, E6].forEach((frequency, i) =>
        tone(ctx, out, t + i * 0.09, {frequency, type: 'triangle', duration: 0.4, gain: 0.2}));
      for (const frequency of [C5, E5, G5, C6]) brass(ctx, out, t + 0.5, frequency, 1.4, 0.08);
      for (let i = 0; i < 6; i++) {  // sparkle
        tone(ctx, out, t + 0.6 + i * 0.12, {frequency: C6 * (i % 2 ? 2 : 1.5), type: 'sine', duration: 0.25, gain: 0.05});
      }
      noise(ctx, out, t + 0.5, {duration: 0.7, gain: 0.1, frequency: 7000});
      return 2.0;
    },
  };

  // ---- state ----
  function remembered() {
    try { return localStorage.getItem(STORAGE_KEY); } catch (e) { return null; }
  }

  function remember(value) {
    try { localStorage.setItem(STORAGE_KEY, value); } catch (e) { /* not remembered: storage unavailable */ }
  }

  function makeOutput(ctx) {
    const gain = ctx.createGain();
    gain.gain.value = VOLUME;
    const limiter = ctx.createDynamicsCompressor();  // keeps overlapping sounds from clipping
    limiter.threshold.value = -6;
    limiter.ratio.value = 12;
    gain.connect(limiter);
    limiter.connect(ctx.destination);
    return gain;
  }

  const toggles = new Set();

  function changed() {
    for (const button of toggles) {
      button.textContent = enabled ? 'Sound off' : 'Sound on';
      button.setAttribute('aria-pressed', String(enabled));
      button.title = enabled ? 'Mute the game sounds' : 'Play game sounds on this screen';
    }
    if (typeof DartSound.onchange === 'function') DartSound.onchange(enabled);
  }

  async function enable() {
    const AudioContextClass = global.AudioContext || global.webkitAudioContext;
    if (!AudioContextClass) return false;
    if (!context) {
      context = new AudioContextClass();
      output = makeOutput(context);
    }
    try { await context.resume(); } catch (e) { /* still suspended: needs a user gesture */ }
    enabled = context.state === 'running';
    if (enabled) remember('on');
    changed();
    return enabled;
  }

  function mute() {
    enabled = false;
    remember('off');
    if (context && context.state === 'running') context.suspend().catch(() => {});
    changed();
  }

  function play(name) {
    const sound = Object.prototype.hasOwnProperty.call(SOUNDS, name) ? SOUNDS[name] : null;
    if (!sound) {
      console.warn('DartSound: unknown sound ' + JSON.stringify(name) + '; use one of ' + DartSound.names.join(', '));
      return false;
    }
    if (!enabled || !context || context.state !== 'running') return false;
    sound(context, output, context.currentTime + 0.01);
    return true;
  }

  async function renderOffline(name) {
    const sound = SOUNDS[name];
    if (!sound) throw Error('Unknown sound ' + name);
    const sampleRate = 44100, OfflineClass = global.OfflineAudioContext || global.webkitOfflineAudioContext;
    const probe = new OfflineClass(1, sampleRate * 3, sampleRate);
    const duration = sound(probe, makeOutput(probe), 0);
    const samples = (await probe.startRendering()).getChannelData(0);
    let peak = 0, sum = 0;
    for (const sample of samples) {
      peak = Math.max(peak, Math.abs(sample));
      sum += sample * sample;
    }
    return {duration, peak, rms: Math.sqrt(sum / samples.length)};
  }

  function attachToggle(button) {
    toggles.add(button);
    button.addEventListener('click', () => { DartSound.toggle(); });
    changed();
  }

  const DartSound = {
    names: ['dart', 'turn', 'bust', 'ton', '180', 'gameshot'],  // Object.keys would sort '180' first
    enable,
    mute,
    toggle: () => (enabled ? (mute(), Promise.resolve(false)) : enable()),
    isEnabled: () => enabled,
    play,
    attachToggle,
    renderOffline,
    onchange: null,
  };
  global.DartSound = DartSound;

  // Sound was on last time: the first interaction turns it back on (browsers need that gesture).
  if (remembered() === 'on' && global.document) {
    const resume = event => {
      if (event.target && event.target.closest && event.target.closest('[aria-pressed]') &&
          toggles.has(event.target.closest('[aria-pressed]'))) return;  // the toggle handles its own click
      global.removeEventListener('pointerdown', resume, true);
      global.removeEventListener('keydown', resume, true);
      if (!enabled) enable();
    };
    global.addEventListener('pointerdown', resume, true);
    global.addEventListener('keydown', resume, true);
  }
})(window);
