"""core/logging 结构化日志测试"""
import json
import logging

from symphony.core.logging import JsonFormatter, get_logger, setup_logging


class TestLogging:
    def test_get_logger(self):
        logger = get_logger("core.llm")
        assert logger.name == "symphony.core.llm"

    def test_setup_logging_no_error(self):
        # 配置不应抛错
        setup_logging(level="DEBUG", json_format=False)
        logger = get_logger("test")
        logger.debug("debug msg")
        logger.info("info msg")

    def test_json_formatter(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname=__file__,
            lineno=1, msg="hello", args=None, exc_info=None)
        output = formatter.format(record)
        data = json.loads(output)
        assert data["message"] == "hello"
        assert data["level"] == "INFO"

    def test_json_formatter_with_extra(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname=__file__,
            lineno=1, msg="event", args=None, exc_info=None)
        record.session_id = "s-123"
        record.step = 3
        output = formatter.format(record)
        data = json.loads(output)
        assert data["session_id"] == "s-123"
        assert data["step"] == 3
