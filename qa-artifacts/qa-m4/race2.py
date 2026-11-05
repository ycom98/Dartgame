exec(open(__file__.replace('race2.py', 'ui_head.py')).read())
D = [Dart(x=30.0, y=-100.0, tilt=12.0), Dart(x=-75.0, y=40.0, tilt=12.0), Dart(x=60.0, y=75.0, tilt=12.0)]
leaks = 0; trials = 0
try:
    start_server(['--fresh'])
    calibrate_and_verify()
    req('/api/game', {'names': ['Ana', 'Ben'], 'start': 501, 'camera': True}); time.sleep(0.8)
    for t in range(32):
        pause(False)
        show([]); req('/api/baseline', {}); time.sleep(0.3)
        show(D[:1]); wait(lambda: len(game_darts()) >= 1, 5)
        req('/api/turn/fill_misses', {})          # host ends the turn: darts 2-3 misses
        show(D[:2]); wait(lambda: len(pend()) >= 1, 4)  # camera sees a dart anyway (turn over: no commit)
        time.sleep(2.0)                           # older than the auto-commit delay
        p = pend()
        st, r = req('/api/next', {})
        time.sleep(1.0)
        g = game_darts(); trials += 1
        if g: leaks += 1
        print(t, 'pending at next', [d['label'] for d in p], 'next', st, '-> new player darts', g, 'pending', labels(), flush=True)
        if g: req('/api/undo', {})
        req('/api/turn/fill_misses', {}); req('/api/next', {})
finally:
    stop_server(); fake.stop()
print('LEAKS', leaks, 'of', trials)
