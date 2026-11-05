import sys, tempfile
exec(open('/tmp/claude-0/-home-user/39130e07-3815-5ada-9f6d-04313fc052e0/scratchpad/probe_vision.py').read().split("print('truth labels'")[0])
import persistence
def restart(v, ds):
    d = tempfile.mkdtemp(); persistence.save_calibration(v, d)
    w = V.Vision(); w.ingest(frame(ds)); persistence.load_calibration(w, d); w.ingest(frame(ds)); w.align(); show(w, ds, 3); return w
def commit_all(v): [v.commit_dart(p['id']) for p in list(v.pending)]
for noisy in (False, True):
    globals()['NOISY'] = noisy; print('=== noisy', noisy)
    v = calibrated(); show(v, darts[:1]); commit_all(v)
    v = restart(v, darts[:1]); show(v, darts[:2]); print('A dart2 after restart 1', P(v)); commit_all(v)
    v = restart(v, darts[:2]); show(v, darts[:3]); print('A dart3 after restart 2', P(v)); commit_all(v); v.end_turn()
    show(v, darts[:2]); a = P(v); show(v, darts[:1]); b = P(v); show(v, []); print('A pulls 3,2,1 ->', a, b, P(v), 'cleared', v.counters['board_cleared'])
    show(v, darts[1:2]); print('A next turn', P(v))
    v = calibrated(); show(v, darts[:2]); commit_all(v)
    v.board_is_empty(); print('B board clear with 2 darts in ->', P(v))
    show(v, darts[:3]); print('B dart3', P(v)); commit_all(v); v.end_turn()
    show(v, darts[:2]); a = P(v); show(v, darts[:1]); b = P(v); show(v, []); print('B pulls 3,2,1 ->', a, b, P(v), 'cleared', v.counters['board_cleared'], v.message)
    commit_all(v); show(v, darts[:1]); print('B next turn dart1 (same spot as a poisoned dart) ->', P(v), v.message)
    v = V.Vision(); v.ingest(frame(darts[:2])); r = v.calibrate(points); show(v, darts[:2], 3)
    print('C calibration board_empty', r['calibration'].get('board_empty'), r['calibration'].get('board_marks_mm2'), 'warns', 'does not look empty' in r['message'])
    v.board_is_empty(); show(v, darts[1:2]); a = P(v); show(v, []); print('C board clear with darts in, pull ->', a, P(v), v.message)
    commit_all(v); show(v, darts[2:3]); print('C next dart', P(v))
    v = V.Vision(); v.ingest(frame(darts[:2])); v.calibrate(points); show(v, darts[:2], 3); v.reset_base()
    show(v, darts[1:2]); show(v, []); print('D pulled before Board clear ->', P(v)); v.pending = []
    v.board_is_empty(); show(v, darts[:1]); print('D after Board clear, dart at calib spot ->', P(v)); commit_all(v)
    show(v, []); print('D pull ->', P(v), 'cleared', v.counters['board_cleared'])
