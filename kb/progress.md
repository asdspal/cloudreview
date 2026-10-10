# Infra Reviewer — KB Setup Progress

AWS Builder Center "build an agent" challenge. Agent name: **CloudReview** (reviews
IaC: Terraform / CloudFormation / CDK / AWS CLI for security, cost, operational issues).

This file tracks the Knowledge Base (KB) step only.

- **Account:** <ACCOUNT_ID> (root creds)
- **Region:** us-west-2
- **Script:** `kb/setup-kb.py` (idempotent — safe to re-run)
- **Index script:** `kb/create-index.py`
- **Local boto3:** upgraded to 1.43.111 (older botocore lacked `bedrock-agent`)
- Also installed: `opensearch-py`, `requests-aws4auth`

---

## STATUS: STEP 1 (KB) COMPLETE ✅ · STEP 2 (AGENT) COMPLETE ✅

The KB is live and verified end-to-end: doc uploaded → ingested → retrieval returns
relevant chunks.

The agent (`agent.py` + `app.py`) is live and verified: it runs a Converse tool-use
loop, calls the KB, and returns a TRUST SCORE + findings. Self-check passes.

### How to run

```bash
cd /home/pauli/wspace/aws
python3 agent.py                     # CLI self-check (calls the model once)
streamlit run app.py                 # web UI -> http://localhost:8501
```

### Live resource IDs

| Resource | Name / ID |
|---|---|
| Bedrock Knowledge Base | **`BF2T5CZDI5`** (`irkb`) |
| Bedrock data source (S3) | **`U2GIEKM6FH`** (`irkb-ds`) |
| S3 bucket | `irkb-docs-<ACCOUNT_ID>` |
| IAM service role | `arn:aws:iam::<ACCOUNT_ID>:role/irkb-role` |
| OpenSearch Serverless collection | `irkb-vs` → `arn:aws:aoss:us-west-2:<ACCOUNT_ID>:collection/h6ewpscwgid28wyaksyg` |
| OSS vector index | `irkb-index` (dim 1024, `hnsw`/`faiss`/`l2`) |
| Embedding model | `arn:aws:bedrock:us-west-2::foundation-model/amazon.titan-embed-text-v2:0` |

### Verification run

- Uploaded `sample-docs/best-practices.md` to the bucket
- Ingestion job `F97GNXAS6Q` → COMPLETE, `numberOfNewDocumentsIndexed: 1`
- `retrieve` queries returned matching chunks (scores 0.35–0.41), e.g.
  "public S3 bucket access" → 1 result

---

## Completed checklist

- [x] Environment check: root creds valid, region us-west-2
- [x] Upgraded boto3/botocore so the `bedrock-agent` client exists
- [x] S3 bucket `irkb-docs-<ACCOUNT_ID>` (pinned name)
- [x] IAM role `irkb-role` + inline policy (S3 read, aoss, InvokeModel, logs)
- [x] OSS encryption security policy (`irkb-vs-sec`)
- [x] OSS **network** security policy (`irkb-vs-net`, AllowFromPublic — required!)
- [x] OSS collection (`irkb-vs`)
- [x] OSS data access policy (`irkb-vs-acl`) — principal = role ARN (+ root)
- [x] Vector index `irkb-index` created manually via opensearch-py
- [x] **Bedrock Knowledge Base** `BF2T5CZDI5`
- [x] Data source `U2GIEKM6FH`
- [x] Ingestion verified + retrieval verified

## Next (not part of step 1)

- [x] Custom RAG agent loop (`agent.py`) — Converse + `search_best_practices` KB tool
- [x] Streamlit UI (`app.py`, `extract_score` trust-score badge)
- [ ] Upload more real AWS best-practice docs (currently 1 sample doc)
- [ ] Demo script + article + profile

---

## Errors hit and fixes (in order) — useful for the write-up

1. **`bedrockagent` unknown service** → upgraded botocore to 1.43.111.
2. **`IllegalLocationConstraintException`** → pass
   `CreateBucketConfiguration={"LocationConstraint":"us-west-2"}`.
3. **Managed policy `AWSBedrockKnowledgeBasesRole` does not exist** → custom role with
   inline policy instead.
4. **OSS `No matching security policy of encryption type`** → create the **encryption**
   policy *before* the collection.
5. **OSS policy name > 32 chars** → shortened names to `irkb-*`.
6. **OSS encryption policy schema** → needs
   `{"Rules":[{"ResourceType":"collection","Resource":[...]}],"AWSOwnedKey":true}`;
   top-level needs >=2 props; `Type`/`Description`/`Owner` rejected.
