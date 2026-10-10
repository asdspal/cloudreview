import boto3
import json
from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth

REGION = "us-west-2"
OSS_COLL = "irkb-vs"
INDEX = "irkb-index"

boto_session = boto3.Session()
creds = boto_session.get_credentials()
auth = AWSV4SignerAuth(creds, REGION, "aoss")

aoss = boto3.client("opensearchserverless", region_name=REGION)
coll = next(c for c in aoss.list_collections()["collectionSummaries"]
            if c["name"] == OSS_COLL)
host = f"{coll['id']}.{REGION}.aoss.amazonaws.com"

client = OpenSearch(
    hosts=[{"host": host, "port": 443}],
    http_auth=auth,
    use_ssl=True,
    verify_certs=True,
    connection_class=RequestsHttpConnection,
)

mapping = {
    "settings": {"index": {"knn": True}},
    "mappings": {
        "properties": {
            "amz-bedrock-metadata": {"type": "text", "index": False},
            "text": {"type": "text"},
            "$vector": {
                "type": "knn_vector",
                "dimension": 1024,
                "method": {
                    "name": "hnsw",
                    "engine": "faiss",
                    "space_type": "l2",
                },
            },
        }
    },
}

if client.indices.exists(index=INDEX):
    print("index exists:", INDEX)
else:
    client.indices.create(index=INDEX, body=mapping)
    print("index created:", INDEX)

print("health:", client.cluster.health())
