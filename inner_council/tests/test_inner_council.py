#!/usr/bin/env python3
"""
Inner Council Test Suite
Comprehensive tests for the Inner Council intelligence system
"""

import sys
import json
import pytest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
import tempfile
import os

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from council import InnerCouncil, CouncilMember
from integrations.ncl_integration import NCLIntegration
from integrations.orchestrator_integration import OrchestratorIntegration
from scripts.daily_monitor import run_daily_monitor
from scripts.report_generator import generate_comprehensive_report
from scripts.maintenance import generate_health_report
from scripts.analytics import analyze_council_activity

class TestInnerCouncil:
    """Test Inner Council core functionality"""

    def setup_method(self):
        """Setup test fixtures"""
        self.council = InnerCouncil()
        self.test_member = CouncilMember(
            name="Test Member",
            channel_id="UC123456789",
            focus_areas=["AI", "Technology"],
            priority="high",
            monitoring_frequency="daily"
        )

    def test_council_initialization(self):
        """Test council initializes correctly"""
        assert self.council is not None
        assert len(self.council.members) > 0
        assert isinstance(self.council.members[0], CouncilMember)

    def test_council_member_creation(self):
        """Test council member creation"""
        assert self.test_member.name == "Test Member"
        assert self.test_member.channel_id == "UC123456789"
        assert "AI" in self.test_member.focus_areas
        assert self.test_member.priority == "high"

    @patch('council.InnerCouncil._get_channel_videos')
    def test_monitor_member(self, mock_get_videos):
        """Test monitoring a council member"""
        # Mock video data
        mock_get_videos.return_value = [
            {
                "video_id": "test123",
                "title": "Test Video",
                "description": "Test description",
                "published_at": datetime.now().isoformat(),
                "transcript": "This is a test transcript about AI technology."
            }
        ]

        result = self.council.monitor_member(self.test_member)

        assert result is not None
        assert "council_member" in result
        assert "content_title" in result
        assert "key_insights" in result

    def test_analyze_content(self):
        """Test content analysis functionality"""
        test_content = {
            "title": "AI Breakthrough in Technology",
            "description": "New AI technology advances",
            "transcript": "Artificial intelligence is revolutionizing technology with new breakthroughs in machine learning."
        }

        analysis = self.council._analyze_content(test_content, self.test_member)

        assert analysis is not None
        assert "key_insights" in analysis
        assert "policy_implications" in analysis
        assert "strategic_recommendations" in analysis

    def test_generate_daily_report(self):
        """Test daily report generation"""
        # Mock insights data
        mock_insights = [
            {
                "council_member": "Test Member",
                "content_title": "Test Content",
                "key_insights": ["Test insight 1", "Test insight 2"],
                "policy_implications": ["Test policy"],
                "strategic_recommendations": ["Test recommendation"]
            }
        ]

        report = self.council.generate_daily_report(mock_insights)

        assert report is not None
        assert "summary" in report
        assert "top_insights" in report["summary"]
        assert "critical_recommendations" in report["summary"]

