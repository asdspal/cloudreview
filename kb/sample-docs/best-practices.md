# AWS Infrastructure-as-Code Review Best Practices

Reference rules for reviewing Terraform / CloudFormation / CDK / AWS CLI.

## Security

### S3 buckets
- Block public access: set `block_public_acls`, `block_public_policy`,
  `ignore_public_acls`, `restrict_public_buckets` to true. A bucket with a public
  policy can leak data to the internet.
- Enable default encryption (`AES256` or `aws:kms`).
- Enable versioning for recovery.

### IAM
- Never use `Action: "*"` with `Resource: "*"` in customer policies.
- Do not create access keys for the root user; enable MFA on root.
- Scope policies to specific ARNs.

### Encryption
- Encrypt RDS/EBS/S3 with KMS (customer-managed keys preferred).
- Reject unencrypted storage unless explicitly justified.

## Cost
- Delete idle load balancers, unattached EBS volumes, and old snapshots.
- Right-size over-provisioned instances; use Graviton where possible.
- Use S3 lifecycle policies to move cold data to cheaper tiers.

## Operational rigor
- Tag all resources (owner, environment, cost-center).
- Enable CloudTrail and CloudWatch alarms for critical resources.
- Set termination protection on stateful resources.
