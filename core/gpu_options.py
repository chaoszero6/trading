"""
GPU-Accelerated Options Pricing & Monte Carlo Simulation
Uses CUDA via numba for parallel computation across strikes/expiries.
"""
import math
import numpy as np
from numba import cuda, float64
from numba.cuda.random import create_xoroshiro128p_states, xoroshiro128p_normal_float32
from scipy.stats import norm

THREADS_PER_BLOCK = 256


@cuda.jit
def _mc_option_kernel(rng_states, spot, strike, T, r, sigma, paths, opt_type):
    i = cuda.grid(1)
    if i >= paths.shape[0]:
        return
    n_steps = max(2, int(252.0 * T))
    dt = T / n_steps
    S = spot
    for t in range(n_steps):
        z = xoroshiro128p_normal_float32(rng_states, i)
        S *= math.exp((r - 0.5 * sigma * sigma) * dt + sigma * math.sqrt(dt) * z)
    if opt_type == 0:
        paths[i] = max(S - strike, 0.0)
    else:
        paths[i] = max(strike - S, 0.0)


@cuda.jit
def _mc_batch_kernel(rng_states, spots, strikes, Ts, rs, sigmas, output, opt_type, n_paths):
    idx = cuda.grid(1)
    n_strikes = strikes.shape[0]
    strike_idx = idx // n_paths
    sim_idx = idx % n_paths
    if strike_idx >= n_strikes:
        return

    S = spots[strike_idx]
    K = strikes[strike_idx]
    T = Ts[strike_idx]
    r = rs[strike_idx]
    sigma = sigmas[strike_idx]
    n_steps = max(2, int(252.0 * T))
    dt = T / n_steps

    price = S
    for t in range(n_steps):
        z = xoroshiro128p_normal_float32(rng_states, idx)
        price *= math.exp((r - 0.5 * sigma * sigma) * dt + sigma * math.sqrt(dt) * z)

    if opt_type == 0:
        output[idx] = max(price - K, 0.0)
    else:
        output[idx] = max(K - price, 0.0)


def monte_carlo_price(spot, strike, T, r, sigma, opt_type="call", n_sims=50000):
    opt_t = 0 if opt_type == "call" else 1
    paths = np.zeros(n_sims, dtype=np.float64)
    threads = min(THREADS_PER_BLOCK, n_sims)
    blocks = (n_sims + threads - 1) // threads
    rng_states = create_xoroshiro128p_states(threads * blocks, seed=42)
    _mc_option_kernel[blocks, threads](rng_states, spot, strike, T, r, sigma, paths, opt_t)
    cuda.synchronize()
    return float(np.mean(paths))


def monte_carlo_greeks(spot, strike, T, r, sigma, opt_type="call", n_sims=30000):
    opt_t = 0 if opt_type == "call" else 1
    eps = spot * 0.01
    base = monte_carlo_price(spot, strike, T, r, sigma, opt_type, n_sims)
    up = monte_carlo_price(spot + eps, strike, T, r, sigma, opt_type, n_sims)
    down = monte_carlo_price(spot - eps, strike, T, r, sigma, opt_type, n_sims)
    delta = (up - down) / (2 * eps)
    gamma = (up - 2 * base + down) / (eps * eps)

    eps_sig = sigma * 0.05
    up_v = monte_carlo_price(spot, strike, T, r, sigma + eps_sig, opt_type, n_sims)
    vega = (up_v - base) / eps_sig * 0.01

    eps_T = max(T * 0.01, 1 / 365)
    up_t = monte_carlo_price(spot, strike, T + eps_T, r, sigma, opt_type, n_sims)
    theta = (up_t - base) / eps_T / 365

    return {"delta": round(delta, 4), "gamma": round(gamma, 6),
            "vega": round(vega, 4), "theta": round(theta, 4),
            "price": round(base, 2)}


def batch_price_all_strikes(spot, strikes, T, r, sigma, opt_type="call", n_sims=100000):
    opt_t = 0 if opt_type == "call" else 1
    n = len(strikes)
    spots = np.full(n, spot, dtype=np.float64)
    Ts = np.full(n, T, dtype=np.float64)
    rs = np.full(n, r, dtype=np.float64)
    sigmas = np.full(n, sigma, dtype=np.float64)
    strikes_a = np.array(strikes, dtype=np.float64)

    total = n * n_sims
    output = np.zeros(total, dtype=np.float64)
    threads = min(THREADS_PER_BLOCK, total)
    blocks = (total + threads - 1) // threads

    rng_states = create_xoroshiro128p_states(threads * blocks, seed=42)
    _mc_batch_kernel[blocks, threads](rng_states, spots, strikes_a, Ts, rs, sigmas,
                                       output, opt_t, n_sims)
    cuda.synchronize()

    prices = []
    for i in range(n):
        prices.append(float(np.mean(output[i * n_sims:(i + 1) * n_sims])))
    return prices


def black_scholes_price(S, K, T, r, sigma, opt_type="call"):
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if opt_type == "call":
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    else:
        return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def bs_greeks(S, K, T, r, sigma):
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return {
        "delta_call": round(norm.cdf(d1), 4),
        "delta_put": round(-norm.cdf(-d1), 4),
        "gamma": round(norm.pdf(d1) / (S * sigma * math.sqrt(T)), 6),
        "theta_call": round((-S * norm.pdf(d1) * sigma / (2 * math.sqrt(T))
                             - r * K * math.exp(-r * T) * norm.cdf(d2)) / 365, 4),
        "theta_put": round((-S * norm.pdf(d1) * sigma / (2 * math.sqrt(T))
                            + r * K * math.exp(-r * T) * norm.cdf(-d2)) / 365, 4),
        "vega": round(S * norm.pdf(d1) * math.sqrt(T) / 100, 4),
        "iv": sigma,
    }
