#!/usr/bin/env python3
"""
NCL System Health Check
Comprehensive diagnostic tool for NUREALCORTEXLINK system components.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests


class NCLHealthChecker:
    def __init__(self, config_path="ncl_config.json"):
        self.config = self.load_config(config_path)
        self.results = {}

    def load_config(self, config_path):
        """Load system configuration"""
        try:
            with open(config_path) as f:
                return json.load(f)
        except (FileNotFoundError, PermissionError, json.JSONDecodeError):
            print(f"Warning: Config file {config_path} not found, using defaults")
            return {
                "network": {"relay_port": 8787, "onedrop_port": 8123},
                "paths": {"root": "~/NCL"}
            }

    def check_python_dependencies(self):
        """Check required Python packages"""
        required = ['jsonschema', 'referencing', 'pytest', 'fastapi', 'uvicorn']
        missing = []

        for pkg in required:
            try:
                __import__(pkg)
            except ImportError:
                missing.append(pkg)

        self.results['python_deps'] = {
            'status': 'PASS' if not missing else 'FAIL',
            'missing': missing
        }
        return not missing

    def check_directory_structure(self):
        """Check required directory structure"""
        required_dirs = [
            'data/event_log',
            'data/quarantine',
            'data/derived',
            'ncl_agency_runtime/agents',
            'ncl_agency_runtime/missions',
            'policies',
            'dist',
            'audit',
            'workspaces',
            '_config',
        ]

        missing_dirs = []
        for dir_path in required_dirs:
            if not os.path.exists(dir_path):
                missing_dirs.append(dir_path)

        self.results['directory_structure'] = {
            'status': 'PASS' if not missing_dirs else 'WARN',
            'missing': missing_dirs
        }
        return len(missing_dirs) == 0

    def check_schemas(self):
        """Check schema catalog and files"""
        schema_index = "schemas/ncl.iphone.v1/index.json"
        if not os.path.exists(schema_index):
            self.results['schemas'] = {'status': 'FAIL', 'error': 'Schema index not found'}
            return False

        try:
            with open(schema_index) as f:
                catalog = json.load(f)

            schema_count = len(catalog.get('schemas', {}))
            self.results['schemas'] = {
                'status': 'PASS',
                'count': schema_count
            }
            return True
        except Exception as e:
            self.results['schemas'] = {'status': 'FAIL', 'error': str(e)}
            return False

    def check_golden_tasks(self):
        """Check golden task evaluation system"""
        task_dir = "evaluation/golden_tasks"
        if not os.path.exists(task_dir):
            self.results['golden_tasks'] = {'status': 'FAIL', 'error': 'Golden tasks directory not found'}
            return False

        task_files = list(Path(task_dir).glob("golden_*.json"))
        self.results['golden_tasks'] = {
            'status': 'PASS',
            'count': len(task_files)
        }
        return len(task_files) > 0

    def check_api_endpoints(self):
        """Check API endpoints"""
        endpoints = {
            'relay_server': f"http://localhost:{self.config.get('network', {}).get('relay_port', 8787)}/health",
            'onedrop_api': f"http://localhost:{self.config.get('network', {}).get('onedrop_port', 8123)}/health"
        }

        results = {}
        for name, url in endpoints.items():
            try:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    results[name] = {'status': 'PASS', 'response': response.json()}
                else:
                    results[name] = {'status': 'FAIL', 'code': response.status_code}
            except Exception as e:
                results[name] = {'status': 'DOWN', 'error': str(e)}

        self.results['api_endpoints'] = results
        return all(r['status'] == 'PASS' for r in results.values())

    def check_shortcuts_pack(self):
        """Check shortcuts pack integrity"""
        manifest_path = "shortcuts_pack/v1/manifest.json"
        if not os.path.exists(manifest_path):
            self.results['shortcuts'] = {'status': 'FAIL', 'error': 'Manifest not found'}
            return False

        try:
            with open(manifest_path) as f:
                manifest = json.load(f)

            shortcut_count = len(manifest.get('shortcuts', []))
            self.results['shortcuts'] = {
                'status': 'PASS',
                'count': shortcut_count
            }
            return True
        except Exception as e:
            self.results['shortcuts'] = {'status': 'FAIL', 'error': str(e)}
            return False

    def run_tests(self):
        """Run test suite"""
        try:
            result = subprocess.run([sys.executable, '-m', 'pytest', 'tests/', '-q', '--tb=no'],
                                  capture_output=True, text=True, timeout=30)

            # Check if pytest ran successfully
            if result.returncode == 0:
                # Parse output for test counts
                output = result.stdout + result.stderr
                lines = output.split('\n')
                for line in lines:
                    if 'passed' in line and 'failed' in line:
                        parts = line.split()
                        passed = int(parts[0]) if parts[0].isdigit() else 0
                        failed = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0

                        self.results['tests'] = {
                            'status': 'PASS' if failed == 0 else 'FAIL',
                            'passed': passed,
                            'failed': failed
                        }
                        return failed == 0

                # If we can't parse, but return code is 0, assume pass
                self.results['tests'] = {'status': 'PASS', 'output': 'Tests completed successfully'}
                return True
            else:
                self.results['tests'] = {'status': 'FAIL', 'return_code': result.returncode, 'output': result.stdout + result.stderr}
                return False

        except subprocess.TimeoutExpired:
            self.results['tests'] = {'status': 'TIMEOUT'}
            return False
        except Exception as e:
            self.results['tests'] = {'status': 'ERROR', 'error': str(e)}
            return False

    def check_agency_runtime(self):
        """Check agency runtime components"""
        runtime_files = [
            "ncl_agency_runtime/runtime/relay_server.py",
            "ncl_agency_runtime/runtime/mission_runner.py",
            "ncl_agency_runtime/runtime/lib_ncl.py"
        ]

        missing = [f for f in runtime_files if not os.path.exists(f)]
        self.results['agency_runtime'] = {
            'status': 'PASS' if not missing else 'FAIL',
            'missing': missing
        }
        return len(missing) == 0

    def check_onedrop_setup(self):
        """Check One-Drop setup components"""
        onedrop_files = [
            "ncl_onedrop_setup/onedrop_setup.py",
            "ncl_onedrop_setup/backend/api/main.py",
            "ncl_onedrop_setup/docs/product/roadmap_100_steps.md"
        ]

        missing = [f for f in onedrop_files if not os.path.exists(f)]
        self.results['onedrop_setup'] = {
            'status': 'PASS' if not missing else 'FAIL',
            'missing': missing
        }
        return len(missing) == 0

    def check_icm_workspaces(self):
        """Check ICM workspace structure (Interpretable Context Methodology)"""
        workspaces = {
            'mission-ops': ['01-intake', '02-dispatch', '03-execute', '04-report'],
            'data-pipeline': ['01-capture', '02-validate', '03-process', '04-synthesize'],
            'agent-dev': ['01-design', '02-implement', '03-test', '04-harden'],
            'daily-ops': ['01-collect', '02-analyze', '03-brief', '04-action'],
        }

        missing = []
        for ws_name, stages in workspaces.items():
            ws_ctx = f"workspaces/{ws_name}/CONTEXT.md"
            if not os.path.exists(ws_ctx):
                missing.append(ws_ctx)
            for stage in stages:
                stage_ctx = f"workspaces/{ws_name}/stages/{stage}/CONTEXT.md"
                stage_out = f"workspaces/{ws_name}/stages/{stage}/output"
                if not os.path.exists(stage_ctx):
                    missing.append(stage_ctx)
                if not os.path.isdir(stage_out):
                    missing.append(stage_out)

        # Check root ICM files
        for root_file in ['CLAUDE.md', 'CONTEXT.md', '_config/CONVENTIONS.md']:
            if not os.path.exists(root_file):
                missing.append(root_file)

        self.results['icm_workspaces'] = {
            'status': 'PASS' if not missing else 'WARN',
            'missing': missing,
            'workspace_count': len(workspaces),
        }
        return len(missing) == 0

    def run_all_checks(self):
        """Run all health checks"""
        print("🔍 NCL System Health Check")
        print("=" * 50)

        checks = [
            ("Python Dependencies", self.check_python_dependencies),
            ("Directory Structure", self.check_directory_structure),
            ("Schema Catalog", self.check_schemas),
            ("Golden Tasks", self.check_golden_tasks),
            ("API Endpoints", self.check_api_endpoints),
            ("Shortcuts Pack", self.check_shortcuts_pack),
            ("Test Suite", self.run_tests),
            ("Agency Runtime", self.check_agency_runtime),
            ("One-Drop Setup", self.check_onedrop_setup),
            ("ICM Workspaces", self.check_icm_workspaces)
        ]

        all_pass = True
        for name, check_func in checks:
            print(f"Checking {name}...", end=" ")
            try:
                result = check_func()
                status = "✅ PASS" if result else "❌ FAIL"
                print(status)
                if not result:
                    all_pass = False
            except Exception as e:
                print(f"❌ ERROR: {e}")
                all_pass = False

        return all_pass

    def generate_report(self):
        """Generate detailed health report"""
        report = ["# NCL System Health Report", ""]
        report.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")

        for component, result in self.results.items():
            report.append(f"## {component.replace('_', ' ').title()}")
            if isinstance(result, dict) and 'status' in result:
                report.append(f"Status: {result['status']}")

                if 'error' in result:
                    report.append(f"Error: {result['error']}")
                elif 'missing' in result:
                    report.append(f"Missing: {', '.join(result['missing'])}")
                elif 'count' in result:
                    report.append(f"Count: {result['count']}")
            else:
                report.append(f"Result: {result}")
            report.append("")

        return "\n".join(report)

def main():
    checker = NCLHealthChecker()

    if checker.run_all_checks():
        print("\n🎉 All checks passed! NCL system is healthy.")
        sys.exit(0)
    else:
        print("\n⚠️  Some checks failed. See detailed report below:")
        print(checker.generate_report())
        sys.exit(1)

if __name__ == "__main__":
    main()
