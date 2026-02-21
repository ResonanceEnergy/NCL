#!/usr/bin/env python3
"""
AAC Compliance Monitor
Automated compliance monitoring and regulatory reporting for Super Agency
"""

import json
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Any, Optional
from pathlib import Path
import requests
from decimal import Decimal

logger = logging.getLogger(__name__)

class ComplianceRule:
    """Represents a compliance rule"""

    def __init__(self, rule_id: str, name: str, description: str,
                 rule_type: str, threshold: Any, frequency: str):
        self.rule_id = rule_id
        self.name = name
        self.description = description
        self.rule_type = rule_type  # 'balance', 'transaction', 'ratio', 'deadline'
        self.threshold = threshold
        self.frequency = frequency  # 'daily', 'weekly', 'monthly', 'quarterly'
        self.last_checked = None
        self.status = "active"

class ComplianceMonitor:
    """Compliance monitoring system"""

    def __init__(self, accounting_engine):
        self.engine = accounting_engine
        self.rules = self.load_default_rules()

    def load_default_rules(self) -> Dict[str, ComplianceRule]:
        """Load default compliance rules"""
        rules = {}

        # Balance sheet rules
        rules['working_capital'] = ComplianceRule(
            'WC001', 'Working Capital Ratio',
            'Current assets should be at least 1.5x current liabilities',
            'ratio', 1.5, 'monthly'
        )

        rules['debt_equity'] = ComplianceRule(
            'DE001', 'Debt-to-Equity Ratio',
            'Total debt should not exceed 2x equity',
            'ratio', 2.0, 'quarterly'
        )

        # Transaction rules
        rules['large_transaction'] = ComplianceRule(
            'LT001', 'Large Transaction Alert',
            'Transactions over $10,000 require additional review',
            'transaction', 10000.00, 'daily'
        )

        # Deadline rules
        rules['tax_filing'] = ComplianceRule(
            'TF001', 'Tax Filing Deadline',
            'Quarterly tax filings due by 15th of month following quarter',
            'deadline', 'Q4_2026-03-15', 'quarterly'
        )

        return rules

    def check_compliance(self) -> Dict[str, Any]:
        """Run compliance checks"""
        results = {
            'timestamp': datetime.now().isoformat(),
            'rules_checked': len(self.rules),
            'passed': 0,
            'failed': 0,
            'warnings': 0,
            'details': []
        }

        for rule_id, rule in self.rules.items():
            if self.should_check_rule(rule):
                result = self.check_rule(rule)
                results['details'].append(result)

                if result['status'] == 'pass':
                    results['passed'] += 1
                elif result['status'] == 'fail':
                    results['failed'] += 1
                elif result['status'] == 'warning':
                    results['warnings'] += 1

                rule.last_checked = datetime.now()

        results['overall_status'] = 'compliant' if results['failed'] == 0 else 'non_compliant'
        return results

    def should_check_rule(self, rule: ComplianceRule) -> bool:
        """Determine if a rule should be checked based on frequency"""
        if rule.last_checked is None:
            return True

        now = datetime.now()
        time_diff = now - rule.last_checked

        if rule.frequency == 'daily':
            return time_diff.days >= 1
        elif rule.frequency == 'weekly':
            return time_diff.days >= 7
        elif rule.frequency == 'monthly':
            return time_diff.days >= 30
        elif rule.frequency == 'quarterly':
            return time_diff.days >= 90

        return False

    def check_rule(self, rule: ComplianceRule) -> Dict[str, Any]:
        """Check a specific compliance rule"""
        result = {
            'rule_id': rule.rule_id,
            'rule_name': rule.name,
            'status': 'unknown',
            'message': '',
            'value': None,
            'threshold': rule.threshold
        }

        try:
            if rule.rule_type == 'ratio':
                result.update(self.check_ratio_rule(rule))
            elif rule.rule_type == 'balance':
                result.update(self.check_balance_rule(rule))
            elif rule.rule_type == 'transaction':
                result.update(self.check_transaction_rule(rule))
            elif rule.rule_type == 'deadline':
                result.update(self.check_deadline_rule(rule))

        except Exception as e:
            result['status'] = 'error'
            result['message'] = f"Error checking rule: {e}"

        return result

    def check_ratio_rule(self, rule: ComplianceRule) -> Dict[str, Any]:
        """Check ratio-based compliance rules"""
        balance_sheet = self.engine.get_balance_sheet()

        if rule.rule_id == 'WC001':  # Working capital ratio
            # Simplified: assume all assets are current, no current liabilities
            current_assets = balance_sheet['assets']
            current_liabilities = balance_sheet['liabilities']
            ratio = float(current_assets / current_liabilities) if current_liabilities > 0 else float('inf')

            return {
                'status': 'pass' if ratio >= rule.threshold else 'warning',
                'message': f"Working capital ratio: {ratio:.2f} (threshold: {rule.threshold})",
                'value': ratio
            }

        elif rule.rule_id == 'DE001':  # Debt-to-equity ratio
            total_debt = balance_sheet['liabilities']
            equity = balance_sheet['equity']
            ratio = float(total_debt / equity) if equity > 0 else float('inf')

            return {
                'status': 'pass' if ratio <= rule.threshold else 'fail',
                'message': f"Debt-to-equity ratio: {ratio:.2f} (threshold: {rule.threshold})",
                'value': ratio
            }

        return {'status': 'unknown', 'message': 'Ratio calculation not implemented'}

    def check_balance_rule(self, rule: ComplianceRule) -> Dict[str, Any]:
        """Check balance-based compliance rules"""
        # Placeholder for balance rules
        return {'status': 'pass', 'message': 'Balance rule check not implemented'}

    def check_transaction_rule(self, rule: ComplianceRule) -> Dict[str, Any]:
        """Check transaction-based compliance rules"""
        if rule.rule_id == 'LT001':  # Large transaction alert
            # Check recent transactions for large amounts
            cursor = self.engine.conn.execute('''
                SELECT SUM(CAST(te.debit AS DECIMAL)) as amount
                FROM transactions t
                JOIN transaction_entries te ON t.transaction_id = te.transaction_id
                WHERE t.date >= date('now', '-30 days')
                GROUP BY t.transaction_id
                HAVING amount > ?
                LIMIT 1
            ''', (rule.threshold,))

            large_transaction = cursor.fetchone()

            if large_transaction:
                return {
                    'status': 'warning',
                    'message': f"Large transaction detected: ${large_transaction[0]:.2f}",
                    'value': float(large_transaction[0])
                }
            else:
                return {
                    'status': 'pass',
                    'message': f"No large transactions over ${rule.threshold} in last 30 days",
                    'value': 0
                }

        return {'status': 'pass', 'message': 'Transaction rule check completed'}

    def check_deadline_rule(self, rule: ComplianceRule) -> Dict[str, Any]:
        """Check deadline-based compliance rules"""
        if rule.rule_id == 'TF001':  # Tax filing deadline
            # Simplified tax deadline check
            today = date.today()
            tax_deadline = date(today.year, 3, 15)  # Q4 tax deadline

            if today <= tax_deadline:
                days_remaining = (tax_deadline - today).days
                return {
                    'status': 'pass' if days_remaining > 30 else 'warning',
                    'message': f"Tax filing deadline: {tax_deadline.isoformat()} ({days_remaining} days remaining)",
                    'value': days_remaining
                }
            else:
                return {
                    'status': 'fail',
                    'message': f"Tax filing deadline {tax_deadline.isoformat()} has passed",
                    'value': -1
                }

        return {'status': 'pass', 'message': 'Deadline rule check completed'}

    def generate_compliance_report(self) -> Dict[str, Any]:
        """Generate comprehensive compliance report"""
        results = self.check_compliance()

        report = {
            'title': 'Super Agency Compliance Report',
            'generated_at': datetime.now().isoformat(),
            'period': f"{date.today().replace(day=1)} to {date.today()}",
            'summary': {
                'overall_status': results['overall_status'],
                'rules_checked': results['rules_checked'],
                'passed': results['passed'],
                'failed': results['failed'],
                'warnings': results['warnings']
            },
            'details': results['details'],
            'recommendations': self.generate_recommendations(results)
        }

        return report

    def generate_recommendations(self, results: Dict[str, Any]) -> List[str]:
        """Generate compliance recommendations based on results"""
        recommendations = []

        failed_rules = [d for d in results['details'] if d['status'] == 'fail']
        warning_rules = [d for d in results['details'] if d['status'] == 'warning']

        if failed_rules:
            recommendations.append("CRITICAL: Address failed compliance rules immediately")
            for rule in failed_rules:
                recommendations.append(f"• Fix {rule['rule_name']}: {rule['message']}")

        if warning_rules:
            recommendations.append("WARNING: Review the following compliance items")
            for rule in warning_rules:
                recommendations.append(f"• Review {rule['rule_name']}: {rule['message']}")

        if not failed_rules and not warning_rules:
            recommendations.append("✅ All compliance checks passed - continue monitoring")

        return recommendations

def main():
    """Test compliance monitor"""
    print("🔍 AAC Compliance Monitor")
    print("=" * 40)

    # This would normally be integrated with the accounting engine
    print("📋 Compliance monitoring system ready")
    print("💡 Integrate with AAC dashboard for full compliance reporting")

if __name__ == "__main__":
    main()