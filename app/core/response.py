"""统一响应包裹：{"code": 0, "message": "ok", "data": ...}"""


def ok(data=None, message: str = "ok") -> dict:
    return {"code": 0, "message": message, "data": data}
