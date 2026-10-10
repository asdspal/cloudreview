import streamlit as st

import agent

st.set_page_config(page_title="CloudReview", page_icon="🔍", layout="centered")

SAMPLES = {
    "Leaky S3 + IAM wildcard": """resource "aws_s3_bucket" "data" { bucket = "my-data" }
resource "aws_s3_bucket_acl" "data" {
  bucket = aws_s3_bucket.data.id
  acl    = "public-read"
}
resource "aws_iam_policy" "p" {
  policy = jsonencode({
    Statement = [{ Effect = "Allow", Action = "*", Resource = "*" }]
  })
}""",
    "Open SSH security group": """resource "aws_security_group" "ssh" {
  name = "ssh"
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}""",
}


def score_badge(score):
    if score is None:
        return
    if score >= 80:
        color, label = "#1a7f37", f"🟢 {score}/100 - looks production-ready"
    elif score >= 50:
        color, label = "#9a6700", f"🟡 {score}/100 - needs work"
    else:
        color, label = "#cf222e", f"🔴 {score}/100 - do not ship this"
    st.markdown(
        f"""<div style="padding:0.6rem 1rem;border-radius:8px;background:{color};
        color:white;font-weight:600;display:inline-block">Trust score: {label}</div>""",
        unsafe_allow_html=True,
    )


def render_sources(trace):
    if not trace:
        return
    with st.expander(f"🔎 Grounded in {len(trace)} knowledge-base lookup(s)"):
        for t in trace:
            st.markdown(f"- searched: `{t['query']}` ({t['chars']} chars of rules)")


# ---- sidebar ----
with st.sidebar:
    st.header("Try an example")
    for name, snippet in SAMPLES.items():
        if st.button(name, use_container_width=True):
            st.session_state.pending = snippet
    if st.button("Reset chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
    st.divider()
    st.caption("CloudReview reviews IaC against a Bedrock Knowledge Base of AWS "
               "best-practice rules, then returns a trust score and copy-paste fixes.")
    st.divider()
    u = agent.usage()
    st.markdown("**Usage this run**")
    st.caption(f"{u['calls']}/{agent.MAX_TOTAL} model calls · "
               f"limit {agent.MAX_PER_MIN}/min")
    st.caption(f"~{u['inputTokens']:,} in / {u['outputTokens']:,} out tokens · "
               f"est ${u['estCostUsd']:.4f}")

# ---- header ----
st.title("🔍 CloudReview")
st.caption("Paste your Terraform, CloudFormation, CDK, or AWS CLI. Get a trust score "
           "and fixes in plain English. Ask follow-ups like a colleague.")

if "messages" not in st.session_state:
    st.session_state.messages = []

# ---- replay history ----
for m in st.session_state.messages:
    if m["role"] == "assistant":
        score_badge(agent.extract_score(m["text"]))
    with st.chat_message(m["role"]):
        st.markdown(m["text"])
        if m["role"] == "assistant":
            render_sources(m.get("trace"))

if not st.session_state.messages:
    st.info("No IaC yet. Load an example on the left, or paste your own below.")

prompt = st.chat_input("Paste IaC or ask a question...")
if not prompt and st.session_state.get("pending"):
    prompt = st.session_state.pop("pending")

if prompt:
    st.session_state.messages.append({"role": "user", "text": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    history = [{"role": m["role"], "content": [{"text": m["text"]}]}
               for m in st.session_state.messages]
    trace = []
    with st.chat_message("assistant"):
        with st.spinner("Reading your IaC and checking it against the rulebook..."):
            try:
                raw, _ = agent.respond(history, trace=trace)
                text = agent.strip_thinking(raw)
            except RuntimeError as e:
                text = f"⏳ {e}"
                trace = []
            except Exception as e:
                text = (f"Hit a snag calling the model: `{type(e).__name__}`. "
                        "Your snippet is unchanged - try again, or use a smaller one.")
                trace = []
        score_badge(agent.extract_score(text))
        st.markdown(text)
        render_sources(trace)
    st.session_state.messages.append({"role": "assistant", "text": text, "trace": trace})
