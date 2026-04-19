def summarize_numeric_columns(rows: list[dict[str, float]]) -> dict[str, dict[str, float]]:
    """Compute min, max, and mean for numeric columns in row dictionaries."""
    columns: dict[str, list[float]] = {}
    for row in rows:
        for key, value in row.items():
            if isinstance(value, (int, float)):
                columns.setdefault(key, []).append(float(value))
    return {
        key: {
            "min": min(values),
            "max": max(values),
            "mean": sum(values) / len(values),
        }
        for key, values in columns.items()
        if values
    }
