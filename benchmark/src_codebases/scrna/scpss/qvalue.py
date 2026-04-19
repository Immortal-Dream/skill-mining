import numpy as np
from scipy.interpolate import UnivariateSpline

def storey_qvalue(pvals, lambda_=np.arange(0, 0.96, 0.01), df=3):
    pvals = np.asarray(pvals)
    m = len(pvals)

    # Sort p-values
    order = np.argsort(pvals)
    p_sorted = pvals[order]

    # CASE 1: fixed lambda (float)
    if isinstance(lambda_, float):
        if lambda_ >= 1.0:
            raise ValueError("lambda_ must be < 1.0 for fixed-lambda estimation.")
        pi0 = np.mean(p_sorted > lambda_) / (1 - lambda_)
        pi0 = min(pi0, 1.0)

    # CASE 2: spline over multiple lambda values
    else:
        lambda_arr = np.asarray(lambda_)
        if np.any(lambda_arr >= 1.0):
            raise ValueError("All lambda values must be < 1.0 for spline estimation.")
        pi0_lambda = np.array([np.mean(p_sorted > lam) / (1 - lam) for lam in lambda_arr])
        pi0_lambda = np.minimum(pi0_lambda, 1.0)
        spline = UnivariateSpline(lambda_arr, pi0_lambda, k=3, s=df)
        pi0 = float(spline(1.0))
        pi0 = min(pi0, 1.0)

    # Compute q-values
    qvals = pi0 * m * p_sorted / np.arange(1, m + 1)
    qvals = np.minimum.accumulate(qvals[::-1])[::-1]

    # Reorder to original
    qval_final = np.empty_like(qvals)
    qval_final[order] = qvals
    return qval_final
