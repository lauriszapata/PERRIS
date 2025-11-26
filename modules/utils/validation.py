import numpy as np
import pandas as pd

def ensure_no_nan(value, name: str):
    """Validate that *value* is not None and contains no NaN.
    Supports scalars, list/array-like, pandas Series/DataFrame.
    Raises ValueError if validation fails.
    """
    if value is None:
        raise ValueError(f"{name} is None")
    
    # Handle pandas structures
    if isinstance(value, (pd.Series, pd.DataFrame)):
        if value.isnull().any().any():
            raise ValueError(f"{name} contains NaN values")
        return True
    
    # Handle list/tuple/array-like (e.g., OHLCV data)
    if isinstance(value, (list, tuple, np.ndarray)):
        try:
            # Try to convert to float array for NaN checking
            # This handles OHLCV data which has mixed int/float numeric types
            arr = np.asarray(value, dtype=float)
            if np.isnan(arr).any():
                raise ValueError(f"{name} contains NaN values")
        except (ValueError, TypeError):
            # If conversion fails, data might be non-numeric (strings, dicts, etc.)
            # For complex structures like order books or order responses, just check if not empty
            if len(value) == 0:
                raise ValueError(f"{name} is empty")
        return True
    
    # Handle scalar numeric
    try:
        if np.isnan(value):
            raise ValueError(f"{name} is NaN")
    except (TypeError, ValueError):
        # Non-numeric scalar, that's okay (e.g., dict, string)
        pass
    
    return True
