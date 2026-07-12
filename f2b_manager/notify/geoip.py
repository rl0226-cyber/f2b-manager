"""
f2b_manager.notify.geoip
========================

IP 归属地查询。

优先使用本地 maxminddb GeoLite2-Country 数据库，若文件不存在或查询失败，
自动回退到 ip-api.com 在线 API。

流量控制:
- 私有 IP（127.x, 10.x, 192.168.x, 172.16-31.x）直接返回空结果，不查询
- ip-api.com 免费版限速 45 次/分钟，本模块不额外限速（由调用方去重逻辑兜底）
"""

from __future__ import annotations

import ipaddress
import logging
import os
from pathlib import Path
from typing import Optional

# 默认 GeoIP 数据库路径
_GEOIP_DB_PATH = "/var/lib/GeoIP/GeoLite2-Country.mmdb"

from ..storage.models import GeoInfo

logger = logging.getLogger("notify.geoip")


def _country_code_to_flag(code: str) -> str:
    """将两位国家代码转换为国旗 emoji。

    使用 Unicode Regional Indicator Symbols (U+1F1E6 - U+1F1FF)。
    """
    if not code or len(code) != 2:
        return ""
    code = code.upper()
    offset = 0x1F1E6 - ord("A")
    try:
        return chr(ord(code[0]) + offset) + chr(ord(code[1]) + offset)
    except (ValueError, IndexError):
        return ""


def _is_private_ip(ip: str) -> bool:
    """判断是否为私有/内网 IP 地址，这类地址不需要查询归属地。"""
    try:
        addr = ipaddress.ip_address(ip)
        return addr.is_private or addr.is_loopback or addr.is_link_local
    except ValueError:
        return True  # 无效 IP 也视为私有，不查询


class GeoIPLookup:
    """IP 归属地查询器。

    双模式查询:
    - local: 使用本地 maxminddb 文件（推荐，零延迟）
    - api: 直接调用 ip-api.com 在线 API

    当 local 模式查询失败时自动回退到 api 模式。
    """

    def __init__(self, db_path: str = "/var/lib/GeoIP/GeoLite2-Country.mmdb",
                 method: str = "local"):
        """
        Args:
            db_path: maxminddb 数据库文件路径
            method: 查询方式 ("local" / "api")
        """
        self._db_path = db_path
        self._method = method
        self._reader: Optional[object] = None  # maxminddb.Reader 实例
        self._reader_loaded = False

        if method == "local":
            self._init_local_db()

    def _init_local_db(self) -> None:
        """尝试加载本地 mmdb 数据库。"""
        try:
            import maxminddb
        except ImportError:
            logger.warning("maxminddb 库未安装，将使用 API 模式回退")
            return

        db_file = Path(self._db_path)
        if not db_file.exists():
            logger.warning("GeoIP 数据库文件不存在: %s，将使用 API 模式回退",
                           self._db_path)
            return

        try:
            self._reader = maxminddb.open_database(str(db_file))
            self._reader_loaded = True
            logger.info("已加载本地 GeoIP 数据库: %s", self._db_path)
        except Exception as e:
            logger.warning("无法打开 GeoIP 数据库 %s: %s，将使用 API 模式回退",
                           self._db_path, e)

    def _lookup_local(self, ip: str) -> Optional[GeoInfo]:
        """通过本地 mmdb 查询 IP 归属地。"""
        if not self._reader_loaded or self._reader is None:
            return None

        try:
            result = self._reader.get(ip)
            if result is None:
                return None

            country_info = result.get("country", {})
            if not country_info:
                return None

            iso_code = country_info.get("iso_code", "")
            country_name = country_info.get("names", {}).get("zh-CN", "")
            if not country_name:
                country_name = country_info.get("names", {}).get("en", "")

            return GeoInfo(
                country=country_name or iso_code,
                country_code=iso_code,
                flag=_country_code_to_flag(iso_code),
            )
        except Exception as e:
            logger.debug("本地 GeoIP 查询失败 ip=%s: %s", ip, e)
            return None

    async def _lookup_api(self, ip: str) -> Optional[GeoInfo]:
        """通过 ip-api.com 免费 API 查询 IP 归属地。

        免费版限制:
        - 45 次/分钟
        - 不支持 HTTPS（免费 HTTP 版本）
        - 单次请求最多约 150 个 IP 批量查询（本模块按单个 IP 请求）
        """
        try:
            import httpx
        except ImportError:
            logger.warning("httpx 未安装，无法查询 IP 归属地")
            return None

        url = f"http://ip-api.com/json/{ip}?fields=country,countryCode&lang=zh-CN"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.debug("ip-api.com 返回 %d for ip=%s",
                                 resp.status_code, ip)
                    return None

                data = resp.json()
                if data.get("status") == "fail":
                    logger.debug("ip-api.com 查询失败 ip=%s: %s",
                                 ip, data.get("message", ""))
                    return None

                country = data.get("country", "")
                country_code = data.get("countryCode", "")
                return GeoInfo(
                    country=country,
                    country_code=country_code,
                    flag=_country_code_to_flag(country_code),
                )
        except Exception as e:
            logger.debug("ip-api.com 请求异常 ip=%s: %s", ip, e)
            return None

    async def lookup(self, ip: str) -> GeoInfo:
        """查询 IP 归属地。

        Args:
            ip: IP 地址字符串

        Returns:
            GeoInfo: 查询结果。若查询失败（私有 IP / 网络异常 / 无数据），
                     返回空的 GeoInfo (country/country_code/flag 均为空字符串)。
        """
        # 私有 IP 直接跳过
        if _is_private_ip(ip):
            logger.debug("跳过私有 IP 查询: %s", ip)
            return GeoInfo()

        # 优先本地 mmdb
        if self._method == "local" and self._reader_loaded:
            result = self._lookup_local(ip)
            if result is not None:
                return result
            logger.debug("本地查询失败，回退到 API 模式 ip=%s", ip)

        # 回退到在线 API
        result = await self._lookup_api(ip)
        if result is not None:
            return result

        # 所有方式都失败，返回空结果
        logger.debug("无法获取 IP 归属地: %s", ip)
        return GeoInfo()

    def close(self) -> None:
        """关闭本地 mmdb 数据库连接。"""
        if self._reader is not None:
            try:
                self._reader.close()
            except Exception:
                pass
            self._reader = None
            self._reader_loaded = False

    def __del__(self) -> None:
        """析构时确保关闭连接。"""
        self.close()


def lookup_country_sync(ip: str, db_path: str = _GEOIP_DB_PATH) -> str:
    """同步查询 IP 归属国家（仅在本地数据库可用时）。

    用于 CLI 等同步环境，不调用 API。

    Args:
        ip: IP 地址
        db_path: maxminddb 数据库路径

    Returns:
        "国家名 🇨🇳" 格式的字符串，查询失败返回空字符串
    """
    if _is_private_ip(ip):
        return ""

    try:
        import maxminddb
        if not os.path.exists(db_path):
            return ""
        reader = maxminddb.open_database(db_path)
        try:
            result = reader.get(ip)
            if result and "country" in result:
                country = result["country"].get("names", {}).get("zh-CN", "")
                code = result["country"].get("iso_code", "")
                if country:
                    flag = _country_code_to_flag(code)
                    return f"{country} {flag}" if flag else country
        finally:
            reader.close()
    except Exception:
        pass

    return ""
