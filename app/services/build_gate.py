from datetime import datetime, timezone

from sqlalchemy import func, select, text

from models import Deployment

# Arbitrary fixed key; every start job takes the same advisory lock.
START_LOCK_KEY = 7061721


def container_started_at_key(deployment_id: str) -> str:
    return f"deployment:{deployment_id}:container_started_at"


async def admit_start(lock_conn, db, deployment_id: str, limit: int) -> str:
    """Decide whether a deployment may start its runner container now.

    Returns "start", "wait" (try again shortly) or "skip" (nothing to start).
    The lock is transaction-scoped, so the caller holds it for as long as the
    transaction on `lock_conn` stays open, and a failed start cannot leak it.
    """
    got = (
        await lock_conn.execute(
            text("select pg_try_advisory_xact_lock(:key)"), {"key": START_LOCK_KEY}
        )
    ).scalar()
    if not got:
        return "wait"

    row = (
        await db.execute(
            select(Deployment.id, Deployment.conclusion).where(
                Deployment.id == deployment_id
            )
        )
    ).one_or_none()
    if row is None or row[1] == "canceled":
        return "skip"

    starting = (
        await db.execute(
            select(func.count())
            .select_from(Deployment)
            .where(
                Deployment.status == "deploy",
                Deployment.container_status == "running",
            )
        )
    ).scalar_one()
    if starting >= limit:
        return "wait"

    return "start"


def timeout_started_at(created_at: datetime, container_started_at) -> datetime:
    """When to start the deployment timeout clock.

    A deployment that waited for a free build slot has not been running since
    it was created, so the clock runs from the recorded container start when
    there is one.
    """
    if container_started_at:
        try:
            if isinstance(container_started_at, bytes):
                container_started_at = container_started_at.decode()
            started = datetime.fromisoformat(container_started_at)
            return (
                started.replace(tzinfo=timezone.utc)
                if started.tzinfo is None
                else started
            )
        except (ValueError, UnicodeDecodeError):
            pass

    return (
        created_at.replace(tzinfo=timezone.utc)
        if created_at.tzinfo is None
        else created_at
    )
