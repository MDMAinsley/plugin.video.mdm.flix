"""Compatibility import for the shared MDM Link files implementation."""
import sys
from mdmlink import files as shared
sys.modules[__name__] = shared
