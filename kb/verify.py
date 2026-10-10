import boto3
import time

REGION = "us-west-2"
KB_ID = "BF2T5CZDI5"
DS_ID = "U2GIEKM6FH"
S3_BUCKET = f"irkb-docs-{boto3.client('sts', region_name=REGION).get_caller_identity()['Account']}"
DOC_KEY = "best-practices.md"

s3 = boto3.client("s3", region_name=REGION)
agent = boto3.client("bedrock-agent", region_name=REGION)
runtime = boto3.client("bedrock-agent-runtime", region_name=REGION)

# 1. upload + ingest
s3.upload_file("sample-docs/best-practices.md", S3_BUCKET, DOC_KEY)
job = agent.start_ingestion_job(knowledgeBaseId=KB_ID, dataSourceId=DS_ID)
jid = job["ingestionJob"]["ingestionJobId"]
for _ in range(40):
    st = agent.get_ingestion_job(knowledgeBaseId=KB_ID, dataSourceId=DS_ID,
                                 ingestionJobId=jid)["ingestionJob"]
    if st["status"] in ("COMPLETE", "FAILED", "STOPPED"):
        break
    time.sleep(15)
assert st["status"] == "COMPLETE", f"ingestion failed: {st['status']}"
print("ingestion:", st["status"], st["statistics"]["numberOfNewDocumentsIndexed"], "new")

# 2. retrieval (allow eventual consistency)
for attempt in range(6):
    res = runtime.retrieve(
        knowledgeBaseId=KB_ID,
        retrievalQuery={"text": "Should an S3 bucket allow public access?"},
        retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 2}},
    )["retrievalResults"]
    if res:
        break
    time.sleep(15)
assert res, "retrieve returned no results"
print("retrieved", len(res), "chunks; top score", round(res[0]["score"], 3))
print("top text:", res[0]["content"]["text"][:100].replace("\n", " "))
print("\nKB VERIFIED OK")
