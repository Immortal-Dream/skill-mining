import numpy as np
from typing import Literal

def mse(A, B):
    return np.mean((A[:, None, :] - B[None, :, :]) ** 2, axis=2)

def mae(A, B):
    return np.mean(np.abs(A[:, None, :] - B[None, :, :]), axis=2)


custom_metrics = {
    "mse": mse,
    "mae": mae,
}

CDIST_METRICS = {
    "braycurtis", "canberra", "chebyshev", "cityblock", "cosine",
    "euclidean", "mahalanobis", "minkowski", "seuclidean", "sqeuclidean"
}

DistanceMetricLiteral = Literal[
    "mse", "mae",
    "braycurtis", "canberra", "chebyshev", "cityblock", "cosine",
    "euclidean", "mahalanobis", "minkowski", "seuclidean", "sqeuclidean"
]
