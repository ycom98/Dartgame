/* Shared dartboard drawing (M1-11). DartBoard.markup() is the /play segment map, moved here unchanged
   from presentation.js. DartBoard.tapBoard() builds the controller's tap-to-score board: the same picture
   plus an invisible hit layer whose narrow rings (bull, treble, double) are widened so every target is at
   least 24 px on a 360 px wide phone. */
window.DartBoard = (() => {
  const SECTORS = [20, 1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5];
  const point = (angle, r) => [220 + Math.sin(angle * Math.PI / 180) * r, 220 - Math.cos(angle * Math.PI / 180) * r];
  // Visual ring bands in viewBox units: inner single, treble, outer single, double.
  const VISUAL_BANDS = [[19, 113, 'Si'], [113, 122, 'T'], [122, 184, 'So'], [184, 194, 'D']];
  // Hit layer bands (wider than the picture for the bull, treble and double rings).
  const HIT_BULL = 16, HIT_OUTER_BULL = 40;
  const HIT_BANDS = [[HIT_OUTER_BULL, 99, 'Si', 1], [99, 132, 'T', 3], [132, 182, 'So', 1], [182, 220, 'D', 2]];

  function wedge(i, inner, outer) {
    const a = point(i * 18 - 9, inner), b = point(i * 18 - 9, outer), c = point(i * 18 + 9, outer), d = point(i * 18 + 9, inner);
    return `M${a} L${b} A${outer} ${outer} 0 0 1 ${c} L${d} A${inner} ${inner} 0 0 0 ${a}`;
  }

  // The /play board. With options.regions the segments carry data-region keys (tap board highlight).
  function markup(darts, options = {}) {
    const tag = key => options.regions ? ` data-region="${key}"` : '';
    let s = '<svg viewBox="0 0 440 440" role="img" aria-label="Entered dart map: approximate segment positions, not physical tracking"><circle cx="220" cy="220" r="217" fill="#0c1413" stroke="#d8b66b" stroke-width="2"/>';
    for (let i = 0; i < 20; i++) {
      for (const [inner, outer, band] of VISUAL_BANDS) {
        const ring = inner === 113 || inner === 184;
        s += `<path${tag(band + SECTORS[i])} d="${wedge(i, inner, outer)}" fill="${ring ? (i % 2 ? '#548274' : '#a34440') : (i % 2 ? '#c6bfa9' : '#25322e')}" stroke="#8f9c8960" stroke-width=".8"/>`;
      }
      const p = point(i * 18, 207);
      s += `<text x="${p[0]}" y="${p[1] + 4}" fill="#eee9d9" text-anchor="middle" font-size="20" font-family="Arial">${SECTORS[i]}</text>`;
    }
    s += `<circle${tag('25')} cx="220" cy="220" r="18" fill="#548274"/><circle${tag('50')} cx="220" cy="220" r="7" fill="#a34440"/>`;
    darts.forEach((d, i) => {
      const p = d.value === 0 ? [415, 170 + i * 30] : d.value === 25 ? [220 + (i - 1) * 7, 220] :
        point(SECTORS.indexOf(d.value) * 18 + (i - 1) * 2, d.multiplier === 3 ? 117 : d.multiplier === 2 ? 189 : 153);
      s += `<g class="hit"><circle cx="${p[0]}" cy="${p[1]}" r="10" fill="#e7c77d" stroke="#142722" stroke-width="2"/><text x="${p[0]}" y="${p[1] + 3.5}" text-anchor="middle" fill="#142722" font-size="10" font-weight="bold">${i + 1}</text></g>`;
    });
    return s + '</svg>';
  }

  const label = (value, multiplier) => value === 25 ? (multiplier === 2 ? 'Bull (50)' : 'Outer bull (25)') :
    ({1: 'Single ', 2: 'Double ', 3: 'Triple '})[multiplier] + value;

  // All 82 hit regions: {key, value, multiplier, d, target: [x, y] (a point well inside, in viewBox units)}.
  function regions() {
    const list = [];
    SECTORS.forEach((value, i) => {
      for (const [inner, outer, band, multiplier] of HIT_BANDS) {
        list.push({key: band + value, value, multiplier, d: wedge(i, inner, outer), target: point(i * 18, (inner + outer) / 2)});
      }
    });
    const ring = r => `M${220 - r} 220 A${r} ${r} 0 1 1 ${220 + r} 220 A${r} ${r} 0 1 1 ${220 - r} 220 Z`;
    list.push({key: '25', value: 25, multiplier: 1, d: ring(HIT_OUTER_BULL) + ' ' + ring(HIT_BULL), evenodd: true,
      target: point(0, (HIT_BULL + HIT_OUTER_BULL) / 2)});
    list.push({key: '50', value: 25, multiplier: 2, d: ring(HIT_BULL), target: [220, 220]});
    return list;
  }

  // Interactive board in container. onTap(value, multiplier, key) is called for each tap.
  function tapBoard(container, onTap) {
    const hits = regions().map(r =>
      `<path class="hit-region" data-key="${r.key}" data-value="${r.value}" data-multiplier="${r.multiplier}"` +
      ` data-target="${r.target.map(v => v.toFixed(2)).join(',')}" d="${r.d}"${r.evenodd ? ' fill-rule="evenodd"' : ''}` +
      ` role="button" aria-label="${label(r.value, r.multiplier)}"/>`).join('');
    container.innerHTML = markup([], {regions: true})
      .replace('role="img" aria-label="Entered dart map: approximate segment positions, not physical tracking"',
        'role="group" aria-label="Tap where the dart landed"')
      .replace('</svg>', `<g class="hit-layer">${hits}</g><g class="markers"></g></svg>`);
    container.querySelector('.hit-layer').addEventListener('click', event => {
      const hit = event.target.closest('.hit-region');
      if (!hit) return;
      onTap(Number(hit.dataset.value), Number(hit.dataset.multiplier), hit.dataset.key, event);
    });
  }

  // Brief highlight of the tapped segment (both single bands for a single).
  function flash(container, key) {
    const visual = container.querySelector(`[data-region="${key}"]`);
    if (!visual) return;
    visual.classList.add('tap-flash');
    setTimeout(() => visual.classList.remove('tap-flash'), 450);
  }

  return {SECTORS, point, markup, regions, tapBoard, flash, label};
})();
