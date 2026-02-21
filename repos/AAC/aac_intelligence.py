#!/usr/bin/env python3
"""
AAC Financial Intelligence
Market analysis and financial forecasting for Super Agency
"""

import json
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Any, Optional
from decimal import Decimal
import requests
import pandas as pd
from pathlib import Path

logger = logging.getLogger(__name__)

class MarketData:
    """Market data and economic indicators"""

    def __init__(self):
        self.api_key = "demo"  # In production, use real API key
        self.base_url = "https://api.example.com"  # Placeholder

    def get_stock_price(self, symbol: str) -> Optional[float]:
        """Get current stock price (simplified)"""
        # In production, this would call real market APIs
        # For demo, return simulated data
        simulated_prices = {
            'SPY': 450.25,
            'QQQ': 380.75,
            'AAPL': 175.50,
            'GOOGL': 135.20,
            'MSFT': 335.80
        }
        return simulated_prices.get(symbol.upper())

    def get_economic_indicators(self) -> Dict[str, Any]:
        """Get key economic indicators"""
        return {
            'inflation_rate': 3.1,  # CPI
            'unemployment_rate': 4.2,
            'gdp_growth': 2.8,
            'interest_rate': 5.25,  # Fed Funds Rate
            'timestamp': datetime.now().isoformat()
        }

