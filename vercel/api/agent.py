import os
import re
import time
import threading
import boto3
from botocore.config import Config

REGION = "us-west-2"
# Swap models with e.g. CLOUDREVIEW_MODEL=us.amazon.nova-2-lite-v1:0 streamlit run app.py
MODEL_ID = os.environ.get("CLOUDREVIEW_MODEL", "us.amazon.nova-micro-v1:0")
KB_ID = "BF2T5CZDI5"
MAX_TOKENS = 1500

# On-demand, approximate (USD per 1M tokens) for the usage readout only.
# Nova Micro. If you switch models, update these to match.
PRICE_IN = 0.035
PRICE_OUT = 0.14

# ponytail: in-memory limiter, resets on restart; use Redis/DB if you run multiple workers.
MAX_PER_MIN = 6
MAX_TOTAL = 100
_call_times: list = []
_usage = {"calls": 0, "inputTokens": 0, "outputTokens": 0}
_lock = threading.Lock()


def usage() -> dict:
    with _lock:
        u = dict(_usage)
    u["estCostUsd"] = round(u["inputTokens"] / 1e6 * PRICE_IN
                            + u["outputTokens"] / 1e6 * PRICE_OUT, 4)
    return u


def _precheck():
    with _lock:
        now = time.time()
        _call_times[:] = [t for t in _call_times if now - t < 60]
        if len(_call_times) >= MAX_PER_MIN:
            wait = 60 - (now - _call_times[0])
            raise RuntimeError(
                f"Rate limit hit ({MAX_PER_MIN} model calls/min). Try again in {wait:.0f}s.")
        if _usage["calls"] >= MAX_TOTAL:
            raise RuntimeError(
                f"Session cap reached ({MAX_TOTAL} model calls). Restart the app to reset.")
        _call_times.append(now)


def _record_usage(u: dict):
    with _lock:
        _usage["calls"] += 1
        _usage["inputTokens"] += u.get("inputTokens", 0)
        _usage["outputTokens"] += u.get("outputTokens", 0)

_runtime = boto3.client(
    "bedrock-runtime",
    region_name=REGION,
    config=Config(retries={"max_attempts": 5, "mode": "adaptive"}, read_timeout=120),
)
_agent_runtime = boto3.client("bedrock-agent-runtime", region_name=REGION)

SYSTEM_PROMPT = """You are CloudReview, a friendly senior cloud engineer who reviews
Infrastructure-as-Code (Terraform, CloudFormation, CDK, AWS CLI) for real-world problems.

When the user pastes IaC:
1. Lead with a "TRUST SCORE: NN/100" line (100 = safe for production). Be bold and honest.
2. List findings ranked by severity (Critical / High / Medium / Low). For each give:
   - the rule you are applying,
   - a plain-English explanation of the real risk (a short concrete attack or failure
     story, not a policy citation),
   - the corrected snippet the user can copy.
3. If the user asks "why", explain like they are a junior engineer, with an analogy.
4. End with one concrete next step.

Use the search_best_practices tool to ground your review in the house best-practice
rules before you write findings. Be warm and concise, never preachy. If the IaC is
clean, say so and give the high score with genuine encouragement. Never invent AWS
services; if unsure, say so."""

TOOL_CONFIG = {
    "tools": [{
        "toolSpec": {
            "name": "search_best_practices",
            "description": ("Search the AWS IaC best-practice knowledge base for the "
                            "rules relevant to a given concern (e.g. 's3 public access', "
                            "'iam wildcard', 'encryption', 'idle cost'). Call this before "
                            "writing findings."),
            "inputSchema": {"json": {
                "type": "object",
                "properties": {"query": {"type": "string",
                                         "description": "The concern to look up"}},
                "required": ["query"],
            }},
        }
    }]
}


def search_best_practices(query: str, n: int = 4) -> str:
    res = _agent_runtime.retrieve(
        knowledgeBaseId=KB_ID,
        retrievalQuery={"text": query},
        retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": n}},
    )["retrievalResults"]
    if not res:
        return "No rules found in the knowledge base for that query."
    return "\n\n".join(r["content"]["text"] for r in res)


def _run_tool(name: str, tool_input: dict):
    if name == "search_best_practices":
        return search_best_practices(str(tool_input.get("query", ""))[:500])
    return f"Unknown tool: {name}"


def respond(messages: list, max_iterations: int = 5, trace: list | None = None) -> tuple[str, list]:
    """Run the Converse tool-use loop. Returns (final_text, updated_messages).

    If `trace` is a list, each KB lookup is appended as a dict for UI transparency.
    """
    for _ in range(max_iterations):
        _precheck()
        resp = _runtime.converse(
            modelId=MODEL_ID,
            messages=messages,
            system=[{"text": SYSTEM_PROMPT}],
            inferenceConfig={"maxTokens": MAX_TOKENS, "temperature": 0.3},
            toolConfig=TOOL_CONFIG,
        )
        _record_usage(resp.get("usage", {}))
        msg = resp["output"]["message"]
        messages.append(msg)

        if resp["stopReason"] != "tool_use":
            text = "".join(b.get("text", "") for b in msg["content"])
            return text, messages

        tool_results = []
        for block in msg["content"]:
            if "toolUse" in block:
                q = str(block["toolUse"]["input"].get("query", ""))
                out = _run_tool(block["toolUse"]["name"], block["toolUse"]["input"])
                if trace is not None:
                    trace.append({"query": q, "chars": len(out)})
                tool_results.append({
                    "toolResult": {
                        "toolUseId": block["toolUse"]["toolUseId"],
                        "content": [{"text": out}],
                    }
                })
        messages.append({"role": "user", "content": tool_results})

    return "I hit my step limit before finishing. Try a smaller snippet.", messages


def extract_score(text: str):
    """Pull the TRUST SCORE out of the reply for the UI badge."""
    m = re.search(r"TRUST SCORE[:*\s]*(\d{1,3})\s*/\s*100", text, re.IGNORECASE)
    return int(m.group(1)) if m else None


def strip_thinking(text: str) -> str:
    """Remove model reasoning tags (Nova emits <thinking>...</thinking>)."""
    return re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL).strip()


if __name__ == "__main__":
    broken = """resource "aws_s3_bucket" "data" { bucket = "my-data" }
resource "aws_s3_bucket_acl" "data" { bucket = aws_s3_bucket.data.id acl = "public-read" }
resource "aws_iam_policy" "p" {
  policy = jsonencode({ Statement = [{ Action = "*", Resource = "*", Effect = "Allow" }] })
}"""
    text, _ = respond([{"role": "user", "content": [{"text": broken}]}])
    print(text)
    score = extract_score(text)
    assert score is not None, "agent did not emit a TRUST SCORE"
    assert 0 <= score <= 100, "score out of range"
    print("\nSELF-CHECK OK -> score:", score)
