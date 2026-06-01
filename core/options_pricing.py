import numpy as np
from scipy.stats import norm


def black_scholes_price(S, K, T, r, sigma, option_type="call"):
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if option_type == "call":
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:
        return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def delta(S, K, T, r, sigma, option_type="call"):
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    return norm.cdf(d1) if option_type == "call" else -norm.cdf(-d1)


def gamma(S, K, T, r, sigma):
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    return norm.pdf(d1) / (S * sigma * np.sqrt(T))


def theta(S, K, T, r, sigma, option_type="call"):
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    term = - (S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T))
    if option_type == "call":
        return term - r * K * np.exp(-r * T) * norm.cdf(d2)
    else:
        return term + r * K * np.exp(-r * T) * norm.cdf(-d2)


def vega(S, K, T, r, sigma):
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    return S * norm.pdf(d1) * np.sqrt(T)


def greeks(S, K, T, r, sigma):
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return {
        "delta_call": round(norm.cdf(d1), 4),
        "delta_put": round(-norm.cdf(-d1), 4),
        "gamma": round(norm.pdf(d1) / (S * sigma * np.sqrt(T)), 6),
        "theta_call": round((- (S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T))
                             - r * K * np.exp(-r * T) * norm.cdf(d2)), 4),
        "theta_put": round((- (S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T))
                            + r * K * np.exp(-r * T) * norm.cdf(-d2)), 4),
        "vega": round(S * norm.pdf(d1) * np.sqrt(T), 4),
    }


def implied_volatility(market_price, S, K, T, r, option_type="call", tol=1e-5, max_iter=100):
    sigma = 0.3
    for _ in range(max_iter):
        price = black_scholes_price(S, K, T, r, sigma, option_type)
        diff = price - market_price
        if abs(diff) < tol:
            return round(sigma, 4)
        v = vega(S, K, T, r, sigma)
        if abs(v) < 1e-10:
            return None
        sigma = sigma - diff / v
        if sigma <= 0:
            sigma = 0.01
    return round(sigma, 4)


def option_strategy_payoff(S_range, strikes, strategy):
    """strategy: list of legs, each leg = (type, strike, side, qty)
    type: 'call'/'put', side: 'buy'/'sell', qty: int"""
    payoffs = np.zeros_like(S_range)
    for opt_type, strike, side, qty in strategy:
        if opt_type == "call":
            leg_payoff = np.maximum(S_range - strike, 0)
        else:
            leg_payoff = np.maximum(strike - S_range, 0)
        if side == "sell":
            leg_payoff = -leg_payoff
        payoffs += leg_payoff * qty
    return payoffs
