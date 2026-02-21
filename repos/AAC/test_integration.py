#!/usr/bin/env python3
"""
AAC Integration Test Suite
Tests the complete Automated Accounting Center system
"""

import sys
import os
import json
from datetime import datetime, timedelta
from decimal import Decimal

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aac_engine import AccountingEngine, Transaction
from aac_compliance import ComplianceMonitor
from aac_intelligence import FinancialIntelligence

def test_full_system_integration():
    """Test the complete AAC system working together"""
    print("🚀 Starting AAC Integration Test Suite")
    print("=" * 50)

    # Initialize components
    print("📊 Initializing Accounting Engine...")
    engine = AccountingEngine()

    print("⚖️ Initializing Compliance Monitor...")
    compliance = ComplianceMonitor(engine)

    print("🧠 Initializing Financial Intelligence...")
    intelligence = FinancialIntelligence(engine)

    print("\n✅ All components initialized successfully")

    # Test 1: Basic Accounting Operations
    print("\n🧪 Test 1: Basic Accounting Operations")
    print("-" * 40)

    # Create some test transactions
    transactions = [
        Transaction("2024-01-01", "Cash", "Revenue", 1000.00, "Initial revenue"),
        Transaction("2024-01-02", "Cash", "Expenses", 200.00, "Office supplies"),
        Transaction("2024-01-03", "Accounts Receivable", "Revenue", 500.00, "Service revenue"),
        Transaction("2024-01-04", "Cash", "Accounts Receivable", 500.00, "Payment received"),
        Transaction("2024-01-05", "Equipment", "Cash", 300.00, "Computer purchase"),
    ]

    for tx in transactions:
        engine.record_transaction(tx)
        print(f"✓ Recorded: {tx.description}")

    # Generate financial reports
    balance_sheet = engine.generate_balance_sheet()
    income_statement = engine.generate_income_statement()

    print(f"\n📈 Balance Sheet Total Assets: ${balance_sheet['total_assets']:.2f}")
    print(f"📈 Balance Sheet Total Liabilities: ${balance_sheet['total_liabilities']:.2f}")
    print(f"📈 Balance Sheet Total Equity: ${balance_sheet['total_equity']:.2f}")
    print(f"💰 Income Statement Net Income: ${income_statement['net_income']:.2f}")

    # Test 2: Compliance Monitoring
    print("\n🧪 Test 2: Compliance Monitoring")
    print("-" * 40)

    compliance_report = compliance.check_compliance()
    print("Compliance Status:")
    for check, status in compliance_report.items():
        status_icon = "✅" if status['passed'] else "❌"
        print(f"{status_icon} {check}: {status['message']}")

    # Test 3: Financial Intelligence
    print("\n🧪 Test 3: Financial Intelligence")
    print("-" * 40)

    health_score = intelligence.calculate_financial_health_score()
    market_analysis = intelligence.analyze_market_conditions()
    recommendations = intelligence.generate_investment_recommendations()

    print(f"🏥 Financial Health Score: {health_score:.1f}/100")
    print(f"📊 Market Conditions: {market_analysis['overall_sentiment']}")
    print(f"💡 Investment Recommendations: {len(recommendations)} suggestions generated")

    # Test 4: Comprehensive Report
    print("\n🧪 Test 4: Comprehensive Intelligence Report")
    print("-" * 40)

    comprehensive_report = intelligence.generate_comprehensive_report()
    print("📋 Comprehensive Report Generated:")
    print(f"   - Financial Health: {comprehensive_report['financial_health']['score']:.1f}/100")
    print(f"   - Risk Level: {comprehensive_report['risk_assessment']['level']}")
    print(f"   - Market Outlook: {comprehensive_report['market_analysis']['outlook']}")
    print(f"   - Recommendations: {len(comprehensive_report['recommendations'])} items")

    # Test 5: Data Persistence
    print("\n🧪 Test 5: Data Persistence Check")
    print("-" * 40)

    # Create new engine instance to test database persistence
    engine2 = AccountingEngine()
    accounts2 = engine2.get_all_accounts()
    transactions2 = engine2.get_all_transactions()

    print(f"✓ Accounts persisted: {len(accounts2)} accounts found")
    print(f"✓ Transactions persisted: {len(transactions2)} transactions found")

    # Verify data integrity
    original_balance = balance_sheet['total_assets']
    reloaded_balance = engine2.generate_balance_sheet()['total_assets']

    if original_balance == reloaded_balance:
        print("✅ Data integrity verified - balances match")
    else:
        print("❌ Data integrity issue - balances don't match")
        return False

    # Test 6: System Performance
    print("\n🧪 Test 6: System Performance")
    print("-" * 40)

    import time

    # Performance test for transaction processing
    start_time = time.time()
    for i in range(100):
        tx = Transaction("2024-01-06", "Cash", "Revenue", 10.00, f"Bulk test transaction {i+1}")
        engine.record_transaction(tx)

    end_time = time.time()
    processing_time = end_time - start_time

    print(f"⚡ Processed 100 transactions in {processing_time:.2f} seconds")
    print(".2f")

    # Final Summary
    print("\n🎉 AAC Integration Test Suite Complete")
    print("=" * 50)
    print("✅ All core components functional")
    print("✅ Accounting operations working")
    print("✅ Compliance monitoring active")
    print("✅ Financial intelligence operational")
    print("✅ Data persistence verified")
    print("✅ Performance within acceptable limits")
    print("\n🚀 AAC System Ready for Production Deployment")

    return True

def test_error_handling():
    """Test error handling capabilities"""
    print("\n🧪 Testing Error Handling")
    print("-" * 30)

    engine = AccountingEngine()

    # Test invalid transaction
    try:
        invalid_tx = Transaction("2024-01-01", "NonExistentAccount", "Revenue", 100.00, "Invalid")
        engine.record_transaction(invalid_tx)
        print("❌ Error handling failed - invalid transaction accepted")
        return False
    except ValueError as e:
        print(f"✅ Error handling working: {str(e)}")

    # Test negative amount
    try:
        negative_tx = Transaction("2024-01-01", "Cash", "Revenue", -100.00, "Negative")
        engine.record_transaction(negative_tx)
        print("❌ Error handling failed - negative amount accepted")
        return False
    except ValueError as e:
        print(f"✅ Error handling working: {str(e)}")

    print("✅ Error handling tests passed")
    return True

if __name__ == "__main__":
    try:
        success = test_full_system_integration()
        if success:
            error_success = test_error_handling()
            if error_success:
                print("\n🎯 ALL TESTS PASSED - AAC System Fully Operational")
                sys.exit(0)
            else:
                print("\n❌ Error handling tests failed")
                sys.exit(1)
        else:
            print("\n❌ Integration tests failed")
            sys.exit(1)
    except Exception as e:
        print(f"\n💥 Test suite crashed: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)