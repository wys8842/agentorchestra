"""core 核心层测试"""

from agentorchestra.core.config import Config
from agentorchestra.core.exceptions import (
    ConfigException,
    LLMException,
    OntologyException,
    SymphonyException,
)
from agentorchestra.core.message import Message


class TestMessage:
    def test_create_message(self):
        msg = Message("你好", "user")
        assert msg.content == "你好"
        assert msg.role == "user"
        assert msg.timestamp is not None

    def test_to_dict(self):
        msg = Message("hello", "assistant")
        data = msg.to_dict()
        assert data["role"] == "assistant"
        assert data["content"] == "hello"
        assert "timestamp" in data

    def test_from_dict(self):
        data = {"role": "user", "content": "hi"}
        msg = Message.from_dict(data)
        assert msg.content == "hi"
        assert msg.role == "user"

    def test_to_text(self):
        msg = Message("abc", "user")
        assert msg.to_text() == "[user] abc"


class TestConfig:
    def test_default_config(self):
        config = Config()
        assert config.default_model == "gpt-3.5-turbo"
        assert config.context_window == 128000
        assert config.trace_enabled is True
        assert config.ontology_engine_enabled is False

    def test_config_custom(self):
        config = Config(default_model="gpt-4o", trace_enabled=False)
        assert config.default_model == "gpt-4o"
        assert config.trace_enabled is False

    def test_to_dict(self):
        config = Config()
        data = config.to_dict()
        assert "default_model" in data
        assert "context_window" in data


class TestExceptions:
    def test_base_exception(self):
        e = SymphonyException("test", error_code="TEST")
        assert e.message == "test"
        assert e.error_code == "TEST"
        assert e.to_dict() == {"error_code": "TEST", "message": "test"}

    def test_exception_hierarchy(self):
        assert issubclass(ConfigException, SymphonyException)
        assert issubclass(LLMException, SymphonyException)
        assert issubclass(OntologyException, SymphonyException)

    def test_default_codes(self):
        assert ConfigException().error_code == "CONFIG_ERROR"
        assert LLMException().error_code == "LLM_ERROR"
        assert OntologyException().error_code == "ONTOLOGY_ERROR"
