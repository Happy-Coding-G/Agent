"""
Pytest configuration and fixtures

This file is automatically loaded by pytest and provides:
- Test configuration
- Shared fixtures
- Custom markers
"""
import pytest
import sys
from pathlib import Path

# Add backend to Python path for all tests
BACKEND_ROOT = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


# Define custom markers
def pytest_configure(config):
    """Configure custom pytest markers"""
    config.addinivalue_line(
        "markers", "unit: Unit tests (fast, isolated)"
    )
    config.addinivalue_line(
        "markers", "integration: Integration tests (may require database)"
    )
    config.addinivalue_line(
        "markers", "slow: Slow tests (skip in fast mode)"
    )
    config.addinivalue_line(
        "markers", "agents: Agent-related tests"
    )
    config.addinivalue_line(
        "markers", "trade: Trade-related tests"
    )


# Shared fixtures
@pytest.fixture
def sample_trade_state():
    """Provide a sample TradeState for testing"""
    from datetime import datetime
    return {
        "action": "listing",
        "space_public_id": "test-space-123",
        "asset_id": "test-asset-456",
        "user_id": 1,
        "user_role": "seller",
        "success": True,
        "started_at": datetime.utcnow(),
        "result": {},
    }


@pytest.fixture
def mock_db_session():
    """Provide a mock database session"""
    from unittest.mock import AsyncMock, MagicMock

    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()

    return session
