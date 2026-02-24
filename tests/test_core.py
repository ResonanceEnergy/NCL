# tests/test_core.py
"""
Tests for NCL Core Components
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock

from src.ncl.core.memory_system import MemorySystem, MemoryRecord
from src.ncl.core.digital_twin import DigitalTwin
from src.ncl.core.decision_engine import DecisionEngine
from src.ncl.core.ncc import NCC


class TestMemorySystem:
    """Test Memory System functionality"""

    @pytest.fixture
    async def memory_system(self):
        """Create a test memory system"""
        system = MemorySystem(storage_path="test_data/memory")
        await system.initialize()
        yield system
        # Cleanup
        await system.shutdown()

    @pytest.mark.asyncio
    async def test_store_and_retrieve(self, memory_system):
        """Test basic store and retrieve operations"""
        test_data = {"key": "value", "number": 42}

        # Store data
        success = await memory_system.store("test_key", test_data)
        assert success

        # Retrieve data
        retrieved = await memory_system.retrieve("test_key")
        assert retrieved == test_data

    @pytest.mark.asyncio
    async def test_ttl_expiration(self, memory_system):
        """Test TTL functionality"""
        test_data = {"temp": "data"}

        # Store with short TTL
        ttl = timedelta(seconds=1)
        success = await memory_system.store("temp_key", test_data, ttl=ttl)
        assert success

        # Should retrieve immediately
        retrieved = await memory_system.retrieve("temp_key")
        assert retrieved == test_data

        # Wait for expiration
        await asyncio.sleep(1.1)

        # Should be expired
        retrieved = await memory_system.retrieve("temp_key")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_search(self, memory_system):
        """Test search functionality"""
        # Store test data
        await memory_system.store("user_1", {"name": "Alice", "role": "admin"})
        await memory_system.store("user_2", {"name": "Bob", "role": "user"})
        await memory_system.store("config", {"setting": "value"})

        # Search for "Alice"
        results = await memory_system.search("Alice")
        assert len(results) == 1
        assert results[0]["data"]["name"] == "Alice"

        # Search for "user"
        results = await memory_system.search("user")
        assert len(results) == 2


class TestDigitalTwin:
    """Test Digital Twin functionality"""

    @pytest.fixture
    async def digital_twin(self):
        """Create a test digital twin"""
        memory_system = MemorySystem(storage_path="test_data/memory")
        await memory_system.initialize()

        twin = DigitalTwin(memory_system)
        await twin.initialize()
        yield twin
        await twin.shutdown()
        await memory_system.shutdown()

    @pytest.mark.asyncio
    async def test_initialization(self, digital_twin):
        """Test digital twin initialization"""
        status = await digital_twin.get_twin_status()
        assert status.overall_health >= 0
        assert status.total_components == 7  # 7 doctrine domains

    @pytest.mark.asyncio
    async def test_insight_gathering(self, digital_twin):
        """Test insight gathering"""
        insights = await digital_twin.gather_insights()
        assert "insights" in insights
        assert isinstance(insights["insights"], list)


class TestDecisionEngine:
    """Test Decision Engine functionality"""

    @pytest.fixture
    async def decision_engine(self):
        """Create a test decision engine"""
        memory_system = MemorySystem(storage_path="test_data/memory")
        await memory_system.initialize()

        digital_twin = DigitalTwin(memory_system)
        await digital_twin.initialize()

        engine = DecisionEngine(digital_twin, memory_system)
        await engine.initialize()
        yield engine
        await engine.shutdown()
        await digital_twin.shutdown()
        await memory_system.shutdown()

    @pytest.mark.asyncio
    async def test_process_insight(self, decision_engine):
        """Test insight processing"""
        insight = {
            "type": "component_health",
            "component": "HHP",
            "severity": "warning",
            "message": "Health component degraded"
        }

        decision = await decision_engine.process_insight(insight)

        # Should generate a decision for warning severity
        assert decision is not None
        assert decision.type.value == "operational"
        assert decision.priority.value == "medium"

    @pytest.mark.asyncio
    async def test_critical_decision(self, decision_engine):
        """Test critical decision generation"""
        insight = {
            "type": "security_threat",
            "severity": "critical",
            "threat_type": "intrusion",
            "description": "Unauthorized access detected"
        }

        decision = await decision_engine.process_insight(insight)

        assert decision is not None
        assert decision.type.value == "emergency"
        assert decision.priority.value == "critical"


class TestNCC:
    """Test NCC functionality"""

    @pytest.fixture
    async def ncc(self):
        """Create a test NCC instance"""
        ncc = NCC(config_path="test_config/ncc_config.json")
        initialized = await ncc.initialize()
        assert initialized
        yield ncc
        await ncc.emergency_shutdown()

    @pytest.mark.asyncio
    async def test_initialization(self, ncc):
        """Test NCC initialization"""
        status = await ncc.get_status()
        assert status.state.value == "operational"
        assert status.system_health == 100.0

    @pytest.mark.asyncio
    async def test_orchestration_cycle(self, ncc):
        """Test orchestration cycle execution"""
        results = await ncc.orchestrate_cycle()

        # Should return cycle results
        assert isinstance(results, dict)
        assert "cycle_duration" in results
        assert "intelligence_gathered" in results
        assert "decisions_made" in results


if __name__ == "__main__":
    # Run basic functionality test
    async def main():
        print("🧪 Running NCL Core Tests...")

        # Test Memory System
        print("Testing Memory System...")
        memory = MemorySystem(storage_path="test_data/memory")
        await memory.initialize()

        test_data = {"test": "data", "timestamp": datetime.now().isoformat()}
        success = await memory.store("test_key", test_data)
        retrieved = await memory.retrieve("test_key")

        assert success and retrieved == test_data
        print("✅ Memory System test passed")

        # Test Digital Twin
        print("Testing Digital Twin...")
        twin = DigitalTwin(memory)
        await twin.initialize()

        status = await twin.get_twin_status()
        assert status.total_components == 7
        print("✅ Digital Twin test passed")

        # Cleanup
        await twin.shutdown()
        await memory.shutdown()

        print("🎉 All core tests passed!")

    asyncio.run(main())
