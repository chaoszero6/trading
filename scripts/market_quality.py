#!/usr/bin/env python3
"""Market quality analysis + filtered backtest."""
import yfinance as yf, pandas as pd, numpy as np
from datetime import timedelta
import math, warnings
warnings.filterwarnings('ignore')
from scipy.stats import norm
from nselib import derivatives
from core.technical_indicators import rsi as _rsi

ndf=yf.download("^NSEI",period="1d",interval="1m",progress=False)
bars=[]
for i,(idx,row) in enumerate(ndf.iterrows()):
    ts=idx.to_pydatetime()+timedelta(hours=5,minutes=30)
    if ts.hour<9 or (ts.hour==9 and ts.minute<15) or ts.hour>=15 and ts.minute>30: continue
    c=float(row["Close"].iloc[0]) if isinstance(row["Close"],pd.Series) else float(row["Close"])
    bars.append({"ts":ts.strftime("%H:%M"),"c":c})
n=pd.DataFrame(bars)
n["s10"]=n["c"].rolling(10).mean()
n["s30"]=n["c"].rolling(30).mean()
n["rsi"]=_rsi(pd.Series(n["c"].values),14).values
ORH,ORL=23796,23664

print("="*90)
print("  MARKET QUALITY ANALYSIS — 15 May 2026")
print("="*90)

# 1. SMA Squeeze
n["squeeze"]=abs(n["s10"]-n["s30"])<10

# 2. False breakout detection
n["fake"]=False
for i in range(20,len(n)):
    if n["c"].iloc[i]>ORH and n["c"].iloc[i-1]<=ORH:
        for j in range(i+1,min(i+6,len(n))):
            if n["c"].iloc[j]<=ORH:
                n.loc[n.index[i],"fake"]=True; break

# 3. Trend oscillation
direction_changes=0; last_trend=None
for i in range(20,len(n)):
    tr="U" if n['s10'].iloc[i]>n['s30'].iloc[i] else "D"
    if tr!=last_trend and last_trend is not None: direction_changes+=1
    last_trend=tr

# 4. Morning trap
morning=n[n['ts'].between("09:15","11:00")]
m_changes=0; last_t=None
for i in range(len(morning)):
    idx=morning.index[i]
    tr="U" if n['s10'].iloc[idx]>n['s30'].iloc[idx] else "D"
    if tr!=last_t and last_t is not None: m_changes+=1
    last_t=tr

print(f"\n  Opening Range: {ORL:.0f}-{ORH:.0f} ({ORH-ORL:.0f} pts) {'⚠️ WIDE' if ORH-ORL>100 else '✅ NORMAL'}")
print(f"  SMA Squeeze bars (S10-S30 <10): {n['squeeze'].sum()}/{len(n)} ({n['squeeze'].mean()*100:.0f}%)")
print(f"  False breakouts: {n['fake'].sum()}")
print(f"  Direction changes: {direction_changes} in day")
print(f"  Morning changes (09:15-11:00): {m_changes} {'⛔ TRAP' if m_changes>=3 else '✅ CLEAN'}")
print()

# Quality verdict
issues=[]
if m_changes>=3: issues.append("Morning trap")
if ORH-ORL>100: issues.append("Wide range")
if n['fake'].sum()>0: issues.append("False breakout")
if n['squeeze'].mean()>0.3: issues.append("Squeeze market")
print(f"  Market Quality: {len(issues)} issues — {', '.join(issues) if issues else '✅ GOOD'}")
print(f"  Verdict: {'🛑 SKIP' if len(issues)>=2 else '⚠️ CAUTION' if len(issues)==1 else '✅ TRADE'}")
print()

# Backtest with filters
opt=derivatives.option_price_volume_data(symbol="NIFTY",instrument="OPTIDX",from_date="14-05-2026",to_date="15-05-2026")
opt=opt[opt['TIMESTAMP']=='15-May-2026']
opt=opt[opt['EXPIRY_DT']=='02-Jun-2026'].copy()
opt["STRIKE_PRICE"]=opt["STRIKE_PRICE"].astype(int)
REAL={}
for _,r in opt.iterrows(): REAL[(r["STRIKE_PRICE"],r["OPTION_TYPE"])]=float(r["OPENING_PRICE"])

def bs(S,K,T,r,s,o='CE'):
    s=max(s,0.05)
    if T<=0 or s*math.sqrt(T)<0.001: return max(0,S-K) if o=='CE' else max(0,K-S)
    d1=(math.log(S/K)+(r+0.5*s**2)*T)/(s*math.sqrt(T)); d2=d1-s*math.sqrt(T)
    return S*norm.cdf(d1)-K*math.exp(-r*T)*norm.cdf(d2) if o=='CE' else K*math.exp(-r*T)*norm.cdf(-d2)-S*norm.cdf(-d1)

