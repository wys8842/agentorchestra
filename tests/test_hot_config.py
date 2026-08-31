"""core/hot_config 配置热更新测试"""
import json

from symphony.core.config import Config
from symphony.core.hot_config import ConfigWatch


class TestConfigWatch:
    def test_initial_load(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"debug": True}), encoding="utf-8")
        watch = ConfigWatch(Config, str(config_file))
        assert watch.config.debug is True

    def test_change_detection(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"debug": False}), encoding="utf-8")
        watch = ConfigWatch(Config, str(config_file))

        # 修改文件
        config_file.write_text(json.dumps({"debug": True}), encoding="utf-8")
        changed = watch.check_once()
        assert changed is True
        assert watch.config.debug is True

    def test_no_change(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"debug": False}), encoding="utf-8")
        watch = ConfigWatch(Config, str(config_file))
        assert watch.check_once() is False

    def test_callback(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"debug": False}), encoding="utf-8")
        watch = ConfigWatch(Config, str(config_file))

        callbacks = []
        watch.on_change(lambda old_c, new_c: callbacks.append((old_c.debug, new_c.debug)))

        config_file.write_text(json.dumps({"debug": True}), encoding="utf-8")
        watch.check_once()
        assert len(callbacks) == 1
        assert callbacks[0] == (False, True)

    def test_missing_file(self, tmp_path):
        watch = ConfigWatch(Config, str(tmp_path / "missing.json"))
        assert watch.config.debug is False  # 默认值
