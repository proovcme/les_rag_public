import pytest

from proxy.routers import jobs


class FakeJobService:
    def __init__(self, payload):
        self.payload = payload

    def list(self, limit=200):
        return self.payload


@pytest.fixture()
def jobs_state():
    previous = jobs._state
    yield
    jobs._state = previous


@pytest.mark.asyncio
async def test_jobs_summary_strips_large_batch_results(jobs_state):
    jobs.set_jobs_state(
        jobs.JobsRouterState(
            job_service=FakeJobService(
                {
                    "job-1": {
                        "id": "job-1",
                        "type": "rag_parse_scheduler",
                        "status": "COMPLETED",
                        "total": 500,
                        "processed": 500,
                        "errors": 0,
                        "message": "done",
                        "started_at": "2026-05-25T10:00:00",
                        "updated_at": "2026-05-25T10:05:00",
                        "result": {
                            "status": "completed",
                            "batches": [{"batch": i, "payload": "x" * 1000} for i in range(3)],
                            "batches_run": 3,
                            "remaining_pending": 0,
                            "errors": 0,
                        },
                    }
                }
            ),
            job_tracker={},
        )
    )

    result = await jobs.get_jobs_summary(_user=object())

    item = result["jobs"][0]
    assert "result" not in item
    assert item["result_summary"]["batches_count"] == 3
    assert item["result_summary"]["remaining_pending"] == 0


@pytest.mark.asyncio
async def test_jobs_summary_can_return_only_active_jobs(jobs_state):
    jobs.set_jobs_state(
        jobs.JobsRouterState(
            job_service=FakeJobService(
                {
                    "done": {"id": "done", "status": "COMPLETED", "updated_at": "2026-05-25T10:00:00"},
                    "run": {"id": "run", "status": "RUNNING", "updated_at": "2026-05-25T10:01:00"},
                }
            ),
            job_tracker={
                "queued": {"id": "queued", "status": "QUEUED", "updated_at": "2026-05-25T10:02:00"}
            },
        )
    )

    result = await jobs.get_jobs_summary(active_only=True, _user=object())

    assert [item["id"] for item in result["jobs"]] == ["queued", "run"]
    assert result["active_count"] == 2
