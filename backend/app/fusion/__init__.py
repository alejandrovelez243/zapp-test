"""Signal-fusion package.

Provides geo-IP resolution (``GeoContext`` / ``GeoFusionService``) and the
deterministic reconciliation logic that computes ``confidence_score`` / ``needs_review``
from the fused language + geo signals.

The public surface exposed here is the minimum other modules need so that internal
implementation files can be refactored without touching callers.

req: orchestrator-and-fusion-002..017
"""

from app.fusion.geo import GeoContext, GeoFusionService

__all__ = ["GeoContext", "GeoFusionService"]
