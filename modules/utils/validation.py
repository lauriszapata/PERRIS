import numpy as np
import pandas as pd

def ensure_no_nan(value, name: str):
    """Validate that *value* is not None and contains no NaN.
    Supports scalars, list/array-like, pandas Series/DataFrame.
    Raises ValueError if validation fails.
    """
    if value is None:
        raise ValueError(f"{name} is None")
    # Convert to numpy array for uniform check where possible
    if isinstance(value, (list, tuple, np.ndarray)):
        arr = np.array(value, dtype=object)
        if np.isnan(arr).any():
            raise ValueError(f"{name} contains NaN values")
    elif isinstance(value, (pd.Series, pd.DataFrame)):
        if value.isnull().any().any():
            raise ValueError(f"{name} contains NaN values")
    else:
        # Assume scalar numeric
        try:
            if np.isnan(value):
                raise ValueError(f"{name} is NaN")
        except TypeError:
            # Non‑numeric scalar, ignore
            pass
    return True
