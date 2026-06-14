import json

import boto3
from tavily import TavilyClient


class ToolError(Exception):
    pass


def _get_client():
    secret = boto3.client("secretsmanager").get_secret_value(
        SecretId="nrl-predictor/tavily-api-key"
    )
    api_key = json.loads(secret["SecretString"]) if secret["SecretString"].startswith("{") else secret["SecretString"]
    return TavilyClient(api_key=api_key)


def web_search(query: str, client=None) -> list[str]:
    try:
        c = client or _get_client()
        response = c.search(query)
        return [r["content"] for r in response.get("results", [])]
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Web search failed: {e}") from e
