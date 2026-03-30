"""People agent — Phonetool lookups, org charts."""

import json
from typing import List, Dict
from envoy_logger import get_logger
from agents.base import builder


async def get_direct_reports(manager_alias: str) -> List[Dict[str, str]]:
    async with builder() as session:
        result = await session.call_tool(
            "ReadInternalWebsites",
            arguments={"inputs": [f"https://phonetool.amazon.com/users/{manager_alias}"]}
        )
        directs = []
        content = str(result.content[0].text) if result.content else ''
        try:
            data = json.loads(content)
            if 'content' in data and 'content' in data['content']:
                for dr in data['content']['content'].get('direct_reports', []):
                    alias = dr.get('login')
                    if alias:
                        directs.append({'alias': alias, 'name': dr.get('name', alias)})
        except Exception as e:
            get_logger().log_error(f"Error parsing phonetool data: {e}")
        return directs


async def get_management_chain(alias: str, levels: int = 3) -> List[Dict[str, str]]:
    async with builder() as session:
        managers = []
        current_alias = alias
        for level in range(levels):
            try:
                result = await session.call_tool(
                    "ReadInternalWebsites",
                    arguments={"inputs": [f"https://phonetool.amazon.com/users/{current_alias}"]}
                )
                content = str(result.content[0].text) if result.content else ''
                data = json.loads(content)
                if 'content' not in data or 'content' not in data['content']:
                    break
                phonetool_data = data['content']['content']
                manager = phonetool_data.get('manager')
                if not manager:
                    break
                manager_login = manager.get('login') if isinstance(manager, dict) else manager
                if not manager_login:
                    break
                mgr_result = await session.call_tool(
                    "ReadInternalWebsites",
                    arguments={"inputs": [f"https://phonetool.amazon.com/users/{manager_login}"]}
                )
                mgr_content = str(mgr_result.content[0].text) if mgr_result.content else ''
                mgr_data = json.loads(mgr_content)
                if 'content' not in mgr_data or 'content' not in mgr_data['content']:
                    break
                mgr_info = mgr_data['content']['content']
                managers.append({'alias': manager_login, 'name': mgr_info.get('name', manager_login)})
                current_alias = manager_login
            except Exception as e:
                get_logger().log_error(f"Level {level+1}: Error fetching manager chain: {e}")
                break
        return managers
