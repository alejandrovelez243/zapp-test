"""Runtime evaluation package for the Zapp Global Philosophy School backend.

Public surface:
    ``app.eval.runtime.is_goodbye``         — deterministic ES/EN/PT goodbye detector
    ``app.eval.runtime.evaluate_conversation`` — end-of-conversation judge + persist
    ``app.eval.runtime.idle_sweep_once``    — grade idle, un-graded sessions
"""
