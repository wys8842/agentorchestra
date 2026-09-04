"""SQLAlchemy 2.0 async 基类。

所有 SQL backend（SQLite/PostgreSQL）共用此基类，差异仅在 dialect 与连接串。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    insert,
    select,
)
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ..checkpoint import Checkpoint, CheckpointStore, dumps_json, loads_json
from ..interrupt import Interrupt, InterruptStatus
from ..records import DLQEntry, IdempotencyRecord, LockRecord
from ..snapshot import Snapshot
from ..thread import ThreadStatus
from ..wal import WALActionType, WALEntry


class Base(DeclarativeBase):
    pass


class _ThreadRow(Base):
    __tablename__ = "threads"

    thread_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    meta_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")


class _CheckpointRow(Base):
    __tablename__ = "checkpoints"

    thread_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    checkpoint_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    parent_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    state_json: Mapped[str] = mapped_column(Text, nullable=False)
    meta_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("idx_checkpoints_thread_created", "thread_id", "created_at"),
    )


class _WALRow(Base):
    __tablename__ = "wal"

    # SQLite 不支持 BigInteger autoincrement；用 Integer（rowid 即 autoincrement）。
    # Postgres 端 INTEGER 也可以 BIGSERIAL 替换（后续 PG backend 覆盖）。
    wal_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sequence_no: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    tx_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("thread_id", "sequence_no", name="uq_wal_thread_seq"),
        Index("idx_wal_thread_seq", "thread_id", "sequence_no"),
    )


class _SnapshotRow(Base):
    __tablename__ = "snapshots"

    thread_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    up_to_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state_json: Mapped[str] = mapped_column(Text, nullable=False)
    meta_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class _InterruptRow(Base):
    __tablename__ = "interrupts"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(128), nullable=False)
    checkpoint_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    response_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class _LockRow(Base):
    __tablename__ = "locks"

    resource_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    owner_tx: Mapped[str] = mapped_column(String(128), nullable=False)
    held_since: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class _IdempotencyRow(Base):
    __tablename__ = "idempotency_keys"

    idempotency_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    tx_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    result_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class _DLQRow(Base):
    __tablename__ = "dead_letter"

    dlq_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tx_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action_name: Mapped[str] = mapped_column(String(255), nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class SQLAlchemyCheckpointStore(CheckpointStore):
    """SQLAlchemy 2.0 async 基类。

    子类只需要指定 `_db_url` 和 `_dialect`（用于 SQL 兼容）。
    """

    _dialect: str = "generic"

    def __init__(self, db_url: str):
        self._db_url = db_url
        self._engine: Optional[AsyncEngine] = None
        self._initialized = False

    async def init(self) -> None:
        if self._initialized:
            return
        # echo=False 避免噪声；生产可调
        self._engine = create_async_engine(self._db_url, echo=False, future=True)
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self._initialized = True

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._initialized = False

    # ---------------- Thread ----------------

    async def create_thread(
        self, thread_id: str, metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        assert self._engine is not None
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        now = datetime.now()
        meta_str = dumps_json(metadata or {}) if metadata else None
        async with self._engine.begin() as conn:
            if self._dialect == "sqlite":
                from sqlalchemy.dialects.sqlite import insert as sqlite_insert

                stmt: Any = sqlite_insert(_ThreadRow).values(
                    thread_id=thread_id,
                    created_at=now,
                    updated_at=now,
                    meta_json=meta_str,
                    status=ThreadStatus.ACTIVE.value,
                ).on_conflict_do_nothing(index_elements=["thread_id"])
            else:  # postgres
                from sqlalchemy.dialects.postgresql import insert as pg_insert

                stmt = pg_insert(_ThreadRow).values(
                    thread_id=thread_id,
                    created_at=now,
                    updated_at=now,
                    meta_json=meta_str,
                    status=ThreadStatus.ACTIVE.value,
                ).on_conflict_do_nothing(index_elements=["thread_id"])
            await conn.execute(stmt)

    async def get_thread(self, thread_id: str) -> Optional[Dict[str, Any]]:
        assert self._engine is not None
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    select(_ThreadRow).where(_ThreadRow.thread_id == thread_id)
                )
            ).first()
            if not row:
                return None
            return {
                "thread_id": row.thread_id,
                "status": row.status,
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
                "metadata": loads_json(row.meta_json) if row.meta_json else {},
            }

    async def update_thread_status(self, thread_id: str, status: str) -> None:
        assert self._engine is not None
        from sqlalchemy import update

        async with self._engine.begin() as conn:
            await conn.execute(
                update(_ThreadRow)
                .where(_ThreadRow.thread_id == thread_id)
                .values(status=status, updated_at=datetime.now())
            )

    # ---------------- Checkpoint ----------------

    async def save_checkpoint(self, cp: Checkpoint) -> None:
        assert self._engine is not None
        from sqlalchemy import delete

        async with self._engine.begin() as conn:
            # 已存在则覆盖
            await conn.execute(
                delete(_CheckpointRow).where(
                    (_CheckpointRow.thread_id == cp.thread_id)
                    & (_CheckpointRow.checkpoint_id == cp.checkpoint_id)
                )
            )
            await conn.execute(
                insert(_CheckpointRow).values(
                    thread_id=cp.thread_id,
                    checkpoint_id=cp.checkpoint_id,
                    parent_id=cp.parent_id,
                    state_json=dumps_json(cp.state),
                    meta_json=dumps_json(cp.metadata) if cp.metadata else None,
                    created_at=cp.created_at,
                )
            )

    async def load_checkpoint(
        self, thread_id: str, checkpoint_id: str
    ) -> Optional[Checkpoint]:
        assert self._engine is not None
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    select(_CheckpointRow).where(
                        (_CheckpointRow.thread_id == thread_id)
                        & (_CheckpointRow.checkpoint_id == checkpoint_id)
                    )
                )
            ).first()
            if not row:
                return None
            return Checkpoint(
                thread_id=row.thread_id,
                checkpoint_id=row.checkpoint_id,
                parent_id=row.parent_id,
                state=loads_json(row.state_json),
                metadata=loads_json(row.meta_json) if row.meta_json else {},
                created_at=row.created_at,
            )

    async def list_checkpoints(
        self, thread_id: str, limit: int = 50
    ) -> List[Checkpoint]:
        assert self._engine is not None
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(_CheckpointRow)
                    .where(_CheckpointRow.thread_id == thread_id)
                    .order_by(_CheckpointRow.created_at.desc())
                    .limit(limit)
                )
            ).all()
            return [
                Checkpoint(
                    thread_id=r.thread_id,
                    checkpoint_id=r.checkpoint_id,
                    parent_id=r.parent_id,
                    state=loads_json(r.state_json),
                    metadata=loads_json(r.meta_json) if r.meta_json else {},
                    created_at=r.created_at,
                )
                for r in rows
            ]

    async def latest_checkpoint(self, thread_id: str) -> Optional[Checkpoint]:
        cps = await self.list_checkpoints(thread_id, limit=1)
        return cps[0] if cps else None

    # ---------------- WAL ----------------

    async def append_wal(self, entry: WALEntry) -> int:
        assert self._engine is not None
        from sqlalchemy import func, select

        async with self._engine.begin() as conn:
            # 原子递增（select max + 1）
            result = await conn.execute(
                select(func.coalesce(func.max(_WALRow.sequence_no), 0)).where(
                    _WALRow.thread_id == entry.thread_id
                )
            )
            current_max = result.scalar() or 0
            seq = current_max + 1
            await conn.execute(
                insert(_WALRow).values(
                    thread_id=entry.thread_id,
                    sequence_no=seq,
                    action_type=entry.action_type.value
                    if isinstance(entry.action_type, WALActionType)
                    else str(entry.action_type),
                    payload_json=dumps_json(entry.payload),
                    tx_id=entry.tx_id,
                    created_at=entry.created_at,
                )
            )
        entry.sequence_no = seq
        return seq

    async def read_wal(
        self, thread_id: str, after_seq: int = 0, limit: int = 1000
    ) -> List[WALEntry]:
        assert self._engine is not None
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(_WALRow)
                    .where(
                        (_WALRow.thread_id == thread_id)
                        & (_WALRow.sequence_no > after_seq)
                    )
                    .order_by(_WALRow.sequence_no.asc())
                    .limit(limit)
                )
            ).all()
            return [
                WALEntry(
                    thread_id=r.thread_id,
                    sequence_no=r.sequence_no,
                    action_type=WALActionType(r.action_type),
                    payload=loads_json(r.payload_json),
                    tx_id=r.tx_id,
                    created_at=r.created_at,
                )
                for r in rows
            ]

    async def max_wal_seq(self, thread_id: str) -> int:
        assert self._engine is not None
        from sqlalchemy import func, select

        async with self._engine.connect() as conn:
            result = await conn.execute(
                select(func.coalesce(func.max(_WALRow.sequence_no), 0)).where(
                    _WALRow.thread_id == thread_id
                )
            )
            return int(result.scalar() or 0)

    # ---------------- Snapshot ----------------

    async def save_snapshot(self, snap: Snapshot) -> None:
        assert self._engine is not None
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(_SnapshotRow).values(
                    thread_id=snap.thread_id,
                    snapshot_id=snap.snapshot_id,
                    up_to_seq=snap.up_to_seq,
                    state_json=dumps_json(snap.state),
                    meta_json=dumps_json(snap.metadata) if snap.metadata else None,
                    created_at=snap.created_at,
                )
            )

    async def latest_snapshot(self, thread_id: str) -> Optional[Snapshot]:
        assert self._engine is not None
        from sqlalchemy import select

        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    select(_SnapshotRow)
                    .where(_SnapshotRow.thread_id == thread_id)
                    .order_by(_SnapshotRow.created_at.desc())
                    .limit(1)
                )
            ).first()
            if not row:
                return None
            return Snapshot(
                thread_id=row.thread_id,
                snapshot_id=row.snapshot_id,
                up_to_seq=row.up_to_seq,
                state=loads_json(row.state_json),
                metadata=loads_json(row.meta_json) if row.meta_json else {},
                created_at=row.created_at,
            )

    # ---------------- Interrupt ----------------

    async def create_interrupt(self, intr: Interrupt) -> None:
        assert self._engine is not None
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(_InterruptRow).values(
                    token=intr.token,
                    thread_id=intr.thread_id,
                    checkpoint_id=intr.checkpoint_id,
                    reason=intr.reason,
                    payload_json=dumps_json(intr.payload) if intr.payload else None,
                    status=intr.status.value,
                    response_json=None,
                    created_at=intr.created_at,
                    resolved_at=None,
                )
            )

    async def resolve_interrupt(self, token: str, response: Dict[str, Any]) -> None:
        assert self._engine is not None
        from sqlalchemy import update

        async with self._engine.begin() as conn:
            await conn.execute(
                update(_InterruptRow)
                .where(_InterruptRow.token == token)
                .values(
                    status=InterruptStatus.RESUMED.value,
                    response_json=dumps_json(response) if response else None,
                    resolved_at=datetime.now(),
                )
            )

    async def get_interrupt(self, token: str) -> Optional[Interrupt]:
        assert self._engine is not None
        from sqlalchemy import select

        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    select(_InterruptRow).where(_InterruptRow.token == token)
                )
            ).first()
            if not row:
                return None
            return Interrupt(
                token=row.token,
                thread_id=row.thread_id,
                checkpoint_id=row.checkpoint_id,
                reason=row.reason,
                payload=loads_json(row.payload_json) if row.payload_json else {},
                status=InterruptStatus(row.status),
                response=loads_json(row.response_json) if row.response_json else None,
                created_at=row.created_at,
                resolved_at=row.resolved_at,
            )

    # ---------------- 锁（M1） ----------------

    async def acquire_lock(
        self, resource_key: str, owner_tx: str, ttl_seconds: float = 30.0
    ) -> Optional[LockRecord]:
        assert self._engine is not None
        from sqlalchemy import delete
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        now = datetime.now()
        expires_at = None
        if ttl_seconds and ttl_seconds > 0:
            from datetime import timedelta

            expires_at = now + timedelta(seconds=ttl_seconds)

        async with self._engine.begin() as conn:
            # ① 已存在且未过期：加锁失败
            row = (
                await conn.execute(
                    select(_LockRow).where(_LockRow.resource_key == resource_key)
                )
            ).first()
            if row is not None:
                exp = row.expires_at
                if exp is None or exp > now:
                    return None
                # 过期锁：抢占（先删旧锁）
                await conn.execute(
                    delete(_LockRow).where(_LockRow.resource_key == resource_key)
                )

            # ② 插入锁（首次 version=0；on conflict 防并发抢占双插）
            if self._dialect == "sqlite":
                stmt: Any = sqlite_insert(_LockRow).values(
                    resource_key=resource_key,
                    version=0,
                    owner_tx=owner_tx,
                    held_since=now,
                    expires_at=expires_at,
                ).on_conflict_do_nothing(index_elements=["resource_key"])
            else:
                from sqlalchemy.dialects.postgresql import insert as pg_insert

                stmt = pg_insert(_LockRow).values(
                    resource_key=resource_key,
                    version=0,
                    owner_tx=owner_tx,
                    held_since=now,
                    expires_at=expires_at,
                ).on_conflict_do_nothing(index_elements=["resource_key"])
            result = await conn.execute(stmt)
            # 若冲突（并发抢锁），回读检查 owner
            if result.rowcount == 0:
                got = (
                    await conn.execute(
                        select(_LockRow).where(_LockRow.resource_key == resource_key)
                    )
                ).first()
                if got is not None and got.owner_tx == owner_tx:
                    return LockRecord(
                        resource_key=got.resource_key,
                        version=got.version,
                        owner_tx=got.owner_tx,
                        held_since=got.held_since,
                        expires_at=got.expires_at,
                    )
                return None

        return LockRecord(
            resource_key=resource_key,
            version=0,
            owner_tx=owner_tx,
            held_since=now,
            expires_at=expires_at,
        )

    async def compare_and_swap(
        self, resource_key: str, expected_version: int, owner_tx: str
    ) -> bool:
        assert self._engine is not None
        from sqlalchemy import update

        async with self._engine.begin() as conn:
            result = await conn.execute(
                update(_LockRow)
                .where(
                    (_LockRow.resource_key == resource_key)
                    & (_LockRow.owner_tx == owner_tx)
                    & (_LockRow.version == expected_version)
                )
                .values(version=expected_version + 1)
            )
            return result.rowcount > 0

    async def release_lock(self, resource_key: str, owner_tx: str) -> bool:
        assert self._engine is not None
        from sqlalchemy import delete

        async with self._engine.begin() as conn:
            result = await conn.execute(
                delete(_LockRow).where(
                    (_LockRow.resource_key == resource_key)
                    & (_LockRow.owner_tx == owner_tx)
                )
            )
            return result.rowcount > 0

    async def read_version(self, resource_key: str) -> Optional[int]:
        assert self._engine is not None
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    select(_LockRow).where(_LockRow.resource_key == resource_key)
                )
            ).first()
            if not row:
                return None
            return row.version

    # ---------------- 幂等（M1） ----------------

    async def put_idempotency(self, record: IdempotencyRecord) -> None:
        assert self._engine is not None
        from sqlalchemy import delete

        async with self._engine.begin() as conn:
            await conn.execute(
                delete(_IdempotencyRow).where(
                    _IdempotencyRow.idempotency_key == record.idempotency_key
                )
            )
            await conn.execute(
                insert(_IdempotencyRow).values(
                    idempotency_key=record.idempotency_key,
                    request_hash=record.request_hash,
                    tx_id=record.tx_id,
                    status=record.status,
                    result_json=dumps_json(record.result) if record.result else None,
                    created_at=record.created_at,
                    expires_at=record.expires_at,
                )
            )

    async def get_idempotency(self, key: str) -> Optional[IdempotencyRecord]:
        assert self._engine is not None
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    select(_IdempotencyRow).where(
                        _IdempotencyRow.idempotency_key == key
                    )
                )
            ).first()
            if not row:
                return None
            # 已过期视为不存在
            if row.expires_at is not None and row.expires_at < datetime.now():
                return None
            return IdempotencyRecord(
                idempotency_key=row.idempotency_key,
                request_hash=row.request_hash,
                tx_id=row.tx_id,
                status=row.status,
                result=loads_json(row.result_json) if row.result_json else None,
                created_at=row.created_at,
                expires_at=row.expires_at,
            )

    async def delete_expired_idempotency(self) -> int:
        assert self._engine is not None
        from sqlalchemy import delete

        async with self._engine.begin() as conn:
            result = await conn.execute(
                delete(_IdempotencyRow).where(
                    _IdempotencyRow.expires_at < datetime.now()
                )
            )
            return result.rowcount

    # ---------------- DLQ（M1） ----------------

    async def enqueue_dlq(self, entry: DLQEntry) -> None:
        assert self._engine is not None
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(_DLQRow).values(
                    tx_id=entry.tx_id,
                    action_name=entry.action_name,
                    error=entry.error,
                    attempts=entry.attempts,
                    status=entry.status,
                    created_at=entry.created_at,
                    resolved_at=entry.resolved_at,
                )
            )

    async def list_dlq(
        self, limit: int = 100, status: str = "open"
    ) -> List[DLQEntry]:
        assert self._engine is not None
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(_DLQRow)
                    .where(_DLQRow.status == status)
                    .order_by(_DLQRow.created_at.asc())
                    .limit(limit)
                )
            ).all()
            return [
                DLQEntry(
                    tx_id=r.tx_id,
                    action_name=r.action_name,
                    error=r.error,
                    attempts=r.attempts,
                    status=r.status,
                    created_at=r.created_at,
                    resolved_at=r.resolved_at,
                )
                for r in rows
            ]
