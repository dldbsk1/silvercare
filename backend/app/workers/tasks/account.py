"""계정 작업: 탈퇴 즉시 처리

run_deletions: 예정 시각 지난 삭제 요청 전부 처리 (탈퇴 = 접수 즉시)
- 정리 주기 (1시간) 기다리지 않게 탈퇴 때 등록
- 멱등: 요청 선점·완료 표시는 deletion_service 안에서. 같이 돌아도 한 번만 완료
- DELETION_EXECUTE_ENABLED 꺼짐 → 할 일 없음 (정리 주기에서도 같음)
"""
from app.services import deletion_service
from app.workers.tasks import Job, task


@task(deletion_service.RUN_JOB)
def run_deletions(db, job: Job):
    deletion_service.run(db)
