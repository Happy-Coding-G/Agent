"""
Tests for Negotiation Kernel

测试统一协商内核的各种场景。
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
    """测试协商内核"""

    @pytest.fixture
    def mock_db(self):
        """模拟数据库会话"""
        return AsyncMock()

    @pytest.fixture
    def kernel(self, mock_db):
        """创建内核实例"""
        return NegotiationKernel(mock_db)

    @pytest.mark.asyncio
    async def test_create_session_bilateral(self, kernel, mock_db):
        """测试创建双边协商会话"""
        # 模拟数据库返回
        mock_session = Mock()
        mock_session.negotiation_id = "test_session_123"
        mock_session.status = "pending"
        mock_session.version = 1

        with patch.object(kernel, '_create_in_db', return_value=mock_session):
            result = await kernel.create_session(
                mechanism=MechanismType.BILATERAL,
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
    async def test_create_session_auction(self, kernel, mock_db):
        """测试创建拍卖会话"""
        mock_session = Mock()
        mock_session.negotiation_id = "auction_123"
        mock_session.status = "active"
        mock_session.version = 1

        with patch.object(kernel, '_create_in_db', return_value=mock_session):
            result = await kernel.create_session(
                mechanism=MechanismType.AUCTION,
                engine=EngineType.EVENT_SOURCED,
                seller_id=1,
                listing_id="listing_456",
                starting_price=500.0,
                expected_participants=10,
            )

        assert result.success is True
        assert result.session_id == "auction_123"

    @pytest.mark.asyncio
    async def test_get_state_bilateral(self, kernel, mock_db):
        """测试获取双边协商状态"""
        mock_session = Mock()
        mock_session.negotiation_id = "session_123"
        mock_session.status = "active"
        mock_session.version = 5
        mock_session.mechanism_type = "bilateral"
        mock_session.engine_type = "simple"
        mock_session.seller_user_id = 1
        mock_session.buyer_user_id = 2
        mock_session.current_round = 3
        mock_session.current_price = 15000  # 以分为单位

        with patch.object(kernel, '_get_from_db', return_value=mock_session):
            state = await kernel.get_state("session_123")

        assert isinstance(state, SessionState)
        assert state.session_id == "session_123"
        assert state.status == NegotiationStatus.ACTIVE
        assert state.version == 5
        assert state.engine_type == EngineType.SIMPLE
        assert state.current_price == 150.0  # 转换为元

    @pytest.mark.asyncio
    async def test_get_state_not_found(self, kernel, mock_db):
        """测试获取不存在的状态"""
        with patch.object(kernel, '_get_from_db', return_value=None):
            state = await kernel.get_state("non_existent")

        assert state is None

    @pytest.mark.asyncio
    async def test_submit_offer_bilateral(self, kernel, mock_db):
        """测试双边协商提交报价"""
        mock_session = Mock()
        mock_session.negotiation_id = "session_123"
        mock_session.status = "active"
        mock_session.version = 5
        mock_session.mechanism_type = "bilateral"
        mock_session.engine_type = "simple"
        mock_session.seller_user_id = 1
        mock_session.buyer_user_id = 2

        with patch.object(kernel, '_get_from_db', return_value=mock_session):
            with patch.object(kernel._bilateral_engine, 'submit_offer', new_callable=AsyncMock) as mock_submit:
                mock_submit.return_value = OfferResult(
                    success=True,
                    negotiation_id="session_123",
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
    async def test_submit_offer_version_mismatch(self, kernel, mock_db):
        """测试版本不匹配时拒绝"""
        mock_session = Mock()
        mock_session.negotiation_id = "session_123"
        mock_session.status = "active"
        mock_session.version = 5  # 当前版本
        mock_session.mechanism_type = "bilateral"
        mock_session.engine_type = "simple"

        with patch.object(kernel, '_get_from_db', return_value=mock_session):
            result = await kernel.submit_offer(
                session_id="session_123",
                user_id=2,
                price=200.0,
                expected_version=4,  # 期望版本不匹配
            )

        assert isinstance(result, OfferResult)
        assert result.success is False
        assert "version" in result.message.lower() or "concurrent" in result.message.lower()

    @pytest.mark.asyncio
    async def test_submit_offer_session_terminated(self, kernel, mock_db):
        """测试会话已终止时拒绝"""
        mock_session = Mock()
        mock_session.negotiation_id = "session_123"
        mock_session.status = "accepted"  # 已终止
        mock_session.version = 5
        mock_session.mechanism_type = "bilateral"

        with patch.object(kernel, '_get_from_db', return_value=mock_session):
            result = await kernel.submit_offer(
                session_id="session_123",
                user_id=2,
                price=200.0,
            )

        assert isinstance(result, OfferResult)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_submit_bid_auction(self, kernel, mock_db):
        """测试拍卖提交出价"""
        mock_session = Mock()
        mock_session.negotiation_id = "auction_123"
        mock_session.status = "active"
        mock_session.version = 10
        mock_session.mechanism_type = "auction"
        mock_session.engine_type = "event_sourced"

        with patch.object(kernel, '_get_from_db', return_value=mock_session):
            with patch.object(kernel._auction_engine, 'submit_bid', new_callable=AsyncMock) as mock_bid:
                mock_bid.return_value = BidResult(
                    success=True,
                    bid_sequence=5,
                    amount=250.0,
                    is_highest=True,
                    message="Bid accepted",
                )

                result = await kernel.submit_bid(
                    session_id="auction_123",
                    bidder_id=3,
                    amount=250.0,
                )

        assert isinstance(result, BidResult)
        assert result.success is True
        assert result.bid_sequence == 5
        assert result.is_highest is True

    @pytest.mark.asyncio
    async def test_accept_offer(self, kernel, mock_db):
        """测试接受报价"""
        mock_session = Mock()
        mock_session.negotiation_id = "session_123"
        mock_session.status = "active"
        mock_session.version = 5
        mock_session.mechanism_type = "bilateral"
        mock_session.engine_type = "simple"
        mock_session.seller_user_id = 1
        mock_session.buyer_user_id = 2
        mock_session.current_price = 15000

        with patch.object(kernel, '_get_from_db', return_value=mock_session):
            with patch.object(kernel._bilateral_engine, 'accept_offer', new_callable=AsyncMock) as mock_accept:
                mock_accept.return_value = OfferResult(
                    success=True,
                    negotiation_id="session_123",
                    status=NegotiationStatus.ACCEPTED,
                    message="Offer accepted",
                    offer_accepted=True,
                    final_price=150.0,
                )

                result = await kernel.accept_offer(
                    session_id="session_123",
                    user_id=1,
                )

        assert isinstance(result, OfferResult)
        assert result.success is True
        assert result.offer_accepted is True


class TestSessionState:
    """测试会话状态模型"""

    def test_session_state_creation(self):
        """测试创建状态对象"""
        state = SessionState(
            session_id="test_123",
            status=NegotiationStatus.ACTIVE,
            version=1,
            mechanism_type=MechanismType.BILATERAL,
            engine_type=EngineType.SIMPLE,
        )

        assert state.session_id == "test_123"
        assert state.status == NegotiationStatus.ACTIVE
        assert state.version == 1

    def test_session_state_is_active(self):
        """测试活跃状态判断"""
        active_state = SessionState(
            session_id="test_1",
            status=NegotiationStatus.ACTIVE,
        )
        pending_state = SessionState(
            session_id="test_2",
            status=NegotiationStatus.PENDING,
        )
        accepted_state = SessionState(
            session_id="test_3",
            status=NegotiationStatus.ACCEPTED,
        )

        assert active_state.is_active is True
        assert pending_state.is_active is True
        assert accepted_state.is_active is False

    def test_session_state_is_terminal(self):
        """测试终止状态判断"""
        accepted_state = SessionState(
            session_id="test_1",
            status=NegotiationStatus.ACCEPTED,
        )
        rejected_state = SessionState(
            session_id="test_2",
            status=NegotiationStatus.REJECTED,
        )
        active_state = SessionState(
            session_id="test_3",
            status=NegotiationStatus.ACTIVE,
        )

        assert accepted_state.is_terminal is True
        assert rejected_state.is_terminal is True
        assert active_state.is_terminal is False

    def test_session_state_can_accept(self):
        """测试可接受状态判断"""
        active_state = SessionState(
            session_id="test_1",
            status=NegotiationStatus.ACTIVE,
            current_turn="buyer",
        )
        pending_state = SessionState(
            session_id="test_2",
            status=NegotiationStatus.PENDING,
        )
        accepted_state = SessionState(
            session_id="test_3",
            status=NegotiationStatus.ACCEPTED,
        )

        assert active_state.can_accept() is True
        assert pending_state.can_accept() is False
        assert accepted_state.can_accept() is False

    def test_session_state_price_conversion(self):
        """测试价格转换"""
        state = SessionState(
            session_id="test_1",
            status=NegotiationStatus.ACTIVE,
            current_price=15000,  # 以分为单位
        )

        assert state.current_price == 150.0  # 转换为元