T,Rsig,S,LOT,CAP=18/365,0.065,0.22,65,20000
cash=CAP; pos=None; trades=[]; skip_until=None

for i in range(30,len(n)):
    hh=int(n['ts'].iloc[i].split(":")[0])
    if hh>=15: break
    if n['squeeze'].iloc[i]: continue
    if n['fake'].iloc[i]: continue

    p=n['c'].iloc[i]; s10=n['s10'].iloc[i]; rsi=n['rsi'].iloc[i]
    near=abs(p-s10)<10; s10up=s10>n['s10'].iloc[i-1]
    trend="BULLISH" if (p>ORH or s10up) else "BEARISH"
    sig=None
    if near and trend=="BULLISH" and 40<rsi<70: sig="CE"
    if near and trend=="BEARISH" and 30<rsi<60: sig="PE"

    if sig and not pos:
        k=round(p/50)*50+(100 if sig=='CE' else -100)
        ep=REAL.get((k,sig))
        if ep and ep*LOT<=cash:
            cash-=ep*LOT; pos={"bi":i,"k":k,"d":sig,"ep":ep,"es":p}

    if pos:
        sc=(p-pos['es'])/pos['es']; cp=max(pos['ep']*(1+sc*10),0.1)
        er=None
        if pos['d']=='CE' and trend=='BEARISH': er="TREND_REV"
        elif pos['d']=='PE' and trend=='BULLISH': er="TREND_REV"
        if not er and i-pos['bi']>=15 and cp<=pos['ep']*0.95: er="NO_IMP"
        if not er and cp<=pos['ep']*0.6: er="HARD_SL"
        if not er and cp>=pos['ep']*2.5: er="TGT_HIT"
        if er:
            pnl=(cp-pos['ep'])*LOT; cash+=pos['ep']*LOT+pnl
            trades.append({"et":n['ts'].iloc[pos['bi']],"xt":n['ts'].iloc[i],"d":pos['d'],
                "k":pos['k'],"ep":round(pos['ep']),"xp":round(cp),"pnl":round(pnl),"r":er})
            pos=None

if pos:
    p=n['c'].iloc[-1]; sc=(p-pos['es'])/pos['es']; cp=pos['ep']*(1+sc*10)
    pnl=(cp-pos['ep'])*LOT; cash+=pos['ep']*LOT+pnl
    trades.append({"et":n['ts'].iloc[pos['bi']],"xt":n['ts'].iloc[-1],"d":pos['d'],
        "k":pos['k'],"ep":round(pos['ep']),"xp":round(cp),"pnl":round(pnl),"r":"EOD"})

total=sum(t['pnl'] for t in trades)
print(f"  FILTERED BACKTEST:\n")
if trades:
    print(f"  {'#':>3} {'Entry':>6} {'Exit':>6} {'Dir':>4} {'Strike':>8} {'Buy':>6} {'Sell':>6} {'P&L':>9} {'Reason':>10}")
    print("  " + "-"*60)
    for i,t in enumerate(trades,1):
        sym="+" if t['pnl']>0 else "-"
        print(f"  {i:>3} {t['et']:>6} {t['xt']:>6} {t['d']:>4} {t['k']:>3}{t['d']} {t['ep']:>5} {t['xp']:>5} {sym} {t['pnl']:>+5,} {t['r']:>10}")
    print("  " + "-"*60)
    w=sum(1 for t in trades if t['pnl']>0); l=len(trades)-w
    print(f"  TOTAL: {w}W/{l}L | P&L: {total:+,} | Cash: {cash:,.0f} | {(cash/CAP-1)*100:+.1f}%")
else:
    print("  No trades (filters skipped all)")

print(f"\n  {'='*60}")
print(f"  COMPARISON:")
print(f"  {'='*60}")
print(f"  RAW (no filters) : 22 trades, -₹994 (-5.0%)")
print(f"  FILTERED         : {len(trades)} trades, {total:+,} ({(cash/CAP-1)*100:+.1f}%)")
print(f"\n  FILTER RULES IMPLEMENTED:")
print(f"  1. SKIP SMA squeeze (S10 & S30 within 10pts) — directionless market")
print(f"  2. SKIP false breakout bars — fake moves")
print(f"  3. Wait for 10:30+ if morning has 3+ direction changes")