7. **OSS data access policy schema** → a **JSON array** of one object:
   `[{"Principal":[...],"Rules":[{"ResourceType":"collection",...},{"ResourceType":"index",...}]}]`
   (`PolicyName` rejected inside the JSON; name is an API arg).
8. **`create_knowledge_base` param shape** → correct shape:
   - `knowledgeBaseConfiguration={"type":"VECTOR","vectorKnowledgeBaseConfiguration":{"embeddingModelArn":...}}`
   - `storageConfiguration` is **top-level** (not nested in knowledgeBaseConfiguration):
     `{"type":"OPENSEARCH_SERVERLESS","opensearchServerlessConfiguration":{"collectionArn":...,"vectorIndexName":"irkb-index","fieldMapping":{...}}}`
   - lowercase `opensearchServerlessConfiguration`, key is `collectionArn`
     (not `vectorCollectionArn`), no `numberOfVectorsPerShard` here.
9. **Invalid embedding model ARN** → Nova embed unavailable in us-west-2; use
   `amazon.titan-embed-text-v2:0`.
10. **"unable to assume the given role"** → IAM propagation; added 20s wait after role
    creation.
11. **OSS 401 during KB create** → missing **network** security policy. Added
    `AllowFromPublic: true`.
12. **`no such index [irkb-index]`** → KB requires the vector index to pre-exist for OSS
    Serverless; created it manually with opensearch-py (knn_vector, dim 1024).
13. **OSS 403 creating index** → data access policy principal must include the calling
    identity; added `arn:aws:iam::...:root` alongside the role ARN.
14. **`create_data_source` shape** → `type` goes *inside* `dataSourceConfiguration`
    (top-level `type` is rejected).
15. **`retrieve` returned empty right after ingest** → eventual consistency; succeeded
    on retry ~1 min later.

---

## Step 2 — Agent (custom RAG loop)

**Architecture (chosen because classic Bedrock Agents is in maintenance mode):**

```
Streamlit UI (app.py)
  -> agent.respond()  Converse tool-use loop  (bedrock-runtime)
        -> tool: search_best_practices(query)
              -> bedrock-agent-runtime.retrieve(KB BF2T5CZDI5)
        -> final answer: "TRUST SCORE: NN/100" + findings
```

**Files**
- `agent.py` — model invocation, tool loop, KB retrieval, `extract_score()`
- `app.py` — Streamlit chat UI with a colored trust-score badge

**Live config**
- Model: **`us.amazon.nova-micro-v1:0`** (swap via `CLOUDREVIEW_MODEL` env var)
- Tool: `search_best_practices` → KB `BF2T5CZDI5`
- `maxTokens` set explicitly (1500) per Bedrock guidance
- Rate limits (agent.py, in-memory): 6 model calls/min, 300 total per run

**Model selection test** (task is rudimentary, so benchmark the capability we use — tool use):
| Model | Tool use | Note |
|---|---|---|
| `us.amazon.nova-micro-v1:0` | ✅ | cheapest that works — chosen |
| `us.amazon.nova-lite-v1:0` | ❌ | ModelErrorException: invalid ToolUse |
| `us.amazon.nova-2-lite-v1:0` | ✅ | best prose, pricier |
| `us.amazon.nova-pro-v1:0` | ✅ | ~20x Micro cost |
| Anthropic (Haiku/Sonnet) | ❌ | gated behind use-case form |

**Verified**
- `python3 agent.py` self-check: fed a deliberately-broken Terraform snippet
  (public-read S3 + IAM `Action:"*" Resource:"*"`), agent returned
  **TRUST SCORE: 20/100** with Critical/High/Medium findings + corrected snippets.
- Streamlit app boots and serves HTTP 200.

### Step 2 errors hit and fixes

1. **`create_agent` → AccessDeniedException: "Bedrock Agents is in Maintenance
   Mode."** Classic `bedrock-agent` agents are closed to new accounts. Verified
   AgentCore (control + data plane) IS available → chose a custom RAG loop instead.
2. **Converse → ResourceNotFoundException: "Model use case details have not been
   submitted for this account"** for every Anthropic model (Sonnet 4.5/4.6, Haiku
   4.5, Opus). The Anthropic use-case form is required for this account. Fix: use
   **Nova** (`us.amazon.nova-pro-v1:0`), which works without the form. (Probe calls
   to Claude briefly "succeeded" then failed — do not trust a single probe; test
   with the full system + toolConfig.)

