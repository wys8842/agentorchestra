"""Scheduler - 调度器（定时触发动作/工作流）

支持两种调度方式：
- interval: 固定间隔重复触发（如每 5 分钟）
- once: 延迟一次触发（如 10 秒后）

后台线程运行，可启动/停止/查询任务。
"""

import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional


class ScheduledTask:
    """定时任务定义"""

    def __init__(self, name: str, target: Callable, schedule_type: str,
                 interval_seconds: Optional[float] = None,
                 delay_seconds: Optional[float] = None,
                 params: Optional[Dict[str, Any]] = None,
                 max_runs: Optional[int] = None):
        """定义定时任务

        Args:
            name: 任务名
            target: 要执行的函数（无参或接收 params）
            schedule_type: interval / once
            interval_seconds: interval 模式的间隔秒数
            delay_seconds: once 模式的延迟秒数
            params: 传给 target 的参数
            max_runs: 最大执行次数（None=无限）
        """
        self.name = name
        self.target = target
        self.schedule_type = schedule_type
        self.interval_seconds = interval_seconds
        self.delay_seconds = delay_seconds
        self.params = params or {}
        self.max_runs = max_runs
        self.run_count = 0
        self.last_run_at: Optional[str] = None
        self.last_result: Any = None
        self.last_error: Optional[str] = None
        self.enabled = True

    def should_run(self, now: datetime) -> bool:
        """判断当前时刻是否应执行"""
        if not self.enabled:
            return False
        if self.max_runs is not None and self.run_count >= self.max_runs:
            return False

        if self.schedule_type == "interval":
            # 首次立即执行，之后按间隔
            if self.last_run_at is None:
                return True
            last = datetime.fromisoformat(self.last_run_at)
            elapsed = (now - last).total_seconds()
            return elapsed >= (self.interval_seconds or 0)

        elif self.schedule_type == "once":
            if self.run_count > 0:
                return False
            if self.last_run_at is not None:
                return False
            return True  # 由调度器在延迟后触发

        return False


class Scheduler:
    """定时调度器（后台线程）"""

    def __init__(self, tick_seconds: float = 1.0):
        """初始化调度器

        Args:
            tick_seconds: 调度检查间隔（秒）
        """
        self.tick_seconds = tick_seconds
        self._tasks: Dict[str, ScheduledTask] = {}
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()
        self._pending_once: Dict[str, float] = {}  # once 任务的触发时刻

    # ==================== 任务管理 ====================

    def add_interval(self, name: str, target: Callable, interval_seconds: float,
                     params: Optional[Dict] = None, max_runs: Optional[int] = None) -> ScheduledTask:
        """添加间隔任务"""
        task = ScheduledTask(name, target, "interval",
                             interval_seconds=interval_seconds,
                             params=params, max_runs=max_runs)
        self._tasks[name] = task
        return task

    def add_once(self, name: str, target: Callable, delay_seconds: float,
                 params: Optional[Dict] = None) -> ScheduledTask:
        """添加一次性延迟任务"""
        task = ScheduledTask(name, target, "once", delay_seconds=delay_seconds,
                             params=params, max_runs=1)
        self._tasks[name] = task
        return task

    def remove_task(self, name: str) -> bool:
        """移除任务，返回是否移除成功"""
        if name in self._tasks:
            del self._tasks[name]
            return True
        return False

    def list_tasks(self) -> List[Dict[str, Any]]:
        """列出全部任务的状态摘要"""
        return [{
            "name": t.name,
            "type": t.schedule_type,
            "run_count": t.run_count,
            "last_run_at": t.last_run_at,
            "enabled": t.enabled,
        } for t in self._tasks.values()]

    # ==================== 运行控制 ====================

    def start(self) -> None:
        """启动调度器（后台线程）"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True,
                                        name="ontology-scheduler")
        self._thread.start()

    def stop(self) -> None:
        """停止调度器"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def is_running(self) -> bool:
        """调度器是否在运行"""
        return self._running

    # ==================== 内部 ====================

    def _run_loop(self) -> None:
        """调度主循环"""
        while self._running:
            now = datetime.now()
            with self._lock:
                for task in list(self._tasks.values()):
                    try:
                        self._check_task(task, now)
                    except Exception:
                        pass
            time.sleep(self.tick_seconds)

    def _check_task(self, task: ScheduledTask, now: datetime) -> None:
        """检查并执行单个任务"""
        # once 模式：到达延迟时间后触发
        if task.schedule_type == "once":
            if not task.enabled:
                return
            if task.last_run_at is None:
                if task.name not in self._pending_once:
                    self._pending_once[task.name] = time.time() + (task.delay_seconds or 0)
                due = self._pending_once.get(task.name, 0)
                if time.time() >= due:
                    self._execute(task)
                    self._pending_once.pop(task.name, None)
            return

        # interval / cron_at：按 should_run 判断
        if task.should_run(now):
            self._execute(task)

    def _execute(self, task: ScheduledTask) -> None:
        """执行任务"""
        try:
            result = task.target(task.params)
            task.last_result = result
            task.last_error = None
        except Exception as e:
            task.last_error = str(e)
            task.last_result = None
        finally:
            task.run_count += 1
            task.last_run_at = datetime.now().isoformat()

    def run_once_now(self, name: str) -> Any:
        """立即执行一次任务（不等待调度）"""
        task = self._tasks.get(name)
        if not task:
            raise ValueError(f"任务不存在: {name}")
        self._execute(task)
        return task.last_result
