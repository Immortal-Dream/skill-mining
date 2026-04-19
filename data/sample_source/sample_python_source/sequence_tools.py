def compute_gc_content(sequence: str) -> float:
    """Compute the GC content of a DNA sequence."""
    cleaned = sequence.upper()
    if not cleaned:
        return 0.0
    gc = cleaned.count("G") + cleaned.count("C")
    return gc / len(cleaned)


def reverse_complement(sequence: str) -> str:
    """Return the reverse complement of a DNA sequence."""
    table = str.maketrans("ACGTacgt", "TGCAtgca")
    return sequence.translate(table)[::-1]
