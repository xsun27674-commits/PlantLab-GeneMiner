"""Contract for a future local search provider, returning standard BLAST tabular data."""

from pathlib import Path
from typing import Protocol


class BlastSearchBackend(Protocol):
    def search(self, query_fasta: Path, database: Path, program: str) -> bytes:
        """Return standard outfmt 6 TSV suitable for read_blast."""
        ...
