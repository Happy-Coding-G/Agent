from datetime import timedelta
from io import BytesIO

from minio import Minio

from app.core.config import settings


class MinioService:
    def __init__(self):
        self.client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        self.bucket = "bucket"

        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def get_upload_url(self, object_key: str):
        """Generate presigned upload URL (PUT)."""
        return self.client.presigned_put_object(self.bucket, object_key, expires=timedelta(minutes=30))

    def get_download_url(self, object_key: str):
        """Generate presigned download URL (GET)."""
        return self.client.presigned_get_object(self.bucket, object_key, expires=timedelta(hours=1))

    def upload_text(self, object_key: str, content: str, content_type: str = "text/markdown; charset=utf-8"):
        data = content.encode("utf-8")
        self.client.put_object(
            self.bucket,
            object_key,
            data=BytesIO(data),
            length=len(data),
            content_type=content_type,
        )


minio_service = MinioService()
