#!/usr/bin/env python3
"""
AAC Web Dashboard
Flask-based web interface for AAC accounting system
"""

import os
from flask import Flask, render_template, request, jsonify, flash, redirect, url_for
from datetime import datetime, date
from decimal import Decimal
import json
from aac_engine import AccountingEngine, Transaction, Account
import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')

# Initialize accounting engine
engine = AccountingEngine()

@app.route('/')
def dashboard():
    """Main dashboard"""
    try:
        # Get financial overview
        balance_sheet = engine.get_balance_sheet()
        income_stmt = engine.get_income_statement(
            date(date.today().year, 1, 1),
            date.today()
        )

        return render_template('dashboard.html',
                             balance_sheet=balance_sheet,
                             income_stmt=income_stmt,
                             current_date=datetime.now())
    except Exception as e:
        flash(f"Error loading dashboard: {e}", "error")
        return render_template('dashboard.html',
                             balance_sheet={},
                             income_stmt={},
                             current_date=datetime.now())

@app.route('/accounts')
def accounts():
    """Chart of accounts"""
    try:
        # Get all accounts (simplified - in production would paginate)
        accounts_list = []
        cursor = engine.conn.execute('SELECT * FROM accounts WHERE is_active = 1 ORDER BY account_type, account_id')
        for row in cursor.fetchall():
            accounts_list.append({
                'account_id': row[0],
                'name': row[1],
                'account_type': row[2],
                'balance': Decimal(row[5])
            })

        return render_template('accounts.html', accounts=accounts_list)
    except Exception as e:
        flash(f"Error loading accounts: {e}", "error")
        return render_template('accounts.html', accounts=[])

@app.route('/transactions')
def transactions():
    """Transaction history"""
    try:
        transactions_list = []
        cursor = engine.conn.execute('''
            SELECT t.transaction_id, t.date, t.description, t.reference,
                   SUM(CAST(te.debit AS DECIMAL)) as total_debit,
                   SUM(CAST(te.credit AS DECIMAL)) as total_credit
            FROM transactions t
            LEFT JOIN transaction_entries te ON t.transaction_id = te.transaction_id
            GROUP BY t.transaction_id, t.date, t.description, t.reference
            ORDER BY t.date DESC
            LIMIT 50
        ''')

        for row in cursor.fetchall():
            transactions_list.append({
                'transaction_id': row[0],
                'date': row[1],
                'description': row[2],
                'reference': row[3],
                'amount': Decimal(str(row[4] or 0))
            })

        return render_template('transactions.html', transactions=transactions_list)
    except Exception as e:
        flash(f"Error loading transactions: {e}", "error")
        return render_template('transactions.html', transactions=[])

@app.route('/record_transaction', methods=['GET', 'POST'])
def record_transaction():
    """Record a new transaction"""
    if request.method == 'POST':
        try:
            # Get form data
            transaction_date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
            description = request.form['description']
            reference = request.form.get('reference', '')

            # Parse entries
            entries = []
            account_ids = request.form.getlist('account_id[]')
            debits = request.form.getlist('debit[]')
            credits = request.form.getlist('credit[]')

            for i, account_id in enumerate(account_ids):
                if account_id and (debits[i] or credits[i]):
                    entries.append({
                        'account_id': account_id,
                        'debit': debits[i] or '0.00',
                        'credit': credits[i] or '0.00'
                    })

            # Create and record transaction
            transaction = Transaction(
                transaction_id=str(uuid.uuid4()),
                date=transaction_date,
                description=description,
                entries=entries,
                reference=reference
            )

            if engine.record_transaction(transaction):
                flash("Transaction recorded successfully!", "success")
                return redirect(url_for('transactions'))
            else:
                flash("Failed to record transaction", "error")

        except Exception as e:
            flash(f"Error recording transaction: {e}", "error")

    # Get accounts for dropdown
    accounts_list = []
    cursor = engine.conn.execute('SELECT account_id, name FROM accounts WHERE is_active = 1 ORDER BY name')
    for row in cursor.fetchall():
        accounts_list.append({'id': row[0], 'name': row[1]})

    return render_template('record_transaction.html', accounts=accounts_list)

@app.route('/reports/balance_sheet')
def balance_sheet_report():
    """Balance sheet report"""
    try:
        report = engine.get_balance_sheet()
        return render_template('balance_sheet.html', report=report)
    except Exception as e:
        flash(f"Error generating balance sheet: {e}", "error")
        return render_template('balance_sheet.html', report={})

@app.route('/reports/income_statement')
def income_statement_report():
    """Income statement report"""
    try:
        start_date = date(date.today().year, 1, 1)
        end_date = date.today()
        report = engine.get_income_statement(start_date, end_date)
        return render_template('income_statement.html', report=report)
    except Exception as e:
        flash(f"Error generating income statement: {e}", "error")
        return render_template('income_statement.html', report={})

@app.route('/api/accounts')
def api_accounts():
    """API endpoint for accounts"""
    try:
        accounts_list = []
        cursor = engine.conn.execute('SELECT account_id, name, account_type, balance FROM accounts WHERE is_active = 1')
        for row in cursor.fetchall():
            accounts_list.append({
                'account_id': row[0],
                'name': row[1],
                'account_type': row[2],
                'balance': str(Decimal(row[3]))
            })
        return jsonify({'accounts': accounts_list})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/transactions')
def api_transactions():
    """API endpoint for transactions"""
    try:
        transactions_list = []
        cursor = engine.conn.execute('''
            SELECT transaction_id, date, description, reference
            FROM transactions
            ORDER BY date DESC
            LIMIT 100
        ''')
        for row in cursor.fetchall():
            transactions_list.append({
                'transaction_id': row[0],
                'date': row[1],
                'description': row[2],
                'reference': row[3]
            })
        return jsonify({'transactions': transactions_list})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.teardown_appcontext
def teardown_db(exception):
    """Clean up database connection"""
    pass  # Engine handles its own connection

if __name__ == '__main__':
    # Set up default accounts if not exists
    engine.setup_default_accounts()

    print("🚀 Starting AAC Web Dashboard...")
    print("📊 Visit http://localhost:5000 to access the dashboard")
    app.run(debug=True, host='0.0.0.0', port=5000)