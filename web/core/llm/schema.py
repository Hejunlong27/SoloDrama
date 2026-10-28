# -*- coding: utf-8 -*-
"""极简 JSON Schema 校验器（只覆盖本仓库实际用到的关键字）

为什么不拉 `jsonschema`：本项目纪律是「零新增依赖优先」（requirements 只锁
httpx + Pillow）。这份校验器约 140 行，覆盖 type / required / properties /
additionalProperties / items / enum / 数值与长度边界，够用且可离线回归。

支持的关键字（超出范围一律**忽略**而不是报错，避免模板里多写一个关键字就炸）：
  type, required, properties, additionalProperties, items, enum,
  minLength, maxLength, minimum, maximum, minItems, maxItems

`type` 接受字符串或字符串列表；`"integer"` 严格要求 int（`4.0` 视为 number 不算 integer）。
"""
from __future__ import annotations

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


def _type_ok(value, want) -> bool:
    if want == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if want == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if want == "boolean":
        return isinstance(value, bool)
    py = _TYPES.get(want)
    if py is None:
        return True
    if want in ("object", "array", "string"):
        return isinstance(value, py)
    return isinstance(value, py)


def _ptr(path, key) -> str:
    if isinstance(key, int):
        return "%s[%d]" % (path or "$", key)
    return "%s.%s" % (path, key) if path else str(key)


def validate(data, schema, path=""):
    """返回错误列表；空列表表示通过。每项形如 {path, message}。"""
    errs = []
    if not isinstance(schema, dict):
        return errs

    want = schema.get("type")
    if want is not None:
        names = want if isinstance(want, list) else [want]
        if not any(_type_ok(data, n) for n in names):
            errs.append({"path": path or "$", "message": "类型应为 %s，实际是 %s"
                         % ("/".join(names), type(data).__name__)})
            return errs  # 类型不对就不要再往下钻，否则报错会刷屏

    if "enum" in schema and data not in schema["enum"]:
        errs.append({"path": path or "$", "message": "取值必须是 %s 之一" % (schema["enum"],)})

    if isinstance(data, str):
        if isinstance(schema.get("minLength"), int) and len(data) < schema["minLength"]:
            errs.append({"path": path or "$", "message": "长度不得小于 %d（当前 %d）"
                         % (schema["minLength"], len(data))})
        if isinstance(schema.get("maxLength"), int) and len(data) > schema["maxLength"]:
            errs.append({"path": path or "$", "message": "长度不得超过 %d（当前 %d）"
                         % (schema["maxLength"], len(data))})

    if isinstance(data, (int, float)) and not isinstance(data, bool):
        if isinstance(schema.get("minimum"), (int, float)) and data < schema["minimum"]:
            errs.append({"path": path or "$", "message": "不得小于 %s" % schema["minimum"]})
        if isinstance(schema.get("maximum"), (int, float)) and data > schema["maximum"]:
            errs.append({"path": path or "$", "message": "不得大于 %s" % schema["maximum"]})

    if isinstance(data, list):
        if isinstance(schema.get("minItems"), int) and len(data) < schema["minItems"]:
            errs.append({"path": path or "$", "message": "至少需要 %d 项（当前 %d）"
                         % (schema["minItems"], len(data))})
        if isinstance(schema.get("maxItems"), int) and len(data) > schema["maxItems"]:
            errs.append({"path": path or "$", "message": "最多 %d 项（当前 %d）"
                         % (schema["maxItems"], len(data))})
        items = schema.get("items")
        if isinstance(items, dict):
            for i, v in enumerate(data):
                errs.extend(validate(v, items, _ptr(path, i)))

    if isinstance(data, dict):
        props = schema.get("properties") or {}
        for key in (schema.get("required") or []):
            # 只把「不存在 / null / 空串」算缺失；空数组交给 minItems 判，
            # 否则一个空数组会同时报两条，读者要自己推理哪条才是真的。
            if key not in data or data[key] is None or data[key] == "":
                errs.append({"path": _ptr(path, key), "message": "必填字段缺失或为空"})
        for key, val in data.items():
            if key in props:
                errs.extend(validate(val, props[key], _ptr(path, key)))
            else:
                extra = schema.get("additionalProperties", True)
                if extra is False:
                    errs.append({"path": _ptr(path, key), "message": "不允许的额外字段"})
                elif isinstance(extra, dict):
                    errs.extend(validate(val, extra, _ptr(path, key)))
    return errs
