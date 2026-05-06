"""Source-adapter subpackage for the research bounded context.

Created by R4 (`openbb-sidecar-container`) — first slice that ships a
concrete `SourcePort` implementation. Future slices land additional
adapters (R2 EDGAR/FRED, R3 news/catalysts, etc.) as new modules in this
package; the dynamic-discovery pattern from slice 5 is NOT used here
because adapters are wired explicitly by the synthesis layer (R5) per
design decision D2 — adapters are not "routes", they're services.
"""
