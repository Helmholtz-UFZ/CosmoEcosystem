"""CSV statistical profiler — standalone computation module.

Takes a CSV file and produces a statistical profile with structured results
suitable for Plotly visualizations. Dependencies: pandas, numpy.
"""

import logging

import numpy as np
import pandas as pd

from cosmo_ecosystem.error_handling import FileValidationError

log = logging.getLogger(__name__)


def validate_csv(file_path: str) -> None:
    """Validate that a file can be parsed as a CSV DataFrame.

    Raises FileValidationError with a descriptive message on failure.
    """
    try:
        df = pd.read_csv(file_path)
    except UnicodeDecodeError:
        raise FileValidationError(
            "File is not a valid text file (binary or unsupported encoding)."
        )
    except pd.errors.EmptyDataError:
        raise FileValidationError("File is empty or contains no data.")
    except pd.errors.ParserError as e:
        raise FileValidationError(f"Cannot parse as CSV: {e}")

    if df.empty:
        raise FileValidationError("CSV file has headers but no data rows.")


def profile_csv(
    file_path: str,
    columns: list[str] | None = None,
    handle_missing: str = "drop",
    histogram_bins: int = 30,
    compute_correlation: bool = True,
    top_n_categories: int = 10,
    trigger_error: bool = False,
) -> dict:
    """Read CSV, compute statistical profile, return structured results.

    Args:
        file_path: Path to the CSV file.
        columns: Which columns to analyze (default: all).
        handle_missing: How to handle missing values.
            "drop" — drop rows with NaN before numeric stats.
            "fill_mean" — fill NaN with column mean (numeric only).
            "fill_zero" — fill NaN with 0 (numeric only).
            "keep" — leave NaN in place.
        histogram_bins: Number of bins for histograms.
        compute_correlation: Whether to compute the correlation matrix.
        top_n_categories: How many top values for categorical columns.

    Returns:
        Structured dict with summary, correlation_matrix, missing_values,
        histograms, value_counts, row_count, and column_count.
    """
    log.info(f"Reading CSV from {file_path}")
    df = pd.read_csv(file_path)

    if columns:
        missing_cols = [c for c in columns if c not in df.columns]
        if missing_cols:
            log.warning(f"Columns not found in CSV, skipping: {missing_cols}")
        columns = [c for c in columns if c in df.columns]
        df = df[columns]

    log.info(f"Profiling {len(df)} rows × {len(df.columns)} columns")

    # Classify columns
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    categorical_cols = [c for c in df.columns if c not in numeric_cols]

    # Handle missing values for numeric columns
    df_numeric = df[numeric_cols].copy() if numeric_cols else pd.DataFrame()
    if handle_missing == "drop" and not df_numeric.empty:
        df_numeric = df_numeric.dropna()
    elif handle_missing == "fill_mean" and not df_numeric.empty:
        df_numeric = df_numeric.fillna(df_numeric.mean())
    elif handle_missing == "fill_zero" and not df_numeric.empty:
        df_numeric = df_numeric.fillna(0)

    # Build per-column summary
    summary = {}
    for col in df.columns:
        if col in numeric_cols:
            s = df_numeric[col] if col in df_numeric.columns else df[col]
            summary[col] = {
                "dtype": "numeric",
                "count": int(s.count()),
                "mean": _safe_float(s.mean()),
                "median": _safe_float(s.median()),
                "std": _safe_float(s.std()),
                "min": _safe_float(s.min()),
                "max": _safe_float(s.max()),
                "25%": _safe_float(s.quantile(0.25)),
                "75%": _safe_float(s.quantile(0.75)),
            }
        else:
            vc = df[col].value_counts()
            summary[col] = {
                "dtype": "categorical",
                "count": int(df[col].count()),
                "unique": int(df[col].nunique()),
                "most_common": str(vc.index[0]) if len(vc) > 0 else None,
                "most_common_count": int(vc.iloc[0]) if len(vc) > 0 else 0,
            }

    # Missing values
    missing_values = {}
    for col in df.columns:
        n_missing = int(df[col].isna().sum())
        # Always include all columns for completeness
        missing_values[col] = {
            "count": n_missing,
            "percent": round(100 * n_missing / len(df), 2) if len(df) > 0 else 0,
        }

    # Correlation matrix (numeric only)
    correlation_matrix = {}
    if compute_correlation and len(numeric_cols) >= 2:
        corr = df_numeric[numeric_cols].corr()
        correlation_matrix = {
            "columns": numeric_cols,
            "values": [
                [_safe_float(corr.iloc[i, j]) for j in range(len(numeric_cols))]
                for i in range(len(numeric_cols))
            ],
        }

    # Histograms (numeric only)
    histograms = {}
    for col in numeric_cols:
        s = df_numeric[col] if col in df_numeric.columns else df[col]
        s = s.dropna()
        if len(s) > 0:
            counts, bin_edges = np.histogram(s, bins=histogram_bins)
            histograms[col] = {
                "values": counts.tolist(),
                "bin_edges": bin_edges.tolist(),
            }

    # Value counts (categorical only)
    value_counts = {}
    for col in categorical_cols:
        vc = df[col].value_counts().head(top_n_categories)
        value_counts[col] = {str(k): int(v) for k, v in vc.items()}

    if trigger_error:
        log.info("Trigger error flag is set — dividing by zero")
        _ = 1 / 0

    return {
        "summary": summary,
        "correlation_matrix": correlation_matrix,
        "missing_values": missing_values,
        "histograms": histograms,
        "value_counts": value_counts,
        "row_count": len(df),
        "column_count": len(df.columns),
    }


def _safe_float(val):
    """Convert to float, handling NaN/inf."""
    if val is None or (isinstance(val, float) and (np.isnan(val) or np.isinf(val))):
        return None
    return float(val)