class FinancialIntelligence:
    """Financial intelligence and forecasting system"""

    def __init__(self, accounting_engine):
        self.engine = accounting_engine
        self.market_data = MarketData()
        self.forecast_horizon = 12  # months

    def analyze_financial_health(self) -> Dict[str, Any]:
        """Analyze overall financial health"""
        balance_sheet = self.engine.get_balance_sheet()
        income_stmt = self.engine.get_income_statement(
            date(date.today().year, 1, 1),
            date.today()
        )

        # Calculate key ratios
        ratios = self.calculate_financial_ratios(balance_sheet, income_stmt)

        # Assess financial health
        health_score = self.calculate_health_score(ratios)

        return {
            'timestamp': datetime.now().isoformat(),
            'ratios': ratios,
            'health_score': health_score,
            'assessment': self.assess_financial_health(health_score),
            'recommendations': self.generate_financial_recommendations(ratios)
        }

    def calculate_financial_ratios(self, balance_sheet: Dict, income_stmt: Dict) -> Dict[str, float]:
        """Calculate key financial ratios"""
        assets = float(balance_sheet['assets'])
        liabilities = float(balance_sheet['liabilities'])
        equity = float(balance_sheet['equity'])
        revenue = float(income_stmt['revenue'])
        expenses = float(income_stmt['expenses'])
        net_income = float(income_stmt['net_income'])

        ratios = {}

        # Liquidity ratios
        ratios['current_ratio'] = assets / liabilities if liabilities > 0 else float('inf')
        ratios['quick_ratio'] = assets / liabilities if liabilities > 0 else float('inf')  # Simplified

        # Leverage ratios
        ratios['debt_to_equity'] = liabilities / equity if equity > 0 else float('inf')
        ratios['debt_ratio'] = liabilities / assets if assets > 0 else 0

        # Profitability ratios
        ratios['gross_margin'] = (revenue - expenses) / revenue if revenue > 0 else 0
        ratios['net_margin'] = net_income / revenue if revenue > 0 else 0
        ratios['return_on_equity'] = net_income / equity if equity > 0 else 0

        # Efficiency ratios (simplified)
        ratios['asset_turnover'] = revenue / assets if assets > 0 else 0

        return ratios

    def calculate_health_score(self, ratios: Dict[str, float]) -> float:
        """Calculate overall financial health score (0-100)"""
        score = 0
        max_score = 0

        # Current ratio (ideal: 1.5-3.0)
        if 1.5 <= ratios.get('current_ratio', 0) <= 3.0:
            score += 20
        elif ratios.get('current_ratio', 0) > 0:
            score += 10
        max_score += 20

        # Debt-to-equity (ideal: <1.0)
        if ratios.get('debt_to_equity', float('inf')) < 1.0:
            score += 20
        elif ratios.get('debt_to_equity', float('inf')) < 2.0:
            score += 10
        max_score += 20

        # Net margin (ideal: >5%)
        if ratios.get('net_margin', 0) > 0.05:
            score += 20
        elif ratios.get('net_margin', 0) > 0.02:
            score += 10
        max_score += 20

        # Return on equity (ideal: >10%)
        if ratios.get('return_on_equity', 0) > 0.10:
            score += 20
        elif ratios.get('return_on_equity', 0) > 0.05:
            score += 10
        max_score += 20

        # Asset turnover (ideal: >1.0)
        if ratios.get('asset_turnover', 0) > 1.0:
            score += 20
        elif ratios.get('asset_turnover', 0) > 0.5:
            score += 10
        max_score += 20

        return (score / max_score) * 100 if max_score > 0 else 0

    def assess_financial_health(self, score: float) -> str:
        """Assess financial health based on score"""
        if score >= 80:
            return "Excellent - Strong financial position"
        elif score >= 60:
            return "Good - Solid financial foundation"
        elif score >= 40:
            return "Fair - Room for improvement"
        elif score >= 20:
            return "Poor - Requires attention"
        else:
            return "Critical - Immediate action needed"

    def generate_financial_recommendations(self, ratios: Dict[str, float]) -> List[str]:
        """Generate financial recommendations based on ratios"""
        recommendations = []

        # Liquidity recommendations
        current_ratio = ratios.get('current_ratio', 0)
        if current_ratio < 1.5:
            recommendations.append("⚠️ Improve liquidity: Current ratio below 1.5:1 - consider reducing short-term debt or increasing current assets")
        elif current_ratio > 3.0:
            recommendations.append("💡 Optimize liquidity: High current ratio suggests excess cash - consider investing in revenue-generating assets")

        # Leverage recommendations
        debt_equity = ratios.get('debt_to_equity', float('inf'))
        if debt_equity > 2.0:
            recommendations.append("⚠️ High leverage: Debt-to-equity ratio above 2.0 - focus on debt reduction and equity building")
        elif debt_equity < 0.5:
            recommendations.append("💡 Leverage opportunity: Low debt levels - consider strategic borrowing for growth investments")

        # Profitability recommendations
        net_margin = ratios.get('net_margin', 0)
        if net_margin < 0.05:
            recommendations.append("⚠️ Profitability concern: Net margin below 5% - review pricing strategy and cost controls")
        elif net_margin > 0.15:
            recommendations.append("✅ Strong profitability: Net margin above 15% - excellent profit generation")

        # Growth recommendations
        asset_turnover = ratios.get('asset_turnover', 0)
        if asset_turnover < 0.8:
            recommendations.append("💡 Growth opportunity: Low asset turnover - focus on increasing sales or improving asset utilization")

        if not recommendations:
            recommendations.append("✅ Financial position is healthy - continue monitoring and strategic growth initiatives")

        return recommendations

    def generate_market_intelligence_report(self) -> Dict[str, Any]:
        """Generate market intelligence report"""
        market_data = self.market_data.get_economic_indicators()

        # Analyze market conditions
        market_analysis = self.analyze_market_conditions(market_data)

        # Generate investment recommendations
        investment_recs = self.generate_investment_recommendations(market_data)

        return {
            'timestamp': datetime.now().isoformat(),
            'market_conditions': market_analysis,
            'economic_indicators': market_data,
            'investment_recommendations': investment_recs,
            'risk_assessment': self.assess_market_risks(market_data)
        }

    def analyze_market_conditions(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze current market conditions"""
        inflation = market_data.get('inflation_rate', 0)
        unemployment = market_data.get('unemployment_rate', 0)
        gdp_growth = market_data.get('gdp_growth', 0)
        interest_rate = market_data.get('interest_rate', 0)

        conditions = {
            'inflation_environment': 'high' if inflation > 4 else 'moderate' if inflation > 2 else 'low',
            'employment_market': 'strong' if unemployment < 4 else 'moderate' if unemployment < 6 else 'weak',
            'economic_growth': 'strong' if gdp_growth > 3 else 'moderate' if gdp_growth > 1 else 'slow',
            'monetary_policy': 'tight' if interest_rate > 4 else 'neutral' if interest_rate > 2 else 'loose'
        }

        # Overall market sentiment
        sentiment_score = 0
        if conditions['economic_growth'] == 'strong': sentiment_score += 25
        elif conditions['economic_growth'] == 'moderate': sentiment_score += 15

        if conditions['employment_market'] == 'strong': sentiment_score += 25
        elif conditions['employment_market'] == 'moderate': sentiment_score += 15

        if conditions['inflation_environment'] == 'low': sentiment_score += 25
        elif conditions['inflation_environment'] == 'moderate': sentiment_score += 15

        if conditions['monetary_policy'] == 'neutral': sentiment_score += 25
        elif conditions['monetary_policy'] == 'loose': sentiment_score += 15

        conditions['overall_sentiment'] = 'bullish' if sentiment_score >= 75 else 'neutral' if sentiment_score >= 50 else 'bearish'

        return conditions

    def generate_investment_recommendations(self, market_data: Dict[str, Any]) -> List[str]:
        """Generate investment recommendations based on market conditions"""
        recommendations = []

        inflation = market_data.get('inflation_rate', 0)
        interest_rate = market_data.get('interest_rate', 0)
        gdp_growth = market_data.get('gdp_growth', 0)

        # Asset allocation recommendations
        if inflation > 4:
            recommendations.append("🛡️ Inflation hedge: Consider TIPS, commodities, or real estate investments")
        elif inflation < 2:
            recommendations.append("📈 Growth focus: Favor equities and risk assets in low inflation environment")

        if interest_rate > 4.5:
            recommendations.append("💰 Income focus: High interest rates favor bonds and dividend stocks")
        elif interest_rate < 2.5:
            recommendations.append("🚀 Growth stocks: Low rates support leveraged growth investments")

        if gdp_growth > 3:
            recommendations.append("📊 Cyclical sectors: Favor industrials, materials, and financials in strong growth")
        elif gdp_growth < 1.5:
            recommendations.append("🛡️ Defensive sectors: Consider utilities, healthcare, and consumer staples")

        # Risk management
        recommendations.append("🔄 Diversification: Maintain balanced portfolio across asset classes")
        recommendations.append("📅 Regular rebalancing: Review and adjust allocations quarterly")

        return recommendations

    def assess_market_risks(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """Assess market risks"""
        risks = {
            'inflation_risk': 'high' if market_data.get('inflation_rate', 0) > 4 else 'moderate' if market_data.get('inflation_rate', 0) > 2 else 'low',
            'recession_risk': 'high' if market_data.get('unemployment_rate', 0) > 6 else 'moderate' if market_data.get('unemployment_rate', 0) > 4.5 else 'low',
            'interest_rate_risk': 'high' if abs(market_data.get('interest_rate', 0) - 3.0) > 2 else 'moderate' if abs(market_data.get('interest_rate', 0) - 3.0) > 1 else 'low'
        }

        overall_risk = 'high' if any(r == 'high' for r in risks.values()) else 'moderate' if any(r == 'moderate' for r in risks.values()) else 'low'

        return {
            'specific_risks': risks,
            'overall_risk_level': overall_risk,
            'recommendations': [
                "📊 Monitor economic indicators weekly",
                "💼 Maintain emergency cash reserves (3-6 months expenses)",
                "🎯 Consider dollar-cost averaging for long-term investments"
            ]
        }

    def generate_comprehensive_report(self) -> Dict[str, Any]:
        """Generate comprehensive financial intelligence report"""
        financial_health = self.analyze_financial_health()
        market_intelligence = self.generate_market_intelligence_report()

        report = {
            'title': 'Super Agency Financial Intelligence Report',
            'generated_at': datetime.now().isoformat(),
            'sections': {
                'financial_health': financial_health,
                'market_intelligence': market_intelligence
            },
            'executive_summary': self.generate_executive_summary(financial_health, market_intelligence),
            'action_items': self.generate_action_items(financial_health, market_intelligence)
        }

        return report

    def generate_executive_summary(self, health: Dict, market: Dict) -> str:
        """Generate executive summary"""
        health_score = health.get('health_score', 0)
        market_sentiment = market.get('market_conditions', {}).get('overall_sentiment', 'neutral')

        summary = f"Financial health score: {health_score:.1f}/100 ({health.get('assessment', 'Unknown')}). "
        summary += f"Market sentiment: {market_sentiment}. "

        if health_score >= 70 and market_sentiment in ['bullish', 'neutral']:
            summary += "Overall financial position is strong with favorable market conditions."
        elif health_score < 50 or market_sentiment == 'bearish':
            summary += "Caution advised - review financial position and market conditions."
        else:
            summary += "Monitor developments closely and maintain conservative approach."

        return summary

    def generate_action_items(self, health: Dict, market: Dict) -> List[str]:
        """Generate prioritized action items"""
        actions = []

        # Financial health actions
        health_score = health.get('health_score', 0)
        if health_score < 60:
            actions.append("🔴 HIGH PRIORITY: Address critical financial health issues")
        elif health_score < 80:
            actions.append("🟡 MEDIUM PRIORITY: Implement financial health improvements")

        # Add specific recommendations
        actions.extend(health.get('recommendations', [])[:3])  # Top 3 financial recommendations
        actions.extend(market.get('investment_recommendations', [])[:2])  # Top 2 market recommendations

        # Risk management
        market_risks = market.get('risk_assessment', {})
        if market_risks.get('overall_risk_level') == 'high':
            actions.append("🛡️ Implement risk mitigation strategies")

        return list(set(actions))  # Remove duplicates

def main():
    """Test financial intelligence system"""
    print("🧠 AAC Financial Intelligence")
    print("=" * 40)

    # This would normally be integrated with the accounting engine
    print("📊 Financial intelligence system ready")
    print("💡 Integrate with AAC dashboard for comprehensive financial analysis")

if __name__ == "__main__":
    main()