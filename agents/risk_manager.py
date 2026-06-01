class RiskManager:
    def __init__(self):
        self.name = "RiskManager"
        self.role = "Portfolio Risk Assessment & Position Sizing Specialist"

    def assess_trade_risk(self, trade, capital=500000):
        assessment = {"risk_score": 0, "max_loss": 0, "recommended_qty": 0,
                      "risk_level": "low", "warnings": []}

        strategy = trade.get("strategy", "").lower()
        trade_type = trade.get("type", "OPTION")
        entry = trade.get("entry", "")

        if "naked" in strategy or "long call" in strategy or "long put" in strategy:
            assessment["risk_score"] = 80
            assessment["risk_level"] = "high"
            assessment["max_loss"] = capital * 0.10
            assessment["recommended_qty"] = max(1, int((capital * 0.05) / 20000))
            assessment["warnings"].append("Unlimited/unlimited-like risk - use strict SL")

        elif "spread" in strategy or "condor" in strategy or "butterfly" in strategy:
            assessment["risk_score"] = 30
            assessment["risk_level"] = "low"
            assessment["max_loss"] = capital * 0.03
            assessment["recommended_qty"] = max(1, int((capital * 0.08) / 15000))
            assessment["warnings"].append("Defined risk strategy - suitable for most portfolios")

        elif "futures" in strategy.lower() or trade_type == "FUTURES":
            assessment["risk_score"] = 55
            assessment["risk_level"] = "moderate"
            assessment["max_loss"] = capital * 0.05
            assessment["recommended_qty"] = max(1, int((capital * 0.06) / 100000))
            assessment["warnings"].append("Leveraged exposure - monitor margin requirements")

        elif "straddle" in strategy or "strangle" in strategy:
            assessment["risk_score"] = 65
            assessment["risk_level"] = "moderate"
            assessment["max_loss"] = capital * 0.07
            assessment["recommended_qty"] = max(1, int((capital * 0.04) / 25000))
            assessment["warnings"].append("Vega sensitive - avoid during low IV")

        confidence = trade.get("confidence", "MEDIUM")
        if confidence == "HIGH":
            assessment["risk_score"] = max(10, assessment["risk_score"] - 15)
        elif confidence == "LOW":
            assessment["risk_score"] = min(90, assessment["risk_score"] + 15)

        return assessment

    def calculate_position_size(self, capital, risk_per_trade_pct, stop_loss_pct):
        risk_amount = capital * (risk_per_trade_pct / 100)
        position_size = risk_amount / (stop_loss_pct / 100)
        return round(position_size, 2)

    def portfolio_risk_summary(self, positions, capital=500000):
        total_delta = 0
        total_gamma = 0
        total_vega = 0
        total_theta = 0
        total_risk = 0

        for pos in positions:
            total_delta += pos.get("delta", 0)
            total_gamma += pos.get("gamma", 0) * 100
            total_vega += pos.get("vega", 0) * 100
            total_theta += pos.get("theta", 0)
            total_risk += pos.get("risk_amount", 0)

        risk_pct = (total_risk / capital) * 100

        warnings = []
        if abs(total_delta) > 1000:
            warnings.append("High delta exposure - market direction risk")
        if total_vega > 5000:
            warnings.append("High vega exposure - volatility crash risk")
        if total_theta < -500:
            warnings.append("Negative theta - time decay working against you")

        return {
            "total_delta": round(total_delta, 2),
            "total_gamma": round(total_gamma, 4),
            "total_vega": round(total_vega, 2),
            "total_theta": round(total_theta, 2),
            "total_risk_amount": round(total_risk, 2),
            "risk_percentage": round(risk_pct, 2),
            "warnings": warnings,
            "status": "OK" if risk_pct < 15 else "CAUTION" if risk_pct < 25 else "OVEREXPOSED",
        }

    def run(self, trade_suggestions, capital=500000):
        print(f"\n{'='*60}")
        print(f"  AGENT: {self.name}")
        print(f"  ROLE: {self.role}")
        print(f"{'='*60}")

        print(f"\n[RISK MANAGER] Assessing trade risk for portfolio (Capital: ₹{capital:,})\n")

        all_assessments = {}
        for risk_level, trades in trade_suggestions.items():
            level_assessments = []
            for trade in trades:
                assessment = self.assess_trade_risk(trade, capital)
                level_assessments.append({**trade, "risk_assessment": assessment})

                print(f"  [{risk_level.upper()}] {trade['strategy']}")
                print(f"      Risk Score : {assessment['risk_score']}/100 ({assessment['risk_level'].upper()})")
                print(f"      Max Loss   : ₹{assessment['max_loss']:,.0f}")
                print(f"      Rec Qty    : {assessment['recommended_qty']} lot(s)")
                if assessment["warnings"]:
                    print(f"      Warnings   : {'; '.join(assessment['warnings'])}")
                print()

            all_assessments[risk_level] = level_assessments

        return all_assessments
