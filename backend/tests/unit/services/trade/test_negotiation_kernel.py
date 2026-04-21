"""
Tests for Negotiation Kernel (Direct Trade Mode)

协商内核已简化为仅支持直接交易模式。
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch
from decimal import Decimal

from app.services.trade.negotiation_kernel import (
    NegotiationKernel,
    SessionState,
    NegotiationStatus,
    MechanismType,
    EngineType,
)
from app.services.trade.result_types import (
    NegotiationResult,
    OfferResult,
    BidResult,
)


class TestNegotiationKernel:
    """测试协商内核——直接交易模式"""

    @pytest.fixture
    def mock_db(self):
        """模拟数据库会话"""
        return AsyncMock()

    @pytest.fixture
    def kernel(self, mock_db):
        """创建内核实例"""
        return NegotiationKernel(mock_db)

    @pytest.mark.asyncio
    async def test_create_session_direct(self, kernel, mock_db):
        """测试创建直接交易会话"""
        mock_session = Mock()
        mock_session.negotiation_id = "test_session_123"
        mock_session.status = "pending"
        mock_session.version = 1

        with patch.object(kernel, '_create_in_db', return_value=mock_session):
            result = await kernel.create_session(
                mechanism=MechanismType.DIRECT,
                engine=EngineType.SIMPLE,
                seller_id=1,
                listing_id="listing_123",
                buyer_id=2,
                starting_price=1000.0,
                reserve_price=800.0,
            )

        assert isinstance(result, NegotiationResult)
        assert result.success is True
        assert result.session_id == "test_session_123"

    @pytest.mark.asyncio
    async def test_get_state_direct(self, kernel, mock_db):
        """测试获取直接交易状态"""
        mock_session = Mock()
        mock_session.negotiation_id = "session_123"
        mock_session.status = "active"
        mock_session.version = 5
        mock_session.mechanism_type = "direct"
        mock_session.engine_type = "simple"
        mock_session.seller_user_id = 1
        mock_session.buyer_user_id = 2
        mock_session.current_round = 3
        mock_session.current_price = 15000  # 以分为单位
        mock_session.shared_board = {}

        with patch.object(kernel, '_get_session', return_value=mock_session):
            state = await kernel.get_state("session_123")

        assert isinstance(state, SessionState)
        assert state.session_id == "session_123"
        assert state.status == NegotiationStatus.ACTIVE
        assert state.version == 5
        assert state.engine_type == "simple"
        assert state.current_price == 150.0  # 转换为元

    @pytest.mark.asyncio
    async def test_get_state_not_found(self, kernel, mock_db):
        """测试获取不存在的状态"""
        with patch.object(kernel, '_get_session', return_value=None):
            state = await kernel.get_state("non_existent")

        assert state is None

    @pytest.mark.asyncio
    async def test_submit_offer_direct(self, kernel, mock_db):
        """测试直接交易提交报价"""
        mock_session = Mock()
        mock_session.negotiation_id = "session_123"
        mock_session.status = "active"
        mock_session.version = 5
        mock_session.mechanism_type = "direct"
        mock_session.engine_type = "simple"
        mock_session.seller_user_id = 1
        mock_session.buyer_user_id = 2

        with patch.object(kernel, '_get_session', return_value=mock_session):
            with patch.object(kernel._bilateral, 'submit_offer', new_callable=AsyncMock) as mock_submit:
                mock_submit.return_value = OfferResult(
                    success=True,
                    session_id="session_123",
                    status=NegotiationStatus.ACTIVE,
                    message="Offer submitted",
                    new_price=200.0,
                )

                result = await kernel.submit_offer(
                    session_id="session_123",
                    user_id=2,
                    price=200.0,
                    message="Test offer",
                )

        assert isinstance(result, OfferResult)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_submit_offer_session_not_active(self, kernel, mock_db):
        """测试会话非活跃时拒绝"""
        mock_session = Mock()
        mock_session.negotiation_id = "session_123"
        mock_session.status = "accepted"  # 已终止
        mock_session.version = 5
        mock_session.mechanism_type = "direct"

        with patch.object(kernel, '_get_session', return_value=mock_session):
            result = await kernel.submit_offer(
                session_id="session_123",
                user_id=2,
                price=200.0,
            )

        assert isinstance(result, OfferResult)
        assert result.success is False


class TestSessionState:
    """测试会话状态模型"""

    def test_session_state_creation(self):
        """测试创建状态对象"""
        state = SessionState(
            session_id="test_123",
            status=NegotiationStatus.ACTIVE,
            seller_id=1,
            mechanism=MechanismType.DIRECT,
            engine=EngineType.SIMPLE,
        )

        assert state.session_id == "test_123"
        assert state.status == NegotiationStatus.ACTIVE
        assert state.mechanism == MechanismType.DIRECT
        assert state.engine == EngineType.SIMPLE

    def test_session_state_to_dict(self):
        """测试状态序列化"""
        state = SessionState(
            session_id="test_123",
            status=NegotiationStatus.ACTIVE,
            seller_id=1,
            mechanism=MechanismType.DIRECT,
            engine=EngineType.SIMPLE,
            current_price=150.0,
        )

        data = state.to_dict()
        assert data["session_id"] == "test_123"
        assert data["mechanism"] == "direct"
        assert data["engine"] == "simple"
        assert data["current_price"] == 150.0
