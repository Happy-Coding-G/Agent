"""
Tests for TradeAgent graph binding.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.subagents.trade.agent import TradeAgent


class TestTradeAgent:
    @pytest.mark.asyncio
    async def test_trade_agent_uses_agent_first_graph(self):
        mock_db = AsyncMock()
        with patch(
            "app.agents.subagents.trade.agent.create_agent_first_trade_graph"
        ) as mock_create_graph, patch.object(
            TradeAgent, "_init_skills", return_value={"pricing": AsyncMock()}
        ):
            mock_graph = AsyncMock()
            mock_create_graph.return_value = mock_graph

            agent = TradeAgent(mock_db)

            mock_create_graph.assert_called_once_with(mock_db, agent.skills)
            assert agent.graph == mock_graph

    @pytest.mark.asyncio
    async def test_execute_trade_goal_passes_session_id(self):
        """回归测试：execute_trade_goal 接收并透传 session_id。"""
        mock_db = AsyncMock()
        with patch(
            "app.agents.subagents.trade.agent.create_agent_first_trade_graph"
        ) as mock_create_graph, patch.object(
            TradeAgent, "_init_skills", return_value={"pricing": AsyncMock()}
        ), patch.object(
            TradeAgent, "_sync_trade_memory", new=AsyncMock()
        ):
            mock_graph = AsyncMock()
            mock_graph.ainvoke = AsyncMock(return_value={
                "success": True,
                "result": {"deal": "done"},
                "calculated_price": 100.0,
                "session_id": "sess_trade_1",
                "mechanism_selection": {
                    "mechanism_type": "bilateral",
                    "engine_type": "simple",
                    "selection_reason": "test",
                    "expected_participants": 2,
                    "requires_approval": False,
                },
            })
            mock_create_graph.return_value = mock_graph

            agent = TradeAgent(mock_db)

            from app.schemas.trade_goal import TradeGoal, TradeConstraints, TradeIntent, AutonomyMode
            goal = TradeGoal(intent=TradeIntent.SELL_ASSET, asset_id="asset_1")
            constraints = TradeConstraints(autonomy_mode=AutonomyMode.NOTIFY_BEFORE_ACTION)
            user = MagicMock(id=1)

            plan = await agent.execute_trade_goal(
                goal=goal,
                constraints=constraints,
                user=user,
                space_public_id="space_1",
                session_id="sess_trade_1",
            )

            call_state = mock_graph.ainvoke.call_args[0][0]
            assert call_state["session_id"] == "sess_trade_1"
            assert plan.session_id == "sess_trade_1"

    @pytest.mark.asyncio
    async def test_run_passes_session_id_and_syncs_memory(self):
        """回归测试：run() 透传 session_id 并同步记忆。"""
        mock_db = AsyncMock()
        with patch(
            "app.agents.subagents.trade.agent.create_agent_first_trade_graph"
        ) as mock_create_graph, patch.object(
            TradeAgent, "_init_skills", return_value={"pricing": AsyncMock()}
        ), patch.object(
            TradeAgent, "_sync_trade_memory", new=AsyncMock()
        ):
            mock_graph = AsyncMock()
            mock_graph.ainvoke = AsyncMock(return_value={
                "success": True,
                "result": {"offer": 99},
                "calculated_price": 99.0,
                "selected_mechanism": "bilateral",
            })
            mock_create_graph.return_value = mock_graph

            agent = TradeAgent(mock_db)
            user = MagicMock(id=1)

            result = await agent.run(
                action="listing",
                space_public_id="space_1",
                user=user,
                session_id="sess_trade_2",
                asset_id="asset_1",
            )

            call_state = mock_graph.ainvoke.call_args[0][0]
            assert call_state["session_id"] == "sess_trade_2"
            agent._sync_trade_memory.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sync_trade_memory_writes_l3_and_l4(self):
        """回归测试：_sync_trade_memory 写入 L3 shared_board / approval_state 和 L4 事件。"""
        mock_db = AsyncMock()
        with patch(
            "app.agents.subagents.trade.agent.create_agent_first_trade_graph"
        ) as mock_create_graph, patch.object(
            TradeAgent, "_init_skills", return_value={"pricing": AsyncMock()}
        ):
            mock_create_graph.return_value = AsyncMock()
            agent = TradeAgent(mock_db)

        with patch("app.services.memory.UnifiedMemoryService") as MockUM:
            mock_memory = AsyncMock()
            MockUM.return_value = mock_memory

            final_state = {
                "calculated_price": 150.0,
                "selected_mechanism": "bilateral",
                "negotiation_id": "neg_1",
                "plan_id": "plan_1",
                "approval_required": True,
                "approval_status": "pending",
                "pending_decision": {"reason": "high_value"},
                "current_step": "settle",
                "success": True,
                "result": {"status": "ok"},
            }
            user = MagicMock(id=1)

            await agent._sync_trade_memory("sess_t", user, "space_1", final_state)

            MockUM.assert_called_once_with(
                db=mock_db,
                user_id=1,
                space_id="space_1",
                session_id="sess_t",
            )

            # L3: shared_board
            l3_shared = mock_memory.set_working_memory.call_args_list[0]
            assert l3_shared.kwargs["key"] == "shared_board"
            assert l3_shared.kwargs["value"]["current_price"] == 150.0

            # L3: approval_state
            l3_approval = mock_memory.set_working_memory.call_args_list[1]
            assert l3_approval.kwargs["key"] == "approval_state"
            assert l3_approval.kwargs["value"]["approval_required"] is True

            # L4: events
            event_types = [call.kwargs["event_type"] for call in mock_memory.log_event.call_args_list]
            assert "approval_required" in event_types
            assert "trade_offer" in event_types
