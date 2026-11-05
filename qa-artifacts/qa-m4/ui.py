exec(open(__file__.replace('ui.py', 'ui_head.py')).read())
import subprocess as sp
SHOTS = sys.argv[3]
os.makedirs(SHOTS, exist_ok=True)
def shoot(prefix):
    out = sp.run(['node', os.path.join(os.path.dirname(__file__), 'shot.cjs'), 'http://127.0.0.1:%d' % PORT, TOKEN,
                  globals()['DISPLAY'], os.path.join(SHOTS, prefix)], capture_output=True, text=True, cwd=ROOT,
                 env={**os.environ, 'NODE_PATH': '/opt/node-tools/node_modules'})
    print(prefix, out.stdout.strip()[:3000], out.stderr[-1500:])
D = [Dart(x=30.0, y=-100.0, tilt=12.0), Dart(x=-75.0, y=40.0, tilt=12.0), Dart(x=60.0, y=75.0, tilt=12.0)]
try:
    start_server(['--fresh'])
    calibrate_and_verify()
    req('/api/game', {'names': ['Ana', 'Ben'], 'start': 501, 'camera': True}); time.sleep(0.8)
    pause(True)
    for k in range(1, 4):
        show(D[:k]); wait(lambda: len(pend()) >= k, 4)
    print('pending', labels())
    shoot('m4-a-three-pending')
    # flagged head + queued
    for _ in range(3): req('/api/throw', {'proposal_id': pend()[0]['id']})
    show(D[1:]); show(D[2:]); show([]); req('/api/next', {})
    upper = Dart(10.0, -60.0, length=125.0, tilt=10.0, azimuth=0.0)
    below = Dart(10.0, -25.0, length=125.0, tilt=10.0, azimuth=0.0)
    show([upper]); wait(lambda: len(pend()) >= 1, 4); req('/api/throw', {'proposal_id': pend()[0]['id']})
    pause(False)
    show([upper, below]); wait(lambda: len(pend()) >= 1, 4)
    show([upper, below, D[1]]); time.sleep(1.0)
    print('pending', [(d['label'], d.get('check')) for d in pend()])
    shoot('m4-b-flagged-head')
    time.sleep(3)
    print('after 3 s still pending', labels(), 'game', game_darts())
finally:
    stop_server(); fake.stop()