class TestNCLIntegration:
    """Test NCL integration functionality"""

    def setup_method(self):
        """Setup test fixtures"""
        # Create temporary NCL file
        self.temp_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.ndjson')
        self.temp_file.close()
        self.ncl_integration = NCLIntegration(ncl_file=self.temp_file.name)

    def teardown_method(self):
        """Cleanup test fixtures"""
        os.unlink(self.temp_file.name)

    def test_store_insight(self):
        """Test storing insights in NCL"""
        test_insight = {
            "type": "inner_council_analysis",
            "data": {
                "council_member": "Test Member",
                "content_title": "Test Content",
                "key_insights": ["Test insight"]
            }
        }

        result = self.ncl_integration.store_insight(test_insight)
        assert result is True

        # Verify stored
        insights = self.ncl_integration.query_council_insights()
        assert len(insights) == 1
        assert insights[0]["data"]["council_member"] == "Test Member"

    def test_query_insights(self):
        """Test querying insights"""
        # Store multiple insights
        insights_data = [
            {"type": "inner_council_analysis", "data": {"council_member": "Member1"}},
            {"type": "inner_council_daily_report", "data": {"report_date": "2024-01-01"}},
            {"type": "inner_council_analysis", "data": {"council_member": "Member2"}}
        ]

        for insight in insights_data:
            self.ncl_integration.store_insight(insight)

        # Query all
        all_insights = self.ncl_integration.query_council_insights()
        assert len(all_insights) == 3

        # Query by type
        analysis_insights = self.ncl_integration.query_council_insights(insight_type="inner_council_analysis")
        assert len(analysis_insights) == 2

    def test_get_member_insights(self):
        """Test getting insights for specific member"""
        insights_data = [
            {"type": "inner_council_analysis", "data": {"council_member": "Member1", "content_title": "Content1"}},
            {"type": "inner_council_analysis", "data": {"council_member": "Member2", "content_title": "Content2"}},
            {"type": "inner_council_analysis", "data": {"council_member": "Member1", "content_title": "Content3"}}
        ]

        for insight in insights_data:
            self.ncl_integration.store_insight(insight)

        member_insights = self.ncl_integration.get_council_member_insights("Member1")
        assert len(member_insights) == 2
        assert all(i["data"]["council_member"] == "Member1" for i in member_insights)

class TestOrchestratorIntegration:
    """Test orchestrator integration functionality"""

    def setup_method(self):
        """Setup test fixtures"""
        self.orchestrator = OrchestratorIntegration()

    @patch('integrations.orchestrator_integration.Path')
    def test_generate_proposals(self, mock_path):
        """Test proposal generation"""
        mock_path.return_value.exists.return_value = True

        test_insights = [
            {
                "council_member": "Test Member",
                "key_insights": ["AI breakthrough discovered"],
                "policy_implications": ["Update AI policy"],
                "strategic_recommendations": ["Invest in AI research"]
            }
        ]

        proposals = self.orchestrator.generate_proposals(test_insights)

        assert proposals is not None
        assert len(proposals) > 0
        assert "title" in proposals[0]
        assert "description" in proposals[0]

    def test_assess_actions(self):
        """Test action assessment"""
        test_actions = [
            {"action": "invest_ai", "description": "Invest in AI research"},
            {"action": "update_policy", "description": "Update AI policy"}
        ]

        assessments = self.orchestrator.assess_actions(test_actions)

        assert assessments is not None
        assert len(assessments) == len(test_actions)
        assert "action" in assessments[0]
        assert "priority" in assessments[0]

class TestScripts:
    """Test script functionality"""

    @patch('scripts.daily_monitor.InnerCouncil')
    @patch('scripts.daily_monitor.NCLIntegration')
    @patch('scripts.daily_monitor.OrchestratorIntegration')
    def test_daily_monitor(self, mock_orchestrator, mock_ncl, mock_council):
        """Test daily monitor script"""
        # Setup mocks
        mock_council_instance = Mock()
        mock_council.return_value = mock_council_instance
        mock_council_instance.run_daily_monitor.return_value = {"status": "success"}

        # Run monitor
        result = run_daily_monitor()

        assert result is not None
        mock_council_instance.run_daily_monitor.assert_called_once()

    @patch('scripts.report_generator.NCLIntegration')
    def test_report_generator(self, mock_ncl):
        """Test report generator"""
        # Setup mock
        mock_ncl_instance = Mock()
        mock_ncl.return_value = mock_ncl_instance
        mock_ncl_instance.query_council_insights.return_value = [
            {
                "timestamp": datetime.now().isoformat(),
                "type": "inner_council_analysis",
                "data": {
                    "council_member": "Test Member",
                    "key_insights": ["Test insight"]
                }
            }
        ]

        # Generate report
        report = generate_comprehensive_report(days_back=7)

        assert report is not None
        assert "Inner Council Intelligence Report" in report
        assert "Test Member" in report

    @patch('scripts.maintenance.NCLIntegration')
    def test_maintenance_health_report(self, mock_ncl):
        """Test maintenance health report"""
        # Setup mock
        mock_ncl_instance = Mock()
        mock_ncl.return_value = mock_ncl_instance
        mock_ncl_instance.query_council_insights.return_value = []

        # Generate health report
        report = generate_health_report()

        assert report is not None
        assert "Inner Council Health Report" in report

    @patch('scripts.analytics.NCLIntegration')
    def test_analytics_activity(self, mock_ncl):
        """Test analytics activity analysis"""
        # Setup mock
        mock_ncl_instance = Mock()
        mock_ncl.return_value = mock_ncl_instance
        mock_ncl_instance.query_council_insights.return_value = [
            {
                "timestamp": datetime.now().isoformat(),
                "data": {"council_member": "Test Member"}
            }
        ]

        # Analyze activity
        result = analyze_council_activity(days_back=30)

        assert result is not None
        assert "total_insights" in result
        assert "member_activity" in result