---

## Step 3 — Vercel deployment (optional public URL)

Vercel cannot host the Streamlit app (needs a persistent server + WebSocket). Instead the
agent runs as a **Vercel Python serverless function** + a static chat page — same agent
logic, public HTTPS URL.

```
vercel/
  index.html          # static chat UI (calls /api/review)
  requirements.txt    # boto3
  vercel.json         # maxDuration 60 for api/review.py
  api/review.py       # POST handler -> agent.respond()
  api/agent.py        # COPY of ../../agent.py (duplicated; keep in sync)
```

- `MAX_TOTAL` lowered to 100 in the Vercel copy (public link = public Bedrock spend).
- Verified locally: ran `api/review.py`'s handler behind `http.server`, POSTed a broken
  snippet -> score 30, 5 KB lookups, 2 model calls, est $0.0003.

### Deploy steps (need YOUR Vercel account + AWS creds)

```bash
cd vercel
npx vercel            # login when prompted, accept defaults (project root = vercel/)
npx vercel env add AWS_ACCESS_KEY_ID production
npx vercel env add AWS_SECRET_ACCESS_KEY production
npx vercel env add AWS_REGION production   # us-west-2
npx vercel --prod     # deploy, prints the public URL
```

**Security**: the creds you add let anyone on that URL spend your Bedrock credits. Use a
least-privilege key scoped to `bedrock:InvokeModel` + `bedrock:Retrieve` on this KB only,
and keep the low `MAX_TOTAL`. Consider taking the link down after the challenge.

---

## Step 4 — Deployed on AWS EC2 (free tier, no secrets shared)

Chose EC2 over Vercel/App Runner so **no AWS keys leave the account** — the app uses an
**instance profile** (IAM role), and it fits the **free tier** (t3.micro, 750 hrs/mo).

**IaC (CloudFormation):** `ec2/cloudreview.yml` (generated by `ec2/gen-stack.py`, which
embeds a base64 tarball of `agent.py` + `app.py` into the instance UserData). Creates:
VPC + public subnet + IGW + route table, IAM role/instance profile (Bedrock +
`AmazonSSMManagedInstanceCore`), security group (8501 public), t3.micro instance,
Elastic IP.

**Live URL:** http://54.69.23.50:8501  (Elastic IP `54.69.23.50`, stable across reboots)
**Stack:** `cloudreview` (us-west-2)  **Instance:** `i-0d3539ecaa132b8b2`

Redeploy / tear down:
```bash
cd ec2 && python3 gen-stack.py
aws cloudformation deploy --stack-name cloudreview --template-file cloudreview.yml \
  --region us-west-2 --capabilities CAPABILITY_NAMED_IAM
aws cloudformation delete-stack --stack-name cloudreview --region us-west-2   # cleanup
```

**Verified**
- `curl http://54.69.23.50:8501` -> HTTP 200
- Ran `agent.respond()` ON the instance via SSM -> returned a trust score (Bedrock +
  KB reachable through the instance role, zero static credentials)

### Step 4 errors hit and fixes

1. **No default VPC** in the account -> template creates VPC/subnet/IGW/route table.
2. **`pip install --upgrade pip` fails on AL2023** ("Cannot uninstall pip ... installed by
   rpm") and `set -e` aborted the whole user-data -> dropped the upgrade.
3. **`Cannot uninstall requests 2.25.1 ... installed by rpm`** when installing streamlit
   system-wide -> use a **venv** (`/opt/cloudreview/venv`) to isolate from rpm packages.
4. **`list | None` syntax crashes on Python 3.9** (AL2023 default) -> added
   `from __future__ import annotations` to `agent.py`.
5. **Public IP changed on reboot** and CFN didn't re-run user-data on the live box ->
   attached an **Elastic IP** for a stable URL; provisioned the running instance once via
   SSM.

**Security note:** port 8501 is open to `0.0.0.0/0` (no auth) for the demo. The IAM role
is scoped to InvokeModel (Nova Micro) + Retrieve (this KB) only, and the app caps calls
(6/min, 100/run). Take it down after judging.

---

## Cleanup TODO

Early debug runs created several orphaned resources to delete later:
- Buckets: `irkb-<random>`, `infra-reviewer-kb-<random>` (many)
- IAM roles: `irkb-role-<random>`, `infra-reviewer-KB-ServiceRole-<random>` (many)

Keep: `irkb-docs-<ACCOUNT_ID>`, `irkb-role`, `irkb-vs`, `irkb`, `irkb-index`.
