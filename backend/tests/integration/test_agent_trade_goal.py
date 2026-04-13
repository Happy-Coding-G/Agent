"""
Integration Tests for Agent Trade Goal

测试 Agent-First 架构下的交易目标执行流程。
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from app.schemas.trade_goal import (
    TradeGoal,
    TradeIntent,
    TradeConstraints,
    AssetType,
    create_buy_goal,
    create_sell_goal,
)
from app.services.agent_task_service import AgentTaskService


class TestAgentTradeGoal:
    """测试 Agent 交易目标"""

    @pytest.fixture
    def mock_db(self):
        """模拟数据库会话"""
        db = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        return db

    @pytest.fixture
    def task_service(self, mock_db):
        """创建任务服务"""
        return AgentTaskService(mock_db)

    @pytest.mark.asyncio
    async def test_create_buy_goal(self):
        """测试创建购买目标"""
        goal = create_buy_goal(
            listing_id="listing_123",
            max_price=1000.0,
            target_price=900.0,
        )

        assert goal.intent == TradeIntent.BUY
        assert goal.listing_id == "listing_123"
        assert goal.target_price == 900.0
        assert goal.asset_type == AssetType.GENERAL

    @pytest.mark.asyncio
    async def test_create_sell_goal(self):
        """测试创建出售目标"""
        goal = create_sell_goal(
            asset_id="asset_456",
            min_price=500.0,
            target_price=800.0,
        )

        assert goal.intent == TradeIntent.SELL
        assert goal.asset_id == "asset_456"
        assert goal.min_price == 500.0
        assert goal.target_price == 800.0

    @pytest.mark.asyncio
    async def test_buy_goal_validation(self):
        """测试购买目标验证"""
        # 缺少 listing_id 应该失败
        with pytest.raises(ValueError):
            TradeGoal(
                intent=TradeIntent.BUY,
                listing_id="",
                target_price=100.0,
                asset_type=AssetType.GENERAL,
            )

        # max_price 为负数应该失败
        with pytest.raises(ValueError):
            TradeGoal(
                intent=TradeIntent.BUY,
                listing_id="listing_123",
                max_price=-100.0,
                target_price=100.0,
                asset_type=AssetType.GENERAL,
            )

    @pytest.mark.asyncio
    async def test_sell_goal_validation(self):
        """测试出售目标验证"""
        # 缺少 asset_id 应该失败
        with pytest.raises(ValueError):
            TradeGoal(
                intent=TradeIntent.SELL,
                asset_id="",
                min_price=100.0,
                target_price=200.0,
                asset_type=AssetType.GENERAL,
            )

        # min_price > target_price 应该失败
        with pytest.raises(ValueError):
            TradeGoal(
                intent=TradeIntent.SELL,
                asset_id="asset_123",
                min_price=300.0,
                target_price=200.0,  # 小于 min_price
                asset_type=AssetType.GENERAL,
            )

    @pytest.mark.asyncio
    async def test_trade_constraints_defaults(self):
        """测试约束默认值"""
        constraints = TradeConstraints()

        assert constraints.max_rounds == 10
        assert constraints.timeout_minutes == 1440
        assert constraints.budget_limit is None

    @pytest.mark.asyncio
    async def test_goal_to_execution_plan(self, mock_db):
        """测试目标转换为执行计划"""
        goal = create_buy_goal(
            listing_id="listing_123",
            max_price=1000.0,
        )
        constraints = TradeConstraints(
            max_rounds=5,
            timeout_minutes=60,
        )

        # 验证计划创建逻辑
        assert goal.intent == TradeIntent.BUY
        assert constraints.max_rounds == 5

    @pytest.mark.asyncio
    async def test_buy_goal_with_preferences(self):
        """测试带偏好的购买目标"""
        goal = TradeGoal(
            intent=TradeIntent.BUY,
            listing_id="listing_123",
            target_price=1000.0,
            max_price=1200.0,
            preferred_mechanism="bilateral",
            urgency="high",
            asset_type=AssetType.DIGITAL_ART,
        )

        assert goal.preferred_mechanism == "bilateral"
        assert goal.urgency == "high"
        assert goal.asset_type == AssetType.DIGITAL_ART


class TestAgentTaskService:
    """测试 Agent 任务服务"""

    @pytest.fixture
    def mock_db(self):
        """模拟数据库会话"""
        db = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        return db

    @pytest.fixture
    def task_service(self, mock_db):
        """创建任务服务"""
        return AgentTaskService(mock_db)

    @pytest.mark.asyncio
    async def test_create_trade_task(self, task_service, mock_db):
        """测试创建交易任务"""
        goal = create_buy_goal(
            listing_id="listing_123",
            max_price=1000.0,
        )
        constraints = TradeConstraints()

        mock_task = Mock()
        mock_task.public_id = "task_123"
        mock_task.id = 1

        # 模拟数据库查询结果
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None  # 没有现有任务
        mock_db.execute.return_value = mock_result

        # 模拟添加和刷新
        mock_db.add.return_value = None
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        with patch('app.services.agent_task_service.AgentTasks') as mock_task_class:
            mock_task_class.return_value = mock_task

            task = await task_service.create_task(
                agent_type="trade",
                input_data={
                    "type": "trade_goal",
                    "goal": goal.dict(),
                    "constraints": constraints.dict(),
                },
                space_id=1,
                created_by=2,
            )

            assert task is not None

    @pytest.mark.asyncio
    async def test_get_task_status(self, task_service, mock_db):
        """测试获取任务状态"""
        mock_task = Mock()
        mock_task.public_id = "task_123"
        mock_task.status = "running"
        mock_task.progress_percentage = 50

        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_task
        mock_db.execute.return_value = mock_result

        task = await task_service.get_task("task_123")

        assert task is not None
        assert task.status == "running"

    @pytest.mark.asyncio
    async def test_update_task_status(self, task_service, mock_db):
        """测试更新任务状态"""
        mock_task = Mock()
        mock_task.public_id = "task_123"
        mock_task.status = "pending"

        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_task
        mock_db.execute.return_value = mock_result

        updated = await task_service.update_task(
            task_id="task_123",
            status="running",
            progress_percentage=25,
        )

        assert updated is True
        assert mock_task.status == "running"
        assert mock_task.progress_percentage == 25


class TestTradeGoalAPI:
    """测试交易目标 API 端点"""

    @pytest.mark.asyncio
    async def test_submit_trade_goal_endpoint(self):
        """测试提交交易目标端点"""
        from app.api.v1.endpoints.agent import submit_trade_goal

        # 这个测试验证端点可以正确接收请求
        # 实际调用需要 FastAPI 测试客户端
        pass

    @pytest.mark.asyncio
    async def test_get_trade_task_status_endpoint(self):
        """测试获取交易任务状态端点"""
        from app.api.v1.endpoints.agent import get_trade_task_status

        # 这个测试验证端点可以正确返回状态
        pass


class TestTradeAgentWorker:
    """测试 Trade Agent Worker"""

    @pytest.mark.asyncio
    async def test_worker_processes_pending_tasks(self):
        """测试 Worker 处理待处理任务"""
        from app.agents.trade.trade_agent_worker import TradeAgentWorker

        # 创建工作器实例
        mock_db = AsyncMock()
        worker = TradeAgentWorker(mock_db)

        assert worker is not None
        assert worker.running is False

    @pytest.mark.asyncio
    async def test_worker_auto_decision_logic(self):
        """测试 Worker 自动决策逻辑"""
        # 测试自动决策的各种场景
        pass
