"""Idle detection (DESIGN.md section 6). Pure: time and samples are inputs, nothing is read from the system.

A device is idle at a sample when (1) its utilization averaged over the last idle_window_s is below idle_utilization_pct
and (2) no fresh status document with state running lists it. An interval opens after the condition held for idle_min_s,
is recorded from the first sample of the condition, and closes after the condition failed for idle_resume_s.

Observation rules (independent review W1, W2): time that was not observed is never counted as idle. A gap between two samples longer
than max_gap_s cuts the candidate run, and closes an open interval at the last observed sample with reason observation_gap.
A sample without a utilization value is unknown: it is neither idle nor busy, it never reuses older low samples, it cuts the candidate
run, and after idle_resume_s of unknown samples an open interval closes with reason unobservable.
"""
import datetime


def condition(avg_util, threshold_pct, has_running_workload):
    """True when the device meets the idle condition at this sample. avg_util None (unavailable) is never idle."""
    if avg_util is None:
        return False
    return avg_util < threshold_pct and not has_running_workload


def average(samples):
    vals = [u for _, u in samples if u is not None]
    return sum(vals) / len(vals) if vals else None


class IdleTracker:
    def __init__(self, window_s=600, threshold_pct=5, min_s=600, resume_s=60, max_gap_s=None):
        self.window_s, self.threshold_pct, self.min_s, self.resume_s = window_s, threshold_pct, min_s, resume_s
        self.max_gap_s = max_gap_s      # None: no gap check (tests of the pure rule); the collector always passes a value
        self.samples = []            # (time, utilization)
        self.last_t = None
        self.cond_since = None       # first sample time of the current run of the condition
        self.fail_since = None       # first sample time of the current run of failure while open
        self.open = False
        self.idle_since = None

    def update(self, t, utilization, has_running_workload):
        """Feeds one sample. Returns a list of events (dicts with type, at, since, duration_s)."""
        if self.last_t is not None and t <= self.last_t:
            return []                # clock stepped back or repeated sample: ignored, no negative durations, no double events
        events = []
        if self.last_t is not None and self.max_gap_s is not None and (t - self.last_t).total_seconds() > self.max_gap_s:
            if self.open:
                events.append({'type': 'idle_ended', 'at': t, 'since': self.idle_since, 'duration_s': (self.last_t - self.idle_since).total_seconds(),
                               'reason': 'observation_gap', 'unobserved_s': (t - self.last_t).total_seconds()})
            self.samples = []
            self.cond_since = self.fail_since = self.idle_since = None
            self.open = False
        self.last_t = t
        self.samples.append((t, utilization))
        cutoff = t - datetime.timedelta(seconds=self.window_s)
        self.samples = [s for s in self.samples if s[0] > cutoff]
        unknown = utilization is None
        avg = None if unknown else average(self.samples)
        if condition(avg, self.threshold_pct, has_running_workload):
            self.fail_since = None
            if self.cond_since is None:
                self.cond_since = t
            if not self.open and (t - self.cond_since).total_seconds() >= self.min_s:
                self.open = True
                self.idle_since = self.cond_since    # from the first sample of the condition, not from confirmation
                events.append({'type': 'idle_started', 'at': t, 'since': self.idle_since})
        else:
            if not self.open:
                self.cond_since = None
            else:
                if self.fail_since is None:
                    self.fail_since = t
                if (t - self.fail_since).total_seconds() >= self.resume_s:
                    events.append({'type': 'idle_ended', 'at': t, 'since': self.idle_since,
                                   'duration_s': (self.fail_since - self.idle_since).total_seconds(),
                                   'reason': 'unobservable' if unknown else 'busy'})
                    self.open = False
                    self.idle_since = None
                    self.cond_since = None
                    self.fail_since = None
        return events

    def to_dict(self):
        f = lambda t: t.isoformat() if t else None
        return {'samples': [[t.isoformat(), u] for t, u in self.samples], 'last_t': f(self.last_t), 'cond_since': f(self.cond_since),
                'fail_since': f(self.fail_since), 'open': self.open, 'idle_since': f(self.idle_since)}

    @classmethod
    def from_dict(cls, d, **kw):
        o = cls(**kw)
        p = lambda s: datetime.datetime.fromisoformat(s) if s else None
        o.samples = [(datetime.datetime.fromisoformat(t), u) for t, u in d.get('samples', [])]
        o.last_t, o.cond_since, o.fail_since = p(d.get('last_t')), p(d.get('cond_since')), p(d.get('fail_since'))
        o.open, o.idle_since = bool(d.get('open')), p(d.get('idle_since'))
        return o