class TestConfiguration:
    """Test configuration loading and validation"""

    def test_config_loading(self):
        """Test loading configuration"""
        config_path = Path(__file__).parent / "config" / "settings.json"

        with open(config_path, 'r') as f:
            config = json.load(f)

        assert "system" in config
        assert "council_members" in config
        assert len(config["council_members"]) > 0
        assert "monitoring" in config
        assert "analysis" in config

    def test_config_validation(self):
        """Test configuration validation"""
        config_path = Path(__file__).parent / "config" / "settings.json"

        with open(config_path, 'r') as f:
            config = json.load(f)

        # Validate required fields
        required_system_fields = ["name", "version", "description"]
        for field in required_system_fields:
            assert field in config["system"]

        # Validate council members structure
        for member in config["council_members"]:
            required_member_fields = ["name", "channel_id", "focus_areas", "priority", "monitoring_frequency"]
            for field in required_member_fields:
                assert field in member

        # Validate monitoring config
        assert "max_videos_per_channel" in config["monitoring"]
        assert "analysis_depth" in config["monitoring"]

class TestIntegration:
    """Test integration between components"""

    def setup_method(self):
        """Setup integration test fixtures"""
        # Create temporary NCL file
        self.temp_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.ndjson')
        self.temp_file.close()
        self.ncl_integration = NCLIntegration(ncl_file=self.temp_file.name)

    def teardown_method(self):
        """Cleanup integration test fixtures"""
        os.unlink(self.temp_file.name)

    @patch('council.InnerCouncil._get_channel_videos')
    def test_full_council_workflow(self, mock_get_videos):
        """Test full council workflow from monitoring to storage"""
        # Setup council
        council = InnerCouncil()

        # Mock video data
        mock_get_videos.return_value = [
            {
                "video_id": "test123",
                "title": "AI Technology Breakthrough",
                "description": "New AI technology",
                "published_at": datetime.now().isoformat(),
                "transcript": "Artificial intelligence technology is advancing rapidly."
            }
        ]

        # Run monitoring
        member = council.members[0]  # Get first member
        analysis_result = council.monitor_member(member)

        # Store in NCL
        self.ncl_integration.store_insight({
            "type": "inner_council_analysis",
            "data": analysis_result
        })

        # Verify storage
        stored_insights = self.ncl_integration.query_council_insights()
        assert len(stored_insights) == 1
        assert stored_insights[0]["data"]["council_member"] == member.name

    def test_council_to_orchestrator_integration(self):
        """Test integration between council and orchestrator"""
        # Create test insights
        test_insights = [
            {
                "council_member": "Test Member",
                "key_insights": ["AI breakthrough"],
                "policy_implications": ["Update AI policy"],
                "strategic_recommendations": ["Invest in AI"]
            }
        ]

        # Generate proposals
        orchestrator = OrchestratorIntegration()
        proposals = orchestrator.generate_proposals(test_insights)

        # Assess actions
        actions = [{"action": "update_policy", "description": "Update AI policy"}]
        assessments = orchestrator.assess_actions(actions)

        assert len(proposals) > 0
        assert len(assessments) > 0
        assert proposals[0]["title"] is not None
        assert assessments[0]["priority"] is not None

if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])