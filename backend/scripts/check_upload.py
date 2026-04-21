
import sys
import asyncio
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.db.models import Upload, FileNode, DataAsset

async def get_info():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Upload).where(Upload.filename.ilike('%2015-DistMult.pdf%')))
        for u in result.scalars().all():
            err = getattr(u, 'error_message', '')
            print(f'Upload [{u.id}]: {u.filename} | Status: {u.status} | Err: {err}')
            
        result = await session.execute(select(FileNode).where(FileNode.name.ilike('%2015-DistMult%')))
        for f in result.scalars().all():
            print(f'FileNode [{f.id}]: {f.name} | Status: {f.ingest_status}')
            
        result = await session.execute(select(DataAsset).where(DataAsset.filename.ilike('%2015-DistMult%')))
        for a in result.scalars().all():
            print(f'DataAsset [{a.id}]: {a.filename} | Status: {a.asset_status}')

if __name__ == '__main__':
    asyncio.run(get_info())

