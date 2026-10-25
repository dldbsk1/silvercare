"""Storage 버킷을 app/db/storage.py의 BUCKETS 설정대로 생성

    cd backend
    python -m scripts.setup_storage
"""
from app.db.storage import BUCKETS, get_admin_client


def main():
    storage = get_admin_client().storage
    existing = {bucket.id for bucket in storage.list_buckets()}

    for bucket_id, options in BUCKETS.items():
        if bucket_id in existing:
            storage.update_bucket(bucket_id, options)
            print(f"맞춤: {bucket_id}")
        else:
            storage.create_bucket(bucket_id, options=options)
            print(f"생성: {bucket_id}")

    for bucket in storage.list_buckets():
        if bucket.id in BUCKETS:
            print(
                f"  {bucket.id}: public={bucket.public} "
                f"limit={bucket.file_size_limit} "
                f"types={bucket.allowed_mime_types}"
            )


if __name__ == "__main__":
    main()
