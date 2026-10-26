"""Background vision worker (M1-06): the one thread that runs Vision processing.

Every Vision action (calibrate, align, verify, reset, ingest) runs on this thread with
vision.lock held, and vision.publish() is called afterwards. HTTP handlers queue actions with
call() and wait on a future, so a slow align() never blocks /api/state or game writes: those
read vision.current_state(), which needs no lock.
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


class WorkerBusy(Exception):
    """A queued vision action did not start and finish within the timeout."""


class VisionWorker:
    def __init__(self, get_vision):
        # get_vision is called for every action and frame, so the Vision object can be replaced (tests do).
        self.get_vision = get_vision
        self.jobs = queue.Queue()
        self.wake = threading.Event()
        self.thread = None
        self.thread_lock = threading.Lock()
        self.stopping = False
        self.last_publish_at = 0.0

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
        finally:
            self.last_publish_at = time.monotonic()

    # ---- thread loop -------------------------------------------------------------------
    def run(self):
        while not self.stopping:
            self.wake.wait(PUBLISH_INTERVAL_SECONDS)
            self.wake.clear()
            while not self.stopping:
                try:
                    action, future = self.jobs.get_nowait()
                except queue.Empty:
                    break
                self.run_job(action, future)
            if self.stopping:
                break
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
