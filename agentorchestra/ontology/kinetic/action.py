"""ActionType - 动作类型（对标 Palantir Action type）

动能层：定义组织的写操作能力。
- 参数定义
- 提交前规则校验（rules）
- 执行逻辑
- 副作用（通知/webhook/触发调度）
- 执行审计
"""

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from ...tools.base import ToolParameter


class ActionType:
    """动作类型定义"""

    def __init__(
        self,
        api_name: str,
        parameters: Optional[List[ToolParameter]] = None,
        description: str = "",
        execute_fn: Optional[Callable] = None,
        rules: Optional[List[Callable]] = None,
        side_effects: Optional[List[Callable]] = None,
        display_name: Optional[str] = None,
    ):
        self.api_name = api_name
        self.display_name = display_name or api_name
        self.description = description
        self.parameters: Dict[str, ToolParameter] = {}
        if parameters:
            for p in parameters:
                self.parameters[p.name] = p
        self.execute_fn = execute_fn
        self.rules = rules or []
        self.side_effects = side_effects or []
        self._audit: List[Dict[str, Any]] = []

    def add_parameter(self, prop: ToolParameter) -> "ActionType":
        self.parameters[prop.name] = prop
        return self

    def get_parameters(self) -> List[ToolParameter]:
        return list(self.parameters.values())

    def execute(self, params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        """执行动作：参数校验 → 规则校验 → 执行 → 副作用 → 审计"""
        errors = []

        # ① 参数必填校验
        for p in self.parameters.values():
            if p.required and (p.name not in params or params[p.name] in (None, "")):
                errors.append(f"缺少必填参数: {p.name}")

        # ② 规则校验
        if not errors:
            for rule in self.rules:
                try:
                    rule_error = rule(params, ctx)
                    if rule_error:
                        errors.append(str(rule_error))
                except Exception as e:
                    errors.append(f"规则校验异常: {e}")

        if errors:
            return {"success": False, "result": None, "errors": errors}

        # ③ 执行
        try:
            if not self.execute_fn:
                raise ValueError(f"动作 '{self.api_name}' 未定义 execute_fn")
            result = self.execute_fn(params, ctx)
        except Exception as e:
            errors.append(f"动作执行失败: {e}")
            self._record_audit(params, ctx, False, errors)
            return {"success": False, "result": None, "errors": errors}

        # ④ 副作用
        for effect in self.side_effects:
            try:
                effect(result, ctx)
            except Exception as e:
                errors.append(f"副作用异常: {e}")

        # ⑤ 审计
        self._record_audit(params, ctx, True, errors)

        # 观测埋点：动作指标 + 追踪
        try:
            from agentorchestra.core.metrics import get_metrics
            from agentorchestra.core.tracing import get_tracer
            get_metrics().record_action_execution(self.api_name)
            with get_tracer().span("action.execute", {"action": self.api_name}):
                pass
        except Exception:
            pass

        return {"success": True, "result": result, "errors": errors}

    def _record_audit(self, params, ctx, success, errors):
        self._audit.append({
            "action": self.api_name,
            "timestamp": datetime.now().isoformat(),
            "params": params,
            "success": success,
            "errors": list(errors),
            "principal": (ctx or {}).get("principal", "unknown"),
        })

    def get_audit(self) -> List[Dict[str, Any]]:
        return list(self._audit)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "api_name": self.api_name,
            "display_name": self.display_name,
            "description": self.description,
            "parameters": [p.to_dict() for p in self.parameters.values()],
            "rules_count": len(self.rules),
            "side_effects_count": len(self.side_effects),
            "audit_count": len(self._audit),
        }

    def __repr__(self) -> str:
        return f"ActionType({self.api_name})"
