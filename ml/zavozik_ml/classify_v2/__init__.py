"""Versioned, extensible multi-output operation encoder.

Runtime modules import neither torch nor transformers. Install the optional
encoder runtime only when serving a v2 artifact; v1 remains independent.
"""
