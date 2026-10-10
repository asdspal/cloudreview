import boto3
import json
import time

REGION = "us-west-2"
ACCOUNT = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]

agent_client = boto3.client("bedrock-agent", region_name=REGION)
iam = boto3.client("iam", region_name=REGION)

AGENT_NAME = "CloudReview"
ROLE_NAME = "irkb-agent-role"
ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/{ROLE_NAME}"
KB_ID = "BF2T5CZDI5"
KB_ARN = f"arn:aws:bedrock:{REGION}:{ACCOUNT}:knowledge-base/{KB_ID}"
MODEL_ARN = (f"arn:aws:bedrock:{REGION}:{ACCOUNT}:inference-profile/"
             "us.anthropic.claude-sonnet-4-5-20250929-v1:0")

INSTRUCTION = """You are CloudReview, a friendly senior cloud engineer who reviews
Infrastructure-as-Code (Terraform, CloudFormation, CDK, AWS CLI) for real-world problems.

When the user pastes IaC, you:
1. Lead with a TRUST SCORE out of 100 (100 = safe for production). State it boldly.
2. List findings ranked by severity (Critical / High / Medium / Low). For each:
   - the rule you are applying,
   - a plain-English explanation of the risk (tell a short concrete attack or failure
     story, not a policy citation),
   - the corrected snippet the user can copy.
3. If the user asks "why", explain like they are a junior engineer, with an analogy.
4. End with one concrete next step.

Ground your answers in the knowledge base. Be warm and concise, never preachy. If the
IaC is clean, say so and give the high score with a bit of encouragement. Never invent
AWS services; if unsure, say so.
"""


def wait(cond, timeout=300, msg=""):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = cond()
        if r:
            return r
        time.sleep(10)
    raise TimeoutError(msg)


def create_agent_role():
    try:
        iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps({
                "Version": "2012-10-17",
                "Statement": [{"Effect": "Allow",
                               "Principal": {"Service": "bedrock.amazonaws.com"},
                               "Action": "sts:AssumeRole",
                               "Condition": {"StringEquals": {"aws:SourceAccount": ACCOUNT}}}],
            }),
            Description="CloudReview Bedrock agent role",
        )
        print("role created:", ROLE_ARN)
    except iam.exceptions.EntityAlreadyExistsException:
        print("role exists:", ROLE_ARN)
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="cloudreview-agent",
        PolicyDocument=json.dumps({
            "Version": "2012-10-17",
            "Statement": [
                {"Effect": "Allow",
                 "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                 "Resource": [MODEL_ARN,
                              "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0"]},
                {"Effect": "Allow",
                 "Action": ["bedrock:Retrieve", "bedrock:RetrieveAndGenerate"],
                 "Resource": KB_ARN},
                {"Effect": "Allow",
                 "Action": ["bedrock:GetKnowledgeBase", "bedrock:ListKnowledgeBases"],
                 "Resource": "*"},
            ],
        }),
    )
    print("inline policy attached")


def create_agent():
    existing = wait(lambda: agent_client.list_agents()["agentSummaries"],
                    msg="list agents") if False else agent_client.list_agents()["agentSummaries"]
    ex = next((a for a in existing if a["agentName"] == AGENT_NAME), None)
    if ex:
        print("agent exists:", ex["agentId"])
        return ex["agentId"]
    ag = agent_client.create_agent(
        agentName=AGENT_NAME,
        description="Reviews Infrastructure-as-Code for security, cost, and operational issues.",
        agentResourceRoleArn=ROLE_ARN,
        foundationModel=MODEL_ARN,
        instruction=INSTRUCTION,
        idleSessionTTLInSeconds=600,
    )
    aid = ag["agent"]["agentId"]
    print("agent created:", aid, "status:", ag["agent"]["agentStatus"])
    return aid


def associate_kb(agent_id):
    try:
        agent_client.associate_agent_knowledge_base(
            agentId=agent_id,
            agentVersion="DRAFT",
            knowledgeBaseId=KB_ID,
            description="IaC best-practice rules",
            knowledgeBaseState="ENABLED",
        )
        print("KB associated")
    except agent_client.exceptions.ConflictException:
        print("KB already associated")


def prepare_agent(agent_id):
    # wait for any in-flight state to settle
    wait(lambda: agent_client.get_agent(agentId=agent_id)["agent"]["agentStatus"]
         not in ("CREATING", "UPDATING", "PREPARING"),
         timeout=300, msg="agent settle")
    agent_client.prepare_agent(agentId=agent_id)
    st = wait(lambda: agent_client.get_agent(agentId=agent_id)["agent"]["agentStatus"]
              if agent_client.get_agent(agentId=agent_id)["agent"]["agentStatus"]
              in ("PREPARED", "FAILED") else None,
              timeout=600, msg="prepare agent")
    print("agent prepared, status:", st)
    return st


def create_alias(agent_id):
    aliases = agent_client.list_agent_aliases(agentId=agent_id)["agentAliasSummaries"]
    ex = next((a for a in aliases if a["agentAliasName"] == "live"), None)
    if ex:
        print("alias exists:", ex["agentAliasId"])
        return ex["agentAliasId"]
    al = agent_client.create_agent_alias(agentId=agent_id, agentAliasName="live")
    aid = al["agentAlias"]["agentAliasId"]
    wait(lambda: agent_client.get_agent_alias(agentId=agent_id, agentAliasId=aid)
         ["agentAlias"]["agentAliasStatus"] == "PREPARED", timeout=600, msg="alias prepare")
    print("alias created:", aid)
    return aid


if __name__ == "__main__":
    create_agent_role()
    print("waiting 20s for IAM propagation...")
    time.sleep(20)
    agent_id = create_agent()
    associate_kb(agent_id)
    prepare_agent(agent_id)
    alias_id = create_alias(agent_id)
    print("\n=== AGENT ===")
    print("agentId:", agent_id)
    print("aliasId:", alias_id)
