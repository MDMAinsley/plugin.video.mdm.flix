"""Compatibility import for the shared MDM Link alldebrid implementation."""
import sys
from mdmlink import alldebrid as shared
sys.modules[__name__] = shared
