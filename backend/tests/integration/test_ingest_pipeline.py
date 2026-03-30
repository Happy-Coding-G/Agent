"""
Ingest 流程完整测试脚本
测试步骤：
1. 检查数据库连接
2. 获取测试空间和用户
3. 创建测试文件并上传
4. 触发 ingest 任务
5. 跟踪任务状态直到完成
6. 验证每一步结果
"""

import asyncio
import sys
import os
import uuid
from datetime import datetime
from pathlib import Path

# 添加 backend 到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.db.models import Spaces, Users, Documents, IngestJobs, Files, FileVersions
from app.utils.MinIO import minio_service
from app.core.task_manager import task_manager
from app.ai.ingest_pipeline import LangChainIngestPipeline
from app.services.ingest_service import IngestService
from app.core.celery_config import celery_app
from celery.result import AsyncResult

import time


class IngestTest:
    def __init__(self):
        self.db: AsyncSession = None
        self.space = None
        self.user = None
        self.test_file_path = None
        self.upload_result = None
        self.doc = None
        self.job = None
        self.test_results = []

    def log(self, message: str, success: bool = True):
        """记录测试结果"""
        status = "[OK]" if success else "[FAIL]"
        print(f"{status} {datetime.now().strftime('%H:%M:%S')} {message}")
        self.test_results.append({"message": message, "success": success})

    async def setup(self):
        """初始化数据库连接"""
        self.db = AsyncSessionLocal()
        self.log("数据库连接初始化完成")

    async def test_database_connection(self):
        """测试数据库连接"""
        try:
            result = await self.db.execute(text("SELECT 1"))
            assert result.scalar() == 1
            self.log("数据库连接测试通过")
            return True
        except Exception as e:
            self.log(f"数据库连接失败: {e}", success=False)
            return False

    async def get_test_entities(self):
        """获取测试所需的空间和用户"""
        try:
            # 获取第一个空间
            result = await self.db.execute(select(Spaces))
            self.space = result.scalars().first()
            if not self.space:
                self.log("没有找到可用的空间", success=False)
                return False
            self.log(f"获取到测试空间: {self.space.name} (ID: {self.space.public_id})")

            # 获取第一个用户
            result = await self.db.execute(select(Users))
            self.user = result.scalars().first()
            if not self.user:
                self.log("没有找到可用的用户", success=False)
                return False
            self.log(f"获取到测试用户: {self.user.display_name or 'Unknown'} (ID: {self.user.id})")

            return True
        except Exception as e:
            self.log(f"获取测试实体失败: {e}", success=False)
            return False

    async def create_test_file(self):
        """创建测试文件"""
        try:
            test_content = """# 测试文档

这是一个用于测试 Ingest Pipeline 的文档。

## 第一部分：简介

本文档用于验证文档摄取流程的各个阶段是否正常工作。

### 关键点
- 文本提取
- Markdown 转换
- 文档切块
- 向量嵌入
- 知识图谱构建

## 第二部分：详细内容

这是一个更长的段落，用于测试文档切块功能。文档切块应该能够智能地将内容分割成适当大小的片段，同时保持语义完整性。

代码示例：
```python
def hello_world():
    print("Hello, World!")
```

## 第三部分：结论

测试文档结束。
"""
            # 保存到临时文件
            self.test_file_path = Path(f"/tmp/test_ingest_{uuid.uuid4().hex[:8]}.md")
            self.test_file_path.write_text(test_content, encoding="utf-8")
            self.log(f"创建测试文件: {self.test_file_path} ({len(test_content)} 字符)")
            return True
        except Exception as e:
            self.log(f"创建测试文件失败: {e}", success=False)
            return False

    async def test_minio_connection(self):
        """测试 MinIO 连接"""
        try:
            # 检查 bucket 是否存在
            buckets = minio_service.client.list_buckets()
            bucket_names = [b.name for b in buckets]
            self.log(f"MinIO 连接成功，buckets: {bucket_names}")
            return True
        except Exception as e:
            self.log(f"MinIO 连接失败: {e}", success=False)
            return False

    async def upload_file_to_minio(self):
        """上传文件到 MinIO"""
        try:
            object_key = f"test/{self.space.public_id}/{self.test_file_path.name}"
            # 读取文件内容并上传
            file_content = self.test_file_path.read_bytes()
            from io import BytesIO
            minio_service.client.put_object(
                minio_service.bucket,
                object_key,
                data=BytesIO(file_content),
                length=len(file_content),
                content_type="text/markdown"
            )
            self.upload_result = {"object_key": object_key}
            self.log(f"文件上传到 MinIO: {object_key}")
            return True
        except Exception as e:
            self.log(f"MinIO 上传失败: {e}", success=False)
            return False

    async def create_file_record(self):
        """创建文件记录"""
        try:
            # 先获取或创建一个文件夹
            from sqlalchemy import select
            from app.db.models import Folders

            result = await self.db.execute(
                select(Folders).where(Folders.space_id == self.space.id).limit(1)
            )
            folder = result.scalar_one_or_none()

            if not folder:
                # 创建根文件夹
                folder = Folders(
                    space_id=self.space.id,
                    name="root",
                    created_by=self.user.id,
                    public_id=uuid.uuid4().hex[:16],
                )
                self.db.add(folder)
                await self.db.flush()
                self.log(f"创建根文件夹: ID={folder.id}")
            else:
                self.log(f"使用现有文件夹: {folder.name} (ID: {folder.id})")

            # 创建 Files 记录
            file_record = Files(
                space_id=self.space.id,
                folder_id=folder.id,  # 使用有效的文件夹 ID
                name=self.test_file_path.name,
                created_by=self.user.id,
                public_id=uuid.uuid4().hex[:16],  # 必须设置 public_id
                mime="text/markdown",
                size_bytes=self.test_file_path.stat().st_size,
            )
            self.db.add(file_record)
            await self.db.flush()

            # 创建 FileVersions 记录
            file_version = FileVersions(
                file_id=file_record.id,
                version_no=1,
                size_bytes=self.test_file_path.stat().st_size,
                object_key=self.upload_result["object_key"],
                created_by=self.user.id,
                public_id=uuid.uuid4().hex[:16],
            )
            self.db.add(file_version)
            await self.db.flush()

            # 更新文件的当前版本
            file_record.current_version_id = file_version.id
            await self.db.flush()
            await self.db.commit()  # 提交事务

            self.file_record = file_record
            self.file_version = file_version

            self.log(f"创建文件记录: file_id={file_record.id}, version_id={file_version.id}")
            return True
        except Exception as e:
            await self.db.rollback()
            self.log(f"创建文件记录失败: {e}", success=False)
            import traceback
            traceback.print_exc()
            return False

    async def create_ingest_job(self):
        """创建 Ingest Job"""
        try:
            service = IngestService(self.db)
            self.doc, self.job = await service.create_ingest_job_from_version(
                space_id=self.space.id,  # 使用内部 id，不是 public_id
                file_id=self.file_record.id,
                file_version_id=self.file_version.id,
                object_key=self.upload_result["object_key"],
                created_by=self.user.id,
            )
            self.log(f"创建 Ingest Job: ingest_id={self.job.ingest_id}, doc_id={self.doc.doc_id}")
            return True
        except Exception as e:
            self.log(f"创建 Ingest Job 失败: {e}", success=False)
            import traceback
            traceback.print_exc()
            return False

    async def run_ingest_pipeline_via_celery(self):
        """通过 Celery 运行 Ingest Pipeline"""
        try:
            self.log("通过 Celery 提交 Ingest Job...")

            # 提交任务到 Celery
            from app.tasks.ingest_tasks import process_ingest_job

            task = process_ingest_job.delay(str(self.job.ingest_id))
            task_id = task.id
            self.log(f"Celery 任务已提交: task_id={task_id}, ingest_id={self.job.ingest_id}")

            # 等待任务完成（最多等待 5 分钟）
            max_wait = 300  # 5 分钟
            wait_interval = 2  # 每 2 秒检查一次
            waited = 0

            while waited < max_wait:
                # 刷新任务状态
                task_result = AsyncResult(task_id, app=celery_app)

                # 首先检查 Celery 任务状态
                if task_result.ready():
                    self.log(f"Celery 任务完成，状态: {task_result.status}")
                    if task_result.successful():
                        result = task_result.get()
                        self.log(f"任务执行成功: {result}")
                        return True
                    else:
                        error = task_result.result if hasattr(task_result, 'result') else "Unknown error"
                        self.log(f"Celery 任务执行失败: {error}", success=False)
                        return False

                # 检查数据库中的 Job 状态
                await self.db.refresh(self.job)

                # 如果数据库状态为 succeeded 或 failed，也视为完成
                if self.job.status == "succeeded":
                    self.log(f"Job 状态为 succeeded (已等待 {waited}s)")
                    return True
                elif self.job.status == "failed":
                    self.log(f"Job 状态为 failed: {self.job.error_message} (已等待 {waited}s)", success=False)
                    return False
                else:
                    self.log(f"  Job 状态: {self.job.status} (已等待 {waited}s)...")

                # 等待一段时间
                await asyncio.sleep(wait_interval)
                waited += wait_interval

            self.log(f"等待 Celery 任务超时（超过 {max_wait} 秒）", success=False)
            return False

        except Exception as e:
            self.log(f"Celery 任务执行失败: {e}", success=False)
            import traceback
            traceback.print_exc()
            return False

    async def verify_ingest_results(self):
        """验证 Ingest 结果"""
        try:
            # 刷新数据库记录
            await self.db.refresh(self.doc)
            await self.db.refresh(self.job)

            # 验证文档状态
            if self.doc.status == "completed":
                self.log(f"文档状态: {self.doc.status}")
            else:
                self.log(f"文档状态异常: {self.doc.status}", success=False)

            # 验证 Job 状态
            if self.job.status == "succeeded":
                self.log(f"Job 状态: {self.job.status}")
            else:
                self.log(f"Job 状态异常: {self.job.status}", success=False)

            # 验证 Markdown 是否保存
            if self.doc.markdown_object_key:
                self.log(f"Markdown 已保存: {self.doc.markdown_object_key}")
                # 尝试读取
                try:
                    from io import BytesIO
                    response = minio_service.client.get_object(
                        minio_service.bucket, self.doc.markdown_object_key
                    )
                    content = response.read().decode("utf-8")
                    response.close()
                    self.log(f"Markdown 内容长度: {len(content)} 字符")
                except Exception as e:
                    self.log(f"读取 Markdown 失败: {e}", success=False)
            else:
                self.log("Markdown object_key 为空", success=False)

            # 验证切块
            from sqlalchemy import select
            from app.db.models import DocChunks

            result = await self.db.execute(
                select(DocChunks).where(DocChunks.doc_id == self.doc.doc_id)
            )
            chunks = result.scalars().all()
            self.log(f"文档切块数量: {len(chunks)}")

            if chunks:
                self.log(f"第一个切块长度: {len(chunks[0].content)} 字符")

            # 验证嵌入
            from app.db.models import DocChunkEmbeddings

            result = await self.db.execute(
                select(DocChunkEmbeddings).where(
                    DocChunkEmbeddings.chunk_id.in_([c.chunk_id for c in chunks[:5]])
                )
            )
            embeddings = result.scalars().all()
            self.log(f"嵌入向量数量: {len(embeddings)}")

            return True
        except Exception as e:
            self.log(f"验证结果失败: {e}", success=False)
            import traceback
            traceback.print_exc()
            return False

    async def cleanup(self):
        """清理测试数据"""
        try:
            if self.test_file_path and self.test_file_path.exists():
                self.test_file_path.unlink()
                self.log(f"清理临时文件: {self.test_file_path}")

            await self.db.close()
            self.log("数据库连接已关闭")
        except Exception as e:
            self.log(f"清理失败: {e}", success=False)

    async def run_all_tests(self):
        """运行所有测试"""
        print("=" * 60)
        print("Ingest Pipeline 完整测试")
        print("=" * 60)

        try:
            await self.setup()

            # 1. 数据库连接测试
            if not await self.test_database_connection():
                return False

            # 2. 获取测试实体
            if not await self.get_test_entities():
                return False

            # 3. 创建测试文件
            if not await self.create_test_file():
                return False

            # 4. MinIO 连接测试
            if not await self.test_minio_connection():
                return False

            # 5. 上传文件
            if not await self.upload_file_to_minio():
                return False

            # 6. 创建文件记录
            if not await self.create_file_record():
                return False

            # 7. 创建 Ingest Job
            if not await self.create_ingest_job():
                return False

            # 8. 执行 Pipeline（通过 Celery）
            if not await self.run_ingest_pipeline_via_celery():
                return False

            # 9. 验证结果
            if not await self.verify_ingest_results():
                return False

            print("\n" + "=" * 60)
            print("测试完成！")
            print("=" * 60)

            # 统计结果
            passed = sum(1 for r in self.test_results if r["success"])
            failed = sum(1 for r in self.test_results if not r["success"])
            print(f"总计: {len(self.test_results)} 项 | 通过: {passed} | 失败: {failed}")

            return failed == 0

        finally:
            await self.cleanup()


async def main():
    test = IngestTest()
    success = await test.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
