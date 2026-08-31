"""core/retry 重试机制测试"""
import time

import pytest

from symphony.core.exceptions import SymphonyException
from symphony.core.retry import RetryManager, retry_with_backoff


class TestRetryWithBackoff:
    def test_success_first_try(self):
        calls = []

        @retry_with_backoff(max_retries=3, base_delay=0)
        def fn():
            calls.append(1)
            return "ok"

        assert fn() == "ok"
        assert len(calls) == 1  # 一次成功，不重试

    def test_retry_until_success(self):
        calls = []

        @retry_with_backoff(max_retries=3, base_delay=0)
        def fn():
            calls.append(1)
            if len(calls) < 3:
                raise SymphonyException("临时错误")
            return "recovered"

        assert fn() == "recovered"
        assert len(calls) == 3  # 第3次成功

    def test_exhaust_retries_raises(self):
        calls = []

        @retry_with_backoff(max_retries=2, base_delay=0)
        def fn():
            calls.append(1)
            raise SymphonyException("总是失败")

        with pytest.raises(SymphonyException):
            fn()
        assert len(calls) == 3  # 1次尝试 + 2次重试


class TestRetryManager:
    def test_success(self):
        manager = RetryManager(max_retries=3, base_delay=0)
        assert manager.execute(lambda: "ok") == "ok"
        assert manager.retry_count == 0

    def test_retry_and_succeed(self):
        manager = RetryManager(max_retries=3, base_delay=0)
        calls = []

        def fn():
            calls.append(1)
            if len(calls) < 2:
                raise SymphonyException("失败")
            return "done"

        assert manager.execute(fn) == "done"
        assert manager.retry_count == 1

    def test_all_fail_raises(self):
        manager = RetryManager(max_retries=2, base_delay=0)

        def fn():
            raise SymphonyException("总是失败")

        with pytest.raises(SymphonyException):
            manager.execute(fn)

    def test_reset(self):
        manager = RetryManager(max_retries=2, base_delay=0)
        calls = []

        def fn():
            calls.append(1)
            if len(calls) < 2:
                raise SymphonyException("x")
            return "ok"

        manager.execute(fn)
        assert manager.retry_count == 1
        manager.reset()
        assert manager.retry_count == 0

    def test_backoff_delay_increases(self):
        """验证退避延迟递增"""
        start = time.time()
        manager = RetryManager(max_retries=3, base_delay=0.1, backoff_factor=2.0)
        calls = []

        def fn():
            calls.append(1)
            raise SymphonyException("x")

        with pytest.raises(SymphonyException):
            manager.execute(fn)
        elapsed = time.time() - start
        # 延迟 = 0.1 + 0.2 = 0.3（指数退避）
        assert elapsed >= 0.3
