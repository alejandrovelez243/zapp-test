"""Runtime evaluation package for the Zapp Global Philosophy School backend.

Public surface:
    ``app.eval.runtime.evaluate_conversation`` — end-of-conversation judge + persist
    ``app.eval.runtime.idle_sweep_once``    — grade idle, un-graded sessions

NOTE: ``is_goodbye`` (keyword heuristic) has been removed (evaluation-015).
End-of-conversation intent is now detected by the orchestrator's ``end_session`` tool.
"""
