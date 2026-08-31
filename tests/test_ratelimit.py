"""core/ratelimit 限流测试"""
import time

from symphony.core.ratelimit import RateLimiter, SlidingWindow, TokenBucket


class TestTokenBucket:
    def test_capacity_burst(self):
        bucket = TokenBucket(rate=10, capacity=5)
        # 桶满时突发 5 个都能过
        for _ in range(5):
            assert bucket.try_acquire()
        # 桶空，第 6 个失败
        assert not bucket.try_acquire()

    def test_refill(self):
        bucket = TokenBucket(rate=10, capacity=1)
        assert bucket.try_acquire()  # 用掉唯一令牌
        assert not bucket.try_acquire()  # 桶空
        time.sleep(0.15)  # 等 0.15s，速率 10/s → 补充 ~1.5 个
        assert bucket.try_acquire()

    def test_wait_timeout(self):
        bucket = TokenBucket(rate=1, capacity=1)
        assert bucket.try_acquire()  # 用掉
        # 速率 1/s，1 个令牌需 1s，timeout 0.2 应失败
        assert not bucket.wait(timeout=0.2)


class TestSlidingWindow:
    def test_max_requests(self):
        window = SlidingWindow(max_requests=3, window_seconds=10)
        assert window.try_acquire()
        assert window.try_acquire()
        assert window.try_acquire()
        assert not window.try_acquire()  # 超限

    def test_window_expire(self):
        window = SlidingWindow(max_requests=1, window_seconds=0.2)
        assert window.try_acquire()
        assert not window.try_acquire()
        time.sleep(0.25)  # 窗口过期
        assert window.try_acquire()


class TestRateLimiter:
    def test_per_key_limit(self):
        limiter = RateLimiter(default_limit=2, window_seconds=10)
        assert limiter.try_acquire("user_a")
        assert limiter.try_acquire("user_a")
        assert not limiter.try_acquire("user_a")  # user_a 超限
        assert limiter.try_acquire("user_b")  # user_b 独立

    def test_set_limit(self):
        limiter = RateLimiter(default_limit=100, window_seconds=10)
        limiter.set_limit("premium", 1)
        assert limiter.try_acquire("premium")
        assert not limiter.try_acquire("premium")

    def test_reset(self):
        limiter = RateLimiter(default_limit=1, window_seconds=10)
        assert limiter.try_acquire("user_a")
        assert not limiter.try_acquire("user_a")
        limiter.reset("user_a")
        assert limiter.try_acquire("user_a")
