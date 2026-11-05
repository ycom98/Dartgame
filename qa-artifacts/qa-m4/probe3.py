import sys
exec(open('/tmp/claude-0/-home-user/39130e07-3815-5ada-9f6d-04313fc052e0/scratchpad/probe_vision.py').read().split("print('truth labels'")[0])
for noisy in (False, True):
    globals()['NOISY'] = noisy
    v = calibrated(); show(v, darts[:2]); [v.commit_dart(p['id']) for p in list(v.pending)]
    v.tracked = []; v.pending = []; v.reset_base()          # restart mid-turn: darts 1-2 untracked, in turn_base
    show(v, darts[:3]); print('R2', noisy, 'dart3', P(v)); [v.commit_dart(p['id']) for p in list(v.pending)]; v.end_turn()
    show(v, darts[:2]); print('R2 pulled dart 3 first ->', P(v), 'cleared', v.counters['board_cleared'], v.message)
    show(v, darts[1:2]); a = P(v); show(v, []); print('R2 then pulled 1 and 2 ->', a, P(v), 'cleared', v.counters['board_cleared'], v.message)
    for p in list(v.pending): v.commit_dart(p['id'])
    show(v, [Dart(x=-20.0, y=120.0, tilt=12.0)]); print('R2 next turn dart ->', P(v))
