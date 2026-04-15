#!/usr/bin/env python3
"""
一次性迁移脚本：将 state_store 中的知识资产迁移到 data_assets 表。

执行方式（离线）：
    cd backend
    conda activate agent
    python scripts/migrate_assets_to_db.py
"""

import asyncio
import glob
import json
import os
import sys
from pathlib import Path

# 将 backend 加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DataAssets, DataSensitivityLevel, Spaces
from app.db.session import async_engine, async_session_maker
from app.utils.state_store import STATE_DIR


async def get_space_owner(db: AsyncSession, space_public_id: str) -> int | None:
    """通过 space_public_id 查找空间的拥有者。"""
    result = await db.execute(
        select(Spaces).where(Spaces.public_id == space_public_id)
    )
    space = result.scalar_one_or_none()
    if space:
        return space.owner_user_id
    return None


async def migrate_space_assets(db: AsyncSession, filepath: str) -> int:
    """迁移单个空间的资产文件。"""
    filename = os.path.basename(filepath)
    space_public_id = filename.replace(".json", "")

    with open(filepath, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"  [!] 跳过损坏文件 {filename}: {e}")
            return 0

    if not isinstance(data, list):
        print(f"  [!] 跳过非列表格式文件 {filename}")
        return 0

    owner_id = await get_space_owner(db, space_public_id)
    if owner_id is None:
        print(f"  [!] 找不到空间 {space_public_id} 的拥有者，跳过")
        return 0

    migrated = 0
    for item in data:
        if not isinstance(item, dict):
            continue

        asset_id = item.get("asset_id")
        if not asset_id:
            continue

        # 检查是否已存在
        existing = await db.execute(
            select(DataAssets).where(DataAssets.asset_id == asset_id)
        )
        if existing.scalar_one_or_none():
            print(f"  [-] 资产已存在，跳过: {asset_id}")
            continue

        db_asset = DataAssets(
            asset_id=asset_id,
            owner_id=owner_id,
            asset_name=item.get("title", "Migrated Asset")[:200],
            asset_description=None,
            data_type="knowledge_report",
            sensitivity_level=DataSensitivityLevel.MEDIUM,
            quality_completeness=0.0,
            quality_accuracy=0.0,
            quality_timeliness=0.0,
            quality_consistency=0.0,
            quality_uniqueness=0.0,
            quality_overall_score=0.0,
            raw_data_source="legacy_state_store",
            storage_location="legacy_state_store",
            is_active=True,
            is_available_for_trade=True,
            space_public_id=space_public_id,
            asset_type="knowledge_report",
            content_markdown=item.get("content_markdown"),
            content_summary=item.get("summary"),
            graph_snapshot=item.get("graph_snapshot") or {},
            generation_prompt=item.get("prompt"),
            source_document_ids=[],
            source_asset_ids=[],
        )
        db.add(db_asset)
        migrated += 1

    await db.commit()
    return migrated


async def main():
    assets_dir = os.path.join(STATE_DIR, "assets")
    if not os.path.isdir(assets_dir):
        print(f"资产目录不存在: {assets_dir}")
        return

    files = sorted(glob.glob(os.path.join(assets_dir, "*.json")))
    if not files:
        print("没有需要迁移的资产文件")
        return

    print(f"发现 {len(files)} 个空间资产文件，开始迁移...")

    async with async_session_maker() as db:
        total_migrated = 0
        for filepath in files:
            space_public_id = os.path.basename(filepath).replace(".json", "")
            print(f"\n[处理] 空间 {space_public_id}")
            count = await migrate_space_assets(db, filepath)
            total_migrated += count
            print(f"  [+] 迁移 {count} 条资产")

            # 可选：迁移完成后重命名原文件为 .bak
            bak_path = filepath + ".bak"
            os.rename(filepath, bak_path)
            print(f"  [>] 已备份原文件 -> {os.path.basename(bak_path)}")

    print(f"\n========================")
    print(f"迁移完成，共迁移 {total_migrated} 条资产")
    print(f"========================")


if __name__ == "__main__":
    asyncio.run(main())
