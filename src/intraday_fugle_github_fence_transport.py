"""Bounded GitHub-ref transport for Fugle single-live consumption receipts.

Production-shaped implementation; CI patches HTTPSConnection completely.
Only one exact tag namespace is reachable. No retry, redirect, update, delete,
listing, main mutation, or credential persistence is allowed.
"""
from __future__ import annotations

import http.client
import json
import re
import ssl
from typing import Any, Mapping

REPOSITORY="pili5420/RATE-Data-Engine"
API_HOST="api.github.com"
API_VERSION="2022-11-28"
REF_PREFIX="refs/tags/rate-v11-qualification-consumed/fugle-"
TAG_PREFIX="rate-v11-qualification-consumed/fugle-"
HEX40=re.compile(r"^[0-9a-f]{40}$")
HEX64=re.compile(r"^[0-9a-f]{64}$")
TIMEOUT_SECONDS=10
MAX_RESPONSE_BYTES=512*1024


class FugleGitHubFenceTransportError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise FugleGitHubFenceTransportError(reason)


def _sha40(value: Any, reason: str) -> str:
    text=str(value or "").lower()
    require(bool(HEX40.fullmatch(text)), reason)
    return text


def _sha64(value: Any, reason: str) -> str:
    text=str(value or "").lower()
    require(bool(HEX64.fullmatch(text)), reason)
    return text


def tag_name_for(authorization_sha256: str) -> str:
    value=_sha64(authorization_sha256,"FUGLE_GH_FENCE_AUTH_HASH_INVALID")
    return TAG_PREFIX + value[:32]


def ref_name_for(authorization_sha256: str) -> str:
    return "refs/tags/" + tag_name_for(authorization_sha256)


