import boto3
from botocore.config import Config

client = boto3.client(
    "s3",
    endpoint_url="http://localhost:9000",
    aws_access_key_id="minioadmin",
    aws_secret_access_key="minioadmin",
    config=Config(signature_version="s3v4"),
)

try:
    buckets = client.list_buckets()
    print("Buckets:", [b["Name"] for b in buckets["Buckets"]])
    for b in buckets["Buckets"]:
        objs = client.list_objects_v2(Bucket=b["Name"], MaxKeys=5)
        contents = objs.get("Contents", [])
        keys = [o["Key"] for o in contents]
        print(f"  {b['Name']}: {len(contents)} objects, sample: {keys[:3]}")
except Exception as e:
    print(f"Error: {e}")
