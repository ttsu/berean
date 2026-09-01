"""Catena — retrieval and citation service. The model layer.

Everything this package emits is untrusted: the Go gateway verifies every
citation against the database before any of it renders. Emitting a
plausible-looking citation is worse than emitting none.
"""

__version__ = "0.1.0"