class FugleGitHubFenceTransport:
    transport="FUGLE_GITHUB_REF_FENCE_V1"

    def __init__(
        self,
        *,
        github_token: str,
        timeout_seconds: int=TIMEOUT_SECONDS,
        max_response_bytes: int=MAX_RESPONSE_BYTES,
    ) -> None:
        require(isinstance(github_token,str) and github_token,
                "FUGLE_GH_FENCE_TOKEN_MISSING")
        require("\r" not in github_token and "\n" not in github_token,
                "FUGLE_GH_FENCE_TOKEN_INVALID")
        require(isinstance(timeout_seconds,int) and 1 <= timeout_seconds <= TIMEOUT_SECONDS,
                "FUGLE_GH_FENCE_TIMEOUT_INVALID")
        require(isinstance(max_response_bytes,int)
                and 1024 <= max_response_bytes <= MAX_RESPONSE_BYTES,
                "FUGLE_GH_FENCE_RESPONSE_LIMIT_INVALID")
        self._token=github_token
        self.timeout_seconds=timeout_seconds
        self.max_response_bytes=max_response_bytes
        self.request_count=0

    def _request(self, method: str, path: str, body: bytes | None=None) -> dict[str,Any]:
        require(method in {"GET","POST"},"FUGLE_GH_FENCE_METHOD_FORBIDDEN")
        require(path.startswith(f"/repos/{REPOSITORY}/git/"),
                "FUGLE_GH_FENCE_PATH_FORBIDDEN")
        require(".." not in path and "%" not in path and "\\" not in path
                and "\r" not in path and "\n" not in path,
                "FUGLE_GH_FENCE_PATH_INVALID")

        payload=body or b""
        require(len(payload) <= 4096,"FUGLE_GH_FENCE_REQUEST_TOO_LARGE")
        context=ssl.create_default_context()
        require(context.check_hostname is True,
                "FUGLE_GH_FENCE_HOSTNAME_VERIFICATION_REQUIRED")
        require(context.verify_mode == ssl.CERT_REQUIRED,
                "FUGLE_GH_FENCE_CERT_VERIFICATION_REQUIRED")

        headers={
            "Accept":"application/vnd.github+json",
            "Authorization":"Bearer " + self._token,
            "X-GitHub-Api-Version":API_VERSION,
            "User-Agent":"RATE-V11-Fugle-Fence/1",
        }
        if payload:
            headers["Content-Type"]="application/json"

        conn=http.client.HTTPSConnection(
            API_HOST,timeout=self.timeout_seconds,context=context
        )
        self.request_count += 1
        try:
            conn.request(method,path,body=payload or None,headers=headers)
            response=conn.getresponse()
            status=int(response.status)
            require(not (300 <= status <= 399),
                    "FUGLE_GH_FENCE_REDIRECT_FORBIDDEN")
            raw=response.read(self.max_response_bytes+1)
            require(len(raw) <= self.max_response_bytes,
                    "FUGLE_GH_FENCE_RESPONSE_TOO_LARGE")
            return {
                "status":status,
                "body":raw,
                "request_count":self.request_count,
                "retry_count":0,
                "redirects_followed":0,
            }
        except FugleGitHubFenceTransportError:
            raise
        except Exception as exc:
            raise FugleGitHubFenceTransportError(
                "FUGLE_GH_FENCE_REQUEST_FAILED:" + type(exc).__name__
            ) from exc
        finally:
            conn.close()

    def read_marker(self, authorization_sha256: str) -> dict[str,Any] | None:
        tag=tag_name_for(authorization_sha256)
        path=f"/repos/{REPOSITORY}/git/ref/tags/{tag}"
        result=self._request("GET",path)
        if result["status"] == 404:
            return None
        require(result["status"] == 200,"FUGLE_GH_FENCE_GET_STATUS_INVALID")
        try:
            value=json.loads(result["body"].decode("utf-8"))
        except (UnicodeError,json.JSONDecodeError) as exc:
            raise FugleGitHubFenceTransportError(
                "FUGLE_GH_FENCE_GET_BODY_INVALID"
            ) from exc
        require(isinstance(value,Mapping),"FUGLE_GH_FENCE_GET_BODY_INVALID")
        ref=value.get("ref")
        obj=value.get("object")
        require(ref == ref_name_for(authorization_sha256),
                "FUGLE_GH_FENCE_GET_REF_MISMATCH")
        require(isinstance(obj,Mapping) and obj.get("type")=="commit",
                "FUGLE_GH_FENCE_GET_OBJECT_INVALID")
        sha=_sha40(obj.get("sha"),"FUGLE_GH_FENCE_GET_SHA_INVALID")
        return {"ref":ref,"sha":sha}

    def create_marker(self, authorization_sha256: str, main_sha: str) -> dict[str,Any]:
        target=_sha40(main_sha,"FUGLE_GH_FENCE_MAIN_SHA_INVALID")
        payload=json.dumps({
            "ref":ref_name_for(authorization_sha256),
            "sha":target,
        },separators=(",",":")).encode("utf-8")
        result=self._request("POST",f"/repos/{REPOSITORY}/git/refs",payload)
        require(result["status"] == 201,"FUGLE_GH_FENCE_CREATE_STATUS_INVALID")
        try:
            value=json.loads(result["body"].decode("utf-8"))
        except (UnicodeError,json.JSONDecodeError) as exc:
            raise FugleGitHubFenceTransportError(
                "FUGLE_GH_FENCE_CREATE_BODY_INVALID"
            ) from exc
        require(isinstance(value,Mapping),"FUGLE_GH_FENCE_CREATE_BODY_INVALID")
        require(value.get("ref")==ref_name_for(authorization_sha256),
                "FUGLE_GH_FENCE_CREATE_REF_MISMATCH")
        obj=value.get("object")
        require(isinstance(obj,Mapping) and obj.get("type")=="commit"
                and _sha40(obj.get("sha"),"FUGLE_GH_FENCE_CREATE_SHA_INVALID")==target,
                "FUGLE_GH_FENCE_CREATE_TARGET_MISMATCH")
        return {
            "ref":value["ref"],
            "sha":target,
            "exclusive_create_acknowledged":True,
        }
