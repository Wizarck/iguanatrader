"""Sidecar adapter layer — thin wrappers around the OpenBB SDK.

Per design D5: this is the ONLY package inside the sidecar that imports
``openbb`` (the rest of the sidecar — routes, config, main — stays
agnostic). All ``openbb`` imports are lazy (inside method bodies) so
module-level imports stay cheap.
"""
