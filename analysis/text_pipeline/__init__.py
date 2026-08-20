"""Internal modules for the Text postprocessing pipeline.

The stable user-facing entry point remains ``python -m analysis.text_pipeline.postprocess``.
Import concrete submodules directly so the compatibility entry point can load
without a package-level circular import.
"""
