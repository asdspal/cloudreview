import boto3
import json
import time

REGION = "us-west-2"
ACCOUNT = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]

bedrock = boto3.client("bedrock-agent", region_name=REGION)
iam = boto3.client("iam", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)
aoss = boto3.client("opensearchserverless", region_name=REGION)

S3_BUCKET = f"irkb-docs-{ACCOUNT}"
OSS_COLL = "irkb-vs"
KB_NAME = "irkb"
DS_NAME = "irkb-ds"
ROLE_NAME = "irkb-role"
ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/{ROLE_NAME}"
EMBED_ARN = "arn:aws:bedrock:us-west-2::foundation-model/amazon.titan-embed-text-v2:0"


def wait(cond, timeout=400, msg=""):
    t0 = time.time()
    while time.time() - t0 < timeout:
        result = cond()
        if result:
            return result
        time.sleep(15)
    raise TimeoutError(f"timeout waiting for {msg}")


def create_s3_bucket():
    try:
        s3.create_bucket(
            Bucket=S3_BUCKET,
            CreateBucketConfiguration={"LocationConstraint": REGION},
        )
        print("bucket created:", S3_BUCKET)
    except s3.exceptions.BucketAlreadyOwnedByYou:
        print("bucket exists:", S3_BUCKET)


def create_role():
    try:
        iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps({
                "Version": "2012-10-17",
                "Statement": [{"Effect": "Allow",
                               "Principal": {"Service": "bedrock.amazonaws.com"},
                               "Action": "sts:AssumeRole"}],
            }),
            Description="KB indexing service role",
        )
        print("role created:", ROLE_ARN)
    except iam.exceptions.EntityAlreadyExistsException:
        print("role exists:", ROLE_ARN)
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="bedrock-kb-full",
        PolicyDocument=json.dumps({
            "Version": "2012-10-17",
            "Statement": [
                {"Effect": "Allow", "Action": ["s3:GetObject", "s3:ListBucket"],
                 "Resource": [f"arn:aws:s3:::{S3_BUCKET}",
                              f"arn:aws:s3:::{S3_BUCKET}/*"]},
                {"Effect": "Allow", "Action": ["aoss:APIAccessAll"], "Resource": "*"},
                {"Effect": "Allow",
                 "Action": ["bedrock:InvokeModel"],
                 "Resource": EMBED_ARN},
                {"Effect": "Allow",
                 "Action": ["logs:CreateLogGroup", "logs:CreateLogStream",
                            "logs:PutLogEvents"],
                 "Resource": "*"},
            ],
        }),
    )
    print("inline policy attached")


def create_security_policy():
    try:
        aoss.create_security_policy(
            name=f"{OSS_COLL}-sec",
            policy=json.dumps({"Rules": [{"ResourceType": "collection",
                                          "Resource": [f"collection/{OSS_COLL}"]}],
                               "AWSOwnedKey": True}),
            type="encryption",
        )
        print("encryption policy created")
    except aoss.exceptions.ConflictException:
        print("encryption policy exists")
    try:
        aoss.create_security_policy(
            name=f"{OSS_COLL}-net",
            policy=json.dumps([{"Rules": [
                {"ResourceType": "collection",
                 "Resource": [f"collection/{OSS_COLL}"]}],
                "AllowFromPublic": True}]),
            type="network",
        )
        print("network policy created")
    except aoss.exceptions.ConflictException:
        print("network policy exists")


def create_collection():
    try:
        aoss.create_collection(name=OSS_COLL, type="VECTORSEARCH")
        print("collection created")
    except aoss.exceptions.ConflictException:
        print("collection exists")
    coll = wait(lambda: next((c for c in aoss.list_collections()["collectionSummaries"]
                              if c["name"] == OSS_COLL), None),
                timeout=500, msg="OSS collection appear")
    print("collection:", coll["name"], coll["arn"])
    return coll["arn"]


def create_access_policy():
    policy = [{
        "Principal": [ROLE_ARN, f"arn:aws:iam::{ACCOUNT}:root"],
        "Rules": [
            {"ResourceType": "collection",
             "Resource": [f"collection/{OSS_COLL}"],
             "Permission": ["aoss:*"]},
            {"ResourceType": "index",
             "Resource": [f"index/{OSS_COLL}/*"],
             "Permission": ["aoss:*"]},
        ],
    }]
    try:
        aoss.delete_access_policy(name=f"{OSS_COLL}-acl", type="data")
    except Exception:
        pass
    aoss.create_access_policy(name=f"{OSS_COLL}-acl",
                              policy=json.dumps(policy), type="data")
    print("access policy created")


def create_kb(collection_arn):
    existing = next((kb for kb in bedrock.list_knowledge_bases()["knowledgeBaseSummaries"]
                     if kb["name"] == KB_NAME), None)
    if existing:
        print("kb exists:", existing["knowledgeBaseId"])
        return existing["knowledgeBaseId"]
    kb = bedrock.create_knowledge_base(
        name=KB_NAME,
        description="Best practices for reviewing Infrastructure-as-Code - security, cost, operational rigor.",
        roleArn=ROLE_ARN,
        knowledgeBaseConfiguration={
            "type": "VECTOR",
            "vectorKnowledgeBaseConfiguration": {"embeddingModelArn": EMBED_ARN},
        },
        storageConfiguration={
            "type": "OPENSEARCH_SERVERLESS",
            "opensearchServerlessConfiguration": {
                "collectionArn": collection_arn,
                "vectorIndexName": "irkb-index",
                "fieldMapping": {"vectorField": "$vector",
                                 "metadataField": "amz-bedrock-metadata",
                                 "textField": "text"},
            },
        },
    )
    print("kb created:", kb["knowledgeBase"]["knowledgeBaseId"])
    return kb["knowledgeBase"]["knowledgeBaseId"]


def create_datasource(kb_id):
    existing = bedrock.list_data_sources(knowledgeBaseId=kb_id)["dataSourceSummaries"]
    ex = next((ds for ds in existing if ds["name"] == DS_NAME), None)
    if ex:
        print("datasource exists:", ex["dataSourceId"])
        return ex["dataSourceId"]
    ds = bedrock.create_data_source(
        knowledgeBaseId=kb_id,
        name=DS_NAME,
        dataSourceConfiguration={
            "type": "S3",
            "s3Configuration": {"bucketArn": f"arn:aws:s3:::{S3_BUCKET}"},
        },
    )
    print("datasource:", ds["dataSource"]["dataSourceId"])
    return ds["dataSource"]["dataSourceId"]


if __name__ == "__main__":
    create_s3_bucket()
    create_role()
    print("waiting 20s for IAM propagation...")
    time.sleep(20)
    create_security_policy()
    collection_arn = create_collection()
    create_access_policy()
    print("waiting 60s for OSS policies to propagate...")
    time.sleep(60)
    kb_id = create_kb(collection_arn)
    ds_id = create_datasource(kb_id)
    print("\n=== IDs ===")
    print("KB:", kb_id)
    print("DS:", ds_id)
    print("Bucket:", S3_BUCKET)
    print("Role:", ROLE_ARN)
