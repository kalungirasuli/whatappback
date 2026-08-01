import boto3
import uuid
import logging

from botocore.config import Config
from botocore.exceptions import ClientError

from src.core.config import settings

logger = logging.getLogger(__name__)

_s3_client = None


def get_s3_client():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=Config(signature_version="s3v4"),
        )
    return _s3_client


async def ensure_bucket() -> None:
    client = get_s3_client()
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
        logger.info(f"Bucket '{settings.s3_bucket}' already exists")
    except ClientError:
        try:
            client.create_bucket(Bucket=settings.s3_bucket)
            client.put_bucket_acl(
                Bucket=settings.s3_bucket,
                ACL="public-read",
            )
            logger.info(f"Bucket '{settings.s3_bucket}' created")
        except ClientError as e:
            logger.error(f"Failed to create bucket: {e}")
            raise


async def upload_image(data: bytes, content_type: str = "image/jpeg") -> str:
    key = f"products/{uuid.uuid4().hex}.jpg"
    client = get_s3_client()
    client.put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
    )
    url = f"{settings.cdn_base_url}/{key}"
    logger.info(f"Image uploaded: {url}")
    return url


async def delete_image(url: str) -> None:
    key = url.replace(f"{settings.cdn_base_url}/", "")
    client = get_s3_client()
    client.delete_object(Bucket=settings.s3_bucket, Key=key)
    logger.info(f"Image deleted: {key}")
