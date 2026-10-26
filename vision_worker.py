"""Background vision worker (M1-06): the one thread that runs Vision processing.

Every Vision action (calibrate, align, verify, reset, ingest) runs on this thread with
vision.lock held, and vision.publish() is called afterwards. HTTP handlers queue actions with
call() and wait on a future, so a slow align() never blocks /api/state or game writes: those
read vision.current_state(), which needs no lock.

With a frame source attached (camera_source.py, M1-07), the same thread pulls the newest
frame at up to max_fps and ingests it. Stale frames are skipped, never queued.
"""
import queue
import threading
import time
from concurrent.futures import Future, TimeoutError as FutureTimeout


# How long an HTTP request waits for a queued vision action (plan: at most 10 s).
ACTION_TIMEOUT_SECONDS = 10.0
# Re-publish the vision state at least this often, so time-based changes (calibration
# snapshot expiry, a stale camera) show up without a new frame or action.
PUBLISH_INTERVAL_SECONDS = 0.5
# The plan's processing rate for pulled frames.
DEFAULT_MAX_FPS = 15.0


class WorkerBusy(Exception):
    """A queued vision action did not start and finish within the timeout."""


class VisionWorker:
    def __init__(self, get_vision, max_fps=DEFAULT_MAX_FPS):
        # get_vision is called for every action and frame, so the Vision object can be replaced (tests do).
        self.get_vision = get_vision
        self.jobs = queue.Queue()
        self.wake = threading.Event()
        self.thread = None
        self.thread_lock = threading.Lock()
        self.stopping = False
        self.last_publish_at = 0.0
        self.max_fps = max_fps       # 0 = no limit (lockstep replay in tests)
        self.source = None
        self.source_lock = threading.Lock()
        self.last_source_seq = None
        self.last_ingest_at = 0.0
        self.processed = []          # monotonic times of recently ingested source frames
        self.ingest_errors = 0
        self.last_ingest_error = None
        self.after_publish = None     # called with vision (lock held) after each publish
        self.on_ingest = None        # test hook: called after each source frame with (frame, seq)

    # ---- lifecycle ---------------------------------------------------------------------
    def start(self):
        with self.thread_lock:
            if self.thread is not None and self.thread.is_alive():
                return
            self.stopping = False
            self.thread = threading.Thread(target=self.run, name='vision-worker', daemon=True)
            self.thread.start()

    def stop(self, timeout=5.0):
        self.stopping = True
        self.wake.set()
        thread = self.thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        self.set_source(None)

    # ---- actions -----------------------------------------------------------------------
    def submit(self, action):
        """Queue action(vision) on the worker thread; returns a Future."""
        future = Future()
        self.start()
        self.jobs.put((action, future))
        self.wake.set()
        return future

    def call(self, action, timeout=ACTION_TIMEOUT_SECONDS):
        """Run action(vision) on the worker thread and return its result (or raise its error)."""
        if threading.current_thread() is self.thread:
            vision = self.get_vision()
            with vision.lock:
                try:
                    return action(vision)
                finally:
                    vision.publish()
        future = self.submit(action)
        try:
            return future.result(timeout)
        except FutureTimeout:
            if future.cancel():
                raise WorkerBusy('Camera processing is busy; nothing was changed. Try again.') from None
            raise WorkerBusy('Camera processing is taking longer than expected; check the setup page.') from None

    def run_job(self, action, future):
        if not future.set_running_or_notify_cancel():
            return
        vision = self.get_vision()
        if vision is None:
            future.set_exception(ValueError('Camera vision unavailable'))
            return
        with vision.lock:
            # Publish before resolving the future, so the waiting request replies with the new state.
            try:
                result, error = action(vision), None
            except BaseException as raised:  # handed to the waiting request
                result, error = None, raised
            try:
                self.publish(vision)
            except BaseException as raised:
                error = error or raised
        if error is not None:
            future.set_exception(error)
        else:
            future.set_result(result)

    def publish(self, vision):
        try:
            vision.publish()
            if self.after_publish is not None:
                self.after_publish(vision)
        finally:
            self.last_publish_at = time.monotonic()

    # ---- frame source (M1-07) ----------------------------------------------------------
    def set_source(self, source):
        """Attach a frame source (or None) and start it. The previous source is stopped."""
        with self.source_lock:  # concurrent switches must not leak a source (QA D8)
            self.replace_source(source)

    def replace_source(self, source):
        previous, self.source = self.source, source
        self.last_source_seq = None
        self.processed = []
        self.last_ingest_error = None
        if previous is not None and previous is not source:
            previous.on_frame = None
            previous.stop()
        if source is not None:
            source.on_frame = self.wake.set
            source.start()
            self.start()
        self.wake.set()

    def source_status(self):
        """Source status for /api/state, read without any lock. None when no source is attached."""
        source = self.source
        if source is None:
            return None
        status = source.status()
        from camera_source import rate  # only reached with a source attached, so OpenCV is present
        status['processed_fps'] = rate(self.processed, time.monotonic())
        if self.last_ingest_error:
            status['ingest_error'] = self.last_ingest_error
        return status

    def process_source_frame(self):
        """Ingest the source's newest frame if it is new and the rate limit allows.

        Returns how many seconds to wait before a frame is allowed again, or None.
        Frames that arrive while vision is busy are replaced by newer ones, never queued.
        """
        source = self.source
        if source is None:
            return None
        if self.max_fps:
            wait = self.last_ingest_at + 1.0 / self.max_fps - time.monotonic()
            if wait > 0:
                return wait
        frame, _, seq = source.latest()
        if frame is None or seq == self.last_source_seq:
            return None
        vision = self.get_vision()
        if vision is None:
            return None
        self.last_source_seq = seq
        self.last_ingest_at = time.monotonic()
        with vision.lock:
            try:
                vision.ingest(frame)
                self.last_ingest_error = None
            except ValueError as error:
                self.ingest_errors += 1
                self.last_ingest_error = str(error)
            self.publish(vision)
        now = time.monotonic()
        self.processed = [t for t in self.processed if now - t <= 2.0] + [now]
        if self.on_ingest is not None:
            self.on_ingest(frame, seq)
        return None

    # ---- thread loop -------------------------------------------------------------------
    def run(self):
        timeout = PUBLISH_INTERVAL_SECONDS
        while not self.stopping:
            self.wake.wait(timeout)
            self.wake.clear()
            # One queued action per pass, then a frame: a burst of requests cannot starve the camera (QA D4).
            try:
                action, future = self.jobs.get_nowait()
            except queue.Empty:
                pass
            else:
                self.run_job(action, future)
                if not self.jobs.empty():
                    self.wake.set()
            if self.stopping:
                break
            try:
                wait = self.process_source_frame()
            except Exception as error:  # one bad frame must not stop the worker
                self.last_ingest_error = f'Frame processing failed ({type(error).__name__})'
                wait = None
            # Rate limited: come back when the next frame is allowed.
            timeout = min(wait, PUBLISH_INTERVAL_SECONDS) if wait else PUBLISH_INTERVAL_SECONDS
            if time.monotonic() - self.last_publish_at >= PUBLISH_INTERVAL_SECONDS:
                vision = self.get_vision()
                if vision is not None:
                    with vision.lock:
                        self.publish(vision)
        # Fail anything still queued so no request waits for the full timeout.
        while True:
            try:
                _, future = self.jobs.get_nowait()
            except queue.Empty:
                break
            if future.set_running_or_notify_cancel():
                future.set_exception(WorkerBusy('Camera processing stopped'))
