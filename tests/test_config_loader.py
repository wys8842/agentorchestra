"""core/config_loader 配置加载测试"""
import json

from symphony.core.config import Config
from symphony.core.config_loader import ConfigLoader


class TestConfigLoader:
    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("SYMPHONY_DEFAULT_MODEL", "gpt-4o")
        monkeypatch.setenv("SYMPHONY_DEBUG", "true")
        monkeypatch.setenv("SYMPHONY_TEMPERATURE", "0.3")

        data = ConfigLoader.from_env("SYMPHONY_")
        assert data.get("default_model") == "gpt-4o"
        assert data.get("debug") == "true"
        assert data.get("temperature") == "0.3"

    def test_from_file(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "default_model": "claude-3",
            "debug": True,
            "trace_enabled": False,
        }), encoding="utf-8")

        data = ConfigLoader.from_file(str(config_file))
        assert data["default_model"] == "claude-3"
        assert data["trace_enabled"] is False

    def test_from_file_missing(self):
        assert ConfigLoader.from_file("/nonexistent/config.json") == {}

    def test_load_precedence(self, monkeypatch, tmp_path):
        """优先级：显式 > 文件 > env"""
        monkeypatch.setenv("SYMPHONY_DEFAULT_MODEL", "env-model")
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"default_model": "file-model"}), encoding="utf-8")

        # 无显式 → 用文件
        config = ConfigLoader.load(Config, str(config_file), "SYMPHONY_")
        assert config.default_model == "file-model"

        # 显式覆盖文件
        config2 = ConfigLoader.load(Config, str(config_file), "SYMPHONY_",
                                    default_model="explicit-model")
        assert config2.default_model == "explicit-model"

    def test_sanitize(self):
        config_dict = {
            "api_key": "sk-secret",
            "default_model": "gpt-4o",
            "llm_api_key": "another-secret",
            "temperature": 0.7,
        }
        sanitized = ConfigLoader.sanitize(config_dict)
        assert sanitized["api_key"] == "***"
        assert sanitized["llm_api_key"] == "***"
        assert sanitized["default_model"] == "gpt-4o"
        assert sanitized["temperature"] == 0.7


class TestConfig:
    def test_from_env_prefix(self, monkeypatch):
        monkeypatch.setenv("SYMPHONY_DEFAULT_MODEL", "gpt-4o")
        config = Config.from_env("SYMPHONY_")
        assert config.default_model == "gpt-4o"

    def test_from_file(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"debug": True}), encoding="utf-8")
        config = Config.from_file(str(config_file))
        assert config.debug is True

    def test_sanitized_dict(self):
        config = Config()
        # 手动注入敏感字段验证脱敏
        raw = config.to_dict()
        raw["api_key"] = "sk-secret"
        sanitized = ConfigLoader.sanitize(raw)
        assert sanitized["api_key"] == "***"
