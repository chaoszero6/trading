#!/usr/bin/env python3
"""Active trade management simulation."""
import yfinance as yf, pandas as pd, numpy as np
from datetime import timedelta
import math, warnings
warnings.filterwarnings('ignore')
from scipy.stats import norm
from core.technical_indicators import rsi as _rsi

def bs(S,K,T,r,s,o='CE'):
    s=max(s,0.05)
    if T<=0 or s*math.sqrt(T)<0.001: return max(0,S-K) if o=='CE' else max(0,K-S)
    d1=(math.log(S/K)+(r+0.5*s**2)*T)/(s*math.sqrt(T))
    d2=d1-s*math.sqrt(T)
    return S*norm.cdf(d1)-K*math.exp(-r*T)*norm.cdf(d2) if o=='CE' else K*math.exp(-r*T)*norm.cdf(-d2)-S*norm.cdf(-d1)

ndf=yf.download("^NSEI",period="1d",interval="1m",progress=False)
bars=[]
for i,(idx,row) in enumerate(ndf.iterrows()):
    ts=idx.to_pydatetime()+timedelta(hours=5,minutes=30)
    if ts.hour<9 or (ts.hour==9 and ts.minute<15) or ts.hour>=15 and ts.minute>30: continue
    c=float(row["Close"].iloc[0]) if isinstance(row["Close"],pd.Series) else float(row["Close"])
    bars.append({"ts":ts.strftime("%H:%M"),"c":c})
n=pd.DataFrame(bars)
n["rsi"]=_rsi(pd.Series(n["c"].values),14).values
n["s10"]=n["c"].rolling(10).mean()
ORH,ORL=23796,23664
T,Rsig,S,LOT,CAP=18/365,0.065,0.22,65,20000

cash=CAP; pos=None; trades=[]; debug_count=0

for i in range(30,len(n)):
    hh=int(n['ts'].iloc[i].split(":")[0])
    if hh>=15: break
    
    p=n['c'].iloc[i]; s10=n['s10'].iloc[i]; rsi=n['rsi'].iloc[i]
    near=abs(p-s10)<10
    s10up=s10>n['s10'].iloc[i-1]
    trend="BULLISH" if (p>ORH or s10up) else "BEARISH"
    
    sig=None
    if near and trend=="BULLISH" and 40<rsi<70: sig="CE"
    if near and trend=="BEARISH" and 30<rsi<60: sig="PE"
    
    if sig:
        debug_count+=1
    
    if sig and not pos:
        k=round(p/50)*50+(100 if sig=='CE' else -100)
        ep=bs(p,k,T,Rsig,S,sig)
        if ep*LOT<=cash:
            cash-=ep*LOT
            pos={"bi":i,"k":k,"d":sig,"ep":ep,"es":p}

    if pos:
        cp=bs(p,pos['k'],T,Rsig,S,pos['d'])
        er=None
        if pos['d']=='CE' and trend=='BEARISH': er="TREND_REV"
        elif pos['d']=='PE' and trend=='BULLISH': er="TREND_REV"
        if not er and i-pos['bi']>=15 and cp<=pos['ep']: er="NO_IMP"
        if not er and cp<=pos['ep']*0.6: er="HARD_SL"
        if er:
            pnl=(cp-pos['ep'])*LOT; cash+=pos['ep']*LOT+pnl
            trades.append({"et":n['ts'].iloc[pos['bi']],"xt":n['ts'].iloc[i],"d":pos['d'],"k":pos['k"],
                "ep":round(pos['ep']),"xp":round(cp),"pnl":round(pnl),"r":er})
            pos=None

if pos:
    p=n['c'].iloc[-1]; cp=bs(p,pos['k'],T,Rsig,S,pos['d'])
    pnl=(cp-pos['ep'])*LOT; cash+=pos['ep']*LOT+pnl
    trades.append({"et":n['ts'].iloc[pos['bi']],"xt":n['ts'].iloc[-1],"d":pos['d'],"k":pos['k'],
        "ep":round(pos['ep']),"xp":round(cp),"pnl":round(pnl),"r":"EOD"})

total=sum(t['pnl'] for t in trades)
print(f"Active Mgmt | Signals detected: {debug_count} | Trades: {len(trades)}\n")
if trades:
    print(f" {'#':>3} {'Entry':>6} {'Exit':>6} {'Dir':>4} {'Strike':>8} {'Buy':>6} {'Sell':>6} {'P&L':>9} {'Reason':>10}")
    print(" " + "-" * 60)
    for i,t in enumerate(trades,1):
        sym="✅" if t['pnl']>0 else "❌"
        print(f" {i:>3} {t['et']:>6} {t['xt']:>6} {t['d']:>4} {t['k']:>3}{t['d']} {t['ep']:>5} {t['xp']:>5} {sym} ₹{t['pnl']:>+6,} {t['r']:>10}")
    print(" " + "-" * 60)
    w=sum(1 for t in trades if t['pnl']>0); l=len(trades)-w
    print(f" {'':>28} TOTAL: {w}W/{l}L | ₹{total:+,} | Cash: ₹{cash:,.0f} | {(cash/CAP-1)*100:+.1f}%")
else:
    print("No trades executed")
print(f"\nPassive: 1 trade, -₹2,405, final ₹17,595, -12.0%")
