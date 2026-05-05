"""Pydantic DTOs for the FastAPI surface.

Slice 4 (``auth-jwt-cookie``) seeds this package with auth DTOs. Subsequent
slices (T4 trading, K1 risk, R5 research, etc.) add their own modules
under :mod:`iguanatrader.api.dtos`. Slice 5
(``api-foundation-rfc7807``) layers OpenAPI typegen on top of these.
"""

from __future__ import annotations
