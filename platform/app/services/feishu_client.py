"""飞书 API 客户端 — 获取用户信息和部门信息。

移植自 agentgateway auth-service/services/feishu_client.py，凭证源改为从
``app.config.settings`` 读取（不再硬编码 / 模块级常量）。底层仍用 ``httpx``，
不引入新的网络库。

公开 5 个异步函数：
    - get_app_access_token() -> str
    - code_to_user_access_token(code) -> dict
    - get_user_info(user_access_token) -> dict
    - get_user_department(user_id, token) -> str
    - get_full_user_info(code) -> {sub, name, email, department, position, avatar}
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# 部门映射兜底：当通讯录 API 无权限时，从配置文件读取 open_id → department 映射
_DEPT_MAP_FILE = Path(__file__).parent.parent / "department_map.json"


def _load_dept_map() -> dict:
    """读取 department_map.json 作为部门名兜底（文件不存在则返回空 dict）。"""
    if _DEPT_MAP_FILE.exists():
        try:
            return json.loads(_DEPT_MAP_FILE.read_text())
        except (OSError, ValueError):
            return {}
    return {}


def _raise_feishu_api_error(action: str, data: dict) -> None:
    """抛出带上下文的异常，不泄露敏感字段（如 app_secret）。"""
    code = data.get("code")
    msg = data.get("msg")
    details = []
    if code is not None:
        details.append(f"code={code}")
    if msg:
        details.append(f"msg={msg}")
    suffix = f" ({', '.join(details)})" if details else ""
    raise Exception(f"{action}失败，请稍后重试{suffix}")


async def get_app_access_token() -> str:
    """获取应用级别的 access_token（调通讯录 API 用）。"""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{settings.feishu_base_url}/auth/v3/app_access_token/internal",
            json={
                "app_id": settings.feishu_app_id,
                "app_secret": settings.feishu_app_secret,
            },
        )
        data = resp.json()
        if data.get("code") != 0:
            _raise_feishu_api_error("获取 app_access_token", data)
        return data["app_access_token"]


async def code_to_user_access_token(code: str, app_access_token: str | None = None) -> dict:
    """用授权码换取 user_access_token（OIDC）。

    ``app_access_token`` 可选传入以复用已取到的应用令牌，避免在
    ``get_full_user_info`` 中重复请求 ``app_access_token``。
    """
    app_token = app_access_token if app_access_token is not None else await get_app_access_token()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{settings.feishu_base_url}/authen/v1/oidc/access_token",
            headers={"Authorization": f"Bearer {app_token}"},
            json={"grant_type": "authorization_code", "code": code},
        )
        data = resp.json()
        if data.get("code") != 0:
            _raise_feishu_api_error("code 换 token", data)
        return data["data"]


async def get_user_info(user_access_token: str) -> dict:
    """用 user_access_token 获取用户基本信息。"""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{settings.feishu_base_url}/authen/v1/user_info",
            headers={"Authorization": f"Bearer {user_access_token}"},
        )
        data = resp.json()
        if data.get("code") != 0:
            _raise_feishu_api_error("获取用户信息", data)
        return data["data"]


async def get_user_department(user_id: str, token: str) -> str:
    """通过通讯录 API 获取用户的部门名称；失败时兜底返回 ``"unknown"``。"""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{settings.feishu_base_url}/contact/v3/users/{user_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "user_id_type": "open_id",
                "department_id_type": "open_department_id",
            },
        )
        data = resp.json()
        if data.get("code") != 0:
            return "unknown"

        user_data = data.get("data", {}).get("user", {})
        dept_ids = user_data.get("department_ids", [])
        if not dept_ids:
            return "unknown"

        # 查第一个部门的名称
        dept_resp = await client.get(
            f"{settings.feishu_base_url}/contact/v3/departments/{dept_ids[0]}",
            headers={"Authorization": f"Bearer {token}"},
            params={"department_id_type": "open_department_id"},
        )
        dept_data = dept_resp.json()
        if dept_data.get("code") != 0:
            return "unknown"

        return dept_data.get("data", {}).get("department", {}).get("name", "unknown")


async def get_full_user_info(code: str) -> dict:
    """完整流程：授权码 → 用户信息 + 部门，返回用于 JWT claims 的字典。"""
    # 1. app_access_token（取一次，后续复用，避免重复请求）
    app_token = await get_app_access_token()

    # 2. code → user_access_token（复用 app_token）
    token_data = await code_to_user_access_token(code, app_access_token=app_token)
    user_access_token = token_data["access_token"]

    # 3. 获取用户基本信息
    user_info = await get_user_info(user_access_token)

    # 4. 用 app_access_token（应用身份）调通讯录 API 获取部门
    open_id = user_info.get("open_id", "")
    department = await get_user_department(open_id, app_token)
    if department == "unknown":
        dept_map = _load_dept_map()
        department = dept_map.get(open_id, dept_map.get("_default", "unknown"))

    return {
        "sub": user_info.get("open_id", ""),
        "name": user_info.get("name", ""),
        "email": user_info.get("email", ""),
        "department": department,
        "position": user_info.get("job_title", ""),
        "avatar": user_info.get("avatar_url", ""),
    }
