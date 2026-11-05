import sys
exec(open('/tmp/claude-0/-home-user/39130e07-3815-5ada-9f6d-04313fc052e0/scratchpad/probe_vision.py').read().split("print('truth labels'")[0])
# R: restart emulation, empty calibration; darts untracked in base
for noisy in (False, True):
    globals()['NOISY'] = noisy
    v = calibrated(); show(v, darts[:2]); v.tracked = []; v.pending = []; v.reset_base()
    show(v, darts[:3]); print('R', noisy, 'dart3', P(v)); [v.commit_dart(p['id']) for p in list(v.pending)]; v.end_turn()
    show(v, darts[1:3]); a = P(v); show(v, darts[2:3]); b = P(v); show(v, []); print('R pulls ->', a, b, P(v), v.counters['board_cleared'], v.message)
    show(v, darts[:1]); print('R next turn', P(v))
# C: calibrate with darts in the board
for noisy in (False, True):
    globals()['NOISY'] = noisy
    v = V.Vision(); v.ingest(frame(darts[:2])); v.calibrate(points); show(v, darts[:2], 3); v.reset_base()
    show(v, darts[:3]); print('C', noisy, 'dart3', P(v)); [v.commit_dart(p['id']) for p in list(v.pending)]; v.end_turn()
    show(v, darts[1:3]); a = P(v); show(v, darts[2:3]); b = P(v); show(v, []); print('C pulls ->', a, b, P(v), 'cleared', v.counters['board_cleared'], v.message)
    for p in list(v.pending): v.commit_dart(p['id'])
    show(v, darts[:1]); print('C next dart at calib-dart spot ->', P(v), v.message)
    show(v, []); show(v, []); v.reset_base()  # host presses baseline on empty board
    show(v, darts[:1]); print('C after baseline dart1', P(v))
    v.commit_dart(v.pending[0]['id']) if v.pending else None
    show(v, []); print('C after baseline, pull ->', P(v), 'cleared', v.counters['board_cleared'])
    show(v, darts[1:2]); print('C next', P(v))
