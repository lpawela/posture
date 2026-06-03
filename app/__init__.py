"""Posture: webcam-based pose estimation and exercise form analysis.

The package is split into three dependency-light layers:

* :mod:`app.geometry` and :mod:`app.landmarks` -- pure-Python primitives with
  no third-party dependencies, so they (and the analyzers built on them) are
  trivially unit testable.
* :mod:`app.exercises` -- the squat/deadlift analyzers and a registry tying
  each exercise to its reference video.
* :mod:`app.server` -- the FastAPI app that serves the web client and runs the
  analyzers over a WebSocket stream of pose landmarks.
"""

__version__ = "0.1.0"
