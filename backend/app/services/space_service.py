import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ServiceError
from app.repositories.space_repo import SpaceRepository
from app.db.models import Users, Spaces
from typing import Sequence

class SpaceService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.spaces = SpaceRepository(db)

    async def list_spaces(self, current_user: Users, limit: int, offset: int) -> Sequence[Spaces]:
        return await self.spaces.list_by_owner(current_user.id, limit, offset)

    async def create_space(self, current_user: Users, name: str) -> Spaces:
        try:
            async with self.db.begin():
                sp = await self.spaces.create(
                    owner_user_id=current_user.id,
                    name=name,
                    public_id=uuid.uuid4().hex[:32],
                )
            return sp
        except Exception as e:
            raise ServiceError(500, f"Failed to create space: {str(e)}")

    async def delete_space(self, current_user: Users, space_public_id: str) -> None:
        try:
            async with self.db.begin():
                target = await self.spaces.get_by_public_id_for_owner(space_public_id, current_user.id)
                if not target:
                    raise ServiceError(404, "Space not found or permission denied")

                cnt = await self.spaces.count_by_owner(current_user.id)
                if cnt <= 1:
                    raise ServiceError(400, "Cannot delete the last remaining space")

                await self.spaces.delete(target)
        except ServiceError:
            raise
        except Exception:
            raise ServiceError(500, "Delete failed. Please ensure the space is empty before deleting.")

    async def switch_space(self, current_user: Users, space_public_id: str) -> Spaces:
        target = await self.spaces.get_by_public_id_for_owner(space_public_id, current_user.id)
        if not target:
            raise ServiceError(404, "Target space not found")
        # TODO: 更新 Redis 或 Session 状态
        return target
