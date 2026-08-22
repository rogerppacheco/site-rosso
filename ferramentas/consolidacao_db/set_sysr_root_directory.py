"""Define rootDirectory do sysr-vendas-api via GraphQL Railway."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import urllib.request

PROJECT_ID = "fe553432-2a22-46cc-b347-ee669ff4aba3"
SERVICE_ID = "bb8d0a77-524c-4578-8603-1109bc25e40c"
ENVIRONMENT_ID = "64a5314b-6a29-4f1f-b359-0215055733c5"
CONFIG_PATH = Path(r"C:\Users\rogge\.railway\config.json")


def _token() -> str:
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    token = data.get("user", {}).get("accessToken") or data.get("user", {}).get("token")
    if not token:
        raise RuntimeError("Token Railway nao encontrado em ~/.railway/config.json")
    return token


def _graphql(query: str, variables: dict | None = None) -> dict:
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    req = urllib.request.Request(
        "https://backboard.railway.com/graphql/v2",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {_token()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    mutation = """
    mutation ServiceInstanceUpdate($serviceId: String!, $environmentId: String!, $input: ServiceInstanceUpdateInput!) {
      serviceInstanceUpdate(serviceId: $serviceId, environmentId: $environmentId, input: $input)
    }
    """
    variables = {
        "serviceId": SERVICE_ID,
        "environmentId": ENVIRONMENT_ID,
        "input": {
            "rootDirectory": "backend",
            "railwayConfigFile": "/backend/railway.toml",
        },
    }
    result = _graphql(mutation, variables)
    if result.get("errors"):
        print(json.dumps(result, indent=2), file=sys.stderr)
        sys.exit(1)
    print("OK - rootDirectory=backend, railwayConfigFile=/backend/railway.toml")

    query = """
    query($projectId: String!) {
      project(id: $projectId) {
        services {
          edges {
            node {
              name
              serviceInstances {
                edges {
                  node {
                    rootDirectory
                    railwayConfigFile
                  }
                }
              }
            }
          }
        }
      }
    }
    """
    verify = _graphql(query, {"projectId": PROJECT_ID})
    print(json.dumps(verify, indent=2))


if __name__ == "__main__":
    main()
