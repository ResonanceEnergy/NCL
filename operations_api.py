#!/usr/bin/env python3
"""
Operations API Server
REST API for programmatic access to Super Agency operations
"""

from quart import Quart, request, jsonify
import asyncio
import json
import sys
import os
from datetime import datetime

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'agents'))

# from operations_command_interface import handle_operations_query  # Move inside function

app = Quart(__name__)

@app.route('/api/v1/operations/query', methods=['POST'])
async def operations_query():
    """
    POST /api/v1/operations/query
    Body: {"query": "your natural language query", "user_context": {...}}
    """
    try:
        data = await request.get_json()

        if not data or 'query' not in data:
            return jsonify({
                "error": "Missing 'query' field in request body",
                "example": {
                    "query": "How is NCC doing today?",
                    "user_context": {"role": "executive", "clearance_level": "supreme_command"}
                }
            }), 400

        query = data['query']
        user_context = data.get('user_context', {})

        # Import here to avoid issues
        from operations_command_interface import handle_operations_query
        import asyncio

        # Process the query
        result = await handle_operations_query(query, user_context)

        # Debug: print result type and content
        print(f"Result type: {type(result)}")
        print(f"Result: {result}")

        # Add API metadata
        result['api_version'] = 'v1'
        result['processed_at'] = datetime.now().isoformat()
        result['query'] = query

        return jsonify(result)

    except Exception as e:
        return jsonify({
            "error": f"Internal server error: {str(e)}",
            "timestamp": datetime.now().isoformat()
        }), 500

@app.route('/api/v1/operations/departments', methods=['GET'])
async def list_departments():
    """GET /api/v1/operations/departments - List all available departments"""
    try:
        # Import OCI to access departments
        from operations_command_interface import oci

        departments = {}
        for key, dept in oci.departments.items():
            departments[key] = {
                "name": dept["name"],
                "head": dept["head"],
                "capabilities": dept["capabilities"],
                "portfolio_company": dept.get("portfolio_company", False)
            }

        return jsonify({
            "departments": departments,
            "total_count": len(departments),
            "core_departments": len([d for d in departments.values() if not d.get("portfolio_company", False)]),
            "portfolio_companies": len([d for d in departments.values() if d.get("portfolio_company", False)])
        })

    except Exception as e:
        return jsonify({
            "error": f"Failed to retrieve departments: {str(e)}"
        }), 500

@app.route('/api/v1/health', methods=['GET'])
async def health_check():
    """GET /api/v1/health - API health check"""
    return jsonify({
        "status": "healthy",
        "service": "Super Agency Operations API",
        "version": "v1",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/v1/operations/status', methods=['GET'])
async def system_status():
    """GET /api/v1/operations/status - Overall system status"""
    try:
        from operations_command_interface import oci

        # Get basic system metrics
        portfolio = json.loads(open('portfolio.json').read())
        total_companies = len(portfolio.get('repositories', []))

        return jsonify({
            "system_status": "operational",
            "total_departments": len(oci.departments),
            "portfolio_companies": total_companies,
            "oci_queries_processed": len(oci.conversation_history),
            "timestamp": datetime.now().isoformat()
        })

    except Exception as e:
        return jsonify({
            "system_status": "degraded",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "error": "Endpoint not found",
        "available_endpoints": [
            "/api/v1/operations/query (POST)",
            "/api/v1/operations/departments (GET)",
            "/api/v1/operations/status (GET)",
            "/api/v1/health (GET)"
        ]
    }), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        "error": "Internal server error",
        "message": "Please try again later"
    }), 500

if __name__ == '__main__':
    print("🚀 Starting Super Agency Operations API Server...")
    print("📡 Available endpoints:")
    print("   POST /api/v1/operations/query     - Process operational queries")
    print("   GET  /api/v1/operations/departments - List all departments")
    print("   GET  /api/v1/operations/status    - System status")
    print("   GET  /api/v1/health               - Health check")
    print("\n🌐 Server running on http://localhost:5001")

    # Run with Quart (async Flask)
    app.run(host='localhost', port=5001, debug=False)
